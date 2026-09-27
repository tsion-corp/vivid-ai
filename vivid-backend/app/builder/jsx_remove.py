"""Deleting an element the person clicked in the preview.

The preview carries no source locations (the editor names what it sees:
tag, id, classes, text, image src), so the element is found in the source
the way text edits are, by what it shows; the project's own TypeScript
parses the TSX so the cut is exact (scripts/remove-jsx.mjs, run in the
sandbox). The backend then writes the files and typechecks; a delete that
would break the build is undone and reported, never left half done.
"""
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.builder.sandbox.base import Sandbox, SandboxError

log = logging.getLogger("vivid.builder.jsx_remove")

SCRIPT = (Path(__file__).parent / "scripts" / "remove-jsx.mjs").read_text()
SCRIPT_PATH = ".vivid/remove-jsx.mjs"
REQUEST_PATH = ".vivid/delete-request.json"
#: Keeps the helper out of versions and published builds.
IGNORE_PATH = ".vivid/.gitignore"

APPLIED, NOT_FOUND, AMBIGUOUS, NOT_SIMPLE, WOULD_BREAK, NOT_SUPPORTED, ERROR = (
    "applied", "not_found", "ambiguous", "not_simple", "would_break", "not_supported", "error")

_TS_ERROR = re.compile(r"error TS\d+", re.I)


@dataclass
class Removal:
    status: str
    files: list[str] = field(default_factory=list)
    reason: str | None = None
    component: str | None = None
    count: int = 0
    #: Set when the item was an entry of data in the code (seed data, a
    #: list): the file it was in, and the texts it showed, which a page that
    #: keeps its data in the browser's storage still holds.
    data_file: str | None = None
    forget: list[str] = field(default_factory=list)


async def _ensure_script(sandbox: Sandbox) -> None:
    try:
        if await sandbox.read_file(SCRIPT_PATH) == SCRIPT:
            return
    except FileNotFoundError:
        pass
    await sandbox.write_file(SCRIPT_PATH, SCRIPT)
    await sandbox.write_file(IGNORE_PATH, "*\n")


async def find(sandbox: Sandbox, target: dict) -> dict:
    """The script's answer for `target` ({tag, id, classes, texts, src}):
    {status, files: {path: new content}, removed, reason}."""
    await _ensure_script(sandbox)
    await sandbox.write_file(REQUEST_PATH, json.dumps(target))
    result = await sandbox.run(f"node {SCRIPT_PATH} {REQUEST_PATH}", timeout=60)
    line = next((l for l in reversed(result.stdout.splitlines()) if l.strip().startswith("{")), "")
    try:
        return json.loads(line)
    except ValueError:
        log.warning("remove-jsx gave no answer: %s", result.output[-500:])
        return {"status": ERROR, "reason": "the code could not be read"}


def _errors(output: str) -> int:
    return len(_TS_ERROR.findall(output or ""))


async def remove(sandbox: Sandbox, target: dict) -> Removal:
    """Find it, cut it, typecheck. Files are written only when the result
    compiles as well as the project did before (a project that already had
    type errors is not held to a clean check, only to no new ones)."""
    answer = await find(sandbox, target)
    status = answer.get("status") or ERROR
    if status != APPLIED:
        return Removal(status, reason=answer.get("reason"), count=int(answer.get("count") or 0))
    files: dict[str, str] = answer.get("files") or {}
    if not files:
        return Removal(NOT_FOUND, reason="nothing to change")
    originals = {}
    for path in files:
        originals[path] = await sandbox.read_file(path)
    for path, content in files.items():
        await sandbox.write_file(path, content)

    check = await sandbox.run(sandbox.target.typecheck_cmd, timeout=180)
    if not check.ok:
        after = _errors(check.output)
        for path, content in originals.items():
            await sandbox.write_file(path, content)
        before_check = await sandbox.run(sandbox.target.typecheck_cmd, timeout=180)
        before = 0 if before_check.ok else _errors(before_check.output)
        if after > before:
            return Removal(WOULD_BREAK, reason="removing it would break the code")
        # The errors were there already: the delete itself is fine.
        for path, content in files.items():
            await sandbox.write_file(path, content)
    removed = answer.get("removed") or {}
    return Removal(APPLIED, files=sorted(files), component=removed.get("component"),
                   data_file=removed.get("file") if removed.get("data") else None,
                   forget=[str(v) for v in removed.get("values") or []][:6])


async def cleanup(sandbox: Sandbox) -> None:
    try:
        await sandbox.run(f"rm -f {REQUEST_PATH}", timeout=10)
    except SandboxError:
        pass
