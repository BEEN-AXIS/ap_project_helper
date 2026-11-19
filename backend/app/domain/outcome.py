"""Who won a finished match, and what to call each side's result."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

EndReason = Literal["ko", "timer", "forfeit", "disconnect", "aborted"]
Label = Literal["victory", "defeat", "hollow_victory", "self_destruct", "draw"]


@dataclass(frozen=True)
class SideEnd:
    hp: int
    hits_landed: int
    ko_by_recoil: bool = False  # this side's own recoil took it to 0 HP
    left: bool = False  # this side fled or disconnected past the grace period


@dataclass(frozen=True)
class Outcome:
    outcome: Literal["win", "draw", "aborted"]
    winner_side: int | None  # 1 or 2
    end_reason: EndReason
    labels: dict[int, Label]  # side -> label (empty when aborted)


def classify(end_reason: EndReason, p1: SideEnd, p2: SideEnd) -> Outcome:
    if end_reason == "aborted":
        return Outcome("aborted", None, end_reason, {})

    if end_reason in ("forfeit", "disconnect"):
        if p1.left and p2.left:
            return Outcome("aborted", None, "aborted", {})
        winner = 2 if p1.left else 1
    elif end_reason == "ko":
        if p1.hp == 0 and p2.hp == 0:  # cannot happen with a single actor; be safe
            return Outcome("draw", None, end_reason, {1: "draw", 2: "draw"})
        winner = 2 if p1.hp == 0 else 1
    else:  # timer: higher HP wins, equal HP is a draw
        if p1.hp == p2.hp:
            return Outcome("draw", None, end_reason, {1: "draw", 2: "draw"})
        winner = 1 if p1.hp > p2.hp else 2

    w, l_ = (p1, p2) if winner == 1 else (p2, p1)
    loser = 3 - winner
    w_label: Label = "victory" if w.hits_landed > 0 else "hollow_victory"
    l_label: Label = (
        "self_destruct" if (l_.hp == 0 and l_.ko_by_recoil and w.hits_landed == 0) else "defeat"
    )
    return Outcome("win", winner, end_reason, {winner: w_label, loser: l_label})
