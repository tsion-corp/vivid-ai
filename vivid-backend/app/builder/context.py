"""What the model is shown about the project at the start of a turn.

The file tree, the three files every app has, and whatever the last two
turns touched, in that priority, within BUILDER_CONTEXT_CHARS. Everything
else it reads with read_file. Keeping this small is what keeps a twenty-step
turn cheap: the whole block is resent on every step.
"""
from app.builder.sandbox.base import Sandbox, SandboxError
from app.core.config import settings

#: The web target's; each sandbox's target names its own (targets.py).
KEY_FILES = ("src/App.tsx", "src/main.tsx", "package.json")

#: The tree is capped separately so a project with hundreds of files still
#: leaves room for the files themselves.
_TREE_SHARE = 0.25


async def build(sandbox: Sandbox, recent: list[str]) -> str:
    budget = settings.BUILDER_CONTEXT_CHARS
    try:
        files = await sandbox.list_files()
    except SandboxError as e:
        return f"(file tree unavailable: {e})"

    tree = "\n".join(files)
    tree_cap = int(budget * _TREE_SHARE)
    if len(tree) > tree_cap:
        tree = tree[:tree_cap].rsplit("\n", 1)[0] + f"\n... ({len(files)} files; use list_files)"
    out = [f"## Files\n{tree}"]
    used = len(out[0])

    key_files = sandbox.target.key_files
    wanted: list[str] = []
    for path in list(key_files) + [p for p in recent if p not in key_files]:
        if path in files and path not in wanted:
            wanted.append(path)

    for path in wanted:
        if used >= budget:
            break
        try:
            content = await sandbox.read_file(path)
        except (FileNotFoundError, SandboxError):
            continue
        block = f"\n\n## {path}\n```\n{content}\n```"
        room = budget - used
        if len(block) > room:
            block = block[:max(room - 40, 0)] + "\n... (truncated; read_file for the rest)\n```"
        out.append(block)
        used += len(block)
    return "".join(out)
