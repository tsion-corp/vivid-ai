import hashlib
import secrets
import json
import logging
import time

import jwt as pyjwt
from app.core.errors import APIError
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, get_session_user
from app.core.config import settings
from app.core.security import (create_handoff_token, create_token_pair, decode_token, hash_password,
                               verify_password)
from app.db.models import User
from app.schemas.auth import (DecaneLoginRequest, DeleteMeRequest, DeletionOut,
                              DeletionPreviewOut, EmailStartRequest, EmailVerifyRequest,
                              HandoffExchangeRequest, HandoffOut, HandoffRequest, LoginRequest,
                              IdentitiesOut, LinkConfirmRequest, LinkTokenRequest, ProfileUpdate,
                              RefreshRequest, SignupRequest, TokenPairOut, UserOut)
from app.services import account, decane, identities

# Sentinel password hash for social-login accounts — it can never verify, so
# password login on these accounts always fails cleanly.
OAUTH_SENTINEL = "!oauth"

router = APIRouter(prefix="/auth", tags=["auth"])
log = logging.getLogger("vivid.auth")


def _pair(user: User) -> TokenPairOut:
    return TokenPairOut(**create_token_pair(user.id), user=user)


def _require_password_auth() -> None:
    """Passwords are a test-only path. In the product, people sign in with
    Google or an emailed code through Decane."""
    if not settings.ALLOW_PASSWORD_AUTH:
        raise HTTPException(status_code=404, detail="Password sign-in is disabled")


@router.post("/signup", response_model=TokenPairOut, status_code=201)
async def signup(body: SignupRequest, db: AsyncSession = Depends(get_db)):
    _require_password_auth()
    email = body.email.lower()
    existing = (await db.execute(
        select(User).where(User.email == email))).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Email already registered")
    user = User(email=email, password_hash=hash_password(body.password))
    db.add(user)
    await db.commit()
    return _pair(user)


@router.post("/login", response_model=TokenPairOut)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    _require_password_auth()
    user = (await db.execute(
        select(User).where(User.email == body.email.lower()))).scalar_one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return _pair(user)


def _claims(access_token: str) -> dict:
    try:
        return decane.verify_access_token(access_token)
    except decane.DecaneAuthError as e:
        status = 503 if "not configured" in str(e) else 401
        raise HTTPException(status_code=status, detail=str(e))


def _fill_profile(user: User, name: str | None, email: str | None, picture: str | None) -> None:
    """The profile fills what the account doesn't have yet: a real name, a
    photo, and the address to show (display only; never used to find it)."""
    if name and not user.name:
        user.name = name.strip()[:120]
    if picture and not user.avatar_url:
        user.avatar_url = picture[:1024]
    if email and not user.profile_email:
        user.profile_email = email.lower()[:320]


#: A Google sign-in waiting for the emailed code that joins it to an
#: existing account: redis key -> {uid, email, name, picture}.
LINK_TTL = 900


def _link_key(token: str) -> str:
    return f"auth:link:{token}"


async def _session(db: AsyncSession, access_token: str, name: str | None = None,
                   email: str | None = None, picture: str | None = None, *,
                   method: str = "other", verified: str | None = None, redis=None) -> TokenPairOut:
    """A verified Decane token -> Vivid's own token pair. The account is the
    one this Decane id is an identity of (identities.py), never one found by
    an email the caller supplies, which would allow account takeover.

    `verified`: an address the sign-in proved (an emailed code). A Google
    sign-in (`method` "google") we have not seen, whose claimed email is an
    existing account's proven address, is held back: 409 link_required, and a
    code goes to that address; entering it (POST /auth/link/confirm) joins
    Google to that account."""
    claims = _claims(access_token)
    uid = str(claims["uid"])
    user = await identities.resolve(db, uid)
    if user is None:
        claimed = (email or "").strip().lower()
        if method == "google" and claimed and redis is not None:
            existing = await identities.by_verified_email(db, claimed)
            if existing is not None:
                await db.rollback()
                token = secrets.token_urlsafe(24)
                await redis.set(_link_key(token), json.dumps(
                    {"uid": uid, "email": claimed, "name": name, "picture": picture}), ex=LINK_TTL)
                sent = True
                try:
                    await _send_code(claimed, redis)
                except APIError:
                    sent = False                       # a code went out moments ago: it still works
                raise APIError(409, "link_required",
                               f"You already have a Vivid account with {_masked(claimed)}. Enter the code we "
                               "emailed there to use Google with it.",
                               details={"link_token": token, "email": _masked(claimed), "code_sent": sent,
                                        "options": ["confirm", "resend", "separate"]})
        user = User(email=identities.legacy_email(uid), password_hash=OAUTH_SENTINEL)
        db.add(user)
        await db.flush()
        await identities.attach(db, uid, user, method, verified)
    elif verified:
        await identities.attach(db, uid, user, "email", verified)
    _fill_profile(user, name, email, picture)
    await db.commit()
    return _pair(user)


def _decane_error(e: decane.DecaneError) -> APIError:
    """A Decane failure as something safe to show."""
    if e.code == "INVALID_CODE":
        return APIError(400, "invalid_code", "That code is wrong or has expired.")
    if e.code == "RATE_LIMITED" or e.status == 429:
        return APIError(429, "rate_limited", "Too many sign-ins right now. Wait a few minutes and try again.")
    if e.code == "not_configured":
        return APIError(503, "not_configured", str(e))
    return APIError(502, "sign_in_unavailable", "Sign-in is unavailable right now. Try again shortly.")


#: Decane sends at most three codes per address an hour, and a fourth
#: request "succeeds" without sending. Counting here, per address (never per
#: IP: every sign-in comes from this one server), lets us say so instead.
CODES_PER_HOUR = 3
RESEND_SECONDS = 60


def _codes_key(email: str) -> str:
    return "auth:codes:" + hashlib.sha256(email.encode()).hexdigest()[:32]


async def _codes_sent(redis, email: str, now: float) -> list[float]:
    if redis is None:
        return []
    try:
        raw = await redis.get(_codes_key(email))
        return [t for t in json.loads(raw or "[]") if now - t < 3600]
    except Exception:
        return []


async def _send_code(email: str, redis) -> dict:
    """One code to this address, within its per-address budget."""
    now = time.time()
    sent = await _codes_sent(redis, email, now)
    if sent and now - sent[-1] < RESEND_SECONDS:
        wait = int(RESEND_SECONDS - (now - sent[-1])) + 1
        raise APIError(429, "code_just_sent",
                       f"A code was just sent. Check your inbox (and spam); you can ask for another in {wait}s.",
                       details={"retry_after": wait, "codes_left": max(CODES_PER_HOUR - len(sent), 0)})
    if len(sent) >= CODES_PER_HOUR:
        wait = int(3600 - (now - sent[0])) + 1
        raise APIError(429, "too_many_codes",
                       f"{CODES_PER_HOUR} codes have gone to this address in the last hour. Use the newest one "
                       f"in your inbox (check spam), or ask for another in {max(wait // 60, 1)} min.",
                       details={"retry_after": wait, "codes_left": 0})
    try:
        await decane.start_email(email)
    except decane.DecaneError as e:
        raise _decane_error(e)
    sent.append(now)
    if redis is not None:
        try:
            await redis.set(_codes_key(email), json.dumps(sent), ex=3600)
        except Exception:
            pass
    return {"ok": True, "resend_in": RESEND_SECONDS, "codes_left": CODES_PER_HOUR - len(sent)}


@router.post("/email/start", status_code=202)
async def email_start(body: EmailStartRequest, request: Request):
    """Emails a sign-in code. Always 202 for a well-formed address (whether
    an account exists is never revealed), unless this address has had a code
    too recently or too often, which is true of any address alike."""
    return await _send_code(body.email.strip().lower(), getattr(request.app.state, "redis", None))


@router.post("/email/verify", response_model=TokenPairOut)
async def email_verify(body: EmailVerifyRequest, db: AsyncSession = Depends(get_db)):
    email = body.email.strip().lower()
    try:
        result = await decane.verify_email(email, body.code.strip())
    except decane.DecaneError as e:
        raise _decane_error(e)
    profile = result.get("profile") or {}
    return await _session(db, str(result.get("jwt") or ""), name=profile.get("name"),
                          email=email, picture=profile.get("picture"), method="email", verified=email)


@router.get("/google/start")
async def google_start(request: Request):
    """Where to send the browser for Google; it comes back to the callback
    registered in Decane with `decane_jwt`, which POST /auth/decane takes.

    The caller's Origin decides WHICH callback: the key carries one per host
    (vividbuild.ai, the preview hosts, localhost), and Decane matches on it.
    Referer is the fallback for a plain navigation, which sends no Origin.
    """
    origin = request.headers.get("origin") or request.headers.get("referer")
    try:
        return {"url": await decane.google_consent_url(origin=origin)}
    except decane.DecaneError as e:
        raise _decane_error(e)


@router.post("/decane", response_model=TokenPairOut)
async def decane_login(body: DecaneLoginRequest, request: Request,
                       db: AsyncSession = Depends(get_db)):
    """The end of the Google redirect: the `decane_jwt` Decane put on the
    callback URL, verified offline (ES256, JWKS) and traded for a session.
    409 link_required when it should join an existing account first."""
    return await _session(db, body.access_token, body.name, body.email, body.picture,
                          method="google", redis=getattr(request.app.state, "redis", None))


async def _pending_link(request: Request, token: str) -> dict:
    redis = getattr(request.app.state, "redis", None)
    raw = await redis.get(_link_key(token)) if redis is not None else None
    if not raw:
        raise APIError(410, "link_expired", "That took too long. Sign in with Google again.")
    return json.loads(raw)


@router.post("/link/confirm", response_model=TokenPairOut)
async def link_confirm(body: LinkConfirmRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """The code from the address the Google sign-in claimed: it proves the
    address, so Google joins the account that proved it before."""
    pending = await _pending_link(request, body.link_token)
    try:
        result = await decane.verify_email(pending["email"], body.code.strip())
    except decane.DecaneError as e:
        raise _decane_error(e)
    email_uid = str(_claims(str(result.get("jwt") or ""))["uid"])
    user = await identities.resolve(db, email_uid) or await identities.by_verified_email(db, pending["email"])
    if user is None:
        raise APIError(410, "link_expired", "That account is gone. Sign in with Google again.")
    await identities.attach(db, email_uid, user, "email", pending["email"])
    await identities.attach(db, pending["uid"], user, "google")
    _fill_profile(user, pending.get("name"), pending["email"], pending.get("picture"))
    await db.commit()
    await request.app.state.redis.delete(_link_key(body.link_token))
    return _pair(user)


@router.post("/link/resend", status_code=202)
async def link_resend(body: LinkTokenRequest, request: Request):
    pending = await _pending_link(request, body.link_token)
    return await _send_code(pending["email"], request.app.state.redis)


@router.post("/link/separate", response_model=TokenPairOut)
async def link_separate(body: LinkTokenRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Keep Google as its own, separate account after all."""
    pending = await _pending_link(request, body.link_token)
    user = await identities.resolve(db, pending["uid"])
    if user is None:
        user = User(email=identities.legacy_email(pending["uid"]), password_hash=OAUTH_SENTINEL)
        db.add(user)
        await db.flush()
        await identities.attach(db, pending["uid"], user, "google")
    _fill_profile(user, pending.get("name"), pending["email"], pending.get("picture"))
    await db.commit()
    await request.app.state.redis.delete(_link_key(body.link_token))
    return _pair(user)


# ------------------------------------------------------ sign-in methods
def _method_out(row) -> dict:
    return {"method": row.method, "email": _masked(row.email) if row.email else None,
            "created_at": row.created_at}


async def _connect(db: AsyncSession, me: User, uid: str, method: str, email: str | None) -> IdentitiesOut:
    other = await identities.resolve(db, uid)
    merged = None
    if other is not None and other.id != me.id:
        try:
            merged = await identities.merge(db, me, other)
        except ValueError as e:
            await db.rollback()
            raise APIError(409, "merge_blocked", e.args[0][0]["message"], details={"blockers": e.args[0]})
    await identities.attach(db, uid, me, method, email)
    await db.commit()
    return IdentitiesOut(methods=[_method_out(r) for r in await identities.methods(db, me)], merged=merged)


@router.get("/me/identities", response_model=IdentitiesOut)
async def my_identities(user: User = Depends(get_session_user), db: AsyncSession = Depends(get_db)):
    """The ways into this account (emailed code, Google)."""
    rows = await identities.methods(db, user)
    if not rows:
        # An account from before identities: its one sign-in, recorded now.
        if user.email.startswith("decane_"):
            await identities.resolve(db, user.email.removeprefix("decane_").removesuffix("@users.vivid"))
            await db.commit()
            rows = await identities.methods(db, user)
    return IdentitiesOut(methods=[_method_out(r) for r in rows])


@router.post("/me/identities/email/start", status_code=202)
async def connect_email_start(body: EmailStartRequest, request: Request,
                              user: User = Depends(get_session_user)):
    """A code to the address to connect (as for sign-in)."""
    return await _send_code(body.email.strip().lower(), getattr(request.app.state, "redis", None))


@router.post("/me/identities/email", response_model=IdentitiesOut)
async def connect_email(body: EmailVerifyRequest, user: User = Depends(get_session_user),
                        db: AsyncSession = Depends(get_db)):
    """Connect an emailed-code sign-in. When that address already has its
    own Vivid account, that account is merged into this one (merged says
    what moved); 409 merge_blocked when money makes that unsafe."""
    email = body.email.strip().lower()
    try:
        result = await decane.verify_email(email, body.code.strip())
    except decane.DecaneError as e:
        raise _decane_error(e)
    uid = str(_claims(str(result.get("jwt") or ""))["uid"])
    return await _connect(db, user, uid, "email", email)


@router.post("/me/identities/google", response_model=IdentitiesOut)
async def connect_google(body: DecaneLoginRequest, user: User = Depends(get_session_user),
                         db: AsyncSession = Depends(get_db)):
    """Connect Google: the `decane_jwt` from a Google sign-in done while
    signed in here. Merges its account into this one, as for email."""
    uid = str(_claims(body.access_token)["uid"])
    return await _connect(db, user, uid, "google", None)


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return user


# ------------------------------------------------------------ deleting
def _masked(email: str) -> str:
    name, _, domain = email.partition("@")
    return f"{name[:2]}{'*' * max(len(name) - 2, 1)}@{domain}"


def _deletion_email(user: User) -> str:
    if not user.profile_email:
        raise APIError(409, "no_email",
                       "This account has no email address to confirm with. Write to support to delete it.")
    return user.profile_email.strip().lower()


@router.get("/me/deletion", response_model=DeletionPreviewOut)
async def deletion_preview(user: User = Depends(get_session_user), db: AsyncSession = Depends(get_db)):
    """What deleting this account would do, for the confirmation screen."""
    out = await account.preview(db, user)
    return {**out, "confirm_email": _masked(user.profile_email.strip().lower()) if user.profile_email else None}


@router.post("/me/deletion-code", status_code=202)
async def deletion_code(request: Request, user: User = Depends(get_session_user)):
    """Emails a code to the account's own address; DELETE /auth/me takes it.
    Same budget as sign-in codes (a minute apart, three an hour)."""
    email = _deletion_email(user)
    out = await _send_code(email, getattr(request.app.state, "redis", None))
    return {**out, "sent_to": _masked(email)}


@router.delete("/me", response_model=DeletionOut)
async def delete_me(body: DeleteMeRequest, request: Request, user: User = Depends(get_session_user),
                    db: AsyncSession = Depends(get_db)):
    """Delete the account: refused (409 cannot_delete, details.blockers)
    while money is owed to the person; otherwise projects, files, keys and
    phones go now, money records are kept seven years, and every token stops
    working. The code is the one POST /auth/me/deletion-code emailed."""
    from app.api.routes.builder import delete_project_row
    from app.builder import snapshots
    email = _deletion_email(user)
    stuck = await account.blockers(db, user)
    if stuck:
        raise APIError(409, "cannot_delete", stuck[0]["message"], details={"blockers": stuck})
    try:
        await decane.verify_email(email, body.code.strip())
    except decane.DecaneError as e:
        raise _decane_error(e)
    redis = getattr(request.app.state, "redis", None)
    project_ids: list[str] = []

    async def drop(project):
        project_ids.append(project.id)
        await delete_project_row(db, project, redis)
    try:
        out = await account.delete_account(db, user, drop)
    except ValueError as e:
        raise APIError(409, "cannot_delete", e.args[0][0]["message"], details={"blockers": e.args[0]})
    await db.commit()
    for pid in project_ids:
        try:
            await snapshots.delete_all(pid)
        except Exception as ex:                          # storage only; the account is gone
            log.warning("snapshots of %s not removed after account deletion: %s", pid, ex)
    return {"deleted": True, **out}


# ------------------------------------------------------- web handoff
def _handoff_key(token: str) -> str:
    return "auth:handoff:" + hashlib.sha256(token.encode()).hexdigest()[:32]


@router.post("/handoff", response_model=HandoffOut)
async def handoff(body: HandoffRequest, user: User = Depends(get_session_user)):
    """A link that opens the web app signed in as this user, for what a
    store app may not sell itself (plans, credits, top-ups). Two minutes,
    one use."""
    token = create_handoff_token(user.id)
    nxt = body.next if body.next and body.next.startswith("/") and not body.next.startswith("//") else "/settings/billing"
    url = (f"{settings.WEB_BASE_URL.rstrip('/')}/auth/handoff?token={token}"
           f"&next={nxt}")
    return {"url": url, "token": token, "expires_in": 120}


@router.post("/handoff/exchange", response_model=TokenPairOut)
async def handoff_exchange(body: HandoffExchangeRequest, request: Request,
                           db: AsyncSession = Depends(get_db)):
    """The web app trades the handoff token for a session, once."""
    try:
        user_id = decode_token(body.token, "handoff")
    except pyjwt.InvalidTokenError:
        raise APIError(401, "handoff_expired", "That link has expired. Open it again from the app.")
    redis = getattr(request.app.state, "redis", None)
    if redis is not None:
        try:
            fresh = await redis.set(_handoff_key(body.token), "1", nx=True, ex=180)
        except Exception:
            fresh = True
        if not fresh:
            raise APIError(401, "handoff_used", "That link was already used. Open it again from the app.")
    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise APIError(401, "unauthorized", "Unknown user")
    return _pair(user)


@router.patch("/me", response_model=UserOut)
async def update_me(body: ProfileUpdate, user: User = Depends(get_current_user),
                    db: AsyncSession = Depends(get_db)):
    user.name = body.name.strip()
    await db.commit()
    return user


@router.post("/refresh", response_model=TokenPairOut)
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    # No bearer is needed here, and a stale one is ignored: only the body's
    # refresh token counts. `refresh_expired` means "sign in again".
    try:
        user_id = decode_token(body.refresh_token, "refresh")
    except pyjwt.InvalidTokenError:
        raise APIError(401, "refresh_expired", "The refresh token is invalid or expired; sign in again.")
    user = await db.get(User, user_id)
    if user is None:
        raise APIError(401, "refresh_expired", "Unknown user; sign in again.")
    return _pair(user)
