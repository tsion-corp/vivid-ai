"""Pouch (Liquifia fiat API): each Vivid user's Nigerian bank virtual
account. A transfer into it credits their wallet.

Accounts are created with settlement_mode "held", so the money lands in
Vivid's Pouch wallet; the user's Vivid balance is our own ledger, never
Pouch's per-account balance. Amounts on Pouch are in kobo.
"""
import logging
import uuid

import httpx

from app.core.config import settings
from app.services.models_gateway import http

log = logging.getLogger("vivid.wallet.pouch")

#: uuid5 namespace for idempotency keys: one key per user, so a retried
#: request can never open a second account.
_NS = uuid.UUID("8b7f0f5e-2c1d-4f8e-9a51-6d1d2b3c4e5f")


class PouchError(Exception):
    """Pouch refused or could not be reached; str() is safe to show."""


def configured() -> bool:
    return bool(settings.POUCH_API_KEY)


def _url(path: str) -> str:
    return f"{settings.POUCH_BASE_URL.rstrip('/')}/api/v1{path}"


async def _call(method: str, path: str, *, json: dict | None = None, params: dict | None = None,
                headers: dict | None = None) -> dict:
    if not configured():
        raise PouchError("bank transfers are not set up on this server")
    try:
        r = await http.client().request(
            method, _url(path), json=json, params=params,
            headers={"Authorization": f"Bearer {settings.POUCH_API_KEY}", **(headers or {})},
            timeout=settings.PAYMENTS_API_TIMEOUT)
    except httpx.HTTPError as e:
        raise PouchError(f"could not reach the bank partner ({e.__class__.__name__})")
    body = r.json() if r.content else {}
    if r.status_code >= 400 or body.get("success") is False:
        err = body.get("error") if isinstance(body.get("error"), dict) else {}
        message = err.get("message") or body.get("message") or f"HTTP {r.status_code}"
        raise PouchError(f"bank partner: {message}")
    return body


def customer_reference(user_id: str) -> str:
    """Alphanumeric, underscore and hyphen only, per Pouch."""
    return "vivid_" + user_id.replace("-", "")


def _names(name: str | None, email: str | None) -> tuple[str, str]:
    parts = (name or "").split()
    if len(parts) >= 2:
        return parts[0][:60], " ".join(parts[1:])[:60]
    first = parts[0] if parts else ((email or "Vivid").split("@")[0] or "Vivid")
    return first[:60], "Vivid"


async def ensure_customer(user_id: str, name: str | None, email: str | None,
                          phone: str | None = None, bvn: str | None = None) -> str:
    """The Pouch customer id for this user, found by reference or created."""
    ref = customer_reference(user_id)
    found = await _call("GET", "/customers", params={"search": ref, "take": 5})
    for c in found.get("data") or []:
        if c.get("customer_reference") == ref:
            return c["id"]
    first, last = _names(name, email)
    body = {"customer_reference": ref, "first_name": first, "last_name": last}
    if email and "@" in email:
        body["email"] = email
    if phone:
        body["phone_number"] = phone
    if bvn:
        body["bvn"] = bvn
    created = await _call("POST", "/customers", json=body)
    return created["data"]["id"]


async def create_virtual_account(user_id: str, customer_id: str) -> dict:
    """A naira account whose money settles to Vivid ("held")."""
    key = str(uuid.uuid5(_NS, user_id))
    out = await _call("POST", f"/customers/{customer_id}/virtual-accounts",
                      json={"country": "NG", "currency": "NGN", "settlement_mode": "held"},
                      headers={"X-Idempotency-Key": key})
    return out["data"]


async def inbound_transfers(skip: int = 0, take: int = 100) -> list[dict]:
    out = await _call("GET", "/inbound-transfers", params={"skip": skip, "take": take})
    return out.get("data") or []


async def find_transfer(transfer_id: str, pages: int = 5) -> dict | None:
    """A transfer by id, from the newest pages (no single-transfer route)."""
    for page in range(pages):
        rows = await inbound_transfers(skip=page * 100, take=100)
        for row in rows:
            if row.get("id") == transfer_id:
                return row
        if len(rows) < 100:
            break
    return None


async def integrator() -> dict:
    return (await _call("GET", "/integrator")).get("data") or {}


async def set_webhook(url: str) -> dict:
    """Register the webhook URL. The docs name /me/webhook but not its
    method or body, so the common shapes are tried in turn."""
    last: PouchError | None = None
    for method in ("PUT", "POST", "PATCH"):
        for body in ({"webhook_url": url}, {"url": url}):
            try:
                return await _call(method, "/me/webhook", json=body)
            except PouchError as e:
                last = e
    raise last or PouchError("could not set the webhook")
