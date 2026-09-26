"""Request dependencies: the database session and who is calling.

Two credential kinds share one `Authorization: Bearer` header:

  eyJ...   a user access token (the web app)
  vk_...   a partner API key (the SDK)

They are told apart by prefix, not by trying both — trying both would mean a
bad key produces a JWT decode error, which is a confusing thing to hand a
partner. Both resolve to a `Principal`, so routes stay unaware of which was
used unless they care (browser routes do, for per-key quotas).
"""
from dataclasses import dataclass
from datetime import datetime, timezone

import jwt as pyjwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import APIError
from app.core.security import decode_token, hash_api_key, looks_like_api_key
from app.db.models import ApiKey, User
from app.db.session import async_session

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass
class Principal:
    """Who is making this request, and under which client's configuration."""
    user: User
    client_id: str
    #: None for user tokens; the key row for partner traffic.
    api_key: ApiKey | None = None

    @property
    def is_partner(self) -> bool:
        return self.api_key is not None

    @property
    def owner_id(self) -> str:
        """Quota and ownership scope: the key for partners, the user for the
        web app. A partner's sessions belong to the key, not the service
        account, so revoking one key does not touch another's."""
        return self.api_key.id if self.api_key else self.user.id

    @property
    def max_sessions(self) -> int:
        return (self.api_key.max_sessions if self.api_key
                else settings.BROWSER_SESSIONS_PER_KEY)


async def get_db() -> AsyncSession:
    async with async_session() as session:
        yield session


async def _from_api_key(credential: str, db: AsyncSession) -> Principal:
    key = (await db.execute(
        select(ApiKey).where(ApiKey.key_hash == hash_api_key(credential))
    )).scalar_one_or_none()
    if key is None:
        raise APIError(401, "unauthorized", "Invalid API key")
    if key.revoked_at is not None:
        raise APIError(401, "unauthorized", "This API key has been revoked")

    user = await db.get(User, key.user_id)
    if user is None:
        raise APIError(401, "unauthorized",
                       "This API key's service account no longer exists")

    # Best-effort last-used stamp: a separate UPDATE so it cannot interfere
    # with whatever the request itself commits, and never fatal — a partner
    # request must not fail because a bookkeeping write did.
    try:
        await db.execute(update(ApiKey).where(ApiKey.id == key.id)
                         .values(last_used_at=datetime.now(timezone.utc)))
        await db.commit()
    except Exception:
        await db.rollback()

    return Principal(user=user, client_id=key.client_id, api_key=key)


async def _from_access_token(credential: str, db: AsyncSession) -> Principal:
    try:
        user_id = decode_token(credential, "access")
    except pyjwt.InvalidTokenError:
        raise APIError(401, "unauthorized", "Invalid or expired token")
    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise APIError(401, "unauthorized", "Unknown user")
    return Principal(user=user, client_id=settings.DEFAULT_CLIENT_ID)


async def get_principal(
        creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
        db: AsyncSession = Depends(get_db)) -> Principal:
    if creds is None:
        raise APIError(401, "unauthorized", "Not authenticated")
    credential = creds.credentials
    if looks_like_api_key(credential):
        return await _from_api_key(credential, db)
    return await _from_access_token(credential, db)


async def get_current_user(
        principal: Principal = Depends(get_principal)) -> User:
    """The user behind the request, whichever credential was used.

    Every existing route keeps its signature; a partner key simply resolves to
    its service-account user, so ownership checks work unchanged.
    """
    return principal.user


async def get_session_user(
        principal: Principal = Depends(get_principal)) -> User:
    """The signed-in human, and only them: an API key is refused here.

    Key management is the one place where "authenticated" is not enough. A key
    that could mint more keys would survive its own revocation — the holder
    just issues a replacement first — so creating, listing and revoking keys
    all require the session a person got by signing in.
    """
    if principal.is_partner:
        raise APIError(403, "session_required",
                       "This endpoint needs a signed-in session; an API key "
                       "cannot manage API keys.")
    return principal.user
