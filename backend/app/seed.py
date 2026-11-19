"""python -m app.seed

Brings the schema up to date, validates the skin manifests, loads the seed
problems with their tests, and creates demo users (alice, bob), an admin and
the bot profiles. Safe to run repeatedly: problems are upserted by slug.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from sqlmodel import Session, delete, select

from app.core.config import BACKEND_DIR, get_game_config
from app.core.db import db_sync, init_db
from app.core.security import hash_password
from app.domain.tiers import get_tier
from app.models import Inventory, Problem, Profile, TestCaseRow, User

PROBLEMS_DIR = BACKEND_DIR / "seed" / "problems"

DEMO_USERS = [
    ("alice", "alice-pass", "player", "#f97316"),
    ("bob", "bob-pass", "player", "#22c55e"),
    ("admin", "admin-pass", "admin", "#a855f7"),
]


def load_problem_files(directory: Path = PROBLEMS_DIR) -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(directory.glob("*.json"))]


def upsert_problem(s: Session, data: dict) -> Problem:
    cfg = get_game_config()
    tier = get_tier(data["rating"], cfg)
    row = cfg.tier_row(tier)
    p = s.exec(select(Problem).where(Problem.slug == data["slug"])).first()
    if p is None:
        p = Problem(slug=data["slug"], title=data["title"], statement_md="", biome=data["biome"], rating=data["rating"],
                    tier=tier, base_damage=row.base_damage, base_recoil=row.base_recoil)
    p.title = data["title"]
    p.statement_md = data["statement_md"]
    p.input_md = data.get("input_md", "")
    p.output_md = data.get("output_md", "")
    p.constraints_md = data.get("constraints_md", "")
    p.biome = data["biome"]
    p.rating = data["rating"]
    p.tier = tier
    p.base_damage = data.get("base_damage", row.base_damage)
    p.base_recoil = data.get("base_recoil", row.base_recoil)
    p.time_limit_ms = data.get("time_limit_ms", cfg.judge.time_limit_ms)
    p.memory_mb = data.get("memory_mb", cfg.judge.memory_mb)
    p.checker = data.get("checker", "exact")
    p.checker_script = data.get("checker_script")
    p.tags = data.get("tags", [])
    p.hints = data.get("hints", [])
    p.stubs = data.get("stubs", {})
    p.reference_solution = data.get("reference_solution", "")
    p.status = data.get("status", "published")
    s.add(p)
    s.flush()
    s.exec(delete(TestCaseRow).where(TestCaseRow.problem_id == p.id))  # type: ignore[arg-type]
    for i, t in enumerate(data["tests"]):
        s.add(TestCaseRow(problem_id=p.id, idx=i, input_text=t["input"], expected_text=t["expected"], is_sample=t["is_sample"]))
    return p


def ensure_user(s: Session, username: str, password: str, role: str, color: str) -> Profile:
    cfg = get_game_config()
    u = s.exec(select(User).where(User.username_lower == username.lower())).first()
    if u is None:
        u = User(username=username, username_lower=username.lower(), password_hash=hash_password(password), role=role)
        s.add(u)
        s.flush()
    prof = s.exec(select(Profile).where(Profile.user_id == u.id)).first()
    if prof is None:
        prof = Profile(user_id=u.id, display_name=username, rating=cfg.rating.starting, peak_rating=cfg.rating.starting,
                       avatar_color=color)
        s.add(prof)
        s.flush()
        grant_defaults(s, prof)
    return prof


def grant_defaults(s: Session, prof: Profile) -> None:
    """Default skins every profile owns; the full catalogue arrives with the skins module."""
    try:
        from app.skins.registry import default_skin_ids

        ids = default_skin_ids()
    except Exception:
        ids = ["card.classic", "bean.plain"]
    for sid in ids:
        if not s.exec(select(Inventory).where(Inventory.profile_id == prof.id, Inventory.skin_id == sid)).first():
            s.add(Inventory(profile_id=prof.id, skin_id=sid, source="default"))


def ensure_bots(s: Session) -> None:
    cfg = get_game_config()
    for name in cfg.bots.personalities:
        display = f"{name.capitalize()} (BOT)"
        b = s.exec(select(Profile).where(Profile.is_bot == True, Profile.personality == name)).first()  # noqa: E712
        if b is None:
            s.add(Profile(display_name=display, is_bot=True, personality=name, rating=cfg.rating.starting,
                          peak_rating=cfg.rating.starting, avatar_color="#64748b"))
    s.add(Profile(display_name="Training Dummy", is_bot=True, personality="dummy", rating=cfg.rating.starting,
                  peak_rating=cfg.rating.starting, avatar_color="#94a3b8")) if not s.exec(
        select(Profile).where(Profile.personality == "dummy")).first() else None


def seed(demo_users: bool = True, problems_dir: Path = PROBLEMS_DIR) -> dict[str, int]:
    init_db()
    try:
        from app.skins.registry import load_registry

        load_registry(strict=True)
    except ImportError:
        pass
    problems = load_problem_files(problems_dir)

    def work(s: Session) -> dict[str, int]:
        for data in problems:
            upsert_problem(s, data)
        if demo_users:
            for u in DEMO_USERS:
                ensure_user(s, *u)
        ensure_bots(s)
        return {"problems": len(problems)}

    return db_sync(work)


def main() -> None:
    out = seed(demo_users="--no-demo" not in sys.argv)
    print(f"seeded {out['problems']} problems, demo users alice/bob/admin and bot profiles")


if __name__ == "__main__":
    main()
