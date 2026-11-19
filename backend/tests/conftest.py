"""Shared test setup: ENV=test, a throwaway database per session, anyio backend."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

_tmp = tempfile.mkdtemp(prefix="algoarena-test-")
os.environ.setdefault("ENV", "test")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ.setdefault("JUDGE_BACKEND", "fake")

import pytest  # noqa: E402


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
