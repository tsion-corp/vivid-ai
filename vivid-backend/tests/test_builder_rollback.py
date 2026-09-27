"""Publishing keeps each build, so an earlier publish can be put back
exactly; unpublishing puts an offline page on the address."""
import asyncio
import time

from app.api.routes import builder as builder_routes
from app.builder import publish as publish_mod
from app.core.config import settings
from tests.test_builder_routes import client, fake_blob, fake_manager, maker  # noqa: F401


def wait(pid):
    for _ in range(200):
        task = builder_routes._publishing.get(pid)
        if task is None or task.done():
            return
        time.sleep(0.05)


def test_rollback_and_unpublish(client, maker, monkeypatch, fake_manager, fake_blob):  # noqa: F811
    monkeypatch.setattr(settings, "CF_API_TOKEN", "t")
    monkeypatch.setattr(settings, "CF_ACCOUNT_ID", "acct")
    monkeypatch.setattr(settings, "CF_PAGES_PROJECT", "vivid-apps")
    deployed = []

    class FakePages:
        async def deploy(self, site, alias, message):
            deployed.append((alias, site.files["index.html"]))
            return {"id": "dep"}
    monkeypatch.setattr(publish_mod, "Pages", FakePages)

    async def instant(url, timeout=90):
        return True
    monkeypatch.setattr(publish_mod, "wait_until_live", instant)
    real_create_task = asyncio.create_task

    async def later(coro):
        await asyncio.sleep(0.2)
        return await coro
    monkeypatch.setattr(builder_routes.asyncio, "create_task", lambda coro: real_create_task(later(coro)))

    sb = fake_manager.sandbox
    sb.files["src/App.tsx"] = "x"
    pid = client.post("/v1/builder/projects", json={"name": "Shop", "skip_plan": True}).json()["id"]
    assert client.post(f"/v1/builder/projects/{pid}/unpublish").status_code == 409     # never published
    assert client.post(f"/v1/builder/projects/{pid}/snapshots").status_code == 200

    sb.files["dist/index.html"] = "<html>first</html>"
    first = client.post(f"/v1/builder/projects/{pid}/publish").json()
    wait(pid)
    sb.files["dist/index.html"] = "<html>second</html>"
    second = client.post(f"/v1/builder/projects/{pid}/publish").json()
    wait(pid)
    rows = {r["id"]: r for r in client.get(f"/v1/builder/projects/{pid}/publishes").json()}
    assert rows[first["id"]]["can_rollback"] and rows[second["id"]]["kind"] == "publish"
    assert b"second" in deployed[-1][1]

    back = client.post(f"/v1/builder/projects/{pid}/publishes/{first['id']}/rollback")
    assert back.status_code == 202 and back.json()["kind"] == "rollback"
    wait(pid)
    alias, html = deployed[-1]
    assert b"first" in html and alias == deployed[0][0]                              # same address
    assert client.get(f"/v1/builder/projects/{pid}/publishes/{back.json()['id']}").json()["status"] == "live"

    off = client.post(f"/v1/builder/projects/{pid}/unpublish")
    assert off.status_code == 202 and off.json()["kind"] == "unpublish"
    wait(pid)
    assert b"is offline" in deployed[-1][1] and b"noindex" in deployed[-1][1]
    project = client.get(f"/v1/builder/projects/{pid}").json()
    assert project["published_at"] is None and project["published_url"]              # address kept
    offline = client.get(f"/v1/builder/projects/{pid}/publishes/{off.json()['id']}").json()
    assert offline["can_rollback"] is False
    r = client.post(f"/v1/builder/projects/{pid}/publishes/{off.json()['id']}/rollback")
    assert r.status_code == 409 and r.json()["error"]["code"] == "cannot_rollback"

    # Rolling back brings the site back online.
    client.post(f"/v1/builder/projects/{pid}/publishes/{second['id']}/rollback")
    wait(pid)
    assert b"second" in deployed[-1][1]
    assert client.get(f"/v1/builder/projects/{pid}").json()["published_at"] is not None


def test_pack_unpack_and_alias():
    site = publish_mod.BuiltSite({"index.html": b"<html>", "assets/a.js": b"1"})
    assert publish_mod.unpack(publish_mod.pack(site)).files == site.files
    assert publish_mod.alias_of("https://shop-abc123.vivid-apps.pages.dev") == "shop-abc123"
    assert publish_mod.alias_of(None) is None
    assert b"&lt;b&gt;" in publish_mod.offline_site("<b>").files["index.html"]
