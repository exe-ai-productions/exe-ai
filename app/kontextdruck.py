"""How full the context is ABOUT TO BE — the last confirmed reading plus an
estimate of everything that has arrived since, asked before the next
request goes out rather than after the previous one came back.

``app/kontextverbrauch.py`` answers a different question: what did the
round that just finished actually use. That number is always one request
behind — it knows nothing about a message just typed, an attachment just
added, or a tool result a running round just produced, because none of
those existed when the round it measures was sent. A threshold checked
against that number alone fires one request late, on the round AFTER the
one that actually grew past it.

This closes that gap: the last confirmed total stands in for the part of
the next prompt that is already settled, and everything since is
estimated — no tokenizer on this side, so the caller measures each piece
with ``app/tokenmass.py``'s ``tokens`` and hands the sum in.
"""

from __future__ import annotations

from app.kontextverbrauch import Kontextstand
from app.tokenmass import ZEICHEN_JE_TOKEN_ROH

# A flat price for an image where nothing better is available. Pricing
# every image from the provider's own usage, calibrated per model and host,
# would need machinery this module has no home for, and more than a fold
# trigger needs. An UNCALIBRATED starting estimate of 1500 tokens per image
# is used instead.
BILD_TOKEN_SCHAETZUNG = 1500


def bild_zeichen(anzahl: int) -> int:
    """The same price, in characters — for the two readers that count a
    history in characters because they CUT one (app/verdichtung.py's
    verbatim tail, app/werkzeugkuerzung.py). A budget that has to become a
    length before the text exists uses the rough ratio; everything that has
    a text in hand measures it (app/tokenmass.py)."""
    return bild_tokens(anzahl) * ZEICHEN_JE_TOKEN_ROH


def bild_tokens(anzahl: int) -> int:
    """What ``anzahl`` freshly attached images add, in tokens.

    Tokens and no longer characters: everything else here is measured now
    (app/tokenmass.py), and an image was the one thing whose price had to be
    turned into characters first only to be divided back afterwards."""
    return anzahl * BILD_TOKEN_SCHAETZUNG


def prozent(letzter_stand: int | None, neu_tokens: int, fenster: int | None) -> float | None:
    """The share of the window the next request is expected to carry:
    the last confirmed total plus ``neu_tokens``, measured by the caller
    (:func:`app.tokenmass.tokens`) rather than counted in characters here.

    ``letzter_stand`` missing counts as zero rather than refusing a
    reading — a chat's very first message has no prior total, and folding
    that early is harmless regardless: there are not yet enough rows for a
    middle to exist (``app/chatverdichtung.py``, ``ERSTE_FEST``).

    ``fenster`` missing answers ``None`` — a threshold measured against a
    size nobody confirmed would fold a conversation for no reason, the
    same rule the rest of the context display follows.
    """
    if not fenster:
        return None
    return 100 * _tokens(letzter_stand, neu_tokens) / fenster


def stand(letzter_stand: int | None, neu_tokens: int, fenster: int | None) -> Kontextstand | None:
    """:func:`prozent`'s reading in the shape a round's measured one is
    logged in (``app/kontextverbrauch.py``), for the context bar of a job.

    The bar reads the last ``kontext`` step. The one written after the
    answer cannot carry the round's own tool results — they do not exist
    yet — so the step between rounds logs the total the trigger reads as a
    step of its own (``app/round_end.py``). The bar shows that total as a
    share of the WHOLE window; the trigger weighs the same total against
    the window less a set answer length (:func:`ueber_der_schwelle`), so
    with one set the bar can stand below the threshold's share when a fold
    fires.
    """
    anteil = prozent(letzter_stand, neu_tokens, fenster)
    if anteil is None or not fenster:
        return None
    return Kontextstand(
        tokens=round(_tokens(letzter_stand, neu_tokens)),
        kontextgroesse=fenster,
        prozent=round(anteil, 1),
    )


def ueber_der_schwelle(
    letzter_stand: int | None,
    neu_tokens: int,
    fenster: int | None,
    schwelle_prozent: float,
    eingestellte_grenze: int | None = None,
) -> bool:
    """Whether the next request has reached the threshold a fold fires at.

    The one comparison, made in TOKENS — and against the window less a
    ceiling somebody SET, because the provider reserves that many tokens of
    output out of the same window: measured against the whole of it, a
    request is refused for being too long before the fold ever fires.
    The usable window is therefore ``context_length - (max_tokens or 0)``,
    the full window where nothing is set.

    Under "Auto" nothing is reserved here and the comparison is the one it
    always was. The bar goes on reading :func:`prozent`, against the whole
    window: it shows the same total the trigger weighs, but where an answer
    length is set, not the same share — a fold can fire while the bar stands
    below the threshold's percentage.

    A window nobody confirmed answers ``False``, like :func:`prozent`.
    """
    if not fenster:
        return False
    nutzbar = max(1, fenster - (eingestellte_grenze or 0))
    return _tokens(letzter_stand, neu_tokens) >= schwelle_prozent / 100 * nutzbar


def _tokens(letzter_stand: int | None, neu_tokens: int) -> float:
    """The last confirmed total plus what is new, priced as tokens."""
    return (letzter_stand or 0) + neu_tokens
