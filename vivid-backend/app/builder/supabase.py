"""The Supabase Management API, as the builder uses it.

One class, one token. The token is the user's (their connector: OAuth or a
pasted personal access token) or, for Vivid Cloud, ours. Shapes checked
against api.supabase.com/api/v1-json on 2026-09-12. Errors carry the
API's own message so the model can act on a failed migration, and never a
token.
"""
import base64
import hashlib
import json
import logging
import secrets as pysecrets
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from app.core.config import settings
from app.services.models_gateway import http

log = logging.getLogger("vivid.builder.supabase")


class SupabaseError(Exception):
    """The API refused or failed. `public` is what a tool result or a
    client may show."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.public = message


@dataclass(frozen=True)
class Project:
    ref: str
    name: str
    organization_id: str
    region: str
    status: str

    @property
    def url(self) -> str:
        return f"https://{self.ref}.supabase.co"


def _base() -> str:
    return settings.SUPABASE_API_BASE.rstrip("/")


class Management:
    def __init__(self, token: str) -> None:
        self._token = token

    # ------------------------------------------------------------ http
    async def _call(self, method: str, path: str, *, json_body=None, params=None,
                    files=None, data=None):
        headers = {"Authorization": f"Bearer {self._token}"}
        try:
            r = await http.client().request(
                method, f"{_base()}{path}", headers=headers, json=json_body,
                params=params, files=files, data=data,
                timeout=settings.SUPABASE_API_TIMEOUT)
        except httpx.HTTPError as e:
            raise SupabaseError(0, f"could not reach Supabase: {e.__class__.__name__}") from e
        if r.status_code >= 400:
            raise SupabaseError(r.status_code, _message(r))
        if not r.content:
            return None
        try:
            return r.json()
        except ValueError:
            return r.text

    # --------------------------------------------------------- account
    async def organizations(self) -> list[dict]:
        return await self._call("GET", "/v1/organizations") or []

    async def projects(self) -> list[Project]:
        rows = await self._call("GET", "/v1/projects") or []
        return [Project(ref=r["ref"], name=r["name"], organization_id=r["organization_id"],
                        region=r["region"], status=r["status"]) for r in rows]

    async def api_keys(self, ref: str) -> dict:
        """{"url", "anon", "service"}: the key the browser app uses and the
        one only edge functions may see. Prefers the new publishable and
        secret keys, falls back to the legacy anon and service_role."""
        rows = await self._call("GET", f"/v1/projects/{ref}/api-keys",
                                params={"reveal": "true"}) or []
        anon = service = None
        for row in rows:
            kind, name, key = row.get("type"), row.get("name"), row.get("api_key")
            if not key:
                continue
            if kind == "publishable" and anon is None:
                anon = key
            elif kind == "secret" and service is None:
                service = key
            elif kind == "legacy" and name == "anon" and anon is None:
                anon = key
            elif kind == "legacy" and name == "service_role" and service is None:
                service = key
        if anon is None:
            raise SupabaseError(404, "the project has no publishable or anon key")
        return {"url": f"https://{ref}.supabase.co", "anon": anon, "service": service}

    # -------------------------------------------------------- database
    async def apply_migration(self, ref: str, sql: str, name: str | None = None) -> None:
        """Recorded in the project's migration history, so `supabase db`
        tooling and the dashboard agree with what the builder did."""
        body = {"query": sql}
        if name:
            body["name"] = name
        await self._call("POST", f"/v1/projects/{ref}/database/migrations", json_body=body)

    async def query(self, ref: str, sql: str, read_only: bool = False):
        return await self._call("POST", f"/v1/projects/{ref}/database/query",
                                json_body={"query": sql, "read_only": read_only})

    async def migrations(self, ref: str) -> list[dict]:
        return await self._call("GET", f"/v1/projects/{ref}/database/migrations") or []

    # --------------------------------------------------------- functions
    async def deploy_function(self, ref: str, slug: str, code: str,
                              verify_jwt: bool = True) -> dict:
        metadata = {"entrypoint_path": "index.ts", "name": slug, "verify_jwt": verify_jwt}
        files = [("file", ("index.ts", code.encode(), "application/typescript")),
                 ("metadata", (None, json.dumps(metadata), "application/json"))]
        out = await self._call("POST", f"/v1/projects/{ref}/functions/deploy",
                               params={"slug": slug}, files=files) or {}
        out["url"] = f"https://{ref}.supabase.co/functions/v1/{slug}"
        return out

    async def functions(self, ref: str) -> list[dict]:
        return await self._call("GET", f"/v1/projects/{ref}/functions") or []

    # ----------------------------------------------------------- secrets
    async def set_secrets(self, ref: str, values: dict[str, str]) -> None:
        await self._call("POST", f"/v1/projects/{ref}/secrets",
                         json_body=[{"name": k, "value": v} for k, v in values.items()])

    async def delete_secrets(self, ref: str, names: list[str]) -> None:
        await self._call("DELETE", f"/v1/projects/{ref}/secrets", json_body=names)

    async def secret_names(self, ref: str) -> list[str]:
        rows = await self._call("GET", f"/v1/projects/{ref}/secrets") or []
        return [r["name"] for r in rows]


def _message(r: httpx.Response) -> str:
    try:
        body = r.json()
    except ValueError:
        return (r.text or f"HTTP {r.status_code}")[:500]
    if isinstance(body, dict):
        for key in ("message", "error", "msg", "error_description"):
            if body.get(key):
                return str(body[key])[:500]
    return json.dumps(body)[:500]


# ------------------------------------------------------------------ oauth
def oauth_configured() -> bool:
    return bool(settings.SUPABASE_OAUTH_CLIENT_ID and settings.SUPABASE_OAUTH_CLIENT_SECRET)


def redirect_uri() -> str:
    return (settings.SUPABASE_OAUTH_REDIRECT_URI
            or f"{settings.PUBLIC_BASE_URL.rstrip('/')}/v1/connectors/supabase/callback")


def pkce_pair() -> tuple[str, str]:
    """(verifier, S256 challenge)."""
    verifier = pysecrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode()).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def authorize_url(state: str, challenge: str) -> str:
    return f"{_base()}/v1/oauth/authorize?" + urlencode({
        "client_id": settings.SUPABASE_OAUTH_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": redirect_uri(),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })


async def exchange_code(code: str, verifier: str) -> dict:
    return await _token_request({"grant_type": "authorization_code", "code": code,
                                 "code_verifier": verifier, "redirect_uri": redirect_uri()})


async def refresh(refresh_token: str) -> dict:
    return await _token_request({"grant_type": "refresh_token",
                                 "refresh_token": refresh_token})


async def _token_request(form: dict) -> dict:
    auth = (settings.SUPABASE_OAUTH_CLIENT_ID, settings.SUPABASE_OAUTH_CLIENT_SECRET)
    try:
        r = await http.client().post(f"{_base()}/v1/oauth/token", data=form, auth=auth,
                                     timeout=settings.SUPABASE_API_TIMEOUT)
    except httpx.HTTPError as e:
        raise SupabaseError(0, f"could not reach Supabase: {e.__class__.__name__}") from e
    if r.status_code >= 400:
        raise SupabaseError(r.status_code, _message(r))
    body = r.json()
    if "access_token" not in body:
        raise SupabaseError(502, "token response had no access_token")
    return body
