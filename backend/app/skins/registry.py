"""Skin manifest registry: one JSON file per skin in shared/skins/, read by the
server (ownership, unlocks) and the client (rendering). Validated at start-up
and by `python -m app.seed`; the client-side validator is `npm run skins:validate`."""

from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.config import SHARED_DIR

SKINS_DIR = SHARED_DIR / "skins"
RECIPES = SHARED_DIR / "skin-recipes.json"
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
DEFAULTS = {"card": "card.classic", "avatar": "bean.plain", "weapon": "weapon.fireball"}
KINDS = ("card", "avatar", "arena", "weapon")
PREFIX = {"card": "card.", "avatar": "bean.", "arena": "arena.", "weapon": "weapon."}
LEVEL_KEYS = ("easy", "normal", "medium", "tough")


def _lum(hex_: str) -> float:
    def ch(c: int) -> float:
        v = c / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = (int(hex_[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a: str, b: str) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def validate(m: dict[str, Any], recipes: dict[str, Any], filename: str | None = None) -> list[str]:
    errs: list[str] = []
    sid = m.get("id", "?")
    if filename and filename != f"{sid}.json":
        errs.append(f"{filename}: file must be named after its id")
    kind = m.get("kind")
    if kind not in KINDS:
        errs.append(f"{sid}: kind must be card, avatar, arena or weapon")
    if not str(sid).startswith(PREFIX.get(str(kind), "?")):
        errs.append(f"{sid}: id prefix does not match kind")
    if m.get("rarity") not in recipes["rarity"]:
        errs.append(f"{sid}: unknown rarity")
    u = m.get("unlock") or {}
    if u.get("type") not in ("default", "tier", "ap", "achievement", "admin"):
        errs.append(f"{sid}: unknown unlock type")
    if u.get("type") == "tier" and not 1 <= int(u.get("tier", 0)) <= 5:
        errs.append(f"{sid}: tier unlock needs a tier 1-5")
    if u.get("type") == "ap" and int(u.get("price", 0)) <= 0:
        errs.append(f"{sid}: ap unlock needs a price")
    if m.get("rarity") == "legendary" and u.get("type") == "ap":
        errs.append(f"{sid}: legendary skins are not for sale")
    if "reducedMotion" not in m:
        errs.append(f"{sid}: missing reducedMotion fallback")
    if "http://" in json.dumps(m) or "https://" in json.dumps(m):
        errs.append(f"{sid}: external URLs are not allowed")
    pal = m.get("palette") or {}
    for k, v in pal.items():
        vals = v if isinstance(v, (list, tuple)) else [v]
        for c in vals:
            if c != "$player" and not HEX.match(str(c)):
                errs.append(f"{sid}: palette.{k} is not a #rrggbb colour")
    if kind == "card":
        if m.get("frame", {}).get("style") not in recipes["frame"]:
            errs.append(f"{sid}: unknown frame style")
        a = m.get("attack") or {}
        for field in ("element", "projectile", "trail", "impact", "status", "sfx"):
            if a.get(field) not in recipes[field]:
                errs.append(f"{sid}: unknown attack.{field} {a.get(field)!r}")
        if len(a.get("ramp") or []) != 5:
            errs.append(f"{sid}: attack.ramp needs 5 colours")
        for part in ("idle", "hover"):
            p = (m.get(part) or {}).get("particles")
            if p is not None and p not in recipes["particles"]:
                errs.append(f"{sid}: unknown {part}.particles")
        if float((m.get("idle") or {}).get("rate", 0)) > recipes["max_particle_rate"]:
            errs.append(f"{sid}: idle particle rate over the limit")
        for bg in pal.get("bg", []):
            if HEX.match(str(pal.get("text", ""))) and HEX.match(str(bg)) and contrast(pal["text"], bg) < 4.5:
                errs.append(f"{sid}: text contrast {contrast(pal['text'], bg):.2f} on {bg} is under 4.5")
    elif kind == "weapon":
        if m.get("style") not in recipes["weapon_style"]:
            errs.append(f"{sid}: unknown weapon style {m.get('style')!r}")
        if m.get("status") not in recipes["weapon_status"]:
            errs.append(f"{sid}: unknown weapon status {m.get('status')!r}")
        levels = m.get("levels") or {}
        if tuple(levels) != LEVEL_KEYS or not all(isinstance(v, str) and v for v in levels.values()):
            errs.append(f"{sid}: levels must name easy, normal, medium and tough in that order")
        if len(pal.get("ramp") or []) != 5:
            errs.append(f"{sid}: palette.ramp needs 5 colours")
        for k in ("metal", "accent"):
            if k not in pal:
                errs.append(f"{sid}: palette.{k} is required")
        if not isinstance(m.get("card_colors"), bool):
            errs.append(f"{sid}: card_colors must be true or false")
    elif kind == "avatar":
        for o in m.get("overlays", []):
            if o.get("sprite") not in recipes["overlay"] or o.get("anchor") not in ("head", "back", "hand"):
                errs.append(f"{sid}: bad overlay {o}")
    elif kind == "arena":
        for layer in m.get("layers", []):
            if layer not in recipes["layer"]:
                errs.append(f"{sid}: unknown layer {layer}")
        if float((m.get("ambient") or {}).get("rate", 0)) > recipes["max_particle_rate"]:
            errs.append(f"{sid}: ambient particle rate over the limit")
        amb = (m.get("ambient") or {}).get("particles")
        if amb is not None and amb not in recipes["particles"]:
            errs.append(f"{sid}: unknown ambient.particles {amb!r}")
        if "music" in m and m["music"] not in recipes.get("music", []):
            errs.append(f"{sid}: unknown music track {m['music']!r}")
        for sky in pal.get("sky", []):
            if contrast(pal["text"], sky) < 4.5:
                errs.append(f"{sid}: text contrast on {sky} is under 4.5")
    return errs


@lru_cache
def load_registry(strict: bool = True) -> dict[str, dict[str, Any]]:
    recipes = json.loads(RECIPES.read_text())
    reg: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for p in sorted(SKINS_DIR.glob("*.json")):
        m = json.loads(p.read_text())
        errors += validate(m, recipes, p.name)
        if m.get("id") in reg:
            errors.append(f"duplicate id {m['id']}")
        reg[m["id"]] = m
    if errors and strict:
        raise ValueError("invalid skin manifests:\n" + "\n".join(errors))
    return reg


def registry_version() -> str:
    raw = "".join(json.dumps(m, sort_keys=True) for m in load_registry().values())
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def default_skin_ids() -> list[str]:
    return sorted(sid for sid, m in load_registry().items() if (m.get("unlock") or {}).get("type") == "default")


def get_skin(skin_id: str) -> dict[str, Any] | None:
    return load_registry().get(skin_id)


def skins_dir() -> Path:
    return SKINS_DIR
