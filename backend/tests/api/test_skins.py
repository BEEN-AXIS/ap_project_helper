"""Skins and weapons: manifests validate, defaults are owned, equipping is
checked against the inventory, purchases are idempotent, and the equipped
weapon travels with the player into a match."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.db import get_engine
from app.models import Profile
from app.skins.registry import RECIPES, load_registry, validate
from tests.api.test_api import H, client, signup  # noqa: F401  (fixture)

WEAPONS = ["arrows", "fireball", "gun", "laser", "lightning", "meteor", "shuriken", "spear"]


def test_every_manifest_validates_and_weapons_cover_all_styles() -> None:
    reg = load_registry()
    weapons = sorted(m["style"] for m in reg.values() if m["kind"] == "weapon")
    assert weapons == WEAPONS
    recipes = json.loads(RECIPES.read_text())
    assert sorted(recipes["weapon_style"]) == WEAPONS
    for m in reg.values():
        if m["kind"] == "weapon":
            assert list(m["levels"]) == ["easy", "normal", "medium", "tough"]


def test_weapon_manifest_rules() -> None:
    recipes = json.loads(RECIPES.read_text())
    good = dict(load_registry()["weapon.spear"])
    assert validate(good, recipes, "weapon.spear.json") == []
    bad = {**good, "style": "bazooka", "levels": {"easy": "a", "tough": "b"}, "palette": {"ramp": ["#fff"]}}
    errs = " ".join(validate(bad, recipes, "weapon.spear.json"))
    assert "unknown weapon style" in errs and "levels must name" in errs and "palette.ramp needs 5" in errs
    assert "palette.metal is required" in errs
    assert validate({**good, "id": "card.spear"}, recipes, "card.spear.json")  # prefix must match kind


def test_default_weapons_are_owned_and_locked_ones_are_not(client: TestClient) -> None:  # noqa: F811
    tok, _ = signup(client)
    skins = client.get("/api/skins", headers=H(tok)).json()
    owned = {s["id"] for s in skins["skins"] if s["owned"]}
    assert {"weapon.fireball", "weapon.spear", "weapon.gun", "weapon.lightning", "weapon.arrows"} <= owned
    assert not {"weapon.shuriken", "weapon.laser", "weapon.meteor"} & owned
    assert skins["equipped"]["weapon"] == "weapon.fireball"
    me = client.get("/api/me", headers=H(tok)).json()
    assert me["equipped"]["weapon"] == "weapon.fireball"


def test_equip_checks_kind_and_ownership(client: TestClient) -> None:  # noqa: F811
    tok, _ = signup(client)
    r = client.post("/api/skins/equip", headers=H(tok), json={"kind": "weapon", "skin_id": "weapon.spear"})
    assert r.status_code == 200 and r.json()["equipped"]["weapon"] == "weapon.spear"
    locked = client.post("/api/skins/equip", headers=H(tok), json={"kind": "weapon", "skin_id": "weapon.laser"})
    assert locked.json()["error"]["code"] == "forbidden"
    wrong_slot = client.post("/api/skins/equip", headers=H(tok), json={"kind": "card", "skin_id": "weapon.gun"})
    assert wrong_slot.json()["error"]["code"] == "validation"
    reset = client.post("/api/skins/equip", headers=H(tok), json={"kind": "weapon", "skin_id": None})
    assert reset.json()["equipped"]["weapon"] == "weapon.fireball"


def test_buying_a_weapon_is_idempotent_and_needs_points(client: TestClient) -> None:  # noqa: F811
    tok, prof = signup(client)
    poor = client.post("/api/skins/weapon.shuriken/buy", headers=H(tok), json={"idempotency_key": "k-poor"})
    assert poor.json()["error"]["code"] == "conflict"
    with Session(get_engine()) as s:
        p = s.exec(select(Profile).where(Profile.id == prof["id"])).one()
        p.points = 500
        s.add(p)
        s.commit()
    first = client.post("/api/skins/weapon.shuriken/buy", headers=H(tok), json={"idempotency_key": "key-0001"})
    again = client.post("/api/skins/weapon.shuriken/buy", headers=H(tok), json={"idempotency_key": "key-0001"})
    assert first.json()["points"] == 200 and again.json()["repeat"] is True and again.json()["points"] == 200
    eq = client.post("/api/skins/equip", headers=H(tok), json={"kind": "weapon", "skin_id": "weapon.shuriken"})
    assert eq.json()["equipped"]["weapon"] == "weapon.shuriken"
    not_for_sale = client.post("/api/skins/weapon.laser/buy", headers=H(tok), json={"idempotency_key": "key-0002"})
    assert not_for_sale.json()["error"]["code"] == "forbidden"


def test_the_equipped_weapon_travels_into_the_match(client: TestClient) -> None:  # noqa: F811
    tok, _ = signup(client)
    client.post("/api/skins/equip", headers=H(tok), json={"kind": "weapon", "skin_id": "weapon.gun"})
    r = client.post("/api/matches/bot", headers=H(tok), json={"map": "bit"})
    assert r.status_code == 200, r.text
    snap = client.get(f"/api/matches/{r.json()['match_id']}", headers=H(tok)).json()["snapshot"]
    players = snap["players"]
    me = next(p for p in players if not p["is_bot"])
    bot = next(p for p in players if p["is_bot"])
    assert me["skins"]["weapon"] == "weapon.gun"
    assert bot["skins"]["weapon"].startswith("weapon.")
    client.post(f"/api/matches/{r.json()['match_id']}/forfeit", headers=H(tok), json={"cmd_id": "ff-1"})
