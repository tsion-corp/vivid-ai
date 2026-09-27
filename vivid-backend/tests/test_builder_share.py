"""A public preview link: made by an editor, opened by anyone without
signing in, gone the moment it is revoked (sharing again makes a new one)."""
from app.api.routes.share import router as share_router
from tests.test_builder_routes import client, fake_blob, fake_manager, maker  # noqa: F401


def test_share_link(client, fake_manager, fake_blob):  # noqa: F811
    client.app.include_router(share_router, prefix="/v1")
    sb = fake_manager.sandbox
    sb.files["src/App.tsx"] = "x"
    pid = client.post("/v1/builder/projects", json={"name": "Bakery", "skip_plan": True}).json()["id"]
    assert client.get(f"/v1/builder/projects/{pid}/share").json() is None

    made = client.post(f"/v1/builder/projects/{pid}/share").json()
    assert made["url"].endswith(f"/s/{made['token']}") and len(made["token"]) >= 30
    assert client.post(f"/v1/builder/projects/{pid}/share").json()["token"] == made["token"]  # the same link

    # Nothing built yet: the page says so rather than showing a blank template.
    r = client.get(f"/v1/s/{made['token']}")
    assert r.status_code == 409 and r.json()["error"]["code"] == "nothing_built"
    assert client.post(f"/v1/builder/projects/{pid}/snapshots").status_code == 200
    opened = client.get(f"/v1/s/{made['token']}").json()
    assert opened["name"] == "Bakery" and opened["url"] == sb.preview_url() and opened["target"] == "web"
    assert client.post(f"/v1/s/{made['token']}/ping").status_code == 204

    # Someone with no part in the project cannot make or revoke its link.
    client.as_user("u2")
    assert client.post(f"/v1/builder/projects/{pid}/share").status_code == 404
    assert client.delete(f"/v1/builder/projects/{pid}/share").status_code == 404
    client.as_user("u1")

    assert client.delete(f"/v1/builder/projects/{pid}/share").status_code == 204
    assert client.get(f"/v1/s/{made['token']}").status_code == 404
    assert client.post(f"/v1/s/{made['token']}/ping").status_code == 404
    again = client.post(f"/v1/builder/projects/{pid}/share").json()
    assert again["token"] != made["token"]
    assert client.get("/v1/s/not-a-token").status_code == 404
