"""Stages a model has already refused.

The catalogue cannot know every model. Where it does not, the control offers
whatever the provider accepts elsewhere — a control that works, if not a
precise one. The price is that a stage can come back as an error the first
time it is tried.

That error is worth keeping. It is written down per model, the stage leaves
the list, and nobody meets it twice. There is no quiet fallback to some
other depth: the request was not what was asked for, so the answer says so
and the choice goes back to the hand that made it.

Only an error that names the field AS ITS CAUSE counts. A provider is down,
a key is wrong, a context is full — all of those also arrive as a 400, and
blaming the stage for them would empty a working list one entry at a time.
Nor is a field name in the text enough: Anthropic answers "`thinking` blocks
in the latest assistant message cannot be modified" about the history, not
about the switch. So the error has to point at the field — in the error
object's ``param``, or by naming it next to a word that says it was not
accepted — or say that thinking cannot be switched off at all.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Iterable

log = logging.getLogger(__name__)

SCHLUESSEL = "denken_abgelehnt"

# The status codes a provider uses to say "not this value".
ABLEHNUNGEN = (400, 422)

# The Responses route's own stage object (app/providers/openai_responses.py,
# `reasoning: {effort: …}`). Every other stage field comes from the
# catalogue (app/denkstufen.py `stage_fields`). Read from a `param` only: the
# bare word in a sentence is too common to blame the stage for.
RESPONSES_FIELD = "reasoning"


def liste_pruefen(wert: Any) -> list[str] | None:
    """Keeps the known stages, drops the rest. ``None`` deletes the entry."""
    if not isinstance(wert, list):
        return None
    raus: list[str] = []
    for eintrag in wert:
        wort = str(eintrag).strip().lower()
        # Not checked against the closed vocabulary: a refused stage can be
        # a word only this model's own template ever named.
        if wort and wort not in raus:
            raus.append(wort)
    return raus or None


# Words a provider uses to say a parameter was not accepted.
NOT_ACCEPTED = (
    "unsupported parameter", "unsupported_parameter", "not supported", "does not support",
    "unknown parameter", "unrecognized request argument", "unrecognized parameter",
    "invalid parameter",
    # A strict schema refusing a field it does not know.
    "extra inputs are not permitted",
    # A value the server does not take (OpenAI "Unsupported value"), a
    # schema refusing the value's shape (pydantic "Input should be …", as
    # in "thinking.type: Input should be 'enabled'") and a tagged union
    # that knows none of the given tags ("… does not match any of the
    # expected tags").
    "unsupported value", "input should be", "does not match any of the expected tags",
)

# A route that cannot think less than always: the refusal of "off" itself.
MANDATORY = "reasoning is mandatory"


def _param(text: str) -> str:
    """The ``param`` of an error object, wherever it stands: inside
    ``error`` (OpenAI), at the top of the object (vLLM's
    ``VLLMValidationError``), or as the ``loc`` of a FastAPI/pydantic
    validation error. The ``loc`` matters: such an error echoes the request
    as its ``input``, so the stage field's name is in the text even where the
    error is about something else entirely."""
    try:
        payload = json.loads(text)
    except ValueError:
        return ""
    if not isinstance(payload, dict):
        return ""
    error = payload.get("error")
    for halter in (error if isinstance(error, dict) else {}, payload):
        param = halter.get("param")
        if isinstance(param, str) and param.strip():
            return param.lower()
    detail = payload.get("detail")
    first = detail[0] if isinstance(detail, list) and detail else None
    loc = first.get("loc") if isinstance(first, dict) else None
    if isinstance(loc, list) and loc:
        return ".".join(str(part) for part in loc).lower()
    return ""


# Path segments that are not the switch: what was said (a thinking block in
# the history). Their refusal is about the conversation, not the stage.
NOT_THE_SWITCH = ("messages", "input")

# Keys inside a stage field that carry something else: how the thinking is
# shown, its token budget (the thinking LENGTH), and the summary, whose
# refusal has its own reading (app/providers/openai_responses.py
# `lehnt_zusammenfassung_ab`).
NOT_A_STAGE = ("display", "budget_tokens", "summary")

_SEGMENT = re.compile(r"[^a-z0-9_]+")
# A field name as it appears in prose: a word, dotted on as far as it goes.
_FIELD_IN_TEXT = re.compile(r"[a-z_][a-z0-9_]*(?:\.[a-z0-9_]+)*")


def _segments(path: str) -> list[str]:
    return [seg for seg in _SEGMENT.split(path.lower()) if seg]


def _names_stage_field(path: str, fields: Iterable[str]) -> bool:
    """Does this path point at a stage field — anywhere in it, behind any
    prefix (``chat_template_kwargs.``, ``body.``) — and not at a key inside
    it that carries something else?"""
    segments = _segments(path)
    if any(seg in NOT_THE_SWITCH for seg in segments):
        return False
    for field in fields:
        wanted = _segments(field)
        for start in range(len(segments) - len(wanted) + 1):
            if segments[start:start + len(wanted)] != wanted:
                continue
            if not any(seg in NOT_A_STAGE for seg in segments[start + len(wanted):]):
                return True
    return False


def _stage_fields() -> tuple[str, ...]:
    from app.denkstufen import stage_fields

    return stage_fields()


def betrifft_denken(text: str | None) -> bool:
    """Does this error name the thinking field as the thing refused?"""
    raw = text or ""
    lower = raw.lower()
    if MANDATORY in lower:
        return True
    # An error object that names its field decides on its own.
    param = _param(raw)
    # Some proxies fill the field with the word for nothing.
    if param and param not in ("none", "null"):
        return _names_stage_field(param, (*_stage_fields(), RESPONSES_FIELD))
    fields = _stage_fields()
    return any(
        _names_stage_field(name, fields) for name in _FIELD_IN_TEXT.findall(lower)
    ) and any(word in lower for word in NOT_ACCEPTED)


def ist_ablehnung(status: int | None, text: str | None) -> bool:
    """A refusal of the stage — not just any error on the way."""
    return status in ABLEHNUNGEN and betrifft_denken(text)


def gemerkt(einstellungen, modell_id: str) -> list[str]:
    """What this model has refused so far."""
    from app.db.repositories.einstellungen import modell_bereich

    return liste_pruefen(einstellungen.holen(modell_bereich(modell_id), SCHLUESSEL)) or []


def merken(einstellungen, modell_id: str, stufe: str | None) -> list[str]:
    """Writes one more refusal down and answers with the whole list."""
    from app.db.repositories.einstellungen import modell_bereich

    wort = str(stufe or "").strip().lower()
    if not wort:
        return gemerkt(einstellungen, modell_id)
    bisher = gemerkt(einstellungen, modell_id)
    if wort in bisher:
        return bisher
    neu = [*bisher, wort]
    einstellungen.setzen(modell_bereich(modell_id), SCHLUESSEL, neu)
    return neu


def refuse_all(einstellungen, modell_id: str, stufen: Iterable[str]) -> list[str]:
    """Writes every one of ``stufen`` down at once, in one write, and answers
    with the whole list — for a server that refused the field itself rather
    than one of its values: with every stage on the list, the profile has
    none left and no stage field goes out again."""
    from app.db.repositories.einstellungen import modell_bereich

    bisher = gemerkt(einstellungen, modell_id)
    neu = [*bisher]
    for stufe in stufen:
        wort = str(stufe or "").strip().lower()
        if wort and wort not in neu:
            neu.append(wort)
    if neu == bisher:
        return bisher
    try:
        einstellungen.setzen(modell_bereich(modell_id), SCHLUESSEL, neu)
    except Exception:  # noqa: BLE001 - runs inside the handler of a failed request, as `lernen`
        log.warning("Refused stages %r for %s not written down", neu, modell_id, exc_info=True)
        return bisher
    return neu


def lernen(
    einstellungen,
    modell_id: str,
    fehler: BaseException,
    zusatz,
    stufe,
    *,
    route: dict[str, Any],
) -> bool:
    """A refused stage, written down — the one rule for every request that
    sends one: a chat turn, and the fold of a chat or a job.

    Blamed only when the stage's fields actually went out (``zusatz``
    carries a stage or the off switch, not only ``route``, the fields the
    requested model's route always gets, ``denkschalter.carries_switch``):
    where the model has no switch for it, or it was refused before, nothing
    was sent that could have been refused, and writing it down would take
    the stage away from the list for a request that never asked. ``stufe``
    may come in the older yes/no form; ``False`` is "off", not "no stage
    given", and goes through the same conversion the request itself went
    through (``denkschalter.ALTFORM``) — written down raw as "false" it would
    never match the stage "off".

    A write that fails is logged, never raised: this runs inside the
    handler of a request that already failed, and a fold must not end its
    run over a summary.
    """
    from app.denkschalter import ALTFORM, carries_switch

    if isinstance(stufe, bool):
        stufe = ALTFORM[stufe]
    if not carries_switch(zusatz, route) or stufe is None or str(stufe).strip() == "":
        return False
    if not ist_ablehnung(getattr(fehler, "status", None), getattr(fehler, "rohtext", None)):
        return False
    try:
        merken(einstellungen, modell_id, str(stufe))
    except Exception:  # noqa: BLE001 - see the docstring
        log.warning("Refused stage %r for %s not written down", stufe, modell_id, exc_info=True)
        return False
    return True


def ohne(stufen: Iterable[str], abgelehnt: Iterable[str]) -> list[str]:
    """A stage list with the refused ones taken out."""
    weg = {str(s).strip().lower() for s in abgelehnt or ()}
    return [s for s in stufen if s not in weg]
