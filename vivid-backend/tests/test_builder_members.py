"""Sharing a project: invites are single-use links; editors build and
hand-edit on the owner's plan, viewers only read; only the owner manages
people, integrations and the project itself."""
from app.api.routes.members import router as members_router
from app.core.config import settings
from app.services import mail
from tests.test_builder_routes import client, fake_blob, fake_manager, maker  # noqa: F401


def setup(client, monkeypatch):
    client.app.include_router(members_router, prefix="/v1")
    sent = []

    async def send(to, subject, text, html=None, reply_to=None):
        sent.append((to, subject, text))
        return True
    monkeypatch.setattr(mail, "send", send)
    return sent


def token_of(invite: dict) -> str:
    return invite["url"].rsplit("/", 1)[-1]


def test_invite_join_and_roles(client, fake_manager, fake_blob, monkeypatch):  # noqa: F811
    sent = setup(client, monkeypatch)
    fake_manager.sandbox.files["src/App.tsx"] = "x"
    pid = client.post("/v1/builder/projects", json={"name": "Bakery", "skip_plan": True}).json()["id"]
    assert client.post(f"/v1/builder/projects/{pid}/snapshots").status_code == 200

    assert client.post(f"/v1/builder/projects/{pid}/members", json={"email": "nope"}).status_code == 400
    invite = client.post(f"/v1/builder/projects/{pid}/members", json={"email": "Ada@Example.com", "role": "viewer"}).json()
    assert invite["email"] == "ada@example.com" and invite["emailed"] is True and invite["url"] in sent[0][2]
    token = token_of(invite)
    assert client.get(f"/v1/builder/invites/{token}").json() == {
        "project_name": "Bakery", "inviter": None, "role": "viewer", "status": "ok"}

    # A stranger sees nothing.
    client.as_user("u2")
    assert client.get(f"/v1/builder/projects/{pid}").status_code == 404
    assert client.get(f"/v1/builder/projects/{pid}/members").status_code == 404

    # Joining as a viewer: reads work, changes are refused with 403.
    joined = client.post(f"/v1/builder/invites/{token}/accept").json()
    assert joined["id"] == pid and joined["role"] == "viewer"
    assert client.post(f"/v1/builder/invites/{token}/accept").status_code == 410       # used once
    listed = client.get("/v1/builder/projects").json()
    assert [(p["id"], p["role"]) for p in listed] == [(pid, "viewer")]
    assert client.get(f"/v1/builder/projects/{pid}/messages").status_code == 200
    assert client.get(f"/v1/builder/projects/{pid}/snapshots").status_code == 200
    r = client.post(f"/v1/builder/projects/{pid}/edits", json={"edits": [{"old": "a", "new": "b"}]})
    assert r.status_code == 403
    assert client.post(f"/v1/builder/projects/{pid}/share").status_code == 403
    assert client.post(f"/v1/builder/projects/{pid}/members", json={"email": "x@y.co"}).status_code == 403

    # The owner makes them an editor: now they can change things, not own them.
    client.as_user("u1")
    people = client.get(f"/v1/builder/projects/{pid}/members").json()
    assert people["owner"]["user_id"] == "u1" and [m["user_id"] for m in people["members"]] == ["u2"]
    assert people["invites"] == []                                                    # accepted
    assert client.patch(f"/v1/builder/projects/{pid}/members/u2", json={"role": "editor"}).json()["role"] == "editor"
    client.as_user("u2")
    assert client.post(f"/v1/builder/projects/{pid}/share").status_code == 200
    assert client.post(f"/v1/builder/projects/{pid}/snapshots").status_code in (200, 409)
    assert client.delete(f"/v1/builder/projects/{pid}").status_code == 403
    assert client.patch(f"/v1/builder/projects/{pid}", json={"name": "Mine"}).status_code == 403
    assert client.post(f"/v1/builder/projects/{pid}/maps", json={"key": "k"}).status_code in (403, 422)
    assert client.get(f"/v1/builder/projects/{pid}/members").json()["invites"] == []   # owner only

    # Leaving: a member removes themselves.
    assert client.delete(f"/v1/builder/projects/{pid}/members/u2").status_code == 204
    assert client.get(f"/v1/builder/projects/{pid}").status_code == 404


def test_invites_expire_are_replaced_and_capped(client, fake_manager, fake_blob, monkeypatch):  # noqa: F811
    setup(client, monkeypatch)
    pid = client.post("/v1/builder/projects", json={"name": "Shop", "skip_plan": True}).json()["id"]
    first = client.post(f"/v1/builder/projects/{pid}/members", json={"email": "a@b.co"}).json()
    again = client.post(f"/v1/builder/projects/{pid}/members", json={"email": "a@b.co"}).json()
    assert again["id"] == first["id"] and token_of(again) != token_of(first)
    assert client.get(f"/v1/builder/invites/{token_of(first)}").status_code == 404     # replaced
    assert len(client.get(f"/v1/builder/projects/{pid}/members").json()["invites"]) == 1

    monkeypatch.setattr(settings, "BUILDER_INVITE_DAYS", 0)
    assert client.get(f"/v1/builder/invites/{token_of(again)}").json()["status"] == "expired"
    client.as_user("u2")
    assert client.post(f"/v1/builder/invites/{token_of(again)}/accept").status_code == 410
    client.as_user("u1")
    monkeypatch.setattr(settings, "BUILDER_INVITE_DAYS", 14)
    monkeypatch.setattr(settings, "BUILDER_MAX_MEMBERS", 1)
    r = client.post(f"/v1/builder/projects/{pid}/members", json={"email": "c@d.co"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "too_many_members"
    assert client.delete(f"/v1/builder/projects/{pid}/invites/{again['id']}").status_code == 204


def test_an_editors_turn_uses_the_owners_plan(client, fake_manager, fake_blob, monkeypatch):  # noqa: F811
    from app.api.routes import builder as builder_routes
    from app.services.plans import gate
    setup(client, monkeypatch)
    pid = client.post("/v1/builder/projects", json={"name": "Bakery", "skip_plan": True}).json()["id"]
    token = token_of(client.post(f"/v1/builder/projects/{pid}/members", json={"email": "e@f.co"}).json())
    client.as_user("u2")
    client.post(f"/v1/builder/invites/{token}/accept")

    asked = []
    real = gate.can_start_turn

    async def spy(db, user_id, project_id):
        asked.append(user_id)
        check = await real(db, user_id, project_id)
        check.ok = False                                     # the owner is out of credits
        return check
    monkeypatch.setattr(builder_routes.plan_gate, "can_start_turn", spy)
    r = client.post(f"/v1/builder/projects/{pid}/chat", json={"text": "make it blue"})
    assert asked == ["u1"]
    assert r.json()["error"]["code"] == "owner_limit"
