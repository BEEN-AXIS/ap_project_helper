"""In-memory cache of published problems and their tests.

Hands are dealt and submissions judged from this cache, so the hot path never
reads problems from the database. Admin edits call reload().
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlmodel import Session, select

from app.core.db import run_db
from app.domain.hand import PoolProblem
from app.judge.runner import TestCase
from app.models import Problem, TestCaseRow


@dataclass
class CachedProblem:
    id: int
    slug: str
    title: str
    biome: str
    rating: int
    tier: int
    base_damage: int
    base_recoil: int
    time_limit_ms: int
    memory_mb: int
    checker: str
    checker_script: str | None
    tags: list[str]
    hints: list[str]
    stubs: dict[str, str]
    statement_md: str
    input_md: str
    output_md: str
    constraints_md: str
    reference_solution: str
    samples: list[TestCase] = field(default_factory=list)
    hidden: list[TestCase] = field(default_factory=list)

    @property
    def all_tests(self) -> list[TestCase]:
        return [*self.samples, *self.hidden]

    def public(self, with_samples: bool = True) -> dict:
        d = {
            "slug": self.slug, "title": self.title, "biome": self.biome, "rating": self.rating, "tier": self.tier,
            "statement_md": self.statement_md, "input_md": self.input_md, "output_md": self.output_md,
            "constraints_md": self.constraints_md, "time_limit_ms": self.time_limit_ms, "memory_mb": self.memory_mb,
            "stubs": self.stubs, "tests_total": len(self.samples) + len(self.hidden),
        }
        if with_samples:
            d["samples"] = [{"input": t.input, "output": t.expected} for t in self.samples]
        return d

    def summary(self) -> dict:
        return {"slug": self.slug, "title": self.title, "biome": self.biome, "tier": self.tier, "rating": self.rating}


class ProblemCache:
    def __init__(self) -> None:
        self.by_slug: dict[str, CachedProblem] = {}
        self.by_id: dict[int, CachedProblem] = {}

    @property
    def pool(self) -> list[PoolProblem]:
        return [PoolProblem(p.slug, p.tier, p.biome) for p in self.by_slug.values()]

    def get(self, slug: str) -> CachedProblem | None:
        return self.by_slug.get(slug)

    @staticmethod
    def _load(s: Session) -> list[CachedProblem]:
        out: list[CachedProblem] = []
        probs = s.exec(select(Problem).where(Problem.status == "published")).all()
        for p in probs:
            rows = s.exec(select(TestCaseRow).where(TestCaseRow.problem_id == p.id).order_by(TestCaseRow.idx)).all()  # type: ignore[arg-type]
            cp = CachedProblem(
                id=p.id or 0, slug=p.slug, title=p.title, biome=p.biome, rating=p.rating, tier=p.tier,
                base_damage=p.base_damage, base_recoil=p.base_recoil, time_limit_ms=p.time_limit_ms,
                memory_mb=p.memory_mb, checker=p.checker, checker_script=p.checker_script, tags=list(p.tags or []),
                hints=list(p.hints or []), stubs=dict(p.stubs or {}), statement_md=p.statement_md, input_md=p.input_md,
                output_md=p.output_md, constraints_md=p.constraints_md, reference_solution=p.reference_solution,
            )
            si = hi = 0
            for r in rows:
                if r.is_sample:
                    cp.samples.append(TestCase(si, r.input_text, r.expected_text, True))
                    si += 1
            for r in rows:
                if not r.is_sample:
                    cp.hidden.append(TestCase(si + hi, r.input_text, r.expected_text, False))
                    hi += 1
            out.append(cp)
        return out

    async def reload(self) -> None:
        loaded = await run_db(self._load)
        self.by_slug = {p.slug: p for p in loaded}
        self.by_id = {p.id: p for p in loaded}

    def reload_sync(self, s: Session) -> None:
        loaded = self._load(s)
        self.by_slug = {p.slug: p for p in loaded}
        self.by_id = {p.id: p for p in loaded}
