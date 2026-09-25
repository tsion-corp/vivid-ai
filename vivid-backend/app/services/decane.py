"""Decane sign-in for Vivid's own users: the calls that sign someone in
(email code, Google) and the verification of the token they produce.

Access-token verification (spec: kit.decane.app/llms-node.txt).

Tokens are ES256 JWTs. Verification is offline against either the project's
static public key (DECANE_VERIFICATION_KEY, SPKI PEM) or Decane's JWKS at
{DECANE_API_BASE}/.well-known/jwks.json. The claim that matters for identity
is `uid` — a stable user UUID; `project_id` must match our app id (Decane's
audience-equivalent). Email is deliberately NOT in the token.
"""
import httpx
import jwt
from jwt import PyJWKClient

from app.core.config import settings
from app.services.models_gateway import http


class DecaneAuthError(Exception):
    pass


_jwks_client: PyJWKClient | None = None


def _jwks() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = PyJWKClient(
            f"{settings.DECANE_API_BASE.rstrip('/')}/.well-known/jwks.json",
            cache_keys=True, lifespan=3600)
    return _jwks_client


def verify_access_token(token: str) -> dict:
    """Returns the verified claims; raises DecaneAuthError on any problem."""
    if not settings.DECANE_APP_ID:
        raise DecaneAuthError("Decane sign-in is not configured")
    try:
        if settings.DECANE_VERIFICATION_KEY:
            # .env files are single-line: the PEM arrives with literal \n.
            key = settings.DECANE_VERIFICATION_KEY.replace("\\n", "\n")
        else:
            key = _jwks().get_signing_key_from_jwt(token).key
        # Decane's clock runs a second or two ahead of ours, so a fresh
        # token's `iat` can sit in the future and PyJWT rejects it as "not
        # yet valid". A small leeway absorbs that skew without weakening the
        # expiry check in any meaningful way.
        claims = jwt.decode(token, key, algorithms=["ES256"],
                            options={"verify_aud": False}, leeway=30)
    except jwt.PyJWTError as e:
        raise DecaneAuthError(f"invalid token: {e}") from e
    if claims.get("project_id") != settings.DECANE_APP_ID:
        raise DecaneAuthError("token was issued for a different app")
    if not claims.get("uid"):
        raise DecaneAuthError("token has no user id")
    return claims


# ------------------------------------------------------------------ sign-in
# Server-side sign-in with the publishable key (Decane's Python guide). The
# browser never talks to Decane; it asks us, we ask Decane, and the Decane
# token only lives long enough to be verified and traded for Vivid's own.

class DecaneError(Exception):
    """Decane refused or could not be reached. `code` is Decane's (INVALID_CODE,
    RATE_LIMITED, ...) or our own (not_configured, unreachable)."""

    def __init__(self, code: str, message: str, status: int = 502):
        super().__init__(message)
        self.code, self.status = code, status


def sign_in_configured() -> bool:
    return bool(settings.DECANE_APP_ID and settings.DECANE_API_KEY)


async def _call(method: str, path: str, body: dict | None = None) -> dict:
    if not sign_in_configured():
        raise DecaneError("not_configured", "Sign-in is not set up on this server.", 503)
    try:
        r = await http.client().request(
            method, f"{settings.DECANE_API_BASE.rstrip('/')}{path}", json=body,
            headers={"X-API-Key": settings.DECANE_API_KEY, "X-App-Id": settings.DECANE_APP_ID},
            timeout=settings.DECANE_AUTH_TIMEOUT)
    except httpx.HTTPError as e:
        raise DecaneError("unreachable", f"Sign-in is unavailable right now ({e.__class__.__name__}).")
    data = r.json() if r.content else {}
    if r.status_code >= 400:
        err = data.get("error") if isinstance(data.get("error"), dict) else {}
        raise DecaneError(str(err.get("code") or r.status_code), str(err.get("message") or ""),
                          r.status_code)
    return data


async def start_email(email: str) -> None:
    """Emails a six-digit code. Succeeds for any address (Decane will not say
    whether one exists, and neither do we)."""
    await _call("POST", "/auth/email/start", {"email": email})


async def verify_email(email: str, code: str) -> dict:
    """{jwt, userId, isNewUser, hasShare, profile}."""
    return await _call("POST", "/auth/email/verify", {"email": email, "code": code})


async def google_consent_url() -> str:
    """Decane's hosted Google flow: the browser goes here and comes back to
    the callback registered against the key, with `decane_jwt`."""
    url = (await _call("GET", "/auth/google/init")).get("url")
    if not url:
        raise DecaneError("not_configured", "Google sign-in is not set up for this Decane key. "
                          "Add a callback URL in the Decane dashboard.", 503)
    return url
