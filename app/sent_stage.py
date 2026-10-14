"""The thinking stage a request really carried.

The stage somebody picked is not always the one that goes out: where a lowered
answer ceiling leaves no room for a thinking budget, the copy of the request
that is sent has thinking switched off (``denkschalter.mit_deckel``). A refusal
of that request is a refusal of "off", and writing the picked stage down as
refused would take a stage away from the list that was never asked for.
"""

from __future__ import annotations

from typing import Any


def _thinking_type(zusatz: dict[str, Any] | None) -> Any:
    denken = (zusatz or {}).get("thinking")
    return denken.get("type") if isinstance(denken, dict) else None


def sent_stage(
    picked: Any,
    picked_zusatz: dict[str, Any] | None,
    sent_zusatz: dict[str, Any] | None,
    off_word: str,
) -> Any:
    """``picked``, unless the request went out with thinking switched off
    where the picked one did not carry that word: then ``"off"``."""
    if _thinking_type(sent_zusatz) == off_word and _thinking_type(picked_zusatz) != off_word:
        return "off"
    return picked
