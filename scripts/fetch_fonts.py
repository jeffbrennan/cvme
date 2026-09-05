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

#: Body families, each in the three faces a document needs. 600 rather than
#: 700 for the bold: a resume leans on bold for its whole hierarchy, and a
#: semibold carries that hierarchy without the page reading as shouted. Typst
#: resolves `weight: "bold"` to the nearest weight the family ships.
BODY_WEIGHTS = {
    "Regular": "400-normal",
    "SemiBold": "600-normal",
    "Italic": "400-italic",
}
BODY_FAMILIES = {
    "Carlito": ("carlito", "Carlito"),
    "IBMPlexSans": ("ibm-plex-sans", "IBM Plex Sans"),
    "SourceSans3": ("source-sans-3", "Source Sans 3"),
    "SourceSerif4": ("source-serif-4", "Source Serif 4"),
    "EBGaramond": ("eb-garamond", "EB Garamond"),
    "Inter": ("inter", "Inter"),
}
#: Display faces for the name. One weight is all the letterhead needs.
DISPLAY_FACES = {
    "FiraCode-SemiBold": ("fira-code", "600-normal", "Fira Code"),
    "IBMPlexMono-SemiBold": ("ibm-plex-mono", "600-normal", "IBM Plex Mono"),
    "JetBrainsMono-SemiBold": ("jetbrains-mono", "600-normal", "JetBrains Mono"),
}

# Carlito ships 400/700 only, so its bold is 700.
OVERRIDES = {("Carlito", "SemiBold"): "700-normal"}


def _sources() -> dict[str, tuple[str, str, str, str]]:
    """destination filename -> (npm package, tarball member, family, face)."""
    out: dict[str, tuple[str, str, str, str]] = {}
    for label, (package, family) in BODY_FAMILIES.items():
        for face, weight in BODY_WEIGHTS.items():
            weight = OVERRIDES.get((label, face), weight)
            out[f"{label}-{face}.ttf"] = (
                package,
                f"package/files/{package}-latin-{weight}.woff2",
                family,
                face,
            )
    for dest, (package, weight, family) in DISPLAY_FACES.items():
        out[f"{dest}.ttf"] = (
            package,
            f"package/files/{package}-latin-{weight}.woff2",
            family,
            "SemiBold",
        )
    return out


def rename(font: TTFont, family: str, face: str) -> None:
    """Flatten the name table to one family with one face per weight.

    The @fontsource builds carry names like `Source Sans 3 ExtraLight`, which
    is the subset's origin rather than the face it holds. Typst matches on the
    family name and the weight class, so leaving those in place makes
    `body_font = "Source Sans 3"` depend on Typst's name-trimming heuristics.
    Rewriting them makes the selection exact.
    """
    table = font["name"]
    full = family if face == "Regular" else f"{family} {face}"
    for name_id, value in (
        (1, family),
        (2, face),
        (4, full),
        (6, full.replace(" ", "")),
    ):
        table.setName(value, name_id, 3, 1, 0x409)
        table.setName(value, name_id, 1, 0, 0)
    # 16/17 are the typographic family and face. With 1/2 correct they add
    # nothing, and a stale pair here outranks the names just written.
    for name_id in (16, 17):
        table.removeNames(nameID=name_id)


def fetch(package: str) -> tarfile.TarFile:
    url = f"https://registry.npmjs.org/@fontsource/{package}/-/{package}-{VERSION}.tgz"
    with urllib.request.urlopen(url) as response:
        return tarfile.open(fileobj=io.BytesIO(response.read()), mode="r:gz")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    sources = _sources()
    packages = {entry[0] for entry in sources.values()}
    archives = {name: fetch(name) for name in packages}

    for dest, (package, member, family, face) in sources.items():
        extracted = archives[package].extractfile(member)
        if extracted is None:
            raise SystemExit(f"{member} missing from @fontsource/{package}")
        font = TTFont(io.BytesIO(extracted.read()))
        font.flavor = None
        rename(font, family, face)
        font.save(OUT / dest)
        print("wrote", (OUT / dest).relative_to(ROOT))

    for package in sorted(packages):
        extracted = archives[package].extractfile("package/LICENSE")
        if extracted is not None:
            label = "".join(part.title() for part in package.split("-"))
            (OUT / f"LICENSE.{label}").write_bytes(extracted.read())
            print("wrote", (OUT / f"LICENSE.{label}").relative_to(ROOT))


if __name__ == "__main__":
    main()
