"""Recipient-facing filenames, independent of internal document keys and versions."""

from __future__ import annotations

import re
import unicodedata

from cvme.config import Config
from cvme.errors import ConfigError
from cvme.md.parse import parse_file


def token(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")


def role_title(title: str) -> str:
    """Drop posting qualifiers and job grades without inventing a seniority level.

    The advertised title is authoritative: a grade III is not assumed to mean
    Senior. Preserve formal words such as Senior, Staff, Principal and Lead.
    """
    title = re.split(r"\s+[-–—|/]\s+|[,|]|\s*\(", title, maxsplit=1)[0]
    words = token(title).split("_")
    aliases = {"sr": "senior", "jr": "junior"}
    ignored = {"specialist", "remote", "hybrid", "onsite"}
    words = [aliases.get(word, word) for word in words]
    words = [
        word
        for word in words
        if word not in ignored and not re.fullmatch(r"\d+|[ivx]+", word)
    ]
    return "_".join(words)


def filenames(config: Config, documents: list[str], title: str) -> dict[str, str]:
    role = role_title(title)
    if not role:
        raise ConfigError("a job title is required for application filenames")
    result = {}
    for key in documents:
        document = config.document(key)
        name = token(parse_file(document.path).name)
        if not name:
            raise ConfigError(f"{document.path} needs a name for application filenames")
        suffix = "" if document.template == "resume" else f"_{token(document.template)}"
        result[key] = f"{name}_{role}{suffix}.md"
    if len(set(result.values())) != len(result):
        raise ConfigError("selected documents produce duplicate application filenames")
    return result
