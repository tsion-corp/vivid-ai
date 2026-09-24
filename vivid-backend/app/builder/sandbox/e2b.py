"""The E2B driver: one microVM from the `vivid-web` template per project.

The template (sandbox-templates/vivid-web) has node_modules installed, git
initialised, and starts the dev server on boot with its output in DEV_LOG.
The manager stores the sandbox id and reconnects to it; a sandbox that has
died is simply replaced, because the snapshot in object storage is the
truth and the sandbox is disposable.

SDK: e2b 2.x (`AsyncSandbox`). Signatures checked against the installed
package, not remembered.
"""
import asyncio
import logging

import httpx
from e2b import AsyncSandbox, CommandExitException, TimeoutException
from e2b.exceptions import NotFoundException, SandboxException

from app.builder import targets as targets_mod
from app.builder.sandbox.base import DEV_LOG, RunResult, Sandbox, SandboxError, safe_path
from app.core.config import settings

log = logging.getLogger("vivid.builder.e2b")

APP_ROOT = "/home/user/app"


def _api() -> dict:
    if not settings.E2B_API_KEY:
        raise SandboxError("E2B_API_KEY is not set")
    return {"api_key": settings.E2B_API_KEY}


class E2BSandbox(Sandbox):
    driver = "e2b"
    root = APP_ROOT

    def __init__(self, sb: AsyncSandbox,
                 target: targets_mod.Target | None = None) -> None:
        self._sb = sb
        self.id = sb.sandbox_id
        if target is not None:
            self.target = target

    @classmethod
    async def create(cls, project_id: str,
                     target: targets_mod.Target | None = None) -> "E2BSandbox":
        target = target or targets_mod.get(targets_mod.WEB)
        last: Exception | None = None
        for attempt in (1, 2):
            try:
                sb = await AsyncSandbox.create(
                    template=target.e2b_template,
                    timeout=settings.BUILDER_SANDBOX_TIMEOUT_SECONDS,
                    metadata={"project_id": project_id},
                    **_api())
                return cls(sb, target)
            except httpx.HTTPError as e:
                # A dropped connection to the control plane, not a refusal;
                # one more try before giving up.
                last = e
                log.warning("sandbox create attempt %d failed: %s", attempt, e)
                await asyncio.sleep(1.0)
            except SandboxException as e:
                raise SandboxError(f"could not create sandbox: {e}") from e
        raise SandboxError(f"could not create sandbox: {last}") from last

    @classmethod
    async def connect(cls, sandbox_id: str,
                      target: targets_mod.Target | None = None) -> "E2BSandbox | None":
        """The running sandbox with this id, or None if it is gone."""
        try:
            sb = await AsyncSandbox.connect(
                sandbox_id, timeout=settings.BUILDER_SANDBOX_TIMEOUT_SECONDS, **_api())
        except NotFoundException:
            return None
        except (SandboxException, httpx.HTTPError) as e:
            log.warning("connect to sandbox %s failed: %s", sandbox_id, e)
            return None
        if not await sb.is_running():
            return None
        return cls(sb, target)

    # --------------------------------------------------------------- files
    def _abs(self, path: str) -> str:
        return f"{APP_ROOT}/{safe_path(path)}"

    async def read_file(self, path: str) -> str:
        try:
            return await self._sb.files.read(self._abs(path))
        except NotFoundException:
            raise FileNotFoundError(path)
        except (SandboxException, httpx.HTTPError) as e:
            raise SandboxError(f"read failed: {e}") from e

    async def write_file(self, path: str, content: str) -> None:
        try:
            await self._sb.files.write(self._abs(path), content)
        except (SandboxException, httpx.HTTPError) as e:
            raise SandboxError(f"write failed: {e}") from e

    def _anywhere(self, path: str) -> str:
        return path if path.startswith("/") else self._abs(path)

    async def read_bytes(self, path: str) -> bytes:
        last: Exception | None = None
        for attempt in (1, 2, 3):
            try:
                return bytes(await self._sb.files.read(self._anywhere(path), format="bytes"))
            except NotFoundException:
                raise FileNotFoundError(path)
            except (SandboxException, httpx.HTTPError) as e:
                # A large read over a poor link times out more often than
                # the sandbox fails; the read is idempotent, so try again.
                last = e
                log.warning("read of %s failed (attempt %d): %s", path, attempt, e)
                await asyncio.sleep(1.0 * attempt)
        raise SandboxError(f"read failed: {last}") from last

    async def write_bytes(self, path: str, data: bytes) -> None:
        # Generated images are a megabyte each; the SDK's default request
        # timeout is tuned for small files and trips on a slow uplink.
        try:
            await self._sb.files.write(self._anywhere(path), data,
                                       request_timeout=settings.BUILDER_SANDBOX_WRITE_TIMEOUT)
        except (SandboxException, httpx.HTTPError) as e:
            raise SandboxError(f"write failed: {e}") from e

    # ------------------------------------------------------------ commands
    async def run(self, cmd: str, timeout: float = 60,
                  env: dict[str, str] | None = None) -> RunResult:
        try:
            result = await self._sb.commands.run(cmd, cwd=APP_ROOT, timeout=timeout,
                                                 envs={"CI": "1", "NO_COLOR": "1",
                                                       "FORCE_COLOR": "0", **(env or {})})
        except CommandExitException as e:
            return RunResult(e.exit_code, e.stdout, e.stderr)
        except TimeoutException:
            return RunResult(124, "", f"command timed out after {timeout:.0f}s",
                             timed_out=True)
        except (SandboxException, httpx.HTTPError) as e:
            raise SandboxError(f"command failed to start: {e}") from e
        return RunResult(result.exit_code, result.stdout, result.stderr)

    # ------------------------------------------------------------ lifetime
    def preview_url(self) -> str:
        return f"https://{self._sb.get_host(self.target.port)}"

    async def start_dev_server(self) -> None:
        """Mobile: restart Metro so the manifest Expo Go reads points at this
        sandbox's public https host. E2B snapshots the start command's process
        when the template is built, so the Metro a sandbox wakes up with was
        started before the sandbox (and its host) existed, and hands phones
        http://<host>:8081 URLs they cannot load."""
        if not self.target.is_mobile:
            return
        host = self._sb.get_host(self.target.port)
        try:
            # "[e]xpo" so the pattern never matches this shell's own command line.
            await self._sb.commands.run("pkill -f '[e]xpo start' || true; sleep 1", cwd=APP_ROOT,
                                        timeout=30)
            await self._sb.commands.run(
                f"npx expo start --port {self.target.port} > {DEV_LOG} 2>&1",
                background=True, cwd=APP_ROOT,
                envs={"EXPO_PACKAGER_PROXY_URL": f"https://{host}", "EXPO_NO_TELEMETRY": "1",
                      "NO_COLOR": "1", "FORCE_COLOR": "0"})
        except (SandboxException, httpx.HTTPError) as e:
            raise SandboxError(f"could not start Metro: {e}") from e

    async def touch(self) -> None:
        try:
            await self._sb.set_timeout(settings.BUILDER_SANDBOX_TIMEOUT_SECONDS)
        except (SandboxException, httpx.HTTPError) as e:
            # A missed extension is not worth failing a turn or a publish;
            # the SDK raises httpx errors when a connection drops.
            log.warning("set_timeout on %s failed: %s", self.id, e)

    async def is_running(self) -> bool:
        try:
            return await self._sb.is_running()
        except (SandboxException, httpx.HTTPError):
            return False

    async def kill(self) -> None:
        try:
            await self._sb.kill()
        except (SandboxException, httpx.HTTPError) as e:
            log.warning("kill %s failed: %s", self.id, e)
