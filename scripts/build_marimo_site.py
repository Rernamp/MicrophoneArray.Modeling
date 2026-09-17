"""Export every marimo notebook in the repo to static WASM HTML for GitHub Pages.

Third-party imports are auto-detected per notebook and pinned to the versions
installed in this environment, then injected as inline PEP 723 dependency
metadata before export. This lets marimo's html-wasm exporter (and Pyodide's
micropip at runtime) know about packages it can't infer on its own, such as
pure-Python packages that aren't part of Pyodide's built-in package set
(e.g. plotly) -- without editing the notebook files themselves.
"""

import ast
import re
import shutil
import subprocess
import sys
import sysconfig
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / "src"
OUTPUT_DIR = ROOT / "site"
# Must live inside ROOT (not the system temp dir) so marimo can still find
# pyproject.toml by walking up from the copied notebook's directory, which is
# what makes it pick up `[tool.marimo.runtime] pythonpath` for local modules.
TMP_DIR = ROOT / ".marimo_export_tmp"
EXCLUDE_DIRS = {".venv", ".git", "node_modules", "site", "__marimo__", TMP_DIR.name}
NOTEBOOK_MARKER = re.compile(r"marimo\.App\(")

# Import name -> PyPI distribution name, for the rare cases they differ.
IMPORT_TO_DIST = {
    "cv2": "opencv-python",
    "PIL": "Pillow",
    "yaml": "PyYAML",
    "sklearn": "scikit-learn",
}

# Packages that don't need to be declared: marimo itself is always available,
# and pyodide provides these as built-in binary wheels that its automatic
# import-based loader already resolves.
SKIP_IMPORTS = {"marimo"}


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


def local_module_names() -> set[str]:
    """Top-level modules/packages importable via this project's pythonpath (src/)."""
    if not SRC_DIR.is_dir():
        return set()
    names = set()
    for entry in SRC_DIR.iterdir():
        if entry.name in {"__init__.py", "__pycache__"} or entry.name.endswith(".egg-info"):
            continue
        names.add(entry.stem)
    return names


def top_level_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                names.add(node.module.split(".")[0])
    return names


def stdlib_module_names() -> set[str]:
    names = set(sys.stdlib_module_names)
    stdlib_path = Path(sysconfig.get_paths()["stdlib"])
    if stdlib_path.is_dir():
        for entry in stdlib_path.iterdir():
            names.add(entry.stem)
    return names


def resolve_dependencies(path: Path, local_names: set[str], stdlib_names: set[str]) -> list[str]:
    third_party = top_level_imports(path) - local_names - stdlib_names - SKIP_IMPORTS
    dependencies = []
    for import_name in sorted(third_party):
        dist_name = IMPORT_TO_DIST.get(import_name, import_name)
        try:
            version = metadata.version(dist_name)
        except metadata.PackageNotFoundError:
            continue
        dependencies.append(f"{dist_name}=={version}")
    return dependencies


def with_inline_dependencies(source: str, dependencies: list[str]) -> str:
    if not dependencies:
        return source
    deps_lines = "\n".join(f'#     "{dep}",' for dep in dependencies)
    header = f"# /// script\n# dependencies = [\n{deps_lines}\n# ]\n# ///\n\n"
    return header + source


def export_notebook(path: Path, local_names: set[str], stdlib_names: set[str], tmp_dir: Path) -> str:
    slug = path.relative_to(ROOT).with_suffix("").as_posix()
    out_dir = OUTPUT_DIR / slug

    dependencies = resolve_dependencies(path, local_names, stdlib_names)
    source = with_inline_dependencies(path.read_text(encoding="utf-8"), dependencies)
    export_input_dir = tmp_dir / slug
    export_input_dir.mkdir(parents=True, exist_ok=True)
    export_input = export_input_dir / path.name
    export_input.write_text(source, encoding="utf-8")

    subprocess.run(
        [
            sys.executable, "-m", "marimo", "export", "html-wasm",
            str(export_input), "-o", str(out_dir), "--mode", "run", "--no-sandbox", "-f",
        ],
        check=True,
        cwd=ROOT,
    )
    inject_home_link(out_dir, depth=len(Path(slug).parts))
    return slug


def inject_home_link(out_dir: Path, depth: int) -> None:
    index_path = out_dir / "index.html"
    home_href = "../" * depth or "."
    link_html = (
        f'<a href="{home_href}" '
        'style="position:fixed;top:0.75rem;left:0.75rem;z-index:2147483647;'
        "font-family:system-ui,sans-serif;font-size:0.85rem;padding:0.35rem 0.7rem;"
        "background:#fff;color:#333;border:1px solid #ccc;border-radius:0.4rem;"
        'text-decoration:none;box-shadow:0 1px 3px rgba(0,0,0,0.15);">'
        "← Home</a>"
    )
    html = index_path.read_text(encoding="utf-8")
    html = html.replace("<body>", f"<body>{link_html}", 1)
    index_path.write_text(html, encoding="utf-8")


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

    local_names = local_module_names()
    stdlib_names = stdlib_module_names()

    if TMP_DIR.exists():
        shutil.rmtree(TMP_DIR)
    TMP_DIR.mkdir(parents=True)
    try:
        slugs = []
        for notebook in notebooks:
            print(f"Exporting {notebook} ...")
            slugs.append(export_notebook(notebook, local_names, stdlib_names, TMP_DIR))
    finally:
        shutil.rmtree(TMP_DIR)

    build_index(slugs)
    print(f"Built {len(slugs)} notebook(s) into {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
