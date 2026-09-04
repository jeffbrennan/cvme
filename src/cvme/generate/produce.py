"""One document, from prompt to PDF.

Both ``cvme tailor`` and ``cvme prep`` do the same four things to each
document: write the prompt out, let an agent write the file, verify what it
wrote, and render it only if verification passed. Keeping that here means the
gate cannot come loose on one path and hold on the other.
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from cvme.errors import VerificationFailed
from cvme.generate import agent as agents
from cvme.generate.bundle import Bundle
from cvme.md.parse import parse_file
from cvme.render.fit import fit as fit_pages
from cvme.style.schema import Style
from cvme.verify.check import verify_file
from cvme.verify.corpus import Corpus
from cvme.verify.report import Report

Echo = Callable[[str], None]


@dataclass
class Produced:
    document: str
    prompt_path: Path
    markdown: Path | None = None
    pdf: Path | None = None
    pages: int | None = None
    report: Report | None = None


def write_prompt(bundle: Bundle, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{bundle.document}.prompt.md"
    path.write_text(bundle.prompt, encoding="utf-8")
    return path


def generate(spec: agents.AgentSpec, bundle: Bundle, prompt_path: Path) -> None:
    """Run the agent in a staging directory and copy its output into place.

    The agent never sees the project. It is handed a temporary directory
    containing the prompt and nothing else, and its file is copied out only
    after the process has exited.
    """
    with tempfile.TemporaryDirectory(prefix=f"cvme-{bundle.document}-") as tmp:
        staging = Path(tmp)
        staged_prompt = staging / "prompt.md"
        staged_prompt.write_text(bundle.prompt, encoding="utf-8")
        result = agents.run(spec, bundle.prompt, staging, staged_prompt)
        if result.returncode != 0:
            raise agents.AgentError(
                f"{spec.name} exited {result.returncode}\n"
                f"{(result.stderr or result.stdout).strip()[:1200]}"
            )
        staged_output = staging / bundle.agent_output_path
        if not staged_output.is_file():
            raise agents.AgentError(
                f"{spec.name} did not write {bundle.agent_output_path}.\n"
                f"  The prompt is at {prompt_path} if you want to run it by hand."
            )
        bundle.output_path.parent.mkdir(parents=True, exist_ok=True)
        bundle.output_path.write_text(
            staged_output.read_text(encoding="utf-8"), encoding="utf-8"
        )


def gate(path: Path, corpus: Corpus, echo: Echo) -> Report:
    """Verify a generated document, removing a PDF it no longer matches."""
    report = verify_file(path, corpus, require_citations=True)
    echo(report.format())
    if not report.ok:
        # A PDF from an earlier run would now sit beside a rejected document
        # and could be sent in the belief that it matches.
        stale = path.with_suffix(".pdf")
        if stale.is_file():
            stale.unlink()
            echo(f"  removed {stale}, which no longer matches")
        raise VerificationFailed(
            f"{path} did not pass verification; it has not been rendered"
        )
    return report


def render(path: Path, style: Style, template: str) -> tuple[Path, int]:
    output = path.with_suffix(".pdf")
    result = fit_pages(parse_file(path), style, output=output, template=template)
    return output, result.pages


def produce(
    bundle: Bundle,
    spec: agents.AgentSpec,
    *,
    prompt_dir: Path,
    corpus: Corpus,
    style: Style,
    template: str,
    verify: bool,
    should_render: bool,
    echo: Echo,
) -> Produced:
    """Prompt, generate, verify, render. Any step may be turned off."""
    prompt_path = write_prompt(bundle, prompt_dir)
    if spec.writes_nothing:
        echo(f"wrote {prompt_path}")
        echo("  paste it into any assistant, then run 'cvme verify'")
        return Produced(bundle.document, prompt_path)

    echo(f"running {spec.name} for {bundle.document}...")
    generate(spec, bundle, prompt_path)
    echo(f"  wrote {bundle.output_path}")

    produced = Produced(bundle.document, prompt_path, markdown=bundle.output_path)
    if verify:
        produced.report = gate(bundle.output_path, corpus, echo)
    if should_render:
        pdf, pages = render(bundle.output_path, style, template)
        produced.pdf, produced.pages = pdf, pages
        echo(f"  wrote {pdf} ({pages} page{'s' * (pages != 1)})")
    return produced
