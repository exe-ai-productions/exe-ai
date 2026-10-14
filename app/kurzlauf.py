"""Flagging a run that ends far under what it was allowed.

A run that stops because the model considers itself finished is a normal,
silent ending — most jobs are short on purpose. But one that used only a
sliver of both its round and its minute budget is worth a second look: the
overnight run this step is named after used 12 of 400 rounds and 35 of 420
minutes and nobody noticed, because "fertig" reads the same either way.

Both figures have to be far under, not just one — a quick job with a small
budget finishing in a couple of rounds is ordinary and must not trigger
this on every short run; a big budget barely touched at all is the actual
signal.

The round budget also needs a floor: an agent with the default 30 rounds
already reaches 10% at round 3, so the hint would fire on nearly every short
everyday task. A hint that is always there stops being one — the whole point
is to make the rare 12-of-400 run stand out.
"""

from __future__ import annotations

from app import i18n

# 10%: comfortably below what a run genuinely working through its budget
# would show, without catching the everyday case of a short task finishing
# early against a budget sized for something longer.
SCHWELLE = 0.10

# Below this many allowed rounds, the percentage alone catches too much of
# the everyday case (a default 30-round agent hits 10% at its 3rd round) to
# be a useful signal.
MINDEST_RUNDEN = 50


def kurz(
    runden_benutzt: int, runden_erlaubt: int, minuten_benutzt: float, minuten_erlaubt: float,
) -> bool:
    """Whether a finished run counts as far under budget in both dimensions."""
    if runden_erlaubt <= 0 or minuten_erlaubt <= 0:
        return False
    if runden_erlaubt < MINDEST_RUNDEN:
        return False
    return (
        runden_benutzt / runden_erlaubt < SCHWELLE
        and minuten_benutzt / minuten_erlaubt < SCHWELLE
    )


def hinweis(
    runden_benutzt: int,
    runden_erlaubt: int,
    minuten_benutzt: float,
    minuten_erlaubt: float,
    sprache: str | None = None,
) -> str:
    return i18n.t(
        "jobs.kurzlauf",
        sprache,
        runden=runden_benutzt,
        runden_erlaubt=runden_erlaubt,
        minuten=minuten_benutzt,
        minuten_erlaubt=minuten_erlaubt,
    )
