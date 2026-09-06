"""Credential handling and the Profile Edit API client."""

from __future__ import annotations

import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from cvme.linkedin import auth
from cvme.linkedin.client import Client, LinkedInAPIError
from cvme.linkedin.model import Education, MonthYear, Position, Skill

SECRET = "wpl_ap1_supersecret"


@pytest.fixture(autouse=True)
def config_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Never touch the real ~/.config/cvme during a test run."""
    monkeypatch.setenv("CVME_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.delenv("CVME_LINKEDIN_CLIENT_ID", raising=False)
    monkeypatch.delenv("CVME_LINKEDIN_CLIENT_SECRET", raising=False)
    return tmp_path / "config"


class TestCredentialFile:
    def test_it_is_written_readable_only_by_its_owner(self) -> None:
        path = auth.save(auth.Credentials(client_id="a", client_secret=SECRET))
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700

    def test_it_round_trips(self) -> None:
        auth.save(auth.Credentials(client_id="a", client_secret=SECRET, port=9000))
        loaded = auth.load()
        assert (loaded.client_id, loaded.client_secret) == ("a", SECRET)
        assert loaded.redirect_uri == "http://localhost:9000/callback"

    def test_a_world_readable_file_is_refused_rather_than_repaired(self) -> None:
        """It may already have been read; fixing the mode would hide that."""
        path = auth.save(auth.Credentials(client_id="a", client_secret=SECRET))
        path.chmod(0o644)
        with pytest.raises(auth.AuthError, match="readable by other users"):
            auth.load()

    def test_the_environment_wins_over_the_file(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        auth.save(auth.Credentials(client_id="stored", client_secret="stored"))
        monkeypatch.setenv("CVME_LINKEDIN_CLIENT_SECRET", "from-env")
        assert auth.load().client_secret == "from-env"

    def test_no_file_is_not_an_error(self) -> None:
        assert not auth.load().configured()

    def test_logout_keeps_the_app_registration(self) -> None:
        auth.save(
            auth.Credentials(
                client_id="a", client_secret=SECRET, token=auth.Token(access_token="t")
            )
        )
        assert auth.forget_token()
        assert not auth.forget_token(), "forgetting twice is not an error"
        assert auth.load().client_id == "a"


class TestRedaction:
    def test_the_secret_is_never_in_what_gets_printed(self) -> None:
        credentials = auth.Credentials(client_id="7712abcd", client_secret=SECRET)
        shown = credentials.redacted()
        assert SECRET not in str(shown)
        assert shown["client_secret"] == "set"
        assert shown["client_id"] == "...abcd"

    def test_an_unset_secret_says_so(self) -> None:
        assert auth.Credentials().redacted()["client_secret"] == "not set"


class TestToken:
    def test_a_token_without_an_expiry_never_expires(self) -> None:
        assert not auth.Token(access_token="t").expired()

    def test_a_token_expiring_within_the_skew_counts_as_expired(self) -> None:
        soon = datetime.now(UTC) + auth.EXPIRY_SKEW - timedelta(minutes=1)
        assert auth.Token(access_token="t", expires_at=soon).expired()

    def test_a_fresh_token_does_not(self) -> None:
        later = datetime.now(UTC) + timedelta(days=30)
        assert not auth.Token(access_token="t", expires_at=later).expired()

    def test_no_token_at_all_is_a_clear_error(self) -> None:
        with pytest.raises(auth.AuthError, match="linkedin login"):
            auth.access_token(auth.Credentials(client_id="a", client_secret=SECRET))

    def test_an_expired_token_with_no_refresh_says_what_to_do(self) -> None:
        past = datetime.now(UTC) - timedelta(days=1)
        credentials = auth.Credentials(
            client_id="a",
            client_secret=SECRET,
            token=auth.Token(access_token="t", expires_at=past),
        )
        with pytest.raises(auth.AuthError, match="no refresh token"):
            auth.access_token(credentials)


class TestCallback:
    """The CSRF check, exercised without standing up a browser."""

    def test_a_mismatched_state_discards_the_code(self) -> None:
        callback = auth._Callback(0)
        callback.result = {"code": "stolen", "state": "attacker"}
        callback.received.set()
        with pytest.raises(auth.AuthError, match="did not carry the state"):
            callback.wait("ours")

    def test_a_matching_state_yields_the_code(self) -> None:
        callback = auth._Callback(0)
        callback.result = {"code": "good", "state": "ours"}
        callback.received.set()
        assert callback.wait("ours") == "good"

    def test_a_declined_authorisation_is_reported(self) -> None:
        callback = auth._Callback(0)
        callback.result = {"error": "user_cancelled_login", "state": "ours"}
        callback.received.set()
        with pytest.raises(auth.AuthError, match="declined"):
            callback.wait("ours")

    def test_authorize_refuses_without_an_app(self) -> None:
        with pytest.raises(auth.AuthError, match="linkedin setup"):
            auth.authorize(auth.Credentials())


class TestClient:
    def test_a_created_entity_returns_the_id_linkedin_assigned(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(201, headers={"x-linkedin-id": "urn:pos:1"})

        with _client(handler) as client:
            created = client.create(
                "position",
                Position(
                    title="Staff DE",
                    company="Northwind",
                    description="• a",
                    start=MonthYear(year=2023, month=7),
                ),
            )
        assert created == "urn:pos:1"
        (request,) = seen
        assert request.url.path == "/v2/people/id=ME/positions"
        assert request.headers["X-Restli-Protocol-Version"] == "2.0.0"
        assert request.headers["Authorization"] == "Bearer tok"

    def test_text_fields_are_sent_localized_and_dates_are_not(self) -> None:
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            import json

            captured.update(json.loads(request.content))
            return httpx.Response(201, headers={"x-linkedin-id": "1"})

        with _client(handler) as client:
            client.create(
                "position",
                Position(
                    title="Staff DE", company="N", start=MonthYear(year=2023, month=7)
                ),
            )
        assert captured["title"] == {
            "localized": {"en_US": "Staff DE"},
            "preferredLocale": {"country": "US", "language": "en"},
        }
        assert captured["startMonthYear"] == {"year": 2023, "month": 7}

    def test_an_update_is_wrapped_in_the_patch_envelope(self) -> None:
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            import json

            captured.update(json.loads(request.content))
            return httpx.Response(204)

        with _client(handler) as client:
            client.update("skill", "urn:s:1", Skill(name="Rust"))
        assert captured == {"patch": {"$set": {"name": "Rust"}}}

    def test_fields_cvme_does_not_write_are_absent_not_blank(self) -> None:
        """A partial update must not blank what was filled in on the profile."""
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            import json

            captured.update(json.loads(request.content)["patch"]["$set"])
            return httpx.Response(204)

        with _client(handler) as client:
            client.update("education", "1", Education(school="Ridgeway"))
        assert set(captured) == {"schoolName"}

    def test_a_forbidden_response_explains_the_partner_gate(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, json={"message": "Not enough permissions"})

        with _client(handler) as client, pytest.raises(LinkedInAPIError) as caught:
            client.create("skill", Skill(name="Rust"))
        message = str(caught.value)
        assert "Not enough permissions" in message
        assert "partner programme" in message
        assert "--transport review" in message

    def test_whoami_reads_the_openid_subject(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/v2/userinfo"
            return httpx.Response(200, json={"sub": "abc123"})

        with _client(handler, person_id="") as client:
            assert client.whoami() == "abc123"
            assert client.whoami() == "abc123", "the second call is cached"


def _client(handler, person_id: str = "ME") -> Client:
    transport = httpx.MockTransport(handler)
    return Client("tok", person_id=person_id, http=httpx.Client(transport=transport))
