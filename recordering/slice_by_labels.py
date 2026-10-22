"""
Нарезка многоканального WAV по меткам Audacity без сведения каналов.

Использование:
    pip install soundfile
    python slice_by_labels.py input.wav labels.txt output_folder

labels.txt — файл из Audacity: File → Export → Export Labels
(строки вида: начало<TAB>конец<TAB>имя, время в секундах).
Метки-точки (начало == конец) и строки частотных диапазонов пропускаются.
"""
import re
import sys
from pathlib import Path

import soundfile as sf


def read_labels(path):
    labels = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("\\"):  # "\" — строки частот Audacity
            continue
        parts = line.split("\t")
        start, end = float(parts[0]), float(parts[1])
        name = parts[2].strip() if len(parts) > 2 else ""
        if end > start:
            labels.append((start, end, name))
    return labels


def safe_name(name, index):
    name = re.sub(r'[\\/:*?"<>|]+', "_", name).strip() or "region"
    return f"{index:03d}_{name}"


def main(wav_path, labels_path, out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    info = sf.info(wav_path)
    data, sr = sf.read(wav_path, always_2d=True, dtype="float64")
    print(f"{wav_path}: {info.channels} кан., {sr} Гц, {info.subtype}")

    for i, (start, end, name) in enumerate(read_labels(labels_path), 1):
        a, b = int(round(start * sr)), min(int(round(end * sr)), len(data))
        fname = out / f"{safe_name(name, i)}.wav"
        sf.write(fname, data[a:b], sr, subtype=info.subtype)
        print(f"  {fname.name}: {start:.3f}–{end:.3f} c, {b - a} сэмплов")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    main(*sys.argv[1:])
