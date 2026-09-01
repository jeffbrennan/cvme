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
        if not rule.applies_to(line):
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


def _excerpt(line: str, start: int, end: int, width: int = 32) -> str:
    left = max(0, start - width)
    right = min(len(line), end + width)
    text = line[left:right].strip()
    return f"{'...' if left else ''}{text}{'...' if right < len(line) else ''}"
