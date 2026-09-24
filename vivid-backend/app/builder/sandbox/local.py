"""The local driver: the template copied to a directory on this host, with
`npm run dev` as a child process.

For development and tests only. It is NOT isolated: a command the model runs
executes as the backend's own user. It exists so the loop can be built and
its pass criteria run without an E2B account, and so unit tests never touch
the network. Production uses the E2B driver.

State does not survive a backend restart: the child dies with the process
and the manager creates a fresh copy on the next request.
"""
import asyncio
import os
import shutil
import signal
import socket
import subprocess
import sys
import uuid
from pathlib import Path

from app.builder import targets as targets_mod
from app.builder.sandbox.base import DEV_LOG, RunResult, Sandbox, SandboxError, safe_path

#: Environment for every command: the caller's PATH so node is found, and
#: no colour codes in anything the model reads.
_ENV_BASE = {
    "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
    "HOME": os.environ.get("HOME", "/tmp"),
    "CI": "1", "NO_COLOR": "1", "FORCE_COLOR": "0",
    "npm_config_update_notifier": "false",
}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _copy_tree(src: Path, dst: Path) -> None:
    """Copy the template including node_modules. APFS clones are instant, so
    on macOS `cp -c` is used; elsewhere a plain recursive copy."""
    if sys.platform == "darwin":
        subprocess.run(["cp", "-Rc", str(src), str(dst)], check=True)
    else:
        shutil.copytree(src, dst, symlinks=True)


class LocalSandbox(Sandbox):
    driver = "local"

    def __init__(self, sandbox_id: str, root: Path, port: int,
                 proc: subprocess.Popen) -> None:
        self.id = sandbox_id
        self.root = str(root)
        self._root = root
        self._port = port
        self._proc = proc
        # DEV_LOG is a sandbox-internal path; here it maps into the project.
        self._log = root / ".vivid-dev.log"

    @classmethod
    async def create(cls, template_dir: str, base_dir: str, project_id: str,
                     target: targets_mod.Target | None = None) -> "LocalSandbox":
        target = target or targets_mod.get(targets_mod.WEB)
        template = Path(template_dir).resolve()
        if not (template / "package.json").exists():
            raise SandboxError(f"template not found at {template}")
        if not (template / "node_modules").exists():
            raise SandboxError(
                f"template at {template} has no node_modules; run `npm install` there once")
        sandbox_id = f"local_{uuid.uuid4().hex[:12]}"
        root = Path(base_dir) / f"{project_id}-{sandbox_id}"
        root.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(_copy_tree, template, root)
        await asyncio.to_thread(_git_init, root)
        port = _free_port()
        log = open(root / ".vivid-dev.log", "ab")
        env = {**_ENV_BASE, "PORT": str(port)}
        if target.is_mobile:
            # Expo CLI turns file watching (fast refresh) off when CI is set.
            env.pop("CI")
            env["EXPO_NO_TELEMETRY"] = "1"
        proc = subprocess.Popen(
            [arg.format(port=port) for arg in target.local_dev_cmd],
            cwd=root, stdout=log, stderr=subprocess.STDOUT,
            env=env, start_new_session=True)
        sandbox = cls(sandbox_id, root, port, proc)
        sandbox.target = target
        return sandbox

    # --------------------------------------------------------------- files
    def _abs(self, path: str) -> Path:
        return self._root / safe_path(path)

    async def read_file(self, path: str) -> str:
        target = self._abs(path)
        if not target.is_file():
            raise FileNotFoundError(path)
        return await asyncio.to_thread(target.read_text, "utf-8", "replace")

    async def write_file(self, path: str, content: str) -> None:
        target = self._abs(path)

        def _write() -> None:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        await asyncio.to_thread(_write)

    def _anywhere(self, path: str) -> Path:
        """Absolute sandbox paths map to the host as-is; relative ones are
        project paths. DEV_LOG lives at a project path here."""
        if path == DEV_LOG:
            return self._log
        return Path(path) if path.startswith("/") else self._abs(path)

    async def read_bytes(self, path: str) -> bytes:
        return await asyncio.to_thread(self._anywhere(path).read_bytes)

    async def write_bytes(self, path: str, data: bytes) -> None:
        target = self._anywhere(path)

        def _write() -> None:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        await asyncio.to_thread(_write)

    # ------------------------------------------------------------ commands
    async def run(self, cmd: str, timeout: float = 60,
                  env: dict[str, str] | None = None) -> RunResult:
        # The dev log lives at a project path here; commands that name the
        # sandbox-wide DEV_LOG get it rewritten so `tail` finds it.
        cmd = cmd.replace(DEV_LOG, str(self._log))
        proc = await asyncio.create_subprocess_exec(
            "bash", "-c", cmd, cwd=self.root, env={**_ENV_BASE, **(env or {})},
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            start_new_session=True)
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            out, err = await proc.communicate()
            return RunResult(124, out.decode(errors="replace"),
                             err.decode(errors="replace"), timed_out=True)
        return RunResult(proc.returncode or 0, out.decode(errors="replace"),
                         err.decode(errors="replace"))

    # ------------------------------------------------------------ lifetime
    def preview_url(self) -> str:
        return f"http://127.0.0.1:{self._port}"

    async def is_running(self) -> bool:
        return self._proc.poll() is None

    async def kill(self) -> None:
        if self._proc.poll() is None:
            try:
                os.killpg(self._proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(asyncio.to_thread(self._proc.wait), timeout=5)
            except asyncio.TimeoutError:
                os.killpg(self._proc.pid, signal.SIGKILL)
        await asyncio.to_thread(shutil.rmtree, self._root, True)


def _git_init(root: Path) -> None:
    """A fresh repository with the template as its first commit. The copy
    sits inside nothing (it is under /tmp), so `git init` is unambiguous."""
    env = {**_ENV_BASE, "GIT_AUTHOR_NAME": "Vivid", "GIT_AUTHOR_EMAIL": "builder@vivid",
           "GIT_COMMITTER_NAME": "Vivid", "GIT_COMMITTER_EMAIL": "builder@vivid"}
    if not (root / ".git").exists():
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, env=env, check=True)
        subprocess.run(["git", "add", "-A"], cwd=root, env=env, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "template"], cwd=root, env=env,
                       check=True)
