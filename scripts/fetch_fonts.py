"""Regenerate the vendored fonts in src/cvme/render/fonts.

Downloads the @fontsource webfont builds and converts the woff2 files to TTF,
which is what Typst consumes. Run from the repository root:

    uv run --group dev python scripts/fetch_fonts.py
"""

from __future__ import annotations

import io
import pathlib
import tarfile
import urllib.request

from fontTools.ttLib import TTFont

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "src" / "cvme" / "render" / "fonts"
VERSION = "5.3.0"

# destination filename -> (npm package, path within the tarball)
SOURCES: dict[str, tuple[str, str]] = {
    "Carlito-Regular.ttf": ("carlito", "package/files/carlito-latin-400-normal.woff2"),
    "Carlito-Bold.ttf": ("carlito", "package/files/carlito-latin-700-normal.woff2"),
    "Carlito-Italic.ttf": ("carlito", "package/files/carlito-latin-400-italic.woff2"),
    "FiraCode-SemiBold.ttf": (
        "fira-code",
        "package/files/fira-code-latin-600-normal.woff2",
    ),
}
LICENSES = {"Carlito": "carlito", "FiraCode": "fira-code"}


def fetch(package: str) -> tarfile.TarFile:
    url = f"https://registry.npmjs.org/@fontsource/{package}/-/{package}-{VERSION}.tgz"
    with urllib.request.urlopen(url) as response:
        return tarfile.open(fileobj=io.BytesIO(response.read()), mode="r:gz")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    archives = {name: fetch(name) for name in {p for p, _ in SOURCES.values()}}

    for dest, (package, member) in SOURCES.items():
        extracted = archives[package].extractfile(member)
        if extracted is None:
            raise SystemExit(f"{member} missing from @fontsource/{package}")
        font = TTFont(io.BytesIO(extracted.read()))
        font.flavor = None
        font.save(OUT / dest)
        print("wrote", (OUT / dest).relative_to(ROOT))

    for label, package in LICENSES.items():
        extracted = archives[package].extractfile("package/LICENSE")
        if extracted is not None:
            (OUT / f"LICENSE.{label}").write_bytes(extracted.read())
            print("wrote", (OUT / f"LICENSE.{label}").relative_to(ROOT))


if __name__ == "__main__":
    main()
