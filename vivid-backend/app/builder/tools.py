"""The builder's six tools: declared for the model, executed in the sandbox.

Every result is a string the model reads, capped at
BUILDER_TOOL_RESULT_CHARS. A failure is an "error: ..." observation, never an
exception, because the model recovers from a described failure and stalls on
a missing result. `write_file` and `edit_file` run the TypeScript checker
afterwards and put its first lines in the result, so the model sees the
breakage next to the edit that caused it.
"""
import json
import re
from dataclasses import dataclass

from app.builder.sandbox.base import PathError, Sandbox, SandboxError, safe_path
from app.builder import chain as chain_mod, targets
from app.builder.chain import Chain
from app.builder.images import ImageError, ImageMaker
from app.builder.supabase import Management, SupabaseError
from app.core.config import settings


def _fn(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {"type": "function",
            "function": {"name": name, "description": description,
                         "parameters": {"type": "object", "properties": properties,
                                        "required": required}}}


SCHEMAS: list[dict] = [
    _fn("read_file",
        "Read a project file. Returns its exact contents. Read a file before "
        "editing it: edit_file matches text exactly as read_file returned it. "
        "Long files: pass start_line and end_line to read a range.",
        {"path": {"type": "string", "description": "Project-relative path, e.g. src/App.tsx"},
         "start_line": {"type": "integer", "description": "1-based first line (optional)."},
         "end_line": {"type": "integer", "description": "1-based last line, inclusive (optional)."}},
        ["path"]),
    _fn("write_file",
        "Create a file or replace it entirely. For a change to part of an "
        "existing file use edit_file instead. Runs the typecheck afterwards "
        "and returns any errors.",
        {"path": {"type": "string", "description": "Project-relative path."},
         "content": {"type": "string", "description": "The complete file contents."}},
        ["path", "content"]),
    _fn("edit_file",
        "Replace one exact occurrence of old_string with new_string in a file. "
        "old_string must match the file EXACTLY once, including whitespace; "
        "include a few surrounding lines to make it unique. Runs the typecheck "
        "afterwards and returns any errors.",
        {"path": {"type": "string", "description": "Project-relative path."},
         "old_string": {"type": "string", "description": "Exact text to replace."},
         "new_string": {"type": "string", "description": "Replacement text."}},
        ["path", "old_string", "new_string"]),
    _fn("list_files",
        "List every source file in the project (node_modules and build output "
        "excluded). Optionally only those under a directory.",
        {"path": {"type": "string", "description": "Directory to list, e.g. src/components (optional)."}},
        []),
    _fn("run_command",
        "Run a shell command in the project root and return its output. Use it "
        "for `npm install <package>`, one-off scripts, or `npx tsc --noEmit`. "
        "Commands are killed after 60 seconds; do not start servers with it "
        "(the dev server is already running).",
        {"command": {"type": "string", "description": "The command line."}},
        ["command"]),
    _fn("get_dev_server_logs",
        "The last lines of the Vite dev server's output. Read this when the "
        "preview is blank or shows an error overlay.",
        {"lines": {"type": "integer", "description": "How many lines, default 100."}},
        []),
]

#: Offered only when the project has a Supabase backend linked (the user's
#: own, or Vivid Cloud). They act through the Management API with the
#: backend's token; the model never sees a key.
SUPABASE_SCHEMAS: list[dict] = [
    _fn("apply_migration",
        "Run SQL against the project's Postgres database and record it as a "
        "migration. Use it for tables, columns, indexes, policies and functions. "
        "Every table needs row level security enabled and policies. One "
        "migration per change, with a short snake_case name.",
        {"name": {"type": "string", "description": "e.g. create_bookings"},
         "sql": {"type": "string", "description": "The SQL to run."}},
        ["name", "sql"]),
    _fn("query_database",
        "Run one read-only SQL query (select only) against the project's database "
        "and see up to 50 rows. For checking data, schema or an account; never "
        "for changes, which go through apply_migration.",
        {"sql": {"type": "string", "description": "A single SELECT."}},
        ["sql"]),
    _fn("deploy_edge_function",
        "Deploy a Supabase Edge Function (Deno, TypeScript) under the given "
        "name; the code is index.ts and must export a Deno.serve handler. "
        "Reads secrets with Deno.env.get. Returns the function's URL.",
        {"name": {"type": "string", "description": "URL slug, e.g. send-receipt"},
         "code": {"type": "string", "description": "Full contents of index.ts."},
         "verify_jwt": {"type": "boolean",
                        "description": "Require a signed-in user (default true)."}},
        ["name", "code"]),
    _fn("set_secret",
        "Store a secret for edge functions (an API key for a third party). "
        "Never put the value in code; the function reads it with Deno.env.get.",
        {"key": {"type": "string", "description": "UPPER_SNAKE_CASE name."},
         "value": {"type": "string"}},
        ["key", "value"]),
]

#: Offered when the project is on-chain (a deployer wallet exists).
CHAIN_SCHEMAS: list[dict] = [
    _fn("deploy_contract",
        "Compile one Solidity contract and deploy it to the project's chain from the "
        "project's deployer wallet. Writes contracts/<Name>.sol, the artifact, and "
        "src/lib/contracts/<Name>.ts (address + ABI as const) for the app to import. "
        "OpenZeppelin imports (@openzeppelin/contracts/...) are available. Returns the "
        "address and explorer link. Redeploying gives a new address.",
        {"name": {"type": "string", "description": "The contract name inside the source."},
         "source": {"type": "string", "description": "Full Solidity source (pragma ^0.8.20)."},
         "constructor_args": {"type": "array", "items": {},
                              "description": "Constructor arguments in order (numbers as strings for wei)."}},
        ["name", "source"]),
    _fn("chain_faucet",
        "Ask the devnet faucet to fund the project's deployer wallet with test tokens. "
        "Call it once before the first deployment, or when a deployment says the "
        "deployer has no balance.",
        {}, []),
]

#: Offered when the image model is configured. Makes a picture and puts it
#: in public/uploads like an upload, so the app can use it by path.
IMAGE_SCHEMAS: list[dict] = [
    _fn("generate_image",
        "Create an image for the app when the user has not uploaded one. kind=photo: a "
        "studio product shot (describe the item exactly). kind=lifestyle: one dramatic "
        "editorial shot for a hero. kind=logo: a flat symbol mark with no text, to sit "
        "beside the brand name set in type (describe the symbol, e.g. 'a lightning bolt "
        "inside a circle', and the colours). kind=illustration: flat artwork. The style "
        "is added for you. The file lands at /uploads/<name> and is returned as a path.",
        {"prompt": {"type": "string", "description": "What the picture shows."},
         "name": {"type": "string",
                  "description": "File name without extension, e.g. air-zoom-red."},
         "aspect": {"type": "string", "enum": ["square", "landscape", "wide", "portrait"],
                    "description": "square for products, wide for heroes (default square)."},
         "kind": {"type": "string", "enum": ["photo", "lifestyle", "logo", "illustration"],
                  "description": "Default photo."}},
        ["prompt", "name"]),
]

NAMES = {s["function"]["name"] for s in SCHEMAS}
CHAIN_NAMES = {s["function"]["name"] for s in CHAIN_SCHEMAS}
SUPABASE_NAMES = {s["function"]["name"] for s in SUPABASE_SCHEMAS}
IMAGE_NAMES = {s["function"]["name"] for s in IMAGE_SCHEMAS}
_IMAGE_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,60}$")

_SLUG = re.compile(r"^[a-z][a-z0-9-]{1,62}$")
_SECRET_NAME = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")
_MIGRATION_NAME = re.compile(r"^[a-z][a-z0-9_]{1,62}$")


@dataclass
class Backend:
    """The Supabase project a turn may act on. With a Management API token
    every tool works; with only a database connection string, migrations
    run over Postgres and the function and secret tools are withheld.
    Built by the route, never by the model."""
    ref: str
    token: str | None = None
    database_url: str | None = None

    @property
    def can_functions(self) -> bool:
        return bool(self.token)

    @property
    def api(self) -> Management:
        if not self.token:
            raise RuntimeError("no management token for this backend")
        return Management(self.token)


FUNCTION_TOOLS = {"deploy_edge_function", "set_secret"}


def schemas_for(backend: "Backend | None", images: "ImageMaker | None" = None,
                chain: "Chain | None" = None) -> list[dict]:
    out = list(SCHEMAS)
    if images is not None:
        out += IMAGE_SCHEMAS
    if chain is not None:
        out += CHAIN_SCHEMAS
    if backend is not None:
        out += [s for s in SUPABASE_SCHEMAS
                if backend.can_functions or s["function"]["name"] not in FUNCTION_TOOLS]
    return out

#: Commands the model may not run, whatever it says it is doing. Matched
#: against the whole command line. Package installs, scripts and checks are
#: allowed; leaving the project, escalating, or publishing are not.
BLOCKED = [
    (re.compile(r"\brm\s+(-[a-z]*\s+)*[\"']?(/|~|\.\.|\*)"), "deleting outside the project"),
    (re.compile(r"\bsudo\b|\bsu\b\s"), "privilege escalation"),
    (re.compile(r"\b(curl|wget)\b.*\|\s*(ba)?sh\b"), "piping a download into a shell"),
    (re.compile(r"\bgit\s+push\b|\bnpm\s+publish\b|\bnpx\s+vercel\b|\bnpx\s+wrangler\b"),
     "publishing from the sandbox"),
    (re.compile(r"\bnpm\s+(install|i|add)\b.*\s(-g|--global)\b"), "global installs"),
    (re.compile(r"\b(shutdown|reboot|halt|poweroff|mkfs|dd)\b"), "system commands"),
    (re.compile(r"\bkill(all)?\b|\bpkill\b"), "killing processes (the dev server lives here)"),
    (re.compile(r"\bnpm\s+run\s+dev\b|\bvite\s*$|\bvite\s+--"), "starting a second dev server"),
    (re.compile(r"(^|[;&|]\s*)cd\s+(/|~|\.\.)"), "leaving the project root"),
    (re.compile(r"\benv\b\s*$|\bprintenv\b|\$\{?E2B|/proc/"), "reading the environment"),
]

_TS_ERROR = re.compile(r"error TS\d+")

#: Third-party native modules that ship inside Expo Go. Anything named
#: expo-* or @expo/* is part of the SDK; other react-native packages carry
#: native code Expo Go does not have, and the app would crash on the phone.
EXPO_GO_NATIVE = frozenset({
    "react-native", "react-native-web", "react-dom",
    "react-native-reanimated", "react-native-gesture-handler", "react-native-screens",
    "react-native-safe-area-context", "react-native-svg", "react-native-maps",
    "react-native-webview", "react-native-pager-view", "react-native-view-shot",
    "react-native-worklets", "react-native-edge-to-edge", "react-native-keyboard-controller",
    "@react-native-async-storage/async-storage", "@react-native-community/datetimepicker",
    "@react-native-community/slider", "@react-native-community/netinfo",
    "@react-native-picker/picker", "@react-native-masked-view/masked-view",
    "@shopify/flash-list", "@shopify/react-native-skia", "lottie-react-native",
    "@stripe/stripe-react-native", "react-native-get-random-values", "react-native-url-polyfill",
    "nativewind", "react-native-css-interop",
})
#: react-native-* packages that are only JavaScript (on top of modules above).
PURE_JS_RN = frozenset({
    "react-native-qrcode-svg", "react-native-markdown-display", "react-native-calendars",
    "react-native-toast-message", "react-native-element-dropdown", "react-native-modal",
    "react-native-gifted-charts", "react-native-animatable", "react-native-render-html",
    "react-native-swiper", "react-native-country-codes-picker", "react-native-otp-entry",
    "react-native-confirmation-code-field", "react-native-uuid", "react-native-paper",
})
_NATIVE_HINT = re.compile(r"^(react-native-|@react-native|@react-native-community/|rn-)|"
                          r"(-react-native|-native)$")
_EXPO_INSTALL = re.compile(r"\bexpo\s+install\b(?P<args>[^;&|]*)")


def _package_name(spec: str) -> str:
    """`@scope/name@1.2` and `name@^3` without the version."""
    if spec.startswith("@"):
        scope, _, rest = spec[1:].partition("/")
        return "@" + scope + "/" + rest.split("@", 1)[0]
    return spec.split("@", 1)[0]


def expo_go_problem(command: str) -> str | None:
    """Why an `expo install` would add a package Expo Go cannot run, or
    None. Pure JavaScript packages pass; so does the Expo SDK."""
    refused = []
    for m in _EXPO_INSTALL.finditer(command):
        for spec in m.group("args").split():
            if spec.startswith("-"):
                continue
            name = _package_name(spec)
            if (name.startswith(("expo-", "@expo/")) or name == "expo"
                    or name in EXPO_GO_NATIVE or name in PURE_JS_RN):
                continue
            if _NATIVE_HINT.search(name.split("/")[-1]) or name.startswith("@react-native"):
                refused.append(name)
    if not refused:
        return None
    return (f"{', '.join(refused)} has native code that Expo Go does not include, so the app "
            "would crash on the user's phone. Use an Expo SDK module or a pure JavaScript "
            "package instead (see the mobile skill's device features table); if nothing "
            "fits, build without it and tell the user in one sentence what a later native "
            "build would add.")


@dataclass
class Outcome:
    text: str
    #: The tool ran the typecheck, and whether it passed. None when the tool
    #: does not typecheck (reads, listings, commands).
    typecheck_ok: bool | None = None
    #: The file this tool changed, if any.
    touched: str | None = None


def truncate(text: str, limit: int | None = None) -> str:
    limit = limit or settings.BUILDER_TOOL_RESULT_CHARS
    if len(text) <= limit:
        return text
    return (text[:limit] +
            f"\n[truncated: {len(text) - limit} more characters. "
            "Read a smaller range or narrow the command.]")


async def execute(name: str, args: dict, sandbox: Sandbox,
                  backend: Backend | None = None,
                  images: ImageMaker | None = None,
                  typecheck_now: bool = True,
                  chain: Chain | None = None) -> Outcome:
    """Run one tool. Never raises for a problem the model can act on.

    `typecheck_now=False` makes write_file and edit_file skip their own
    typecheck; the loop then runs one check for the whole step and attaches
    the report to the last write. Same information, one tsc instead of
    one per file."""
    if name in IMAGE_NAMES:
        if images is None:
            return Outcome("error: image generation is not available on this deployment; "
                           "use a gradient block with the item's initial instead.")
        try:
            outcome = await _generate_image(args, images)
        except ImageError as e:
            outcome = Outcome(f"error: {e}")
        outcome.text = truncate(outcome.text) or "(no output)"
        return outcome
    if name in CHAIN_NAMES:
        if chain is None:
            return Outcome(f"error: {name} needs the project to be on-chain (chain enabled in settings).")
        outcome = await _CHAIN_HANDLERS[name](args, sandbox, chain)
        outcome.text = truncate(outcome.text) or "(no output)"
        return outcome
    if name in SUPABASE_NAMES:
        if backend is None:
            return Outcome(f"error: {name} needs a Supabase backend linked to this project.")
        if name in FUNCTION_TOOLS and not backend.can_functions:
            return Outcome(f"error: {name} needs the user's Supabase account connected; write "
                           "the function as a file under supabase/functions/ instead and "
                           "tell the user to deploy it.")
        try:
            outcome = await _SUPABASE_HANDLERS[name](args, backend)
        except SupabaseError as e:
            outcome = Outcome(f"error: Supabase refused: {e.public}")
        outcome.text = truncate(outcome.text) or "(no output)"
        return outcome
    if name not in NAMES:
        return Outcome(f"error: no tool named {name!r}. Tools: "
                       f"{', '.join(sorted(NAMES | (SUPABASE_NAMES if backend else set())))}.")
    handler = _HANDLERS[name]
    try:
        if name in ("write_file", "edit_file") and not typecheck_now:
            outcome = await handler(args, sandbox, typecheck_now=False)
        else:
            outcome = await handler(args, sandbox)
    except PathError as e:
        outcome = Outcome(f"error: {e}")
    except FileNotFoundError as e:
        outcome = Outcome(f"error: no such file: {e}")
    except SandboxError as e:
        outcome = Outcome(f"error: the sandbox failed: {e}")
    outcome.text = truncate(outcome.text) or "(no output)"
    return outcome


async def _generate_image(args: dict, images: ImageMaker) -> Outcome:
    prompt = str(args.get("prompt") or "").strip()
    name = str(args.get("name") or "").strip().lower()
    if len(prompt) < 8:
        return Outcome("error: describe the picture in a sentence")
    if not _IMAGE_NAME.match(name):
        return Outcome("error: name must be a lowercase slug like air-zoom-red")
    out = await images.make(prompt, name, str(args.get("aspect") or "square"),
                            kind=str(args.get("kind") or "photo"))
    dims = out["meta"].get("width")
    size = f"{out['meta']['width']}x{out['meta']['height']}, " if dims else ""
    if images.sandbox.target.is_mobile:
        use = (f"Use it as <Image source={{require(\"@/{out['path']}\")}} ...> (expo-image) "
               f"with a fixed aspect ratio.")
        if args.get("kind") == "logo":
            use += " It is also the app icon now (assets/icon.png)."
    else:
        use = f"Use it as <img src=\"{out['path']}\" ...> with a fixed aspect ratio."
    return Outcome(f"Image ready at {out['path']} ({size}{out['bytes'] // 1024} KB). "
                   f"{use} {images.left} more this turn.", touched=None)


# ---------------------------------------------------- supabase handlers
async def _apply_migration(args: dict, backend: Backend) -> Outcome:
    name = str(args.get("name") or "").strip()
    sql = str(args.get("sql") or "").strip()
    if not sql:
        return Outcome("error: sql is required")
    if not _MIGRATION_NAME.match(name):
        return Outcome("error: name must be short snake_case, e.g. create_bookings")
    if backend.token:
        await backend.api.apply_migration(backend.ref, sql, name)
    else:
        from app.builder import pgdirect
        try:
            await pgdirect.apply_migration(backend.database_url, sql, name)
        except pgdirect.DirectError as e:
            return Outcome(f"error: migration {name} failed: {e}")
    return Outcome(f"Migration {name} applied.")


_SELECT = re.compile(r"^\s*(with\b[\s\S]*?\bselect\b|select\b)", re.I)
_UNSAFE = re.compile(r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke)\b", re.I)


def _rows_text(rows: list[dict]) -> str:
    if not rows:
        return "No rows."
    cols = list(rows[0].keys())
    lines = [" | ".join(cols)]
    for r in rows[:50]:
        lines.append(" | ".join(str(r.get(c)) for c in cols))
    more = f"\n... {len(rows) - 50} more rows" if len(rows) > 50 else ""
    return "\n".join(lines) + more


async def _query_database(args: dict, backend: Backend) -> Outcome:
    sql = str(args.get("sql") or "").strip().rstrip(";")
    if not sql or not _SELECT.match(sql) or _UNSAFE.search(sql) or ";" in sql:
        return Outcome("error: query_database takes one SELECT; changes go through apply_migration")
    try:
        if backend.token:
            rows = await backend.api.query(backend.ref, sql, read_only=True) or []
        else:
            from app.builder import pgdirect
            rows = await pgdirect.query(backend.database_url, sql)
    except Exception as e:                                     # the text is for the model
        from app.builder import pgdirect
        return Outcome(f"error: query failed: {pgdirect.clean_error(e)}")
    return Outcome(truncate(_rows_text(list(rows))))


async def _deploy_edge_function(args: dict, backend: Backend) -> Outcome:
    slug = str(args.get("name") or "").strip()
    code = args.get("code")
    if not _SLUG.match(slug):
        return Outcome("error: name must be a lowercase slug like send-receipt")
    if not isinstance(code, str) or "serve" not in code:
        return Outcome("error: code must be the full index.ts with a Deno.serve handler")
    out = await backend.api.deploy_function(backend.ref, slug, code,
                                            verify_jwt=bool(args.get("verify_jwt", True)))
    return Outcome(f"Deployed {slug} (version {out.get('version', '?')}). "
                   f"URL: {out['url']}\nCall it from the app with "
                   f"supabase.functions.invoke('{slug}', {{ body }}).")


async def _set_secret(args: dict, backend: Backend) -> Outcome:
    key = str(args.get("key") or "").strip()
    value = args.get("value")
    if not _SECRET_NAME.match(key):
        return Outcome("error: key must be UPPER_SNAKE_CASE")
    if not isinstance(value, str) or not value:
        return Outcome("error: value is required")
    await backend.api.set_secrets(backend.ref, {key: value})
    # The value is never echoed: not to the model, not to the thread.
    return Outcome(f"Secret {key} set for edge functions.")


# ------------------------------------------------------- chain handlers
async def _ensure_chain_tooling(sandbox: Sandbox) -> str | None:
    """solc, viem and OpenZeppelin in node_modules, and the deploy script
    on disk. Returns an error string when the install fails."""
    check = await sandbox.run("test -d node_modules/solc && test -d node_modules/viem "
                              "&& test -d node_modules/@openzeppelin/contracts", timeout=15)
    if not check.ok:
        inst = await sandbox.run(f"npm install --no-audit --no-fund {chain_mod.PACKAGES} 2>&1 | tail -3",
                                 timeout=settings.BUILDER_INSTALL_TIMEOUT)
        if not inst.ok:
            return f"error: could not install the chain tooling: {inst.output[-300:]}"
    try:
        current = await sandbox.read_file(chain_mod.SCRIPT_PATH)
    except FileNotFoundError:
        current = None
    if current != chain_mod.DEPLOY_SCRIPT:
        await sandbox.write_file(chain_mod.SCRIPT_PATH, chain_mod.DEPLOY_SCRIPT)
    return None


async def _deploy_contract(args: dict, sandbox: Sandbox, chain: Chain) -> Outcome:
    name = str(args.get("name") or "").strip()
    source = args.get("source")
    if not chain_mod.valid_name(name):
        return Outcome("error: name must be the contract's name, CapitalCase, e.g. Marketplace")
    if not isinstance(source, str) or "contract " not in source:
        return Outcome("error: source must be the full Solidity file containing the contract")
    if f"contract {name}" not in source:
        return Outcome(f"error: the source has no `contract {name}`")
    ctor = args.get("constructor_args") or []
    if not isinstance(ctor, list):
        return Outcome("error: constructor_args must be a JSON array")
    problem = await _ensure_chain_tooling(sandbox)
    if problem:
        return Outcome(problem)
    spec = chain.spec
    file = f"contracts/{name}.sol"
    await sandbox.write_file(file, source)
    await sandbox.write_bytes(chain_mod.KEY_FILE, chain.deployer_key.encode())
    try:
        result = await sandbox.run(chain_mod.deploy_command(spec, file, name, json.dumps(ctor)),
                                   timeout=240)
    finally:
        await sandbox.run(f"rm -f {chain_mod.KEY_FILE}", timeout=10)
    line = next((ln for ln in reversed(result.stdout.splitlines()) if ln.startswith("{")), "")
    try:
        out = json.loads(line)
    except ValueError:
        return Outcome(f"error: the deploy script failed: {result.output[-400:]}")
    if not out.get("ok"):
        return Outcome("error: " + "\n".join(out.get("errors") or ["unknown failure"]))
    note = await chain_mod.verify(spec, out["address"], name, source)
    link = chain_mod.explorer_link(spec, "address", out["address"])
    text = (f"Deployed {name} at {out['address']} on {spec['name']} (tx {out['tx']}, block "
            f"{out['block']}, gas {out['gasUsed']}). Explorer: {link}\n"
            f"Import it: `import {{ {name}Address, {name}Abi }} from \"@/lib/contracts/{name}\"`. "
            f"Deployer balance: {out['balance']} {spec['symbol']}."
            + (f" {note}" if note else ""))
    return Outcome(text, touched=f"src/lib/contracts/{name}.ts")


async def _chain_faucet(args: dict, sandbox: Sandbox, chain: Chain) -> Outcome:
    spec = chain.spec
    try:
        got = await chain_mod.fund(spec, chain.deployer_address)
    except ValueError as e:
        return Outcome(f"error: the faucet refused: {e}")
    return Outcome(f"Faucet sent {got.get('amount')} {spec['symbol']} to the deployer "
                   f"{chain.deployer_address} (tx {got.get('tx')}). It lands within a few seconds.")


_CHAIN_HANDLERS = {"deploy_contract": _deploy_contract, "chain_faucet": _chain_faucet}


_SUPABASE_HANDLERS = {
    "apply_migration": _apply_migration,
    "query_database": _query_database,
    "deploy_edge_function": _deploy_edge_function,
    "set_secret": _set_secret,
}


# ------------------------------------------------------------- handlers
async def _read_file(args: dict, sandbox: Sandbox) -> Outcome:
    path = safe_path(str(args.get("path", "")))
    content = await sandbox.read_file(path)
    start, end = args.get("start_line"), args.get("end_line")
    if start or end:
        lines = content.splitlines(keepends=True)
        first = max(int(start or 1), 1)
        last = min(int(end or len(lines)), len(lines))
        content = "".join(lines[first - 1:last])
        return Outcome(f"[{path} lines {first}-{last} of {len(lines)}]\n{content}")
    return Outcome(content)


async def _write_file(args: dict, sandbox: Sandbox, typecheck_now: bool = True) -> Outcome:
    path = safe_path(str(args.get("path", "")))
    content = args.get("content")
    if not isinstance(content, str):
        return Outcome("error: content must be a string")
    await sandbox.write_file(path, content)
    if not typecheck_now:
        return Outcome(f"Wrote {path} ({len(content)} chars).", touched=path)
    ok, report = await typecheck(sandbox)
    return Outcome(f"Wrote {path} ({len(content)} chars).\n{report}",
                   typecheck_ok=ok, touched=path)


async def _edit_file(args: dict, sandbox: Sandbox, typecheck_now: bool = True) -> Outcome:
    path = safe_path(str(args.get("path", "")))
    old, new = args.get("old_string"), args.get("new_string")
    if not isinstance(old, str) or not isinstance(new, str):
        return Outcome("error: old_string and new_string must be strings")
    if not old:
        return Outcome("error: old_string is empty; use write_file to create a file")
    content = await sandbox.read_file(path)
    count = content.count(old)
    if count == 0:
        return Outcome(f"error: old_string was not found in {path}. Read the file "
                       "again and copy the text exactly, including indentation.")
    if count > 1:
        return Outcome(f"error: old_string matches {count} places in {path}; include "
                       "more surrounding lines so it matches exactly once.")
    await sandbox.write_file(path, content.replace(old, new, 1))
    if not typecheck_now:
        return Outcome(f"Edited {path}.", touched=path)
    ok, report = await typecheck(sandbox)
    return Outcome(f"Edited {path}.\n{report}", typecheck_ok=ok, touched=path)


async def _list_files(args: dict, sandbox: Sandbox) -> Outcome:
    files = await sandbox.list_files()
    prefix = str(args.get("path") or "").strip().strip("/")
    if prefix:
        prefix = safe_path(prefix) + "/"
        files = [f for f in files if f.startswith(prefix)]
        if not files:
            return Outcome(f"(no files under {prefix})")
    return Outcome("\n".join(files))


async def _run_command(args: dict, sandbox: Sandbox) -> Outcome:
    command = str(args.get("command") or "").strip()
    if not command:
        return Outcome("error: command is required")
    reason = blocked_reason(command, sandbox.target)
    if reason:
        return Outcome(f"error: that command is not allowed here ({reason}).")
    if sandbox.target.is_mobile:
        problem = expo_go_problem(command)
        if problem:
            return Outcome(f"error: {problem}")
    result = await sandbox.run(command, timeout=settings.BUILDER_COMMAND_TIMEOUT)
    head = (f"[timed out after {settings.BUILDER_COMMAND_TIMEOUT}s]" if result.timed_out
            else f"[exit code {result.exit_code}]")
    return Outcome(f"{head}\n{result.output}".strip())


async def _dev_server_logs(args: dict, sandbox: Sandbox) -> Outcome:
    lines = int(args.get("lines") or 100)
    text = await sandbox.dev_server_logs(max(1, min(lines, 500)))
    return Outcome(text.strip() or "(the dev server has printed nothing yet)")


_HANDLERS = {
    "read_file": _read_file,
    "write_file": _write_file,
    "edit_file": _edit_file,
    "list_files": _list_files,
    "run_command": _run_command,
    "get_dev_server_logs": _dev_server_logs,
}


def blocked_reason(command: str, target: "targets.Target | None" = None) -> str | None:
    extra = target.blocked if target is not None else ()
    for pattern, reason in (*BLOCKED, *extra):
        if pattern.search(command):
            return reason
    return None


async def typecheck(sandbox: Sandbox) -> tuple[bool, str]:
    """`tsc --noEmit` over the app. Returns (passed, report) where the report
    is the first BUILDER_TYPECHECK_ERROR_LINES error lines, or one word."""
    result = await sandbox.run(sandbox.target.typecheck_cmd,
                               timeout=settings.BUILDER_TYPECHECK_TIMEOUT)
    if result.timed_out:
        return False, "Typecheck: timed out."
    if result.ok:
        return True, "Typecheck: clean."
    lines = [ln for ln in result.output.splitlines() if _TS_ERROR.search(ln)]
    if not lines:
        lines = result.output.splitlines()
    limit = settings.BUILDER_TYPECHECK_ERROR_LINES
    shown = lines[:limit]
    more = f"\n... {len(lines) - limit} more" if len(lines) > limit else ""
    return False, "Typecheck: FAILED\n" + "\n".join(shown) + more
