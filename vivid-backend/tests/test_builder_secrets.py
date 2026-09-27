"""Secrets the owner adds: never shown back, public ones in the app's .env,
server ones on the backend, their names (not values) told to the agent,
which may not overwrite them."""
from app.builder import routing, secrets
from app.builder.loop import TurnRunner
from app.core.config import settings
from tests.builder_fakes import FakeSandbox
from tests.test_builder_loop import call, collect, install, models  # noqa: F401
from tests.test_builder_routes import client, fake_blob, fake_manager, maker  # noqa: F401

KEY = "Bv0eHnXbX1p0M1y9P7vB9w8ozR1Bq9mWvYbM7Tq7iJk="


def test_secret_routes(client, fake_manager, fake_blob, monkeypatch):  # noqa: F811
    monkeypatch.setattr(settings, "SECRETS_ENCRYPTION_KEY", KEY)
    pid = client.post("/v1/builder/projects", json={"name": "Shop", "skip_plan": True}).json()["id"]
    base = f"/v1/builder/projects/{pid}/secrets"
    assert client.put(f"{base}/stripe_key", json={"value": "x"}).status_code == 400          # not UPPER_SNAKE
    assert client.put(f"{base}/SUPABASE_URL", json={"value": "x"}).status_code == 400        # reserved
    r = client.put(f"{base}/STRIPE_SECRET_KEY", json={"value": "sk_live_abcdefgh1234"})
    assert r.status_code == 200 and r.json()["where"] == "stored" and r.json()["hint"] == "…1234"
    r = client.put(f"{base}/MAPBOX_TOKEN", json={"value": "pk.short", "public": True})
    assert r.json()["where"] == "app" and r.json()["hint"] is None                          # too short to hint
    listed = client.get(base).json()
    assert {(s["name"], s["public"]) for s in listed} == {("STRIPE_SECRET_KEY", False), ("MAPBOX_TOKEN", True)}
    assert "sk_live" not in str(listed)

    # The live sandbox's .env gets the public one only.
    fake_manager.sandbox.files[".env"] = ""
    assert client.get(f"/v1/builder/projects/{pid}/preview").status_code == 200              # a live sandbox
    client.put(f"{base}/MAPBOX_TOKEN", json={"value": "pk.short2", "public": True})
    env = fake_manager.sandbox.files.get(".env", "")
    assert "VITE_MAPBOX_TOKEN=pk.short2" in env and "STRIPE" not in env

    # Switching kind replaces it; deleting removes it from .env.
    client.put(f"{base}/MAPBOX_TOKEN", json={"value": "pk.server", "public": False})
    assert [s["public"] for s in client.get(base).json() if s["name"] == "MAPBOX_TOKEN"] == [False]
    assert "MAPBOX" not in fake_manager.sandbox.files.get(".env", "")
    assert client.delete(f"{base}/MAPBOX_TOKEN").status_code == 204
    assert client.delete(f"{base}/MAPBOX_TOKEN").status_code == 404
    client.as_user("u2")
    assert client.get(base).status_code == 404


async def test_the_agent_knows_the_names_and_cannot_overwrite(monkeypatch):
    monkeypatch.setattr(settings, "FALLBACK_MODEL", "vendor/primary")
    model = install(monkeypatch, [
        ("", [call("set_secret", {"key": "STRIPE_SECRET_KEY", "value": "sk_test"}, "s1")]),
        ("Done.", []),
    ])
    runner = TurnRunner(FakeSandbox({"src/App.tsx": "x", "package.json": "{}"}), routing.EDIT, [],
                        "wire stripe", user_secrets=["STRIPE_SECRET_KEY"])
    await collect(runner)
    system = model.requests[0]["messages"][0]["content"]
    assert "Server secrets the person added" in system and "STRIPE_SECRET_KEY" in system
    result = next(m for m in model.requests[1]["messages"] if m.get("tool_call_id") == "s1")
    assert result["content"].startswith("error: refused")
    assert "secrets" not in runner.memory["ledger"]


def test_prefixes_are_distinct():
    assert secrets.USER_SERVER != secrets.USER_PUBLIC and not secrets.USER_PUBLIC.startswith(secrets.USER_SERVER)
