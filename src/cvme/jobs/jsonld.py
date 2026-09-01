"""Extract a posting from schema.org JSON-LD.

This is the primary extractor for every source. LinkedIn, Indeed and the major
applicant tracking systems all emit ``<script type="application/ld+json">``
carrying a ``JobPosting``, and unlike a CSS selector it is a documented
standard with named fields, so it survives redesigns.
"""

from __future__ import annotations

import json
import re
from typing import Any

from cvme.jobs.htmltext import to_markdown
from cvme.jobs.models import JobPosting

_SCRIPT = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)


def _blocks(html: str) -> list[Any]:
    """Every JSON-LD payload in the page, parsed, bad ones skipped."""
    out: list[Any] = []
    for raw in _SCRIPT.findall(html):
        try:
            out.append(json.loads(raw.strip()))
        except json.JSONDecodeError:
            continue  # pages ship broken JSON-LD more often than you would hope
    return out


def _walk(node: Any) -> list[dict[str, Any]]:
    """Every JobPosting object, however it is nested (@graph, arrays)."""
    found: list[dict[str, Any]] = []
    if isinstance(node, list):
        for item in node:
            found += _walk(item)
    elif isinstance(node, dict):
        types = node.get("@type", "")
        types = types if isinstance(types, list) else [types]
        if any(str(t).endswith("JobPosting") for t in types):
            found.append(node)
        for key in ("@graph", "mainEntity", "itemListElement"):
            if key in node:
                found += _walk(node[key])
    return found


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return str(value.get("name") or value.get("value") or "").strip()
    if isinstance(value, list):
        return ", ".join(filter(None, (_text(v) for v in value)))
    return "" if value is None else str(value).strip()


def _location(node: Any) -> str:
    places = node if isinstance(node, list) else [node]
    parts: list[str] = []
    for place in places:
        if not isinstance(place, dict):
            parts.append(_text(place))
            continue
        address = place.get("address", place)
        if isinstance(address, str):
            parts.append(address.strip())
            continue
        if isinstance(address, dict):
            fields = (
                address.get("addressLocality"),
                address.get("addressRegion"),
                _text(address.get("addressCountry")),
            )
            joined = ", ".join(str(f).strip() for f in fields if f)
            if joined:
                parts.append(joined)
    seen = list(dict.fromkeys(p for p in parts if p))
    return "; ".join(seen)


def _salary(node: Any) -> str:
    if not isinstance(node, dict):
        return _text(node)
    currency = _text(node.get("currency") or node.get("salaryCurrency"))
    value = node.get("value", node)
    if isinstance(value, dict):
        low = value.get("minValue")
        high = value.get("maxValue")
        unit = _text(value.get("unitText"))
        amount = (
            f"{low}-{high}"
            if low is not None and high is not None
            else _text(low if low is not None else value.get("value"))
        )
    else:
        amount = _text(value)
        unit = ""
    parts = [p for p in (currency, amount) if p]
    text = " ".join(parts)
    return f"{text} per {unit.lower()}" if text and unit else text


def from_dict(node: dict[str, Any], url: str, *, source: str = "jsonld") -> JobPosting:
    """Build a posting from one JSON-LD JobPosting object."""
    remote: bool | None = None
    if location_type := _text(node.get("jobLocationType")):
        remote = location_type.upper() == "TELECOMMUTE"

    return JobPosting(
        url=url,
        title=_text(node.get("title")),
        company=_text(node.get("hiringOrganization")),
        location=_location(node.get("jobLocation"))
        or _text(node.get("applicantLocationRequirements")),
        employment_type=_text(node.get("employmentType")),
        remote=remote,
        salary=_salary(node.get("baseSalary")),
        posted=_text(node.get("datePosted"))[:10],
        apply_url=_text(node.get("url")) or url,
        description=to_markdown(_text(node.get("description"))),
        source=source,
        tier="jsonld",
    )


def extract(html: str, url: str, *, source: str = "jsonld") -> JobPosting | None:
    """The first JobPosting in a page's JSON-LD, if there is one."""
    for block in _blocks(html):
        for node in _walk(block):
            posting = from_dict(node, url, source=source)
            if posting.title or posting.description:
                return posting
    return None
