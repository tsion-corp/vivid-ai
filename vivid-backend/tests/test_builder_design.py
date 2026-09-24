"""The design skill loader and the critique round: which recipe a project
gets, what the prompt carries, and how a turn looks at its own page."""
import pytest

from app.builder import loop, routing, screenshots, skills, stream
from app.builder.loop import TurnRunner
from app.core.config import settings
from app.services.models_gateway import code_llm
from tests.builder_fakes import FakeSandbox
from tests.test_builder_loop import ScriptedModel, call, collect


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "k")
    monkeypatch.setattr(settings, "BUILD_MODEL", "vendor/primary")
    monkeypatch.setattr(settings, "EDIT_MODEL", "vendor/primary")
    monkeypatch.setattr(settings, "FALLBACK_MODEL", "vendor/fallback")
    monkeypatch.setattr(settings, "BUILDER_MAX_STEPS", 4)
    monkeypatch.setattr(settings, "BUILDER_BUILD_MAX_STEPS", 4)
    monkeypatch.setattr(settings, "BUILDER_COMPLETION_ROUNDS", 0)
    monkeypatch.setattr(settings, "BUILDER_COMPLETION_STEPS", 3)
    monkeypatch.setattr(settings, "BUILDER_CRITIQUE_ROUNDS", 1)
    monkeypatch.setattr(settings, "BUILDER_CRITIQUE_STEPS", 3)
    monkeypatch.setattr(settings, "CODE_STREAM_RETRIES", 1)
    skills.clear_cache()


def test_recipes_come_from_disk_and_the_block_carries_the_chosen_one():
    assert skills.available() == ["auth", "copy", "design", "fullstack", "maps", "mobile", "motion", "payments", "vividpay", "web3"]
    names = skills.recipe_names()
    assert len(names) >= 35 and names == sorted(names)
    for n in ("booking", "dashboard", "landing", "platform", "portfolio", "shop", "wallet", "restaurant",
              "event", "real-estate", "course", "job-board", "community", "magazine", "saas", "directory",
              "nonprofit", "fitness", "hotel", "travel", "clinic", "school", "marketplace", "rental",
              "crowdfunding", "membership", "agency", "invoicing", "inventory", "social", "support",
              "survey", "personal", "wedding", "newsletter", "chat-assistant", "nft-drop", "token-launch",
              "dao", "exchange", "ticketing"):
        assert n in names, n
    for r in skills.recipes():
        text = skills.design_block("x", "", recipe=r["name"])
        assert f"Recipe: {r['name']}" in text and "Minimums for a first build" in text, r["name"]
    menu = skills.recipe_menu()
    assert "- platform: platform (delivery, logistics" in menu and "- shop: shop" in menu
    block = skills.design_block("# Spec\nSell sneakers online", "", recipe="shop")
    assert block.startswith("## Design skill\n# Design method")
    assert "Recipe: shop" in block and "Recipe: booking" not in block
    assert "| forest |" in block and "| navy-lime |" in block and "Space Grotesk" in block
    assert "name: design" not in block                      # frontmatter stripped
    assert "Black Nigerian" in block and "ProductMockup" in block
    none = skills.design_block("# Spec\nSell sneakers online", "")
    assert "Recipe:" not in none                            # no guess from keywords
    assert "Recipe:" not in skills.design_block("x", "", recipe="not-a-recipe")


async def test_pick_recipe_asks_the_plan_model_once(monkeypatch):
    calls = []

    async def stream_chat(messages, tools, max_tokens=None, endpoint=None, temperature=None):
        calls.append(messages[0]["content"])
        yield {"type": "token", "text": " Platform.\n"}
        yield {"type": "done", "finish_reason": "stop", "usage": None}
    monkeypatch.setattr(code_llm, "stream_chat", stream_chat)
    monkeypatch.setattr(settings, "PLAN_MODEL", "vendor/planner")
    assert await skills.pick_recipe("a delivery app for Lagos") == "platform"
    assert "- platform:" in calls[0] and "a delivery app" in calls[0]
    assert await skills.pick_recipe("") is None

    async def broken(*a, **k):
        raise RuntimeError("down")
        yield
    monkeypatch.setattr(code_llm, "stream_chat", broken)
    assert await skills.pick_recipe("anything") is None


def test_skill_can_be_turned_off(monkeypatch):
    monkeypatch.setattr(settings, "BUILDER_DESIGN_SKILL", False)
    assert skills.design_block("shop", "") == ""
    monkeypatch.setattr(settings, "BUILDER_COPY_SKILL", False)
    assert skills.copy_block() == "" and skills.ui_block("shop", "") == ""


def test_fullstack_skill_only_with_a_backend(monkeypatch):
    assert skills.fullstack_block(False) == ""
    block = skills.fullstack_block(True)
    assert block.startswith("## App logic skill\n# App logic on Supabase")
    assert "handle_new_user" in block and "advance_order" in block       # patterns ride along
    assert "Definition of done" in block and "name: fullstack" not in block
    ui = skills.ui_block("# Spec\nSell sneakers online", "", payments="paystack", backend=True)
    order = [ui.index(h) for h in ("## Design skill", "## Copy skill",
                                   "## App logic skill", "## Payments skill")]
    assert order == sorted(order)
    assert "## App logic skill" not in skills.ui_block("shop", "", backend=False)
    monkeypatch.setattr(settings, "BUILDER_FULLSTACK_SKILL", False)
    assert skills.fullstack_block(True) == ""


def test_copy_skill_rides_with_the_design_skill():
    assert skills.available() == ["auth", "copy", "design", "fullstack", "maps", "mobile", "motion", "payments", "vividpay", "web3"]
    block = skills.ui_block("# Spec\nA salon booking app", "", recipe="booking")
    assert "## Design skill" in block and "## Copy skill" in block
    assert block.index("## Design skill") < block.index("## Copy skill")
    assert "Recipe: booking" in block
    copy = skills.copy_block()
    assert "Never \"Submit\"" in copy and "Em dashes" in copy and "₦12,000" in copy


def test_critique_message_carries_both_shots():
    shots = [screenshots.Shot("desktop", 1280, b"\xff\xd8x"), screenshots.Shot("mobile", 390, b"\xff\xd8y")]
    msg = screenshots.critique_message(shots)
    assert msg["role"] == "user" and msg["content"][0]["text"].startswith("Here is your page")
    assert [p["type"] for p in msg["content"]] == ["text", "text", "image_url", "text", "image_url"]
    assert msg["content"][2]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert shots[0].url is None                             # not stored


async def test_capture_reads_both_files_and_stores(monkeypatch):
    stored = {}

    async def put(key, data, content_type="application/gzip"):
        stored[key] = data
    monkeypatch.setattr(screenshots.blob, "put", put)
    monkeypatch.setattr(screenshots.blob, "presigned_url", lambda k, expires_in=3600: f"https://r2/{k}")
    monkeypatch.setattr(settings, "R2_PREFIX", "t/")
    sb = FakeSandbox({"src/App.tsx": "x"})
    sb.blobs[f"/tmp/vivid-shots-{sb.id}/desktop.jpg"] = b"D"
    sb.blobs[f"/tmp/vivid-shots-{sb.id}/mobile.jpg"] = b"M"
    shots = await screenshots.capture(sb, "p1", "m1-r1")
    assert [(s.name, s.data) for s in shots] == [("desktop", b"D"), ("mobile", b"M")]
    assert shots[0].url == "https://r2/t/projects/p1/shots/m1-r1-desktop.jpg"
    assert any("node scripts/screenshot.mjs http://localhost:5173" in c for c in sb.commands)

    from app.builder.sandbox.base import RunResult
    sb2 = FakeSandbox({"src/App.tsx": "x"})
    sb2.responses.append(("screenshot.mjs", RunResult(1, "", "chromium not found")))
    assert await screenshots.capture(sb2, "p1", "x") == []


async def test_turn_critiques_after_answering(monkeypatch):
    """Write, answer, then a critique round: the model sees two images,
    fixes, answers again. Steps for the fixes come from the extra budget."""
    model = ScriptedModel([
        ("Building.", [call("write_file", {"path": "src/App.tsx", "content": "v1"})]),
        ("Done, take a look.", []),
        ("Tightening the hero spacing.", [call("edit_file", {"path": "src/App.tsx", "old_string": "v1", "new_string": "v2"}, "c2")]),
        ("Adjusted the hero and the phone layout.", []),
    ])
    monkeypatch.setattr(code_llm, "stream_chat", model.stream_chat)

    async def fake_capture(sandbox, project_id, label, store=True):
        return [screenshots.Shot("desktop", 1280, b"D", key=None),
                screenshots.Shot("mobile", 390, b"M", key=None)]
    monkeypatch.setattr(screenshots, "capture", fake_capture)
    monkeypatch.setattr(settings, "BUILDER_BUILD_MAX_STEPS", 2)   # the critique needs its own budget

    sb = FakeSandbox({"src/App.tsx": "x"})
    runner = TurnRunner(sb, routing.BUILD, [], "a shop", spec_md="# Spec\nA sneaker shop",
                        project_id="p1", recipe="shop")
    parts, c = await collect(runner)
    assert runner.result.reason == loop.ANSWERED and runner.result.critique_rounds == 1
    assert runner.result.steps == 4 and sb.files["src/App.tsx"] == "v2"
    critique = [p for p in parts if p["type"] == "data-critique"]
    assert critique[0]["data"]["round"] == 1 and len(critique[0]["data"]["screenshots"]) == 2
    # The third request carried the screenshots as images after the answer.
    third = model.requests[2]["messages"]
    assert third[-1]["role"] == "user" and third[-1]["content"][2]["type"] == "image_url"
    assert "Design skill" in third[0]["content"] and "Recipe: shop" in third[0]["content"]
    assert "Copy skill" in third[0]["content"]
    assert c.text().endswith("Adjusted the hero and the phone layout.")


async def test_no_critique_without_ui_changes_or_when_off(monkeypatch):
    model = ScriptedModel([("Nothing to change.", [])])
    monkeypatch.setattr(code_llm, "stream_chat", model.stream_chat)
    captured = []

    async def fake_capture(*a, **k):
        captured.append(1)
        return []
    monkeypatch.setattr(screenshots, "capture", fake_capture)
    runner = TurnRunner(FakeSandbox({"src/App.tsx": "x"}), routing.EDIT, [], "hi", project_id="p1")
    await collect(runner)
    assert captured == [] and runner.result.critique_rounds == 0

    model = ScriptedModel([("", [call("write_file", {"path": "src/A.tsx", "content": "z"})]), ("ok", [])])
    monkeypatch.setattr(code_llm, "stream_chat", model.stream_chat)
    runner = TurnRunner(FakeSandbox({"src/App.tsx": "x"}), routing.EDIT, [], "hi", project_id="p1",
                        critique=False)
    await collect(runner)
    assert captured == [] and runner.result.reason == loop.ANSWERED


async def test_generate_image_tool_stores_and_returns_a_path(monkeypatch):
    """The image model's bytes become an asset (store + app file) and the
    model gets the public path back; the per-turn cap holds."""
    from app.builder import images as images_mod
    from app.builder import tools
    from app.services.models_gateway import media
    from tests.test_builder_assets import png

    calls = []

    async def fake_generate(prompt, aspect_ratio="1:1"):
        calls.append((prompt, aspect_ratio))
        return png(64, 64), "image/png"
    monkeypatch.setattr(media, "generate_image", fake_generate)

    added = []

    class FakeAsset:
        def __init__(self, name):
            self.name, self.meta = name, {"width": 64, "height": 64}

    async def fake_add(db, project_id, filename, mime, data):
        added.append((project_id, filename, mime, len(data)))
        return FakeAsset(filename)

    class FakeSession:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        def add(self, row): added.append(("usage", row.kind, row.unit))
        async def commit(self): pass
    monkeypatch.setattr(images_mod.assets, "add", fake_add)
    monkeypatch.setattr(images_mod, "async_session", lambda: FakeSession())
    monkeypatch.setattr(settings, "BUILDER_IMAGES_PER_TURN", 2)

    sb = FakeSandbox({"src/App.tsx": "x"})
    maker = images_mod.ImageMaker("p1", sb)
    out = await tools.execute("generate_image", {"prompt": "a red running sneaker, side view",
                                                 "name": "air-zoom-red", "aspect": "square"},
                              sb, None, maker)
    assert out.text.startswith("Image ready at /uploads/air-zoom-red.jpg (64x64")
    assert "1 more this turn" in out.text
    assert calls[0][1] == "1:1" and "Photorealistic" in calls[0][0]
    assert added[0][:3] == ("p1", "air-zoom-red.jpg", "image/jpeg")   # photos are re-encoded
    assert ("usage", "model", "images") in added
    assert sb.blobs["public/uploads/air-zoom-red.jpg"][:3] == b"\xff\xd8\xff"

    await tools.execute("generate_image", {"prompt": "a white court sneaker", "name": "court"}, sb, None, maker)
    out = await tools.execute("generate_image", {"prompt": "one more please", "name": "third"}, sb, None, maker)
    assert out.text.startswith("error: you have made 2 images this turn")
    out = await tools.execute("generate_image", {"prompt": "x", "name": "Bad Name"}, sb, None, maker)
    assert "describe the picture" in out.text or "lowercase slug" in out.text
    out = await tools.execute("generate_image", {"prompt": "a nice shoe photo", "name": "shoe"}, sb, None, None)
    assert out.text.startswith("error: image generation is not available")
    assert [s["function"]["name"] for s in tools.schemas_for(None, maker)][-1] == "generate_image"
    assert "generate_image" not in [s["function"]["name"] for s in tools.schemas_for(None)]


async def test_first_build_gets_a_completeness_review_before_the_critique(monkeypatch):
    monkeypatch.setattr(settings, "BUILDER_COMPLETION_ROUNDS", 1)
    monkeypatch.setattr(settings, "BUILDER_BUILD_MAX_STEPS", 2)
    model = ScriptedModel([
        ("", [call("write_file", {"path": "src/App.tsx", "content": "thin"})]),
        ("Done.", []),                                               # answer -> completion review
        ("Adding the missing pages.", [call("write_file", {"path": "src/pages/Shop.tsx", "content": "x"}, "c2")]),
        ("Complete now.", []),                                       # answer -> visual critique
        ("Looks right on both.", []),
    ])
    monkeypatch.setattr(code_llm, "stream_chat", model.stream_chat)

    async def fake_capture(sandbox, project_id, label, store=True):
        return [screenshots.Shot("desktop", 1280, b"D"), screenshots.Shot("mobile", 390, b"M")]
    monkeypatch.setattr(screenshots, "capture", fake_capture)

    sb = FakeSandbox({"src/App.tsx": "x"})
    runner = TurnRunner(sb, routing.BUILD, [], "build", spec_md="# Spec\nA shop", project_id="p1")
    parts, c = await collect(runner)
    assert runner.result.reason == loop.ANSWERED
    assert runner.result.completion_rounds == 1 and runner.result.critique_rounds == 1
    kinds = [p["type"] for p in parts if p["type"].startswith("data-")]
    assert kinds.index("data-review") < kinds.index("data-critique")
    review_msg = model.requests[2]["messages"][-1]
    assert review_msg["role"] == "user" and "review the app against the spec" in review_msg["content"]
    assert "sixteen" not in review_msg["content"] and "at least eight" in review_msg["content"]
    assert "src/pages/Shop.tsx" in sb.files
    # The static prompt now asks for completeness, and edits stay minimal.
    assert "A first build is not done until the whole spec exists" in model.requests[0]["messages"][0]["content"]

    # Edit turns get no completeness review.
    model = ScriptedModel([("", [call("write_file", {"path": "src/A.tsx", "content": "z"})]), ("ok", [])])
    monkeypatch.setattr(code_llm, "stream_chat", model.stream_chat)
    runner = TurnRunner(FakeSandbox({"src/App.tsx": "x"}), routing.EDIT, [], "tweak", project_id="p1", critique=False)
    await collect(runner)
    assert runner.result.completion_rounds == 0 and runner.result.steps == 2


async def test_capture_reads_the_page_report_and_broken_pages_lead_the_brief(monkeypatch):
    import json as _json
    monkeypatch.setattr(screenshots.blob, "put", _noop_put)
    sb = FakeSandbox({"src/App.tsx": "x"})
    d = f"/tmp/vivid-shots-{sb.id}"
    sb.blobs[f"{d}/desktop.jpg"] = b"D"
    sb.blobs[f"{d}/mobile.jpg"] = b"M"
    sb.blobs[f"{d}/report.json"] = _json.dumps({
        "rendered": {"desktop": False, "mobile": True}, "overlay": None,
        "errors": ["[desktop] Uncaught TypeError: x is not a function"]}).encode()
    shots = await screenshots.capture(sb, "p1", "m1", store=False)
    rep = screenshots.last_report
    assert rep is not None and rep.broken
    assert "rendered NOTHING at desktop" in rep.summary()
    msg = screenshots.critique_message(shots, rep)
    assert msg["content"][0]["text"].startswith("Before any design critique: the page is BROKEN")
    assert "Uncaught TypeError" in msg["content"][0]["text"]

    sb.blobs[f"{d}/report.json"] = _json.dumps({"rendered": {"desktop": True, "mobile": True},
                                                "overlay": None, "errors": []}).encode()
    await screenshots.capture(sb, "p1", "m2", store=False)
    assert not screenshots.last_report.broken
    assert screenshots.critique_message(shots, screenshots.last_report)["content"][0]["text"].startswith("Here is your page")


async def _noop_put(key, data, content_type="application/gzip"):
    return None


def test_payments_skill_only_when_enabled():
    assert skills.payments_block(None) == "" and skills.payments_block("none") == ""
    block = skills.ui_block("shop", "", payments="paystack")
    assert "## Payments skill" in block and "kobo" in block and "x-paystack-signature" in block
    assert "## Payments skill" not in skills.ui_block("shop", "")


async def test_generate_image_kinds(monkeypatch):
    from app.builder import images as images_mod
    from app.services.models_gateway import media
    from tests.test_builder_assets import png
    prompts = []

    async def fake_generate(prompt, aspect_ratio="1:1"):
        prompts.append((prompt, aspect_ratio))
        return png(8, 8), "image/png"
    monkeypatch.setattr(media, "generate_image", fake_generate)

    class FakeAsset:
        def __init__(self, name): self.name, self.meta = name, None
    async def fake_add(db, project_id, filename, mime, data): return FakeAsset(filename)
    class FakeSession:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        def add(self, row): pass
        async def commit(self): pass
    monkeypatch.setattr(images_mod.assets, "add", fake_add)
    monkeypatch.setattr(images_mod, "async_session", lambda: FakeSession())

    maker = images_mod.ImageMaker("p1", FakeSandbox({"src/App.tsx": "x"}), limit=5)
    await maker.make("a lightning bolt in a circle", "mark", aspect="wide", kind="logo")
    await maker.make("three sneakers on a dark table", "hero", aspect="wide", kind="lifestyle")
    await maker.make("a white sneaker", "shoe", aspect="square")
    assert prompts[0][1] == "1:1" and "no text" in prompts[0][0] and "app-icon style logo" in prompts[0][0]
    assert prompts[1][1] == "16:9" and "premium brand campaign" in prompts[1][0]
    assert "product photography" in prompts[2][0]


async def test_intent_reply_is_nudged_and_fallback_keeps_first_build_rules(monkeypatch):
    """"Let me build the pages." with no tool call is not an answer: the
    model is told to go on (twice at most). And when the primary strikes
    out, the fallback attempt still gets the first-build review."""
    monkeypatch.setattr(settings, "BUILDER_COMPLETION_ROUNDS", 1)
    monkeypatch.setattr(settings, "BUILDER_BUILD_MAX_STEPS", 6)
    monkeypatch.setattr(settings, "BUILDER_TYPECHECK_STRIKES", 1)
    model = ScriptedModel([
        ("", [call("write_file", {"path": "src/App.tsx", "content": "bad"})]),   # primary: strike -> fallback
        ("Good, the scaffolding is in place. Let me check the UI primitives, then build the pages.", []),
        ("", [call("write_file", {"path": "src/pages/Shop.tsx", "content": "ok"}, "c2")]),
        ("Done.", []),                                                          # -> completeness review
        ("All pages present.", []),
    ])
    monkeypatch.setattr(code_llm, "stream_chat", model.stream_chat)
    sb = FakeSandbox({"src/App.tsx": "x"})
    sb.tsc_output = "src/App.tsx(1,1): error TS1005: bad"
    runner = TurnRunner(sb, routing.BUILD, [], "build", spec_md="# Spec", project_id="p1", critique=False)

    async def clean_after_fallback():
        async for part in runner.run():
            if part.get("type") == "data-notice" and part["data"]["reason"] == "typecheck_strikes":
                sb.tsc_output = ""
            yield part
    parts = [p async for p in clean_after_fallback()]
    models_used = [r["model"] for r in model.requests]
    assert models_used[0] == "vendor/primary" and set(models_used[1:]) == {"vendor/fallback"}
    nudge = model.requests[2]["messages"][-1]
    assert nudge["role"] == "user" and nudge["content"].startswith("Go on and do it now")
    assert "src/pages/Shop.tsx" in sb.files
    assert runner.result.completion_rounds == 1 and runner.result.reason == loop.ANSWERED
    assert any(p["type"] == "data-review" for p in parts)


def test_intent_detector():
    from app.builder.loop import _announces_more_work as f
    assert f("The scaffolding is in place. Let me check the UI primitives, then build the pages.")
    assert f("Now I'll wire the cart and the checkout.")
    assert f("Next, I am going to add the admin page")
    assert not f("You now have a shop with twelve pairs, a cart and an admin page.")
    assert not f("The delete button works again.")
    assert not f("")


async def test_one_typecheck_per_step_and_small_edits_skip_the_critique(monkeypatch):
    """Three writes in one step: one tsc, its report on the last write's
    output. A one-file edit gets no screenshot pass; an edit about looks or
    a three-file edit does. Status parts name the phase."""
    monkeypatch.setattr(settings, "BUILDER_CRITIQUE_MIN_FILES", 3)
    captured = []

    async def fake_capture(sandbox, project_id, label, store=True):
        captured.append(label)
        return [screenshots.Shot("desktop", 1280, b"D"), screenshots.Shot("mobile", 390, b"M")]
    monkeypatch.setattr(screenshots, "capture", fake_capture)

    model = ScriptedModel([
        ("", [call("write_file", {"path": "src/a.ts", "content": "a"}, "c1"),
              call("write_file", {"path": "src/b.ts", "content": "b"}, "c2"),
              call("read_file", {"path": "src/App.tsx"}, "c3")]),
        ("Done.", []),
    ])
    monkeypatch.setattr(code_llm, "stream_chat", model.stream_chat)
    sb = FakeSandbox({"src/App.tsx": "x"})
    runner = TurnRunner(sb, routing.EDIT, [], "rename two helpers", project_id="p1")
    parts, c = await collect(runner)
    tsc_runs = [cmd for cmd in sb.commands if "tsc --noEmit" in cmd]
    assert len(tsc_runs) == 1
    outs = {p["toolCallId"]: p["output"] for p in parts if p["type"] == "tool-output-available"}
    assert outs["c1"] == "Wrote src/a.ts (1 chars)." and "Typecheck: clean" in outs["c2"]
    assert outs["c3"] == "x"
    statuses = [p["data"]["text"] for p in parts if p["type"] == "data-status"]
    assert statuses[:2] == ["Writing the app", "Reading the project"]
    assert captured == [] and runner.result.critique_rounds == 0   # two files, not about looks

    model = ScriptedModel([("", [call("edit_file", {"path": "src/App.tsx", "old_string": "x", "new_string": "y"})]),
                           ("Done.", []), ("Looks fine.", [])])
    monkeypatch.setattr(code_llm, "stream_chat", model.stream_chat)
    runner = TurnRunner(FakeSandbox({"src/App.tsx": "x"}), routing.EDIT, [], "make the hero colour warmer", project_id="p1")
    parts, _ = await collect(runner)
    assert runner.result.critique_rounds == 1 and len(captured) == 1
    assert "Looking at the page on desktop and phone" in [p["data"]["text"] for p in parts if p["type"] == "data-status"]

    model = ScriptedModel([("", [call("write_file", {"path": f"src/{i}.ts", "content": "z"}, f"c{i}") for i in range(3)]),
                           ("Done.", []), ("Fine.", [])])
    monkeypatch.setattr(code_llm, "stream_chat", model.stream_chat)
    runner = TurnRunner(FakeSandbox({"src/App.tsx": "x"}), routing.EDIT, [], "refactor the helpers", project_id="p1")
    await collect(runner)
    assert runner.result.critique_rounds == 1 and len(captured) == 2


async def test_typecheck_failure_in_a_step_counts_once(monkeypatch):
    monkeypatch.setattr(settings, "BUILDER_TYPECHECK_STRIKES", 1)
    monkeypatch.setattr(settings, "BUILDER_MAX_STEPS", 3)
    model = ScriptedModel([("", [call("write_file", {"path": "src/a.ts", "content": "a"}, "c1"),
                                 call("write_file", {"path": "src/b.ts", "content": "b"}, "c2")]),
                           ("ok", [])])
    monkeypatch.setattr(code_llm, "stream_chat", model.stream_chat)
    sb = FakeSandbox({"src/App.tsx": "x"})
    sb.tsc_output = "src/a.ts(1,1): error TS1005: bad"
    runner = TurnRunner(sb, routing.EDIT, [], "go", project_id="p1", critique=False)
    parts, _ = await collect(runner)
    assert runner.result.typecheck_failures == 1
    assert runner.result.reason in (loop.TYPECHECK_STRIKES, loop.ANSWERED)


async def test_images_asked_in_one_step_are_made_together(monkeypatch):
    """Three pictures in one step take one picture's time, and the cap is
    honoured even though the calls run concurrently."""
    import asyncio
    import time
    from app.builder import images as images_mod
    from app.services.models_gateway import media
    from tests.test_builder_assets import png

    async def fake_generate(prompt, aspect_ratio="1:1"):
        await asyncio.sleep(0.3)
        return png(8, 8), "image/png"
    monkeypatch.setattr(media, "generate_image", fake_generate)

    class FakeAsset:
        def __init__(self, name): self.name, self.meta = name, {"width": 8, "height": 8}

    async def fake_add(db, project_id, filename, mime, data): return FakeAsset(filename)

    class FakeSession:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        def add(self, row): pass
        async def commit(self): pass
    monkeypatch.setattr(images_mod.assets, "add", fake_add)
    monkeypatch.setattr(images_mod, "async_session", lambda: FakeSession())
    monkeypatch.setattr(settings, "BUILDER_CRITIQUE_ROUNDS", 0)

    sb = FakeSandbox({"src/App.tsx": "x"})
    maker = images_mod.ImageMaker("p1", sb, limit=2)
    model = ScriptedModel([
        ("Pictures first.", [call("generate_image", {"prompt": "a red sneaker on a grey surface", "name": "one"}, "c1"),
                             call("generate_image", {"prompt": "a white sneaker on a grey surface", "name": "two"}, "c2"),
                             call("generate_image", {"prompt": "a blue sneaker on a grey surface", "name": "three"}, "c3")]),
        ("Done.", []),
    ])
    monkeypatch.setattr(code_llm, "stream_chat", model.stream_chat)
    runner = TurnRunner(sb, routing.EDIT, [], "pictures", images=maker)
    t = time.monotonic()
    parts, c = await collect(runner)
    assert time.monotonic() - t < 0.8                          # concurrent, not 0.9 s serial
    outs = [p for p in c.parts if p["type"] == "tool-generate_image"]
    texts = [p.get("output") or p.get("errorText") or "" for p in outs]
    assert sum(t.startswith("Image ready") for t in texts) == 2, texts
    assert sum("images this turn" in t for t in texts) == 1   # the cap held under concurrency
    assert [p["data"]["text"] for p in parts if p["type"] == "data-status"][0] == "Making 3 pictures"


def test_compress_makes_photos_jpeg_and_keeps_logos_png():
    import io
    from PIL import Image
    from app.builder import images as images_mod
    from tests.test_builder_assets import png

    import os
    noise = Image.frombytes("RGB", (2048, 1536), os.urandom(2048 * 1536 * 3))
    big = io.BytesIO(); noise.save(big, format="PNG")
    data, mime = images_mod.compress(big.getvalue(), "image/png", "photo")
    assert mime == "image/jpeg" and len(data) < len(big.getvalue()) // 4
    assert Image.open(io.BytesIO(data)).size == (1280, 960)           # capped, ratio kept
    data, mime = images_mod.compress(png(64, 64), "image/png", "logo")
    assert mime == "image/png" and data[:4] == b"\x89PNG"
    assert images_mod.compress(b"not an image", "image/png", "photo") == (b"not an image", "image/png")


def test_maps_skill_only_with_a_key():
    assert skills.maps_block(None) == "" and skills.maps_block("none") == ""
    block = skills.maps_block("google")
    assert block.startswith("## Maps skill\n# Maps with Google") and "PlaceAutocomplete" in block
    ui = skills.ui_block("# Spec\nA delivery app", "", payments="paystack", backend=True,
                         recipe="platform", maps="google")
    assert ui.index("## Payments skill") < ui.index("## Maps skill")
    assert "## Maps skill" not in skills.ui_block("x", "")


def test_motion_skill_for_hero_pages_and_animation_requests(monkeypatch):
    assert skills.motion_block("platform").startswith("## Motion skill\n# Motion and polish")
    assert "ScrollTrigger" in skills.motion_block("landing") and "ShaderBackdrop" in skills.motion_block("shop")
    assert skills.motion_block("dashboard") == "" and skills.motion_block(None) == ""
    assert "## Motion skill" in skills.motion_block("dashboard", "add a parallax hero")
    ui = skills.ui_block("# Spec", "", recipe="platform")
    assert ui.index("## Copy skill") < ui.index("## Motion skill")
    monkeypatch.setattr(settings, "BUILDER_MOTION_SKILL", False)
    assert skills.motion_block("platform") == ""


async def test_logo_also_becomes_the_favicon(monkeypatch):
    import io
    from PIL import Image
    from app.builder import images as images_mod
    from app.services.models_gateway import media
    from tests.test_builder_assets import png

    async def fake_generate(prompt, aspect_ratio="1:1"):
        return png(512, 512), "image/png"
    monkeypatch.setattr(media, "generate_image", fake_generate)

    class FakeAsset:
        def __init__(self, name): self.name, self.meta = name, {"width": 512, "height": 512}

    async def fake_add(db, project_id, filename, mime, data): return FakeAsset(filename)

    class FakeSession:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        def add(self, row): pass
        async def commit(self): pass
    monkeypatch.setattr(images_mod.assets, "add", fake_add)
    monkeypatch.setattr(images_mod, "async_session", lambda: FakeSession())

    sb = FakeSandbox({"index.html": "<html><head><title>x</title></head><body></body></html>"})
    maker = images_mod.ImageMaker("p1", sb, limit=2)
    await maker.make("a bolt in a circle", "mark", kind="logo")
    icon = sb.blobs["public/favicon.png"]
    assert Image.open(io.BytesIO(icon)).size == (256, 256)
    assert 'rel="icon"' in sb.files["index.html"] and "apple-touch-icon" in sb.files["index.html"]
    assert images_mod.with_favicon_links(sb.files["index.html"]) == sb.files["index.html"]   # once
    assert sb.blobs["public/uploads/mark.png"][:4] == b"\x89PNG"                           # logos stay PNG


async def test_picture_tool_disappears_once_the_budget_is_spent(monkeypatch):
    from app.builder import images as images_mod
    from app.services.models_gateway import media
    from tests.test_builder_assets import png

    async def fake_generate(prompt, aspect_ratio="1:1"):
        return png(8, 8), "image/png"
    monkeypatch.setattr(media, "generate_image", fake_generate)

    class FakeAsset:
        def __init__(self, name): self.name, self.meta = name, {"width": 8, "height": 8}

    async def fake_add(db, project_id, filename, mime, data): return FakeAsset(filename)

    class FakeSession:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        def add(self, row): pass
        async def commit(self): pass
    monkeypatch.setattr(images_mod.assets, "add", fake_add)
    monkeypatch.setattr(images_mod, "async_session", lambda: FakeSession())
    monkeypatch.setattr(settings, "BUILDER_CRITIQUE_ROUNDS", 0)

    sb = FakeSandbox({"src/App.tsx": "x"})
    maker = images_mod.ImageMaker("p1", sb, limit=1)
    model = ScriptedModel([
        ("One picture.", [call("generate_image", {"prompt": "a red sneaker on grey", "name": "one"}, "c1")]),
        ("Now code.", [call("write_file", {"path": "src/A.tsx", "content": "export {}"}, "c2")]),
        ("Done.", []),
    ])
    monkeypatch.setattr(code_llm, "stream_chat", model.stream_chat)
    runner = TurnRunner(sb, routing.EDIT, [], "pictures then code", images=maker)
    await collect(runner)
    assert "generate_image" in model.requests[0]["tools"]
    assert "generate_image" not in model.requests[1]["tools"]        # budget spent
