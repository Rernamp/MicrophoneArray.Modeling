"""
iXML metadata chunk for the WAV files written by record_audio.py and pdm_to_pcm.py.

The chunk is standard iXML (root <BWFXML>, readable by Reaper, Audition, Wavelab, BWF MetaEdit, ...):
  - IXML_VERSION, FILE_UID, NOTE, SPEED (rate/bit depth), TRACK_LIST (channel names)
  - <MICNODE> with this project's sections:
      <RECORDING>   written by record_audio.py (host, device, backend, time, format, sync/overrun checks)
      <CONVERSION>  written by pdm_to_pcm.py (source file, filter parameters, gain, levels)
      <USER>        free fields passed from outside on the command line (array geometry, setup, ...)

User fields (both scripts accept them):
    --note "free text"                 -> <NOTE>
    --meta KEY=VALUE                   repeatable; dots/slashes nest: array.radius_mm=20 ->
                                       <USER><ARRAY><RADIUS_MM>20</RADIUS_MM></ARRAY></USER>
    --meta-file FILE.json              repeatable; nested JSON object, lists become repeated elements:
                                       {"array": {"mic": [{"channel": 0, "x_mm": -14.1}, ...]}} ->
                                       <ARRAY><MIC><CHANNEL>0</CHANNEL>...</MIC><MIC>...</MIC></ARRAY>
    --meta wins over --meta-file for the same key. Tag names are upper-cased (iXML convention).

Run directly to print a file's iXML:
    python wav_ixml.py recording.wav
"""

import argparse
import hashlib
import json
import os
import platform
import re
import socket
import struct
import sys
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

IXML_VERSION = "1.61"


# ---------------------------------------------------------------- building the document

def _tag(name):
    tag = re.sub(r"[^0-9A-Za-z_.-]", "_", str(name)).upper()
    return tag if re.match(r"[A-Z_]", tag) else "_" + tag


def _clean(text):
    """Undo surrogate escapes from a non-UTF-8 locale (argv decoded as ASCII): valid UTF-8 is recovered,
    anything else becomes U+FFFD instead of breaking the XML encoding."""
    return text.encode("utf-8", "surrogateescape").decode("utf-8", "replace")


def _text(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    return "" if value is None else _clean(str(value))


def dict_to_xml(parent, data):
    """Nested dict -> child elements; a list value becomes repeated elements with the key's tag."""
    for key, value in data.items():
        for item in value if isinstance(value, list) else [value]:
            el = ET.SubElement(parent, _tag(key))
            if isinstance(item, dict):
                dict_to_xml(el, item)
            else:
                el.text = _text(item)


def new_document(note=None):
    root = ET.Element("BWFXML")
    ET.SubElement(root, "IXML_VERSION").text = IXML_VERSION
    ET.SubElement(root, "FILE_UID").text = uuid.uuid4().hex.upper()
    if note:
        ET.SubElement(root, "NOTE").text = _clean(note)
    return root


def _child(parent, tag):
    el = parent.find(tag)
    return el if el is not None else ET.SubElement(parent, tag)


def _replace(parent, tag):
    """Fresh empty <tag> under parent, at the position of the old one if there was one."""
    new = ET.Element(tag)
    old = parent.find(tag)
    if old is None:
        parent.append(new)
    else:
        parent.insert(list(parent).index(old), new)
        parent.remove(old)
    return new


def set_section(root, path, data):
    """Replace the section at path (e.g. "MICNODE/RECORDING") with data."""
    *parents, last = path.split("/")
    parent = root
    for part in parents:
        parent = _child(parent, part)
    dict_to_xml(_replace(parent, last), data)


def update_section(root, path, data):
    """Add data to the section at path, replacing only the top-level keys present in data."""
    section = root
    for part in path.split("/"):
        section = _child(section, part)
    for key in data:
        for old in section.findall(_tag(key)):
            section.remove(old)
    dict_to_xml(section, data)


def set_note(root, note):
    if note:
        _replace(root, "NOTE").text = _clean(note)


def set_format(root, sample_rate, bits, track_names):
    speed = _replace(root, "SPEED")
    ET.SubElement(speed, "FILE_SAMPLE_RATE").text = str(sample_rate)
    ET.SubElement(speed, "AUDIO_BIT_DEPTH").text = str(bits)
    tracks = _replace(root, "TRACK_LIST")
    ET.SubElement(tracks, "TRACK_COUNT").text = str(len(track_names))
    for i, name in enumerate(track_names, 1):
        track = ET.SubElement(tracks, "TRACK")
        ET.SubElement(track, "CHANNEL_INDEX").text = str(i)
        ET.SubElement(track, "INTERLEAVE_INDEX").text = str(i)
        ET.SubElement(track, "NAME").text = name


def renew_uid(root):
    """New FILE_UID for a derived file; returns the previous one ("" if none)."""
    old = root.findtext("FILE_UID", default="")
    _replace(root, "FILE_UID").text = uuid.uuid4().hex.upper()
    return old


def parse(xml_text):
    """iXML text -> root element; a fresh document if the text is missing or not valid iXML."""
    if xml_text:
        try:
            root = ET.fromstring(xml_text)
            if root.tag == "BWFXML":
                return root
        except ET.ParseError:
            pass
    return new_document()


def serialize(root):
    ET.indent(root)
    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode").encode("utf-8") + b"\n"


# ---------------------------------------------------------------- common field values

def now():
    return {
        "utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "local": datetime.now().astimezone().isoformat(timespec="seconds"),
    }


def host_info():
    return {"hostname": socket.gethostname(), "platform": platform.platform(), "python": platform.python_version()}


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def tool_info(script_path):
    """Script name + hash of its source, so a file can be traced to the exact code that wrote it."""
    return {"name": os.path.basename(script_path), "sha256": file_sha256(script_path)[:16]}


# ---------------------------------------------------------------- command-line user fields

def add_metadata_args(parser):
    g = parser.add_argument_group("iXML metadata (see wav_ixml.py)")
    g.add_argument("--note", default=None, help="free-text note -> <NOTE>")
    g.add_argument("--meta", action="append", default=[], metavar="KEY=VALUE",
                   help="user field -> <MICNODE><USER>; dots nest (array.radius_mm=20); repeatable")
    g.add_argument("--meta-file", action="append", default=[], metavar="FILE.json",
                   help="nested JSON object of user fields; repeatable")


def _merge(dst, src):
    for key, value in src.items():
        if isinstance(value, dict) and isinstance(dst.get(key), dict):
            _merge(dst[key], value)
        else:
            dst[key] = value


def user_fields(args):
    data = {}
    for path in args.meta_file:
        with open(path, encoding="utf-8") as f:
            loaded = json.load(f)
        if not isinstance(loaded, dict):
            sys.exit(f"--meta-file {path}: top level must be a JSON object")
        _merge(data, loaded)
    for item in args.meta:
        key, sep, value = item.partition("=")
        parts = [p for p in re.split(r"[./]", key.strip()) if p]
        if not sep or not parts:
            sys.exit(f"--meta expects KEY=VALUE, got {item!r}")
        node = data
        for part in parts[:-1]:
            if not isinstance(node.get(part), dict):
                node[part] = {}
            node = node[part]
        node[parts[-1]] = value
    return data


# ---------------------------------------------------------------- RIFF chunk I/O

def _chunks(f):
    f.seek(0)
    header = f.read(12)
    if len(header) < 12 or header[:4] != b"RIFF" or header[8:12] != b"WAVE":
        raise ValueError("not a RIFF/WAVE file")
    end = os.fstat(f.fileno()).st_size
    pos = 12
    while pos + 8 <= end:
        f.seek(pos)
        cid, size = struct.unpack("<4sI", f.read(8))
        yield cid, pos, size
        pos += 8 + size + (size & 1)


def read_ixml(path):
    """iXML text of a WAV file, or None if it has no iXML chunk."""
    with open(path, "rb") as f:
        for cid, pos, size in _chunks(f):
            if cid == b"iXML":
                f.seek(pos + 8)
                return f.read(size).rstrip(b"\0").decode("utf-8", errors="replace")
    return None


def write_ixml(path, root):
    """Put the document into the WAV as its iXML chunk (replacing an existing one), appended at the end."""
    payload = serialize(root)
    with open(path, "r+b") as f:
        old = next(((pos, size) for cid, pos, size in _chunks(f) if cid == b"iXML"), None)
        if old:
            pos, size = old
            f.seek(pos + 8 + size + (size & 1))
            rest = f.read()
            f.seek(pos)
            f.write(rest)
            f.truncate()
        f.seek(0, os.SEEK_END)
        f.write(b"iXML" + struct.pack("<I", len(payload)) + payload + b"\0" * (len(payload) & 1))
        riff_size = f.tell() - 8
        f.seek(4)
        f.write(struct.pack("<I", riff_size))


def main():
    p = argparse.ArgumentParser(description="Print the iXML chunk of a WAV file.")
    p.add_argument("wav")
    text = read_ixml(p.parse_args().wav)
    if text is None:
        sys.exit("No iXML chunk in this file.")
    sys.stdout.reconfigure(encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
