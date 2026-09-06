"""OAuth credentials, held locally.

The rules this file is written to, in the order they mattered:

* **Nothing secret goes in the project.** ``cvme.toml`` is committed; a client
  secret is not. Credentials live under the user's config directory, and the
  project only ever names which profile to use.
* **The filesystem is the boundary.** The directory is created ``0700`` and
  the file ``0600``, and a file that is readable by anyone else is refused
  rather than used, because a token that leaked is not fixed by reading it.
* **The token is short-lived and the secret is not.** Both are here, so both
  are handled the same way, and ``logout`` can drop the token without making
  the user find their client secret again.
* **A secret never reaches a log, an error, or a terminal.** ``Credentials``
  redacts on dump, and the flow prints a URL and nothing else.

The flow itself is the authorization code grant with a loopback redirect,
which is what LinkedIn offers: it is a confidential client, so there is a
client secret and no PKCE to use instead. The ``state`` parameter is random
per run and compared before the code is exchanged.
"""

from __future__ import annotations

import http.server
import json
import os
import secrets
import stat
import threading
import urllib.parse
import webbrowser
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, Field

from cvme.errors import CvmeError

AUTHORIZE_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"

#: What a self-serve LinkedIn app can actually ask for. Writing to profile
#: sections needs a permission granted through a partner programme, which is
#: why the scope list is configuration rather than a constant: cvme cannot
#: know the name of a scope your agreement gave you.
DEFAULT_SCOPES = ("openid", "profile", "email")

#: Fixed, because LinkedIn matches the redirect URL exactly against the one
#: registered on the app. A random port would mean re-registering per run.
DEFAULT_PORT = 8723
REDIRECT_PATH = "/callback"

#: Refresh this long before the token actually expires, so a sync that takes a
#: minute does not fail halfway through with a token that was valid at the
#: start.
EXPIRY_SKEW = timedelta(minutes=5)

_TIMEOUT = 20.0
_LOGIN_TIMEOUT = 300.0


class AuthError(CvmeError):
    exit_code = 9


class Token(BaseModel):
    access_token: str
    refresh_token: str = ""
    expires_at: datetime | None = None
    scopes: list[str] = Field(default_factory=list)

    def expired(self, *, at: datetime | None = None) -> bool:
        if self.expires_at is None:
            return False
        return (at or datetime.now(UTC)) + EXPIRY_SKEW >= self.expires_at


class Credentials(BaseModel):
    """One LinkedIn app, and the token it last obtained."""

    client_id: str = ""
    client_secret: str = ""
    port: int = DEFAULT_PORT
    scopes: list[str] = Field(default_factory=lambda: list(DEFAULT_SCOPES))
    token: Token | None = None
    #: The member the token belongs to, cached after the first ``userinfo``
    #: call because every Profile Edit URL contains it.
    person_id: str = ""

    @property
    def redirect_uri(self) -> str:
        return f"http://localhost:{self.port}{REDIRECT_PATH}"

    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def redacted(self) -> dict[str, Any]:
        """Everything about this app that is safe to print."""
        return {
            "client_id": _mask(self.client_id),
            "client_secret": "set" if self.client_secret else "not set",
            "redirect_uri": self.redirect_uri,
            "scopes": " ".join(self.scopes),
            "token": _token_status(self.token),
            "person_id": self.person_id or "unknown",
        }


def config_home() -> Path:
    """Where credentials live, honouring the XDG variable and a test override."""
    if override := os.environ.get("CVME_CONFIG_HOME"):
        return Path(override)
    base = os.environ.get("XDG_CONFIG_HOME")
    return (Path(base) if base else Path.home() / ".config") / "cvme"


def credentials_path() -> Path:
    return config_home() / "linkedin.json"


def load() -> Credentials:
    """Read the stored credentials, letting the environment win.

    The environment override exists for CI and for anyone who would rather
    keep the secret in a password manager and export it, which is a better
    habit than a file and should not be made harder than using the file.
    """
    path = credentials_path()
    stored = Credentials()
    if path.is_file():
        _refuse_loose_permissions(path)
        try:
            stored = Credentials.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise AuthError(f"{path}: cannot read credentials ({exc})") from exc
    stored.client_id = os.environ.get("CVME_LINKEDIN_CLIENT_ID", stored.client_id)
    stored.client_secret = os.environ.get(
        "CVME_LINKEDIN_CLIENT_SECRET", stored.client_secret
    )
    return stored


def save(credentials: Credentials) -> Path:
    """Write credentials with the permissions they need, and no wider."""
    path = credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(stat.S_IRWXU)
    # Opened through os.open so the file is never, even briefly, readable by
    # anyone else: chmod after the fact leaves a window where it is.
    descriptor = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR
    )
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(credentials.model_dump(mode="json"), handle, indent=2)
        handle.write("\n")
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return path


def forget_token() -> bool:
    """Drop the token, keeping the app registration."""
    credentials = load()
    if credentials.token is None:
        return False
    credentials.token = None
    save(credentials)
    return True


def authorize(credentials: Credentials, *, open_browser: bool = True) -> Credentials:
    """Run the three-legged flow and store the token that comes back."""
    if not credentials.configured():
        raise AuthError("no LinkedIn app configured. Run `cvme linkedin setup` first.")
    state = secrets.token_urlsafe(32)
    query = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": credentials.client_id,
            "redirect_uri": credentials.redirect_uri,
            "state": state,
            "scope": " ".join(credentials.scopes),
        }
    )
    url = f"{AUTHORIZE_URL}?{query}"
    with _Callback(credentials.port) as server:
        if open_browser:
            webbrowser.open(url)
        print(f"Authorise cvme in your browser:\n  {url}\n")
        code = server.wait(state)

    credentials.token = _exchange(credentials, code)
    return credentials


def access_token(credentials: Credentials) -> str:
    """A usable token, refreshed if it is close to expiring.

    Refreshing mutates and re-saves the credentials, because a refresh token
    LinkedIn rotated and cvme did not record is a login the user has to do
    again for no reason.
    """
    token = credentials.token
    if token is None:
        raise AuthError("not logged in. Run `cvme linkedin login`.")
    if not token.expired():
        return token.access_token
    if not token.refresh_token:
        raise AuthError(
            "the access token has expired and this app has no refresh token.\n"
            "  Refresh tokens are granted to approved apps only; run "
            "`cvme linkedin login` to get a new one."
        )
    credentials.token = _refresh(credentials, token.refresh_token)
    save(credentials)
    return credentials.token.access_token


def _exchange(credentials: Credentials, code: str) -> Token:
    return _token_request(
        credentials,
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": credentials.redirect_uri,
        },
    )


def _refresh(credentials: Credentials, refresh_token: str) -> Token:
    token = _token_request(
        credentials,
        {"grant_type": "refresh_token", "refresh_token": refresh_token},
    )
    # LinkedIn does not always return the refresh token on a refresh; losing it
    # here would turn the next expiry into a re-login.
    if not token.refresh_token:
        token.refresh_token = refresh_token
    return token


def _token_request(credentials: Credentials, form: dict[str, str]) -> Token:
    payload = {
        **form,
        "client_id": credentials.client_id,
        "client_secret": credentials.client_secret,
    }
    try:
        response = httpx.post(TOKEN_URL, data=payload, timeout=_TIMEOUT)
    except httpx.HTTPError as exc:
        raise AuthError(f"could not reach LinkedIn: {exc}") from exc
    if response.status_code != 200:
        raise AuthError(f"LinkedIn refused the token request: {_reason(response)}")
    try:
        data = response.json()
    except ValueError as exc:
        raise AuthError("LinkedIn returned a token response that is not JSON") from exc

    expires_in = data.get("expires_in")
    return Token(
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token", ""),
        expires_at=(
            datetime.now(UTC) + timedelta(seconds=int(expires_in))
            if expires_in
            else None
        ),
        scopes=str(data.get("scope", "")).split(),
    )


def _reason(response: httpx.Response) -> str:
    """A server's complaint, without echoing whatever we sent it.

    LinkedIn's error bodies are short and do not contain the request, but this
    is the one place a secret could plausibly be reflected back into a message
    the user pastes into an issue, so only the two named fields are read.
    """
    try:
        body = response.json()
    except ValueError:
        return f"HTTP {response.status_code}"
    described = body.get("error_description") or body.get("error") or ""
    return f"HTTP {response.status_code} {described}".strip()


class _Callback:
    """A loopback server that accepts exactly one redirect.

    Bound to 127.0.0.1 rather than all interfaces: the authorization code is
    in the URL, and the machine's network should not get a chance to see it.
    """

    def __init__(self, port: int):
        self.port = port
        self.result: dict[str, str] = {}
        self.received = threading.Event()

    def __enter__(self) -> _Callback:
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path != REDIRECT_PATH:
                    self.send_error(404)
                    return
                query = urllib.parse.parse_qs(parsed.query)
                outer.result = {k: v[0] for k, v in query.items()}
                outer.received.set()
                body = _CLOSING_PAGE.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: Any) -> None:
                """Silence the default stderr logging: the URL holds the code."""

        try:
            self.server = http.server.HTTPServer(("127.0.0.1", self.port), Handler)
        except OSError as exc:
            raise AuthError(
                f"cannot listen on {self.port} for the OAuth redirect: {exc}.\n"
                "  Close whatever is using the port, or pick another with "
                "`cvme linkedin setup --port`, and register the matching "
                "redirect URL on your LinkedIn app."
            ) from exc
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.server.shutdown()
        self.server.server_close()

    def wait(self, state: str) -> str:
        """Block for the redirect, then check it before trusting the code."""
        if not self.received.wait(timeout=_LOGIN_TIMEOUT):
            raise AuthError(
                f"no redirect from LinkedIn within {int(_LOGIN_TIMEOUT)}s; "
                "nothing was changed"
            )
        if error := self.result.get("error"):
            described = self.result.get("error_description", "")
            raise AuthError(f"LinkedIn declined the authorisation: {error} {described}")
        # Constant-time, because the comparison is the whole of the CSRF
        # defence and it runs against a value an attacker chose.
        if not secrets.compare_digest(self.result.get("state", ""), state):
            raise AuthError(
                "the redirect did not carry the state cvme sent; "
                "the authorisation was discarded"
            )
        if not (code := self.result.get("code", "")):
            raise AuthError("the redirect carried no authorisation code")
        return code


_CLOSING_PAGE = """<!doctype html>
<title>cvme</title>
<p style="font: 16px system-ui; margin: 3rem">
cvme is authorised. You can close this tab and return to the terminal.
</p>
"""


def _mask(value: str) -> str:
    return f"...{value[-4:]}" if len(value) > 4 else "set" if value else "not set"


def _token_status(token: Token | None) -> str:
    if token is None:
        return "none"
    if token.expires_at is None:
        return "present"
    if token.expired():
        return f"expired {token.expires_at:%Y-%m-%d}"
    return f"valid until {token.expires_at:%Y-%m-%d}"


def _refuse_loose_permissions(path: Path) -> None:
    """Refuse a credentials file other users on the machine can read.

    Checked on every read rather than fixed silently: a file that has been
    world-readable may already have been read, and repairing the mode would
    hide that it ever happened.
    """
    if os.name == "nt":  # pragma: no cover - POSIX modes do not apply
        return
    mode = path.stat().st_mode
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise AuthError(
            f"{path} is readable by other users (mode {stat.filemode(mode)}).\n"
            "  It holds a client secret and an access token. Fix it with:\n"
            f"    chmod 600 {path}\n"
            "  and consider the credentials compromised: rotate the client "
            "secret in the LinkedIn developer portal."
        )
