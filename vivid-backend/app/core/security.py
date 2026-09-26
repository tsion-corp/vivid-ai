import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import settings

# Developer API keys. The prefix makes a leaked key greppable in logs and
# scannable by secret-detection tooling; the random half is 32 bytes of
# urandom.
API_KEY_PREFIX = "vivid_"
#: `vk_` was the prefix before self-serve keys existed. Keys already issued to
#: partners are still valid, so both are accepted on the way in and only the
#: current one is ever minted.
LEGACY_KEY_PREFIXES = ("vk_",)
API_KEY_BYTES = 32
#: Characters of the key kept in the clear, for "which key is this?". Long
#: enough to be distinctive after the prefix, short enough to be useless to
#: anyone who sees it.
API_KEY_VISIBLE = len(API_KEY_PREFIX) + 8


def generate_api_key() -> tuple[str, str, str]:
    """Returns (full_key, prefix, key_hash). The full key is shown once and
    never stored — only its hash goes to the database."""
    token = secrets.token_urlsafe(API_KEY_BYTES)
    full = f"{API_KEY_PREFIX}{token}"
    return full, full[:API_KEY_VISIBLE], hash_api_key(full)


def hash_api_key(key: str) -> str:
    """SHA-256, deliberately. Keys are high-entropy random strings, so there is
    nothing to brute-force; bcrypt's cost would be paid on every request for no
    security gain."""
    return hashlib.sha256(key.encode()).hexdigest()


def looks_like_api_key(credential: str) -> bool:
    """Is this an API key rather than a JWT? Decides which table the
    credential is looked up in, nothing more — an unknown key still fails
    authentication."""
    return credential.startswith((API_KEY_PREFIX, *LEGACY_KEY_PREFIXES))


def hash_password(password: str) -> str:
    # bcrypt ignores input past 72 bytes; truncate explicitly so hash and
    # verify always agree.
    return bcrypt.hashpw(password.encode()[:72], bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode()[:72], password_hash.encode())
    except ValueError:
        return False


def _create_token(user_id: str, token_type: str, lifetime: timedelta) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": user_id, "type": token_type, "iat": now, "exp": now + lifetime}
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def create_token_pair(user_id: str) -> dict:
    return {
        "access_token": _create_token(
            user_id, "access", timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)),
        "refresh_token": _create_token(
            user_id, "refresh", timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)),
        "token_type": "bearer",
    }


def create_handoff_token(user_id: str) -> str:
    """Carries a signed-in phone's session to the web for two minutes; the
    exchange route makes it single-use."""
    return _create_token(user_id, "handoff", timedelta(minutes=2))


def decode_token(token: str, expected_type: str = "access") -> str:
    """Return the user id, raising jwt.InvalidTokenError on any problem."""
    payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    if payload.get("type") != expected_type:
        raise jwt.InvalidTokenError(f"expected a {expected_type} token")
    sub = payload.get("sub")
    if not sub:
        raise jwt.InvalidTokenError("token has no subject")
    return sub
