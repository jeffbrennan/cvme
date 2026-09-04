"""The report: a computed fit score, then the written background under it.

The split matters. The score and the term lists above the rule are derived
from the posting and the corpus and can be recomputed from them; everything
below the rule was written by a model reading the same two things. Keeping
them apart means the number never becomes something a model asserted.
"""

from __future__ import annotations

from cvme.hunt.score import Fit, Requirement
from cvme.jobs.models import JobPosting

#: How many missing terms are worth listing before the tail stops being signal.
LIST_LIMIT = 18


def _terms(requirements: list[Requirement], limit: int = LIST_LIMIT) -> str:
    shown = requirements[:limit]
    rendered = ", ".join(
        f"{r.term} ({r.mentions})" if r.mentions > 1 else r.term for r in shown
    )
    if len(requirements) > limit:
        rendered += f", and {len(requirements) - limit} more"
    return rendered or "_none_"


def fit_block(posting: JobPosting, fit: Fit) -> str:
    """The computed half of a report, including its own working."""
    heading = " at ".join(p for p in (posting.title, posting.company) if p)
    lines = [
        f"# {heading or 'Job posting'}",
        "",
        f"**Fit {fit.score}/100 ({fit.band})**",
        "",
    ]
    if fit.blockers:
        lines += [
            "This posting is excluded by your own filters, so the score is held "
            "at zero:",
            "",
            *(f"- {reason}" for reason in fit.blockers),
            "",
        ]
    lines += [
        "| component | earned | of | why |",
        "|---|---|---|---|",
        *(
            f"| {c.name} | {c.earned:.0f} | {c.possible} | {c.detail} |"
            for c in fit.components
        ),
        "",
        f"**Answered.** {_terms(fit.matched)}",
        "",
        f"**Not answered.** {_terms(fit.missing)}",
        "",
        "Terms are counted where the posting names them and looked for in your "
        "fact corpus and base documents. A count in brackets is how many times "
        "the posting said it. Everything above this line is computed; "
        "everything below it was written.",
        "",
        "---",
        "",
    ]
    return "\n".join(lines)


def compose(posting: JobPosting, fit: Fit, background: str) -> str:
    body = background.strip() or "_No background was generated._"
    return f"{fit_block(posting, fit)}{body}\n"


def summary_line(fit: Fit) -> str:
    """The one line worth putting in a CLI exit message."""
    missing = fit.missing[:4]
    tail = (
        f"; not answered: {', '.join(r.term for r in missing)}"
        if missing
        else "; every named term answered"
    )
    return f"fit {fit.score}/100 ({fit.band}){tail}"
