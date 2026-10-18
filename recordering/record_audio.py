"""
Cross-platform bit-exact capture for the UsbMicrophone UAC2 device -- one script for Windows and Linux.

Both backends bypass every host-side mixer/converter, so the WAV holds exactly what the device sent:
  - Windows: WASAPI EXCLUSIVE mode via pycaw/comtypes (same path as check_usb_audio_exclusive.py --
    no mixer engine, no APO enhancement chain, see HostAudioCapture.md).
  - Linux:   ALSA `hw:` device via `arecord` (alsa-utils) -- the ALSA equivalent of exclusive mode,
    no plug/dmix/PulseAudio/PipeWire conversion in between.

Channel count, sample rate and sample width are taken from what the device itself reports, so the same
command works for the PCM firmware (16-bit) and the raw-PDM firmware ("MicNode-RawPDM", 32-bit), and
for the 4-channel Tests/TinyusbUsbMicrophone4Elements bring-up firmware.

Setup (one-time):
    Windows: pip install pycaw comtypes
    Linux:   sudo apt install alsa-utils      (usually preinstalled)

Usage:
    python record_audio.py [-n NAME_FILTER] [-d DURATION] [-o OUT.wav] [-c SYNC_CHANNEL]
                           [--bits 16|32] [--verify-pattern] [-b BUFFER_MS]

    -n/--name-filter  Case-insensitive substring of the device name. Default: "MicNode".
                       Windows: matched against the recording device's friendly name.
                       Linux: matched against the ALSA card id/name (`cat /proc/asound/cards`).
    -d/--duration     Capture length, seconds. Default: 3.
    -o/--out          Output WAV path (same channel count and sample width as the device).
                       Default: "capture.wav". Pass "" to skip writing.
    -c/--sync-channel 0-based sync-counter channel to check for continuity. Default: the last channel
                       (ch4 on the real 5-channel firmware, ch3 on the 4-channel bring-up firmware).
    --bits            Force the sample width instead of taking the device's own (16 = PCM firmware,
                       32 = raw-PDM firmware).
    --verify-pattern  32-bit only: bit-exact check of the firmware's raw-PDM test pattern
                       (rawPdmSendsTestPattern in UsbMicrophone/main.cpp).
    -b/--buffer-ms    Windows only: exclusive-mode engine buffer/period, ms. Default: 20.

Besides the sync-counter check, the script reports host-side overruns (WASAPI DATA_DISCONTINUITY
flag / ALSA "overrun!!!") -- frames lost on the host, not by the device.
"""

import argparse
import array
import ctypes
import re
import struct
import subprocess
import sys
import time
import wave

if sys.platform == "win32":
    import warnings

    warnings.filterwarnings("ignore")

    from comtypes import CLSCTX_ALL, COMMETHOD, GUID, HRESULT, IUnknown
    from ctypes import POINTER, c_uint32, c_uint64
    from ctypes.wintypes import BYTE, DWORD

    from pycaw.api.audioclient import IAudioClient
    from pycaw.api.audioclient.depend import WAVEFORMATEX
    from pycaw.utils import AudioUtilities

    class IAudioCaptureClient(IUnknown):
        _iid_ = GUID("{C8ADBD64-E71E-48a0-A4DE-185C395CD317}")
        _methods_ = (
            COMMETHOD(
                [], HRESULT, "GetBuffer",
                (["out"], POINTER(POINTER(BYTE)), "ppData"),
                (["out"], POINTER(c_uint32), "pNumFramesToRead"),
                (["out"], POINTER(DWORD), "pdwFlags"),
                (["out"], POINTER(c_uint64), "pu64DevicePosition"),
                (["out"], POINTER(c_uint64), "pu64QPCPosition"),
            ),
            COMMETHOD([], HRESULT, "ReleaseBuffer", (["in"], c_uint32, "NumFramesRead")),
            COMMETHOD([], HRESULT, "GetNextPacketSize", (["out"], POINTER(c_uint32), "pNumFramesInNextPacket")),
        )

AUDCLNT_SHAREMODE_EXCLUSIVE = 1
AUDCLNT_STREAMFLAGS_EVENTCALLBACK = 0x00040000
# audioclient.h _AUDCLNT_BUFFERFLAGS
AUDCLNT_BUFFERFLAGS_DATA_DISCONTINUITY = 0x1
AUDCLNT_BUFFERFLAGS_SILENT = 0x2
AUDCLNT_E_BUFFER_SIZE_NOT_ALIGNED = -2004287463  # 0x88890019 as signed HRESULT
REFTIMES_PER_SEC = 10_000_000
WAIT_OBJECT_0 = 0

WAVE_FORMAT_EXTENSIBLE = 0xFFFE
# {00000001-0000-0010-8000-00AA00389B71} KSDATAFORMAT_SUBTYPE_PCM
SUBTYPE_PCM_TAIL = bytes([0x80, 0x00, 0x00, 0xAA, 0x00, 0x38, 0x9B, 0x71])


# ---------------------------------------------------------------- Windows: WASAPI exclusive

def find_wasapi_device(name_filter):
    devices = AudioUtilities.GetAllDevices()
    matches = [d for d in devices if name_filter.lower() in (d.FriendlyName or "").lower() and str(d.state) == "AudioDeviceState.Active"]
    if not matches:
        print(f"No active recording device matching {name_filter!r} found. All devices:")
        for d in devices:
            print(" ", d.id, "|", d.FriendlyName, "|", d.state)
        sys.exit(1)
    if len(matches) > 1:
        print(f"Multiple active devices matched {name_filter!r}, using the first:")
        for d in matches:
            print(" ", d.id, "|", d.FriendlyName)
    return matches[0]


def make_pcm_format_extensible(nchannels, samplerate, bits):
    """Build a raw WAVEFORMATEXTENSIBLE byte buffer (mmreg.h packing, no ctypes padding).

    Multichannel (>2ch) exclusive-mode streams generally require WAVEFORMATEXTENSIBLE --
    plain WAVEFORMATEX with WAVE_FORMAT_PCM gets rejected (AUDCLNT_E_UNSUPPORTED_FORMAT).
    """
    block_align = nchannels * bits // 8
    base = struct.pack(
        "<HHIIHHH",
        WAVE_FORMAT_EXTENSIBLE, nchannels, samplerate, samplerate * block_align, block_align, bits, 22,
    )
    tail = struct.pack("<HI", bits, 0) + struct.pack("<IHH", 1, 0, 0x0010) + SUBTYPE_PCM_TAIL
    raw = base + tail
    assert len(raw) == 40, len(raw)
    buf = ctypes.create_string_buffer(raw, len(raw))
    return buf, ctypes.cast(buf, POINTER(WAVEFORMATEX))


def capture_windows(args):
    target = find_wasapi_device(args.name_filter)
    print(f"Using device: {target.FriendlyName} ({target.id})")
    dev = target._dev

    def activate():
        return dev.Activate(IAudioClient._iid_, CLSCTX_ALL, None).QueryInterface(IAudioClient)

    # The shared mix format is queried only to learn the channel count/rate the driver reports.
    mix = activate().GetMixFormat().contents
    nchannels, samplerate = mix.nChannels, mix.nSamplesPerSec
    print(f"Device reports {nchannels} channels @ {samplerate} Hz")

    # The device exposes a single native width (16 in PCM firmware, 32 in raw-PDM firmware): probe it.
    client = activate()
    for bits in ([args.bits] if args.bits else [16, 32]):
        fmt_buf, fmt_ptr = make_pcm_format_extensible(nchannels, samplerate, bits)
        try:
            client.IsFormatSupported(AUDCLNT_SHAREMODE_EXCLUSIVE, fmt_ptr)
            break
        except Exception as e:
            print(f"Exclusive {bits}-bit PCM not supported: {e}")
    else:
        sys.exit("The device accepts none of the tried exclusive-mode formats. Aborting.")
    print(f"Exclusive-mode {bits}-bit PCM (extensible) format is supported by the device.")

    def initialize(client, duration):
        client.Initialize(AUDCLNT_SHAREMODE_EXCLUSIVE, AUDCLNT_STREAMFLAGS_EVENTCALLBACK,
                          duration, duration, fmt_ptr, None)

    try:
        initialize(client, int(args.buffer_ms * 10000))
    except Exception as e:
        if getattr(e, "hresult", None) != AUDCLNT_E_BUFFER_SIZE_NOT_ALIGNED:
            sys.exit(f"Initialize (exclusive) FAILED: {e}")
        print("Buffer size not aligned, retrying with engine-reported aligned size...")
        num_frames = client.GetBufferSize()
        client = activate()
        initialize(client, int(REFTIMES_PER_SEC * num_frames / samplerate + 0.5))

    buf_frames = client.GetBufferSize()
    print(f"Engine buffer size: {buf_frames} frames ({buf_frames / samplerate * 1000:.2f}ms)")

    kernel32 = ctypes.windll.kernel32
    event_handle = kernel32.CreateEventW(None, False, False, None)
    if not event_handle:
        sys.exit("CreateEventW failed")
    client.SetEventHandle(event_handle)

    capture = client.GetService(IAudioCaptureClient._iid_).QueryInterface(IAudioCaptureClient)
    client.Start()
    print(f"Capturing (WASAPI exclusive, event-driven) for {args.duration}s...")

    frame_size = nchannels * bits // 8
    chunks, discontinuities, npackets = [], [], 0
    t_end = time.time() + args.duration
    while time.time() < t_end:
        wait_ms = max(int((t_end - time.time()) * 1000), 0) + 500
        if kernel32.WaitForSingleObject(event_handle, wait_ms) != WAIT_OBJECT_0:
            break
        while capture.GetNextPacketSize():
            data_ptr, num_frames, flags, dev_pos, qpc_pos = capture.GetBuffer()
            if num_frames > 0:
                # The first packet after Start() normally carries DATA_DISCONTINUITY -- not a loss.
                if flags & AUDCLNT_BUFFERFLAGS_DATA_DISCONTINUITY and npackets > 0:
                    discontinuities.append(f"packet {npackets} (device position {dev_pos})")
                if flags & AUDCLNT_BUFFERFLAGS_SILENT:
                    chunks.append(bytes(num_frames * frame_size))
                else:
                    chunks.append(ctypes.string_at(data_ptr, num_frames * frame_size))
                npackets += 1
            capture.ReleaseBuffer(num_frames)

    client.Stop()
    kernel32.CloseHandle(event_handle)
    return b"".join(chunks), nchannels, samplerate, bits, discontinuities


# ---------------------------------------------------------------- Linux: ALSA hw: via arecord

def find_alsa_card(name_filter):
    """-> (card index, card id) of the first /proc/asound/cards entry matching name_filter."""
    with open("/proc/asound/cards") as f:
        cards = [m.groups() for m in re.finditer(r"^\s*(\d+)\s+\[(\S+)\s*\]:\s*(.*)$", f.read(), re.M)]
    matches = [c for c in cards if name_filter.lower() in f"{c[1]} {c[2]}".lower()]
    if not matches:
        print(f"No ALSA card matching {name_filter!r} found. All cards:")
        for c in cards:
            print(f"  {c[0]} [{c[1]}] {c[2]}")
        sys.exit(1)
    if len(matches) > 1:
        print(f"Multiple ALSA cards matched {name_filter!r}, using the first:")
        for c in matches:
            print(f"  {c[0]} [{c[1]}] {c[2]}")
    return int(matches[0][0]), matches[0][1]


def alsa_capture_format(card):
    """Capture format the USB device declares, from snd-usb-audio's stream0: (nchannels, rate, bits)."""
    path = f"/proc/asound/card{card}/stream0"
    try:
        with open(path) as f:
            text = f.read()
    except OSError:
        sys.exit(f"{path} not found -- card {card} is not a USB audio device?")
    if "Capture:" not in text:
        sys.exit(f"Card {card} has no capture stream:\n{text}")
    section = text.split("Capture:", 1)[1].split("Playback:", 1)[0]
    fmt = re.search(r"Format:\s*(\S+)", section).group(1)
    nchannels = int(re.search(r"Channels:\s*(\d+)", section).group(1))
    rates = [int(r) for r in re.findall(r"\d+", re.search(r"Rates:\s*(.*)", section).group(1))]
    bits = {"S16_LE": 16, "S32_LE": 32}.get(fmt)
    if bits is None:
        sys.exit(f"Unsupported capture format {fmt} (expected S16_LE or S32_LE)")
    return nchannels, 48000 if 48000 in rates else rates[0], bits


def capture_linux(args):
    card, card_id = find_alsa_card(args.name_filter)
    nchannels, samplerate, bits = alsa_capture_format(card)
    if args.bits:
        bits = args.bits
    device = f"hw:CARD={card_id},DEV=0"
    print(f"Using device: {device} (card {card}), {nchannels} channels @ {samplerate} Hz, {bits}-bit")

    nframes = int(round(args.duration * samplerate))
    cmd = ["arecord", "-D", device, "-c", str(nchannels), "-r", str(samplerate),
           "-f", f"S{bits}_LE", "-t", "raw", "-s", str(nframes)]
    print(f"Capturing (ALSA hw, arecord) for {args.duration}s...")
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError:
        sys.exit("arecord not found -- install alsa-utils (sudo apt install alsa-utils)")
    stderr = proc.stderr.decode(errors="replace")
    if proc.returncode != 0:
        print(stderr)
        if "busy" in stderr.lower():
            print("The device is held by another process (PulseAudio/PipeWire?). Free it, e.g.:\n"
                  "  pactl list cards short; pactl set-card-profile <card> off")
        sys.exit(f"arecord failed (exit code {proc.returncode})")
    # arecord reports xruns as "overrun!!! (at least N ms long)"; the "!!!" survives localization.
    overruns = [line.strip() for line in stderr.splitlines() if "!!!" in line]
    return proc.stdout, nchannels, samplerate, bits, overruns


# ---------------------------------------------------------------- common analysis

def analyze_counter(pcm, nchan, sync_channel):
    ch = pcm[sync_channel::nchan]
    start = next((i for i, v in enumerate(ch) if v != 0), None)
    if start is None:
        print("Sync channel is all-zero, nothing to analyze.")
        return
    ch = ch[start:]
    print(f"Analyzing {len(ch)} frames of channel {sync_channel} (skipped {start} leading silent frames)")

    # Step is compared modulo 2^16 and may be +1 or -1: the real firmware sends an int16 triangle wave
    # (-1 on the descending half), Tests/TinyusbUsbMicrophone4Elements a wrapping uint16 counter (+1 only).
    anomalies = []
    prev = ch[0]
    for i in range(1, len(ch)):
        cur = ch[i]
        delta = (cur - prev) & 0xFFFF
        if delta not in (1, 0xFFFF):
            anomalies.append((i, prev & 0xFFFF, cur & 0xFFFF, delta - 0x10000 if delta & 0x8000 else delta))
        prev = cur

    print(f"Anomalies (delta != +-1): {len(anomalies)}")
    for a in anomalies[:60]:
        print(f"  frame {a[0]}: {a[1]:#06x} -> {a[2]:#06x} (delta={a[3]:+d})")
    if not anomalies:
        print("  Clean: counter stepped by exactly +-1 every frame, no gaps/duplicates.")


def verify_test_pattern(pcm, nchan):
    """Check the raw-PDM test pattern: every frame's ch0..ch3 must be exact functions of ch0 = n,
    and n must step by exactly 1 per frame. Exercises all 32 bits of every mic slot."""
    if nchan < 4:
        print(f"Test pattern needs at least 4 channels, device has {nchan}.")
        return
    nframes = len(pcm) // nchan
    # The stream may start with a few all-zero frames before the device FIFO fills - not part of the pattern.
    start = 0
    while start < nframes and not any(pcm[start * nchan:(start + 1) * nchan]):
        start += 1
    print(f"Test pattern: skipped {start} leading all-zero frames")
    relation_errors = []
    step_errors = []
    prev = None
    for i in range(start, nframes):
        n, c1, c2, c3 = (pcm[i * nchan + c] & 0xFFFFFFFF for c in range(4))
        if c1 != (~n & 0xFFFFFFFF) or c2 != (n * 0x9E3779B1) & 0xFFFFFFFF or c3 != ((n << 16) | (n >> 16)) & 0xFFFFFFFF:
            relation_errors.append((i, n, c1, c2, c3))
        if prev is not None and n != (prev + 1) & 0xFFFFFFFF:
            step_errors.append((i, prev, n))
        prev = n
    print(f"Test pattern: {nframes - start} frames, {len(relation_errors)} frames with corrupted bits, "
          f"{len(step_errors)} counter discontinuities (dropped/duplicated frames)")
    for i, n, c1, c2, c3 in relation_errors[:20]:
        print(f"  frame {i}: n={n:#010x} ch1={c1:#010x} ch2={c2:#010x} ch3={c3:#010x}")
    for i, a, b in step_errors[:20]:
        print(f"  frame {i}: n {a:#010x} -> {b:#010x}")
    if not relation_errors and not step_errors:
        print("  Clean: all 32 bits of every mic slot arrived bit-exact, no gaps.")


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-n", "--name-filter", default="MicNode")
    parser.add_argument("-d", "--duration", type=float, default=3.0)
    parser.add_argument("-o", "--out", default="capture.wav")
    parser.add_argument("-c", "--sync-channel", type=int, default=None)
    parser.add_argument("--bits", type=int, choices=(16, 32), default=None)
    parser.add_argument("--verify-pattern", action="store_true")
    parser.add_argument("-b", "--buffer-ms", type=float, default=20.0)
    return parser.parse_args()


def main():
    args = parse_args()
    if sys.platform == "win32":
        raw, nchannels, samplerate, bits, host_losses = capture_windows(args)
    elif sys.platform.startswith("linux"):
        raw, nchannels, samplerate, bits, host_losses = capture_linux(args)
    else:
        sys.exit(f"Unsupported platform {sys.platform!r} (Windows and Linux only)")

    pcm = array.array("h" if bits == 16 else "i")
    assert pcm.itemsize == bits // 8
    pcm.frombytes(raw[:len(raw) - len(raw) % (pcm.itemsize * nchannels)])
    total_frames = len(pcm) // nchannels
    print(f"\nTotal frames captured: {total_frames} ({total_frames / samplerate:.2f}s)")
    if total_frames == 0:
        print("No data arrived at all.")
        return

    if host_losses:
        print(f"WARNING: {len(host_losses)} host-side overrun(s) -- frames lost on the host, not by the device:")
        for loss in host_losses[:20]:
            print(f"  {loss}")
    else:
        print("Host-side overruns: none")

    if args.out:
        with wave.open(args.out, "wb") as wav:
            wav.setnchannels(nchannels)
            wav.setsampwidth(bits // 8)
            wav.setframerate(samplerate)
            wav.writeframes(pcm.tobytes())
        print(f"Wrote {total_frames} frames ({nchannels} channels, {bits}-bit PCM) to {args.out}")

    if args.verify_pattern:
        verify_test_pattern(pcm, nchannels)
    analyze_counter(pcm, nchannels, nchannels - 1 if args.sync_channel is None else args.sync_channel)


if __name__ == "__main__":
    main()
