"""Expo's API (EAS), the part the builder uses: who a token belongs to, and a
build's status, artifacts and cancellation.

Starting a build needs the project's files uploaded, which only eas-cli does,
so that happens in a sandbox (app_build.py). Everything after the start is a
GraphQL call from here with the token, never in a sandbox. Queries and field
names match eas-cli's own (graphql/queries/BuildQuery.js, types/Build.js).
"""
from dataclasses import dataclass

import httpx

from app.core.config import settings
from app.services.models_gateway import http

API = "https://api.expo.dev/graphql"

#: EAS build statuses (eas-cli's BuildStatus enum).
NEW, IN_QUEUE, IN_PROGRESS = "NEW", "IN_QUEUE", "IN_PROGRESS"
PENDING_CANCEL, CANCELED, FINISHED, ERRORED = "PENDING_CANCEL", "CANCELED", "FINISHED", "ERRORED"
TERMINAL = {CANCELED, FINISHED, ERRORED}


class ExpoError(Exception):
    """Expo refused or could not be reached; `str()` is safe to show."""


@dataclass
class BuildInfo:
    id: str
    status: str
    platform: str | None = None
    #: The installable file: an .apk or .aab, or a simulator .tar.gz.
    artifact_url: str | None = None
    #: The build's page on expo.dev (logs, install QR for internal builds).
    logs_url: str | None = None
    error: str | None = None


_ME = """query CurrentUser { meActor { __typename id ... on User { username }
  ... on SSOUser { username } accounts { name } } }"""

_BUILD = """query BuildsByIdQuery($buildId: ID!) { builds { byId(buildId: $buildId) {
  id status platform error { errorCode message } artifacts { buildUrl applicationArchiveUrl }
  logFiles app { slug ownerAccount { name } } } } }"""

_CANCEL = """mutation CancelBuildMutation($buildId: ID!) {
  build { cancelBuild(buildId: $buildId) { id status } } }"""


async def _graphql(token: str, query: str, variables: dict | None = None) -> dict:
    if not token:
        raise ExpoError("no Expo access token")
    try:
        r = await http.client().post(
            API, json={"query": query, "variables": variables or {}},
            headers={"authorization": f"Bearer {token}"},
            timeout=settings.EXPO_API_TIMEOUT)
    except httpx.HTTPError as e:
        raise ExpoError(f"could not reach Expo ({e.__class__.__name__})")
    if r.status_code in (401, 403):
        raise ExpoError("Expo rejected the access token")
    if r.status_code >= 400:
        raise ExpoError(f"Expo answered {r.status_code}")
    body = r.json() if r.content else {}
    if body.get("errors"):
        raise ExpoError("Expo: " + "; ".join(str(e.get("message", e)) for e in body["errors"])[:300])
    return body.get("data") or {}


async def whoami(token: str) -> dict:
    """{"username", "accounts"} for a token; raises ExpoError when it is bad."""
    me = (await _graphql(token, _ME)).get("meActor") or {}
    if not me:
        raise ExpoError("that token does not belong to an Expo user")
    return {"username": me.get("username") or me.get("id"),
            "accounts": [a["name"] for a in me.get("accounts") or [] if a.get("name")]}


def _build_page(build: dict) -> str | None:
    app = build.get("app") or {}
    owner = (app.get("ownerAccount") or {}).get("name")
    if not owner or not app.get("slug"):
        return None
    return f"https://expo.dev/accounts/{owner}/projects/{app['slug']}/builds/{build['id']}"


def _info(build: dict) -> BuildInfo:
    artifacts = build.get("artifacts") or {}
    error = build.get("error") or {}
    return BuildInfo(
        id=build["id"], status=build.get("status") or NEW,
        platform=(build.get("platform") or "").lower() or None,
        artifact_url=artifacts.get("buildUrl") or artifacts.get("applicationArchiveUrl"),
        logs_url=_build_page(build),
        error=error.get("message"))


async def build(token: str, build_id: str) -> BuildInfo:
    data = await _graphql(token, _BUILD, {"buildId": build_id})
    found = (data.get("builds") or {}).get("byId")
    if not found:
        raise ExpoError("Expo has no build with that id")
    return _info(found)


async def cancel(token: str, build_id: str) -> str:
    data = await _graphql(token, _CANCEL, {"buildId": build_id})
    return ((data.get("build") or {}).get("cancelBuild") or {}).get("status") or PENDING_CANCEL
