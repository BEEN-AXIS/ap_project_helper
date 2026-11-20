"""Profile payloads. Tier and max HP are derived from rating, never stored."""

from __future__ import annotations

from typing import Any

from sqlmodel import Session, select

from app.domain.gameconfig import GameConfig
from app.domain.tiers import get_tier
from app.models import Inventory, Profile, User


def profile_public(p: Profile, cfg: GameConfig) -> dict[str, Any]:
    tier = get_tier(p.rating, cfg)
    nxt = cfg.tier_row(tier + 1) if tier < len(cfg.tiers) else None
    return {
        "id": p.id, "display_name": p.display_name, "rating": p.rating, "peak_rating": p.peak_rating,
        "tier": tier, "tier_title": cfg.tier_row(tier).title, "max_hp": cfg.tier_row(tier).max_hp,
        "next_tier": ({"tier": nxt.tier, "title": nxt.title, "min_rating": nxt.min_rating, "max_hp": nxt.max_hp} if nxt else None),
        "wins": p.wins, "losses": p.losses, "draws": p.draws, "avatar_color": p.avatar_color,
        "equipped": {"card": p.equipped_card, "avatar": p.equipped_avatar, "arena": p.equipped_arena,
                     "weapon": p.equipped_weapon},
        "badges": list(p.badges or []), "is_bot": p.is_bot,
    }


def profile_private(s: Session, p: Profile, cfg: GameConfig) -> dict[str, Any]:
    d = profile_public(p, cfg)
    inv = s.exec(select(Inventory.skin_id).where(Inventory.profile_id == p.id)).all()
    user = s.get(User, p.user_id) if p.user_id else None
    d.update({
        "points": p.points, "settings": p.settings or {}, "inventory": sorted(inv),
        "role": user.role if user else "player", "counters": p.counters or {},
        "queue_ban_until": p.queue_ban_until.isoformat() if p.queue_ban_until else None,
    })
    return d
