"""
WASAPI EXCLUSIVE-mode capture for the sync-counter wrap-boundary anomaly investigation.

check_usb_audio.py uses shared mode, which goes through Windows' mixer engine and its
audio-enhancement APO chain (loudness equalization, de-click/de-pop filters, etc.). The
current working hypothesis (2026-09-08) is that the anomaly found there -- a duplicated 0
at the counter's raw 0xFFFF->0x0000 wrap, and two skipped values at the 0x7FFF->0x8000
sign-bit-flip midpoint, both period-65536 -- is a HOST-side artifact of that APO chain
reacting to the full-scale-amplitude discontinuity a raw wrapping counter produces when
interpreted as signed 16-bit PCM, not a firmware/USB-transport bug.

Exclusive mode bypasses the mixer and every APO entirely, going straight to the audio
engine/hardware with the device's native format (bit-exact). If this capture shows the
SAME anomaly, the hypothesis is wrong (something upstream of the mixer, i.e. firmware/
TinyUSB/transport, is really dropping/duplicating). If the anomaly disappears here, the
hypothesis is confirmed and the whole thing is a Windows enhancement-chain artifact,
irrelevant to the JUCE app (which will also use exclusive mode).

Usage:
    python Tools/check_usb_audio_exclusive.py [-n NAME_FILTER] [-d DURATION] [-o OUT.wav] [-c CHANNEL]

    -c/--sync-channel  0-based channel index to analyze for counter continuity.
                        Default: 3 (matches Tests/TinyusbUsbMicrophone4Elements's 4-channel
                        bring-up layout, where CH3 carries the free-running sync counter).
                        Use 4 for the real 5-channel UsbMicrophone firmware.
    --bits            16 (default, normal CIC-decoded PCM firmware mode) or 32 (raw-PDM mode:
                        PA0 strapped to GND at boot, device enumerates as "MicNode-RawPDM").
                        In 32-bit mode each mic channel carries that mic's 32 raw PDM bits per
                        frame (bit 31 = earliest bit; unpack with astype('>u4') before
                        np.unpackbits), and the sync channel is the same int16 triangle wave,
                        sign-extended. The WAV is written as 32-bit PCM.
    --verify-pattern  32-bit mode only: check the firmware's raw-PDM test pattern
                        (rawPdmSendsTestPattern in UsbMicrophone/main.cpp) bit-exactly --
                        ch0 = n, ch1 = ~n, ch2 = n * 0x9E3779B1, ch3 = rotl(n, 16).
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
from ctypes import POINTER, c_uint32, c_uint64, c_int64
from ctypes.wintypes import BYTE, DWORD, WORD

from pycaw.api.audioclient import IAudioClient
from pycaw.api.audioclient.depend import WAVEFORMATEX
from pycaw.utils import AudioUtilities

AUDCLNT_SHAREMODE_EXCLUSIVE = 1
AUDCLNT_STREAMFLAGS_EVENTCALLBACK = 0x00040000
AUDCLNT_BUFFERFLAGS_SILENT = 0x1
AUDCLNT_E_BUFFER_SIZE_NOT_ALIGNED = -2004287463  # 0x88890019 as signed HRESULT
AUDCLNT_E_UNSUPPORTED_FORMAT = -2004287488       # 0x88890008 as signed HRESULT
REFTIMES_PER_SEC = 10_000_000
WAVE_FORMAT_PCM = 1

kernel32 = ctypes.windll.kernel32
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 0x102


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


WAVE_FORMAT_EXTENSIBLE = 0xFFFE
# {00000001-0000-0010-8000-00AA00389B71} KSDATAFORMAT_SUBTYPE_PCM
SUBTYPE_PCM_TAIL = bytes([0x80, 0x00, 0x00, 0xAA, 0x00, 0x38, 0x9B, 0x71])


def make_pcm_format_extensible(nchannels, samplerate, bits):
    """Build a raw WAVEFORMATEXTENSIBLE byte buffer (mmreg.h packing, no ctypes padding).

    Multichannel (>2ch) exclusive-mode streams generally require WAVEFORMATEXTENSIBLE --
    plain WAVEFORMATEX with WAVE_FORMAT_PCM gets rejected (AUDCLNT_E_UNSUPPORTED_FORMAT)
    even though the same channel count/rate/depth works fine in the extensible form.
    """
    block_align = nchannels * bits // 8
    avg_bytes_per_sec = samplerate * block_align
    base = struct.pack(
        "<HHIIHHH",
        WAVE_FORMAT_EXTENSIBLE, nchannels, samplerate, avg_bytes_per_sec, block_align, bits, 22,
    )
    tail = struct.pack("<HI", bits, 0) + struct.pack("<IHH", 1, 0, 0x0010) + SUBTYPE_PCM_TAIL
    raw = base + tail
    assert len(raw) == 40, len(raw)
    buf = ctypes.create_string_buffer(raw, len(raw))
    return buf, ctypes.cast(buf, POINTER(WAVEFORMATEX))


def activate_client(dev):
    return dev.Activate(IAudioClient._iid_, CLSCTX_ALL, None).QueryInterface(IAudioClient)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-n", "--name-filter", default="MicNode")
    parser.add_argument("-d", "--duration", type=float, default=4.0)
    parser.add_argument("-o", "--out", default="Tools/wrap_test_capture_exclusive.wav")
    parser.add_argument("-c", "--sync-channel", type=int, default=3)
    parser.add_argument("--bits", type=int, choices=(16, 32), default=16,
                         help="Sample size to open the device with: 16 = PCM mode, 32 = raw-PDM mode.")
    parser.add_argument("--verify-pattern", action="store_true",
                         help="32-bit mode only: verify the firmware's raw-PDM test pattern bit-exactly.")
    parser.add_argument("-b", "--buffer-ms", type=float, default=20.0,
                         help="Exclusive-mode engine buffer/period duration in ms. Capture is "
                              "event-driven (SetEventHandle + WaitForSingleObject), so this "
                              "mainly trades latency for safety margin, not correctness.")
    return parser.parse_args()


def analyze_counter(pcm16, nchan, sync_channel):
    ch = pcm16[sync_channel::nchan]
    start = None
    for i, v in enumerate(ch):
        if v != 0:
            start = i
            break
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
    # The stream starts with a few all-zero frames before the device FIFO fills (same as PCM mode's
    # leading silence) - not part of the pattern.
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


def main():
    args = parse_args()
    target = find_device(args.name_filter)
    print(f"Using device: {target.FriendlyName} ({target.id})")
    dev = target._dev

    # Query the shared mix format only to learn the channel count/rate the driver reports.
    probe = activate_client(dev)
    mix_fmt_ptr = probe.GetMixFormat()
    nchannels = mix_fmt_ptr.contents.nChannels
    samplerate = mix_fmt_ptr.contents.nSamplesPerSec
    print(f"Device reports {nchannels} channels @ {samplerate} Hz (from shared mix format)")

    bits = args.bits
    fmt_buf, fmt_ptr = make_pcm_format_extensible(nchannels, samplerate, bits)
    block_align = nchannels * bits // 8

    client = activate_client(dev)
    try:
        client.IsFormatSupported(AUDCLNT_SHAREMODE_EXCLUSIVE, fmt_ptr)
        print(f"Exclusive-mode {bits}-bit PCM (extensible) format is supported by the device.")
    except Exception as e:
        print(f"IsFormatSupported (exclusive, {bits}-bit PCM extensible) FAILED: {e}")
        print("The device doesn't accept this exact exclusive-mode format. Aborting.")
        sys.exit(1)

    default_period, min_period = client.GetDevicePeriod()
    print(f"Device period: default={default_period/10000:.2f}ms min={min_period/10000:.2f}ms")

    buffer_duration = int(args.buffer_ms * 10000)

    def try_initialize(client, duration):
        return client.Initialize(AUDCLNT_SHAREMODE_EXCLUSIVE, AUDCLNT_STREAMFLAGS_EVENTCALLBACK,
                                  duration, duration, fmt_ptr, None)

    try:
        try_initialize(client, buffer_duration)
    except Exception as e:
        hr = getattr(e, "hresult", None)
        if hr == AUDCLNT_E_BUFFER_SIZE_NOT_ALIGNED:
            print("Buffer size not aligned, retrying with engine-reported aligned size...")
            num_frames = client.GetBufferSize()
            aligned_duration = int(REFTIMES_PER_SEC * num_frames / samplerate + 0.5)
            client = activate_client(dev)
            try_initialize(client, aligned_duration)
        else:
            print(f"Initialize (exclusive) FAILED: {e}")
            sys.exit(1)

    buf_frames = client.GetBufferSize()
    print(f"Engine buffer size: {buf_frames} frames ({buf_frames/samplerate*1000:.2f}ms)")

    event_handle = kernel32.CreateEventW(None, False, False, None)
    if not event_handle:
        print("CreateEventW failed")
        sys.exit(1)
    client.SetEventHandle(event_handle)

    capture = client.GetService(IAudioCaptureClient._iid_).QueryInterface(IAudioCaptureClient)
    client.Start()
    print(f"Capturing (EXCLUSIVE, event-driven) for {args.duration}s...")

    frame_size = block_align
    all_packets = []
    t_end = time.time() + args.duration
    t_start = time.time()
    while time.time() < t_end:
        wait_ms = max(int((t_end - time.time()) * 1000), 0) + 500
        result = kernel32.WaitForSingleObject(event_handle, wait_ms)
        if result != WAIT_OBJECT_0:
            break
        while True:
            packet_len = capture.GetNextPacketSize()
            if packet_len == 0:
                break
            data_ptr, num_frames, flags, dev_pos, qpc_pos = capture.GetBuffer()
            if num_frames > 0:
                all_packets.append((num_frames, flags, ctypes.string_at(data_ptr, num_frames * frame_size)))
            capture.ReleaseBuffer(num_frames)

    client.Stop()
    kernel32.CloseHandle(event_handle)

    total_frames = sum(p[0] for p in all_packets)
    print(f"\nTotal frames captured: {total_frames} in {len(all_packets)} packets, t={time.time()-t_start:.2f}s")

    if total_frames == 0:
        print("No data arrived at all.")
        return

    pcm = array.array("h" if bits == 16 else "i")
    assert pcm.itemsize == bits // 8
    for num_frames, flags, buf in all_packets:
        if flags & AUDCLNT_BUFFERFLAGS_SILENT:
            pcm.extend([0] * (num_frames * nchannels))
        else:
            pcm.frombytes(buf)

    if args.out:
        with wave.open(args.out, "wb") as wav:
            wav.setnchannels(nchannels)
            wav.setsampwidth(bits // 8)
            wav.setframerate(samplerate)
            wav.writeframes(pcm.tobytes())
        print(f"Wrote {total_frames} frames to {args.out}")

    if args.verify_pattern:
        verify_test_pattern(pcm, nchannels)
    analyze_counter(pcm, nchannels, args.sync_channel)


if __name__ == "__main__":
    main()
