"""A client for LinkedIn's Profile Edit API.

Read this before reaching for it: **the Profile Edit API is not self-serve.**
LinkedIn's public developer tier grants ``openid``, ``profile``, ``email`` and
``w_member_social``, none of which can write a position, an education or a
skill. Editing those requires a permission granted through a partner
programme. Without one, every call here returns 403 no matter how correct it
is, which is why the review transport exists and is the default.

It is implemented anyway, and implemented against the documented shapes rather
than a guess, because the alternative is a project that cannot use the access
the day it arrives. The endpoints, the ``$set`` patch envelope, the localized
field wrapper and the ``x-linkedin-id`` response header are all as documented
for the ``/v2/people/id={person}`` sub-resources.

One field is marked inferred: the headline and the summary live on the person
resource rather than a sub-resource, and cvme applies them as a partial update
on the person. Errors are surfaced verbatim precisely so that being wrong
about it is visible on the first call instead of silently doing nothing.
"""

from __future__ import annotations

from typing import Any, Literal

import httpx

from cvme.errors import CvmeError
from cvme.linkedin.model import Education, MonthYear, Position, Skill

API_ROOT = "https://api.linkedin.com"
USERINFO_URL = f"{API_ROOT}/v2/userinfo"

Kind = Literal["position", "education", "skill"]

#: Sub-resource per entity kind, as they appear in the documented URLs.
COLLECTIONS: dict[str, str] = {
    "position": "positions",
    "education": "educations",
    "skill": "skills",
}

#: Which body fields the API expects wrapped in a localized envelope.
#: Beside the collections so the two cannot drift.
LOCALIZED_FIELDS: dict[str, tuple[str, ...]] = {
    "position": ("title", "companyName", "description", "locationName"),
    "education": ("schoolName", "degreeName", "fieldOfStudy", "description"),
    "skill": (),
}

_TIMEOUT = 30.0


class LinkedInAPIError(CvmeError):
    exit_code = 10


class Client:
    """Authenticated calls against one member's profile."""

    def __init__(
        self,
        token: str,
        *,
        person_id: str = "",
        locale: tuple[str, str] = ("en", "US"),
        http: httpx.Client | None = None,
    ):
        self._token = token
        self.person_id = person_id
        self.locale = locale
        self._http = http or httpx.Client(timeout=_TIMEOUT)

    def __enter__(self) -> Client:
        return self

    def __exit__(self, *_: object) -> None:
        self._http.close()

    # -- identity ---------------------------------------------------------

    def whoami(self) -> str:
        """The member's id, which every profile URL is built from.

        ``/v2/userinfo`` is the OpenID Connect endpoint, so this one call works
        on the self-serve tier. It is also the cheapest way to tell a token
        that has expired from a token that was never granted what it needs.
        """
        if self.person_id:
            return self.person_id
        data = self._request("GET", USERINFO_URL)
        if not (sub := str(data.get("sub", ""))):
            raise LinkedInAPIError("LinkedIn's userinfo response carried no member id")
        self.person_id = sub
        return sub

    # -- entities ---------------------------------------------------------

    def create(self, kind: Kind, entity: Position | Education | Skill) -> str:
        """Add an entity, returning the id LinkedIn assigned it."""
        body = self._localize(kind, _body(kind, entity))
        response = self._call("POST", self._collection(kind), json=body)
        if not (created := response.headers.get("x-linkedin-id", "")):
            raise LinkedInAPIError(
                f"LinkedIn created the {kind} but returned no id, so cvme cannot "
                "record it for a later update"
            )
        return created

    def update(
        self, kind: Kind, remote_id: str, entity: Position | Education | Skill
    ) -> None:
        """Partially update an entity, touching only the fields cvme owns."""
        body = self._localize(kind, _body(kind, entity))
        url = f"{self._collection(kind)}/{remote_id}"
        self._call("POST", url, json={"patch": {"$set": body}})

    def delete(self, kind: Kind, remote_id: str) -> None:
        self._call("DELETE", f"{self._collection(kind)}/{remote_id}")

    def set_person_fields(self, fields: dict[str, str]) -> None:
        """Set headline and/or summary on the person resource.

        Inferred rather than documented -- see the module docstring. The patch
        envelope and the localized wrapper are the same ones the sub-resources
        use, which is the only reason to expect it to hold.
        """
        if not fields:
            return
        patch = {name: self._localized(value) for name, value in fields.items()}
        self._call(
            "POST",
            f"{API_ROOT}/v2/people/id={self.whoami()}",
            json={"patch": {"$set": patch}},
        )

    # -- plumbing ---------------------------------------------------------

    def _localize(self, kind: Kind, body: dict[str, Any]) -> dict[str, Any]:
        """Wrap the text fields this resource localizes, and leave the rest."""
        wrapped = LOCALIZED_FIELDS[kind]
        return {
            name: self._localized(value) if name in wrapped else value
            for name, value in body.items()
        }

    def _collection(self, kind: Kind) -> str:
        if kind not in COLLECTIONS:
            raise LinkedInAPIError(f"cvme cannot sync '{kind}' through the API")
        return f"{API_ROOT}/v2/people/id={self.whoami()}/{COLLECTIONS[kind]}"

    def _localized(self, value: str) -> dict[str, Any]:
        language, country = self.locale
        return {
            "localized": {f"{language}_{country}": value},
            "preferredLocale": {"country": country, "language": language},
        }

    def _request(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        response = self._call(method, url, **kwargs)
        try:
            return response.json()
        except ValueError as exc:
            raise LinkedInAPIError(f"{url} returned a body that is not JSON") from exc

    def _call(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        headers = {
            "Authorization": f"Bearer {self._token}",
            "X-Restli-Protocol-Version": "2.0.0",
            "Content-Type": "application/json",
        }
        try:
            response = self._http.request(method, url, headers=headers, **kwargs)
        except httpx.HTTPError as exc:
            raise LinkedInAPIError(f"could not reach {url}: {exc}") from exc
        if response.is_success:
            return response
        raise LinkedInAPIError(_explain(method, url, response))


def _explain(method: str, url: str, response: httpx.Response) -> str:
    """Say what LinkedIn said, and for 403 say what it usually means.

    A permissions failure here is the expected outcome for most people rather
    than a bug in the request, and a bare "403 Forbidden" sends them looking
    for one.
    """
    detail = ""
    try:
        body = response.json()
        detail = str(body.get("message") or body.get("error_description") or "")
    except ValueError:
        detail = response.text[:200]
    message = f"{method} {url} failed: HTTP {response.status_code} {detail}".strip()
    if response.status_code in (401, 403):
        message += (
            "\n  Writing to profile sections needs a Profile Edit permission, "
            "which LinkedIn grants through a partner programme and not through "
            "the self-serve developer tier.\n"
            "  Use the default review transport instead: "
            "`cvme linkedin sync --transport review`."
        )
    return message


def _body(kind: Kind, entity: Position | Education | Skill) -> dict[str, Any]:
    """One entity as the API's field names.

    Localization is applied by the caller's client, so this stays a plain
    mapping of the fields cvme is willing to own. Fields cvme does not write
    are absent rather than empty, so a partial update never blanks something
    that was filled in on the profile by hand.
    """
    match entity:
        case Position():
            return _drop_empty(
                {
                    "title": entity.title,
                    "companyName": entity.company,
                    "description": entity.description,
                    "locationName": entity.location,
                    "startMonthYear": _month_year(entity.start),
                    "endMonthYear": _month_year(entity.end),
                }
            )
        case Education():
            return _drop_empty(
                {
                    "schoolName": entity.school,
                    "degreeName": entity.degree,
                    "fieldOfStudy": entity.field_of_study,
                    "description": entity.description,
                    "startMonthYear": _month_year(entity.start),
                    "endMonthYear": _month_year(entity.end),
                }
            )
        case Skill():
            return {"name": entity.name}
    raise LinkedInAPIError(f"cvme cannot serialise a {kind}")


def _month_year(value: MonthYear | None) -> dict[str, int] | None:
    if value is None:
        return None
    return {"year": value.year, **({"month": value.month} if value.month else {})}


def _drop_empty(fields: dict[str, Any]) -> dict[str, Any]:
    return {name: value for name, value in fields.items() if value not in (None, "")}
