"""The overlay, the diff, and the state that makes the sync incremental."""

from __future__ import annotations

from pathlib import Path

import pytest

from cvme.config import Config, DocumentConfig
from cvme.errors import ConfigError
from cvme.linkedin import state as sync_state
from cvme.linkedin import sync
from cvme.linkedin.diff import diff
from cvme.linkedin.model import MonthYear, Position, Profile, Skill
from cvme.linkedin.overlay import merge
from cvme.linkedin.project import to_profile
from cvme.md.parse import parse

BASE = """\
---
name: Morgan Avery
---

## Summary

The short summary that fits a page.

## Experience

### Staff Data Engineer @ Northwind Analytics | Jul 2023 – Present

- One bullet
- Two bullets

### Data Engineer @ GreyHarbor Health | Dec 2020 – Jul 2023

- Untouched by the overlay

## Skills

- **Languages**: Python, SQL
"""

OVERLAY = """\
---
headline: Staff Data Engineer | Streaming platforms
---

## Summary

The long summary, which has no page to fit.

## Experience

### Staff Data Engineer @ Northwind Analytics | Jul 2023 – Present

- One bullet
- Two bullets
- Three bullets the page had no room for
"""


class TestOverlay:
    def test_no_overlay_leaves_the_document_alone(self) -> None:
        base = parse(BASE)
        assert merge(base, None) is base

    def test_a_matched_entry_is_replaced_not_duplicated(self) -> None:
        profile, _ = to_profile(merge(parse(BASE), parse(OVERLAY)))
        assert len(profile.positions) == 2, "the overlay patches, it does not append"
        assert profile.positions[0].description.count("•") == 3

    def test_an_unmentioned_entry_survives(self) -> None:
        profile, _ = to_profile(merge(parse(BASE), parse(OVERLAY)))
        assert profile.positions[1].company == "GreyHarbor Health"
        assert "Untouched" in profile.positions[1].description

    def test_the_overlay_replaces_prose_rather_than_appending_to_it(self) -> None:
        profile, _ = to_profile(merge(parse(BASE), parse(OVERLAY)))
        assert profile.summary == "The long summary, which has no page to fit."

    def test_frontmatter_from_the_overlay_wins(self) -> None:
        profile, _ = to_profile(merge(parse(BASE), parse(OVERLAY)))
        assert profile.headline == "Staff Data Engineer | Streaming platforms"

    def test_a_section_only_the_overlay_has_is_added(self) -> None:
        extra = "## Education\n\n### Ridgeway University\n#### BSc | May 2018\n"
        profile, _ = to_profile(merge(parse(BASE), parse(extra)))
        assert [e.school for e in profile.educations] == ["Ridgeway University"]

    def test_matching_ignores_the_end_date(self) -> None:
        """The role you still hold is the one an overlay is most likely to extend."""
        left = OVERLAY.replace("Jul 2023 – Present", "Jul 2023 – Sep 2026")
        profile, _ = to_profile(merge(parse(BASE), parse(left)))
        assert len(profile.positions) == 2

    def test_a_different_start_date_is_a_different_stint(self) -> None:
        rejoined = OVERLAY.replace("Jul 2023 – Present", "Jan 2019 – Dec 2020")
        profile, _ = to_profile(merge(parse(BASE), parse(rejoined)))
        assert len(profile.positions) == 3


class TestDiff:
    def test_an_unchanged_profile_produces_nothing(self) -> None:
        profile, _ = to_profile(parse(BASE))
        assert not diff(profile, profile)

    def test_the_first_run_offers_the_whole_profile(self) -> None:
        profile, _ = to_profile(parse(BASE))
        changeset = diff(profile, Profile())
        assert {c.action for c in changeset.changes} == {"set", "add"}

    def test_one_edited_bullet_is_one_change(self) -> None:
        before, _ = to_profile(parse(BASE))
        after, _ = to_profile(parse(BASE.replace("Two bullets", "Two better bullets")))
        (change,) = diff(after, before).changes
        assert change.action == "update"
        assert change.fields == ["description"]
        assert change.label == "Staff Data Engineer @ Northwind Analytics"

    def test_the_long_field_is_kept_apart_from_the_short_ones(self) -> None:
        before, _ = to_profile(parse(BASE))
        after, _ = to_profile(parse(BASE.replace("Two bullets", "Two better bullets")))
        (change,) = diff(after, before).changes
        assert "description:" not in change.after, "the body is carried separately"
        assert "• Two better bullets" in change.after_body
        assert "dates: Jul 2023 – Present" in change.after

    def test_skills_are_a_set(self) -> None:
        mine = Profile(skills=[Skill(name="Python"), Skill(name="Rust")])
        theirs = Profile(skills=[Skill(name="Rust"), Skill(name="Python")])
        assert not diff(mine, theirs), "order is LinkedIn's to choose, not cvme's"

    def test_removals_come_after_additions(self) -> None:
        kept = Position(title="A", company="B", start=MonthYear(year=2020))
        gone = Position(title="C", company="D", start=MonthYear(year=2019))
        changes = diff(Profile(positions=[kept]), Profile(positions=[gone])).changes
        assert [c.action for c in changes] == ["add", "remove"]

    def test_summary_counts_by_action(self) -> None:
        profile, _ = to_profile(parse(BASE))
        assert diff(profile, profile).summary() == "no changes"
        assert "to add" in diff(profile, Profile()).summary()


class TestPlan:
    def test_the_overlay_is_found_beside_the_resume_without_configuration(
        self, project: Config
    ) -> None:
        (project.root / "base" / "linkedin.md").write_text(OVERLAY, encoding="utf-8")
        plan = sync.build(project)
        assert plan.overlay == project.root / "base" / "linkedin.md"
        assert plan.profile.positions[0].description.count("•") == 3

    def test_no_overlay_file_is_not_an_error(self, project: Config) -> None:
        assert sync.build(project).overlay is None

    def test_a_configured_overlay_that_is_missing_is_an_error(
        self, project: Config
    ) -> None:
        project.linkedin.overlay = project.root / "nowhere.md"
        with pytest.raises(ConfigError, match="no such file"):
            sync.build(project)

    def test_fields_the_config_excludes_never_diff(self, project: Config) -> None:
        project.linkedin.fields = ["headline", "summary"]
        plan = sync.build(project)
        assert plan.profile.skills == []
        assert not plan.changeset.of("skill", "position")

    def test_recording_makes_the_next_plan_empty(self, project: Config) -> None:
        first = sync.build(project)
        assert first.changeset
        sync.record(project, first)
        assert not sync.build(project).changeset

    def test_an_edit_after_recording_shows_only_that_edit(
        self, project: Config
    ) -> None:
        sync.record(project, sync.build(project))
        source = project.root / "base" / "resume.md"
        source.write_text(BASE.replace("One bullet", "One better bullet"), "utf-8")
        (change,) = sync.build(project).changeset.changes
        assert change.action == "update"

    def test_an_over_long_field_blocks_the_plan(self, project: Config) -> None:
        source = project.root / "base" / "resume.md"
        source.write_text(BASE.replace("- One bullet", f"- {'x' * 2100}"), "utf-8")
        plan = sync.build(project)
        assert plan.blocked
        assert "over the limit" in str(plan.violations[0])


class TestState:
    def test_an_absent_state_reads_as_never_synced(self, tmp_path: Path) -> None:
        state = sync_state.load(tmp_path)
        assert not state.recorded
        assert state.profile == Profile()

    def test_a_corrupt_state_is_an_error_rather_than_a_silent_reset(
        self, tmp_path: Path
    ) -> None:
        """A reset would quietly re-push every field of the profile."""
        path = sync_state.path_for(tmp_path)
        path.parent.mkdir(parents=True)
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(sync_state.SyncStateError, match="cannot read"):
            sync_state.load(tmp_path)

    def test_saving_round_trips(self, tmp_path: Path) -> None:
        profile = Profile(headline="Staff Data Engineer")
        sync_state.save(tmp_path, profile)
        state = sync_state.load(tmp_path)
        assert state.profile == profile
        assert state.recorded

    def test_clearing_forgets_it(self, tmp_path: Path) -> None:
        sync_state.save(tmp_path, Profile())
        assert sync_state.clear(tmp_path)
        assert not sync_state.clear(tmp_path), "clearing twice is not an error"
        assert not sync_state.load(tmp_path).recorded


@pytest.fixture
def project(tmp_path: Path) -> Config:
    """A minimal project whose resume is ``BASE``."""
    (tmp_path / "base").mkdir()
    (tmp_path / "base" / "resume.md").write_text(BASE, encoding="utf-8")
    return Config(
        root=tmp_path,
        documents={"resume": DocumentConfig(path=tmp_path / "base" / "resume.md")},
    )
