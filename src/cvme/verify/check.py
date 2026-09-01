"""Run every check over a document.

Verification reads the markdown source rather than the parsed IR, which gives
exact line numbers and means it works on any hand-written document, not only
generated ones.
"""

from __future__ import annotations

import re
from pathlib import Path

from cvme.verify.corpus import Corpus
from cvme.verify.numbers import Claim, extract
from cvme.verify.prose import Rule, load_rules
from cvme.verify.prose import check_line as check_prose
from cvme.verify.report import Finding, Report

_FACT = re.compile(r"<!--\s*fact:\s*([A-Za-z0-9_.-]+)\s*-->")
_FRONTMATTER = re.compile(r"^---\s*$")


def _body_lines(text: str) -> list[tuple[int, str]]:
    """Source lines, with frontmatter skipped but numbering preserved."""
    lines = text.splitlines()
    start = 0
    if lines and _FRONTMATTER.match(lines[0]):
        for index in range(1, len(lines)):
            if _FRONTMATTER.match(lines[index]):
                start = index + 1
                break
    return [(n, line) for n, line in enumerate(lines[start:], start + 1)]


def _claim_findings(
    claim: Claim, line_no: int, fact_ids: list[str], corpus: Corpus
) -> Finding | None:
    if fact_ids:
        allowed: set[tuple[float, str | None]] = set()
        for identifier in fact_ids:
            fact = corpus.facts.get(identifier)
            if fact is not None:
                allowed |= fact.keys
        if claim.key in allowed:
            return None
        cited = ", ".join(fact_ids)
        return Finding(
            rule="fact:mismatch",
            severity="error",
            message=f"'{claim.raw}' does not appear in the cited fact",
            line=line_no,
            excerpt=f"cites {cited}",
            suggestion="cite the fact that carries this number, or correct it",
        )

    if claim.key in corpus.keys:
        return None

    near = corpus.describe(claim.key)
    return Finding(
        rule="fact:unsourced",
        severity="error",
        message=f"'{claim.raw}' appears nowhere in the fact corpus",
        line=line_no,
        excerpt=near[0][:72] if near else "",
        suggestion=(
            "the same value appears above with a different unit"
            if near
            else "add it to the corpus, or remove the claim"
        ),
    )


def verify_text(
    text: str,
    path: Path,
    corpus: Corpus,
    *,
    rules: list[Rule] | None = None,
    check_facts: bool = True,
) -> Report:
    """Check one document's source."""
    rules = load_rules() if rules is None else rules
    findings: list[Finding] = []

    for number, line in _body_lines(text):
        if not line.strip():
            continue
        fact_ids = _FACT.findall(line)
        prose = _FACT.sub("", line)

        for identifier in fact_ids:
            if identifier not in corpus.facts:
                findings.append(
                    Finding(
                        rule="fact:unknown",
                        severity="error",
                        message=f"cited fact '{identifier}' is not in the corpus",
                        line=number,
                        suggestion="add it to a fact file, or fix the id",
                    )
                )

        findings += check_prose(prose, number, rules)

        if check_facts and corpus:
            for claim in extract(prose):
                if finding := _claim_findings(claim, number, fact_ids, corpus):
                    findings.append(finding)

    findings.sort(key=lambda f: (f.line, f.rule))
    return Report(path=path, findings=findings)


def verify_file(path: Path, corpus: Corpus, *, check_facts: bool = True) -> Report:
    return verify_text(
        path.read_text(encoding="utf-8"), path, corpus, check_facts=check_facts
    )
