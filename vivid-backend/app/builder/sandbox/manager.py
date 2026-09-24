"""One live sandbox per project, found or made on demand, killed when idle.

`get_or_create(project_id)` is the only way the rest of the builder gets a
sandbox. It reconnects to the one already running (this process remembers
it; Redis remembers it across restarts), creates a fresh one from the
template otherwise, lets the caller restore a snapshot into it, then waits
for the dev server before handing it back.

Idle sandboxes cost money. Every turn and preview request touches the
project; the sweeper kills anything untouched for
BUILDER_SANDBOX_IDLE_SECONDS. The E2B driver also carries its own timeout a
little above that, so a backend that dies without sweeping still leaks
nothing for long.
"""
import asyncio
import logging
import time
from typing import Awaitable, Callable

import httpx

from app.builder import targets, usage
from app.builder.sandbox.base import Sandbox, SandboxError
from app.core.config import settings

log = logging.getLogger("vivid.builder.sandbox")

Restore = Callable[[Sandbox], Awaitable[None]]

_REDIS_KEY = "builder:sandbox:{project_id}"


def _key(project_id: str) -> str:
    return _REDIS_KEY.format(project_id=project_id)


class SandboxManager:
    def __init__(self) -> None:
        self._live: dict[str, Sandbox] = {}
        self._seen: dict[str, float] = {}
        #: When this process started (or reconnected to) each sandbox; the
        #: metered session is from here to the kill.
        self._started: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    # ---------------------------------------------------------------- api
    async def get_or_create(self, project_id: str, redis,
                            restore: Restore | None = None,
                            target: targets.Target | None = None) -> Sandbox:
        """`target` picks the template for a new sandbox (web by default);
        a project's target never changes, so a live one is always right."""
        target = target or targets.get(targets.WEB)
        lock = self._locks.setdefault(project_id, asyncio.Lock())
        async with lock:
            sandbox = await self._existing(project_id, redis, target)
            if sandbox is not None:
                self._seen[project_id] = time.monotonic()
                return sandbox

            sandbox = await self._create(project_id, target)
            log.info("sandbox %s created for project %s (%s)",
                     sandbox.id, project_id, sandbox.driver)
            try:
                if restore is not None:
                    await restore(sandbox)
                await sandbox.start_dev_server()
                await self._wait_for_dev_server(sandbox)
            except Exception:
                await sandbox.kill()
                raise
            self._live[project_id] = sandbox
            self._seen[project_id] = self._started[project_id] = time.monotonic()
            await self._remember(redis, project_id, sandbox.id)
            return sandbox

    def peek(self, project_id: str) -> Sandbox | None:
        """The live sandbox if this process holds one; never creates."""
        return self._live.get(project_id)

    async def touch(self, project_id: str) -> None:
        self._seen[project_id] = time.monotonic()
        sandbox = self._live.get(project_id)
        if sandbox is not None:
            await sandbox.touch()

    async def kill(self, project_id: str, redis) -> None:
        sandbox = self._live.pop(project_id, None)
        self._seen.pop(project_id, None)
        started = self._started.pop(project_id, None)
        if sandbox is None:
            # Maybe another process, or a previous life of this one, made it.
            sandbox = await self._reconnect(project_id, redis)
        if sandbox is not None:
            await sandbox.kill()
            log.info("sandbox %s for project %s killed", sandbox.id, project_id)
            if started is not None:
                await usage.record_sandbox(project_id, sandbox.id,
                                           time.monotonic() - started)
        await self._forget(redis, project_id)

    async def sweep(self, redis) -> None:
        cutoff = time.monotonic() - settings.BUILDER_SANDBOX_IDLE_SECONDS
        idle = [pid for pid, seen in self._seen.items() if seen < cutoff]
        for pid in idle:
            try:
                await self.kill(pid, redis)
            except Exception as e:                    # keep sweeping
                log.warning("sweep of project %s failed: %s", pid, e)

    async def sweeper(self, redis, interval: float = 60) -> None:
        """Run forever; the app's lifespan owns the task."""
        while True:
            await asyncio.sleep(interval)
            await self.sweep(redis)

    async def kill_all(self, redis) -> None:
        for pid in list(self._live):
            try:
                await self.kill(pid, redis)
            except Exception as e:
                log.warning("kill of project %s at shutdown failed: %s", pid, e)

    # ----------------------------------------------------------- internals
    async def _existing(self, project_id: str, redis,
                        target: targets.Target | None = None) -> Sandbox | None:
        sandbox = self._live.get(project_id)
        if sandbox is not None:
            if await sandbox.is_running():
                return sandbox
            log.info("sandbox %s for project %s is gone; replacing", sandbox.id, project_id)
            self._live.pop(project_id, None)
            # It ran until it died; the session is still billable.
            started = self._started.pop(project_id, None)
            if started is not None:
                await usage.record_sandbox(project_id, sandbox.id,
                                           time.monotonic() - started)
        sandbox = await self._reconnect(project_id, redis, target)
        if sandbox is not None:
            self._live[project_id] = sandbox
            self._started[project_id] = time.monotonic()
        return sandbox

    async def _reconnect(self, project_id: str, redis,
                         target: targets.Target | None = None) -> Sandbox | None:
        if settings.SANDBOX_DRIVER != "e2b":
            return None                     # local sandboxes die with the process
        try:
            sandbox_id = await redis.get(_key(project_id))
        except Exception as e:
            log.warning("redis unavailable, cannot reconnect sandboxes: %s", e)
            return None
        if not sandbox_id:
            return None
        from app.builder.sandbox.e2b import E2BSandbox
        sandbox = await E2BSandbox.connect(sandbox_id, target)
        if sandbox is None:
            await self._forget(redis, project_id)
        return sandbox

    async def create_fresh(self, project_id: str,
                           target: targets.Target | None = None,
                           wait: bool = True) -> Sandbox:
        """A new sandbox from the template, not registered with the manager:
        the caller owns it and kills it. For app builds, the eval script and
        tests; `wait=False` for work that never needs the dev server."""
        sandbox = await self._create(project_id, target or targets.get(targets.WEB))
        if not wait:
            return sandbox
        try:
            await self._wait_for_dev_server(sandbox)
        except Exception:
            await sandbox.kill()
            raise
        return sandbox

    async def _create(self, project_id: str, target: targets.Target) -> Sandbox:
        driver = settings.SANDBOX_DRIVER
        if driver == "e2b":
            from app.builder.sandbox.e2b import E2BSandbox
            return await E2BSandbox.create(project_id, target)
        if driver == "local":
            from app.builder.sandbox.local import LocalSandbox
            return await LocalSandbox.create(target.template_dir,
                                             settings.BUILDER_LOCAL_ROOT, project_id, target)
        raise SandboxError(f"SANDBOX_DRIVER must be e2b or local, not {driver!r}")

    async def _wait_for_dev_server(self, sandbox: Sandbox) -> None:
        """Poll the preview URL until Vite answers. The template starts the
        dev server on boot; this only waits for it."""
        url = sandbox.preview_url()
        deadline = time.monotonic() + settings.BUILDER_DEV_SERVER_WAIT_SECONDS
        last = ""
        async with httpx.AsyncClient(timeout=5, follow_redirects=True) as client:
            while time.monotonic() < deadline:
                try:
                    r = await client.get(url)
                    if r.status_code < 500:
                        return
                    last = f"HTTP {r.status_code}"
                except httpx.HTTPError as e:
                    last = e.__class__.__name__
                await asyncio.sleep(1)
        logs = await sandbox.dev_server_logs(30)
        raise SandboxError(
            f"dev server did not come up within "
            f"{settings.BUILDER_DEV_SERVER_WAIT_SECONDS}s ({last}). Log tail:\n{logs}")

    @staticmethod
    async def _remember(redis, project_id: str, sandbox_id: str) -> None:
        try:
            await redis.set(_key(project_id), sandbox_id,
                            ex=settings.BUILDER_SANDBOX_TIMEOUT_SECONDS + 60)
        except Exception as e:
            log.warning("could not record sandbox id in redis: %s", e)

    @staticmethod
    async def _forget(redis, project_id: str) -> None:
        try:
            await redis.delete(_key(project_id))
        except Exception:
            pass


manager = SandboxManager()
