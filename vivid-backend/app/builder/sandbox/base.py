"""What the builder needs from wherever the user's app runs.

A sandbox holds one project checkout at `root`, with node_modules installed
and the Vite dev server listening on the dev port. The builder reads and
writes files under root, runs commands there, and hands the preview URL to
the client. Nothing above this interface knows whether that is an E2B
microVM or a directory on the developer's laptop.

Rules every driver keeps:
  - paths are project-relative; `safe_path` rejects anything that escapes
  - `run` never raises for a failing command: the exit code comes back and
    the model reads it as an observation
  - the dev server's output goes to DEV_LOG so `dev_server_logs` is one tail
"""
import posixpath
from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.builder import targets


class SandboxError(Exception):
    """The sandbox itself failed (unreachable, dead, refused). A command that
    merely exited non-zero is a RunResult, not this."""


class PathError(ValueError):
    """A project-relative path that is not one."""


#: Where the dev server writes, inside the sandbox.
DEV_LOG = "/tmp/vivid-dev.log"

#: Never listed, never read into context.
IGNORED_DIRS = ("node_modules", ".git", "dist", ".vite")


@dataclass
class RunResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    @property
    def output(self) -> str:
        parts = [self.stdout.rstrip(), self.stderr.rstrip()]
        return "\n".join(p for p in parts if p)


def safe_path(path: str) -> str:
    """A normalised project-relative path, or PathError.

    Absolute paths, `..` segments and an empty result are refused. The
    model gets the error as a tool result and corrects itself; the file
    system outside the project is never touched.
    """
    raw = (path or "").strip().replace("\\", "/")
    if not raw:
        raise PathError("path is required")
    if raw.startswith("/") or raw.startswith("~"):
        raise PathError(f"{raw!r} is absolute; give a path relative to the project root")
    norm = posixpath.normpath(raw)
    if norm == "." or norm.startswith("../") or norm == "..":
        raise PathError(f"{raw!r} escapes the project root")
    if any(part in IGNORED_DIRS for part in norm.split("/")[:1]):
        raise PathError(f"{norm!r} is not part of the project source")
    return norm


class Sandbox(ABC):
    """One running project. Drivers implement the primitives; the shared
    behaviour (listing through git, tailing the dev log) lives here."""

    #: Stable identifier the manager stores to reconnect later.
    id: str
    #: Absolute project root inside the sandbox.
    root: str
    #: "e2b" or "local".
    driver: str
    #: What the sandbox was made from; tools, typecheck and screenshots read
    #: it. Web unless the driver was given another target.
    target: targets.Target = targets.get(targets.WEB)

    @abstractmethod
    async def read_file(self, path: str) -> str: ...

    @abstractmethod
    async def write_file(self, path: str, content: str) -> None: ...

    @abstractmethod
    async def read_bytes(self, path: str) -> bytes:
        """Raw contents of a file anywhere in the sandbox (absolute path
        allowed): used for the snapshot tarball, never by a tool."""

    @abstractmethod
    async def write_bytes(self, path: str, data: bytes) -> None: ...

    @abstractmethod
    async def run(self, cmd: str, timeout: float = 60,
                  env: dict[str, str] | None = None) -> RunResult:
        """`env` is added for this one command only (a token for a CLI), so
        it is never in the command line, a file, or a later command."""

    @abstractmethod
    def preview_url(self) -> str: ...

    @abstractmethod
    async def kill(self) -> None: ...

    @abstractmethod
    async def is_running(self) -> bool: ...

    async def start_dev_server(self) -> None:
        """Called once on a new sandbox, before the wait for the dev server.
        Drivers whose template starts it correctly on boot do nothing."""

    async def touch(self) -> None:
        """Extend the sandbox's own lifetime, where the driver has one."""

    async def list_files(self) -> list[str]:
        """Every source file, as git sees it: tracked plus untracked, minus
        what .gitignore excludes (node_modules, dist) and minus files deleted
        since the last commit. One command, identical on every driver."""
        result = await self.run(
            "comm -23 <(git ls-files -co --exclude-standard | sort -u) "
            "<(git ls-files -d | sort -u)", timeout=30)
        if not result.ok:
            raise SandboxError(f"could not list files: {result.output[:300]}")
        return [line for line in result.stdout.splitlines() if line.strip()]

    async def dev_server_logs(self, lines: int = 100) -> str:
        result = await self.run(f"tail -n {int(lines)} {DEV_LOG} 2>/dev/null || true",
                                timeout=15)
        return result.stdout
