"""Reading the sources, planning the sync, and applying it.

The CLI stays thin: it parses flags and prints. Everything between the files
on disk and the changeset lives here, so a plan can be built and asserted on
without a terminal.

The plan is complete before anything is written. A run that discovered halfway
through that the sixth position is over the description limit would have
already handed you five to paste, one of which was about to be rejected.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass, field
from pathlib import Path

from cvme.config import Config
from cvme.errors import ConfigError
from cvme.linkedin import state as sync_state
from cvme.linkedin.diff import Changeset, diff
from cvme.linkedin.model import Profile, Violation
from cvme.linkedin.overlay import merge
from cvme.linkedin.project import to_profile
from cvme.md.parse import parse_file

#: Default name for the long-form overlay, looked for beside the source
#: document. Configuring it is possible and, at this name, unnecessary.
OVERLAY_NAME = "linkedin.md"

#: Config field name -> the profile attribute it governs.
_FIELDS = {
    "headline": "headline",
    "summary": "summary",
    "positions": "positions",
    "educations": "educations",
    "skills": "skills",
}


@dataclass
class Plan:
    """What a sync would do, and everything wrong with it."""

    profile: Profile
    changeset: Changeset
    source: Path
    overlay: Path | None = None
    unmapped: list[str] = field(default_factory=list)
    violations: list[Violation] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return bool(self.violations)


def build(config: Config) -> Plan:
    """Read the sources and diff them against the last recorded sync."""
    document = config.document(config.linkedin.document)
    if not document.path.is_file():
        raise ConfigError(
            f"{document.path}: no such file. `[linkedin] document` names "
            f"'{config.linkedin.document}', which cvme.toml points here."
        )
    overlay = _overlay_path(config, document.path)
    merged = merge(parse_file(document.path), parse_file(overlay) if overlay else None)
    profile, unmapped = to_profile(merged)

    wanted = set(config.linkedin.fields)
    current = _restrict(profile, wanted)
    previous = _restrict(sync_state.load(config.root).profile, wanted)
    return Plan(
        profile=current,
        changeset=diff(current, previous),
        source=document.path,
        overlay=overlay,
        unmapped=unmapped,
        violations=current.violations(),
    )


def _overlay_path(config: Config, source: Path) -> Path | None:
    """The configured overlay, or ``linkedin.md`` beside the resume.

    A configured path that does not exist is an error, because someone wrote
    it down on purpose. The conventional one simply does not apply when it is
    not there.
    """
    if (configured := config.linkedin.overlay) is not None:
        if not configured.is_file():
            raise ConfigError(f"{configured}: no such file (`[linkedin] overlay`)")
        return configured
    beside = source.parent / OVERLAY_NAME
    return beside if beside.is_file() else None


def _restrict(profile: Profile, wanted: Collection[str]) -> Profile:
    """Blank whatever the config does not want cvme to own.

    Blanked on both sides of the diff rather than filtered out of it, so a
    field removed from ``[linkedin] fields`` stops producing changes instead
    of producing one last removal of everything in it.
    """
    empty = Profile()
    return profile.model_copy(
        update={
            attribute: getattr(empty if name not in wanted else profile, attribute)
            for name, attribute in _FIELDS.items()
        },
        deep=True,
    )


def record(config: Config, plan: Plan) -> Path:
    """Record the planned profile as the one now on LinkedIn.

    Separate from writing the changeset because cvme cannot see the profile:
    only you know whether the file was pasted in, and claiming otherwise would
    make every later diff wrong.
    """
    return sync_state.save(config.root, plan.profile)
