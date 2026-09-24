"""Test fixtures for the pieces that need no Postgres.

The end-to-end path is covered by `make smoke` against the real stack. What
lives here is the logic that a live stack makes slow and flaky to check:
session ownership, egress rules, the controller loop's decisions, and the
error envelope.
"""
import fnmatch

import pytest


class FakeRedis:
    """Enough of redis.asyncio for the browser session registry.

    Ignores TTLs on purpose — expiry is the one thing these tests never assert,
    and a fake clock would only add a way to be wrong.
    """

    def __init__(self) -> None:
        self.strings: dict[str, str] = {}
        self.sets: dict[str, set[str]] = {}
        self.fail = False        # flip to simulate an unavailable registry

    def _check(self) -> None:
        if self.fail:
            raise ConnectionError("redis is down")

    async def set(self, key, value, ex=None, nx=False):
        self._check()
        if nx and key in self.strings:
            return None                      # as Redis does: not set
        self.strings[key] = value
        return True

    async def get(self, key):
        self._check()
        return self.strings.get(key)

    async def mget(self, keys):
        self._check()
        return [self.strings.get(k) for k in keys]

    async def delete(self, *keys):
        self._check()
        return sum(self.strings.pop(k, None) is not None for k in keys)

    async def sadd(self, key, *values):
        self._check()
        self.sets.setdefault(key, set()).update(values)
        return len(values)

    async def srem(self, key, *values):
        self._check()
        bucket = self.sets.get(key, set())
        removed = 0
        for v in values:
            if v in bucket:
                bucket.discard(v)
                removed += 1
        return removed

    async def smembers(self, key):
        self._check()
        return set(self.sets.get(key, set()))

    async def expire(self, key, seconds):
        self._check()
        return True

    async def keys(self, pattern):
        self._check()
        return [k for k in self.strings if fnmatch.fnmatch(k, pattern)]


@pytest.fixture
def redis() -> FakeRedis:
    return FakeRedis()
