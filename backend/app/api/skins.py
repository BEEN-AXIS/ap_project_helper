"""Skins: the registry (public), ownership, purchases with an idempotency key, equip."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session

from app.api.deps import Caller, current
from app.context import AppContext, ctx_dep
from app.core.db import run_db
from app.models import Profile
from app.skins import service
from app.skins.registry import load_registry, registry_version

router = APIRouter(tags=["skins"])


@router.get("/skins/registry")
async def registry() -> dict:
    return {"version": registry_version(), "skins": list(load_registry().values())}


@router.get("/skins")
async def my_skins(caller: Caller = Depends(current), ctx: AppContext = Depends(ctx_dep)) -> dict:
    def work(s: Session) -> dict:
        p = s.get(Profile, caller.profile_id)
        assert p is not None
        service.evaluate_unlocks(s, p, ctx.cfg)
        s.flush()
        return {"points": p.points, "equipped": {"card": p.equipped_card, "avatar": p.equipped_avatar, "arena": p.equipped_arena,
                     "weapon": p.equipped_weapon},
                "skins": service.skin_list(s, p, ctx.cfg)}

    return await run_db(work)


class BuyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=4, max_length=64)


@router.post("/skins/{skin_id}/buy")
async def buy(skin_id: str, body: BuyBody, caller: Caller = Depends(current)) -> dict:
    def work(s: Session) -> dict:
        p = s.get(Profile, caller.profile_id)
        assert p is not None
        return service.buy(s, p, skin_id, body.idempotency_key)

    return await run_db(work)


class EquipBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["card", "avatar", "arena", "weapon"]
    skin_id: str | None = Field(default=None, max_length=48)


@router.post("/skins/equip")
async def equip(body: EquipBody, caller: Caller = Depends(current)) -> dict:
    def work(s: Session) -> dict:
        p = s.get(Profile, caller.profile_id)
        assert p is not None
        return service.equip(s, p, body.kind, body.skin_id)

    return {"equipped": await run_db(work)}
