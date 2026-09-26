"""Push notifications: phones register an Expo token; finished turns and
app builds are pushed to them; tokens Expo says are gone are dropped."""
import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.deps import get_db, get_session_user
from app.api.routes.push import router as push_router
from app.core import errors
from app.core.config import settings
from app.db.models import PushDevice, User
from app.services import push
from tests.test_builder_routes import maker  # noqa: F401

TOKEN = "ExponentPushToken[abcdefghij0123456789]"


@pytest.fixture
def api(maker):  # noqa: F811
    app = FastAPI()
    errors.install(app)
    app.include_router(push_router, prefix="/v1")
    who = {"id": "u1"}

    async def db():
        async with maker() as session:
            yield session

    async def user():
        async with maker() as session:
            return await session.get(User, who["id"])
    app.dependency_overrides[get_db] = db
    app.dependency_overrides[get_session_user] = user
    with TestClient(app, raise_server_exceptions=False) as tc:
        tc.who = who
        yield tc


def test_a_phone_registers_moves_and_signs_out(api, maker):
    r = api.post("/v1/me/push-tokens", json={"token": TOKEN, "platform": "ios", "app_version": "1.0.0"})
    assert r.status_code == 201 and r.json()["token"] == TOKEN and r.json()["platform"] == "ios"
    # Every launch may register again: still one device.
    assert api.post("/v1/me/push-tokens", json={"token": TOKEN}).status_code == 201
    assert len(api.get("/v1/me/push-tokens").json()) == 1
    assert api.post("/v1/me/push-tokens", json={"token": "nope"}).json()["error"]["code"] == "invalid_token"
    # Someone else signs in on the same phone: the token is theirs now.
    api.who["id"] = "u2"
    api.post("/v1/me/push-tokens", json={"token": TOKEN})
    assert len(api.get("/v1/me/push-tokens").json()) == 1
    api.who["id"] = "u1"
    assert api.get("/v1/me/push-tokens").json() == []
    api.who["id"] = "u2"
    assert api.delete(f"/v1/me/push-tokens/{TOKEN}").status_code == 204
    assert api.get("/v1/me/push-tokens").json() == []
    assert api.delete(f"/v1/me/push-tokens/{TOKEN}").status_code == 204     # already gone: fine


class FakeExpo:
    def __init__(self, gone=()):
        self.posts, self.gone = [], set(gone)

    async def post(self, url, json=None, headers=None, timeout=None):
        self.posts.append((url, json, headers))
        tickets = [{"status": "error", "message": "gone", "details": {"error": "DeviceNotRegistered"}}
                   if m["to"] in self.gone else {"status": "ok", "id": "t"} for m in json]

        class R:
            status_code = 200
            text = ""

            def json(self_inner):
                return {"data": tickets}
        return R()


def test_sending_reaches_every_phone_and_drops_uninstalled_ones(maker, monkeypatch):  # noqa: F811
    monkeypatch.setattr(settings, "PUSH_ENABLED", True)
    monkeypatch.setattr(settings, "EXPO_PUSH_ACCESS_TOKEN", "expo-secret")
    import app.db.session as session_mod
    monkeypatch.setattr(session_mod, "async_session", maker)
    tokens = [f"ExponentPushToken[device{i:04d}xxxxxxxx]" for i in range(150)]

    async def seed():
        async with maker() as db:
            for t in tokens:
                db.add(PushDevice(user_id="u1", token=t, platform="android"))
            await db.commit()
    asyncio.run(seed())
    fake = FakeExpo(gone={tokens[3]})
    monkeypatch.setattr(push.http, "client", lambda: fake)

    sent = asyncio.run(push.send("u1", "Crumbs", "Built a bakery site.", {"type": "turn"}))
    assert sent == 149 and len(fake.posts) == 2                   # 100 a request
    first = fake.posts[0][1][0]
    assert first["title"] == "Crumbs" and first["data"] == {"type": "turn"}
    assert fake.posts[0][2]["authorization"] == "Bearer expo-secret"

    async def left():
        async with maker() as db:
            return [d.token for d in (await db.execute(select(PushDevice))).scalars()]
    remaining = asyncio.run(left())
    assert tokens[3] not in remaining and len(remaining) == 149
    # Nobody to tell, or pushes off: nothing sent, nothing raised.
    assert asyncio.run(push.send("u2", "x", "y")) == 0
    monkeypatch.setattr(settings, "PUSH_ENABLED", False)
    assert asyncio.run(push.send("u1", "x", "y")) == 0


def test_what_finished_work_says(monkeypatch):
    sent = []
    monkeypatch.setattr(push, "send_later", lambda *a, **k: sent.append(a))
    push.turn_finished("u1", "p1", "Crumbs", ok=True, reason="answered",
                       summary="Built a one-page bakery site.", message_id="m1")
    push.turn_finished("u1", "p1", "Crumbs", ok=False, reason="step_limit", summary=None, message_id="m2")
    push.turn_finished("u1", "p1", "Crumbs", ok=False, reason="cancelled", summary=None, message_id="m3")
    push.turn_finished("u1", "p1", "", ok=True, reason="asked", summary=None, message_id="m4", planning=True)
    push.app_build_finished("u1", "p1", "Crumbs", build_id="b1", platform="android",
                            status="finished", artifact_url="https://x/app.apk")
    push.app_build_finished("u1", "p1", "Crumbs", build_id="b2", platform="ios",
                            status="canceled", artifact_url=None)
    assert [(s[1], s[2]) for s in sent] == [
        ("Crumbs", "Built a one-page bakery site."),
        ("Crumbs", "The build didn't finish. Open the app to see what happened."),
        ("Your app", "A question about your app is waiting for you."),
        ("Crumbs", "Your Android build is ready to install."),
    ]
    assert sent[0][3] == {"type": "turn", "project_id": "p1", "message_id": "m1", "ok": True}
    assert sent[3][3]["type"] == "app_build" and sent[3][3]["artifact_url"] == "https://x/app.apk"
