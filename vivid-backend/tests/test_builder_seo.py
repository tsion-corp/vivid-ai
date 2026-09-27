"""SEO settings: read from the page, saved per project, written into the
published index.html (only the fields that are set)."""
import io
import tarfile

from app.builder import seo
from tests.test_builder_routes import client, fake_blob, fake_manager, maker  # noqa: F401

PAGE = """<!doctype html><html><head>
    <meta charset="utf-8">
    <title>Mama Titi's Kitchen</title>
    <meta name="description" content="Jollof &amp; suya in Yaba">
    <meta property="og:image" content="/images/hero.jpg">
    <link rel="icon" href="/favicon.png">
  </head><body></body></html>"""


def test_read_and_apply():
    assert seo.read(PAGE) == {"title": "Mama Titi's Kitchen", "description": "Jollof & suya in Yaba",
                              "image": "/images/hero.jpg"}
    assert seo.apply(PAGE.encode(), None) == PAGE.encode()

    out = seo.apply(PAGE.encode(), {"title": 'Titi "&" Co', "image": "/uploads/card.png", "noindex": True},
                    "https://titi-abc123.vivid-apps.pages.dev").decode()
    assert "<title>Titi &quot;&amp;&quot; Co</title>" in out and out.count("<title>") == 1
    assert 'content="Jollof &amp; suya in Yaba"' in out                    # untouched: not set
    assert out.count('property="og:image"') == 1
    assert 'content="https://titi-abc123.vivid-apps.pages.dev/uploads/card.png"' in out
    assert 'name="robots" content="noindex"' in out and '<link rel="icon" href="/favicon.png">' in out
    assert out.index("og:url") < out.index("</head>")

    icon = seo.apply(PAGE.encode(), {"favicon": "/uploads/logo.png", "description": "New"}).decode()
    assert '<link rel="icon" href="/uploads/logo.png">' in icon and "/favicon.png" not in icon
    assert icon.count('name="description"') == 1 and 'content="New"' in icon
    assert "og:url" not in icon                                            # no site URL given


def tgz(files):
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as t:
        for name, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
    return out.getvalue()


def test_seo_routes(client, fake_manager, fake_blob):  # noqa: F811
    pid = client.post("/v1/builder/projects", json={"name": "Titi", "skip_plan": True}).json()["id"]
    assert client.get(f"/v1/builder/projects/{pid}/seo").json()["page"] == {
        "title": None, "description": None, "image": None}
    assert client.post(f"/v1/builder/projects/{pid}/snapshots").status_code == 200
    # The fake sandbox's snapshot is not a tarball; put a real one in its place.
    key = next(k for k in fake_blob if "snapshots" in k)
    fake_blob[key] = tgz({"./index.html": PAGE})
    got = client.get(f"/v1/builder/projects/{pid}/seo").json()
    assert got["page"]["title"] == "Mama Titi's Kitchen" and got["title"] is None

    r = client.put(f"/v1/builder/projects/{pid}/seo", json={"title": "Titi's", "noindex": True})
    assert r.status_code == 200 and r.json()["title"] == "Titi's" and r.json()["noindex"] is True
    assert client.get(f"/v1/builder/projects/{pid}/seo").json()["title"] == "Titi's"
    assert client.put(f"/v1/builder/projects/{pid}/seo", json={"image": "javascript:alert(1)"}).status_code == 422
    assert client.put(f"/v1/builder/projects/{pid}/seo", json={"title": "x" * 71}).status_code == 422
    client.as_user("u2")
    assert client.put(f"/v1/builder/projects/{pid}/seo", json={"title": "Mine"}).status_code == 404
