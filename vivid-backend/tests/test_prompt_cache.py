"""Claude caches only what a request marks; video runs trim old context in batches;
a reported OpenRouter cost wins over the price list."""
import json

from app.builder import pricing, video as video_mod
from app.services.models_gateway.code_llm import with_cache_breakpoints


def _conv():
    return [{"role": "system", "content": "You make videos."},
            {"role": "user", "content": "Make it."},
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "a", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "a", "name": "read_file", "content": "file text"}]


def test_claude_requests_mark_the_system_prompt_and_the_newest_message():
    msgs = _conv()
    out = with_cache_breakpoints(msgs, "anthropic/claude-sonnet-5.5")
    assert out[0]["content"] == [{"type": "text", "text": "You make videos.", "cache_control": {"type": "ephemeral"}}]
    assert out[3]["content"][0]["cache_control"] == {"type": "ephemeral"}       # the tool result
    assert out[1]["content"] == "Make it." and out[2]["content"] is None           # untouched
    assert msgs[0]["content"] == "You make videos."                                # the caller's list is not changed
    marks = sum(1 for m in out if isinstance(m["content"], list)
                for p in m["content"] if "cache_control" in p)
    assert marks == 2


def test_images_and_other_models():
    msgs = _conv() + [{"role": "user", "content": [{"type": "text", "text": "stills"},
                                                    {"type": "image_url", "image_url": {"url": "data:x"}}]}]
    out = with_cache_breakpoints(msgs, "anthropic/claude-fable-5.1")
    assert "cache_control" in out[-1]["content"][-1] and "cache_control" not in out[-1]["content"][0]
    assert with_cache_breakpoints(msgs, "deepseek/deepseek-v4-flash") is msgs      # caches on its own


def test_long_video_runs_trim_old_output_in_one_batch(monkeypatch):
    monkeypatch.setattr(video_mod, "COMPACT_AT_CHARS", 5_000)
    msgs = [{"role": "system", "content": "S" * 100}]
    for i in range(14):
        msgs.append({"role": "assistant", "content": None, "tool_calls": [{"id": f"c{i}", "type": "function",
                     "function": {"name": "write_file", "arguments": json.dumps({"path": "x", "content": "y" * 900})}}]})
        msgs.append({"role": "tool", "tool_call_id": f"c{i}", "name": "write_file", "content": "z" * 900})
    assert video_mod._compact(msgs)
    tools = [m for m in msgs if m["role"] == "tool"]
    assert all("trimmed" in t["content"] for t in tools[:-video_mod.KEEP_RECENT_RESULTS])
    assert all(t["content"] == "z" * 900 for t in tools[-video_mod.KEEP_RECENT_RESULTS:])
    first_args = json.loads(msgs[1]["tool_calls"][0]["function"]["arguments"])
    assert first_args["content"].startswith("[900 characters")
    last_args = json.loads(msgs[-2]["tool_calls"][0]["function"]["arguments"])
    assert last_args["content"] == "y" * 900                                       # recent writes stay whole
    assert msgs[0]["content"] == "S" * 100
    small = [{"role": "system", "content": "s"}, {"role": "tool", "content": "t" * 900}]
    assert not video_mod._compact(small)


def test_reported_cost_wins():
    price = pricing.Price(prompt=0.000003, completion=0.000015, cached=0.0000003)
    assert price.cost({"prompt_tokens": 1000, "completion_tokens": 10, "cost": 0.0123}) == 0.0123
    assert round(price.cost({"prompt_tokens": 1000, "completion_tokens": 10,
                             "prompt_tokens_details": {"cached_tokens": 800}}), 7) == round(200 * 0.000003 + 800 * 0.0000003 + 10 * 0.000015, 7)
