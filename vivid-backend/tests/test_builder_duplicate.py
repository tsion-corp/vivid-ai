"""Duplicating a project: a new project of the caller's from any version,
with the files and uploads but not the .env or the connections."""
import io
import tarfile

from app.builder import blob, duplicate
from tests.test_builder_routes import client, fake_blob, fake_manager, maker  # noqa: F401


def tgz(files: dict[str, str]) -> bytes:
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as t:
        for name, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
    return out.getvalue()


def names(data: bytes) -> set[str]:
    return set(tarfile.open(fileobj=io.BytesIO(data), mode="r:gz").getnames())


def test_env_is_left_out():
    data = tgz({"./.env": "VITE_SUPABASE_URL=x", "./src/App.tsx": "a", "./.env.local": "y",
                "./src/.env.ts": "fine"})
    assert names(duplicate.without_env(data)) == {"./src/App.tsx", "./src/.env.ts"}


def test_duplicate_route(client, fake_manager, fake_blob):  # noqa: F811
    sb = fake_manager.sandbox
    sb.files["src/App.tsx"] = "v1"
    pid = client.post("/v1/builder/projects", json={"name": "Bakery", "skip_plan": True}).json()["id"]
    assert client.post(f"/v1/builder/projects/{pid}/duplicate", json={}).status_code == 409   # nothing built
    assert client.post(f"/v1/builder/projects/{pid}/snapshots").status_code == 200
    sb.files["src/App.tsx"] = "v2"
    assert client.post(f"/v1/builder/projects/{pid}/snapshots").status_code == 200

    r = client.post(f"/v1/builder/projects/{pid}/duplicate", json={"seq": 1})
    assert r.status_code == 201, r.json()
    copy = r.json()["project"]
    assert copy["name"] == "Bakery (copy)" and copy["id"] != pid and copy["role"] == "owner"
    assert r.json()["reset"] == []
    versions = client.get(f"/v1/builder/projects/{copy['id']}/snapshots").json()
    assert [v["seq"] for v in versions] == [1] and "version 1" in versions[0]["summary"]
    assert client.post(f"/v1/builder/projects/{pid}/duplicate", json={"seq": 9}).status_code == 404
    # The Free plan's two apps are used: a third copy is a plan limit.
    r = client.post(f"/v1/builder/projects/{pid}/duplicate", json={})
    assert r.status_code == 402 and r.json()["error"]["code"] == "plan_limit"

    # Someone else cannot copy a project they have no part in.
    client.as_user("u2")
    assert client.post(f"/v1/builder/projects/{pid}/duplicate", json={}).status_code == 404
