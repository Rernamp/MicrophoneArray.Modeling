"""
Offline spatial-separation (TDOA) check for the 4-mic linear array (20mm spacing).

Analyzes a WAV file already captured with check_usb_audio_exclusive.py. Locates an
impulsive event (clap/click) shared across mic channels, upsamples a window around it
(FFT zero-padding) for sub-sample time resolution, and cross-correlates adjacent channel
pairs to estimate inter-mic delay in microseconds/samples.

Why upsampling is required: at 20mm spacing and c=343 m/s, the max possible delay between
ADJACENT mics (source exactly in line with the array axis) is only ~58.3us =~2.8 samples
at 48kHz (sample period 20.83us) -- smaller than one sample, so plain integer-lag
cross-correlation can't resolve it.

Recommended test procedure:
  1. In-line (endfire) test: place an impulsive source (finger snap, clicker) directly on
     the array's axis, close to one end. Expect delay to step up ~58.3us (~2.8 samples)
     per adjacent channel pair, monotonically in one direction, independent of distance to
     the source (pure geometry -- it's the same for any point on the axis).
  2. Broadside test: place the source on the perpendicular bisector (equidistant from all
     4 mics). Expect ~0 delay and ~equal RMS on all channels.

Fix/confirm the channel<->physical-mic mapping (ROADMAP.md step 8) BEFORE trusting this --
a channel-ordering bug will produce a TDOA pattern that doesn't match physical geometry.

Usage:
    python Tools/check_spatial_separation.py recording.wav [-c0 0] [--spacing-mm 20] [--speed 343]

    -c0/--first-channel   0-based index of the first (mic 1) audio channel. Default 0.
                          Real UsbMicrophone firmware: channels 0-3 are mics 1-4, channel 4
                          is the sync counter (excluded automatically).
"""

import argparse
import sys
import wave

import numpy as np


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("wav", help="WAV file captured via check_usb_audio_exclusive.py")
    p.add_argument("-c0", "--first-channel", type=int, default=0,
                    help="0-based index of mic-1's channel (default 0)")
    p.add_argument("--mics", type=int, default=4, help="Number of mic channels starting at --first-channel (default 4)")
    p.add_argument("--spacing-mm", type=float, default=20.0, help="Linear array spacing between adjacent mics, mm")
    p.add_argument("--speed", type=float, default=343.0, help="Speed of sound, m/s")
    p.add_argument("--upsample", type=int, default=20, help="FFT upsample factor for sub-sample TDOA (default 20)")
    p.add_argument("--window-ms", type=float, default=8.0, help="Analysis window half-width around the detected impulse, ms")
    return p.parse_args()


def load_wav(path):
    with wave.open(path, "rb") as w:
        nch = w.getnchannels()
        sr = w.getframerate()
        sw = w.getsampwidth()
        if sw != 2:
            print(f"Expected 16-bit PCM, got {sw*8}-bit. Aborting.")
            sys.exit(1)
        raw = w.readframes(w.getnframes())
    data = np.frombuffer(raw, dtype="<i2").astype(np.float64)
    data = data.reshape(-1, nch)
    return data, sr


def find_impulse_center(mic_data, sr):
    """Broadband energy envelope (sum of |x| across mic channels), locate the peak."""
    envelope = np.abs(mic_data).sum(axis=1)
    win = max(int(sr * 0.001), 1)  # 1ms smoothing
    kernel = np.ones(win) / win
    smoothed = np.convolve(envelope, kernel, mode="same")
    return int(np.argmax(smoothed))


def upsampled_xcorr_delay(a, b, sr, upsample):
    """Sub-sample delay (seconds) of b relative to a: positive means b lags a (arrives later)."""
    n = len(a)
    nfft = n * upsample
    A = np.fft.rfft(a, n=n)
    B = np.fft.rfft(b, n=n)
    # Upsample both signals to a common finer grid via zero-padded IFFT.
    a_up = np.fft.irfft(A, n=nfft) * upsample
    b_up = np.fft.irfft(B, n=nfft) * upsample
    corr = np.correlate(b_up, a_up, mode="full")
    lag = np.argmax(corr) - (nfft - 1)
    return lag * (1.0 / (sr * upsample))


def main():
    args = parse_args()
    data, sr = load_wav(args.wav)
    nframes, nch = data.shape
    c0, nm = args.first_channel, args.mics
    if c0 + nm > nch:
        print(f"Requested mic channels [{c0}:{c0+nm}] exceed file's {nch} channels.")
        sys.exit(1)

    mic_data = data[:, c0:c0 + nm]
    print(f"Loaded {nframes} frames @ {sr}Hz, {nch} channels; analyzing mic channels {list(range(c0, c0+nm))}")

    center = find_impulse_center(mic_data, sr)
    half_win = int(sr * args.window_ms / 1000)
    lo, hi = max(0, center - half_win), min(nframes, center + half_win)
    if hi - lo < 32:
        print("Impulse window too short/degenerate -- capture didn't contain a clear transient?")
        sys.exit(1)
    print(f"Impulse detected at frame {center} ({center/sr*1000:.2f}ms); analyzing window [{lo}:{hi}] ({(hi-lo)/sr*1000:.2f}ms)")

    window = mic_data[lo:hi, :] * np.hanning(hi - lo)[:, None]

    print("\nPer-channel RMS in window (proximity/amplitude check):")
    rms = np.sqrt((window ** 2).mean(axis=0))
    for i in range(nm):
        print(f"  mic {c0+i}: RMS={rms[i]:8.1f}")

    print(f"\nPairwise TDOA (adjacent mics, {args.spacing_mm}mm spacing, c={args.speed}m/s):")
    expected_step_us = args.spacing_mm / 1000.0 / args.speed * 1e6
    print(f"  Max possible delay between adjacent mics (in-line source): {expected_step_us:.1f}us "
          f"({expected_step_us / (1e6 / sr):.2f} samples @ {sr}Hz)\n")

    for i in range(nm - 1):
        delay_s = upsampled_xcorr_delay(window[:, i], window[:, i + 1], sr, args.upsample)
        print(f"  mic {c0+i} -> mic {c0+i+1}: delay = {delay_s*1e6:+8.2f} us "
              f"({delay_s*sr:+6.2f} samples)")

    if nm >= 2:
        total_delay_s = upsampled_xcorr_delay(window[:, 0], window[:, -1], sr, args.upsample)
        span_mm = args.spacing_mm * (nm - 1)
        expected_max_us = span_mm / 1000.0 / args.speed * 1e6
        print(f"\n  mic {c0} -> mic {c0+nm-1} (full span, {span_mm}mm): delay = {total_delay_s*1e6:+8.2f} us "
              f"(max possible for in-line source: {expected_max_us:.1f}us)")

    print("\nInterpretation:")
    print("  - Endfire test (source in line with array axis, near one end): delays between")
    print("    ADJACENT pairs should be roughly equal in magnitude and same sign (monotonic")
    print(f"    staircase), each near +/-{expected_step_us:.0f}us, independent of distance to source.")
    print("  - Broadside test (source on the perpendicular bisector): all delays should be")
    print("    near 0us, and RMS should be roughly equal across channels.")
    print("  - If the mapping bug from ROADMAP.md step 8 (ch1/ch2 identical, ch3/ch4 swapped)")
    print("    is still present, expect ch(i)->ch(i+1) delay ~0 for the duplicated pair and a")
    print("    sign/order that doesn't match physical geometry for the swapped pair.")


if __name__ == "__main__":
    main()
