"""What cvme believes is currently on the profile.

A one-way sync needs a memory. Without one the only options are to push
everything on every run, which rewrites fields nobody touched, or to read the
profile back, which the API tier most people can get does not allow.

So the last profile that was actually applied is recorded here, and the next
run diffs against it. The file is a claim about the past, not a cache: it is
written when a sync is applied and at no other time, so an aborted push leaves
the changes outstanding rather than silently swallowed.

It lives under ``.cvme/`` beside the job database, which is already the
project's directory for state that is derived and machine-written.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from cvme.errors import CvmeError
from cvme.linkedin.model import Profile

STATE_PATH = Path(".cvme/linkedin/state.json")


class SyncStateError(CvmeError):
    exit_code = 8


class SyncState(BaseModel):
    """The last applied profile, and how it got there."""

    profile: Profile = Field(default_factory=Profile)
    synced_at: datetime | None = None
    #: Which transport applied it. Worth keeping: a state recorded from a
    #: review the author says they pasted in is a weaker claim than one the
    #: API confirmed, and ``status`` says which you have.
    transport: str = ""
    #: cvme's key for an entity -> the id LinkedIn gave it. Only the API
    #: transport can fill this in, and without it an update has nothing to
    #: address, so a position first applied by hand is created rather than
    #: updated the first time the API is used.
    remote_ids: dict[str, str] = Field(default_factory=dict)

    @property
    def recorded(self) -> bool:
        return self.synced_at is not None


def path_for(root: Path) -> Path:
    return root / STATE_PATH


def load(root: Path) -> SyncState:
    """The recorded state, or an empty one on the first run.

    A corrupt file is an error rather than a silent reset: resetting would
    present the whole profile as new and quietly re-push every field.
    """
    path = path_for(root)
    if not path.is_file():
        return SyncState()
    try:
        return SyncState.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SyncStateError(
            f"{path}: cannot read the sync state ({exc}).\n"
            "  Delete it to start over; the next sync will then offer the "
            "whole profile as new."
        ) from exc


def save(
    root: Path,
    profile: Profile,
    *,
    transport: str,
    remote_ids: dict[str, str] | None = None,
) -> Path:
    """Record ``profile`` as applied."""
    state = SyncState(
        profile=profile,
        synced_at=datetime.now(UTC),
        transport=transport,
        remote_ids=dict(remote_ids or {}),
    )
    path = path_for(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(state.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def clear(root: Path) -> bool:
    """Forget the recorded state, so the next sync sees the whole profile."""
    path = path_for(root)
    if not path.is_file():
        return False
    path.unlink()
    return True
