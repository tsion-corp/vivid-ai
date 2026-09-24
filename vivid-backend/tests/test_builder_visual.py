"""Hand edits: replacing pictures, changing copy, and the preview's editor."""
import io

from PIL import Image

from app.builder import publish, visual
from tests.test_builder_routes import client, fake_blob, fake_manager, maker  # noqa: F401


def image(fmt: str, size=(8, 8), color=(200, 30, 30)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, fmt)
    return out.getvalue()


# ------------------------------------------------------------------ text
def test_text_found_however_the_source_spells_it():
    sources = {"src/Hero.tsx": "<h1>\n  Fresh bread,\n  baked daily\n</h1>\n<p>We&apos;re open</p>"}
    r = visual.apply_text_edit(sources, "Fresh bread, baked daily", "Sourdough every morning")
    assert r.status == "applied" and r.files == ["src/Hero.tsx"]
    assert "<h1>\n  Sourdough every morning\n</h1>" in sources["src/Hero.tsx"]
    r = visual.apply_text_edit(sources, "We're open", "Open <late> {daily}")
    assert r.status == "applied"
    assert "<p>Open &lt;late&gt; &#123;daily&#125;</p>" in sources["src/Hero.tsx"]


def test_text_in_a_string_is_escaped_for_its_quote():
    sources = {"src/data.ts": 'export const items = [{ title: "Fast delivery" }]',
               "src/copy.json": '{"cta": "Shop now"}'}
    visual.apply_text_edit(sources, "Fast delivery", 'Same-day "express"')
    assert 'title: "Same-day \\"express\\""' in sources["src/data.ts"]
    visual.apply_text_edit(sources, "Shop now", 'Buy "now"')
    assert sources["src/copy.json"] == '{"cta": "Buy \\"now\\""}'


def test_text_in_several_places_needs_all_and_missing_text_is_reported():
    sources = {"src/Nav.tsx": "<a>Pricing</a>", "src/Footer.tsx": "<a>Pricing</a>"}
    r = visual.apply_text_edit(sources, "Pricing", "Plans")
    assert r.status == "ambiguous" and r.count == 2 and sources["src/Nav.tsx"] == "<a>Pricing</a>"
    r = visual.apply_text_edit(sources, "Pricing", "Plans", every=True)
    assert r.status == "applied" and sources["src/Footer.tsx"] == "<a>Plans</a>"
    assert visual.apply_text_edit(sources, "Hello, Ada", "Hi").status == "not_found"


# ---------------------------------------------------------------- images
def test_upload_is_reencoded_into_the_files_format():
    fitted = visual.fit_to(image("PNG"), "src/assets/hero.jpg")
    assert Image.open(io.BytesIO(fitted)).format == "JPEG"
    jpeg = image("JPEG")
    assert visual.fit_to(jpeg, "public/a.jpeg") == jpeg
    assert visual.fit_to(image("PNG"), "public/logo.svg") is None


def test_non_images_are_refused():
    try:
        visual.upload_ext(b"<html>not a picture</html>")
    except visual.VisualError:
        pass
    else:
        raise AssertionError("accepted a non-image")


def test_src_resolves_to_the_file_vite_served():
    files = ["src/assets/hero.jpg", "public/images/team.png", "public/uploads/logo.png"]
    preview = "https://5173-abc.e2b.app"
    t = visual.resolve_src(f"{preview}/src/assets/hero.jpg?t=123", preview, files)
    assert t.path == "src/assets/hero.jpg" and t.refs == []
    t = visual.resolve_src(f"{preview}/images/team.png", preview, files)
    assert t.path == "public/images/team.png" and t.refs == ["/images/team.png"]
    t = visual.resolve_src(f"{preview}/uploads/logo.png", preview, files)
    assert t.path is None and t.refs == ["/uploads/logo.png"]
    t = visual.resolve_src("https://images.unsplash.com/photo-1?w=800", preview, files)
    assert t.path is None and t.refs == ["https://images.unsplash.com/photo-1?w=800"]


# ---------------------------------------------------------------- editor
def test_editor_is_placed_once_and_never_published():
    html = "<html><body><div id=root></div></body></html>"
    once = visual.with_editor(html)
    assert once.count(visual.EDITOR_START) == 1
    assert visual.with_editor(once) == once
    assert visual.strip_editor(once.encode()).decode() == html


# ---------------------------------------------------------------- routes
def _built(client, fake_manager):
    sb = fake_manager.sandbox
    sb.files["index.html"] = "<html><body></body></html>"
    sb.files["src/Hero.tsx"] = "<h1>Fresh bread</h1><img src=\"/images/hero.jpg\" />"
    sb.blobs["public/images/hero.jpg"] = image("JPEG")
    pid = client.post("/v1/builder/projects", json={"name": "Bakery", "skip_plan": True}).json()["id"]
    assert client.post(f"/v1/builder/projects/{pid}/snapshots").status_code == 200
    return pid, sb


def test_edit_routes(client, fake_manager, fake_blob):
    pid = client.post("/v1/builder/projects", json={"name": "Empty", "skip_plan": True}).json()["id"]
    r = client.post(f"/v1/builder/projects/{pid}/edits", json={"edits": [{"old": "a", "new": "b"}]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "nothing_to_edit"

    pid, sb = _built(client, fake_manager)
    assert visual.EDITOR_START in (client.get(f"/v1/builder/projects/{pid}/preview") and sb.files["index.html"])

    r = client.post(f"/v1/builder/projects/{pid}/edits", json={"edits": [
        {"old": "Fresh bread", "new": "Warm loaves"}, {"old": "Not there", "new": "x"}]})
    body = r.json()
    assert r.status_code == 200, body
    assert [e["status"] for e in body["results"]] == ["applied", "not_found"]
    assert "<h1>Warm loaves</h1>" in sb.files["src/Hero.tsx"]
    assert body["snapshot"]["summary"] == "Edited text: Warm loaves"


def test_replace_routes(client, fake_manager, fake_blob):
    pid, sb = _built(client, fake_manager)
    files = {"file": ("new.png", image("PNG"), "image/png")}
    r = client.put(f"/v1/builder/projects/{pid}/files/public/images/hero.jpg", files=files)
    assert r.status_code == 200, r.json()
    assert Image.open(io.BytesIO(sb.blobs["public/images/hero.jpg"])).format == "JPEG"
    r = client.put(f"/v1/builder/projects/{pid}/files/src/Hero.tsx", files=files)
    assert r.status_code == 400 and r.json()["error"]["code"] == "not_an_image"

    # A stock photo URL gets a file of its own and the source follows it.
    sb.files["src/Hero.tsx"] += '<img src="https://cdn.example.com/p.jpg" />'
    r = client.post(f"/v1/builder/projects/{pid}/images/replace",
                    data={"src": "https://cdn.example.com/p.jpg"}, files=files)
    body = r.json()
    assert r.status_code == 200, body
    assert body["path"].startswith("public/images/new-") and body["relinked"] == ["src/Hero.tsx"]
    assert "cdn.example.com" not in sb.files["src/Hero.tsx"]
    assert "/" + body["path"].removeprefix("public/") in sb.files["src/Hero.tsx"]


def test_publish_strips_the_editor():
    html = visual.with_editor("<html><body>app</body></html>").encode()
    assert visual.EDITOR_START.encode() not in visual.strip_editor(html)
    assert publish.visual is visual
