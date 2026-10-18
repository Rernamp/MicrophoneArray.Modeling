"""
TDOA / direction-of-arrival check for the 4-mic square array, from a RAW-PDM capture.

Input: a 5-channel 32-bit WAV captured in raw-PDM firmware mode
(`check_usb_audio_exclusive.py --bits 32 -c 4`). ch0-3 = 32 raw PDM bits per 48 kHz frame per mic
(bit 31 = earliest), ch4 = int16 triangle sync counter (sign-extended).

Pipeline:
  1. Sync-counter continuity check (any dropped frame would corrupt inter-channel timing).
  2. PDM bits -> +-1 at 1.536 MHz -> 4th-order CIC (R=8) -> 192 kHz, DC removed.
  3. Detect the stimulus events (Tools/tdoa_test_signal.wav: chirp + click, 10 times).
  4. Per event, GCC-PHAT between all 6 mic pairs, band 300 Hz - 12 kHz, sub-sample peak
     via frequency-domain upsampling + parabolic interpolation.
  5. Per-channel arrival times (LS over the 6 pairs, ch0 = 0) - with the source overhead
     (tdoa_top) these ARE the per-channel hardware/acoustic offsets; pass them back as --calib-us.
  6. Least-squares fit of the (calibrated) delays to a plane wave (horizontal slowness vector).
     NOT fitted jointly with an SPI2<->SPI3 offset: the SPI split (near pair vs far pair) lies
     exactly along the 0/180 deg axis, so that offset is indistinguishable from geometry there.

Geometry (user-confirmed 2026-10-03): circle R=20 mm, top view, user at the bottom,
azimuth 0 deg = toward the user, 90 deg = right, 180 deg = away:
      ch3 (MIC4) --- ch2 (MIC3)      far pair  = SPI3
      ch0 (MIC2) --- ch1 (MIC1)      near pair = SPI2

Delay convention: tau(i->j) = t_j - t_i, positive = mic j hears the sound later.

Usage:
    python Tools/analyze_tdoa_rawpdm.py Datasets/doa/tdoa_top.wav --expect-el 90      # -> prints --calib-us
    python Tools/analyze_tdoa_rawpdm.py Datasets/doa/tdoa_000.wav --expect-az 0 --calib-us 0,0.5,6.8,-2.8
"""

import argparse
import sys
import wave

import numpy as np

FS_FRAME = 48000
R_CIC = 8
FS = FS_FRAME * 32 // R_CIC          # 192 kHz after CIC
C_SOUND = 343.0
HALF = 0.020 / np.sqrt(2)            # 14.14 mm
POS = np.array([[-HALF, -HALF],      # ch0 MIC2  near-left
                [+HALF, -HALF],      # ch1 MIC1  near-right
                [+HALF, +HALF],      # ch2 MIC3  far-right
                [-HALF, +HALF]])     # ch3 MIC4  far-left
NAMES = ["ch0/MIC2", "ch1/MIC1", "ch2/MIC3", "ch3/MIC4"]
PAIRS = [(0, 1), (3, 2), (0, 3), (1, 2), (0, 2), (1, 3)]


def load(path):
    with wave.open(path, "rb") as w:
        nch, sw, sr, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    if nch != 5 or sw != 4 or sr != FS_FRAME:
        sys.exit(f"Expected 5ch/32-bit/48k raw-PDM capture, got {nch}ch/{sw*8}-bit/{sr}")
    return np.frombuffer(raw, dtype="<i4").reshape(-1, 5)


def check_sync(sync):
    d = np.diff(sync.astype(np.int64))
    bad = np.nonzero(np.abs(d) != 1)[0]
    return bad


def pdm_to_pcm(words):
    """32 raw bits/frame (bit31 earliest) -> CIC N=4, R=8 -> float at 192 kHz, DC removed."""
    bits = np.unpackbits(words.astype(">u4").view(np.uint8)).astype(np.int64) * 2 - 1
    y = bits
    for _ in range(4):                                   # 4 moving sums of length R (= CIC N=4)
        c = np.concatenate(([0], np.cumsum(y)))
        y = c[R_CIC:] - c[:-R_CIC]
    y = y[::R_CIC].astype(np.float64) / R_CIC ** 4
    return y - y.mean()


def bandpass(x, lo=300.0, hi=12000.0):
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / FS)
    X[(f < lo) | (f > hi)] = 0
    return np.fft.irfft(X, len(x))


def detect_events(x, min_gap_s=0.3):
    env = np.convolve(x * x, np.ones(int(0.002 * FS)) / int(0.002 * FS), mode="same")
    noise = np.median(env)
    thr = noise * 30
    above = env > thr
    on = np.nonzero(above[1:] & ~above[:-1])[0] + 1
    events, last = [], -10 ** 9
    for i in on:
        if i - last > min_gap_s * FS:
            events.append(i)
            last = i
    return events, 10 * np.log10(env.max() / noise)


def gcc_phat(a, b, max_lag_s, up=32):
    """Returns tau = t_b - t_a in seconds (positive: b is later)."""
    n = len(a) + len(b)
    A, B = np.fft.rfft(a, n), np.fft.rfft(b, n)
    f = np.fft.rfftfreq(n, 1 / FS)
    G = B * np.conj(A)
    G /= np.abs(G) + 1e-12
    G[(f < 300) | (f > 12000)] = 0
    cc = np.fft.irfft(G, n * up)
    m = int(max_lag_s * FS * up)
    cc = np.concatenate((cc[-m:], cc[:m + 1]))
    k = int(np.argmax(cc))
    if 0 < k < len(cc) - 1:
        y0, y1, y2 = cc[k - 1], cc[k], cc[k + 1]
        k = k + 0.5 * (y0 - y2) / (y0 - 2 * y1 + y2)
    return (k - m) / (FS * up), cc.max() / (np.sort(cc)[-int(0.0003 * FS * up)] + 1e-12)


def channel_times(taus):
    """LS per-channel arrival times from pair delays, ch0 fixed at 0."""
    A = np.zeros((len(taus), 3)); b = np.zeros(len(taus))
    for k, ((i, j), t) in enumerate(taus.items()):
        if j: A[k, j - 1] += 1
        if i: A[k, i - 1] -= 1
        b[k] = t
    return np.concatenate(([0.0], np.linalg.lstsq(A, b, rcond=None)[0]))


def fit(taus):
    """taus: dict pair -> tau. Model t_i = -(p_i . s) (+ common). s = horizontal slowness [s/m]."""
    rows, rhs = [], []
    for (i, j), t in taus.items():
        dp = POS[j] - POS[i]
        rows.append([-dp[0], -dp[1]])
        rhs.append(t)
    A, b = np.array(rows), np.array(rhs)
    sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    resid = b - A @ sol
    sx, sy = sol
    o = 0.0
    # direction toward the source u = (sin az, -cos az); t_i = -(p_i.u)cos(el)/c => s = u cos(el)/c
    az = np.degrees(np.arctan2(sx, -sy)) % 360
    cos_el = min(np.hypot(sx, sy) * C_SOUND, 1.0)
    return az, np.degrees(np.arccos(cos_el)), o, resid


def expected_taus(az_deg, el_deg=0.0):
    u = np.array([np.sin(np.radians(az_deg)), -np.cos(np.radians(az_deg))]) * np.cos(np.radians(el_deg))
    t = -(POS @ u) / C_SOUND
    return {p: t[p[1]] - t[p[0]] for p in PAIRS}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("wav")
    ap.add_argument("--expect-az", type=float, default=None, help="azimuth you placed the source at, deg")
    ap.add_argument("--expect-el", type=float, default=0.0, help="elevation of the source, deg (90 = above)")
    ap.add_argument("--max-lag-ms", type=float, default=2.0, help="GCC search range (covers SPI offsets)")
    ap.add_argument("--calib-us", default=None,
                    help="per-channel offsets t0,t1,t2,t3 in us (from an overhead recording) to subtract")
    ap.add_argument("--win-ms", type=float, default=3.0, help="analysis window after onset, ms")
    ap.add_argument("--radius-mm", type=float, default=20.0, help="mic circle radius, mm (default 20)")
    args = ap.parse_args()
    POS[:] = np.sign(POS) * args.radius_mm / 1000 / np.sqrt(2)

    data = load(args.wav)
    print(f"{args.wav}: {len(data)} frames ({len(data) / FS_FRAME:.1f} s)")
    bad = check_sync(data[:, 4])
    late_bad = bad[bad > 200]
    print(f"Sync counter: {len(bad)} discontinuities ({len(late_bad)} after the startup transient)")
    if len(late_bad):
        print(f"  WARNING: discontinuities at frames {late_bad[:10]} - timing across them is unreliable")
    start = (bad.max() + 1) if len(bad) and bad.max() < 200 else 0

    pcm = np.stack([pdm_to_pcm(data[start:, ch]) for ch in range(4)])
    bp = np.stack([bandpass(x) for x in pcm])
    rms = np.sqrt((bp ** 2).mean(axis=1))
    print("Band RMS per channel: " + "  ".join(f"{NAMES[i]} {rms[i]:.4f}" for i in range(4)))

    events, snr = detect_events(bp.mean(axis=0))
    print(f"Detected {len(events)} events (peak/noise envelope {snr:.0f} dB)")
    if not events:
        sys.exit("No events found")

    calib = np.zeros(4) if args.calib_us is None else np.array([float(v) for v in args.calib_us.split(",")]) * 1e-6
    pre, win = int(0.0005 * FS), int(args.win_ms / 1000 * FS)
    per_event, fits = [], []
    for e in events:
        seg = bp[:, max(0, e - pre): e + win]
        seg = seg * np.hanning(seg.shape[1])
        taus = {}
        for (i, j) in PAIRS:
            taus[(i, j)], _ = gcc_phat(seg[i], seg[j], args.max_lag_ms / 1000)
            taus[(i, j)] -= calib[j] - calib[i]
        per_event.append(taus)
        fits.append(fit(taus))

    print(f"\nPer-pair delay tau(i->j) = t_j - t_i, microseconds, over {len(events)} events:")
    exp = expected_taus(args.expect_az, args.expect_el) if args.expect_az is not None else None
    hdr = f"  {'pair':<22}{'median':>9}{'std':>8}{'min':>9}{'max':>9}"
    print(hdr + (f"{'expected':>10}" if exp else ""))
    for p in PAIRS:
        v = np.array([t[p] for t in per_event]) * 1e6
        line = f"  {NAMES[p[0]] + ' -> ' + NAMES[p[1]]:<22}{np.median(v):9.2f}{v.std():8.2f}{v.min():9.2f}{v.max():9.2f}"
        if exp:
            line += f"{exp[p] * 1e6:10.2f}"
        print(line)

    ct = np.array([channel_times(t) for t in per_event]) * 1e6
    ct_med = np.median(ct, axis=0)
    print("\nPer-channel arrival time vs ch0 (median over events, us)"
          + (" - after calibration" if args.calib_us else "") + ":")
    print("  " + "  ".join(f"{NAMES[i]} {ct_med[i]:+6.2f}" for i in range(4))
          + f"   -> --calib-us {','.join(f'{v:.2f}' for v in ct_med)}")
    print("  spread over events (std): " + "  ".join(f"{ct[:, i].std():.2f}" for i in range(4)))
    az = np.array([f[0] for f in fits]); el = np.array([f[1] for f in fits])
    res = np.array([np.sqrt(np.mean(f[3] ** 2)) for f in fits]) * 1e6
    az_med = np.degrees(np.angle(np.median(np.cos(np.radians(az))) + 1j * np.median(np.sin(np.radians(az))))) % 360
    print("\nPlane-wave fit (per event, then median):")
    print(f"  azimuth      {az_med:7.1f} deg   (spread {np.std(np.unwrap(np.radians(az))) * 180 / np.pi:.1f} deg;"
          f" meaningless when elevation ~90)")
    print(f"  elevation    {np.median(el):7.1f} deg   (from |slowness|; 0 = in array plane, 90 = overhead)")
    print(f"  fit residual {np.median(res):7.2f} us rms (how well the 6 pairs agree with one plane wave)")

    print("\nPer event:  #   onset_s   az     el    resid_us")
    for k, (e, f) in enumerate(zip(events, fits)):
        print(f"           {k:2d}  {e / FS + start / FS_FRAME:7.3f}  {f[0]:5.1f}  {f[1]:5.1f}  {np.sqrt(np.mean(f[3] ** 2)) * 1e6:7.2f}")


if __name__ == "__main__":
    main()
