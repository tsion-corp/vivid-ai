"""An in-memory sandbox for the builder's unit tests.

Files live in a dict; commands are answered by a script the test sets up.
The typecheck is the one command the tools care about, so it is scripted by
name: `fake.tsc_output = "..."` makes the next typecheck fail with that text.
"""
import io
import json
import posixpath
import tarfile

from app.builder.sandbox.base import RunResult, Sandbox, safe_path


class FakeSandbox(Sandbox):
    driver = "fake"
    root = "/app"

    def __init__(self, files: dict[str, str] | None = None) -> None:
        self.id = "fake_1"
        self.files: dict[str, str] = dict(files or {})
        #: Absolute-path binary files (tarballs the snapshot code moves).
        self.blobs: dict[str, bytes] = {}
        self.commands: list[str] = []
        self.tsc_output: str = ""
        self.killed = False
        self.log = "vite ready\n"
        #: command substring -> RunResult, checked in order.
        self.responses: list[tuple[str, RunResult]] = []
        #: The template commit; the first turn always changes something.
        self.committed: dict[str, str] = {}
        self.commits = 0
        self.restored = 0
        self.installs = 0

    async def read_file(self, path: str) -> str:
        path = safe_path(path)
        if path not in self.files:
            raise FileNotFoundError(path)
        return self.files[path]

    async def write_file(self, path: str, content: str) -> None:
        self.files[safe_path(path)] = content

    async def read_bytes(self, path: str) -> bytes:
        if path in self.blobs:
            return self.blobs[path]
        if path.startswith("/"):
            raise FileNotFoundError(path)
        return (await self.read_file(path)).encode()

    async def write_bytes(self, path: str, data: bytes) -> None:
        self.blobs[path] = data

    async def list_files(self) -> list[str]:
        return sorted(set(self.files) | {k for k in self.blobs if not k.startswith("/")})

    async def dev_server_logs(self, lines: int = 100) -> str:
        return "\n".join(self.log.splitlines()[-lines:])

    async def run(self, cmd: str, timeout: float = 60,
                  env: dict[str, str] | None = None) -> RunResult:
        self.commands.append(cmd)
        #: The env of each command, in order, for tests of what saw a token.
        self.envs = getattr(self, "envs", []) + [dict(env or {})]
        if "tsc --noEmit" in cmd:
            if self.tsc_output:
                return RunResult(2, self.tsc_output, "")
            return RunResult(0, "", "")
        # Enough of git, tar and md5sum for the snapshot code.
        if cmd.startswith("git add -A"):
            changed = self.files != self.committed
            self.committed = dict(self.files)
            self.commits += 0 if not changed else 1
            sha = f"sha{self.commits}"
            return RunResult(0, ("NOCHANGE\n" if not changed else "") + sha + "\n", "")
        if cmd.startswith("tar -czf "):
            path = cmd.split()[2]
            if "-C dist" in cmd:
                # A built site: a real tarball of the files under dist/.
                self.blobs[path] = _tgz({k[5:]: v.encode() for k, v in self.files.items()
                                         if k.startswith("dist/")})
            else:
                self.blobs[path] = json.dumps(self.files).encode()
            return RunResult(0, "", "")
        if cmd.startswith("rm -rf dist && npx vite build"):
            for needle, result in self.responses:
                if needle in cmd:
                    return result
            return RunResult(0, "built", "")
        if "tar -xzf " in cmd:
            path = cmd.split("tar -xzf ")[1].split()[0]
            self.files = json.loads(self.blobs[path].decode())
            self.restored += 1
            return RunResult(0, "", "")
        if cmd.startswith("md5sum package.json"):
            return RunResult(0, f"{hash(self.files.get('package.json', ''))}  package.json\n", "")
        if cmd.startswith("npm install"):
            self.installs += 1
            return RunResult(0, "added 1 package", "")
        for needle, result in self.responses:
            if needle in cmd:
                return result
        return RunResult(0, f"ran: {cmd}", "")

    def preview_url(self) -> str:
        return "http://fake:5173"

    async def kill(self) -> None:
        self.killed = True

    async def is_running(self) -> bool:
        return not self.killed


def tree(files: dict[str, str]) -> list[str]:
    return sorted(posixpath.normpath(p) for p in files)


def _tgz(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data in files.items():
            info = tarfile.TarInfo(f"./{name}")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()
