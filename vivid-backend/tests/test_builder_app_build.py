"""Installable mobile builds on EAS: the token only ever reaches the eas
commands of a throwaway sandbox, app.json gets the store ids, the build is
followed from Expo's API until it ends, Vivid-account builds are charged and
refunded when they fail, and the routes refuse what cannot work."""
import asyncio
import json
import time

import pytest

from app.api.routes import builder as builder_routes
from app.builder import app_build, billing, expo, targets
from app.builder.sandbox.base import RunResult
from app.core.config import settings
from app.db.models import (BuilderAppBuild, BuilderProject, BuilderSnapshot, BuilderUsageEvent,
                           Connector)
from tests.builder_fakes import FakeSandbox
from tests.test_builder_routes import client, fake_blob, fake_manager, maker  # noqa: F401

TOKEN = "vivid-robot-token-0123456789abcdef"


def build_sandbox() -> FakeSandbox:
    sb = FakeSandbox({"app.json": json.dumps({"expo": {"name": "Vivid App", "slug": "vivid-app"}}),
                      "app.config.js": "module.exports = () => process.env"})
    sb.target = targets.get(targets.MOBILE)
    sb.responses = [
        ("eas init", RunResult(0, json.dumps({"projectId": "eas-proj-1", "status": "created"}), "")),
        ("eas build", RunResult(0, json.dumps([{"id": "eas-build-1", "status": "IN_QUEUE"}]), "")),
    ]
    return sb


class FakeFreshManager:
    def __init__(self, sandbox):
        self.sandbox, self.made = sandbox, []

    async def create_fresh(self, project_id, target=None, wait=True):
        self.made.append((project_id, target.name if target else None, wait))
        return self.sandbox


@pytest.fixture
def eas(monkeypatch, maker):
    monkeypatch.setattr(settings, "EXPO_TOKEN", TOKEN)
    monkeypatch.setattr(settings, "EXPO_OWNER", "vivid-apps")
    monkeypatch.setattr(settings, "EAS_VIVID_BUILDS_PER_MONTH", 2)
    monkeypatch.setattr(app_build, "async_session", maker)
    sb = build_sandbox()
    fm = FakeFreshManager(sb)
    monkeypatch.setattr(app_build, "manager", fm)

    async def restore(sandbox, snapshot):
        sandbox.restored += 1
    monkeypatch.setattr(app_build.snapshots, "restore", restore)
    remote = {"status": expo.IN_PROGRESS, "artifact": None, "error": None, "cancelled": []}

    async def fake_build(token, build_id):
        assert token == TOKEN
        return expo.BuildInfo(id=build_id, status=remote["status"], platform="android",
                              artifact_url=remote["artifact"], error=remote["error"],
                              logs_url=f"https://expo.dev/builds/{build_id}")

    async def fake_cancel(token, build_id):
        remote["cancelled"].append(build_id)
        return expo.CANCELED
    monkeypatch.setattr(app_build.expo, "build", fake_build)
    monkeypatch.setattr(app_build.expo, "cancel", fake_cancel)
    return {"sandbox": sb, "manager": fm, "remote": remote}


async def _project(maker, target="mobile", snapshot=True) -> tuple[str, str | None]:
    async with maker() as db:
        p = BuilderProject(owner_id="u1", name="Mama's Kitchen!", mode="build", target=target)
        db.add(p)
        await db.flush()
        sid = None
        if snapshot:
            s = BuilderSnapshot(project_id=p.id, seq=1, r2_key="k", commit_sha="c",
                                summary="first", size_bytes=1)
            db.add(s)
            await db.flush()
            p.current_snapshot_id = sid = s.id
        await db.commit()
        return p.id, sid


async def _build(maker, pid, sid, account="vivid", platform="android") -> str:
    async with maker() as db:
        b = BuilderAppBuild(project_id=pid, snapshot_id=sid, platform=platform,
                            profile="preview", account=account)
        db.add(b)
        await db.flush()
        billing.charge(db, b)
        await db.commit()
        return b.id


# ------------------------------------------------------------------ start
async def test_a_build_starts_in_a_throwaway_sandbox_with_the_token_only_in_eas(eas, maker):
    pid, sid = await _project(maker)
    bid = await _build(maker, pid, sid)
    await app_build.start(bid)

    sb = eas["sandbox"]
    assert eas["manager"].made == [(f"build-{bid}", "mobile", False)] and sb.killed
    assert sb.restored == 1 and "app.config.js" in " ".join(sb.commands)
    # The token went to the two eas commands' environment, nowhere else.
    for cmd, env in zip(sb.commands, sb.envs):
        assert TOKEN not in cmd
        assert (env.get("EXPO_TOKEN") == TOKEN) == cmd.startswith("eas "), cmd
    assert TOKEN not in json.dumps(sb.files)
    app = json.loads(sb.files["app.json"])["expo"]
    assert app["owner"] == "vivid-apps" and app["name"] == "Mama's Kitchen!"
    assert app["ios"]["bundleIdentifier"] == app["android"]["package"]
    assert app["android"]["package"].startswith("app.vivid.mamaskitchen")

    async with maker() as db:
        b = await db.get(BuilderAppBuild, bid)
        p = await db.get(BuilderProject, pid)
        assert b.eas_build_id == "eas-build-1" and b.status == app_build.QUEUED
        assert b.charge == billing.CHARGED and b.price == settings.EAS_BUILD_PRICE_ANDROID
        assert p.eas_projects == {"vivid-apps": "eas-proj-1"} and p.app_id == app["ios"]["bundleIdentifier"]

    # The next build reuses the EAS project: no second init.
    sb.commands.clear()
    await app_build.start(await _build(maker, pid, sid))
    assert not any(c.startswith("eas init") for c in sb.commands)
    assert json.loads(sb.files["app.json"])["expo"]["extra"]["eas"]["projectId"] == "eas-proj-1"


async def test_a_build_that_cannot_start_fails_and_is_refunded(eas, maker):
    eas["sandbox"].responses[1] = ("eas build", RunResult(1, "", "Error: bundle identifier taken"))
    pid, sid = await _project(maker)
    bid = await _build(maker, pid, sid)
    await app_build.start(bid)
    async with maker() as db:
        b = await db.get(BuilderAppBuild, bid)
        assert b.status == app_build.FAILED and "bundle identifier taken" in b.error
        assert b.charge == billing.REFUNDED
        events = (await db.execute(
            BuilderUsageEvent.__table__.select().where(BuilderUsageEvent.kind == "app_build"))).all()
        assert sorted(float(e.quantity) for e in events) == [-1.0, 1.0]
    assert eas["sandbox"].killed


# --------------------------------------------------------------- following
async def test_the_poller_follows_a_build_to_its_artifact(eas, maker):
    pid, sid = await _project(maker)
    bid = await _build(maker, pid, sid)
    await app_build.start(bid)
    await app_build.poll_once()
    async with maker() as db:
        assert (await db.get(BuilderAppBuild, bid)).status == app_build.BUILDING
    eas["remote"].update(status=expo.FINISHED, artifact="https://expo.dev/artifacts/app.apk")
    await app_build.poll_once()
    async with maker() as db:
        b = await db.get(BuilderAppBuild, bid)
        assert b.status == app_build.FINISHED and b.artifact_url.endswith("app.apk")
        assert b.finished_at is not None and b.charge == billing.CHARGED


async def test_a_build_that_fails_on_expo_is_refunded(eas, maker):
    pid, sid = await _project(maker)
    bid = await _build(maker, pid, sid)
    await app_build.start(bid)
    eas["remote"].update(status=expo.ERRORED, error="Gradle build failed")
    await app_build.poll_once()
    async with maker() as db:
        b = await db.get(BuilderAppBuild, bid)
        assert b.status == app_build.FAILED and b.error == "Gradle build failed"
        assert b.charge == billing.REFUNDED


async def test_cancel_stops_it_on_expo_and_refunds(eas, maker):
    pid, sid = await _project(maker)
    bid = await _build(maker, pid, sid)
    await app_build.start(bid)
    async with maker() as db:
        b = await db.get(BuilderAppBuild, bid)
        await app_build.cancel(db, b, "u1")
        await db.commit()
        assert b.status == app_build.CANCELED and b.charge == billing.REFUNDED
    assert eas["remote"]["cancelled"] == ["eas-build-1"]


async def test_the_users_own_account_is_free_and_uses_their_token(eas, maker, monkeypatch):
    async with maker() as db:
        db.add(Connector(user_id="u1", provider="expo", name="expo (ada)", token="their-token-xyz",
                         config_json={"username": "ada", "owner": "ada"}))
        await db.commit()

    async def their_build(token, build_id):
        assert token == "their-token-xyz"
        return expo.BuildInfo(id=build_id, status=expo.FINISHED)
    monkeypatch.setattr(app_build.expo, "build", their_build)
    pid, sid = await _project(maker)
    bid = await _build(maker, pid, sid, account="user")
    await app_build.start(bid)
    assert eas["sandbox"].envs[-1]["EXPO_TOKEN"] == "their-token-xyz"
    await app_build.poll_once()
    async with maker() as db:
        b = await db.get(BuilderAppBuild, bid)
        assert b.price == 0 and b.charge == billing.NONE and b.eas_owner == "ada"
        assert b.status == app_build.FINISHED
        assert (await db.get(BuilderProject, pid)).eas_projects == {"ada": "eas-proj-1"}


def test_store_ids_are_valid_for_both_stores():
    p = BuilderProject(id="1234abcd-0000-0000-0000-000000000000", name="9ja Eats & Co.")
    p.app_id = app_build.app_id_for(p)
    assert p.app_id == "app.vivid.a9jaeatsco1234ab"
    assert app_build.slug_for(p) == "a9jaeatsco-1234ab"
    out = json.loads(app_build.with_store_ids('{"expo": {"extra": {"eas": {"projectId": "old"}}}}',
                                              p, "acct", None))["expo"]
    assert "projectId" not in out["extra"]["eas"] and out["owner"] == "acct"


# ------------------------------------------------------------------ routes
def _wait_for(client, url, done, tries=40):
    for _ in range(tries):
        body = client.get(url).json()
        if done(body):
            return body
        time.sleep(0.05)
    return body


def test_build_routes(client, maker, eas, monkeypatch):
    real_create_task = asyncio.create_task

    async def later(coro):
        await asyncio.sleep(0.2)
        return await coro
    monkeypatch.setattr(builder_routes.asyncio, "create_task",
                        lambda coro: real_create_task(later(coro)))
    web_pid, _ = asyncio.run(_project(maker, target="web"))
    r = client.post(f"/v1/builder/projects/{web_pid}/builds", json={"platform": "android"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "not_supported"

    bare, _ = asyncio.run(_project(maker, snapshot=False))
    r = client.post(f"/v1/builder/projects/{bare}/builds", json={"platform": "android"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "no_snapshot"

    pid, _ = asyncio.run(_project(maker))
    assert client.post(f"/v1/builder/projects/{pid}/publish").json()["error"]["code"] == "not_supported"
    r = client.post(f"/v1/builder/projects/{pid}/builds", json={"platform": "ios", "profile": "production"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "needs_own_account"
    r = client.post(f"/v1/builder/projects/{pid}/builds", json={"platform": "android", "account": "user"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "not_connected"

    opts = client.get("/v1/builder/app-builds/options").json()
    assert opts["default"] == "vivid" and opts["accounts"][0]["remaining"] == 2
    assert opts["accounts"][0]["price_android"] == settings.EAS_BUILD_PRICE_ANDROID

    r = client.post(f"/v1/builder/projects/{pid}/builds", json={"platform": "android"})
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["status"] == "starting" and body["account"] == "vivid" and body["charge"] == "charged"
    # One android build at a time.
    again = client.post(f"/v1/builder/projects/{pid}/builds", json={"platform": "android"})
    assert again.status_code == 409
    url = f"/v1/builder/projects/{pid}/builds/{body['id']}"
    got = _wait_for(client, url, lambda b: b["status"] != "starting")
    assert got["status"] in ("queued", "building")
    eas["remote"].update(status=expo.FINISHED, artifact="https://x/app.apk")
    got = _wait_for(client, url, lambda b: b["status"] == "finished")
    assert got["artifact_url"] == "https://x/app.apk"
    assert [b["id"] for b in client.get(f"/v1/builder/projects/{pid}/builds").json()] == [body["id"]]

    # The monthly cap on Vivid's account: 2, one used.
    ios = client.post(f"/v1/builder/projects/{pid}/builds", json={"platform": "ios"})
    assert ios.status_code == 202
    _wait_for(client, f"/v1/builder/projects/{pid}/builds/{ios.json()['id']}",
              lambda b: b["status"] != "starting")
    eas["remote"].update(status=expo.FINISHED)
    _wait_for(client, f"/v1/builder/projects/{pid}/builds/{ios.json()['id']}",
              lambda b: b["status"] == "finished")
    r = client.post(f"/v1/builder/projects/{pid}/builds", json={"platform": "android"})
    assert r.status_code == 402 and r.json()["error"]["code"] == "payment_required"


# -------------------------------------------------------------- expo api
async def test_expo_build_info_and_whoami(monkeypatch):
    calls = []

    async def graphql(token, query, variables=None):
        calls.append((token, variables))
        if "meActor" in query:
            return {"meActor": {"__typename": "User", "id": "u", "username": "ada",
                                "accounts": [{"name": "ada"}, {"name": "ada-studio"}]}}
        return {"builds": {"byId": {
            "id": "b1", "status": "ERRORED", "platform": "ANDROID",
            "error": {"errorCode": "X", "message": "Gradle failed"},
            "artifacts": {"buildUrl": "https://x/app.apk", "applicationArchiveUrl": None},
            "app": {"slug": "shop-123abc", "ownerAccount": {"name": "ada"}}}}}
    monkeypatch.setattr(expo, "_graphql", graphql)
    info = await expo.build("t", "b1")
    assert (info.status, info.platform, info.artifact_url, info.error) == \
        ("ERRORED", "android", "https://x/app.apk", "Gradle failed")
    assert info.logs_url == "https://expo.dev/accounts/ada/projects/shop-123abc/builds/b1"
    assert calls[-1] == ("t", {"buildId": "b1"})

    from app.services.connectors import expo as expo_connector
    out = await expo_connector.verify("a" * 40)
    assert out["login"] == "ada" and out["config"]["owner"] == "ada"
    assert out["config"]["accounts"] == ["ada", "ada-studio"]
    with pytest.raises(ValueError):
        await expo_connector.verify("short")


async def test_expo_errors_are_readable(monkeypatch):
    with pytest.raises(expo.ExpoError, match="no Expo access token"):
        await expo.build("", "b1")
