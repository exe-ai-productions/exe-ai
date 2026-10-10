"""How full the context is, round by round.

The provider stream already carries the numbers — Anthropic adds input and
output tokens together into ``gesamt_tokens``
(``app/providers/anthropic.py``); an OpenAI-compatible server hands back its
raw ``usage`` block under ``nutzung`` (``app/providers/openai_kompatibel.py``).
A job run never looked at either: a full context only showed up as an error
message once the request had already failed. This turns the same numbers,
already sitting in the round's stats chunk, into an answer to three
questions after every round: how many tokens are in the context, how many
fit, and what share is that.

The context size itself is not computed here — it comes from
``app/fenstergroesse.py``'s ``aufloesen``, which always answers with
something: a configured value, the server's own report, a size learned from
an earlier refusal, the known-models table, or a fallback. So the
percentage below is only ever ``None`` when the caller has not resolved a
size at all yet, never because nobody could confirm one.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


@dataclass
class Kontextstand:
    tokens: int
    kontextgroesse: int | None
    prozent: float | None


def als_zahl(wert: Any) -> int | None:
    """A usable token count, or ``None`` — never a crash.

    The value comes straight from a model server's response, a boundary this
    module does not control: a malformed number there — including a NaN or
    an infinity, both valid JSON-parsed floats that ``int()`` rejects — must
    cost this one reading, not the whole round it arrived with. Rounded
    rather than truncated: a server reporting an estimate like 149.9 means
    150, not 149.
    """
    if isinstance(wert, bool) or not isinstance(wert, (int, float)):
        return None
    if isinstance(wert, float) and not math.isfinite(wert):
        return None
    return round(wert)


def tokens_aus_messwerten(messwerte: dict[str, Any] | None) -> int | None:
    """How many tokens the last round's request and answer used together.

    Two shapes reach here, one per provider family: Anthropic's stats chunk
    already carries the sum as ``gesamt_tokens``; an OpenAI-compatible
    server's raw ``usage`` block (forwarded under ``nutzung``) has
    ``total_tokens`` when the server fills it in, or the two halves to add
    ourselves when it does not.
    """
    if not messwerte:
        return None
    gesamt = als_zahl(messwerte.get("gesamt_tokens"))
    if gesamt is not None:
        return gesamt
    nutzung = messwerte.get("nutzung")
    if isinstance(nutzung, dict):
        gesamt = als_zahl(nutzung.get("total_tokens"))
        if gesamt is not None:
            return gesamt
        eingang = als_zahl(nutzung.get("prompt_tokens"))
        ausgang = als_zahl(nutzung.get("completion_tokens"))
        # Either half missing is not the same as both missing: a server that
        # only reports one side still said something usable, and treating
        # the other as zero costs less than dropping the reading entirely.
        if eingang is not None or ausgang is not None:
            return (eingang or 0) + (ausgang or 0)
    return None


def stand(messwerte: dict[str, Any] | None, kontextgroesse: int | None) -> Kontextstand | None:
    """The reading for one round, or ``None`` when there is nothing to report.

    A ``kontextgroesse`` of ``None`` still yields a reading — tokens are
    known, the ceiling is not — just without a percentage: better to show a
    raw count than to invent a threshold from a size nobody confirmed.
    """
    tokens = tokens_aus_messwerten(messwerte)
    if tokens is None:
        return None
    prozent = round(100 * tokens / kontextgroesse, 1) if kontextgroesse else None
    return Kontextstand(tokens=tokens, kontextgroesse=kontextgroesse, prozent=prozent)
