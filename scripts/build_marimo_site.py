"""Export every marimo notebook in the repo to static WASM HTML for GitHub Pages."""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "site"
EXCLUDE_DIRS = {".venv", ".git", "node_modules", "site", "__marimo__"}
NOTEBOOK_MARKER = re.compile(r"marimo\.App\(")


def find_notebooks() -> list[Path]:
    notebooks = []
    for path in ROOT.rglob("*.py"):
        if any(part in EXCLUDE_DIRS for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if NOTEBOOK_MARKER.search(text):
            notebooks.append(path)
    return sorted(notebooks)


def export_notebook(path: Path) -> str:
    slug = path.relative_to(ROOT).with_suffix("").as_posix()
    out_dir = OUTPUT_DIR / slug
    subprocess.run(
        [
            sys.executable, "-m", "marimo", "export", "html-wasm",
            str(path), "-o", str(out_dir), "--mode", "run", "-f",
        ],
        check=True,
        cwd=ROOT,
    )
    return slug


def build_index(slugs: list[str]) -> None:
    items = "\n".join(f'<li><a href="{slug}/">{slug}</a></li>' for slug in slugs)
    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Marimo notebooks</title>
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 40rem; margin: 3rem auto; padding: 0 1rem; }}
  li {{ margin: 0.4rem 0; }}
</style>
</head>
<body>
<h1>Marimo notebooks</h1>
<ul>
{items}
</ul>
</body>
</html>"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "index.html").write_text(html, encoding="utf-8")
    (OUTPUT_DIR / ".nojekyll").touch()


def main() -> None:
    notebooks = find_notebooks()
    if not notebooks:
        print("No marimo notebooks found.")
        return
    slugs = []
    for notebook in notebooks:
        print(f"Exporting {notebook} ...")
        slugs.append(export_notebook(notebook))
    build_index(slugs)
    print(f"Built {len(slugs)} notebook(s) into {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
