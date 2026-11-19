"""In-memory token buckets behind a small interface so Redis can replace them."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol

from app.core.errors import AppError
from app.domain.gameconfig import BucketCfg


class RateLimiter(Protocol):
    def hit(self, key: str, bucket: BucketCfg, cost: float = 1.0) -> tuple[bool, float]: ...
    def reset(self) -> None: ...


@dataclass
class _Bucket:
    tokens: float
    updated: float


class MemoryRateLimiter:
    def __init__(self) -> None:
        self._b: dict[str, _Bucket] = {}

    def hit(self, key: str, bucket: BucketCfg, cost: float = 1.0) -> tuple[bool, float]:
        now = time.monotonic()
        b = self._b.get(key)
        if b is None:
            b = self._b[key] = _Bucket(float(bucket.capacity), now)
        b.tokens = min(float(bucket.capacity), b.tokens + (now - b.updated) * bucket.per_s)
        b.updated = now
        if b.tokens >= cost:
            b.tokens -= cost
            return True, 0.0
        retry = (cost - b.tokens) / bucket.per_s if bucket.per_s > 0 else 60.0
        if len(self._b) > 50_000:  # crude memory guard
            self._b.clear()
        return False, retry

    def reset(self) -> None:
        self._b.clear()


limiter: RateLimiter = MemoryRateLimiter()


def enforce(key: str, bucket: BucketCfg) -> None:
    ok, retry = limiter.hit(key, bucket)
    if not ok:
        raise AppError("rate_limited", "Too many requests, slow down", {"retry_after": round(retry, 2)})
