"""Injectable clocks. Match actors schedule every timer through a Clock so tests
can drive time deterministically with FakeClock.advance()."""

from __future__ import annotations

import asyncio
import heapq
import itertools
import time
from collections.abc import Callable
from typing import Protocol


class TimerHandle(Protocol):
    def cancel(self) -> None: ...


class Clock(Protocol):
    def now_ms(self) -> int: ...
    def wall_ms(self) -> int: ...
    def call_later(self, delay_s: float, fn: Callable[[], None]) -> TimerHandle: ...


class RealClock:
    def now_ms(self) -> int:
        return int(time.monotonic() * 1000)

    def wall_ms(self) -> int:
        return int(time.time() * 1000)

    def call_later(self, delay_s: float, fn: Callable[[], None]) -> TimerHandle:
        return asyncio.get_running_loop().call_later(max(0.0, delay_s), fn)


class _FakeHandle:
    def __init__(self) -> None:
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class FakeClock:
    """Time only moves when a test calls advance()."""

    def __init__(self, start_ms: int = 1_000_000, wall_start_ms: int = 1_790_000_000_000) -> None:
        self._now = start_ms
        self._wall0 = wall_start_ms - start_ms
        self._heap: list[tuple[int, int, _FakeHandle, Callable[[], None]]] = []
        self._seq = itertools.count()

    def now_ms(self) -> int:
        return self._now

    def wall_ms(self) -> int:
        return self._wall0 + self._now

    def call_later(self, delay_s: float, fn: Callable[[], None]) -> TimerHandle:
        h = _FakeHandle()
        heapq.heappush(self._heap, (self._now + int(round(max(0.0, delay_s) * 1000)), next(self._seq), h, fn))
        return h

    def advance(self, seconds: float) -> int:
        """Move time forward, firing due timers in order. Returns how many fired."""
        target = self._now + int(round(seconds * 1000))
        fired = 0
        while self._heap and self._heap[0][0] <= target:
            due, _, h, fn = heapq.heappop(self._heap)
            self._now = max(self._now, due)
            if not h.cancelled:
                fn()
                fired += 1
        self._now = target
        return fired

    def pending(self) -> int:
        return sum(1 for e in self._heap if not e[2].cancelled)
