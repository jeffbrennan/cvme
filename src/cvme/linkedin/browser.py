"""A local browser, signed in as you, reading your own profile.

Read this before changing anything in it.

**This automates access LinkedIn's user agreement does not permit.** The
agreement prohibits automated access and does not carve out your own profile.
The risk is to your account, it is yours to accept, and cvme makes the
decision explicit rather than quiet: the browser is visible, you type your own
credentials into LinkedIn's own login form, and nothing here pretends to be
anything other than Chromium under automation.

What that last part means concretely, because it is a line worth stating:
**cvme does not attempt to evade detection.** No stealth patches, no
fingerprint masking, no spoofed user agent, no proxying. If LinkedIn presents
a challenge, the capture stops and tells you. Automating your own account is
one thing; defeating the controls that would notice is another, and the second
one is not in this file.

**Scope is your own profile and nothing else.** The session navigates to the
signed-in member's profile and verifies it is theirs by an element that only
renders on your own page. No target URL is accepted from the caller, so this
cannot be pointed at anybody else.

The session lives in its own Chromium profile under cvme's data directory,
never the everyday browser profile: Playwright's own guidance is to use a
separate automation profile, and a session cvme can delete is one you can
revoke without touching your real browser.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from cvme.errors import CvmeError
from cvme.linkedin.capture import Capture
from cvme.linkedin.dom import OWN_PROFILE_MARK, Reader

FEED_URL = "https://www.linkedin.com/feed/"
#: LinkedIn resolves this to the signed-in member's own profile, which is the
#: cheapest way to bind the capture to the account rather than to a URL.
OWN_PROFILE_URL = "https://www.linkedin.com/in/me/"
LOGIN_HOST = "linkedin.com/login"
CHECKPOINT = re.compile(r"/checkpoint/|/authwall|/uas/login")

_PROFILE_URL = re.compile(r"^https://[\w.]*linkedin\.com/in/[^/?#]+", re.IGNORECASE)

#: How long to let a human sign in and clear MFA, in milliseconds.
LOGIN_TIMEOUT_MS = 300_000
NAVIGATE_TIMEOUT_MS = 45_000


class BrowserError(CvmeError):
    exit_code = 11


def data_home() -> Path:
    """Where the browser session lives, honouring XDG and a test override."""
    if override := os.environ.get("CVME_DATA_HOME"):
        return Path(override)
    base = os.environ.get("XDG_DATA_HOME")
    return (Path(base) if base else Path.home() / ".local" / "share") / "cvme"


def session_dir() -> Path:
    return data_home() / "linkedin-browser"


def signed_in() -> bool:
    """Whether a session has been stored. Not whether it is still valid."""
    return session_dir().is_dir() and any(session_dir().iterdir())


def forget() -> bool:
    """Delete the stored session, cookies and all."""
    path = session_dir()
    if not path.is_dir():
        return False
    shutil.rmtree(path)
    return True


@contextmanager
def session(*, headless: bool = False) -> Iterator[Any]:
    """A Chromium page in cvme's own persistent profile.

    ``headless`` exists for the fixture tests, which drive the reader against
    local pages. A real capture runs visible: you have to be able to see the
    login form you are typing into, and a hidden browser doing things to your
    account is the wrong default whatever the automation.
    """
    playwright = _playwright()
    path = session_dir()
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(stat.S_IRWXU)  # it holds live session cookies

    with playwright() as driver:
        # No launch arguments. The flags that would go here are the ones that
        # hide automation, and this file does not do that.
        context = driver.chromium.launch_persistent_context(
            str(path),
            headless=headless,
            executable_path=os.environ.get("CVME_CHROMIUM") or None,
            viewport={"width": 1280, "height": 1400},
        )
        try:
            yield context.pages[0] if context.pages else context.new_page()
        finally:
            context.close()


def login(page: Any) -> None:
    """Put the login page in front of the user and wait for them to finish.

    cvme never types a credential. It navigates, then waits for LinkedIn to
    stop showing a login or challenge, which is the only signal it needs and
    the only one it is entitled to.
    """
    page.goto(FEED_URL, timeout=NAVIGATE_TIMEOUT_MS)
    if not _needs_login(page):
        return
    print(
        "Sign in to LinkedIn in the browser window, including any "
        "verification step.\nThis terminal will continue once you are through."
    )
    try:
        page.wait_for_url(
            lambda url: LOGIN_HOST not in url and not CHECKPOINT.search(url),
            timeout=LOGIN_TIMEOUT_MS,
        )
    except Exception as exc:
        raise BrowserError(
            "still on a LinkedIn login or verification page after "
            f"{LOGIN_TIMEOUT_MS // 1000}s; nothing was captured.\n"
            "  cvme does not work around a challenge -- complete it in the "
            "browser and run the command again."
        ) from exc


def own_profile(page: Any) -> str:
    """Navigate to the signed-in member's own profile, or refuse.

    Two checks, because either alone is weak. The URL must look like a profile
    URL, and the page must carry an element LinkedIn only renders for the
    profile's owner. A capture that cannot establish both stops: reading the
    wrong profile and calling it yours would put someone else's job history
    into your changeset.
    """
    page.goto(OWN_PROFILE_URL, timeout=NAVIGATE_TIMEOUT_MS)
    if _needs_login(page):
        raise BrowserError(
            "LinkedIn asked for a sign-in. Run `cvme linkedin login` first."
        )
    url = _canonical(page.url)
    if url is None:
        raise BrowserError(
            f"expected to land on a profile page, got {page.url}.\n"
            "  cvme will not guess a profile URL; it only reads the one "
            "LinkedIn resolves for the signed-in account."
        )
    if _count(page.locator(OWN_PROFILE_MARK)) == 0:
        raise BrowserError(
            f"{url} does not look like your own profile: none of the controls "
            "LinkedIn shows an owner are on it.\n"
            "  cvme reads your own profile only, and stops rather than guess."
        )
    return url


def capture(page: Any) -> Capture:
    """Read the signed-in member's profile."""
    url = own_profile(page)
    return Reader(page).capture(profile_url=url)


def _needs_login(page: Any) -> bool:
    return LOGIN_HOST in page.url or bool(CHECKPOINT.search(page.url))


def _canonical(url: str) -> str | None:
    match = _PROFILE_URL.match(url)
    return match.group(0) if match else None


def _playwright() -> Any:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise BrowserError(
            "the browser capture needs Playwright, which is an optional extra.\n"
            "  Install it with:\n"
            "    uv sync --extra browser && uv run playwright install chromium\n"
            "  Or use a source that needs no browser:\n"
            "    cvme linkedin check ~/Downloads/Profile.pdf"
        ) from exc
    return sync_playwright


def _count(locator: Any) -> int:
    try:
        return locator.count()
    except Exception:
        return 0
