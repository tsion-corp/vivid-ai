"""One builder turn: the model call, its tool calls, the step cap, and the
one retry on the fallback model.

`TurnRunner.run()` is an async generator of UI Message Stream parts (see
stream.py). The route frames them for the wire and folds them into stored
parts; the eval script counts them. Nothing here knows about HTTP or the
database.

The shape follows services/code_agent.py: messages are appended only when a
model call completes, so a broken stream leaves the conversation valid, and
a tool result is always paired with the assistant turn that asked for it.
"""
import asyncio
from datetime import datetime, timezone
import json
import logging
import re
from dataclasses import dataclass, field
from typing import AsyncIterator, Awaitable, Callable

from app.builder import context, prompt, routing, screenshots, skills, stream, tools
from app.builder.sandbox.base import Sandbox
from app.core.config import settings
from app.services.models_gateway import code_llm, provider
from app.services.models_gateway.code_llm import CodeLLMUnavailable

log = logging.getLogger("vivid.builder.loop")

ANSWERED = "answered"
STEP_LIMIT = "step_limit"
TYPECHECK_STRIKES = "typecheck_strikes"
CANCELLED = "cancelled"
ERROR = "error"

#: Attempt outcomes that earn a retry on the fallback model. ERROR is the
#: primary's stream failing repeatedly; the fallback is another vendor.
#: A build turn that ended without changing a file: not an answer.
NO_CHANGES = "no_changes"
RETRYABLE = {STEP_LIMIT, TYPECHECK_STRIKES, ERROR, NO_CHANGES}
#: The reasons a client may treat as "the turn ended the way it meant to".
OK_REASONS = {ANSWERED, "asked", "spec_written"}

RETRY_NOTICE = "Retrying with a different model."


@dataclass
class ModelCall:
    """One model request, for the usage ledger."""
    model: str
    stage: str
    usage: dict | None


@dataclass
class TurnResult:
    reason: str = ERROR
    steps: int = 0
    #: Slug of the model that produced the final answer.
    model: str = ""
    calls: list[ModelCall] = field(default_factory=list)
    touched: list[str] = field(default_factory=list)
    #: Tool calls whose arguments could not be parsed, as "name path".
    failed_tools: list[str] = field(default_factory=list)
    #: Storage key of the latest desktop screenshot, for the project card.
    thumbnail_key: str | None = None
    typecheck_failures: int = 0
    retried: bool = False
    critique_rounds: int = 0
    completion_rounds: int = 0
    #: Stored screenshot keys, newest round last.
    screenshots: list[str] = field(default_factory=list)

    @property
    def tokens_in(self) -> int:
        return sum((c.usage or {}).get("prompt_tokens", 0) for c in self.calls)

    @property
    def tokens_out(self) -> int:
        return sum((c.usage or {}).get("completion_tokens", 0) for c in self.calls)


STREAM_RETRY_NOTICE = "The model connection dropped; retrying."

_REASON_WORDS = {"step_limit": "it ran out of steps", "typecheck_strikes": "the typecheck kept failing",
                 "error": "its connection failed", "no_changes": "it wrote no files"}
#: The fallback needs what was done, not every byte of it: long tool
#: results are shortened to their first lines.
_CARRY_RESULT_CHARS = 600


_PATH_IN_ERROR = re.compile(r'"path"\s*:\s*"([^"]+)"')


def _path_hint(error: str) -> str:
    m = _PATH_IN_ERROR.search(error or "")
    return m.group(1) if m else ""


def _trim_carry(messages: list[dict]) -> list[dict]:
    out = []
    for m in messages:
        if m.get("role") == "tool" and isinstance(m.get("content"), str) \
                and len(m["content"]) > _CARRY_RESULT_CHARS:
            m = dict(m, content=m["content"][:_CARRY_RESULT_CHARS] + "\n... (shortened)")
        out.append(m)
    return out


#: Put to the fallback model after the primary's conversation: continue,
#: do not start over.
HANDOVER_NOTE = ("The previous model stopped here ({reason}); the files it wrote are in place and "
                 "its tool results above are current. Continue from this state: do not re-read "
                 "files you can see above, do not remake pictures or migrations already made, "
                 "finish what is left, get the typecheck clean, and reply to the user.")
BUILD_NUDGE = ("You have not changed any files yet. Build the app now: write the files with "
               "write_file (several per step), install what you need with run_command, and "
               "only then reply. Do not describe the plan.")
BLANK_NUDGE = ("Your reply was empty. Continue the work with tool calls now, or answer the "
               "user in plain sentences.")
CONTINUE_NUDGE = ("Go on and do it now with the tools; do not describe what you are about "
                  "to do. Reply to the user only when the work is complete.")

#: A final reply that says what comes next instead of what was done.
_INTENT = re.compile(
    r"(let me|let's|i['’]ll|i will|now i|next[, ]|i am going to|i'm going to|"
    r"going to (build|create|write|add|wire|set up)|then build|then i)\b[^.!?]*[.!]?\s*$",
    re.IGNORECASE)


def _announces_more_work(text: str) -> bool:
    tail = (text or "").strip()[-220:]
    return bool(tail) and bool(_INTENT.search(tail))

COMPLETION_BRIEF = """Before we show this to the user, review the app against the spec, page by \
page. Check: every page in the spec's Pages section exists, is routed, and is linked from the \
nav and footer; any admin or owner area exists at its own route behind a sign-in gate and is NOT \
linked from the customer nav (a footer "Owner sign in" link at most); each list has at least eight realistic \
seeded items with names, prices in the spec's currency, short descriptions and an image \
(generate_image for anything without an upload); each page has every section its recipe \
lists; every image path used in the code AND in seeded database rows (query the tables that hold \
image columns) exists in public/uploads (list_files it; generate or repoint any that do \
not, a broken image is worse than none); forms work end to end (add to \
cart, book, save); index.html has a real title, description, theme-color and a favicon link \
with public/favicon.png present; the footer has the real business details; the copy passes the copy \
skill's checks. list_files and read what you need, then build everything that is missing or thin \
now, in this turn. Do not shorten anything. When it is complete, reply to the user in one or \
two sentences about what the app now contains."""
MOBILE_COMPLETION_BRIEF = """Before we show this to the user, review the app against the spec, \
screen by screen. Check: every screen in the spec exists as a route under app/ and is reachable \
(a tab in app/(tabs)/_layout.tsx with a clear icon and label, or a link from a screen that is); \
any admin or owner area sits behind a sign-in and is NOT a customer tab; each list is a FlatList \
with at least eight realistic seeded items with names, prices in the spec's currency, short \
descriptions and an image (generate_image for anything without an upload); every image the \
code requires exists under assets/ (list_files it; generate or repoint any that do not, a \
missing require crashes the app); every screen has loading and empty states, keeps its content \
inside the safe area, and scrolls when it is taller than a phone; forms work end to end and move \
out of the keyboard's way; touch targets are at least 44pt; buttons and cards press with a \
spring and a haptic (PressableScale), list rows and first content enter with the motion \
reference's entrances, cards are raised (soft shadow or lighter surface) under a floating \
layer, and the recipe's signature moment is built and works; app.json has the real app name; the \
copy passes the copy skill's checks; nothing uses DOM elements, window or document. list_files \
and read what you need, then build everything that is missing or thin now, in this turn. Do not \
shorten anything. When it is complete, reply to the user in one or two sentences about what the \
app now contains."""
#: Added to the completeness brief when the project has a Supabase backend:
#: the app-logic skill's definition of done, checked, not assumed.
CHAIN_BRIEF = """ This project is on-chain, so also check: every contract the spec needs is deployed \
with deploy_contract and imported from src/lib/contracts (no hard-coded addresses elsewhere); \
the app connects a wallet, switches it to the chain, shows the balance and a faucet link when \
it is zero, and every transaction shows a pending state and an explorer link; the deployer key \
is nowhere in src/ or .env."""
FULLSTACK_BRIEF = """ This project has a Supabase backend, so also check the app-logic skill's \
definition of done: sign-up, sign-in, sign-out and password reset exist and the session \
survives a reload; a new customer can do the main thing end to end and see it in their \
account; the owner signs in, lands in /admin and can move an order or booking to its next \
state through the transition function; other roles named in the spec can apply through the \
site and be approved from /admin; sign out is in the header on desktop and phone and the auth \
spinner never sticks; every table has row level security with policies \
per role; nothing that matters is kept in localStorage; no service key or secret in src/ or \
.env. Build what is missing with apply_migration (or the migration files when the tools are \
not available) and the app files, then tell the user how to sign in as the owner."""
#: Seconds before restarting a broken stream, multiplied by the attempt.
_RETRY_BACKOFF = 1.5


class ModelStep:
    """One model call streamed as parts, restarted whole if the stream
    breaks. Providers behind OpenRouter drop long responses often enough
    that a first build would fail one time in a handful without this.
    Restarting is safe: the conversation is not touched until the call
    completes, so a half-streamed reply leaves no trace. The prose the user
    already saw is closed with a notice."""

    def __init__(self, messages: list[dict], schemas: list[dict],
                 endpoint: provider.Endpoint) -> None:
        self.messages, self.schemas, self.endpoint = messages, schemas, endpoint
        self.text = ""
        self.calls: list[dict] = []
        self.usage: dict | None = None
        self.failed: CodeLLMUnavailable | None = None

    async def run(self) -> AsyncIterator[dict]:
        attempts = max(1, settings.CODE_STREAM_RETRIES)
        for attempt in range(1, attempts + 1):
            text_id, started, parts, calls, usage = stream.new_id("txt"), False, [], [], None
            try:
                async for ev in code_llm.stream_chat(
                        self.messages, self.schemas, endpoint=self.endpoint,
                        max_tokens=settings.BUILDER_MAX_REPLY_TOKENS,
                        temperature=settings.BUILDER_TEMPERATURE):
                    if ev["type"] == "token":
                        if not started:
                            started = True
                            yield stream.text_start(text_id)
                        parts.append(ev["text"])
                        yield stream.text_delta(text_id, ev["text"])
                    elif ev["type"] == "tool_calls":
                        calls = ev["calls"]
                    elif ev["type"] == "done":
                        usage = ev.get("usage")
            except CodeLLMUnavailable as e:
                if started:
                    yield stream.text_end(text_id)
                if attempt == attempts:
                    log.warning("model call failed after %d attempts: %s", attempts, e)
                    self.failed = e
                    return
                log.warning("stream broke (attempt %d/%d), restarting: %s", attempt, attempts, e)
                yield stream.data("notice", {"text": STREAM_RETRY_NOTICE,
                                             "reason": "stream_retry", "attempt": attempt})
                await asyncio.sleep(_RETRY_BACKOFF * attempt)
                continue
            if started:
                yield stream.text_end(text_id)
            self.text, self.calls, self.usage = "".join(parts).strip(), calls, usage
            return


class TurnRunner:
    def __init__(self, sandbox: Sandbox, stage: str, history: list[dict],
                 user_text: str, spec_md: str | None = None,
                 recent_files: list[str] | None = None,
                 cancelled: Callable[[], bool] = lambda: False,
                 message_id: str | None = None,
                 backend: tools.Backend | None = None,
                 assets_block: str = "",
                 keepalive: Callable[[], Awaitable[None]] | None = None,
                 project_id: str = "",
                 critique: bool | None = None,
                 images=None,
                 payments: str | None = None,
                 fullstack: bool = False,
                 backend_env: bool = False,
                 recipe: str | None = None,
                 maps: str | None = None,
                 chain: "tools.Chain | None" = None,
                 auth: str | None = None) -> None:
        self.sandbox = sandbox
        self.backend = backend
        #: The app has a Supabase client (keys pasted) but this turn has no
        #: management tools: migrations and functions are written as files.
        self.backend_env = backend_env
        #: The design recipe the plan chose for this project.
        self.recipe = recipe
        #: "google" when the project has a Maps key; adds the maps skill.
        self.maps = maps
        #: "decane" when the app has its own sign-in; adds the auth skill.
        self.auth = auth
        #: The chain and deployer when the project is on-chain; adds the
        #: deploy tools and the web3 skill.
        self.chain = chain
        #: The previous attempt's conversation, handed to the next model.
        self._carry: list[dict] = []
        self._live: tuple[list[dict], int] | None = None
        #: The user asked for accounts and server-side data (plan or client
        #: set it). Adds the app-logic skill when a backend is linked.
        self.fullstack = fullstack
        #: "paystack" when the project takes payments; adds the skill.
        self.payments = payments
        #: An ImageMaker when the image model is configured; the model may
        #: make pictures for a project with no uploads.
        self.images = images
        self.assets_block = assets_block
        self.project_id = project_id
        #: Screenshot the page after the answer and let the model fix what
        #: it sees. Defaults to the setting; the eval turns it off for A.
        self.critique = settings.BUILDER_DESIGN_CRITIQUE if critique is None else critique
        #: Awaited after every step. A long turn outlives a sandbox whose
        #: lifetime is only extended between turns; this extends it as
        #: the turn goes.
        self.keepalive = keepalive
        self.stage = stage
        self.history = history
        self.user_text = user_text
        self.spec_md = spec_md
        self.recent_files = recent_files or []
        self.cancelled = cancelled
        self.message_id = message_id or stream.new_id("msg")
        self.result = TurnResult()

    # ---------------------------------------------------------------- run
    async def run(self) -> AsyncIterator[dict]:
        yield stream.start(self.message_id)
        primary = routing.endpoint_for(self.stage)
        fallback = routing.endpoint_for(routing.FALLBACK)

        outcome = ERROR
        async for part in self._attempt(primary, self.stage):
            yield part
        outcome = self.result.reason

        if outcome in RETRYABLE and fallback.configured and fallback.model != primary.model:
            log.info("turn on %s ended with %s; retrying on %s",
                     primary.model, outcome, fallback.model)
            self.result.retried = True
            yield stream.data("notice", {"text": RETRY_NOTICE, "reason": outcome})
            text_id = stream.new_id("txt")
            yield stream.text_start(text_id)
            yield stream.text_delta(text_id, RETRY_NOTICE)
            yield stream.text_end(text_id)
            async for part in self._attempt(fallback, routing.FALLBACK):
                yield part
            outcome = self.result.reason

        if outcome in RETRYABLE and outcome != ERROR:
            # Both models ran out of road. Say so in the thread rather than
            # ending on a tool result the user cannot read.
            text_id = stream.new_id("txt")
            yield stream.text_start(text_id)
            yield stream.text_delta(text_id, _exhausted_message(outcome))
            yield stream.text_end(text_id)

        yield stream.data("usage", {
            "model": self.result.model, "steps": self.result.steps,
            "tokens_in": self.result.tokens_in, "tokens_out": self.result.tokens_out,
            "reason": outcome, "ok": outcome in OK_REASONS,
            "failed_tools": list(self.result.failed_tools),
        })
        yield stream.finish()

    @property
    def _mobile(self) -> bool:
        return self.sandbox.target.is_mobile

    @property
    def _app_logic(self) -> bool:
        """The app-logic skill and its done check apply only to a project
        the user asked to be full-stack, and only once a backend is linked
        so the migration and function tools exist."""
        return self.fullstack and (self.backend is not None or self.backend_env)

    # ------------------------------------------------------------ attempt
    async def _attempt(self, endpoint: provider.Endpoint, stage: str) -> AsyncIterator[dict]:
        """One model's try at the turn. Sets self.result.reason on exit."""
        self.result.model = endpoint.model
        self._live = None
        try:
            async for part in self._attempt_inner(endpoint, stage):
                yield part
        finally:
            if self._live is not None:
                messages, base_len = self._live
                self._carry = _trim_carry(messages[base_len:])

    async def _attempt_inner(self, endpoint: provider.Endpoint, stage: str) -> AsyncIterator[dict]:
        block = await context.build(self.sandbox, self.recent_files)
        messages = [{"role": "system",
                     "content": prompt.system_prompt(
                         self.spec_md, block, backend=self.backend is not None,
                         assets_block=self.assets_block,
                         skill_block=skills.ui_block(self.spec_md, self.user_text,
                                                    payments=self.payments,
                                                    backend=self._app_logic,
                                                    recipe=self.recipe, maps=self.maps,
                                                    chain=self.chain is not None,
                                                    auth=self.auth, mobile=self._mobile),
                         fullstack=self.fullstack, backend_env=self.backend_env,
                         functions=self.backend is None or self.backend.can_functions,
                         chain=self.chain, mobile=self._mobile)}]
        messages += self.history
        messages.append({"role": "user", "content": self.user_text})
        if self._carry:
            # A handover: the fallback sees what the primary did and why it
            # stopped, instead of re-reading the project from scratch.
            messages += self._carry
            messages.append({"role": "user", "content": HANDOVER_NOTE.format(
                reason=_REASON_WORDS.get(self.result.reason, self.result.reason))})
        base_len = len(messages)
        self._carry = []
        self._live = (messages, base_len)

        strikes = 0
        # The turn's stage, not the attempt's: a fallback attempt of a first
        # build is still a first build (budget, review, critique).
        first_build = self.stage == routing.BUILD
        budget = settings.BUILDER_BUILD_MAX_STEPS if first_build else settings.BUILDER_MAX_STEPS
        completion_left = settings.BUILDER_COMPLETION_ROUNDS if first_build else 0
        critique_left = settings.BUILDER_CRITIQUE_ROUNDS if self.critique else 0
        # A small edit does not need a screenshot pass; a first build, a
        # request about looks, or a turn that touched several files does.
        critique_always = first_build or _about_looks(self.user_text)
        nudges_left = 2
        review_deadline = None
        extended = False
        step = 0
        while True:
            step += 1
            if step > budget and not extended and strikes == 0 \
                    and review_deadline is None and not self.result.completion_rounds \
                    and not self.result.critique_rounds:
                # Still writing clean files at the cap: more steps for this
                # model beat a handover.
                extended = True
                budget += (settings.BUILDER_BUILD_EXTENSION_STEPS if first_build
                           else settings.BUILDER_EDIT_EXTENSION_STEPS)
                yield stream.data("status", {"text": "Still building, a few more steps"})
            if step > budget:
                if (review_deadline is not None and step > review_deadline
                        and critique_left > 0 and self.result.touched):
                    # The review spent its steps mid-work. Close it with a
                    # look at the page: the critique keeps its own budget.
                    review_deadline = None
                    critique_left -= 1
                    shots = await screenshots.capture(
                        self.sandbox, self.project_id or "project",
                        f"{self.message_id}-r{self.result.critique_rounds + 1}")
                    if shots:
                        self.result.critique_rounds += 1
                        self.result.thumbnail_key = shots[0].key or self.result.thumbnail_key
                        self.result.screenshots += [s.key for s in shots if s.key]
                        yield stream.data("critique", {
                            "round": self.result.critique_rounds,
                            "broken": bool(screenshots.last_report and screenshots.last_report.broken),
                            "screenshots": [{"name": s.name, "width": s.width, "url": s.url}
                                            for s in shots]})
                        messages.append(screenshots.critique_message(shots, screenshots.last_report,
                                                                    mobile=self._mobile))
                        budget = step + settings.BUILDER_CRITIQUE_STEPS
                        self.result.reason = ANSWERED
                        if self.keepalive is not None:
                            await self.keepalive()
                        continue
                break
            if self.cancelled():
                yield stream.abort("cancelled by the user")
                self.result.reason = CANCELLED
                return
            self.result.steps += 1
            yield stream.start_step()

            # Once the picture budget is spent the tool goes away: a refused
            # call still costs a step, and the model keeps trying otherwise.
            images = self.images if (self.images is not None and self.images.left > 0) else None
            call_step = ModelStep(messages, tools.schemas_for(self.backend, images, self.chain), endpoint)
            async for part in call_step.run():
                yield part
            if call_step.failed is not None:
                yield stream.error(call_step.failed.public)
                self.result.reason = ERROR
                return
            self.result.calls.append(ModelCall(endpoint.model, stage, call_step.usage))
            text, calls = call_step.text, call_step.calls

            if not calls:
                messages.append({"role": "assistant", "content": text})
                yield stream.finish_step()
                if nudges_left > 0 and not text.strip():
                    # Nothing visible and no tool call: a reply that was
                    # dropped somewhere (reasoning, a parse failure). Ask
                    # for it again rather than calling that an answer.
                    nudges_left -= 1
                    messages.append({"role": "user", "content": BLANK_NUDGE})
                    continue
                if nudges_left > 0 and _announces_more_work(text):
                    # "Let me build the pages." with no tool call is not the
                    # end of the turn; tell the model to go on.
                    nudges_left -= 1
                    messages.append({"role": "user", "content": CONTINUE_NUDGE})
                    continue
                if first_build and not self.result.touched and review_deadline is None:
                    # A first build that wrote nothing is not done, whatever
                    # the model says. One push, then the fallback.
                    if nudges_left > 0:
                        nudges_left -= 1
                        messages.append({"role": "user", "content": BUILD_NUDGE})
                        continue
                    self.result.reason = NO_CHANGES
                    return
                self.result.reason = ANSWERED
                if completion_left > 0 and self.result.touched:
                    # Content before looks: is the whole spec there?
                    completion_left -= 1
                    self.result.completion_rounds += 1
                    yield stream.data("status", {"text": "Checking the app against the spec"})
                    yield stream.data("review", {"kind": "completeness",
                                                 "round": self.result.completion_rounds})
                    brief = (MOBILE_COMPLETION_BRIEF if self._mobile else COMPLETION_BRIEF) \
                        + (FULLSTACK_BRIEF if self._app_logic else "") \
                        + (CHAIN_BRIEF if self.chain is not None else "")
                    messages.append({"role": "user", "content": brief})
                    budget = step + settings.BUILDER_COMPLETION_STEPS
                    review_deadline = budget
                    strikes = 0                          # a new phase, a fresh count
                    if self.keepalive is not None:
                        await self.keepalive()
                    continue
                if critique_left > 0 and self.result.touched and (
                        critique_always
                        or len(self.result.touched) >= settings.BUILDER_CRITIQUE_MIN_FILES):
                    # The page is whole: look at it, then keep going with a
                    # few extra steps for the fixes.
                    critique_left -= 1
                    yield stream.data("status", {"text": "Looking at the app on iPhone and Android"
                                                  if self._mobile else
                                                  "Looking at the page on desktop and phone"})
                    shots = await screenshots.capture(
                        self.sandbox, self.project_id or "project",
                        f"{self.message_id}-r{self.result.critique_rounds + 1}")
                    if shots:
                        self.result.critique_rounds += 1
                        self.result.thumbnail_key = shots[0].key or self.result.thumbnail_key
                        self.result.screenshots += [s.key for s in shots if s.key]
                        yield stream.data("critique", {
                            "round": self.result.critique_rounds,
                            "broken": bool(screenshots.last_report and screenshots.last_report.broken),
                            "screenshots": [{"name": s.name, "width": s.width, "url": s.url}
                                            for s in shots]})
                        messages.append(screenshots.critique_message(shots, screenshots.last_report,
                                                                    mobile=self._mobile))
                        budget = step + settings.BUILDER_CRITIQUE_STEPS
                        if self.keepalive is not None:
                            await self.keepalive()
                        continue
                return

            messages.append({
                "role": "assistant", "content": text or None,
                "tool_calls": [{"id": c["id"], "type": "function",
                                "function": {"name": c["name"],
                                             "arguments": json.dumps(c["arguments"])}}
                               for c in calls]})

            # Writes in this step are typechecked once, together, after the
            # last of them; their outputs are held back until the report
            # exists so the model reads it next to the file it belongs to.
            held: list[tuple[dict, tools.Outcome]] = []
            results: dict[str, str] = {}
            wrote_kind = None
            # Pictures take a minute each and do not touch the code: a step
            # that asks for several gets them all at once.
            pre: dict[str, tools.Outcome] = {}
            retry_call: tuple[str, str, str] | None = None
            image_calls = [c for c in calls if c["name"] == "generate_image" and not c.get("error")]
            if len(image_calls) > 1:
                yield stream.data("status", {"text": f"Making {len(image_calls)} pictures"})
                outs = await asyncio.gather(*(
                    tools.execute(c["name"], c["arguments"], self.sandbox, self.backend,
                                  self.images, typecheck_now=False, chain=self.chain)
                    for c in image_calls))
                pre = {c["id"]: o for c, o in zip(image_calls, outs)}
                if self.keepalive is not None:
                    await self.keepalive()
            for call in calls:
                if self.cancelled():
                    yield stream.abort("cancelled by the user")
                    self.result.reason = CANCELLED
                    return
                yield stream.tool_input(call["id"], call["name"], call["arguments"])
                status = _status_for(call)
                if status and status != wrote_kind:
                    wrote_kind = status
                    yield stream.data("status", {"text": status})
                if call.get("error"):
                    content = f"error: {call['error']}. Call the tool again with valid JSON."
                    yield stream.tool_error(call["id"], content)
                    results[call["id"]] = content
                    hint = _path_hint(call["error"])
                    self.result.failed_tools.append(f"{call['name']}{' ' + hint if hint else ''}")
                    retry_call = (call["name"], hint, call["error"])
                    continue
                outcome = pre.get(call["id"]) or await tools.execute(
                    call["name"], call["arguments"], self.sandbox, self.backend, self.images,
                    typecheck_now=False, chain=self.chain)
                if outcome.touched and outcome.touched not in self.result.touched:
                    self.result.touched.append(outcome.touched)
                if outcome.touched:
                    held.append((call, outcome))
                else:
                    yield stream.tool_output(call["id"], outcome.text)
                    results[call["id"]] = outcome.text
            if held:
                ok, report = await tools.typecheck(self.sandbox)
                if ok:
                    strikes = 0
                else:
                    strikes += 1
                    self.result.typecheck_failures += 1
                for i, (call, outcome) in enumerate(held):
                    text = outcome.text
                    if i == len(held) - 1:
                        text = tools.truncate(f"{text}\n{report}")
                    yield stream.tool_output(call["id"], text)
                    results[call["id"]] = text
            for call in calls:
                messages.append({"role": "tool", "tool_call_id": call["id"],
                                 "name": call["name"], "content": results.get(call["id"], "")})
            if retry_call is not None:
                # A write that never happened poisons every step after it;
                # insist on the redo before anything else.
                name, hint, err = retry_call
                messages.append({"role": "user", "content": (
                    f"Your {name} call{' for ' + hint if hint else ''} could not be parsed "
                    f"({err[:120]}). Make that exact call again now with valid JSON, before "
                    "anything else; keep the content shorter if it was very long.")})
            yield stream.finish_step()
            if self.keepalive is not None:
                try:
                    await self.keepalive()
                except Exception as e:                       # never fails a turn
                    log.warning("keepalive failed: %s", e)

            if strikes >= settings.BUILDER_TYPECHECK_STRIKES:
                self.result.reason = TYPECHECK_STRIKES
                return

        # Out of steps. During a review or critique the page was already
        # answered for, so the turn still counts as done.
        if (self.result.critique_rounds or self.result.completion_rounds) \
                and self.result.reason == ANSWERED:
            return
        self.result.reason = STEP_LIMIT


#: Plain-English phase lines for a client that wants one sentence.
_TOOL_STATUS = {
    "read_file": "Reading the project", "list_files": "Reading the project",
    "write_file": "Writing the app", "edit_file": "Making the change",
    "run_command": "Installing and running", "get_dev_server_logs": "Checking the dev server",
    "generate_image": "Making pictures", "apply_migration": "Updating the database",
    "query_database": "Checking the database",
    "deploy_contract": "Deploying the contract", "chain_faucet": "Funding the deployer",
    "deploy_edge_function": "Deploying server code", "set_secret": "Storing a secret",
}

_LOOKS = re.compile(r"\b(design|look|looks|colou?r|colours|layout|spacing|font|style|styling|"
                    r"theme|ui|mobile|responsive|hero|padding|margin|align|prettier|beautiful|"
                    r"premium|logo|image|photo)\b", re.IGNORECASE)


def _status_for(call: dict) -> str | None:
    return _TOOL_STATUS.get(call.get("name", ""))


def _about_looks(text: str) -> bool:
    return bool(_LOOKS.search(text or ""))


def _exhausted_message(reason: str) -> str:
    if reason == TYPECHECK_STRIKES:
        return ("I could not get the code to typecheck cleanly this turn. The "
                "preview may show an error; tell me what you see and I will fix it.")
    if reason == NO_CHANGES:
        return ("I did not manage to write any files this turn. Send \"build it\" again "
                "and I will start with the files.")
    return ("I ran out of steps before finishing. Send another message to "
            "continue from here.")


#: The end-of-stream marker inside a feed (the SSE terminator is framed
#: by the route).
FEED_DONE = object()


class TurnFeed:
    """One running turn's output, kept in memory so that the connection
    that started it and any that attach later (a reload, another tab) see
    the same parts; the turn itself runs as a task and does not care
    whether anyone is watching."""

    def __init__(self, project_id: str) -> None:
        self.project_id = project_id
        self.started_at = datetime.now(timezone.utc)
        self.cancel = asyncio.Event()
        self.parts: list = []
        self.done = False
        self.task: asyncio.Task | None = None
        self._cond = asyncio.Condition()

    async def push(self, part) -> None:
        async with self._cond:
            self.parts.append(part)
            self._cond.notify_all()

    async def close(self) -> None:
        async with self._cond:
            self.done = True
            self._cond.notify_all()

    async def follow(self, start: int = 0):
        """Every part from `start`, then new ones as they land, until the
        feed closes. Safe to call from any number of readers."""
        i = start
        while True:
            async with self._cond:
                while i >= len(self.parts) and not self.done:
                    await self._cond.wait()
                if i >= len(self.parts) and self.done:
                    return
                part = self.parts[i]
            i += 1
            yield part


class TurnRegistry:
    """Which projects have a turn in flight in this process, with the feed
    each one writes to. One turn per project at a time."""

    def __init__(self) -> None:
        self._feeds: dict[str, TurnFeed] = {}

    def start(self, project_id: str) -> TurnFeed | None:
        if project_id in self._feeds:
            return None
        feed = TurnFeed(project_id)
        self._feeds[project_id] = feed
        return feed

    def get(self, project_id: str) -> TurnFeed | None:
        return self._feeds.get(project_id)

    def finish(self, project_id: str) -> None:
        self._feeds.pop(project_id, None)

    def cancel(self, project_id: str) -> bool:
        feed = self._feeds.get(project_id)
        if feed is None:
            return False
        feed.cancel.set()
        return True

    def running(self, project_id: str) -> bool:
        return project_id in self._feeds

    def started_at(self, project_id: str):
        feed = self._feeds.get(project_id)
        return feed.started_at if feed else None


turns = TurnRegistry()
