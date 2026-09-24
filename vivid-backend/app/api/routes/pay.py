"""Vivid Pay's public API, called by the apps users build.

    POST /v1/pay/checkouts                 {key, amount_kobo, reference, customer?, metadata?}
    GET  /v1/pay/checkouts/{id}?key=       status, polled by the app
    POST /v1/pay/checkouts/{id}/simulate   {key}; test checkouts only
    POST /v1/pay/checkouts/{id}/crypto     {key, network, payer}; pay in crypto instead
    GET  /v1/pay/checkouts?reference=      Authorization: Bearer vsk_... (the app's server side)

The publishable key (vpk_) is in the app's bundle, so it is honoured only
from the app's own origins: its published site (live) and the builder's
preview (test: no real account, no money). Requests are plain text so a
browser sends them without a preflight, and answers allow any origin, as
the pageview beacon does (analytics.py); the origin check is ours.
"""
import json
import logging
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.builder import targets
from app.core.config import settings
from app.core.errors import APIError
from app.db.models import BuilderProject, VividPayCheckout, VividPayProject
from app.services import rate_limit
from app.services.vividpay import VividPayError, checkouts, crypto, events, key_hash

router = APIRouter(prefix="/pay", tags=["vivid-pay"])
log = logging.getLogger("vivid.pay")

CORS = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "content-type, authorization",
        "Access-Control-Max-Age": "86400", "Cache-Control": "no-store"}

#: Hosts the builder previews apps on: test mode.
PREVIEW_SUFFIXES = (".e2b.app", ".e2b.dev", ".sslip.io")
LOCAL_HOSTS = ("localhost", "127.0.0.1")


def _json(data, status: int = 200) -> Response:
    return Response(json.dumps(data, default=str), status_code=status,
                    media_type="application/json", headers=CORS)


def _fail(e: VividPayError) -> Response:
    return _json({"error": {"code": e.code, "message": str(e)}}, e.status)


def _host(url: str | None) -> str:
    return (urlparse(url or "").hostname or "").lower()


def mode_for(origin: str | None, project: BuilderProject) -> str | None:
    """live from the app's published site, test from the builder preview,
    None (refused) from anywhere else."""
    host = _host(origin)
    if not host:
        return None
    if project.published_url and host == _host(project.published_url):
        return "live"
    if host.endswith(PREVIEW_SUFFIXES) or host in LOCAL_HOSTS:
        return "test"
    return None


def key_mode(key: str | None, pay: VividPayProject, origin: str | None,
             project: BuilderProject) -> str | None:
    """The test key is always test. The live key goes by origin on the web;
    a mobile app's native requests carry no origin, and its live key only
    ever ships in an installable build, so they are live."""
    if pay.test_key and key == pay.test_key:
        return "test"
    mode = mode_for(origin, project)
    if mode is None and not origin and targets.of(project).is_mobile:
        return "live"
    return mode


def _ip(request: Request) -> str:
    return (request.headers.get("cf-connecting-ip")
            or request.headers.get("x-forwarded-for", "").split(",")[0].strip()
            or (request.client.host if request.client else ""))


async def _body(request: Request) -> dict:
    try:
        data = json.loads((await request.body()).decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError):
        raise VividPayError("The body must be JSON.")
    if not isinstance(data, dict):
        raise VividPayError("The body must be a JSON object.")
    return data


async def _by_key(db: AsyncSession, key: str | None) -> tuple[VividPayProject, BuilderProject]:
    if not settings.VIVIDPAY_ENABLED:
        raise VividPayError("Payments are switched off.", "not_configured", 503)
    if not key or not key.startswith("vpk_"):
        raise VividPayError("A publishable key (vpk_...) is required.", "unauthorized", 401)
    pay = (await db.execute(select(VividPayProject).where(or_(
        VividPayProject.publishable_key == key,
        VividPayProject.test_key == key)))).scalar_one_or_none()
    if pay is None or not pay.enabled:
        raise VividPayError("That key is not active.", "unauthorized", 401)
    project = await db.get(BuilderProject, pay.project_id)
    if project is None:
        raise VividPayError("That key is not active.", "unauthorized", 401)
    return pay, project


@router.options("/checkouts")
@router.options("/checkouts/{checkout_id}")
@router.options("/checkouts/{checkout_id}/simulate")
@router.options("/checkouts/{checkout_id}/crypto")
async def preflight(checkout_id: str | None = None):
    return Response(status_code=204, headers=CORS)


@router.post("/checkouts")
async def create_checkout(request: Request, db: AsyncSession = Depends(get_db)):
    try:
        data = await _body(request)
        pay, project = await _by_key(db, data.get("key"))
        mode = key_mode(data.get("key"), pay, request.headers.get("origin"), project)
        if mode is None:
            raise VividPayError("This key only works on the app's own site.", "forbidden", 403)
        redis = getattr(request.app.state, "redis", None)
        if redis is not None and mode == "live":
            if not await rate_limit.check_bucket(redis, f"pay:{project.id}",
                                                 settings.VIVIDPAY_CHECKOUTS_PER_MINUTE) or \
               not await rate_limit.check_bucket(redis, f"pay:{project.id}:{_ip(request)}",
                                                 settings.VIVIDPAY_CHECKOUTS_PER_IP_MINUTE):
                raise VividPayError("Too many checkouts; try again in a minute.", "rate_limited", 429)
        try:
            amount = int(data.get("amount_kobo"))
        except (TypeError, ValueError):
            raise VividPayError("amount_kobo must be a whole number of kobo.")
        c = await checkouts.create(db, pay, project, amount, str(data.get("reference") or ""),
                                   data.get("customer") if isinstance(data.get("customer"), dict) else None,
                                   data.get("metadata"), mode)
        await db.commit()
    except VividPayError as e:
        await db.rollback()
        return _fail(e)
    return _json(checkouts.view(c), 201)


async def _checkout_for_key(db: AsyncSession, checkout_id: str, key: str | None) -> VividPayCheckout:
    pay, _ = await _by_key(db, key)
    c = await db.get(VividPayCheckout, checkout_id)
    if c is None or c.project_id != pay.project_id:
        raise VividPayError("No such checkout.", "not_found", 404)
    return c


#: How often, at most, waiting checkouts look at Pouch directly (all of
#: them together), seconds.
POLL_EVERY = 4


@router.get("/checkouts/{checkout_id}")
async def get_checkout(checkout_id: str, request: Request, key: str | None = None,
                       db: AsyncSession = Depends(get_db)):
    try:
        c = await _checkout_for_key(db, checkout_id, key)
    except VividPayError as e:
        return _fail(e)
    if c.mode == "live" and c.status in ("pending", "partial") and events.configured():
        # The app polls while its customer waits; that is when to look.
        redis = getattr(request.app.state, "redis", None)
        try:
            go = redis is None or await redis.set("pay:poll", "1", nx=True, ex=POLL_EVERY)
        except Exception:
            go = False
        if go:
            try:
                await events.poll_pending(db)
            except Exception as e:                     # the webhook still comes
                log.warning("pending poll failed: %s", e)
            await db.refresh(c)
    return _json(checkouts.view(c))


@router.post("/checkouts/{checkout_id}/simulate")
async def simulate_checkout(checkout_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    try:
        data = await _body(request)
        c = await _checkout_for_key(db, checkout_id, data.get("key"))
        await checkouts.simulate(db, c)
        await db.commit()
        pay = await db.get(VividPayProject, c.project_id)
    except VividPayError as e:
        await db.rollback()
        return _fail(e)
    if pay is not None:
        await checkouts.notify_app(pay, c)
    return _json(checkouts.view(c))


@router.post("/checkouts/{checkout_id}/crypto")
async def crypto_checkout(checkout_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """A crypto address for the order: what arrives is converted by Pouch
    and credited in naira, like a transfer."""
    try:
        data = await _body(request)
        c = await _checkout_for_key(db, checkout_id, data.get("key"))
        redis = getattr(request.app.state, "redis", None)
        if redis is not None and c.mode == "live" and not c.crypto_address and \
           not await rate_limit.check_bucket(redis, f"pay:{c.project_id}:{_ip(request)}",
                                             settings.VIVIDPAY_CHECKOUTS_PER_IP_MINUTE):
            raise VividPayError("Too many requests; try again in a minute.", "rate_limited", 429)
        await crypto.open_address(db, c, str(data.get("network") or "evm"),
                                  data.get("payer") if isinstance(data.get("payer"), dict) else None)
        await db.commit()
    except VividPayError as e:
        await db.rollback()
        return _fail(e)
    return _json(checkouts.view(c))


@router.get("/checkouts")
async def find_checkout(request: Request, reference: str, db: AsyncSession = Depends(get_db)):
    """For the app's server side (an edge function), with the secret key."""
    auth = request.headers.get("authorization", "")
    secret = auth.removeprefix("Bearer ").strip()
    if not secret.startswith("vsk_"):
        raise APIError(401, "unauthorized", "A secret key (vsk_...) is required.")
    pay = (await db.execute(select(VividPayProject).where(
        VividPayProject.secret_key_hash == key_hash(secret),
        VividPayProject.enabled.is_(True)))).scalar_one_or_none()
    if pay is None:
        raise APIError(401, "unauthorized", "That key is not active.")
    c = (await db.execute(select(VividPayCheckout).where(
        VividPayCheckout.project_id == pay.project_id,
        VividPayCheckout.reference == reference))).scalar_one_or_none()
    if c is None:
        raise APIError(404, "not_found", "No checkout for that reference.")
    return _json(checkouts.view(c))

