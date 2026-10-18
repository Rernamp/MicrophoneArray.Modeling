# Host-side audio capture

How to record from the UAC2 device on a Windows host for diagnostics. Both tools live in
`Tools/` and talk to Windows' Core Audio (WASAPI) API directly via `pycaw`/`comtypes` — see
`usbmicrophone_host_verification` memory / `Docs/Notes/ROADMAP.md` for why: Audacity, ffmpeg
and PortAudio all fail to record this device correctly (2-channel caps, silent
misdetection, or outright failure to enumerate it), even though the device itself is healthy.

One-time setup:
```bash
pip install pycaw comtypes
```

## Cross-platform: `record_audio.py` (Windows + Linux)

One script, same flags and same WAV on both hosts. Windows: WASAPI exclusive (same path as
`check_usb_audio_exclusive.py`). Linux: ALSA `hw:` device via `arecord` (alsa-utils), the ALSA
equivalent of exclusive mode. Channel count, rate and sample width (16 = PCM firmware,
32 = raw-PDM firmware) are taken from the device, the sync channel defaults to the last one.

```bash
python record_audio.py -d 90 -o recording.wav            # PCM or raw-PDM, whatever is flashed
python record_audio.py -d 3 -o "" --verify-pattern       # raw-PDM test-pattern firmware
```

It also reports host-side overruns (WASAPI `DATA_DISCONTINUITY` / ALSA `overrun!!!`), i.e. frames
lost on the host rather than by the device. On Linux, `Device or resource busy` means
PulseAudio/PipeWire holds the card — switch its profile off (`pactl set-card-profile <card> off`).

## Raw-PDM -> PCM: `pdm_to_pcm.py`

```bash
python pdm_to_pcm.py rawpdm.wav                    # -> rawpdm_pcm.wav: 4 mics + sync, 16-bit @ 48 kHz
python pdm_to_pcm.py rawpdm.wav --bits 32 --rate 96000
```

CIC N=4/R=8 (1.536 MHz -> 192 kHz, same as `analyze_tdoa_rawpdm.py`) + 255-tap FIR with CIC droop
compensation (flat within 0.22 dB to 0.4*rate, >128 dB rejection above 26 kHz at 48 kHz output).
Zero-phase w.r.t. the output grid, so inter-mic delays are kept; at 48 kHz the sync counter is
carried over as ch4, giving the same layout as the PCM firmware. 0 dBFS = all-ones PDM, so a quiet
room sits around -63 dBFS (~20 LSB RMS in 16-bit) — use `--gain-db` or `--bits 32` for quiet material.

## Which tool to use

**Use `check_usb_audio_exclusive.py` for anything where sample-accuracy matters** (dropout
counting, wrap/anomaly checks, anything you'd cite as a measurement). It captures in WASAPI
**exclusive** mode — bit-exact, bypassing Windows' mixer engine and its audio-enhancement APO
chain (loudness equalization, de-click/de-pop filters) entirely. Shared mode was found to
introduce its own host-side corruption independent of the firmware (see the wrap-anomaly
investigation in `Docs/Notes/ROADMAP.md` step 6) — the enhancement chain reacts to specific
sample values/discontinuities and mangles them in ways that look like firmware bugs but
aren't.

Use `check_usb_audio.py` (shared mode) only for a quick "is the device alive and mounted at
all" sanity check — it's simpler to run and doesn't require picking a sync channel, but don't
trust its output for anything quantitative.

## `check_usb_audio_exclusive.py` (preferred)

```bash
python Tools/check_usb_audio_exclusive.py -d 90 -o recording.wav -c 4
```

| Flag | Meaning | Default |
|---|---|---|
| `-d`/`--duration` | Capture length in seconds | 3 |
| `-o`/`--out` | Output 16-bit PCM WAV path | `capture.wav` |
| `-c`/`--sync-channel` | 0-based index of the sync-counter channel to analyze for continuity | 3 |
| `-b`/`--buffer-ms` | Exclusive-mode engine buffer/period (ms). Capture is event-driven, so this trades latency for safety margin, not correctness | device default |
| `-n`/`--name-filter` | Substring match against the Windows device name | `MicNode` |
| `--bits` | `16` = normal PCM firmware mode, `32` = raw-PDM mode (see below). WAV is written at the same width | `16` |
| `--verify-pattern` | 32-bit only: bit-exact check of the firmware's raw-PDM test pattern (`rawPdmSendsTestPattern` in `UsbMicrophone/main.cpp`) | off |

**Raw-PDM mode** (PA0 strapped to GND at boot; device enumerates as `MicNode-RawPDM` under its own
PID): same 5 channels @ 48 kHz, but 32-bit slots — ch0..ch3 each carry one mic's 32 raw PDM bits
for that frame (bit 31 = earliest bit, same channel ↔ mic mapping as PCM mode), ch4 is the same
int16 triangle sync counter, sign-extended. Capture with `--bits 32 -c 4`. Must be exclusive mode:
shared mode converts to float32 (24-bit mantissa) and destroys the low bits. When unpacking, read
the WAV as raw `int32` (not a normalizing audio reader) and byte-swap to big-endian before
`np.unpackbits` (`a.astype('>u4').view(np.uint8)`), or the bit order comes out scrambled.

**`-c` depends on which firmware is flashed:**
- Real `UsbMicrophone` firmware (5 channels: 4 mics + sync counter) → `-c 4`
- `Tests/TinyusbUsbMicrophone4Elements` bring-up firmware (4 channels, CH3 = sync counter) →
  `-c 3` (the default)

The script analyzes the chosen channel for continuity and prints anomalies (`delta != 1`
between consecutive samples). **This naive check floods with false positives on the real
firmware**, because its sync counter is a triangle wave (0 → 65535 → 0 → ...), not a plain
wrapping counter (see `usbmicrophone_wrap_anomaly_resolved` memory) — every descending step
reports `delta=65535` and gets flagged even though it's normal. For a real zero-burst-dropout
count, don't rely on the script's raw anomaly list; instead parse the WAV and count
*contiguous runs of the exact same value* (length ≥ 2) — that's the actual dropout signature
(a burst of duplicated/zeroed frames), not the triangle wave's expected steps. Example:

```python
import wave, array

w = wave.open("recording.wav", "rb")
nch = w.getnchannels()
a = array.array("h"); a.frombytes(w.readframes(w.getnframes()))
vals = a[4::nch]  # channel 4 for the real firmware

start = 0
while start < len(vals) and vals[start] == 0:
    start += 1  # skip leading silence

i = start
while i < len(vals):
    if vals[i] == 0:
        j = i
        while j < len(vals) and vals[j] == 0:
            j += 1
        if j - i >= 2:
            print(f"zero-burst at frame {i}, length {j - i}")
        i = j
    else:
        i += 1
```

## `check_usb_audio.py` (shared mode, quick sanity check only)

```bash
python Tools/check_usb_audio.py -d 3 -o capture.wav
```

| Flag | Meaning | Default |
|---|---|---|
| `-d`/`--duration` | Capture length in seconds | 3 |
| `-o`/`--out` | Output WAV path (pass `""` to skip writing and only print diagnostics) | `capture.wav` |
| `-n`/`--name-filter` | Substring match against the Windows device name | `MicNode` |

What to look for in its output:
- **`MixFormat`**: `nChannels` should be 5, `nSamplesPerSec` 48000. An
  `AUDCLNT_E_UNSUPPORTED_FORMAT` (0x88890008) error means Windows has a stale cached format
  for this endpoint from an earlier firmware iteration — fully remove the device in Device
  Manager and re-plug (a different USB port forces fresh enumeration).
- **`padding` trace**: frames currently sitting in the capture buffer, sampled every 0.2s. If
  it stays at 0 the whole capture, no isochronous data is reaching the OS at all — a
  firmware/USB-transport problem, not a tool limitation.
- **Channel 4** (0-based) is the sync counter — it should visibly increment every frame
  regardless of acoustic input, and is the most reliable "is the pipeline alive" check since
  it doesn't need you to make noise near the mics.

## Gotchas

- If the device was just re-plugged after a firmware/descriptor change, Windows may briefly
  list it as generic "USB Audio 2.0" instead of its product string until the endpoint fully
  refreshes — pass `-n "Audio"` (or another shorter substring) if the default `-n "MicNode"`
  finds nothing.
- Both scripts auto-detect int vs. float32 sample encoding from the WASAPI MixFormat's
  SubFormat GUID — don't assume a fixed sample type when writing your own analysis on top of
  a captured WAV; check what the script actually wrote (both write 16-bit PCM regardless of
  the engine's native transport format, so downstream analysis can always assume 16-bit PCM).
