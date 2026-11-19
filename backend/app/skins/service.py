"""Inventory, purchases, equipping and unlock checks. Skins never change a number."""

from __future__ import annotations

from typing import Any

from sqlmodel import Session, select

from app.core.errors import AppError
from app.domain.gameconfig import GameConfig
from app.domain.tiers import get_tier
from app.models import Achievement, Inventory, Profile, Purchase
from app.skins.registry import DEFAULTS, load_registry


def owned(s: Session, profile_id: int) -> set[str]:
    return set(s.exec(select(Inventory.skin_id).where(Inventory.profile_id == profile_id)).all())


def evaluate_unlocks(s: Session, prof: Profile, cfg: GameConfig, earned_achievements: list[str] | None = None) -> list[str]:
    """Grant every skin whose unlock condition now holds. A tier unlock counts the
    peak tier, so a demotion never re-locks a skin."""
    have = owned(s, prof.id or 0)
    peak_tier = get_tier(max(prof.peak_rating, prof.rating), cfg)
    achieved = {a.key for a in s.exec(select(Achievement).where(Achievement.profile_id == prof.id)).all()}
    achieved |= set(earned_achievements or [])
    new: list[str] = []
    for sid, m in load_registry().items():
        if sid in have:
            continue
        u = m.get("unlock") or {}
        ok = (u.get("type") == "default"
              or (u.get("type") == "tier" and peak_tier >= int(u["tier"]))
              or (u.get("type") == "achievement" and u.get("id") in achieved))
        if ok:
            s.add(Inventory(profile_id=prof.id or 0, skin_id=sid, source=u.get("type", "default")))
            new.append(sid)
    return [sid for sid in new if (load_registry()[sid].get("unlock") or {}).get("type") != "default"]


def skin_list(s: Session, prof: Profile, cfg: GameConfig) -> list[dict[str, Any]]:
    have = owned(s, prof.id or 0)
    counters = prof.counters or {}
    peak_tier = get_tier(max(prof.peak_rating, prof.rating), cfg)
    out = []
    for sid, m in sorted(load_registry().items()):
        u = m.get("unlock") or {}
        progress = None
        if u.get("type") == "achievement" and u.get("id") == "bit_master":
            progress = {"value": counters.get("bit_wins", 0), "target": 25}
        if u.get("type") == "tier":
            progress = {"value": peak_tier, "target": int(u["tier"])}
        out.append({"id": sid, "kind": m["kind"], "owned": sid in have, "unlock": u, "progress": progress})
    return out


def buy(s: Session, prof: Profile, skin_id: str, idem_key: str) -> dict[str, Any]:
    prior = s.exec(select(Purchase).where(Purchase.profile_id == prof.id, Purchase.idem_key == idem_key)).first()
    if prior is not None:
        return {"skin_id": prior.skin_id, "points": prof.points, "repeat": True}
    m = load_registry().get(skin_id)
    if m is None:
        raise AppError("not_found", "No such skin")
    u = m.get("unlock") or {}
    if u.get("type") != "ap":
        raise AppError("forbidden", "This skin is not for sale")
    if skin_id in owned(s, prof.id or 0):
        raise AppError("conflict", "You already own this skin")
    price = int(u["price"])
    if prof.points < price:
        raise AppError("conflict", "Not enough Arena Points", {"need": price, "have": prof.points})
    prof.points -= price
    s.add(prof)
    s.add(Inventory(profile_id=prof.id or 0, skin_id=skin_id, source="ap"))
    s.add(Purchase(profile_id=prof.id or 0, skin_id=skin_id, idem_key=idem_key, price=price))
    return {"skin_id": skin_id, "points": prof.points, "repeat": False}


def equip(s: Session, prof: Profile, kind: str, skin_id: str | None) -> dict[str, Any]:
    if kind not in ("card", "avatar", "arena"):
        raise AppError("validation", "kind must be card, avatar or arena")
    if skin_id is not None:
        m = load_registry().get(skin_id)
        if m is None or m["kind"] != kind:
            raise AppError("validation", "That skin does not fit this slot")
        if skin_id not in owned(s, prof.id or 0):
            raise AppError("forbidden", "You do not own this skin")
    if kind == "card":
        prof.equipped_card = skin_id or DEFAULTS["card"]
    elif kind == "avatar":
        prof.equipped_avatar = skin_id or DEFAULTS["avatar"]
    else:
        prof.equipped_arena = skin_id
    s.add(prof)
    return {"card": prof.equipped_card, "avatar": prof.equipped_avatar, "arena": prof.equipped_arena}
