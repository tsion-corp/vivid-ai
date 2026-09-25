"""Vivid's own sign-in, driven from this server: the browser asks us, we ask
Decane with the publishable key, and the Decane token is verified and traded
for Vivid's own pair. Decane itself is faked here."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.deps import get_db
from app.api.routes.auth import router as auth_router
from app.core import errors
from app.core.config import settings
from app.db.models import User
from app.services import decane
from tests.conftest import FakeRedis
from tests.test_builder_routes import maker  # noqa: F401

REAL_CALL = decane._call


class FakeDecane:
    def __init__(self):
        self.calls: list[tuple] = []
        self.fail: decane.DecaneError | None = None

    async def call(self, method, path, body=None, origin=None):
        self.calls.append((method, path, body))
        self.origin = origin
        if self.fail:
            raise self.fail
        if path == "/auth/email/start":
            return {"ok": True}
        if path == "/auth/email/verify":
            return {"jwt": "tok-u1", "userId": "u1", "isNewUser": True, "hasShare": False,
                    "profile": {"email": body["email"]}}
        if path == "/auth/google/init":
            return {"url": "https://accounts.google.com/o/oauth2/v2/auth?x=1"}
        raise AssertionError(path)


@pytest.fixture
def fake(monkeypatch):
    f = FakeDecane()
    monkeypatch.setattr(settings, "DECANE_APP_ID", "app-1")
    monkeypatch.setattr(settings, "DECANE_API_KEY", "dck_live_x")
    monkeypatch.setattr(decane, "_call", f.call)

    def verify(token):
        if not token.startswith("tok-"):
            raise decane.DecaneAuthError("invalid token")
        return {"uid": token.removeprefix("tok-"), "project_id": "app-1"}
    monkeypatch.setattr(decane, "verify_access_token", verify)
    return f


@pytest.fixture
def api(maker):  # noqa: F811
    app = FastAPI()
    errors.install(app)
    app.include_router(auth_router, prefix="/v1")
    app.state.redis = FakeRedis()

    async def db():
        async with maker() as session:
            yield session
    app.dependency_overrides[get_db] = db
    with TestClient(app, raise_server_exceptions=False) as tc:
        yield tc


def test_an_emailed_code_signs_in_from_the_server(api, maker, fake):
    assert api.post("/v1/auth/email/start", json={"email": " Ada@Example.com "}).status_code == 202
    assert fake.calls[-1] == ("POST", "/auth/email/start", {"email": "ada@example.com"})
    out = api.post("/v1/auth/email/verify", json={"email": "ada@example.com", "code": " 123456 "})
    assert out.status_code == 200, out.json()
    body = out.json()
    assert body["access_token"] and body["refresh_token"]
    assert fake.calls[-1] == ("POST", "/auth/email/verify", {"email": "ada@example.com", "code": "123456"})

    async def user():
        async with maker() as db:
            return (await db.execute(select(User).where(User.email == "decane_u1@users.vivid"))).scalar_one()
    import asyncio
    u = asyncio.run(user())
    assert u.profile_email == "ada@example.com" and body["user"]["id"] == u.id
    # The same person again is the same account.
    again = api.post("/v1/auth/email/verify", json={"email": "ada@example.com", "code": "654321"}).json()
    assert again["user"]["id"] == u.id


@pytest.mark.parametrize("error,status,code", [
    (decane.DecaneError("INVALID_CODE", "bad", 400), 400, "invalid_code"),
    (decane.DecaneError("RATE_LIMITED", "slow down", 429), 429, "rate_limited"),
    (decane.DecaneError("unreachable", "down"), 502, "sign_in_unavailable"),
])
def test_decane_failures_are_safe_to_show(api, fake, error, status, code):
    fake.fail = error
    out = api.post("/v1/auth/email/verify", json={"email": "ada@example.com", "code": "123456"})
    assert out.status_code == status and out.json()["error"]["code"] == code
    assert "slow down" not in out.text and "down" not in out.json()["error"]["message"].split()


def test_not_configured_and_bad_input(api, fake, monkeypatch):
    assert api.post("/v1/auth/email/start", json={"email": "not-an-email"}).status_code == 422
    monkeypatch.setattr(decane, "_call", REAL_CALL)        # no key: never reaches Decane
    monkeypatch.setattr(settings, "DECANE_API_KEY", "")
    out = api.post("/v1/auth/email/start", json={"email": "ada@example.com"})
    assert out.status_code == 503 and out.json()["error"]["code"] == "not_configured"


def test_google_starts_from_the_server(api, fake):
    out = api.get("/v1/auth/google/start")
    assert out.json()["url"].startswith("https://accounts.google.com/")
    assert fake.calls[-1][:2] == ("GET", "/auth/google/init")
    # The host the person started from picks which of the key's callbacks
    # Google returns them to (Referer for a plain navigation).
    assert fake.origin is None
    api.get("/v1/auth/google/start", headers={"origin": "https://vividbuild.ai"})
    assert fake.origin == "https://vividbuild.ai"
    api.get("/v1/auth/google/start", headers={"referer": "https://vivid-build.vercel.app/"})
    assert fake.origin == "https://vivid-build.vercel.app/"


def test_codes_per_address_are_counted_so_nobody_hammers_a_silent_button(api, fake, monkeypatch):
    from app.api.routes import auth
    clock = [1_000_000.0]
    monkeypatch.setattr(auth.time, "time", lambda: clock[0])
    first = api.post("/v1/auth/email/start", json={"email": "ada@example.com"})
    assert first.status_code == 202 and first.json()["codes_left"] == 2
    again = api.post("/v1/auth/email/start", json={"email": "ADA@example.com"})
    assert again.status_code == 429 and again.json()["error"]["code"] == "code_just_sent"
    # Another address has its own budget: nothing is shared across people.
    assert api.post("/v1/auth/email/start", json={"email": "tunde@example.com"}).status_code == 202
    for _ in range(2):
        clock[0] += 61
        assert api.post("/v1/auth/email/start", json={"email": "ada@example.com"}).status_code == 202
    clock[0] += 61
    out = api.post("/v1/auth/email/start", json={"email": "ada@example.com"})
    assert out.status_code == 429 and out.json()["error"]["code"] == "too_many_codes"
    assert sum(1 for c in fake.calls if c[2] == {"email": "ada@example.com"}) == 3
    clock[0] += 3600
    assert api.post("/v1/auth/email/start", json={"email": "ada@example.com"}).status_code == 202
