"""Running a coding agent as a subprocess.

The argv is configuration, not code. These CLIs change their flags often
enough that hard-coding them would guarantee breakage, and the failure mode
would be a stack trace rather than something a user can fix. Overriding a
string in ``cvme.toml`` is the repair.

Nothing here parses agent stdout. The agent is told to write files at given
paths, and cvme reads and validates those files afterwards; stdout is kept
only for diagnostics.
"""

from __future__ import annotations

import shutil
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from cvme.errors import CvmeError

AGENTS_PATH = Path(__file__).parent / "agents.toml"


class AgentError(CvmeError):
    exit_code = 5


class AgentSpec(BaseModel):
    """How to invoke one agent. Validated, because it comes from user TOML."""

    model_config = {"extra": "forbid", "frozen": True}

    name: str
    argv: list[str] = Field(default_factory=list)
    stdin: bool = False
    timeout: int = 900

    @property
    def writes_nothing(self) -> bool:
        """A spec with no argv only emits the prompt; it runs no agent."""
        return not self.argv

    @property
    def executable(self) -> str | None:
        return self.argv[0] if self.argv else None


@dataclass(frozen=True)
class AgentResult:
    returncode: int
    stdout: str
    stderr: str


def _spec(name: str, entry: dict[str, Any]) -> AgentSpec:
    try:
        return AgentSpec(name=name, **entry)
    except ValidationError as exc:
        raise AgentError(f"invalid [agents.{name}]: {exc}") from exc


def defaults() -> dict[str, AgentSpec]:
    data = tomllib.loads(AGENTS_PATH.read_text(encoding="utf-8"))
    return {name: _spec(name, entry) for name, entry in data.get("agents", {}).items()}


def resolve(name: str, overrides: dict[str, dict[str, Any]] | None = None) -> AgentSpec:
    """The named agent, with any cvme.toml override layered over the default."""
    specs = defaults()
    merged = dict(overrides or {})
    if name in merged:
        entry = dict(merged[name])
        if base := specs.get(name):
            entry = base.model_dump(exclude={"name"}) | entry
        return _spec(name, entry)
    if name not in specs:
        known = ", ".join(sorted(set(specs) | set(merged)))
        raise AgentError(f"unknown agent '{name}'; configured: {known}")
    return specs[name]


def render_argv(
    spec: AgentSpec, prompt: str, workdir: Path, prompt_file: Path
) -> list[str]:
    values = {
        "prompt": prompt,
        "workdir": str(workdir),
        "prompt_file": str(prompt_file),
    }
    return [arg.format(**values) for arg in spec.argv]


def probe(spec: AgentSpec) -> tuple[bool, str]:
    """Whether the agent's executable is on PATH, for ``cvme doctor``."""
    if spec.writes_nothing:
        return True, "writes the prompt to a file; runs nothing"
    executable = spec.executable
    assert executable is not None
    found = shutil.which(executable)
    return (bool(found), found or f"'{executable}' is not on PATH")


def run(spec: AgentSpec, prompt: str, workdir: Path, prompt_file: Path) -> AgentResult:
    """Invoke the agent, letting it write into ``workdir``."""
    if spec.writes_nothing:
        return AgentResult(0, "", "")
    argv = render_argv(spec, prompt, workdir, prompt_file)
    if shutil.which(argv[0]) is None:
        raise AgentError(
            f"'{argv[0]}' is not on PATH.\n"
            f"  Install it, point [agents.{spec.name}] at something else in "
            "cvme.toml,\n"
            "  or run with --agent none and paste the prompt into any assistant."
        )
    try:
        completed = subprocess.run(
            argv,
            input=prompt if spec.stdin else None,
            capture_output=True,
            text=True,
            cwd=workdir,
            timeout=spec.timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise AgentError(f"{spec.name} timed out after {spec.timeout}s") from exc
    except OSError as exc:
        raise AgentError(f"could not run {spec.name}: {exc}") from exc
    return AgentResult(completed.returncode, completed.stdout, completed.stderr)
