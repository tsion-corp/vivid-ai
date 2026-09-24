"""Dextopus: static crypto deposit addresses per user. Whatever arrives is
bridged and settled as USDC on Base to Vivid's treasury
(DEXTOPUS_SETTLEMENT_ADDRESS); the settled USDC amount is what the user's
wallet is credited.

Refund addresses (for deposits that cannot be routed) come from the
integration's defaults, set once in the Dextopus dashboard per chain type.
"""
import hashlib
import hmac
import json
import logging
import time

import httpx

from app.core.config import settings
from app.services.models_gateway import http
from app.services.wallet import crypto_options

log = logging.getLogger("vivid.wallet.dextopus")

SIGNATURE_MAX_AGE_MS = 5 * 60 * 1000


class DextopusError(Exception):
    """Dextopus refused or could not be reached; str() is safe to show."""


def configured() -> bool:
    return bool(settings.DEXTOPUS_API_KEY and settings.DEXTOPUS_SETTLEMENT_ADDRESS)


async def _call(method: str, path: str, *, json_body: dict | None = None,
                params: dict | None = None) -> dict:
    if not settings.DEXTOPUS_API_KEY:
        raise DextopusError("crypto top-ups are not set up on this server")
    url = f"{settings.DEXTOPUS_BASE_URL.rstrip('/')}/api{path}"
    try:
        r = await http.client().request(method, url, json=json_body, params=params,
                                        headers={"x-api-key": settings.DEXTOPUS_API_KEY},
                                        timeout=settings.PAYMENTS_API_TIMEOUT)
    except httpx.HTTPError as e:
        raise DextopusError(f"could not reach the crypto partner ({e.__class__.__name__})")
    body = r.json() if r.content else {}
    if r.status_code >= 400 or body.get("success") is False:
        raise DextopusError("crypto partner: " + str(body.get("message") or body.get("error")
                                                     or f"HTTP {r.status_code}")[:300])
    return body


async def static_address(user_id: str, option: crypto_options.Option) -> dict:
    """The user's reusable address for this token and chain."""
    out = await _call("POST", "/deposit/static/generate", json_body={
        "userId": user_id,
        "originChainId": option.chain_id,
        "originAsset": option.asset,
        "settlementChainId": crypto_options.SETTLEMENT_CHAIN,
        "settlementAsset": crypto_options.SETTLEMENT_ASSET,
        "settlementAddress": settings.DEXTOPUS_SETTLEMENT_ADDRESS,
        "metadata": {"vivid_user": user_id, "option": option.key},
    })
    return out["data"]


async def deposits(user_id: str | None = None, status: str | None = None,
                   limit: int = 50, offset: int = 0) -> list[dict]:
    params = {"limit": limit, "offset": offset}
    if user_id:
        params["userId"] = user_id
    if status:
        params["status"] = status
    return (await _call("GET", "/deposit/static/deposits", params=params)).get("data") or []


async def deposit(request_id: str) -> dict | None:
    out = await _call("GET", f"/deposit/static/deposits/{request_id}")
    return out.get("data")


async def supported(chain_id: int) -> set[str]:
    """Token addresses on a chain that can take static deposits."""
    out = await _call("GET", "/deposit/tokens",
                      params={"chainId": chain_id, "supportsStaticAddress": "true"})
    return {str(t.get("address", "")).lower() for t in out.get("tokens") or []}


async def set_webhook(url: str) -> dict:
    """Register the webhook; the response carries the signing secret."""
    return (await _call("POST", "/deposit/static/webhook", json_body={
        "webhookUrl": url,
        "events": ["deposit.created", "deposit.completed", "deposit.failed", "deposit.refunded"],
    })).get("data") or {}


def verify_signature(raw_body: bytes, timestamp: str | None, signature: str | None,
                     secret: str, now_ms: int | None = None) -> bool:
    """HMAC-SHA256 over "<timestamp>.<JSON body>". The body Dextopus signs is
    JSON.stringify of the payload, which matches the raw body we received;
    the compact re-serialisation is also accepted in case a proxy reformatted it."""
    if not (secret and timestamp and signature):
        return False
    try:
        age = (now_ms if now_ms is not None else int(time.time() * 1000)) - int(timestamp)
    except ValueError:
        return False
    if age > SIGNATURE_MAX_AGE_MS or age < -SIGNATURE_MAX_AGE_MS:
        return False
    candidates = [raw_body]
    try:
        candidates.append(json.dumps(json.loads(raw_body), separators=(",", ":"),
                                     ensure_ascii=False).encode())
    except ValueError:
        pass
    for body in candidates:
        expected = hmac.new(secret.encode(), f"{timestamp}.".encode() + body,
                            hashlib.sha256).hexdigest()
        if hmac.compare_digest(signature.strip().lower(), expected):
            return True
    return False
