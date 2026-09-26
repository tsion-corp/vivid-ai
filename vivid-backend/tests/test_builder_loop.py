"""The turn loop with the model scripted: answers end the turn, tool calls
are executed and fed back, the step cap and repeated typecheck failures hand
the turn to the fallback model once, and cancel stops it."""
import pytest

from app.builder import loop, routing, stream
from app.builder.loop import TurnRunner
from app.core.config import settings
from app.services.models_gateway import code_llm
from tests.builder_fakes import FakeSandbox


def call(name: str, args: dict, cid: str = "c1") -> dict:
    return {"id": cid, "name": name, "arguments": args, "error": None}


class ScriptedModel:
    """Each entry is (text, calls) for one model call; records what it saw."""

    def __init__(self, script: list[tuple[str, list[dict]]]) -> None:
        self.script = list(script)
        self.requests: list[dict] = []

    async def stream_chat(self, messages, tools, max_tokens=None, endpoint=None,
                          temperature=None):
        # A copy: the loop keeps appending to the same list.
        self.requests.append({"messages": [dict(m) for m in messages], "model": endpoint.model,
                              "tools": [t["function"]["name"] for t in tools]})
        if not self.script:
            text, calls = "Done.", []
        else:
            text, calls = self.script.pop(0)
        for ch in text:
            yield {"type": "token", "text": ch}
        if calls:
            yield {"type": "tool_calls", "calls": calls}
        yield {"type": "done", "finish_reason": "stop",
               "usage": {"prompt_tokens": 100, "completion_tokens": 10}}


@pytest.fixture(autouse=True)
def models(monkeypatch):
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "test-key")
    # Extensions are tested on their own; the cap tests want a hard cap.
    monkeypatch.setattr(settings, "BUILDER_EDIT_EXTENSION_STEPS", 0)
    monkeypatch.setattr(settings, "BUILDER_BUILD_EXTENSION_STEPS", 0)
    monkeypatch.setattr(settings, "BUILD_MODEL", "vendor/primary")
    monkeypatch.setattr(settings, "EDIT_MODEL", "vendor/primary")
    monkeypatch.setattr(settings, "FALLBACK_MODEL", "vendor/fallback")
    monkeypatch.setattr(settings, "BUILDER_MAX_STEPS", 3)
    monkeypatch.setattr(settings, "BUILDER_BUILD_MAX_STEPS", 3)
    monkeypatch.setattr(settings, "BUILDER_COMPLETION_ROUNDS", 0)
    monkeypatch.setattr(settings, "BUILDER_TYPECHECK_STRIKES", 2)
    monkeypatch.setattr(settings, "CODE_STREAM_RETRIES", 2)
    monkeypatch.setattr(loop, "_RETRY_BACKOFF", 0)


def install(monkeypatch, script) -> ScriptedModel:
    model = ScriptedModel(script)
    monkeypatch.setattr(code_llm, "stream_chat", model.stream_chat)
    return model


async def collect(runner: TurnRunner) -> tuple[list[dict], stream.PartsCollector]:
    parts, c = [], stream.PartsCollector()
    async for part in runner.run():
        parts.append(part)
        c.add(part)
    return parts, c


async def test_tool_call_then_answer(monkeypatch):
    model = install(monkeypatch, [
        ("Adding it.", [call("write_file", {"path": "src/A.tsx", "content": "export {}"})]),
        ("You now have a page.", []),
    ])
    sb = FakeSandbox({"src/App.tsx": "x", "src/main.tsx": "y", "package.json": "{}"})
    runner = TurnRunner(sb, routing.BUILD, [], "add a page", spec_md="# Spec\nA thing")
    parts, c = await collect(runner)

    assert parts[0]["type"] == "start" and parts[-1]["type"] == "finish"
    assert runner.result.reason == loop.ANSWERED
    assert runner.result.steps == 2 and runner.result.model == "vendor/primary"
    assert runner.result.touched == ["src/A.tsx"] and sb.files["src/A.tsx"] == "export {}"
    assert c.text() == "Adding it.\nYou now have a page."
    tool_parts = [p for p in c.parts if p["type"] == "tool-write_file"]
    assert tool_parts[0]["state"] == "output-available"
    assert "Typecheck: clean" in tool_parts[0]["output"]

    # The second request carried the tool result back to the model, and the
    # system prompt carried the spec and the file tree.
    second = model.requests[1]["messages"]
    assert second[0]["role"] == "system" and "# Spec" in second[0]["content"]
    assert "src/App.tsx" in second[0]["content"]
    assert second[-1]["role"] == "tool" and "Typecheck: clean" in second[-1]["content"]
    assert runner.result.tokens_in == 200 and runner.result.tokens_out == 20


async def test_step_cap_retries_once_on_fallback(monkeypatch):
    forever = [("", [call("list_files", {}, f"c{i}")]) for i in range(10)]
    model = install(monkeypatch, forever)
    sb = FakeSandbox({"src/App.tsx": "x"})
    runner = TurnRunner(sb, routing.EDIT, [], "loop")
    parts, c = await collect(runner)

    models_used = [r["model"] for r in model.requests]
    assert models_used[:3] == ["vendor/primary"] * 3
    assert models_used[3:] == ["vendor/fallback"] * 3
    assert runner.result.retried and runner.result.reason == loop.STEP_LIMIT
    assert runner.result.steps == 6
    notices = [p for p in c.parts if p["type"] == "data-notice"]
    assert notices[0]["data"] == {"text": loop.RETRY_NOTICE, "reason": loop.STEP_LIMIT}
    assert "ran out of steps" in c.text()


async def test_typecheck_strikes_retry_on_fallback(monkeypatch):
    broken = [("", [call("write_file", {"path": "src/A.tsx", "content": "bad"}, f"c{i}")])
              for i in range(3)]
    model = install(monkeypatch, broken + [("Fixed.", [])])
    sb = FakeSandbox({"src/App.tsx": "x"})
    sb.tsc_output = "src/A.tsx(1,1): error TS1005: ';' expected."
    runner = TurnRunner(sb, routing.EDIT, [], "break it")

    async def clean_after_fallback():
        # The fallback's second write passes, then it answers.
        async for part in runner.run():
            if part.get("type") == "data-notice":
                sb.tsc_output = ""
            yield part

    parts = [p async for p in clean_after_fallback()]
    # Two strikes on the primary, then the fallback writes once (clean now)
    # and answers.
    assert [r["model"] for r in model.requests] == (
        ["vendor/primary"] * 2 + ["vendor/fallback"] * 2)
    assert runner.result.reason == loop.ANSWERED and runner.result.retried
    assert runner.result.typecheck_failures == 2
    assert parts[-1]["type"] == "finish"


async def test_cancel_stops_between_steps(monkeypatch):
    install(monkeypatch, [("", [call("list_files", {})]), ("", [call("list_files", {})])])
    flag = {"cancel": False}
    sb = FakeSandbox({"src/App.tsx": "x"})
    runner = TurnRunner(sb, routing.EDIT, [], "go", cancelled=lambda: flag["cancel"])
    parts = []
    async for part in runner.run():
        parts.append(part)
        if part["type"] == "tool-output-available":
            flag["cancel"] = True
    assert runner.result.reason == loop.CANCELLED
    assert any(p["type"] == "abort" for p in parts)
    assert parts[-1]["type"] == "finish"


async def test_broken_stream_is_restarted(monkeypatch):
    """The first attempt dies mid-prose; the restart answers. The half
    reply is closed, a notice says why, and the conversation holds only
    the completed call."""
    model = ScriptedModel([("Hello again.", [])])
    calls = {"n": 0}

    async def flaky(messages, tools, max_tokens=None, endpoint=None, temperature=None):
        calls["n"] += 1
        if calls["n"] == 1:
            yield {"type": "token", "text": "Half a"}
            raise code_llm.CodeLLMUnavailable("stream interrupted")
        async for ev in model.stream_chat(messages, tools, max_tokens, endpoint, temperature):
            yield ev
    monkeypatch.setattr(code_llm, "stream_chat", flaky)
    runner = TurnRunner(FakeSandbox({"src/App.tsx": "x"}), routing.EDIT, [], "hi")
    parts, c = await collect(runner)
    assert runner.result.reason == loop.ANSWERED and not runner.result.retried
    assert runner.result.model == "vendor/primary" and calls["n"] == 2
    notices = [p for p in parts if p["type"] == "data-notice"]
    assert notices[0]["data"]["reason"] == "stream_retry"
    texts = [p["text"] for p in c.parts if p["type"] == "text"]
    assert texts == ["Half a", "Hello again."]
    assert len(model.requests[0]["messages"]) == 2      # system + user, no half reply


async def test_dead_primary_falls_back_to_the_other_vendor(monkeypatch):
    seen = []

    async def broken(messages, tools, max_tokens=None, endpoint=None, temperature=None):
        seen.append(endpoint.model)
        if endpoint.model == "vendor/primary":
            raise code_llm.CodeLLMUnavailable("upstream 502")
        yield {"type": "token", "text": "Fallback here."}
        yield {"type": "done", "finish_reason": "stop", "usage": None}
    monkeypatch.setattr(code_llm, "stream_chat", broken)
    runner = TurnRunner(FakeSandbox({"src/App.tsx": "x"}), routing.EDIT, [], "hi")
    parts, c = await collect(runner)
    assert seen == ["vendor/primary", "vendor/primary", "vendor/fallback"]
    assert runner.result.reason == loop.ANSWERED and runner.result.retried
    assert runner.result.model == "vendor/fallback"
    assert [p["type"] for p in parts if p["type"] == "error"] == ["error"]
    assert c.text().endswith("Fallback here.")


async def test_both_vendors_dead_is_an_error(monkeypatch):
    async def broken(*a, **k):
        raise code_llm.CodeLLMUnavailable("upstream 502")
        yield  # pragma: no cover
    monkeypatch.setattr(code_llm, "stream_chat", broken)
    runner = TurnRunner(FakeSandbox({"src/App.tsx": "x"}), routing.EDIT, [], "hi")
    parts, _ = await collect(runner)
    errors = [p for p in parts if p["type"] == "error"]
    assert len(errors) == 2 and "unavailable" in errors[0]["errorText"]
    assert runner.result.reason == loop.ERROR and runner.result.retried
    assert parts[-1]["type"] == "finish"


async def test_bad_tool_arguments_go_back_to_the_model(monkeypatch):
    model = install(monkeypatch, [
        ("", [{"id": "c1", "name": "read_file", "arguments": {},
               "error": "arguments were not valid JSON"}]),
        ("ok", []),
    ])
    runner = TurnRunner(FakeSandbox({"src/App.tsx": "x"}), routing.EDIT, [], "hi")
    parts, c = await collect(runner)
    assert [p for p in c.parts if p["type"] == "tool-read_file"][0]["state"] == "output-error"
    assert "valid JSON" in model.requests[1]["messages"][-1]["content"]


def test_stage_routing(monkeypatch):
    assert routing.stage_for(0) == routing.BUILD
    assert routing.stage_for(3) == routing.EDIT
    ep = routing.endpoint_for(routing.FALLBACK)
    assert ep.model == "vendor/fallback" and ep.provider == "openrouter" and ep.configured
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")
    assert not routing.endpoint_for(routing.BUILD).configured


def test_turn_registry():
    reg = loop.TurnRegistry()
    ev = reg.start("p1")
    assert ev is not None and reg.start("p1") is None and reg.running("p1")
    assert reg.started_at("p1") is not None and reg.get("p1") is ev
    assert reg.cancel("p1") and ev.cancel.is_set()
    reg.finish("p1")
    assert not reg.running("p1") and not reg.cancel("p1")


async def test_keepalive_runs_after_every_step(monkeypatch):
    install(monkeypatch, [("", [call("list_files", {})]), ("", [call("list_files", {}, "c2")]),
                          ("done", [])])
    ticks = []

    async def keepalive():
        ticks.append(1)
    runner = TurnRunner(FakeSandbox({"src/App.tsx": "x"}), routing.EDIT, [], "go",
                        keepalive=keepalive)
    await collect(runner)
    assert runner.result.reason == loop.ANSWERED and len(ticks) == 2   # two tool steps


async def test_raw_ssl_error_mid_stream_is_retried(monkeypatch):
    """A corrupted TLS record surfaces as ssl.SSLError from the stream
    reader; the adapter must turn it into a retryable failure."""
    import ssl
    from app.services.models_gateway import code_llm as adapter, provider

    class Broken:
        def stream(self, *a, **k):
            raise ssl.SSLError("bad record mac")
    monkeypatch.setattr(adapter.http, "client", lambda: Broken())
    monkeypatch.setattr(adapter, "_RETRY_DELAY", 0)
    ep = provider.openrouter_model("vendor/x")
    with pytest.raises(adapter.CodeLLMUnavailable):
        async for _ in adapter.stream_chat([{"role": "user", "content": "hi"}], [], endpoint=ep):
            pass


async def test_first_build_extends_once_while_clean_then_falls_back(monkeypatch):
    """A first build at its cap with a clean typecheck gets one extension
    with the same model; a second cap hands over as before."""
    monkeypatch.setattr(settings, "BUILDER_BUILD_MAX_STEPS", 2)
    monkeypatch.setattr(settings, "BUILDER_BUILD_EXTENSION_STEPS", 2)
    monkeypatch.setattr(settings, "BUILDER_COMPLETION_ROUNDS", 0)
    monkeypatch.setattr(settings, "BUILDER_CRITIQUE_ROUNDS", 0)
    forever = [("", [call("write_file", {"path": f"src/F{i}.tsx", "content": "export {}"}, f"c{i}")])
               for i in range(12)]
    model = install(monkeypatch, forever)
    sb = FakeSandbox({"src/App.tsx": "x"})
    runner = TurnRunner(sb, routing.BUILD, [], "build it all", spec_md="# Spec\nBig")
    parts, c = await collect(runner)
    models_used = [r["model"] for r in model.requests]
    assert models_used[:4] == ["vendor/primary"] * 4          # 2 + the extension of 2
    assert models_used[4:] == ["vendor/fallback"] * 4
    statuses = [p["data"]["text"] for p in parts if p["type"] == "data-status"]
    assert statuses.count("Still building, a few more steps") == 2   # once per attempt
    assert runner.result.reason == loop.STEP_LIMIT


async def test_edits_extend_once_too_but_not_after_a_failed_typecheck(monkeypatch):
    monkeypatch.setattr(settings, "BUILDER_MAX_STEPS", 2)
    monkeypatch.setattr(settings, "BUILDER_BUILD_MAX_STEPS", 2)
    monkeypatch.setattr(settings, "BUILDER_BUILD_EXTENSION_STEPS", 2)
    monkeypatch.setattr(settings, "BUILDER_EDIT_EXTENSION_STEPS", 1)
    monkeypatch.setattr(settings, "BUILDER_COMPLETION_ROUNDS", 0)
    monkeypatch.setattr(settings, "BUILDER_CRITIQUE_ROUNDS", 0)
    forever = [("", [call("write_file", {"path": f"src/F{i}.tsx", "content": "export {}"}, f"c{i}")])
               for i in range(8)]
    model = install(monkeypatch, forever)
    runner = TurnRunner(FakeSandbox({"src/App.tsx": "x"}), routing.EDIT, [], "tweak")
    await collect(runner)
    assert [r["model"] for r in model.requests][:4] == ["vendor/primary"] * 3 + ["vendor/fallback"]

    # A first build whose last typecheck failed gets no extension either.
    sb = FakeSandbox({"src/App.tsx": "x"})
    sb.tsc_output = "src/F0.tsx(1,1): error TS2304: Cannot find name 'x'."
    model = install(monkeypatch, forever)
    runner = TurnRunner(sb, routing.BUILD, [], "build", spec_md="# Spec\nBig")
    await collect(runner)
    assert [r["model"] for r in model.requests][:3] == ["vendor/primary"] * 2 + ["vendor/fallback"]


async def test_fallback_inherits_the_primary_conversation(monkeypatch):
    """The second model sees the first model's tool calls and results plus a
    handover note, so it continues instead of re-reading everything."""
    monkeypatch.setattr(settings, "BUILDER_MAX_STEPS", 2)
    monkeypatch.setattr(settings, "BUILDER_EDIT_EXTENSION_STEPS", 0)
    monkeypatch.setattr(settings, "BUILDER_CRITIQUE_ROUNDS", 0)
    model = install(monkeypatch, [
        ("Reading.", [call("read_file", {"path": "src/App.tsx"}, "c1")]),
        ("Writing.", [call("write_file", {"path": "src/B.tsx", "content": "export {}"}, "c2")]),
        ("Done now.", []),
    ])
    sb = FakeSandbox({"src/App.tsx": "x" * 2000})
    runner = TurnRunner(sb, routing.EDIT, [], "add B")
    await collect(runner)
    assert [r["model"] for r in model.requests] == ["vendor/primary"] * 2 + ["vendor/fallback"]
    handed = model.requests[2]["messages"]
    roles = [m["role"] for m in handed]
    assert roles[:2] == ["system", "user"] and "tool" in roles          # the primary's turn rides along
    assert handed[-1]["role"] == "user" and "ran out of steps" in handed[-1]["content"]
    tool_results = [m for m in handed if m["role"] == "tool"]
    assert any(m["content"].endswith("(shortened)") for m in tool_results)  # long reads trimmed
    assert runner.result.reason == loop.ANSWERED and runner.result.retried


async def test_first_build_that_writes_nothing_is_not_an_answer(monkeypatch):
    """Reads only, then "done": one push to build, then no_changes and the
    fallback with the conversation in hand; the usage part says ok=false."""
    monkeypatch.setattr(settings, "BUILDER_COMPLETION_ROUNDS", 0)
    monkeypatch.setattr(settings, "BUILDER_CRITIQUE_ROUNDS", 0)
    monkeypatch.setattr(settings, "BUILDER_BUILD_MAX_STEPS", 10)
    model = install(monkeypatch, [
        ("I'll start by reading.", [call("read_file", {"path": "src/App.tsx"}, "c1")]),
        ("", []),                                             # blank reply: nudged
        ("All done.", []),                                    # no files: nudged to build
        ("Really done.", []),                                 # still nothing: no_changes
        ("Fallback writes.", [call("write_file", {"path": "src/A.tsx", "content": "export {}"}, "c2")]),
        ("Built it.", []),
    ])
    sb = FakeSandbox({"src/App.tsx": "x"})
    runner = TurnRunner(sb, routing.BUILD, [], "build it", spec_md="# Spec\nA page")
    parts, c = await collect(runner)
    models_used = [r["model"] for r in model.requests]
    assert models_used[-2:] == ["vendor/fallback"] * 2 and models_used.count("vendor/primary") >= 3
    nudges = [m["content"] for r in model.requests for m in r["messages"]
              if m["role"] == "user" and m["content"] in (loop.BLANK_NUDGE, loop.BUILD_NUDGE)]
    assert loop.BUILD_NUDGE in nudges                     # a blank stream may be retried by ModelStep first
    assert runner.result.reason == loop.ANSWERED and runner.result.retried
    usage = [p for p in parts if p["type"] == "data-usage"][0]["data"]
    assert usage["ok"] is True and usage["failed_tools"] == []
    notice = [p for p in parts if p["type"] == "data-notice"][0]["data"]
    assert notice["reason"] == loop.NO_CHANGES


async def test_unparseable_tool_call_is_asked_for_again_and_named(monkeypatch):
    monkeypatch.setattr(settings, "BUILDER_CRITIQUE_ROUNDS", 0)
    bad = {"id": "c1", "name": "write_file", "arguments": {},
           "error": 'arguments were not valid JSON (x): {"path": "src/pages/Deal.tsx", "content": "…'}
    model = install(monkeypatch, [
        ("Writing.", [bad]),
        ("Again.", [call("write_file", {"path": "src/pages/Deal.tsx", "content": "export {}"}, "c2")]),
        ("Done.", []),
    ])
    sb = FakeSandbox({"src/App.tsx": "x"})
    runner = TurnRunner(sb, routing.EDIT, [], "add the deal dialog")
    parts, c = await collect(runner)
    second = model.requests[1]["messages"]
    assert second[-1]["role"] == "user" and "src/pages/Deal.tsx" in second[-1]["content"]
    assert "could not be parsed" in second[-1]["content"]
    assert sb.files["src/pages/Deal.tsx"] == "export {}"
    usage = [p for p in parts if p["type"] == "data-usage"][0]["data"]
    assert usage["failed_tools"] == ["write_file src/pages/Deal.tsx"] and usage["ok"] is True


async def test_turn_feed_replays_and_follows():
    feed = loop.TurnFeed("p1")
    await feed.push({"type": "start"})
    await feed.push({"type": "text-delta", "delta": "hi"})
    seen = []

    async def reader(start):
        async for part in feed.follow(start):
            seen.append((start, part.get("type") if isinstance(part, dict) else "DONE"))

    import asyncio
    t1 = asyncio.create_task(reader(0))
    t2 = asyncio.create_task(reader(2))         # a late reader misses nothing new
    await asyncio.sleep(0.01)
    await feed.push({"type": "finish"})
    await feed.push(loop.FEED_DONE)
    await feed.close()
    await asyncio.gather(t1, t2)
    assert seen.count((0, "start")) == 1 and (2, "start") not in seen
    assert (0, "finish") in seen and (2, "finish") in seen and (2, "DONE") in seen


async def test_a_turn_that_changed_files_ends_with_a_summary(monkeypatch):
    """However the turn ended, the thread closes with what was built, and
    that line is the version's label."""
    monkeypatch.setattr(settings, "BUILDER_CLOSING_SUMMARY", True)
    model = install(monkeypatch, [
        ("", [call("write_file", {"path": "src/A.tsx", "content": "export {}"})]),
        ("Checked the spacing on the menu cards.", []),
        ("Built a one-page bakery site with a menu and an order form.", []),
    ])
    sb = FakeSandbox({"src/App.tsx": "x", "src/main.tsx": "y", "package.json": "{}"})
    runner = TurnRunner(sb, routing.EDIT, [], "make a bakery site")
    parts, c = await collect(runner)
    assert c.text().rstrip().endswith("Built a one-page bakery site with a menu and an order form.")
    assert runner.result.summary == "Built a one-page bakery site with a menu and an order form."
    ask = model.requests[-1]
    assert ask["tools"] == []
    prompt_text = ask["messages"][0]["content"]
    assert "make a bakery site" in prompt_text and "src/A.tsx" in prompt_text
    assert "spacing on the menu cards" in prompt_text
