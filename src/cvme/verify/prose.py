"""Rules that catch generated-sounding prose.

A prompt asking a model not to write like this fails silently, and you find
out after you have applied. These rules are the part that actually holds.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cvme.verify.report import Finding, Severity

RULES_PATH = Path(__file__).parent / "rules.toml"

#: A labelled list line ("- **Languages**: a, b, and c") is an enumeration, so
#: rhetoric rules scoped to prose skip it.
_LABELLED = re.compile(r"^\s*[-*+]\s+\*\*[^*]+\*\*\s*:")


@dataclass(frozen=True)
class Rule:
    id: str
    pattern: re.Pattern[str]
    message: str
    severity: Severity
    suggestion: str = ""
    scope: str = "all"

    def applies_to(self, line: str) -> bool:
        return self.scope != "prose" or not _LABELLED.match(line)


def _phrase_rules(table: dict[str, Any], prefix: str) -> list[Rule]:
    severity: Severity = table.get("severity", "error")
    rules = []
    for word in table.get("words", []):
        rules.append(
            Rule(
                id=f"{prefix}:{word.replace(' ', '-')}",
                pattern=re.compile(rf"\b{re.escape(word)}", re.IGNORECASE),
                message=f"'{word}'",
                severity=severity,
                suggestion="plainer wording",
            )
        )
    return rules


def load_rules(path: Path = RULES_PATH) -> list[Rule]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    rules = [
        Rule(
            id=entry["id"],
            pattern=re.compile(entry["pattern"], re.IGNORECASE),
            message=entry["message"],
            severity=entry.get("severity", "error"),
            suggestion=entry.get("suggestion", ""),
            scope=entry.get("scope", "all"),
        )
        for entry in data.get("rule", [])
    ]
    phrases = data.get("phrases", {})
    rules += _phrase_rules(phrases, "phrase")
    rules += _phrase_rules(phrases.get("soft", {}), "phrase")
    return rules


def check_line(line: str, number: int, rules: list[Rule]) -> list[Finding]:
    findings = []
    for rule in rules:
        if rule.scope == "paragraph" or not rule.applies_to(line):
            continue
        if match := rule.pattern.search(line):
            findings.append(
                Finding(
                    rule=rule.id,
                    severity=rule.severity,
                    message=rule.message,
                    line=number,
                    excerpt=_excerpt(line, match.start(), match.end()),
                    suggestion=rule.suggestion,
                )
            )
    return findings


def check_paragraph(lines: list[tuple[int, str]], rules: list[Rule]) -> list[Finding]:
    """Rules that need more than one line to see what they are looking for.

    A rhetorical figure runs across a sentence boundary, and a sentence
    boundary in a hard-wrapped document is usually also a line boundary. Line
    rules cannot see "is not the API surface. It is deciding" at all, so these
    run against the paragraph joined back into one string, and report the line
    the match starts on.
    """
    if not lines:
        return []
    joined = " ".join(line for _, line in lines)
    # Where each line begins in the joined string, to map an offset back.
    starts, offset = [], 0
    for number, line in lines:
        starts.append((offset, number))
        offset += len(line) + 1

    findings = []
    for rule in rules:
        if rule.scope != "paragraph":
            continue
        if match := rule.pattern.search(joined):
            number = next(
                num for start, num in reversed(starts) if start <= match.start()
            )
            findings.append(
                Finding(
                    rule=rule.id,
                    severity=rule.severity,
                    message=rule.message,
                    line=number,
                    excerpt=_excerpt(joined, match.start(), match.end()),
                    suggestion=rule.suggestion,
                )
            )
    return findings


def _excerpt(line: str, start: int, end: int, width: int = 32) -> str:
    left = max(0, start - width)
    right = min(len(line), end + width)
    text = line[left:right].strip()
    return f"{'...' if left else ''}{text}{'...' if right < len(line) else ''}"
