"""What the builder remembers between turns, so a turn continues instead of
starting over.

Past turns reach the model as prose only (routes/builder.py `_history`), so
a turn that ran out of steps used to leave the next one nothing but "Let me
read the store...": it re-read the same files, re-queried the schema,
re-installed packages and re-set secrets, and ran out of steps again. Two
things fix that, kept on the project (builder_projects.memory):

- the ledger: what was done to the world outside the files, which no file
  shows (migrations, tables this app created, function secrets, edge
  functions, packages). It is shown on every turn.
- the unfinished turn: the tool calls and results of a turn that stopped
  before it finished, handed to the next turn to continue from.
"""
import hashlib
import json
import re
from datetime import datetime, timezone

from app.core.config import settings

#: Tools whose calls change the project or the world; a step with none of
#: them only looked around.
PROGRESS_TOOLS = frozenset({
    "write_file", "edit_file", "apply_migration", "deploy_edge_function", "set_secret",
    "generate_image", "deploy_contract", "chain_faucet"})

_CREATE_TABLE = re.compile(
    r"\bcreate\s+table\s+(?:if\s+not\s+exists\s+)?(?:\"?public\"?\.)?\"?([a-z_][a-z0-9_]*)\"?", re.I)
_DROP_TABLE = re.compile(
    r"\bdrop\s+table\s+(?:if\s+exists\s+)?((?:(?:\"?[a-z_][a-z0-9_]*\"?\.)?\"?[a-z_][a-z0-9_]*\"?\s*,?\s*)+)",
    re.I)
_TRUNCATE = re.compile(
    r"\btruncate\s+(?:table\s+)?((?:(?:\"?[a-z_][a-z0-9_]*\"?\.)?\"?[a-z_][a-z0-9_]*\"?\s*,?\s*)+)", re.I)
_DELETE_ALL = re.compile(
    r"\bdelete\s+from\s+(?:\"?public\"?\.)?\"?([a-z_][a-z0-9_]*)\"?\s*(?:;|$)", re.I | re.M)
_DROP_SCHEMA = re.compile(r"\bdrop\s+schema\b", re.I)
_INSTALL = re.compile(r"\b(?:npm\s+(?:install|i|add)|pnpm\s+add|yarn\s+add|npx\s+expo\s+install)\b([^;&|]*)")
_SQL_COMMENT = re.compile(r"--[^\n]*|/\*.*?\*/", re.S)


def empty() -> dict:
    return {"ledger": {}, "unfinished": None}


def load(raw: dict | None) -> dict:
    mem = empty()
    if isinstance(raw, dict):
        mem["ledger"] = dict(raw.get("ledger") or {})
        mem["unfinished"] = raw.get("unfinished") or None
    return mem


# ------------------------------------------------------------------ ledger
def _add(ledger: dict, key: str, *values: str) -> None:
    items = list(ledger.get(key) or [])
    for v in values:
        if v and v not in items:
            items.append(v)
    ledger[key] = items[-200:]


def packages_in(command: str) -> list[str]:
    """Packages a successful install command added (none for a bare
    `npm install`, which only restores what package.json names)."""
    found = []
    for m in _INSTALL.finditer(command):
        for word in m.group(1).split():
            if word.startswith("-"):
                continue
            found.append(word)
    return found


def record(ledger: dict, name: str, args: dict, result: str) -> None:
    """Note what a tool call did outside the files, when it worked."""
    if result.startswith("error"):
        return
    if name == "apply_migration":
        _add(ledger, "migrations", str(args.get("name") or ""))
        sql = _SQL_COMMENT.sub(" ", str(args.get("sql") or ""))
        _add(ledger, "tables", *(t.lower() for t in _CREATE_TABLE.findall(sql)))
        dropped = set(_names(_DROP_TABLE, sql))
        if dropped:
            ledger["tables"] = [t for t in ledger.get("tables") or [] if t not in dropped]
    elif name == "set_secret":
        _add(ledger, "secrets", str(args.get("key") or ""))
    elif name == "deploy_edge_function":
        _add(ledger, "functions", str(args.get("name") or ""))
    elif name == "deploy_contract":
        _add(ledger, "contracts", str(args.get("name") or ""))
    elif name == "run_command" and result.startswith("[exit code 0]"):
        _add(ledger, "packages", *packages_in(str(args.get("command") or "")))


def _names(pattern: re.Pattern, sql: str) -> list[str]:
    out = []
    for group in pattern.findall(sql):
        for part in group.split(","):
            words = part.split()
            if not words:
                continue
            name = words[0].strip('"').split(".")[-1].strip('"').lower()
            if name and name not in ("cascade", "restrict"):
                out.append(name)
    return out


def foreign_drops(sql: str, ledger: dict, user_text: str) -> list[str]:
    """Tables a migration would drop or empty that this app did not create
    (in an earlier turn or in this same migration) and that the person did
    not name in their message. A database can hold other apps' tables."""
    clean = _SQL_COMMENT.sub(" ", sql)
    if _DROP_SCHEMA.search(clean):
        return ["a whole schema"]
    own = set(ledger.get("tables") or []) | {t.lower() for t in _CREATE_TABLE.findall(clean)}
    hit = _names(_DROP_TABLE, clean) + _names(_TRUNCATE, clean) + \
        [t.lower() for t in _DELETE_ALL.findall(clean)]
    asked = (user_text or "").lower()
    return sorted({t for t in hit if t not in own and t not in asked})


def ledger_block(ledger: dict, env: dict[str, str] | None = None) -> str:
    """The memory section of the system prompt."""
    lines = []
    labels = (("migrations", "Migrations applied"), ("tables", "Tables this app created"),
              ("secrets", "Edge function secrets set"), ("functions", "Edge functions deployed"),
              ("contracts", "Contracts deployed"), ("packages", "Packages installed"))
    for key, label in labels:
        if ledger.get(key):
            lines.append(f"- {label}: {', '.join(ledger[key])}")
    if env:
        lines.append("- Public values in .env (already set; no need to read .env): " +
                     ", ".join(f"{k}={v}" for k, v in sorted(env.items())))
    if not lines:
        return ""
    return ("## Project memory\nDone in earlier turns and still in place. Do not redo these; "
            "a secret or migration applied again changes nothing.\n" + "\n".join(lines))


# ------------------------------------------------------ the unfinished turn
def _result_cap() -> int:
    return settings.BUILDER_MEMORY_RESULT_CHARS


def _shorten(content: str, limit: int) -> str:
    if len(content) <= limit:
        return content
    return content[:limit] + "\n... (shortened)"


def _read_key(call: dict) -> str | None:
    fn = call.get("function") or {}
    if fn.get("name") != "read_file":
        return None
    try:
        args = json.loads(fn.get("arguments") or "{}")
    except ValueError:
        return None
    return json.dumps([args.get("path"), args.get("start_line"), args.get("end_line")])


def compact(messages: list[dict]) -> list[dict]:
    """A turn's tool conversation, small enough to hand on: a file read
    twice keeps only its last read, long results are shortened, and past
    the budget the oldest steps go first. Assistant tool calls and their
    results stay paired (a model API refuses one without the other)."""
    # Steps: an assistant message with tool calls and the results after it.
    steps: list[list[dict]] = []
    for m in messages:
        if m.get("role") == "assistant":
            steps.append([m])
        elif steps and m.get("role") == "tool":
            steps[-1].append(m)
        # Nudges and notes the loop added are not carried.
    # A step cut off mid-way (cancelled) has calls without results: dropped.
    steps = [s for s in steps
             if (s[0].get("tool_calls") or s[0].get("content"))
             and {c["id"] for c in s[0].get("tool_calls") or []} <= {m.get("tool_call_id") for m in s[1:]}]

    # The last read of each file (and range) wins; earlier ones point at it.
    last_read: dict[str, str] = {}
    for step in steps:
        for call in step[0].get("tool_calls") or []:
            key = _read_key(call)
            if key:
                last_read[key] = call["id"]
    out_steps = []
    for step in steps:
        calls = {c["id"]: c for c in step[0].get("tool_calls") or []}
        kept = [step[0]]
        for m in step[1:]:
            content = m.get("content") or ""
            call = calls.get(m.get("tool_call_id"))
            key = _read_key(call) if call else None
            if key and last_read.get(key) != m.get("tool_call_id"):
                content = "(read again later; see the later read)"
            else:
                content = _shorten(content, _result_cap())
            kept.append(dict(m, content=content))
        # Arguments of writes carry whole files; the file is in the sandbox.
        head = dict(step[0])
        if head.get("tool_calls"):
            head["tool_calls"] = [_slim_call(c) for c in head["tool_calls"]]
        kept[0] = head
        out_steps.append(kept)

    budget = settings.BUILDER_MEMORY_CARRY_CHARS
    size = lambda s: sum(len(json.dumps(m)) for m in s)                     # noqa: E731
    total = sum(size(s) for s in out_steps)
    while out_steps and total > budget:
        total -= size(out_steps.pop(0))
    return [m for s in out_steps for m in s]


def _slim_call(call: dict) -> dict:
    fn = call.get("function") or {}
    if fn.get("name") not in ("write_file", "deploy_edge_function", "apply_migration"):
        return call
    try:
        args = json.loads(fn.get("arguments") or "{}")
    except ValueError:
        return call
    for field in ("content", "code", "sql"):
        value = args.get(field)
        if isinstance(value, str) and len(value) > 1500:
            args[field] = value[:1500] + "\n... (shortened; it is in place)"
    return dict(call, function=dict(fn, arguments=json.dumps(args)))


def unfinished(reason: str, request: str, messages: list[dict]) -> dict:
    return {"reason": reason, "request": request[:2000], "messages": compact(messages),
            "stale": [], "at": datetime.now(timezone.utc).isoformat()}


_CONTINUE = re.compile(
    r"\b(c\w{0,3}ntin\w*|go on|go ahead|keep going|carry on|proceed|resume|finish\w*|"
    r"complete\w*|the rest|where you (?:left|stopped)|not done|still not|you stopped|do it|"
    r"try again|retry)\b", re.I)


def continues(text: str) -> bool:
    """Whether a message asks to carry on with the unfinished work ("continue",
    "cnontinue", "finish the fullstack thing") rather than something new."""
    t = (text or "").strip()
    return bool(t) and (len(t) <= 12 or bool(_CONTINUE.search(t[:300])))


#: Stands for "all of them" in `stale`: another version was restored.
EVERY_FILE = "every file (an earlier version was restored since)"


def mark_stale(mem: dict, paths: list[str]) -> None:
    """Files changed outside a turn (a hand edit): the carried reads of them
    are out of date."""
    left = mem.get("unfinished")
    if left:
        left["stale"] = sorted(set(left.get("stale") or []) | set(paths))


_REASONS = {"step_limit": "it ran out of steps", "typecheck_strikes": "the typecheck kept failing",
            "cancelled": "the person stopped it", "error": "the model failed",
            "no_changes": "it changed nothing"}


def carry_messages(left: dict) -> list[dict]:
    """The previous, unfinished turn, as messages placed before this turn's
    request: an opening note, its tool calls and results, a closing note."""
    msgs = list(left.get("messages") or [])
    if not msgs:
        return []
    why = _REASONS.get(left.get("reason"), left.get("reason") or "it stopped")
    opening = {"role": "user", "content": (
        f"[Your previous turn on this request stopped before it finished ({why}): "
        f"\"{left.get('request', '')[:300]}\". Its tool calls and results follow; they are "
        "the current state.]")}
    stale = left.get("stale") or []
    closing = ("[End of the previous turn. Carry on from exactly here (and if the message below "
               "asks for something else, do that, knowing all of this): do not re-read files, "
               "re-query tables or redo migrations, secrets, installs or functions shown above; "
               "go straight to what is left.")
    if stale:
        closing += f" These files were edited by hand since, so read them again first: {', '.join(stale)}."
    closing += "]"
    return [opening, *msgs, {"role": "user", "content": closing}]


# ------------------------------------------------------------- read guard
def digest(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()


def seen_reads(messages: list[dict]) -> dict[str, str]:
    """{read key: digest of what it returned} for full, unshortened reads in
    `messages` (a carried turn), so reading them again is answered short."""
    calls = {}
    for m in messages:
        for c in m.get("tool_calls") or []:
            key = _read_key(c)
            if key:
                calls[c["id"]] = key
    seen = {}
    for m in messages:
        key = calls.get(m.get("tool_call_id"))
        content = m.get("content") or ""
        if key and "(shortened)" not in content and not content.startswith("(read again later"):
            seen[key] = digest(content)
    return seen


def read_key(args: dict) -> str:
    return json.dumps([args.get("path"), args.get("start_line"), args.get("end_line")])


UNCHANGED = ("(unchanged since you read it earlier in this conversation; that content is above "
             "and still current. Use it instead of reading again.)")
