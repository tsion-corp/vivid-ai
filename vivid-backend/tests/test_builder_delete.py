"""Deleting what the person clicked in the preview: found in the source by
what the page showed, cut exactly with the project's own TypeScript, and
undone if the result would not compile."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from app.builder import jsx_remove
from app.builder.sandbox.base import RunResult
from tests.test_builder_routes import client, fake_blob, fake_manager, maker  # noqa: F401

SCRIPT = Path(jsx_remove.__file__).parent / "scripts" / "remove-jsx.mjs"
REPO = Path(__file__).resolve().parents[2]
TYPESCRIPT = next((p for p in (REPO / "sandbox-templates/vivid-web/node_modules",
                               REPO / "sandbox-templates/vivid-expo/node_modules")
                   if (p / "typescript/package.json").exists()), None)
needs_node = pytest.mark.skipif(not (shutil.which("node") and TYPESCRIPT),
                                reason="needs node and a template's node_modules/typescript")

APP = '''import { Hero } from "./components/Hero";
import Menu from "./components/Menu";
import { Truck } from "lucide-react";

const dishes = [{ name: "Jollof" }, { name: "Suya" }];

export default function App({ promo }: { promo: boolean }) {
  return (
    <main>
      <Hero />
      <Menu />
      <section id="about" className="py-16 px-4">
        <h2>Our story</h2>
        <p>Cooking since 1998 in Surulere &amp; Yaba.</p>
        <div className="card rounded-xl">
          <h3>Free delivery</h3>
          <p><Truck /> Within Lagos</p>
        </div>
        <div className="card rounded-xl">
          <h3>Open late</h3>
        </div>
      </section>
      {promo && (
        <section className="promo">
          <h2>Weekend deal</h2>
        </section>
      )}
      <ul>
        {dishes.map((d) => (
          <li key={d.name}>{d.name}<span>Order</span></li>
        ))}
      </ul>
      <img src="/uploads/hero.png" alt="" />
    </main>
  );
}
'''
HERO = '''export function Hero() {
  return (
    <section className="hero">
      <h1>Mama Titi&apos;s Kitchen</h1>
    </section>
  );
}
'''
MENU = '''export default function Menu() {
  return (
    <section>
      <h2>Menu</h2>
    </section>
  );
}
'''


@pytest.fixture
def project(tmp_path):
    (tmp_path / "src/components").mkdir(parents=True)
    (tmp_path / "package.json").write_text("{}")
    (tmp_path / "node_modules").symlink_to(TYPESCRIPT)
    (tmp_path / "src/App.tsx").write_text(APP)
    (tmp_path / "src/components/Hero.tsx").write_text(HERO)
    (tmp_path / "src/components/Menu.tsx").write_text(MENU)
    return tmp_path


def run(project, **target):
    req = project / "req.json"
    req.write_text(json.dumps(target))
    out = subprocess.run(["node", str(SCRIPT), str(req)], cwd=project, capture_output=True, text=True, timeout=60)
    return json.loads(out.stdout.strip().splitlines()[-1])


@needs_node
def test_an_element_is_cut_exactly_by_what_the_page_showed(project):
    card = run(project, tag="div", classes=["card"], texts=["Free delivery", "Within Lagos"])
    assert card["status"] == "applied"
    app = card["files"]["src/App.tsx"]
    assert "Free delivery" not in app and "Within Lagos" not in app and "Open late" in app
    assert '        <div className="card rounded-xl">\n          <h3>Open late</h3>' in app   # no gap left

    section = run(project, tag="section", id="about", texts=["Our story"])
    assert "Our story" not in section["files"]["src/App.tsx"] and "<Hero />" in section["files"]["src/App.tsx"]

    icon_line = run(project, tag="p", texts=["Within Lagos"])
    assert "<Truck /> Within Lagos" not in icon_line["files"]["src/App.tsx"]

    picture = run(project, tag="img", src="/uploads/hero.png")
    assert "/uploads/hero.png" not in picture["files"]["src/App.tsx"]

    promo = run(project, tag="section", classes=["promo"], texts=["Weekend deal"])
    app = promo["files"]["src/App.tsx"]
    assert "{promo &&" not in app and "Weekend deal" not in app and "      <ul>" in app


@needs_node
def test_a_section_that_is_a_whole_component_removes_where_it_is_used(project):
    hero = run(project, tag="section", classes=["hero"], texts=["Mama Titi's Kitchen"])
    assert hero["status"] == "applied" and hero["removed"]["component"] == "Hero"
    app = hero["files"]["src/App.tsx"]
    assert "<Hero />" not in app and "import { Hero }" not in app and app.startswith("import Menu")
    menu = run(project, tag="section", texts=["Menu"])
    assert "<Menu />" not in menu["files"]["src/App.tsx"] and "import Menu" not in menu["files"]["src/App.tsx"]


@needs_node
def test_what_cannot_be_cut_by_hand_says_why(project):
    assert run(project, tag="li", texts=["Order"])["status"] == "not_simple"       # one item of a mapped list
    assert run(project, tag="li", texts=["Jollof"])["status"] == "not_found"       # text from data
    assert run(project, tag="div", classes=["card"], texts=[])["status"] == "not_found"
    both = run(project, tag="div", classes=["card", "rounded-xl"], texts=["Open late"])
    assert both["status"] == "applied"
    (project / "src/components/Twin.tsx").write_text(
        'export function Twin() { return (<main><div className="card">Open late</div></main>); }\n')
    assert run(project, tag="div", texts=["Open late"])["status"] == "ambiguous"
    assert run(project, tag="main", texts=["Our story"])["status"] == "not_simple"  # the whole page


class Box:
    """Enough of a sandbox for remove(): files, and a typecheck that fails
    when any file says BROKEN (or always, for a project already broken)."""

    def __init__(self, answer, broken_before=False):
        self.files = {"src/App.tsx": "ok", "src/Other.tsx": "ok"}
        self.answer, self.broken_before = answer, broken_before

        class Target:
            typecheck_cmd = "npx tsc --noEmit"
        self.target = Target()

    async def read_file(self, path):
        if path not in self.files:
            raise FileNotFoundError(path)
        return self.files[path]

    async def write_file(self, path, content):
        self.files[path] = content

    async def run(self, cmd, timeout=60, env=None):
        if cmd.startswith("node "):
            return RunResult(0, json.dumps(self.answer) + "\n", "")
        if "tsc" in cmd:
            bad = sum("BROKEN" in v for k, v in self.files.items() if k.startswith("src/"))
            if self.broken_before:
                bad += 1
            return RunResult(2 if bad else 0, "error TS1005: x\n" * bad, "")
        return RunResult(0, "", "")


async def test_a_delete_that_would_break_the_code_is_undone():
    box = Box({"status": "applied", "files": {"src/App.tsx": "BROKEN"}, "removed": {}})
    out = await jsx_remove.remove(box, {"tag": "div"})
    assert out.status == "would_break" and box.files["src/App.tsx"] == "ok"

    box = Box({"status": "applied", "files": {"src/App.tsx": "fine"}, "removed": {"component": "Hero"}})
    out = await jsx_remove.remove(box, {"tag": "div"})
    assert out.status == "applied" and out.files == ["src/App.tsx"] and out.component == "Hero"
    assert box.files["src/App.tsx"] == "fine" and box.files[jsx_remove.IGNORE_PATH] == "*\n"

    # Already failing before: the delete adds no error, so it stands.
    box = Box({"status": "applied", "files": {"src/App.tsx": "fine"}, "removed": {}}, broken_before=True)
    assert (await jsx_remove.remove(box, {"tag": "div"})).status == "applied"
    assert box.files["src/App.tsx"] == "fine"

    box = Box({"status": "ambiguous", "reason": "2 elements match", "count": 2})
    out = await jsx_remove.remove(box, {"tag": "div"})
    assert out.status == "ambiguous" and out.count == 2 and box.files["src/App.tsx"] == "ok"


def test_delete_route(client, fake_manager, fake_blob, monkeypatch):  # noqa: F811
    from tests.test_builder_visual import _built
    pid = client.post("/v1/builder/projects", json={"name": "Empty", "skip_plan": True}).json()["id"]
    r = client.post(f"/v1/builder/projects/{pid}/edits/delete", json={"tag": "section", "texts": ["x"]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "nothing_to_edit"

    pid, sb = _built(client, fake_manager)
    seen = []

    async def find(sandbox, target):
        seen.append(target)
        return {"status": "applied", "files": {"src/Hero.tsx": "<img src=\"/images/hero.jpg\" />"},
                "removed": {"file": "src/Hero.tsx", "tag": "h1"}}
    monkeypatch.setattr(jsx_remove, "find", find)
    r = client.post(f"/v1/builder/projects/{pid}/edits/delete", json={
        "tag": "h1", "texts": ["  Fresh   bread "], "scope": "section", "label": "Fresh bread"})
    body = r.json()
    assert r.status_code == 200, body
    assert body["status"] == "applied" and body["files"] == ["src/Hero.tsx"]
    assert "Fresh bread" not in sb.files["src/Hero.tsx"]
    assert body["snapshot"]["summary"] == 'Deleted the "Fresh bread" section'
    assert seen[0]["texts"] == ["Fresh bread"] and "scope" not in seen[0]

    async def nothing(sandbox, target):
        return {"status": "not_simple", "reason": "one item of a list the page builds from data"}
    monkeypatch.setattr(jsx_remove, "find", nothing)
    r = client.post(f"/v1/builder/projects/{pid}/edits/delete", json={"tag": "li", "texts": ["Jollof"]})
    assert r.json()["status"] == "not_simple" and r.json()["snapshot"] is None
    assert client.post(f"/v1/builder/projects/{pid}/edits/delete", json={"tag": "<script>"}).status_code == 422
