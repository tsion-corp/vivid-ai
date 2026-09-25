import hashlib
import json
import time

import jwt as pyjwt
from app.core.errors import APIError
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core.config import settings
from app.core.security import (create_token_pair, decode_token, hash_password,
                               verify_password)
from app.db.models import User
from app.schemas.auth import (DecaneLoginRequest, EmailStartRequest, EmailVerifyRequest,
                              LoginRequest, ProfileUpdate, RefreshRequest,
                              SignupRequest, TokenPairOut, UserOut)
from app.services import decane

# Sentinel password hash for social-login accounts — it can never verify, so
# password login on these accounts always fails cleanly.
OAUTH_SENTINEL = "!oauth"

router = APIRouter(prefix="/auth", tags=["auth"])


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


async def _session(db: AsyncSession, access_token: str, name: str | None = None,
                   email: str | None = None, picture: str | None = None) -> TokenPairOut:
    """A verified Decane token -> Vivid's own token pair. The account is keyed
    on the token's stable `uid`, never on an email the caller supplies, which
    would allow account takeover."""
    try:
        claims = decane.verify_access_token(access_token)
    except decane.DecaneAuthError as e:
        status = 503 if "not configured" in str(e) else 401
        raise HTTPException(status_code=status, detail=str(e))

    # Synthetic, deterministic identity per Decane user — the email column is
    # our unique key and Decane tokens carry no verified email.
    identity = f"decane_{claims['uid']}@users.vivid"
    user = (await db.execute(
        select(User).where(User.email == identity))).scalar_one_or_none()
    if user is None:
        user = User(email=identity, password_hash=OAUTH_SENTINEL)
        db.add(user)
    # The profile fills what the account doesn't have yet: a real name, a
    # photo, and the address to show (the account key stays synthetic).
    if name and not user.name:
        user.name = name.strip()[:120]
    if picture and not user.avatar_url:
        user.avatar_url = picture[:1024]
    if email and not user.profile_email:
        user.profile_email = email.lower()[:320]
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


@router.post("/email/start", status_code=202)
async def email_start(body: EmailStartRequest, request: Request):
    """Emails a sign-in code. Always 202 for a well-formed address (whether
    an account exists is never revealed), unless this address has had a code
    too recently or too often, which is true of any address alike."""
    email = body.email.strip().lower()
    redis = getattr(request.app.state, "redis", None)
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


@router.post("/email/verify", response_model=TokenPairOut)
async def email_verify(body: EmailVerifyRequest, db: AsyncSession = Depends(get_db)):
    email = body.email.strip().lower()
    try:
        result = await decane.verify_email(email, body.code.strip())
    except decane.DecaneError as e:
        raise _decane_error(e)
    profile = result.get("profile") or {}
    return await _session(db, str(result.get("jwt") or ""), name=profile.get("name"),
                          email=profile.get("email") or email, picture=profile.get("picture"))


@router.get("/google/start")
async def google_start():
    """Where to send the browser for Google; it comes back to the callback
    registered in Decane with `decane_jwt`, which POST /auth/decane takes."""
    try:
        return {"url": await decane.google_consent_url()}
    except decane.DecaneError as e:
        raise _decane_error(e)


@router.post("/decane", response_model=TokenPairOut)
async def decane_login(body: DecaneLoginRequest,
                       db: AsyncSession = Depends(get_db)):
    """The end of the Google redirect: the `decane_jwt` Decane put on the
    callback URL, verified offline (ES256, JWKS) and traded for a session."""
    return await _session(db, body.access_token, body.name, body.email, body.picture)


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return user


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
