"""
Host-side sanity check for the UsbMicrophone UAC2 device on Windows.

Bypasses Audacity/ffmpeg/PortAudio entirely and talks to Windows' Core Audio
(WASAPI) API directly via pycaw/comtypes, because those higher-level tools
either cap capture at 2 channels (Audacity's MME/DirectSound backends,
PortAudio's MME/DirectSound host APIs) or fail to enumerate this device at
all (PortAudio's WASAPI host API silently drops it, even though the Windows
Core Audio endpoint itself is healthy). This script mirrors exactly what
those tools would do at the WASAPI level (GetMixFormat -> Initialize ->
Start -> read packets) with no aggregation/downmixing in the way, so it is
the ground truth for "is USB audio data actually arriving".

Setup (one-time):
    pip install pycaw comtypes

Usage:
    python Tools/check_usb_audio.py [-n NAME_FILTER] [-d DURATION] [-o OUT.wav]

    -n/--name-filter  Case-insensitive substring to match against the Windows
                       recording device's friendly name. Default: "MicNode"
                       (matches the device's iProduct string). This also
                       matches the Tests/TinyusbUsbMicrophone4Elements* bring-up
                       firmwares' product string ("MicNode_4_Ch") via substring,
                       so no change is needed to point this script at those --
                       the script auto-adapts to whatever channel count and
                       sample format the connected device actually reports (no
                       assumption of exactly 5 channels or a sync-counter
                       channel; that per-frame printout only appears for
                       5-channel devices). If the device was recently
                       re-plugged after a firmware/descriptor change, Windows
                       may register it as "USB Audio 2.0" instead until the
                       endpoint is fully refreshed -- try that as the filter
                       if the default finds nothing, or just pass a shorter
                       substring like "Audio".
    -d/--duration     How long to capture, in seconds. Default: 3.
    -o/--out          Where to write the captured audio as a 16-bit PCM WAV
                       file, with as many channels as the connected device
                       reports (openable directly in Audacity, which
                       shows each channel as its own track even though it
                       can't *record* more than 2 channels live). Default:
                       "capture.wav" in the current directory. Samples are
                       downconverted from the engine's native format (see
                       "sample_type" in the printed MixFormat) to 16-bit PCM,
                       matching the device's own native bit depth
                       (CFG_TUD_AUDIO_FUNC_1_N_BYTES_PER_SAMPLE_TX=2), so this
                       loses nothing beyond what Windows' shared-mode engine
                       already reintroduced by upconverting to float32/int32.
                       Pass "" (empty string) to skip writing a file and only
                       print the diagnostics.

What to look for in the output:
    - "MixFormat" line: nChannels should be 5 (4 mics + sync counter) and
      nSamplesPerSec 48000. If this section throws AUDCLNT_E_UNSUPPORTED_FORMAT
      (hex 0x88890008), Windows has a stale cached format for this endpoint
      GUID from an earlier (broken) firmware iteration -- fully remove the
      device in Device Manager and re-plug it (a different USB port forces a
      fresh enumeration) before re-running this script.
    - "padding" trace: this is how many audio frames are actually sitting in
      the engine's capture buffer, sampled every 0.2s. If it stays at 0 for
      the whole capture, no isochronous data is reaching the OS at all --
      that's a firmware/USB-transport problem, not a channel-count/tool
      limitation.
    - Per-frame dump: channel index 4 (0-based) is the diagnostic sync
      counter (see CLAUDE.md / ROADMAP.md step 3) -- it should visibly
      increment frame-to-frame regardless of any acoustic signal on the
      mics, since it's driven by the DMA/CIC production side, not USB
      packet boundaries. This is the most reliable "is the pipeline alive"
      check: it doesn't require making noise near the microphones.
    - Channels 0-3 are the mic audio channels; the script auto-detects
      int vs float32 from the mix format's SubFormat GUID ("sample_type"
      in the MixFormat line) and decodes accordingly.
"""

import argparse
import array
import ctypes
import struct
import sys
import time
import wave
import warnings

warnings.filterwarnings("ignore")

from comtypes import CLSCTX_ALL, COMMETHOD, GUID, HRESULT, IUnknown
from ctypes import POINTER, c_uint32, c_uint64
from ctypes.wintypes import BYTE, DWORD

from pycaw.api.audioclient import IAudioClient
from pycaw.utils import AudioUtilities

AUDCLNT_SHAREMODE_SHARED = 0
AUDCLNT_BUFFERFLAGS_SILENT = 0x1
REFTIMES_PER_SEC = 10_000_000


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


def find_device(name_filter):
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


def subformat_name(fmt_ptr):
    if fmt_ptr.contents.cbSize < 22:
        return "unknown (not WAVEFORMATEXTENSIBLE)"

    # Real Win32 WAVEFORMATEX is 18 bytes with no trailing pad (mmreg.h packs it tighter than
    # ctypes' default natural alignment, which inserts 2 phantom bytes after cbSize) -- read the
    # extensible tail by raw byte offset instead of casting through a ctypes.Structure, or the
    # SubFormat GUID comes out shifted by 2 bytes and compares equal to nothing.
    raw = ctypes.string_at(ctypes.addressof(fmt_ptr.contents), 18 + 2 + 4 + 16)
    subfmt_data1 = struct.unpack_from("<I", raw, 18 + 2 + 4)[0]
    if subfmt_data1 == 0x00000003:
        return "float32"
    if subfmt_data1 == 0x00000001:
        return "int (PCM)"
    return f"unknown subformat (Data1=0x{subfmt_data1:08x})"


def to_int16(buf, n_values, sample_kind, bits):
    """Downconvert a raw packet buffer to 16-bit PCM samples (interleaved, all channels)."""
    out = array.array("h", bytes(2 * n_values))
    if sample_kind == "float32":
        src = array.array("f")
        src.frombytes(buf)
        for i in range(n_values):
            v = src[i]
            if v > 1.0:
                v = 1.0
            elif v < -1.0:
                v = -1.0
            out[i] = int(v * 32767)
    else:
        src = array.array("i")
        src.frombytes(buf)
        shift = max(bits - 16, 0)
        for i in range(n_values):
            out[i] = src[i] >> shift
    return out


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-n", "--name-filter", default="MicNode")
    parser.add_argument("-d", "--duration", type=float, default=3.0)
    parser.add_argument("-o", "--out", default="capture.wav")
    return parser.parse_args()


def main():
    args = parse_args()
    name_filter = args.name_filter
    duration = args.duration

    target = find_device(name_filter)
    print(f"Using device: {target.FriendlyName} ({target.id})")

    dev = target._dev
    client = dev.Activate(IAudioClient._iid_, CLSCTX_ALL, None).QueryInterface(IAudioClient)

    try:
        fmt_ptr = client.GetMixFormat()
    except Exception as e:
        print(f"GetMixFormat FAILED: {e}")
        print("This usually means Windows has a stale cached format for this endpoint.")
        print("Fix: remove the device in Device Manager, then unplug/replug (try a different port).")
        sys.exit(1)

    fmt = fmt_ptr.contents
    sample_kind = subformat_name(fmt_ptr)
    print(f"MixFormat: nChannels={fmt.nChannels} nSamplesPerSec={fmt.nSamplesPerSec} "
          f"wBitsPerSample={fmt.wBitsPerSample} sample_type={sample_kind}")

    client.Initialize(AUDCLNT_SHAREMODE_SHARED, 0, REFTIMES_PER_SEC, 0, fmt_ptr, None)
    buf_frames = client.GetBufferSize()
    print(f"Engine buffer size: {buf_frames} frames")

    capture = client.GetService(IAudioCaptureClient._iid_).QueryInterface(IAudioCaptureClient)
    client.Start()
    print(f"Capturing for {duration}s...")

    nchan = fmt.nChannels
    bytes_per_sample = fmt.wBitsPerSample // 8
    frame_size = nchan * bytes_per_sample

    all_packets = []
    t_end = time.time() + duration
    t_start = time.time()
    while time.time() < t_end:
        time.sleep(0.2)
        padding = client.GetCurrentPadding()
        print(f"  t={time.time() - t_start:4.1f}s padding={padding} frames")
        while True:
            packet_len = capture.GetNextPacketSize()
            if packet_len == 0:
                break
            data_ptr, num_frames, flags, dev_pos, qpc_pos = capture.GetBuffer()
            if num_frames > 0:
                all_packets.append((num_frames, flags, ctypes.string_at(data_ptr, num_frames * frame_size)))
            capture.ReleaseBuffer(num_frames)

    client.Stop()

    total_frames = sum(p[0] for p in all_packets)
    nonsilent = sum(1 for p in all_packets if not (p[1] & AUDCLNT_BUFFERFLAGS_SILENT))
    print(f"\nTotal frames captured: {total_frames} in {len(all_packets)} packets "
          f"({nonsilent} non-silent)")

    if total_frames == 0:
        print("No data arrived at all -- USB isochronous transport isn't delivering audio to Windows.")
        return

    if args.out:
        pcm16 = array.array("h")
        for num_frames, flags, buf in all_packets:
            if flags & AUDCLNT_BUFFERFLAGS_SILENT:
                pcm16.extend([0] * (num_frames * nchan))
            else:
                pcm16.extend(to_int16(buf, num_frames * nchan, sample_kind, fmt.wBitsPerSample))
        with wave.open(args.out, "wb") as wav:
            wav.setnchannels(nchan)
            wav.setsampwidth(2)
            wav.setframerate(fmt.nSamplesPerSec)
            wav.writeframes(pcm16.tobytes())
        print(f"Wrote {total_frames} frames ({nchan} channels, 16-bit PCM) to {args.out}")

    for num_frames, flags, buf in all_packets:
        if flags & AUDCLNT_BUFFERFLAGS_SILENT:
            continue
        n_show = min(8, num_frames)
        print(f"\nFirst non-silent packet: {num_frames} frames, showing {n_show}:")
        if sample_kind == "float32":
            vals = struct.unpack_from(f"<{n_show * nchan}f", buf)
        else:
            vals = struct.unpack_from(f"<{n_show * nchan}i", buf)
        for i in range(n_show):
            row = vals[i * nchan:(i + 1) * nchan]
            if nchan >= 5:
                # UsbMicrophone's own 5-channel layout: 4 mics + diagnostic sync counter (ch4).
                print(f"  frame {i}: mics={row[:4]} sync_counter(ch4)={row[4]}")
            else:
                # Other channel counts (e.g. the Tests/TinyusbUsbMicrophone4Elements* bring-up
                # firmwares, which have no sync-counter channel) - just show every channel raw.
                print(f"  frame {i}: channels={row}")
        break
    else:
        print("Every captured packet was flagged silent by the audio engine.")


if __name__ == "__main__":
    main()
