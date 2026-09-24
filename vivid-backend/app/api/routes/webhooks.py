"""Payment webhooks: Pouch (a bank transfer arrived) and Dextopus (a crypto
deposit settled).

A webhook is a hint, never proof. The signature is checked when a secret is
configured, then the transfer or deposit is fetched from the provider's API
with Vivid's key and only what the API reports is credited, once. Answers
200 whatever happens after the signature, so the provider does not retry
into a loop; the reconciler catches anything that failed here.
"""
import json
import logging

from fastapi import APIRouter, Request

from app.core.config import settings
from app.core.errors import APIError
from app.db.session import async_session
from app.services import rate_limit
from app.services.wallet import deposits, dextopus

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
log = logging.getLogger("vivid.webhooks")


async def _limited(request: Request, name: str) -> None:
    redis = getattr(request.app.state, "redis", None)
    if redis is not None and not await rate_limit.check_bucket(redis, f"webhook:{name}", 600):
        raise APIError(429, "rate_limited", "Too many webhook calls")


async def _handle(payload: dict, handler, name: str) -> dict:
    try:
        async with async_session() as db:
            entry = await handler(db, payload)
            await db.commit()
        return {"received": True, "credited": entry is not None}
    except Exception as e:                          # the reconciler retries
        log.warning("%s webhook not processed: %s", name, e)
        return {"received": True, "credited": False}


@router.post("/pouch")
async def pouch_webhook(request: Request):
    await _limited(request, "pouch")
    raw = await request.body()
    secret = settings.POUCH_WEBHOOK_SECRET
    if secret and not deposits.verify_pouch_signature(
            raw, request.headers.get("x-liquifia-signature"), secret):
        # Logged, not refused: the scheme is undocumented, and the credit is
        # verified against the API anyway. A forged call can only make us look.
        log.warning("pouch webhook signature did not verify")
    try:
        payload = json.loads(raw or b"{}")
    except ValueError:
        raise APIError(400, "bad_request", "Not JSON")
    return await _handle(payload, deposits.on_pouch_event, "pouch")


@router.post("/dextopus")
async def dextopus_webhook(request: Request):
    await _limited(request, "dextopus")
    raw = await request.body()
    secret = settings.DEXTOPUS_WEBHOOK_SECRET
    if secret and not dextopus.verify_signature(raw, request.headers.get("x-signature-timestamp"),
                                                request.headers.get("x-signature-sha256"), secret):
        raise APIError(401, "unauthorized", "Invalid signature")
    try:
        payload = json.loads(raw or b"{}")
    except ValueError:
        raise APIError(400, "bad_request", "Not JSON")
    return await _handle(payload, deposits.on_dextopus_event, "dextopus")
