"""Fail when private or non-generic content would ship.

This repository is public and its packaging is public, so every example is
synthetic: `example.com` contacts, invented employers, and placeholder names.
Personal data and captured source material do not belong in a public tool.

Two layers of rules run over whatever is scanned:

* Generic patterns that need no configuration. The main one is an email or
  `mailto:` whose domain is not a reserved example domain, which catches the
  common case of a real address copied into a doc, test, or fixture.
* A private term list read from ``--terms FILE``, ``CVME_PRIVATE_TERMS``, or
  ``~/.config/cvme/private-terms.txt``. Keeping the list outside the repository
  means the public repo never contains the very words it forbids. Without a
  list the generic patterns still run, so an unconfigured checkout is not
  silently unchecked.

Usage::

    uv run --no-project python scripts/check_private.py            # the tree
    uv run --no-project python scripts/check_private.py docs tests
    uv run --no-project python scripts/check_private.py --archive dist/*

The archive mode reads a built ``.tar.gz`` or ``.whl`` without extracting it,
which is the backstop for the release workflow: it scans exactly what would be
uploaded.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import re
import sys
import tarfile
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent

#: Reserved domains that are safe in examples. An address outside these is a
#: finding, because a real one has no business in a public repository.
EXAMPLE_DOMAINS = frozenset(
    {"example.com", "example.org", "example.net", "example.edu"}
)

#: Directories that never hold authored content.
SKIP_DIRS = frozenset(
    {
        ".git",
        ".cvme",
        ".venv",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        ".ty",
        "__pycache__",
        "dist",
        "build",
        "node_modules",
    }
)

#: Suffixes that are not text and cannot be read as one.
SKIP_SUFFIXES = frozenset(
    {
        ".pdf",
        ".ttf",
        ".otf",
        ".woff",
        ".woff2",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".ico",
        ".zip",
        ".gz",
        ".tgz",
        ".whl",
        ".pyc",
        ".so",
        ".dylib",
        ".bin",
    }
)

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

#: Strings that look like a rule violation but are the project's own identity
#: or an obvious placeholder.
ALLOW = (
    # The project's canonical URL carries the maintainer handle, which is
    # public and required by the package metadata.
    re.compile(r"github\.com/jeffbrennan/cvme"),
    # A deliberately minimal address, used to test inline link handling.
    re.compile(r"\ba@b\.com\b"),
)


class Finding:
    __slots__ = ("lineno", "rule", "text", "where")

    def __init__(self, where: str, lineno: int, text: str, rule: str) -> None:
        self.where = where
        self.lineno = lineno
        self.text = text
        self.rule = rule

    def __str__(self) -> str:
        return f"{self.where}:{self.lineno}: {self.rule}: {self.text}"


def _is_allowed(line: str) -> str:
    for pattern in ALLOW:
        line = pattern.sub("", line)
    return line


def _text_rules(terms: list[str]):
    def scan(where: str, lineno: int, line: str) -> list[Finding]:
        stripped = _is_allowed(line)
        found: list[Finding] = []
        for match in EMAIL.finditer(stripped):
            domain = match.group(0).rsplit("@", 1)[1].casefold()
            if domain not in EXAMPLE_DOMAINS:
                found.append(
                    Finding(where, lineno, match.group(0), "non-example email")
                )
        low = stripped.casefold()
        for term in terms:
            if term and term.casefold() in low:
                found.append(Finding(where, lineno, term, "private term"))
        return found

    return scan


def _scan_text(where: str, text: str, scan) -> list[Finding]:
    found: list[Finding] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        found.extend(scan(where, lineno, line))
    return found


def scan_paths(paths: list[pathlib.Path], scan) -> list[Finding]:
    found: list[Finding] = []
    for path in paths:
        if path.is_dir():
            for file in sorted(path.rglob("*")):
                if not file.is_file():
                    continue
                if any(part in SKIP_DIRS for part in file.parts):
                    continue
                if file.suffix.casefold() in SKIP_SUFFIXES:
                    continue
                try:
                    text = file.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                try:
                    label = str(file.relative_to(ROOT))
                except ValueError:
                    label = str(file)
                found.extend(_scan_text(label, text, scan))
        elif path.is_file():
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            found.extend(_scan_text(str(path), text, scan))
    return found


def scan_archives(paths: list[pathlib.Path], scan) -> list[Finding]:
    found: list[Finding] = []
    for path in paths:
        if tarfile.is_tarfile(path):
            with tarfile.open(path) as archive:
                for member in archive.getmembers():
                    if not member.isfile():
                        continue
                    handle = archive.extractfile(member)
                    if handle is None:
                        continue
                    found.extend(_scan_member(path, member.name, handle.read(), scan))
        elif zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as archive:
                for name in archive.namelist():
                    found.extend(_scan_member(path, name, archive.read(name), scan))
        else:
            found.extend(_scan_member(path, path.name, path.read_bytes(), scan))
    return found


def _scan_member(archive: pathlib.Path, name: str, data: bytes, scan) -> list[Finding]:
    if pathlib.PurePosixPath(name).suffix.casefold() in SKIP_SUFFIXES:
        return []
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return []
    return _scan_text(f"{archive}!{name}", text, scan)


def load_terms(explicit: str | None) -> list[str]:
    if explicit:
        raw = pathlib.Path(explicit).read_text(encoding="utf-8")
    elif env := os.environ.get("CVME_PRIVATE_TERMS"):
        raw = env.replace(",", "\n")
    else:
        default = pathlib.Path.home() / ".config" / "cvme" / "private-terms.txt"
        raw = default.read_text(encoding="utf-8") if default.is_file() else ""
    return [
        line.strip()
        for line in raw.splitlines()
        if line.strip() and not line.startswith("#")
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="*", type=pathlib.Path, default=[ROOT])
    parser.add_argument("--terms", help="File of private terms, one per line.")
    parser.add_argument(
        "--archive",
        nargs="+",
        type=pathlib.Path,
        help="Built archives to scan instead of the source tree.",
    )
    args = parser.parse_args(argv)

    terms = load_terms(args.terms)
    scan = _text_rules(terms)
    found = (
        scan_archives(args.archive, scan)
        if args.archive
        else scan_paths(args.paths or [ROOT], scan)
    )

    if not found:
        scope = "archives" if args.archive else "source tree"
        note = (
            f"{len(terms)} private term(s) loaded" if terms else "no private term list"
        )
        print(f"check_private: clean ({scope}, {note})")
        return 0

    for finding in found:
        print(finding)
    print(f"check_private: {len(found)} finding(s)", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
