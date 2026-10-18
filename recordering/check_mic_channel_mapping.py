"""
Channel<->physical-mic mapping check (ROADMAP.md step 8: ch1/ch2 read identical, ch3/ch4
appear swapped -- not yet root-caused as hardware fault vs. firmware deinterleave bug).

Procedure:
  1. Record one continuous capture while tapping/speaking at each physical mic in turn,
     with a few seconds of silence between each, in a KNOWN order (e.g. mic1, mic2, mic3,
     mic4), everything else silent:
        python Tools/check_usb_audio_exclusive.py -d 20 -o mapping_test.wav -c 4
  2. Run this script on the result. It computes windowed RMS per audio channel and prints
     which channel dominates in each time window, so you can match it against the known
     tapping order and see directly which USB channel each physical mic lands on.

Interpretation:
  - If two channels are literally identical (near-zero difference) throughout, or one
    channel never shows a dominant peak for ANY tap, that's consistent with a dead/HiZ mic
    on that SPI pair (see CLAUDE.md: SPI2 carries mics 1/2 on one shared SD line, PB15) --
    cross-check with a continuity/multimeter check on that mic's SD output pin.
  - If every channel shows a clear, distinct peak for exactly one tap, but the timing lines
    up with the WRONG physical mic in a consistent, repeatable way (e.g. tapping mic3
    always lights up channel 4 and vice versa), that's a deterministic firmware
    channel-ordering bug in the bit-position-parity deinterleave
    (UsbMicrophone/main.cpp / Pdm.cpp), not a hardware fault -- fix the channel index
    mapping there, not the wiring.

Usage:
    python Tools/check_mic_channel_mapping.py mapping_test.wav [-c0 0] [--mics 4] [--window-ms 200]
"""

import argparse
import wave

import numpy as np


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("wav", help="WAV file captured via check_usb_audio_exclusive.py")
    p.add_argument("-c0", "--first-channel", type=int, default=0, help="0-based index of mic-1's channel")
    p.add_argument("--mics", type=int, default=4, help="Number of mic channels starting at --first-channel")
    p.add_argument("--window-ms", type=float, default=200.0, help="RMS window size, ms")
    p.add_argument("--quiet-threshold", type=float, default=150.0,
                    help="RMS below this counts as silence (no dominant channel printed)")
    return p.parse_args()


def load_wav(path):
    with wave.open(path, "rb") as w:
        nch = w.getnchannels()
        sr = w.getframerate()
        sw = w.getsampwidth()
        if sw != 2:
            raise SystemExit(f"Expected 16-bit PCM, got {sw*8}-bit.")
        raw = w.readframes(w.getnframes())
    data = np.frombuffer(raw, dtype="<i2").astype(np.float64).reshape(-1, nch)
    return data, sr


def main():
    args = parse_args()
    data, sr = load_wav(args.wav)
    nframes, nch = data.shape
    c0, nm = args.first_channel, args.mics
    mic_data = data[:, c0:c0 + nm]

    win = max(int(sr * args.window_ms / 1000), 1)
    nwin = nframes // win
    print(f"Loaded {nframes} frames @ {sr}Hz. Analyzing {nwin} windows of {args.window_ms}ms "
          f"across mic channels {list(range(c0, c0+nm))}\n")

    print(f"{'t(s)':>7} | " + " | ".join(f"ch{c0+i:>2}" for i in range(nm)) + " | dominant")
    print("-" * (10 + nm * 7 + 12))

    per_channel_peak = [0.0] * nm
    per_channel_peak_time = [0.0] * nm
    for wi in range(nwin):
        lo, hi = wi * win, (wi + 1) * win
        block = mic_data[lo:hi, :]
        rms = np.sqrt((block ** 2).mean(axis=0))
        t = lo / sr
        dominant_i = int(np.argmax(rms))
        for i in range(nm):
            if rms[i] > per_channel_peak[i]:
                per_channel_peak[i] = rms[i]
                per_channel_peak_time[i] = t
        label = f"ch{c0+dominant_i}" if rms[dominant_i] >= args.quiet_threshold else "-"
        row = " | ".join(f"{v:6.0f}" for v in rms)
        print(f"{t:7.2f} | {row} | {label}")

    print("\nPeak RMS per channel (time of peak):")
    for i in range(nm):
        print(f"  ch{c0+i}: peak={per_channel_peak[i]:8.0f} at t={per_channel_peak_time[i]:.2f}s")

    print("\nNow match each 'dominant' time window against the physical mic you tapped at that")
    print("moment. A channel that never becomes dominant for any tap is suspect (dead/HiZ).")
    print("Two channels dominant at the exact same times/never distinguishable from each other")
    print("suggests one physical mic isn't driving its bit slot (leaking onto both channels).")


if __name__ == "__main__":
    main()
