"""Why an answer stopped — whether a length was the reason, and whether the
model ended it by itself.

Until now nothing read this at all. A run that hit its ceiling ended exactly
like one that finished, and the window said nothing about it. With a thinking
model that silence is expensive: thinking and answering are spent out of the
same budget, so a model cut off mid-thought never closes its reasoning block,
and the whole unfinished trace drops into the visible text. What that looks
like from the outside is a broken model, and it is nothing of the sort — it
merely ran out of room.

Every backend has its own word for it and they do not agree: the
OpenAI-compatible servers say ``length``, Anthropic says ``max_tokens``, and
a few say it in capitals. So the word is compared here, once, and the rest of
the program asks a boolean.

The other end of that question is here too: the words that mean nothing cut
the answer off at all — the model was done and said so. No caller compares
an end word of its own; both readings are asked as booleans.

Anything unknown counts as NOT cut off. A wrong silence costs one missing
note; a wrong claim tells the user their complete answer is a fragment.

A model's whole context window running out is a different reason again —
not the answer's own length setting, but no room left for it at all — so
it gets its own word and its own reading below, even though it stops a run
the same way an ordinary length limit does.
"""

from __future__ import annotations

# Every spelling seen for "the token ceiling was reached", lowercased. Not a
# substring match: ``stop`` would be inside nothing here, but a future
# ``stop_sequence`` should never be dragged in by a loose test.
LAENGENENDE = frozenset({
    "length",
    "max_tokens",
    "max_output_tokens",
    "model_length",
    "token_limit",
})

# Anthropic's word for a model ending mid-answer because its context window
# ran out of room, not because the answer hit a length setting.
KONTEXTFENSTER_VOLL = frozenset({
    "model_context_window_exceeded",
})


def kontextfenster_voll(grund: str | None) -> bool:
    """True only for the context-window reading of ``abgeschnitten`` — the
    narrower question the hint under an answer needs to pick its wording."""
    if not isinstance(grund, str):
        return False
    return grund.strip().lower() in KONTEXTFENSTER_VOLL


def abgeschnitten(grund: str | None) -> bool:
    """True when this end reason means the answer ran into a length limit —
    its own ceiling or the model's whole context window."""
    if not isinstance(grund, str):
        return False
    return grund.strip().lower() in LAENGENENDE or kontextfenster_voll(grund)


# Every spelling seen for "the model ended this answer on its own" — nothing
# cut it off and it asked for nothing more. Lowercased like the length set,
# and just as narrow: Anthropic spells it ``end_turn`` where the
# OpenAI-compatible servers spell it ``stop``, and a server that hands the
# word over in capitals is read the same way.
NATUERLICHES_ENDE = frozenset({
    "stop",
    "end_turn",
})


def natuerliches_ende(grund: str | None) -> bool:
    """True only for the words that mean the model ended by itself.

    The other end of :func:`abgeschnitten`, and every bit as narrow: a length
    stop, a full context window, a tool call, a refusal, nothing reported at
    all — none of those is this, whatever else they may be. A caller that
    acts on a FINISHED answer asks this rather than compare a word of its
    own: the backends do not agree on one, and an unknown word must never
    pass for a finished answer.
    """
    if not isinstance(grund, str):
        return False
    return grund.strip().lower() in NATUERLICHES_ENDE


def fenster_voll(
    grund: str | None,
    *,
    gesamt_tokens: int | None = None,
    fenster: int | None = None,
    eigene_grenze: bool = False,
) -> bool:
    """Whether this answer stopped because the model's context window was
    full — the question :func:`kontextfenster_voll` can only half answer,
    because only one backend has a word for it.

    Three readings, in this order:

    * The backend said so itself. Anthropic does; nobody else.
    * The answer ran into a ceiling **nobody chose** AND the numbers say
      the window ran out. Under "Auto" the ceiling is what is left of the
      window, and a ceiling lowered for one refused request
      (``app/kontextvoll.py``) is the free room the refusal named — where
      the answer really filled the window, pointing at the answer-length
      setting would send the user to a slider that was never the cause.
      Where it did NOT fill it, the answer stopped at a limit of the
      PROVIDER's (:func:`anbietergrenze`) — a maker's number, a learned cap,
      or a server that decides for itself — and saying "context window full"
      there is simply wrong. ``eigene_grenze`` says a number really came
      from the setting, the slider or an agent's own head
      (``app/antwortgrenze.py``, where anything set wins outright).
    * A ceiling the user DID choose still stops at the window where the
      window is the smaller of the two. llama.cpp reports that as an
      ordinary length stop and nothing else — measured: ``finish_reason:
      length`` with ``prompt 150 + completion 106 = 256`` against a
      256-token window — so the numbers are what tells the two apart.

    ``gesamt_tokens`` is prompt plus completion, read by the one function
    that already normalizes both provider shapes
    (``app/kontextverbrauch.py``, ``tokens_aus_messwerten``). ``fenster`` is
    what ``app/fenstergroesse.py`` resolved for the endpoint; unknown, only
    the end reason counts — a comparison against a size nobody confirmed
    would be a claim, and this file's rule is that a wrong claim costs more
    than a missing note.

    Anything that is not a length stop at all — ``stop``, ``end_turn``,
    nothing reported — is False whatever the numbers say.
    """
    if kontextfenster_voll(grund):
        return True
    if not abgeschnitten(grund):
        return False
    if not fenster:
        # No confirmed window: the end reason is all there is. A ceiling
        # nobody chose still reads as the window, exactly as before — an
        # unknown window ends a round as a provider outage anyway.
        return not eigene_grenze
    return (gesamt_tokens or 0) >= fenster


def denken_aufgebraucht(
    grund: str | None,
    *,
    denktext: str | None = None,
    sichtbarer_text: str | None = None,
) -> bool:
    """Whether the thinking pass used up the whole answer length.

    A length stop, thinking the server itself labelled as thinking, and not
    one visible character after it: then the model spent its output budget
    reasoning and the user is looking at an empty answer. That shape — a
    thinking block with no visible text after it — is written down as the
    reason the answer ended, instead of continuing on its own.

    What counts as thinking is the house's one narrow rule
    (``app/denkdopplung.py``): only text the server itself labelled as
    thinking. A model that merely writes its reasoning into the visible
    answer is not this case — nothing there was cut off unseen.
    """
    if not abgeschnitten(grund) or kontextfenster_voll(grund):
        return False
    return bool(denktext) and not (sichtbarer_text or "").strip()


def anbietergrenze(
    grund: str | None,
    *,
    gesamt_tokens: int | None = None,
    fenster: int | None = None,
    eigene_grenze: bool = False,
) -> bool:
    """Whether this answer stopped at a limit of the PROVIDER's rather than
    at the window or at a length somebody set.

    The same three readings as :func:`fenster_voll`, asked the other way
    round: a length stop, no ceiling of the user's, a known window — and the
    numbers say the window still had room. What ended the answer is then a
    number of the provider's: the maker's own limit out of a model list, a
    cap learned from a refusal, or a server that decides the length itself
    where none travels (``app/antwortgrenze.py``).

    The line between the two ends is not drawn at a fixed number of free
    tokens; it is the reading measured — prompt plus completion against the
    window — so no new number enters the house.
    """
    if kontextfenster_voll(grund):
        return False
    if not abgeschnitten(grund) or eigene_grenze or not fenster:
        return False
    return (gesamt_tokens or 0) < fenster
