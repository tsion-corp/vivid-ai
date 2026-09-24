"""The sandbox manager: one sandbox per project, remembered in redis,
replaced when dead, killed when idle, and a failed start leaves nothing."""
import pytest

from app.builder.sandbox import manager as manager_mod
from app.builder.sandbox.base import SandboxError
from app.builder.sandbox.manager import SandboxManager
from app.core.config import settings
from tests.builder_fakes import FakeSandbox
from tests.conftest import FakeRedis


class Driver:
    """Stands in for _create and the dev-server wait."""

    def __init__(self) -> None:
        self.created: list[FakeSandbox] = []
        self.fail_wait = False

    def install(self, monkeypatch, manager: SandboxManager) -> None:
        async def create(project_id, target=None):
            sb = FakeSandbox({"src/App.tsx": "x"})
            sb.id = f"sb_{len(self.created) + 1}"
            self.created.append(sb)
            return sb

        async def wait(sandbox):
            if self.fail_wait:
                raise SandboxError("dev server never answered")

        monkeypatch.setattr(manager, "_create", create)
        monkeypatch.setattr(manager, "_wait_for_dev_server", wait)


@pytest.fixture
def manager(monkeypatch):
    monkeypatch.setattr(settings, "SANDBOX_DRIVER", "e2b")
    return SandboxManager()


@pytest.fixture
def driver(monkeypatch, manager) -> Driver:
    d = Driver()
    d.install(monkeypatch, manager)
    return d


async def test_get_or_create_reuses_and_remembers(manager, driver):
    redis = FakeRedis()
    a = await manager.get_or_create("p1", redis)
    b = await manager.get_or_create("p1", redis)
    assert a is b and len(driver.created) == 1
    assert redis.strings["builder:sandbox:p1"] == "sb_1"
    assert manager.peek("p1") is a and manager.peek("p2") is None


async def test_dead_sandbox_is_replaced_and_metered(manager, driver, monkeypatch):
    redis = FakeRedis()
    metered = []

    async def record_sandbox(project_id, sandbox_id, seconds):
        metered.append((project_id, sandbox_id))
    monkeypatch.setattr(manager_mod.usage, "record_sandbox", record_sandbox)

    a = await manager.get_or_create("p1", redis)
    a.killed = True                                  # died on its own
    b = await manager.get_or_create("p1", redis)
    assert b is not a and b.id == "sb_2"
    assert redis.strings["builder:sandbox:p1"] == "sb_2"
    assert metered == [("p1", "sb_1")]
    await manager.kill("p1", redis)
    assert metered == [("p1", "sb_1"), ("p1", "sb_2")]


async def test_restore_runs_before_handover_and_failure_kills(manager, driver):
    redis = FakeRedis()
    seen = []

    async def restore(sandbox):
        seen.append(sandbox.id)
    await manager.get_or_create("p1", redis, restore=restore)
    assert seen == ["sb_1"]

    driver.fail_wait = True
    with pytest.raises(SandboxError):
        await manager.get_or_create("p2", redis)
    assert driver.created[-1].killed and manager.peek("p2") is None
    assert "builder:sandbox:p2" not in redis.strings


async def test_reconnects_from_redis_after_restart(manager, driver, monkeypatch):
    redis = FakeRedis()
    redis.strings["builder:sandbox:p1"] = "sb_old"
    revived = FakeSandbox({"src/App.tsx": "x"})
    revived.id = "sb_old"

    class E2BStub:
        @staticmethod
        async def connect(sandbox_id, target=None):
            return revived if sandbox_id == "sb_old" else None
    monkeypatch.setattr("app.builder.sandbox.e2b.E2BSandbox", E2BStub)

    assert await manager.get_or_create("p1", redis) is revived
    assert driver.created == []

    # A stale id is forgotten and a fresh sandbox made.
    redis.strings["builder:sandbox:p2"] = "sb_gone"
    sb = await manager.get_or_create("p2", redis)
    assert sb.id == "sb_1" and redis.strings["builder:sandbox:p2"] == "sb_1"


async def test_sweep_kills_idle_only(manager, driver, monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(settings, "BUILDER_SANDBOX_IDLE_SECONDS", 100)
    now = [1000.0]
    monkeypatch.setattr(manager_mod.time, "monotonic", lambda: now[0])
    a = await manager.get_or_create("p1", redis)
    now[0] = 1050.0
    b = await manager.get_or_create("p2", redis)
    now[0] = 1120.0
    await manager.sweep(redis)
    assert a.killed and not b.killed
    assert manager.peek("p1") is None and manager.peek("p2") is b
    assert "builder:sandbox:p1" not in redis.strings

    await manager.touch("p2")
    now[0] = 1300.0
    await manager.kill_all(redis)
    assert b.killed and manager.peek("p2") is None
