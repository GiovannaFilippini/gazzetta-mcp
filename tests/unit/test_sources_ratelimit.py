import asyncio

import pytest

from gazzetta_mcp.sources.ratelimit import RateLimiter


class FakeTime:
    def __init__(self) -> None:
        self.now = 100.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


async def test_spaces_requests():
    t = FakeTime()
    limiter = RateLimiter(2.0, clock=t.clock, sleep=t.sleep)
    for _ in range(3):
        await limiter.acquire()
    assert t.sleeps == pytest.approx([0.5, 0.5])


async def test_no_wait_after_idle():
    t = FakeTime()
    limiter = RateLimiter(1.0, clock=t.clock, sleep=t.sleep)
    await limiter.acquire()
    t.now += 10
    await limiter.acquire()
    assert t.sleeps == []


async def test_concurrent_callers_are_serialised():
    t = FakeTime()
    limiter = RateLimiter(1.0, clock=t.clock, sleep=t.sleep)
    await asyncio.gather(*(limiter.acquire() for _ in range(4)))
    assert sum(t.sleeps) == pytest.approx(3.0)


def test_invalid_rate():
    with pytest.raises(ValueError):
        RateLimiter(0)
