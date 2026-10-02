"""Adapter for the coding model (Devstral: on our pod, or on OpenRouter when
the pod is down — provider.py decides).

Separate from llm.py on purpose: that one serves the Gemma assistant and knows
nothing about tools. This one is the opposite — its whole job is NATIVE tool
calling, which is why the coding agent exists at all. The chat agent recovers
the model's intent by regex-scraping JSON out of prose (services/agent.py);
over a fifty-step coding loop that fails often enough to be useless.

When the pod serves it, vLLM must have been started with:
    --enable-auto-tool-choice --tool-call-parser mistral
Without those, vLLM ignores `tools` and answers in prose. probe_tool_support()
detects that at startup rather than leaving it to fail mid-session. OpenRouter
needs no flags, but the probe still tells you whether the chosen model calls
tools at all.
"""
import asyncio
import json
import logging
import ssl

import httpx

from app.core.config import settings
from app.services.models_gateway import http, provider

log = logging.getLogger("vivid.code_llm")


class CodeLLMUnavailable(provider.UpstreamError):
    public = "The coding model is unavailable right now. Please try again in a moment."


# ssl.SSLError and OSError: a corrupted TLS record or a dropped socket can
# surface raw from the stream reader, unmapped by httpx, and would otherwise
# escape as a crash instead of a retry.
_TRANSIENT = (httpx.ConnectError, httpx.ConnectTimeout, httpx.RemoteProtocolError,
              httpx.ReadTimeout, httpx.ReadError, ssl.SSLError, OSError)
_RETRY_DELAY = 0.5
_VLLM_FLAGS = "--enable-auto-tool-choice --tool-call-parser mistral"


def _describe(e: Exception) -> str:
    """httpx transport errors frequently carry an empty message — a bare
    "request failed: " tells nobody anything. Fall back to the class name."""
    return str(e) or e.__class__.__name__


def _endpoint() -> provider.Endpoint:
    ep = provider.endpoint(provider.CODE)
    if not ep.configured:
        raise CodeLLMUnavailable(ep.missing)
    return ep


def configured() -> bool:
    return provider.endpoint(provider.CODE).configured


def missing() -> str | None:
    """Why the coder cannot be served, naming the env var to set."""
    return provider.endpoint(provider.CODE).missing


def model_name() -> str:
    """The vendor id currently serving the coder, for the `ready` frame."""
    return provider.endpoint(provider.CODE).model


def context_tokens() -> int:
    """The window the live coding model serves, as advertised on /v1/models."""
    return provider.endpoint(provider.CODE).context_tokens


def loop_budget_tokens() -> int:
    """What the agent loop may fill before old tool results are blanked.

    CODE_CONTEXT_TOKENS is the loop's own ceiling, chosen to sit under the
    pod's window. It is kept as the ceiling on OpenRouter too — a longer
    window is not a reason to carry more stale tool output — but if the live
    model's window is the smaller number, that wins, with a tenth held back
    for the reply and the estimator's error.
    """
    window = context_tokens()
    if not window:
        return settings.CODE_CONTEXT_TOKENS
    return min(settings.CODE_CONTEXT_TOKENS, int(window * 0.9))


def _stream_error(chunk: dict) -> str | None:
    """See llm._stream_error: OpenRouter can fail mid-stream with a 200."""
    error = chunk.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error)
    if isinstance(error, str) and error:
        return error
    return None


_EPHEMERAL = {"type": "ephemeral"}


def _mark(content):
    """The content with a cache breakpoint on its last block, or None if it can't carry one."""
    if isinstance(content, str):
        return [{"type": "text", "text": content, "cache_control": _EPHEMERAL}] if content.strip() else None
    if isinstance(content, list) and content:
        parts = [dict(p) for p in content]
        for p in reversed(parts):
            if p.get("type") == "image_url" or (p.get("type") == "text" and str(p.get("text") or "").strip()):
                p["cache_control"] = _EPHEMERAL
                return parts
    return None


def with_cache_breakpoints(messages: list[dict], model: str) -> list[dict]:
    """Claude only caches what a request marks (other providers cache on their own).
    Mark the system prompt and the newest message that can carry a marker: each step
    then reads everything before it from the cache (about a tenth of the input price)
    instead of paying full price for the whole conversation again. The caller's list
    is not changed."""
    if not model.lstrip("~").startswith("anthropic/"):
        return messages
    out = list(messages)
    targets = [0] if out and out[0].get("role") == "system" else []
    for i in range(len(out) - 1, 0, -1):
        if _mark(out[i].get("content")) is not None:
            targets.append(i)
            break
    for i in targets:
        marked = _mark(out[i].get("content"))
        if marked is not None:
            out[i] = {**out[i], "content": marked}
    return out


async def stream_chat(messages: list[dict], tools: list[dict],
                      max_tokens: int | None = None,
                      endpoint: provider.Endpoint | None = None,
                      temperature: float | None = None):
    """Yields, in order:
        {"type": "token", "text": str}          assistant prose, as it arrives
        {"type": "tool_calls", "calls": [...]}  once, if the turn ended in calls
        {"type": "done", "finish_reason": str, "usage": dict | None}

    Each call is {"id", "name", "arguments"} with arguments already parsed.
    Tool calls stream as fragments keyed by `index` — name arrives on the
    first fragment, the JSON arguments dribble in across later ones — so they
    are reassembled here and emitted only when the turn is complete.
    """
    # The coding agent takes whatever the provider switch says serves CODE.
    # The app builder passes its own endpoint: it routes by stage, and its
    # models live on OpenRouter whatever the switch says.
    ep = endpoint if endpoint is not None else _endpoint()
    if not ep.configured:
        raise CodeLLMUnavailable(ep.missing)
    payload = {
        "model": ep.model,
        "messages": with_cache_breakpoints(messages, ep.model),
        "tools": tools,
        "tool_choice": "auto",
        "max_tokens": max_tokens or settings.CODE_MAX_REPLY_TOKENS,
        "temperature": (settings.CODE_LLM_TEMPERATURE
                        if temperature is None else temperature),
        "top_p": settings.CODE_LLM_TOP_P,
        "stream": True,
        "stream_options": {"include_usage": True},
        **ep.extra_payload,
    }

    partial: dict[int, dict] = {}
    usage = None
    finish_reason = None
    yielded = False

    for attempt in (1, 2):
        try:
            async with http.client().stream(
                    "POST", ep.url(), json=payload, headers=ep.headers,
                    timeout=settings.CODE_LLM_TIMEOUT) as r:
                if r.status_code >= 400:
                    body = (await r.aread()).decode(errors="replace")[:600]
                    raise CodeLLMUnavailable(
                        f"coding model returned {r.status_code}: {body}")
                async for line in r.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    chunk = json.loads(data)
                    if (problem := _stream_error(chunk)):
                        raise CodeLLMUnavailable(
                            f"coding model stream failed: {problem}")
                    if chunk.get("usage"):
                        usage = chunk["usage"]
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    choice = choices[0]
                    if choice.get("finish_reason"):
                        finish_reason = choice["finish_reason"]
                    delta = choice.get("delta") or {}

                    text = delta.get("content")
                    if text:
                        yielded = True
                        yield {"type": "token", "text": text}

                    for frag in delta.get("tool_calls") or []:
                        yielded = True
                        slot = partial.setdefault(
                            _slot_index(frag, partial),
                            {"id": None, "name": None, "arguments": ""})
                        if frag.get("id"):
                            slot["id"] = frag["id"]
                        fn = frag.get("function") or {}
                        if fn.get("name"):
                            slot["name"] = fn["name"]
                        if fn.get("arguments"):
                            slot["arguments"] += fn["arguments"]
            break
        except _TRANSIENT as e:
            if yielded or attempt == 2:
                raise CodeLLMUnavailable(
                f"coding model request failed: {_describe(e)}") from e
            await asyncio.sleep(_RETRY_DELAY)
        except (httpx.HTTPError, json.JSONDecodeError) as e:
            raise CodeLLMUnavailable(
                f"coding model request failed: {_describe(e)}") from e

    if partial:
        yield {"type": "tool_calls", "calls": _finalize(partial)}
    yield {"type": "done", "finish_reason": finish_reason, "usage": usage}


def _slot_index(frag: dict, partial: dict[int, dict]) -> int:
    """Which call a fragment belongs to. vLLM always numbers fragments; some
    providers behind OpenRouter send each call whole and unnumbered, and
    piling those into slot 0 would merge two calls into one broken one. An
    unnumbered fragment joins the slot with its id, else opens a new one."""
    if frag.get("index") is not None:
        return int(frag["index"])
    call_id = frag.get("id")
    if call_id:
        for idx, slot in partial.items():
            if slot["id"] == call_id:
                return idx
    return max(partial, default=-1) + 1


def _finalize(partial: dict[int, dict]) -> list[dict]:
    """Reassembled fragments -> calls. A call whose arguments did not parse is
    kept with a parse error rather than dropped: the loop feeds that back as
    the tool result so the model can correct itself, which it reliably does.
    Dropping it instead leaves the model waiting on a result that never comes.
    """
    calls = []
    for idx in sorted(partial):
        slot = partial[idx]
        if not slot["name"]:
            continue
        raw = slot["arguments"].strip() or "{}"
        try:
            args = json.loads(raw)
            error = None
        except json.JSONDecodeError as e:
            args, error = {}, f"arguments were not valid JSON ({e}): {raw[:200]}"
        calls.append({
            "id": slot["id"] or f"call_{idx}",
            "name": slot["name"],
            "arguments": args,
            "error": error,
        })
    return calls


async def probe_tool_support() -> dict:
    """Is the served model reachable AND does it actually call tools?

    Sends a one-shot request with a trivial tool the model has no choice but to
    use. On a pod, a 400 means the vLLM flags are missing; prose back means the
    same thing in a friendlier disguise. On OpenRouter, prose back means the
    chosen OPENROUTER_CODE_MODEL is not a tool-calling model.
    """
    ep = provider.endpoint(provider.CODE)
    if not ep.configured:
        return {"ok": False, "tool_calling": False, "provider": ep.provider,
                "detail": ep.missing}
    probe_tool = [{
        "type": "function",
        "function": {
            "name": "report_ready",
            "description": "Report that you are ready. Call this immediately.",
            "parameters": {
                "type": "object",
                "properties": {"ok": {"type": "boolean"}},
                "required": ["ok"],
            },
        },
    }]
    base = {"provider": ep.provider, "model": ep.model}
    try:
        r = await http.client().post(
            ep.url(),
            json={
                "model": ep.model,
                "messages": [{"role": "user",
                              "content": "Call report_ready with ok=true."}],
                "tools": probe_tool,
                "tool_choice": "auto",
                "max_tokens": 64,
                "temperature": 0,
                **ep.extra_payload,
            },
            headers=ep.headers,
            timeout=60)
    except httpx.HTTPError as e:
        return {**base, "ok": False, "tool_calling": False, "detail": _describe(e)}

    if r.status_code >= 400:
        body = r.text[:300]
        hint = ""
        if ep.is_pod and "tool" in body.lower():
            hint = f"start vLLM with {_VLLM_FLAGS}"
        return {**base, "ok": False, "tool_calling": False,
                "detail": f"HTTP {r.status_code}: {body}", "hint": hint}

    msg = (r.json().get("choices") or [{}])[0].get("message") or {}
    if msg.get("tool_calls"):
        return {**base, "ok": True, "tool_calling": True}
    return {
        **base, "ok": True, "tool_calling": False,
        "detail": "model answered in prose instead of calling the tool",
        "hint": (f"vLLM is serving but tool calling is off — restart with "
                 f"{_VLLM_FLAGS}" if ep.is_pod
                 else "pick an OPENROUTER_CODE_MODEL that supports tools"),
    }
