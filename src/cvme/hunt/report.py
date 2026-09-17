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


#: The axes, in the order they are read: can I do it, is the seat right, is
#: the cause right, is the week right, is the employer built to last.
AXIS_ORDER = ("skills", "role", "domain", "culture", "stability")

AXIS_LABEL = {
    "skills": "skills",
    "role": "role & logistics",
    "domain": "domain",
    "culture": "culture",
    "stability": "stability",
}


def _component(fit: Fit, name: str) -> str:
    for component in fit.components:
        if component.name == name:
            return component.detail
    return ""


def _axis_detail(fit: Fit, axis: str) -> str:
    if axis == "skills":
        return _component(fit, "skills") or "term overlap"
    if axis == "role":
        parts = [
            f"{name} {earned:.0f}/{possible}"
            for name, earned, possible in (
                (c.name, c.earned, c.possible)
                for c in fit.components
                if c.name in ("title", "experience", "location")
            )
        ]
        return ", ".join(parts) or "title, experience, location"
    if axis == "culture":
        return "the posting's own reading of the hours"
    if axis == "domain":
        return "the cause the engineering serves"
    if axis == "stability":
        return "researched employer stability" if fit.stability else "not researched"
    return ""


def _cell(value: str) -> str:
    """Make a value safe inside a markdown table cell."""
    return value.replace("|", "\\|").replace("\n", " ")


def stability_block(fit: Fit) -> list[str]:
    """The researched stability signals, with the source behind each one.

    Stability is the one axis the posting cannot carry, so the block states
    plainly when nothing has been researched rather than letting a neutral
    baseline read as a clean bill of health.
    """
    stability = fit.stability
    if stability is None or not stability.known:
        return [
            "**Employer stability not researched.** Run `cvme research` for this "
            "company to score it. An unresearched employer sits at the neutral "
            "baseline, which is not evidence of stability.",
            "",
        ]
    lines = [
        f"**Employer stability {stability.score}/100 ({stability.band})**, "
        f"researched {stability.researched}.",
        "",
    ]
    if stability.verdict:
        reason = f" {stability.verdict_reason}" if stability.verdict_reason else ""
        lines += [f"**Verdict {stability.verdict}.**{reason}", ""]
    if not stability.signals:
        lines += ["The dossier records no weighted signals.", ""]
        return lines
    count = len(stability.signals)
    sources = len(stability.sources)
    lines += [
        "| signal | worth | detail | source |",
        "|---|---|---|---|",
        *(
            f"| {signal.type} | {signal.points:+d} | {_cell(signal.detail)} | "
            f"{_cell(signal.source)} |"
            for signal in stability.signals
        ),
        "",
        f"Scored from {count} cited signal{'s' * (count != 1)} across "
        f"{sources} source{'s' * (sources != 1)}.",
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
    total_weight = sum(fit.weights.get(axis, 0) for axis in AXIS_ORDER) or 1
    lines += [
        "| axis | score | weight | what moved it |",
        "|---|---|---|---|",
        *(
            f"| {AXIS_LABEL[axis]} | {fit.axis(axis)} | "
            f"{round(100 * fit.weights.get(axis, 0) / total_weight)}% | "
            f"{_axis_detail(fit, axis)} |"
            for axis in AXIS_ORDER
        ),
        "",
    ]
    if fit.gate_hits:
        lines += [
            "A gated axis scored below its floor, which caps the composite: "
            + "; ".join(fit.gate_hits)
            + ".",
            "",
        ]
    lines += [
        f"**Answered.** {_terms(fit.matched)}",
        "",
        f"**Not answered.** {_terms(fit.missing)}",
        "",
        "Terms are counted where the posting names them and looked for in your "
        "fact corpus and base documents. A count in brackets is how many times "
        "the posting said it.",
        "",
        *conditions_block(money, culture),
        *stability_block(fit),
        "Everything above this line is computed from the posting; everything "
        "below it was written.",
        "",
        "---",
        "",
    ]
    if fit.preferences is not None:
        prefs = fit.preferences

        def cell(value: str) -> str:
            return value.replace("|", "\\|").replace("\n", " ")

        by_axis = prefs.by_axis
        summary = ", ".join(f"{axis} {by_axis.get(axis, 0):+d}" for axis in AXIS_ORDER)
        details = [
            "### Personal preferences",
            "",
            f"Preference weight by axis: {summary}. Each rule moves the axis it "
            "is tagged with, and the composite weights those axes.",
            "",
            "| axis | signal | points | evidence | why it matters to you |",
            "|---|---|---|---|---|",
            *(
                f"| {signal.axis} | {cell(signal.name)} | {signal.weight:+d} "
                f"| {cell(signal.evidence)} | {cell(signal.reason)} |"
                for signal in prefs.signals
            ),
            "",
            "Each rule counts once. Missing mentions describe the captured posting, "
            "not proof of the employer's stack or standards. These are personal "
            "preferences, not evidence of your skills.",
            "",
        ]
        if not prefs.signals:
            details += ["No preference rules matched.", ""]
        # Insert before the computed/written boundary.
        boundary = next(
            i
            for i, line in enumerate(lines)
            if line.startswith("Everything above this line")
        )
        lines[boundary:boundary] = details
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
