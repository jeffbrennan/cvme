"""Findings and how they are reported."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

Severity = Literal["error", "warning"]


@dataclass(frozen=True)
class Finding:
    rule: str
    severity: Severity
    message: str
    line: int
    excerpt: str = ""
    suggestion: str = ""

    def format(self, path: Path) -> str:
        head = f"{path}:{self.line}: {self.severity}: {self.message} [{self.rule}]"
        parts = [head]
        if self.excerpt:
            parts.append(f"    {self.excerpt}")
        if self.suggestion:
            parts.append(f"    suggestion: {self.suggestion}")
        return "\n".join(parts)


@dataclass(frozen=True)
class Report:
    path: Path
    findings: list[Finding]

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def format(self) -> str:
        if not self.findings:
            return f"{self.path}: ok"
        body = "\n".join(f.format(self.path) for f in self.findings)
        errors = len(self.errors)
        warnings = len(self.findings) - errors
        return f"{body}\n\n{errors} error(s), {warnings} warning(s)"

    def to_json(self) -> str:
        return json.dumps(
            {"path": str(self.path), "findings": [asdict(f) for f in self.findings]},
            indent=2,
        )
