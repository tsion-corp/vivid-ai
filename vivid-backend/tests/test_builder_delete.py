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

SCRIPT = Path(jsx_remove.__file__).parent / "scripts" / "edit-jsx.mjs"
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
    assert run(project, tag="li", texts=["Order"])["status"] == "not_simple"       # no item says "Order"
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


CONTACT = '''export const HUB_ADDRESS = "14 Adeola Odeku Street, Victoria Island, Lagos";
export const SITE = { phone: "0803 123 4567" } as const;
'''
CARD_UI = '''export function Card({ className, ...p }: any) { return <div className={"rounded-xl " + (className ?? "")} {...p} />; }
export function CardTitle(p: any) { return <div {...p} />; }
'''
FEATURE = '''export function FeatureCard({ title, body }: { title: string; body: string }) {
  return (
    <div className="feature">
      <h3>{title}</h3>
      <p>{body}</p>
    </div>
  );
}
'''
PAGE = '''import { HUB_ADDRESS, SITE } from "../lib/contact";
import { FeatureCard } from "../components/FeatureCard";
import { Card, CardTitle } from "../components/ui/card";
import { Button } from "../components/ui/button";
import { Reveal } from "../components/Reveal";
export function Page() {
  return (
    <main>
      <Reveal delay={0.1}>
        <div className="rounded-2xl bg-card p-6">
          <h3>Dispatch desk</h3>
          <dl>
            <dt>Address</dt>
            <dd className="text-muted-foreground">{HUB_ADDRESS}</dd>
          </dl>
          <p>Call {SITE.phone}</p>
        </div>
      </Reveal>
      <div className="grid">
        <FeatureCard title="Same-day delivery" body="Order by noon." />
        <FeatureCard title="Live tracking" body="Watch your rider." />
        <Card className="p-6"><CardTitle>Cash on delivery</CardTitle></Card>
      </div>
      <Button asChild><a href="/track">Track a parcel</a></Button>
    </main>
  );
}
'''


@pytest.fixture
def site(project):
    (project / "src/lib").mkdir()
    (project / "src/pages").mkdir()
    (project / "src/components/ui").mkdir()
    (project / "src/lib/contact.ts").write_text(CONTACT)
    (project / "src/components/ui/card.tsx").write_text(CARD_UI)
    (project / "src/components/FeatureCard.tsx").write_text(FEATURE)
    (project / "src/pages/Page.tsx").write_text(PAGE)
    return project


@needs_node
def test_text_from_constants_props_and_components_is_found(site):
    """What generated sites do: contact details in a constants file, text
    passed to a card component as props, shadcn Cards, Button asChild."""
    dd = run(site, tag="dd", texts=["14 Adeola Odeku Street, Victoria Island, Lagos"])
    assert dd["status"] == "applied" and "{HUB_ADDRESS}" not in dd["files"]["src/pages/Page.tsx"]
    phone = run(site, tag="p", texts=["Call 0803 123 4567"])
    assert phone["status"] == "applied" and "SITE.phone" not in phone["files"]["src/pages/Page.tsx"]

    feature = run(site, tag="div", classes=["feature"], texts=["Live tracking", "Watch your rider."])
    page = feature["files"]["src/pages/Page.tsx"]
    assert feature["status"] == "applied" and 'title="Live tracking"' not in page and 'title="Same-day delivery"' in page
    # The <p> inside a FeatureCard is that component's own layout: not this use's to cut.
    assert run(site, tag="p", texts=["Watch your rider."])["status"] == "not_simple"

    card = run(site, tag="div", classes=["rounded-xl", "p-6"], texts=["Cash on delivery"])
    assert card["status"] == "applied" and "Cash on delivery" not in card["files"]["src/pages/Page.tsx"]


@needs_node
def test_a_wrapper_left_empty_goes_with_its_only_child(site):
    desk = run(site, tag="div", classes=["rounded-2xl", "bg-card", "p-6"],
               texts=["Dispatch desk", "Address", "14 Adeola Odeku Street, Victoria Island, Lagos"])
    page = desk["files"]["src/pages/Page.tsx"]
    assert desk["status"] == "applied" and "<Reveal" not in page and "Dispatch desk" not in page
    link = run(site, tag="a", texts=["Track a parcel"])
    assert link["status"] == "applied" and "<Button asChild>" not in link["files"]["src/pages/Page.tsx"]


SEED = '''import type { Shipment } from "./types";

export const shipments: Shipment[] = [
  {
    id: "shp-01",
    tracking_code: "LR-4K7T2M",
    recipient_name: "Tunde Bello",
    status: "in_transit",
  },
  {
    id: "shp-06",
    tracking_code: "LR-1H9ZK7",
    recipient_name: "Ruth Adeyemi",
    status: "booked",
  },
];
export const riders = [{ id: "rdr-01", name: "Musa Ali" }];
export const seedDatabase = { shipments, riders };
'''
TYPES = '''export type Shipment = { id: string; tracking_code: string; recipient_name: string; status: string };
'''
STORE = '''import { seedDatabase } from "./seed";
export function useStore() {
  const raw = localStorage.getItem("db");
  return { db: raw ? JSON.parse(raw) : seedDatabase };
}
'''
ADMIN = '''import { useStore } from "../lib/store";
import { Mockup } from "../components/Mockup";
import { Row } from "../components/Row";

export default function Admin() {
  const { db } = useStore();
  const rows = db.shipments.filter((s: any) => s.status !== "lost");
  const plans = [{ name: "Starter", perks: ["Same-day pickup", "SMS alerts"] }];
  return (
    <main>
      <Mockup shipment={db.shipments[0]} />
      <table>
        <tbody>
          {rows.slice(0, 8).map((s: any) => (
            <tr key={s.id} className="border-b">
              <td><a className="font-bold tracking-tight">{s.tracking_code}</a></td>
              <td>{s.recipient_name}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {db.riders.map((r: any) => <Row key={r.id} rider={r} />)}
      {plans.map((plan) => (
        <div key={plan.name} className="plan">
          <h3>{plan.name}</h3>
          <ul>{plan.perks.map((perk) => <li key={perk}>{perk}</li>)}</ul>
        </div>
      ))}
    </main>
  );
}
'''
MOCKUP = '''export function Mockup({ shipment }: { shipment: any }) {
  return (
    <div className="mockup">
      <p className="font-display text-xl">{shipment.tracking_code}</p>
      <span>Live</span>
    </div>
  );
}
'''
ROW = '''export function Row({ rider }: { rider: any }) {
  return (
    <div className="rider-row">
      <span className="font-semibold">{rider.name}</span>
    </div>
  );
}
'''


@pytest.fixture
def data_site(project):
    (project / "src/lib").mkdir()
    (project / "src/pages").mkdir()
    (project / "src/lib/seed.ts").write_text(SEED)
    (project / "src/lib/types.ts").write_text(TYPES)
    (project / "src/lib/store.ts").write_text(STORE)
    (project / "src/pages/Admin.tsx").write_text(ADMIN)
    (project / "src/components/Mockup.tsx").write_text(MOCKUP)
    (project / "src/components/Row.tsx").write_text(ROW)
    return project


@needs_node
def test_text_that_comes_from_data_is_found(data_site):
    """A tracking code from seed data: an item of a list goes from the data;
    a single record shown by a component goes from the JSX."""
    code = run(data_site, tag="a", classes=["font-bold", "tracking-tight"], texts=["LR-1H9ZK7"])
    assert code["status"] == "applied" and code["removed"]["data"] is True
    assert code["removed"]["file"] == "src/lib/seed.ts" and code["removed"]["values"] == ["LR-1H9ZK7"]
    seed = code["files"]["src/lib/seed.ts"]
    assert "LR-1H9ZK7" not in seed and "Ruth Adeyemi" not in seed and "LR-4K7T2M" in seed
    assert '    status: "in_transit",\n  },\n];' in seed               # the array still closes cleanly

    row = run(data_site, tag="tr", classes=["border-b"], texts=["LR-4K7T2M", "Tunde Bello"])
    assert row["status"] == "applied" and "LR-4K7T2M" not in row["files"]["src/lib/seed.ts"]
    assert "LR-1H9ZK7" in row["files"]["src/lib/seed.ts"]

    mockup = run(data_site, tag="p", classes=["font-display", "text-xl"], texts=["LR-4K7T2M"])
    assert mockup["status"] == "applied" and "data" not in mockup["removed"]
    assert "{shipment.tracking_code}" not in mockup["files"]["src/components/Mockup.tsx"]

    # A component rendered by a list is one item: the rider goes from the data.
    rider = run(data_site, tag="span", classes=["font-semibold"], texts=["Musa Ali"])
    assert rider["status"] == "applied" and "Musa Ali" not in rider["files"]["src/lib/seed.ts"]
    assert "export const riders = [];" in rider["files"]["src/lib/seed.ts"]

    # A string list inside a page: that string goes from its array.
    perk = run(data_site, tag="li", texts=["SMS alerts"])
    admin = perk["files"]["src/pages/Admin.tsx"]
    assert perk["status"] == "applied" and 'perks: ["Same-day pickup"]' in admin


@needs_node
def test_data_the_page_loads_while_running(data_site):
    # Not in any file: the element that shows data with the clicked classes
    # is found; one item of a loaded list cannot be removed by hand.
    shown = run(data_site, tag="p", classes=["font-display", "text-xl"], texts=["LR-XXXXXX"])
    assert shown["status"] == "applied" and "{shipment.tracking_code}" not in shown["files"]["src/components/Mockup.tsx"]
    listed = run(data_site, tag="a", classes=["font-bold", "tracking-tight"], texts=["LR-ZZZZZZ"])
    assert listed["status"] == "not_simple" and "loads" in listed["reason"]


async def test_an_item_removed_from_data_says_where_and_what_to_forget():
    box = Box({"status": "applied", "files": {"src/App.tsx": "ok2"},
               "removed": {"file": "src/lib/seed.ts", "data": True, "values": ["LR-1H9ZK7"]}})
    out = await jsx_remove.remove(box, {"tag": "a"})
    assert out.status == "applied" and out.data_file == "src/lib/seed.ts" and out.forget == ["LR-1H9ZK7"]
