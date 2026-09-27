"""Moving and duplicating what was clicked: the same finder as deleting,
then an exact swap or copy in the JSX, or in the data for a list item."""
from tests.test_builder_delete import data_site, needs_node, project, run  # noqa: F401
from tests.test_builder_routes import client, fake_blob, fake_manager, maker  # noqa: F401


@needs_node
def test_move_and_duplicate_in_the_page(project):  # noqa: F811
    card = dict(tag="div", classes=["card"], texts=["Free delivery", "Within Lagos"])
    down = run(project, op="move_down", **card)
    app = down["files"]["src/App.tsx"]
    assert down["status"] == "applied" and down["removed"]["op"] == "move_down"
    assert app.index("Open late") < app.index("Free delivery") and app.index("Free delivery") < app.index("{promo")
    up = run(project, op="move_up", **card)["files"]["src/App.tsx"]
    assert up.index("Free delivery") < up.index("Cooking since")                    # above the paragraph
    assert run(project, op="move_up", tag="h2", texts=["Our story"])["reason"] == "it is already at the top"
    top = run(project, op="move_up", tag="p", texts=["Cooking since 1998"])
    assert top["status"] == "applied" and top["files"]["src/App.tsx"].index("Cooking since") < \
        top["files"]["src/App.tsx"].index("Our story")

    twice = run(project, op="duplicate", **card)["files"]["src/App.tsx"]
    assert twice.count("Free delivery") == 2 and twice.count("Open late") == 1
    assert '        </div>\n        <div className="card rounded-xl">\n          <h3>Free delivery</h3>' in twice

    # A section that is a whole component moves where it is used.
    hero = run(project, op="move_down", tag="section", classes=["hero"], texts=["Mama Titi's Kitchen"])
    app = hero["files"]["src/App.tsx"]
    assert hero["removed"]["component"] == "Hero" and app.index("<Menu />") < app.index("<Hero />")
    assert run(project, op="move_up", tag="section", classes=["hero"], texts=["Mama Titi's Kitchen"])["status"] == "not_simple"
    # A conditional section moves as a whole.
    promo = run(project, op="move_up", tag="section", classes=["promo"], texts=["Weekend deal"])
    app = promo["files"]["src/App.tsx"]
    assert app.index("{promo &&") < app.index('<section id="about"')


@needs_node
def test_list_items_move_and_copy_in_the_data(data_site):  # noqa: F811
    code = dict(tag="a", classes=["font-bold", "tracking-tight"], texts=["LR-1H9ZK7"])
    up = run(data_site, op="move_up", **code)
    seed = up["files"]["src/lib/seed.ts"]
    assert up["removed"]["data"] and seed.index("LR-1H9ZK7") < seed.index("LR-4K7T2M")
    assert run(data_site, op="move_down", **code)["reason"] == "it is already the last item"

    copy = run(data_site, op="duplicate", **code)
    seed = copy["files"]["src/lib/seed.ts"]
    assert seed.count("Ruth Adeyemi") == 2 and '"shp-06-copy"' in seed and '"LR-1H9ZK7-copy"' in seed
    perk = run(data_site, op="duplicate", tag="li", texts=["SMS alerts"])["files"]["src/pages/Admin.tsx"]
    assert 'perks: ["Same-day pickup", "SMS alerts", "SMS alerts"]' in perk


def test_structure_route(client, fake_manager, fake_blob, monkeypatch):  # noqa: F811
    from app.builder import jsx_remove
    from tests.test_builder_visual import _built
    pid, sb = _built(client, fake_manager)
    seen = []

    async def find(sandbox, target):
        seen.append(target)
        return {"status": "applied", "files": {"src/Hero.tsx": "<h1>Fresh bread</h1>" * (len(seen) + 1)},
                "removed": {"file": "src/Hero.tsx", "tag": "h1", "op": target["op"]}}
    monkeypatch.setattr(jsx_remove, "find", find)
    r = client.post(f"/v1/builder/projects/{pid}/edits/structure",
                    json={"op": "duplicate", "tag": "h1", "texts": ["Fresh bread"], "label": "Fresh bread"})
    assert r.status_code == 200 and r.json()["snapshot"]["summary"] == 'Duplicated the "Fresh bread" element'
    assert seen[0]["op"] == "duplicate"
    r = client.post(f"/v1/builder/projects/{pid}/edits/structure",
                    json={"op": "move_up", "tag": "section", "texts": ["x"], "scope": "section", "label": "Menu"})
    assert r.json()["snapshot"]["summary"] == 'Moved up the "Menu" section'
    assert client.post(f"/v1/builder/projects/{pid}/edits/structure",
                       json={"op": "explode", "tag": "h1"}).status_code == 422
