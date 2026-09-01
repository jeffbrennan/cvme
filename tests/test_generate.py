"""Prompt assembly and the agent adapter."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from cvme.config import GenerateConfig
from cvme.generate import agent as agents
from cvme.generate.bundle import build
from cvme.style.schema import resolve as resolve_style
from tests.conftest import FIXTURES

FACTS = [FIXTURES / "facts" / "skills.md", FIXTURES / "facts" / "metrics.md"]


@pytest.fixture
def job(tmp_path: Path) -> Path:
    path = tmp_path / "job.md"
    path.write_text("---\ntitle: Staff Data Engineer\n---\n\nOwn ingestion.\n")
    return path


def bundle_for(template: str, job: Path, tmp_path: Path):
    return build(
        document=template,
        template=template,
        base_path=FIXTURES / f"{template}.md",
        job_path=job,
        facts=FACTS,
        output_path=tmp_path / f"{template}.md",
        style=resolve_style("standard"),
        generate=GenerateConfig(),
    )


def test_the_prompt_carries_everything_the_agent_may_draw_on(job: Path, tmp_path: Path):
    prompt = bundle_for("resume", job, tmp_path).prompt
    for section in ("# JOB POSTING", "# FACTS", "# BASE DOCUMENT", "# GRAMMAR"):
        assert section in prompt
    assert "Own ingestion." in prompt  # the posting
    assert "m-events" in prompt  # a fact id
    assert "Morgan Avery" in prompt  # the base document
    assert "### Left \\| Right" in prompt or "Left \\| Right" in prompt  # the grammar


def test_the_grammar_is_embedded_verbatim(job: Path, tmp_path: Path):
    """So that what writes these documents and what parses them cannot drift."""
    from cvme.generate.bundle import GRAMMAR

    prompt = bundle_for("resume", job, tmp_path).prompt
    body = GRAMMAR.read_text().strip()
    assert body[:400] in prompt


def test_the_rules_are_always_present(job: Path, tmp_path: Path):
    for template in ("resume", "cover_letter"):
        prompt = bundle_for(template, job, tmp_path).prompt
        assert "Em dashes" in prompt
        assert "does not license" in prompt


def test_a_letter_prompt_omits_the_resume_grammar(job: Path, tmp_path: Path):
    assert "# GRAMMAR" not in bundle_for("cover_letter", job, tmp_path).prompt


def test_budgets_are_interpolated_from_config(job: Path, tmp_path: Path):
    prompt = build(
        document="resume",
        template="resume",
        base_path=FIXTURES / "resume.md",
        job_path=job,
        facts=FACTS,
        output_path=tmp_path / "r.md",
        style=resolve_style("standard"),
        generate=GenerateConfig(min_bullets=1, max_bullets=3, max_bullet_words=20),
    ).prompt
    assert "Between 1 and 3 bullets" in prompt
    assert "20 words" in prompt


def test_the_output_path_is_stated_explicitly(job: Path, tmp_path: Path):
    """Nothing parses agent stdout; the contract is a file at a named path."""
    bundle = bundle_for("resume", job, tmp_path)
    assert str(bundle.output_path) in bundle.prompt


def test_a_missing_job_file_is_reported(tmp_path: Path):
    from cvme.errors import ConfigError

    with pytest.raises(ConfigError, match="job posting not found"):
        build(
            document="resume",
            template="resume",
            base_path=FIXTURES / "resume.md",
            job_path=tmp_path / "nope.md",
            facts=[],
            output_path=tmp_path / "r.md",
            style=resolve_style("standard"),
            generate=GenerateConfig(),
        )


# --- the agent adapter ----------------------------------------------------


def test_the_shipped_agents_all_parse() -> None:
    specs = agents.defaults()
    assert {"codex", "opencode", "none"} <= set(specs)
    assert specs["codex"].stdin is True


def test_placeholders_are_substituted() -> None:
    argv = agents.render_argv(
        agents.resolve("codex"), "THE PROMPT", Path("/w"), Path("/w/p.md")
    )
    assert argv == ["codex", "exec", "--cd", "/w", "-"]
    assert "{" not in " ".join(argv)


def test_config_overrides_layer_over_the_default() -> None:
    """Flags change; overriding a string in cvme.toml is the repair."""
    spec = agents.resolve(
        "codex", {"codex": {"argv": ["codex", "exec", "--model", "x"]}}
    )
    assert spec.argv == ["codex", "exec", "--model", "x"]
    assert spec.stdin is True, "unspecified keys keep the packaged default"


def test_a_new_agent_can_be_defined_entirely_in_config() -> None:
    spec = agents.resolve("mine", {"mine": {"argv": ["my-tool", "{prompt_file}"]}})
    assert spec.argv == ["my-tool", "{prompt_file}"]


def test_an_unknown_agent_lists_the_known_ones() -> None:
    with pytest.raises(agents.AgentError, match="codex"):
        agents.resolve("nope")


def test_an_invalid_agent_table_is_rejected() -> None:
    with pytest.raises(agents.AgentError, match="invalid"):
        agents.resolve("bad", {"bad": {"argv": "not-a-list"}})


def test_the_none_agent_runs_nothing() -> None:
    spec = agents.resolve("none")
    assert spec.writes_nothing
    assert agents.probe(spec)[0] is True
    assert agents.run(spec, "p", Path("."), Path("p.md")).returncode == 0


def test_a_missing_executable_says_what_to_do(tmp_path: Path) -> None:
    spec = agents.resolve("x", {"x": {"argv": ["definitely-not-installed-xyz"]}})
    with pytest.raises(agents.AgentError, match="--agent none"):
        agents.run(spec, "p", tmp_path, tmp_path / "p.md")


def test_the_agent_runs_in_the_working_directory(tmp_path: Path) -> None:
    spec = agents.resolve(
        "stub",
        {
            "stub": {
                "argv": [
                    sys.executable,
                    "-c",
                    "import pathlib; pathlib.Path('out.txt').write_text('hi')",
                ]
            }
        },
    )
    result = agents.run(spec, "prompt", tmp_path, tmp_path / "p.md")
    assert result.returncode == 0
    assert (tmp_path / "out.txt").read_text() == "hi"


def test_stdin_delivery_reaches_the_agent(tmp_path: Path) -> None:
    spec = agents.resolve(
        "stub",
        {
            "stub": {
                "argv": [
                    sys.executable,
                    "-c",
                    "import sys, pathlib\n"
                    "pathlib.Path('got.txt').write_text(sys.stdin.read())",
                ],
                "stdin": True,
            }
        },
    )
    agents.run(spec, "THE PROMPT", tmp_path, tmp_path / "p.md")
    assert (tmp_path / "got.txt").read_text() == "THE PROMPT"


def test_a_timeout_is_reported_as_an_agent_error(tmp_path: Path) -> None:
    spec = agents.resolve(
        "slow",
        {
            "slow": {
                "argv": [sys.executable, "-c", "import time; time.sleep(5)"],
                "timeout": 1,
            }
        },
    )
    with pytest.raises(agents.AgentError, match="timed out"):
        agents.run(spec, "p", tmp_path, tmp_path / "p.md")
