"""Memory between turns: a turn that stops unfinished hands its work to the
next, which continues instead of re-reading; what was done outside the files
(migrations, secrets, functions, packages) is remembered; reading in circles
is called out; tables this app did not create are not dropped."""
import json

import pytest

from app.builder import memory, routing, tools
from app.builder.loop import READ_NUDGE, TurnRunner
from app.core.config import settings
from tests.builder_fakes import FakeSandbox
from tests.test_builder_loop import call, collect, install, models  # noqa: F401

FILES = {"src/App.tsx": "export default function App() { return <main>Hi</main>; }",
         "src/main.tsx": "y", "package.json": "{}", "src/lib/store.tsx": "export const store = 1;"}


def texts(request: dict) -> str:
    return "\n".join(str(m.get("content") or "") for m in request["messages"])


async def test_an_unfinished_turn_is_continued_not_restarted(monkeypatch):
    monkeypatch.setattr(settings, "FALLBACK_MODEL", "vendor/primary")      # no retry: one attempt
    install(monkeypatch, [
        ("Reading.", [call("read_file", {"path": "src/lib/store.tsx"}, "a1")]),
        ("More.", [call("list_files", {}, "a2")]),
        ("And more.", [call("read_file", {"path": "src/App.tsx"}, "a3")]),
    ])
    sb = FakeSandbox(dict(FILES))
    first = TurnRunner(sb, routing.EDIT, [], "turn this into a full stack app")
    await collect(first)
    assert first.result.reason == "step_limit"
    left = first.memory["unfinished"]
    assert left["request"] == "turn this into a full stack app" and left["reason"] == "step_limit"
    assert any(m.get("content") == "export const store = 1;" for m in left["messages"])

    # "continue": the next turn sees that work, gets more steps, and a
    # re-read of an unchanged file is answered short.
    monkeypatch.setattr(settings, "BUILDER_CONTINUE_MAX_STEPS", 5)
    model = install(monkeypatch, [
        ("", [call("read_file", {"path": "src/lib/store.tsx"}, "b1")]),
        ("", [call("write_file", {"path": "src/lib/api.ts", "content": "export {}"}, "b2")]),
        ("The API is wired.", []),
    ])
    stored = json.loads(json.dumps(first.memory))                         # as the column keeps it
    second = TurnRunner(sb, routing.EDIT, [], "cnontinue", memory=stored)
    assert second.continuing
    await collect(second)
    seen = texts(model.requests[0])
    assert "stopped before it finished" in seen and "export const store = 1;" in seen
    assert "Carry on from exactly here" in seen
    reread = next(m for m in model.requests[1]["messages"] if m.get("tool_call_id") == "b1")
    assert reread["content"] == memory.UNCHANGED
    assert second.result.reason == "answered" and second.memory["unfinished"] is None


async def test_a_new_request_keeps_the_unfinished_work_for_later(monkeypatch):
    left = memory.unfinished("step_limit", "build the backend", [
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "x", "type": "function", "function": {"name": "list_files", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "x", "name": "list_files", "content": "src/App.tsx"}])
    model = install(monkeypatch, [("Removed it.", [])])
    runner = TurnRunner(FakeSandbox(dict(FILES)), routing.EDIT, [],
                        'Remove the part with "LR-1H9ZK7" from the page.',
                        memory={"ledger": {}, "unfinished": left})
    assert not runner.continuing
    await collect(runner)
    system = model.requests[0]["messages"][0]["content"]
    assert "Unfinished: an earlier request" in system and "build the backend" in system
    assert "stopped before it finished" not in texts(model.requests[0])     # not carried in full
    assert runner.memory["unfinished"]["request"] == "build the backend"   # still there after


async def test_the_ledger_and_env_are_in_every_turn(monkeypatch):
    model = install(monkeypatch, [("Hello.", [])])
    ledger = {}
    memory.record(ledger, "apply_migration", {"name": "create_riders", "sql":
                  "create table if not exists public.riders (id text); CREATE TABLE shipments (id text);"},
                  "Migration create_riders applied.")
    memory.record(ledger, "set_secret", {"key": "DECANE_APP_ID", "value": "v"}, "Secret DECANE_APP_ID set.")
    memory.record(ledger, "set_secret", {"key": "DECANE_APP_ID", "value": "v"}, "Secret DECANE_APP_ID set.")
    memory.record(ledger, "deploy_edge_function", {"name": "api"}, "Deployed api (version 1).")
    memory.record(ledger, "run_command", {"command": "npm install decane-connect-kit qrcode.react"},
                  "[exit code 0]\nadded 2 packages")
    memory.record(ledger, "set_secret", {"key": "BAD"}, "error: value is required")
    assert ledger == {"migrations": ["create_riders"], "tables": ["riders", "shipments"],
                      "secrets": ["DECANE_APP_ID"], "functions": ["api"],
                      "packages": ["decane-connect-kit", "qrcode.react"]}
    runner = TurnRunner(FakeSandbox(dict(FILES)), routing.EDIT, [], "hi",
                        memory={"ledger": ledger}, env_values={"VITE_DECANE_APP_ID": "app-1"})
    await collect(runner)
    system = model.requests[0]["messages"][0]["content"]
    assert "## Project memory" in system and "Edge function secrets set: DECANE_APP_ID" in system
    assert "Tables this app created: riders, shipments" in system and "VITE_DECANE_APP_ID=app-1" in system


def test_dropping_tables_this_app_did_not_create():
    ledger = {"tables": ["shipments"]}
    sql = "drop table if exists public.bookings, votes cascade; drop table shipments; truncate awards;"
    assert memory.foreign_drops(sql, ledger, "make it full stack") == ["awards", "bookings", "votes"]
    assert memory.foreign_drops("create table x (id int); drop table x;", {}, "") == []
    assert memory.foreign_drops("delete from bookings;", {}, "") == ["bookings"]
    assert memory.foreign_drops("delete from bookings where id = 1;", {}, "") == []
    assert memory.foreign_drops("-- drop table bookings\nselect 1", {}, "") == []
    assert memory.foreign_drops("drop table bookings;", {}, "yes drop the bookings table") == []
    assert memory.foreign_drops("drop schema public cascade;", {}, "") == ["a whole schema"]


async def test_the_loop_refuses_a_foreign_drop(monkeypatch):
    monkeypatch.setattr(settings, "FALLBACK_MODEL", "vendor/primary")
    model = install(monkeypatch, [
        ("", [call("apply_migration", {"name": "reset", "sql": "drop table bookings;"}, "m1")]),
        ("Left them alone.", []),
    ])
    runner = TurnRunner(FakeSandbox(dict(FILES)), routing.EDIT, [], "clear out the database")
    await collect(runner)
    result = next(m for m in model.requests[1]["messages"] if m.get("tool_call_id") == "m1")
    assert result["content"].startswith("error: refused") and "bookings" in result["content"]
    assert "migrations" not in runner.memory["ledger"]


async def test_reading_in_circles_is_called_out(monkeypatch):
    monkeypatch.setattr(settings, "FALLBACK_MODEL", "vendor/primary")
    monkeypatch.setattr(settings, "BUILDER_MAX_STEPS", 6)
    monkeypatch.setattr(settings, "BUILDER_READ_STREAK", 2)
    model = install(monkeypatch, [
        ("", [call("read_file", {"path": "src/App.tsx"}, "r1")]),
        ("", [call("list_files", {}, "r2")]),
        ("", [call("write_file", {"path": "src/A.tsx", "content": "export {}"}, "r3")]),
        ("Done.", []),
    ])
    await collect(TurnRunner(FakeSandbox(dict(FILES)), routing.EDIT, [], "add a page"))
    nudge = READ_NUDGE.format(n=2)
    assert nudge not in texts(model.requests[1]) and nudge in texts(model.requests[2])


def test_compact_keeps_the_last_read_pairs_calls_and_fits_the_budget(monkeypatch):
    def step(cid, name, args, result):
        return [{"role": "assistant", "content": None, "tool_calls": [
                    {"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]},
                {"role": "tool", "tool_call_id": cid, "name": name, "content": result}]
    msgs = (step("1", "read_file", {"path": "a.ts"}, "old a") +
            [{"role": "user", "content": "a nudge"}] +
            step("2", "write_file", {"path": "b.ts", "content": "z" * 5000}, "Wrote b.ts") +
            step("3", "read_file", {"path": "a.ts"}, "new a") +
            [{"role": "assistant", "content": None, "tool_calls": [
                {"id": "4", "type": "function", "function": {"name": "list_files", "arguments": "{}"}}]}])
    out = memory.compact(msgs)
    contents = [m.get("content") for m in out if m["role"] == "tool"]
    assert contents == ["(read again later; see the later read)", "Wrote b.ts", "new a"]
    assert not any(m["role"] == "user" for m in out)                       # nudges are not carried
    assert all(c["id"] != "4" for m in out for c in m.get("tool_calls") or [])  # no result: dropped
    write_args = json.loads(out[2]["tool_calls"][0]["function"]["arguments"])
    assert len(write_args["content"]) < 2000
    assert memory.seen_reads(out) == {memory.read_key({"path": "a.ts"}): memory.digest("new a")}

    monkeypatch.setattr(settings, "BUILDER_MEMORY_CARRY_CHARS", 600)
    small = memory.compact(msgs)
    assert small and small[0]["tool_calls"][0]["id"] == "3"                 # oldest steps go first


@pytest.mark.parametrize("text,expected", [
    ("continue", True), ("cnontinue", True), ("contiue", True),
    ("finish the fullstack and payment thing", True), ("ok", True),
    ('Remove the part with "LR-1H9ZK7" from the page.', False), ("make the header blue", False),
])
def test_what_counts_as_continuing(text, expected):
    assert memory.continues(text) is expected


def test_hand_edits_and_restores_mark_carried_reads_stale():
    mem = {"ledger": {}, "unfinished": memory.unfinished("step_limit", "x", [])}
    memory.mark_stale(mem, ["src/App.tsx"])
    memory.mark_stale(mem, [memory.EVERY_FILE, "src/App.tsx"])
    assert mem["unfinished"]["stale"] == sorted(["src/App.tsx", memory.EVERY_FILE])
    left = dict(mem["unfinished"], messages=[
        {"role": "assistant", "content": "Looked."}])
    closing = memory.carry_messages(left)[-1]["content"]
    assert "read them again first: " in closing and "src/App.tsx" in closing


async def test_installs_are_a_change_and_env_is_not_read():
    sb = FakeSandbox(dict(FILES))
    out = await tools.execute("run_command", {"command": "npm install decane-connect-kit"}, sb)
    assert out.touched == "package.json"
    plain = await tools.execute("run_command", {"command": "npm install"}, sb)
    assert plain.touched is None
    assert (await tools.execute("read_file", {"path": ".env"}, sb)).text.startswith("error")
    for cmd in ("cat .env", "grep VITE .env", "node -e \"require('fs').readFileSync('.env')\""):
        assert "not allowed" in (await tools.execute("run_command", {"command": cmd}, sb)).text
    assert "not allowed" not in (await tools.execute("run_command", {"command": "ls src"}, sb)).text
