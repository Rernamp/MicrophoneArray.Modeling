"""
Convert a RAW-PDM capture into an ordinary PCM WAV.

Input: a 32-bit WAV captured in raw-PDM firmware mode (`record_audio.py` or
`check_usb_audio_exclusive.py --bits 32 -c 4`): ch0-3 = 32 raw PDM bits per 48 kHz frame per mic
(bit 31 = earliest, PDM clock 1.536 MHz), ch4 = int16 triangle sync counter (sign-extended).

Output: PCM WAV, mics on ch0-3 in the same order. At the default 48 kHz the sync counter is carried
over as ch4, sample-aligned with the audio -- the same layout as the PCM firmware, so
check_mic_channel_mapping.py / check_spatial_separation.py / the sync-counter checks read it as is.

Pipeline (per mic channel):
  1. CIC decimator N=4, R=8: 1.536 MHz -> 192 kHz (same filter as analyze_tdoa_rawpdm.py). Computed
     per PDM byte through lookup tables (one byte = one 192 kHz output sample), so memory stays small
     even for long captures.
  2. Linear-phase FIR low-pass + decimation 192 kHz -> --rate. Passband 0.4*rate, stopband from
     0.5*rate (no aliasing into the output band), with the CIC passband droop compensated
     (-0.6 dB at 20 kHz otherwise). Skipped at --rate 192000 (pure CIC output).
  3. DC removed, scaled so that a full-scale PDM stream (all ones) = 0 dBFS, then --gain-db.

Timing: every filter is zero-phase relative to the output grid -- output sample n is centered on the
first PDM bit of frame n (at 48 kHz), identically for all mics, so inter-mic delays are preserved.

Usage:
    python pdm_to_pcm.py rawpdm.wav [-o out.wav] [--rate 48000] [--bits 16|32] [--gain-db 0] [--no-sync]

    -o/--out      Output path. Default: <input>_pcm.wav next to the input.
    --rate        Output sample rate; must divide 192000 (e.g. 16000, 48000, 96000, 192000). Default 48000.
    --bits        Output sample width: 16 (default, readable by every tool here) or 32.
    --gain-db     Gain applied before quantization. Default 0. Clipped samples are reported.
    --mics        Number of PDM mic channels (ch0..). Default 4; the next channel is the sync counter.
    --no-sync     Don't carry the sync counter over (it is only carried at --rate 48000 anyway).
    --note, --meta KEY=VALUE, --meta-file FILE.json
                  User fields added to <MICNODE><USER> (see wav_ixml.py) -- e.g. to fill in what was
                  forgotten at capture time.

iXML: the source's iXML (RECORDING, USER, NOTE) is carried over, a new FILE_UID is assigned, SPEED and
TRACK_LIST describe the output, and <MICNODE><CONVERSION> records the source file (name, FILE_UID,
sha256) and every conversion parameter, gain, per-channel levels and clipping. Needs wav_ixml.py next
to this script.
"""

import argparse
import sys
import wave
from pathlib import Path

import numpy as np

import wav_ixml

FS_FRAME = 48000
BITS_PER_FRAME = 32
FS_PDM = FS_FRAME * BITS_PER_FRAME      # 1.536 MHz
CIC_N = 4
CIC_R = 8                               # = bits per byte, which the lookup-table CIC relies on
FS_CIC = FS_PDM // CIC_R                # 192 kHz
FIR_TAPS = 255
FIR_ATTEN_DB = 90.0
PDM_IDLE_BYTE = 0x55                    # 01010101: zero-mean padding at the stream edges


def cic_luts():
    """CIC N=4/R=8 as one FIR kernel, split into per-byte lookup tables.

    Output sample m is centered on PDM bit 8m: s[m] = sum_p lut_p[byte[m + p]].
    """
    kernel = np.array([1.0])
    for _ in range(CIC_N):
        kernel = np.convolve(kernel, np.ones(CIC_R))
    kernel /= CIC_R ** CIC_N            # unity DC gain: all-ones PDM -> +1.0
    center = (len(kernel) - 1) // 2
    levels = ((np.arange(256)[:, None] >> (7 - np.arange(8))) & 1) * 2 - 1   # MSB = earliest bit
    luts = []
    for p in range(-((center + 7) // 8), (len(kernel) - 1 - center) // 8 + 1):
        k = 8 * p + np.arange(8) + center
        valid = (k >= 0) & (k < len(kernel))
        w = np.zeros(8)
        w[valid] = kernel[k[valid]]
        luts.append((p, levels @ w))
    return luts


def cic_decimate(words, luts):
    """32-bit PDM words (one per 48 kHz frame) -> float samples at 192 kHz."""
    stream = np.ascontiguousarray(words).view("<u4").astype(">u4").view(np.uint8)   # bytes in time order
    lo = -min(p for p, _ in luts)
    hi = max(p for p, _ in luts)
    padded = np.concatenate((np.full(lo, PDM_IDLE_BYTE, np.uint8), stream, np.full(hi, PDM_IDLE_BYTE, np.uint8)))
    out = np.zeros(len(stream))
    for p, lut in luts:
        out += lut[padded[lo + p: lo + p + len(stream)]]
    return out


def design_fir(decim):
    """Kaiser-windowed frequency-sampling low-pass at FS_CIC with inverse-CIC passband."""
    fs_out = FS_CIC / decim
    f_pass, f_stop = 0.4 * fs_out, 0.5 * fs_out
    nfft = 1 << 16
    f = np.fft.rfftfreq(nfft, 1 / FS_CIC)
    x = np.pi * f / FS_PDM
    x[0] = 1e-12
    cic = np.abs(np.sin(CIC_R * x) / (CIC_R * np.sin(x))) ** CIC_N
    transition = np.clip((f_stop - f) / (f_stop - f_pass), 0.0, 1.0)
    desired = (0.5 - 0.5 * np.cos(np.pi * transition)) / cic
    h = np.roll(np.fft.irfft(desired, nfft), FIR_TAPS // 2)[:FIR_TAPS]
    h *= np.kaiser(FIR_TAPS, 0.1102 * (FIR_ATTEN_DB - 8.7))
    return h / h.sum()


def fir_decimate(x, h, decim):
    """Output n = sum_j h[j] * x[decim*n + j - half]: centered on input sample decim*n."""
    half = (len(h) - 1) // 2
    xp = np.concatenate((np.zeros(half), x, np.zeros(half)))
    n_out = len(x) // decim
    out = np.zeros(n_out)
    for j, hj in enumerate(h):
        out += hj * xp[j: j + decim * n_out: decim]
    return out


def load(path, mics):
    with wave.open(str(path), "rb") as w:
        nch, sw, sr, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    if sw != 4 or sr != FS_FRAME or nch < mics:
        sys.exit(f"Expected a 32-bit/48 kHz raw-PDM capture with >= {mics} channels, got {nch}ch/{sw * 8}-bit/{sr} Hz")
    return np.frombuffer(raw, dtype="<i4").reshape(-1, nch)


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("wav", help="raw-PDM WAV (32-bit, 48 kHz frames)")
    p.add_argument("-o", "--out", default=None)
    p.add_argument("--rate", type=int, default=48000)
    p.add_argument("--bits", type=int, choices=(16, 32), default=16)
    p.add_argument("--gain-db", type=float, default=0.0)
    p.add_argument("--mics", type=int, default=4)
    p.add_argument("--no-sync", action="store_true")
    wav_ixml.add_metadata_args(p)
    return p.parse_args()


def main():
    args = parse_args()
    if args.rate <= 0 or FS_CIC % args.rate:
        sys.exit(f"--rate must divide {FS_CIC} (e.g. 16000, 48000, 96000, 192000)")
    decim = FS_CIC // args.rate
    user = wav_ixml.user_fields(args)
    src = Path(args.wav)
    out_path = Path(args.out) if args.out else src.with_name(src.stem + "_pcm.wav")

    data = load(src, args.mics)
    nframes, nch = data.shape
    print(f"{src}: {nframes} frames ({nframes / FS_FRAME:.2f} s), {nch} channels, PDM {FS_PDM / 1e6:.3f} MHz")

    luts = cic_luts()
    h = design_fir(decim) if decim > 1 else None
    print(f"CIC N={CIC_N} R={CIC_R} -> {FS_CIC} Hz"
          + (f", FIR {FIR_TAPS} taps /{decim} -> {args.rate} Hz" if h is not None else " (no FIR stage)"))

    gain = 10 ** (args.gain_db / 20)
    channels, levels = [], []
    for c in range(args.mics):
        x = cic_decimate(data[:, c], luts)
        x -= x.mean()
        if h is not None:
            x = fir_decimate(x, h, decim)
            x -= x.mean()
        x *= gain
        rms_db = 20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-20)
        peak_db = 20 * np.log10(np.abs(x).max() + 1e-20)
        print(f"  ch{c}: RMS {rms_db:7.1f} dBFS   peak {peak_db:7.1f} dBFS")
        channels.append(x)
        levels.append({"index": c, "rms_dbfs": f"{rms_db:.1f}", "peak_dbfs": f"{peak_db:.1f}"})

    full_scale = 2 ** (args.bits - 1) - 1
    dtype = np.int16 if args.bits == 16 else np.int32
    audio = np.stack(channels, axis=1) * full_scale
    clipped = int(np.count_nonzero(np.abs(audio) > full_scale))
    pcm = np.clip(np.round(audio), -full_scale - 1, full_scale).astype(dtype)

    keep_sync = not args.no_sync and nch > args.mics and args.rate == FS_FRAME
    if keep_sync:
        pcm = np.column_stack((pcm, data[:, args.mics].astype(dtype)))

    with wave.open(str(out_path), "wb") as w:
        w.setnchannels(pcm.shape[1])
        w.setsampwidth(args.bits // 8)
        w.setframerate(args.rate)
        w.writeframes(pcm.astype(f"<i{args.bits // 8}").tobytes())

    doc = wav_ixml.parse(wav_ixml.read_ixml(src))
    source_uid = wav_ixml.renew_uid(doc)
    wav_ixml.set_note(doc, args.note)
    wav_ixml.set_format(doc, args.rate, args.bits,
                        [f"ch{c}" for c in range(args.mics)] + (["sync"] if keep_sync else []))
    fir = "none" if h is None else {
        "taps": FIR_TAPS, "decimation": decim, "kaiser_atten_db": FIR_ATTEN_DB,
        "passband_hz": int(0.4 * args.rate), "stopband_hz": int(0.5 * args.rate),
        "cic_droop_compensation": True,
    }
    wav_ixml.set_section(doc, "MICNODE/CONVERSION", {
        "tool": wav_ixml.tool_info(__file__),
        "host": wav_ixml.host_info(),
        "time": wav_ixml.now(),
        "source": {"file": src.name, "file_uid": source_uid, "sha256": wav_ixml.file_sha256(src),
                   "frames": nframes, "channels": nch},
        "pdm_rate_hz": FS_PDM,
        "cic": {"order": CIC_N, "decimation": CIC_R, "output_rate_hz": FS_CIC},
        "fir": fir,
        "output": {"sample_rate": args.rate, "bits": args.bits, "channels": pcm.shape[1], "frames": len(pcm)},
        "gain_db": args.gain_db,
        "full_scale": "all-ones PDM = 0 dBFS",
        "dc_removed": True,
        "alignment": f"output sample n centered on PDM bit {FS_PDM // args.rate}*n (first bit of 48 kHz frame n at 48 kHz)",
        "sync_carried": keep_sync,
        "clipped_samples": clipped,
        "channel": levels,
    })
    if user:
        wav_ixml.update_section(doc, "MICNODE/USER", user)
    wav_ixml.write_ixml(out_path, doc)
    print(f"Wrote {len(pcm)} frames, {pcm.shape[1]} channels "
          f"({args.mics} mics{' + sync counter' if keep_sync else ''}), {args.bits}-bit @ {args.rate} Hz + iXML to {out_path}")
    if clipped:
        print(f"WARNING: {clipped} samples clipped -- lower --gain-db")


if __name__ == "__main__":
    main()
