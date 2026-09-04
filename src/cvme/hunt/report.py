"""The report: a computed fit score, then the written background under it.

The split matters. The score and the term lists above the rule are derived
from the posting and the corpus and can be recomputed from them; everything
below the rule was written by a model reading the same two things. Keeping
them apart means the number never becomes something a model asserted.
"""

from __future__ import annotations

from cvme.hunt.culture import BASELINE as CULTURE_BASELINE
from cvme.hunt.culture import NO_CULTURE, Culture
from cvme.hunt.culture import summary_line as culture_line
from cvme.hunt.pay import NO_PAY, Pay
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


def conditions_block(money: Pay, culture: Culture) -> list[str]:
    """What the posting says about pay and hours, and which words said it.

    Both readings are of the advertisement, not of the company, and both name
    the phrases they came from so a wrong reading is visibly wrong.
    """
    stated = f" (as stated: {money.stated})" if money.stated else ""
    lines = [
        f"**Pay** {money.short}{stated}" if money else "**Pay** not stated",
        "",
        f"**Work-life {culture.score}/100 ({culture.band})**",
        "",
    ]
    if not culture.signals:
        lines += ["The posting says nothing either way about the hours.", ""]
        return lines
    lines += [
        "| signal | worth | what it predicts |",
        "|---|---|---|",
        *(f"| {s.term} | {s.sign} | {s.says} |" for s in culture.signals),
        "",
        f"Read from the posting's own vocabulary, starting at {CULTURE_BASELINE} "
        "where a posting says nothing. Each phrase counts once however often it "
        "appears.",
        "",
    ]
    return lines


def fit_block(
    posting: JobPosting, fit: Fit, money: Pay = NO_PAY, culture: Culture = NO_CULTURE
) -> str:
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
        "the posting said it.",
        "",
        *conditions_block(money, culture),
        "Everything above this line is computed from the posting; everything "
        "below it was written.",
        "",
        "---",
        "",
    ]
    return "\n".join(lines)


def compose(
    posting: JobPosting, fit: Fit, money: Pay, culture: Culture, background: str
) -> str:
    body = background.strip() or "_No background was generated._"
    return f"{fit_block(posting, fit, money, culture)}{body}\n"


def conditions_line(money: Pay, culture: Culture) -> str:
    """The one line worth putting in a CLI exit message."""
    pay_part = f"pay {money.short}" if money else "pay not stated"
    return f"{pay_part}; {culture_line(culture)}"


def summary_line(fit: Fit) -> str:
    """The one line worth putting in a CLI exit message."""
    missing = fit.missing[:4]
    tail = (
        f"; not answered: {', '.join(r.term for r in missing)}"
        if missing
        else "; every named term answered"
    )
    return f"fit {fit.score}/100 ({fit.band}){tail}"
