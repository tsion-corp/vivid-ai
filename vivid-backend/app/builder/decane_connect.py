"""Decane Connect: sign-in for the apps the builder makes.

Vivid holds one organization token (DECANE_PARTNER_TOKEN) and gives each
builder project that wants sign-in its own Decane client and API key, keyed
on the project id as `external_ref`. The generated app signs its users in
with the Decane browser SDK against that key; Vivid is never in their auth
path. Spec: https://kit.decane.app/llms-connect.txt (connect/v1).

Not Vivid's own sign-in: that is app/services/decane.py with DECANE_APP_ID.
"""
import logging
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from app.core.config import settings
from app.services.models_gateway import http

log = logging.getLogger("vivid.builder.decane")

#: The route the app serves for the Google sign-in return.
CALLBACK_PATH = "/auth/callback"


class ConnectError(Exception):
    """A Decane Connect call failed. `kind` is how the route answers:
    bad_request (400), not_configured (503, an operator problem: token
    missing, revoked, out of scope or over quota) or upstream (502)."""

    def __init__(self, kind: str, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.status = status


@dataclass
class Minted:
    id: str
    key: str


def configured() -> bool:
    return bool(settings.DECANE_PARTNER_TOKEN)


def host_of(url: str | None) -> str | None:
    """The hostname Decane matches origins on: no scheme, no port."""
    if not url:
        return None
    return urlparse(url if "//" in url else f"https://{url}").hostname or None


def origins_for(published_url: str | None, previews: list[str]) -> tuple[list[str], str | None]:
    """The key's whole allowlist and its callback: the published host, the
    current preview host and the one before it (a tab may still be open).
    Google sign-in returns to one host, the published one once there is one."""
    published = host_of(published_url)
    hosts: list[str] = []
    for h in [published, *previews[:2]]:
        if h and h not in hosts:
            hosts.append(h)
    primary = published or (previews[0] if previews else None)
    return hosts, (f"https://{primary}{CALLBACK_PATH}" if primary else None)


async def _call(method: str, path: str, body: dict | None = None) -> dict:
    if not configured():
        raise ConnectError("not_configured", "Decane sign-in is not configured.")
    try:
        r = await http.client().request(
            method, f"{settings.DECANE_CONNECT_BASE.rstrip('/')}/connect/v1{path}",
            json=body, timeout=settings.DECANE_CONNECT_TIMEOUT,
            headers={"Authorization": f"Bearer {settings.DECANE_PARTNER_TOKEN}"})
    except httpx.HTTPError as e:
        raise ConnectError("upstream", f"Could not reach Decane ({e.__class__.__name__}).")
    try:
        data = r.json()
    except ValueError:
        data = {}
    if r.status_code < 400:
        return data if isinstance(data, dict) else {}
    err = (data.get("error") or {}) if isinstance(data, dict) else {}
    code, message = err.get("code", ""), err.get("message") or f"Decane answered {r.status_code}."
    if r.status_code == 400:
        raise ConnectError("bad_request", message, r.status_code)
    if r.status_code in (401, 403):
        # Missing, revoked or narrowed org token, or the org's quota: the
        # operator's problem, never the user's.
        log.error("decane connect refused %s %s: %s %s", method, path, code, message)
        text = message if code == "QUOTA_EXCEEDED" else "Decane sign-in is not configured."
        raise ConnectError("not_configured", text, r.status_code)
    if r.status_code == 404:
        raise ConnectError("not_found", message, r.status_code)
    raise ConnectError("upstream", f"Decane answered {r.status_code}.", r.status_code)


async def create_client(ref: str, name: str, origins: list[str],
                        callback_url: str | None) -> tuple[str, Minted | None]:
    """POST /clients. Returns the appId and the new key, or None for the key
    when the client already existed (a retry, or a re-enable): the original
    key cannot be read back, so the caller mints one."""
    body = {"external_ref": ref, "name": (name or "Vivid app")[:120], "allowed_origins": origins}
    if callback_url:
        body["callback_url"] = callback_url
    data = await _call("POST", "/clients", body)
    app_id = (data.get("client") or {}).get("appId")
    if not app_id:
        raise ConnectError("upstream", "Decane did not return the client.")
    key = data.get("apiKey")
    return app_id, (Minted(id=key["id"], key=key["key"]) if key else None)


async def mint_key(ref: str, origins: list[str], callback_url: str | None) -> Minted:
    body = {"name": "vivid", "allowed_origins": origins}
    if callback_url:
        body["callback_url"] = callback_url
    data = await _call("POST", f"/clients/{ref}/keys", body)
    if not data.get("id") or not data.get("key"):
        raise ConnectError("upstream", "Decane did not return the key.")
    return Minted(id=data["id"], key=data["key"])


async def update_key(ref: str, key_id: str, origins: list[str], callback_url: str | None) -> None:
    """The allowlist is REPLACED, so `origins` is the whole set."""
    body: dict = {"allowed_origins": origins}
    if callback_url:
        body["callback_url"] = callback_url
    await _call("PATCH", f"/clients/{ref}/keys/{key_id}", body)


async def revoke_key(ref: str, key_id: str) -> None:
    await _call("DELETE", f"/clients/{ref}/keys/{key_id}")


async def deprovision(ref: str) -> None:
    """Archive the client and revoke every key. There is no hard delete."""
    await _call("DELETE", f"/clients/{ref}")
