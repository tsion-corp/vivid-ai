"""Decane sign-in for the apps the builder makes: provisioning, the key's
origins as sandboxes come and go and the site is published, teardown, and
how Decane's errors are answered. Decane is a fake server behind httpx."""
import asyncio
import json
import time

import httpx
import pytest
from cryptography.fernet import Fernet

from app.api.routes import builder as builder_routes
from app.builder import decane_connect, secrets
from app.builder import skills
from app.core.config import settings
from app.db.models import BuilderProject
from app.services.models_gateway import code_llm, http
from tests.test_builder_routes import client, fake_blob, fake_manager, maker  # noqa: F401

APP_ID = "2bf79738-9e91-429b-8156-865768cdd071"


class FakeDecane:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict | None]] = []
        self.clients: set[str] = set()
        self.keys = 0
        #: (method, path suffix) -> (status, body): canned failures.
        self.fail: dict[tuple[str, str], tuple[int, dict]] = {}
        self.down = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("down", request=request)
        assert request.headers["authorization"] == "Bearer dck_org_test"
        path = request.url.path.removeprefix("/connect/v1")
        body = json.loads(request.content) if request.content else None
        self.calls.append((request.method, path, body))
        for (method, suffix), (status, payload) in self.fail.items():
            if request.method == method and path.endswith(suffix):
                return httpx.Response(status, json=payload)
        if request.method == "POST" and path == "/clients":
            client = {"appId": APP_ID, "clientRef": body["external_ref"]}
            if body["external_ref"] in self.clients:
                return httpx.Response(200, json={"client": client, "alreadyExisted": True, "apiKey": None})
            self.clients.add(body["external_ref"])
            return httpx.Response(201, json={"client": client, "apiKey": self._key()})
        if request.method == "POST" and path.endswith("/keys"):
            return httpx.Response(201, json=self._key())
        return httpx.Response(200, json={"ok": True})

    def _key(self) -> dict:
        self.keys += 1
        return {"id": f"key-{self.keys}", "key": f"dck_live_{self.keys}", "keyPrefix": "dck_live_"}

    def of(self, method: str, suffix: str = "") -> list[dict | None]:
        return [b for m, p, b in self.calls if m == method and p.endswith(suffix)]


@pytest.fixture
def decane(monkeypatch):
    fake = FakeDecane()
    shared = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))
    monkeypatch.setattr(http, "client", lambda: shared)
    monkeypatch.setattr(settings, "DECANE_PARTNER_TOKEN", "dck_org_test")
    monkeypatch.setattr(settings, "SECRETS_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(builder_routes, "_auth_synced", {})
    return fake


def _secret(maker, pid, key):
    async def read():
        async with maker() as db:
            return await secrets.get_secret(db, pid, key)
    return asyncio.run(read())


def _project(client):
    return client.post("/v1/builder/projects", json={"name": "Bakery", "skip_plan": True}).json()["id"]


def test_not_configured_changes_nothing(client, monkeypatch, maker, fake_manager):
    monkeypatch.setattr(settings, "DECANE_PARTNER_TOKEN", "")
    monkeypatch.setattr(settings, "SECRETS_ENCRYPTION_KEY", Fernet.generate_key().decode())
    pid = _project(client)
    r = client.post(f"/v1/builder/projects/{pid}/auth")
    assert r.status_code == 503 and r.json()["error"]["code"] == "not_configured"
    assert client.get(f"/v1/builder/projects/{pid}").json()["auth_provider"] == "none"


def test_enable_provisions_stores_and_reaches_the_app(client, maker, fake_manager, decane, monkeypatch):
    pid = _project(client)
    r = client.post(f"/v1/builder/projects/{pid}/auth")
    body = r.json()
    assert r.status_code == 200, body
    assert body["auth_provider"] == "decane" and body["decane_app_id"] == APP_ID
    created = decane.of("POST", "/clients")[0]
    assert created == {"external_ref": pid, "name": "Bakery", "allowed_origins": ["fake"],
                       "callback_url": "https://fake/auth/callback"}
    assert _secret(maker, pid, "DECANE_CLIENT_API_KEY") == "dck_live_1"
    assert _secret(maker, pid, "DECANE_CLIENT_KEY_ID") == "key-1"
    assert _secret(maker, pid, "DECANE_CLIENT_REF") == pid
    env = fake_manager.sandbox.files[".env"]
    assert f"VITE_DECANE_APP_ID={APP_ID}\n" in env and "VITE_DECANE_API_KEY=dck_live_1\n" in env
    # Again: already on, nothing new minted.
    assert client.post(f"/v1/builder/projects/{pid}/auth").status_code == 200 and decane.keys == 1

    seen = []

    async def stream_chat(messages, tools, max_tokens=None, endpoint=None, temperature=None):
        seen.append(messages[0]["content"])
        yield {"type": "token", "text": "ok"}
        yield {"type": "done", "finish_reason": "stop", "usage": None}
    monkeypatch.setattr(code_llm, "stream_chat", stream_chat)
    client.post(f"/v1/builder/projects/{pid}/chat", json={"text": "add sign in"})
    assert "## Sign-in skill" in seen[-1] and "decane-connect-kit" in seen[-1]


def test_already_existing_client_gets_a_new_key(client, maker, fake_manager, decane):
    pid = _project(client)
    decane.clients.add(pid)                      # a retry after a timeout, or a re-enable
    r = client.post(f"/v1/builder/projects/{pid}/auth")
    assert r.status_code == 200, r.json()
    assert decane.of("POST", f"/clients/{pid}/keys")[0]["allowed_origins"] == ["fake"]
    assert _secret(maker, pid, "DECANE_CLIENT_API_KEY") == "dck_live_1"


def test_a_key_that_cannot_be_stored_is_revoked(client, maker, fake_manager, decane, monkeypatch):
    pid = _project(client)
    real = secrets.set_secret

    async def broken(db, project_id, key, value):
        if key == "DECANE_CLIENT_KEY_ID":
            raise RuntimeError("database went away")
        await real(db, project_id, key, value)
    monkeypatch.setattr(secrets, "set_secret", broken)
    r = client.post(f"/v1/builder/projects/{pid}/auth")
    assert r.status_code == 503
    assert [p for m, p, _ in decane.calls if m == "DELETE"] == [f"/clients/{pid}/keys/key-1"]
    assert client.get(f"/v1/builder/projects/{pid}").json()["auth_provider"] == "none"


@pytest.mark.parametrize("status,payload,code", [
    (401, {"error": {"code": "UNAUTHORIZED", "message": "revoked"}}, "not_configured"),
    (403, {"error": {"code": "QUOTA_EXCEEDED", "message": "Client limit reached."}}, "not_configured"),
    (400, {"error": {"code": "BAD_REQUEST", "message": "bad ref"}}, "bad_request"),
    (None, None, "upstream_error"),
])
def test_decane_errors_are_answered(client, fake_manager, decane, status, payload, code):
    pid = _project(client)
    if status is None:
        decane.down = True
    else:
        decane.fail[("POST", "/clients")] = (status, payload)
    r = client.post(f"/v1/builder/projects/{pid}/auth")
    assert r.json()["error"]["code"] == code
    assert r.status_code == {"not_configured": 503, "bad_request": 400, "upstream_error": 502}[code]
    if payload and payload["error"]["code"] == "QUOTA_EXCEEDED":
        assert "Client limit reached." in r.json()["error"]["message"]


def test_new_sandbox_and_publish_move_the_origins(client, maker, fake_manager, fake_blob, decane, monkeypatch):
    pid = _project(client)
    client.post(f"/v1/builder/projects/{pid}/auth")

    # A new sandbox on another host: the key gets it, keeping the previous one.
    fake_manager.sandbox.preview_url = lambda: "https://5173-sbx2.e2b.app"
    client.get(f"/v1/builder/projects/{pid}/preview")
    patched = decane.of("PATCH", f"/clients/{pid}/keys/key-1")
    assert patched[-1] == {"allowed_origins": ["5173-sbx2.e2b.app", "fake"],
                           "callback_url": "https://5173-sbx2.e2b.app/auth/callback"}
    client.get(f"/v1/builder/projects/{pid}/preview")
    assert len(decane.of("PATCH")) == 1              # once per sandbox, not per request

    # Publishing adds the published host and moves Google's callback to it.
    from app.builder import publish as publish_mod
    monkeypatch.setattr(settings, "CF_API_TOKEN", "t")
    monkeypatch.setattr(settings, "CF_ACCOUNT_ID", "acct")
    monkeypatch.setattr(settings, "CF_PAGES_PROJECT", "vivid-apps")

    class FakePages:
        async def deploy(self, site, alias, message):
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
    fake_manager.sandbox.files["src/Page.tsx"] = "export {}"
    fake_manager.sandbox.files["dist/index.html"] = "<html>"
    assert client.post(f"/v1/builder/projects/{pid}/snapshots").status_code == 200
    assert client.post(f"/v1/builder/projects/{pid}/publish").status_code == 202
    for _ in range(200):
        task = builder_routes._publishing.get(pid)
        if task is None or task.done():
            break
        time.sleep(0.05)
    host = f"{publish_mod.alias_for('Bakery', pid)}.vivid-apps.pages.dev"
    assert decane.of("PATCH")[-1] == {"allowed_origins": [host, "5173-sbx2.e2b.app", "fake"],
                                      "callback_url": f"https://{host}/auth/callback"}


def test_a_failed_origin_sync_does_not_fail_the_request(client, fake_manager, decane):
    pid = _project(client)
    client.post(f"/v1/builder/projects/{pid}/auth")
    decane.fail[("PATCH", "/keys/key-1")] = (500, {})
    fake_manager.sandbox.preview_url = lambda: "https://5173-sbx3.e2b.app"
    assert client.get(f"/v1/builder/projects/{pid}/preview").status_code == 200
    decane.fail.clear()
    client.get(f"/v1/builder/projects/{pid}/preview")    # retried, since it did not land
    assert len(decane.of("PATCH")) == 2


def test_disable_revokes_and_keeps_the_client(client, maker, fake_manager, decane):
    pid = _project(client)
    client.post(f"/v1/builder/projects/{pid}/auth")
    r = client.delete(f"/v1/builder/projects/{pid}/auth")
    assert r.json()["auth_provider"] == "none" and r.json()["decane_app_id"] == APP_ID
    assert [p for m, p, _ in decane.calls if m == "DELETE"] == [f"/clients/{pid}/keys/key-1"]
    assert _secret(maker, pid, "DECANE_CLIENT_API_KEY") is None
    # Back on: the same client, a new key.
    assert client.post(f"/v1/builder/projects/{pid}/auth").json()["auth_provider"] == "decane"
    assert decane.of("POST", f"/clients/{pid}/keys") and _secret(maker, pid, "DECANE_CLIENT_API_KEY") == "dck_live_2"


def test_deleting_the_project_deprovisions_even_when_decane_is_down(client, fake_manager, decane):
    pid = _project(client)
    client.post(f"/v1/builder/projects/{pid}/auth")
    assert client.delete(f"/v1/builder/projects/{pid}").status_code == 204
    assert (("DELETE", f"/clients/{pid}", None)) in decane.calls

    pid = _project(client)
    client.post(f"/v1/builder/projects/{pid}/auth")
    decane.down = True
    assert client.delete(f"/v1/builder/projects/{pid}").status_code == 204


def test_origins_and_skill():
    assert decane_connect.host_of("https://5173-abc.e2b.app:443/x") == "5173-abc.e2b.app"
    hosts, callback = decane_connect.origins_for(None, ["a", "b", "c"])
    assert hosts == ["a", "b"] and callback == "https://a/auth/callback"
    assert skills.auth_block(None) == "" and "useSocialAuth" in skills.auth_block("decane")
    assert BuilderProject.__table__.c.auth_provider.default.arg == "none"
