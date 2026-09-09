"""Session storage, own-profile binding, and the CLI's browser wiring.

The parts that can be tested without LinkedIn: where the session lives, that
it can be revoked, that a page which is not the signed-in member's own profile
is refused, and that `check` insists on exactly one source.
"""

from __future__ import annotations

import stat
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cvme.cli.app import app
from cvme.config import CONFIG_NAME
from cvme.linkedin import browser
from cvme.linkedin.capture import Capture, Section
from cvme.linkedin.model import Profile

runner = CliRunner()

CONFIG = '[documents.resume]\npath = "base/resume.md"\n'
RESUME = """\
---
name: Morgan Avery
---

## Experience

### Staff Data Engineer @ Northwind Analytics | Jul 2023 – Present

- Own ingestion for several hundred tenants
"""


@pytest.fixture(autouse=True)
def data_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Never touch the real ~/.local/share/cvme during a test run."""
    home = tmp_path / "data"
    monkeypatch.setenv("CVME_DATA_HOME", str(home))
    return home


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "docs"
    (root / "base").mkdir(parents=True)
    (root / "base" / "resume.md").write_text(RESUME, encoding="utf-8")
    (root / CONFIG_NAME).write_text(CONFIG, encoding="utf-8")
    return root


class TestSession:
    def test_it_lives_outside_the_project(self, data_home: Path) -> None:
        assert browser.session_dir() == data_home / "linkedin-browser"

    def test_nothing_is_stored_until_a_login(self) -> None:
        assert not browser.signed_in()

    def test_it_can_be_revoked_without_touching_a_real_browser(
        self, data_home: Path
    ) -> None:
        session = browser.session_dir()
        session.mkdir(parents=True)
        (session / "Cookies").write_bytes(b"session")
        assert browser.signed_in()
        assert browser.forget()
        assert not browser.signed_in()
        assert not browser.forget(), "revoking twice is not an error"


class TestOwnProfileBinding:
    """cvme reads the signed-in member's profile, and refuses anything else."""

    def test_a_page_that_is_not_a_profile_url_is_refused(self) -> None:
        page = _FakePage(url="https://www.linkedin.com/feed/", owner_marks=1)
        with pytest.raises(browser.BrowserError, match="will not guess"):
            browser.own_profile(page)

    def test_someone_elses_profile_is_refused(self) -> None:
        """No owner-only control on the page means it is not yours."""
        page = _FakePage(url="https://www.linkedin.com/in/someone-else/", owner_marks=0)
        with pytest.raises(browser.BrowserError, match="your own profile"):
            browser.own_profile(page)

    def test_your_own_profile_is_accepted_and_canonicalised(self) -> None:
        page = _FakePage(
            url="https://www.linkedin.com/in/morgan-avery/?trk=nav", owner_marks=1
        )
        assert browser.own_profile(page) == "https://www.linkedin.com/in/morgan-avery"

    def test_a_login_wall_says_to_log_in(self) -> None:
        page = _FakePage(url="https://www.linkedin.com/checkpoint/x", owner_marks=0)
        with pytest.raises(browser.BrowserError, match="linkedin login"):
            browser.own_profile(page)


class TestCheckWiring:
    def test_naming_no_source_is_refused(self, project: Path) -> None:
        result = _run(project, "check")
        assert result.exit_code != 0
        assert "name one source" in result.output

    def test_naming_two_sources_is_refused(self, project: Path) -> None:
        result = _run(project, "check", "somewhere.pdf", "--browser")
        assert result.exit_code != 0
        assert "name one source" in result.output

    def test_a_browser_capture_is_audited_like_any_other_source(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured = Capture(
            profile=Profile(headline="Staff Data Engineer at Northwind Analytics"),
            sections={"headline": Section(status="complete", found=1)},
            profile_url="https://www.linkedin.com/in/morgan-avery",
        )
        _fake_capture(monkeypatch, captured)
        result = _run(project, "check", "--browser")
        assert result.exit_code == 0, result.output
        assert "browser capture" in result.output
        assert "not checked" in result.output, (
            "a headline-only capture must say what it did not look at"
        )

    def test_a_capture_that_could_not_read_a_section_reports_no_drift(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The whole point of the status type, exercised through the CLI."""
        _fake_capture(
            monkeypatch,
            Capture(
                profile=Profile(),
                sections={"experience": Section(status="unavailable", note="timeout")},
            ),
        )
        result = _run(project, "check", "--browser")
        assert result.exit_code == 0, result.output
        assert "matches your documents" in result.output


def _fake_capture(monkeypatch: pytest.MonkeyPatch, captured: Capture) -> None:
    """Stand in for the browser, so the wiring is tested without LinkedIn."""
    import contextlib

    @contextlib.contextmanager
    def session(**_: object):
        yield object()

    monkeypatch.setattr(browser, "session", session)
    monkeypatch.setattr(browser, "capture", lambda _page: captured)


def _run(project: Path, *args: str):
    return runner.invoke(
        app, ["linkedin", *args, "--config", str(project / CONFIG_NAME)]
    )


class _FakePage:
    """Just enough page for the navigation checks."""

    def __init__(self, url: str, owner_marks: int):
        self.url = url
        self._marks = owner_marks

    def goto(self, url: str, timeout: float | None = None) -> None:
        del url, timeout

    def locator(self, selector: str) -> _FakeLocator:
        del selector
        return _FakeLocator(self._marks)


class _FakeLocator:
    def __init__(self, count: int):
        self._count = count

    def count(self) -> int:
        return self._count


def test_the_session_directory_is_private(data_home: Path) -> None:
    """It holds live LinkedIn session cookies."""
    session = browser.session_dir()
    session.mkdir(parents=True)
    session.chmod(stat.S_IRWXU)
    assert stat.S_IMODE(session.stat().st_mode) == 0o700
