"""What the service answers when a request body does not pass its checks.

FastAPI writes these sentences itself, in English — "String should have at
most 100000 characters" is what a German window read above the skill editor
(`frontend/src/lib/api.js` hands the ``msg`` of every entry to the screen).
The handler below builds each sentence from the catalogue in the language of
the request, with the numbers the check itself used; a check that has no
entry of its own names the field in one general sentence.

Nothing else about the answer is touched: it keeps its status, its list, and
every part of an entry except the sentence and the refused value —
``type``, ``loc`` and ``ctx`` stand exactly as FastAPI wrote them, and
``input`` does not travel at all (see :func:`answer_for_input_error`).
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app import sprachwahl
from app.i18n import t

# One sentence per check that has something of its own to say — the length
# bounds, because those are the ones a person can fix by typing less or more,
# and the missing field. Each entry also names the value its sentence needs;
# only that one travels on from the check's `ctx`. Everything else stays
# where it is: the check's own context is its business, and a key of it named
# like a placeholder (`field`) or like a parameter of ``t`` would silently
# rewrite the sentence or break the call.
#
# A check a route's own model makes can name ITSELF here: the kind it raises
# is the key of its sentence (`bild_lauf_nr_zu_gross`,
# app/api/v1/bild.py — `PydanticCustomError` writes that kind into the entry,
# and the sentence is then built in the language of the request like every
# other). A kind this table does not know falls to the general sentence.
SENTENCE_FOR_KIND: dict[str, tuple[str, str | None]] = {
    "string_too_long": ("fehler.eingabe_zu_lang", "max_length"),
    "string_too_short": ("fehler.eingabe_zu_kurz", "min_length"),
    "missing": ("fehler.eingabe_feld_fehlt", None),
    "bild_lauf_nr_zu_gross": ("bild.lauf_nr_zu_gross", None),
}
GENERAL = "fehler.eingabe_ungueltig"

# Where a value can live. Dropped from the front of the location when a field
# name follows, so the sentence names the field ("inhalt") and not the
# protocol's word for the place it arrived in ("body.inhalt").
PLACES = frozenset({"body", "query", "path", "header", "cookie"})


def _field(location: tuple[Any, ...]) -> str:
    """The field as the caller wrote it: the name in the location.

    A NUMBER in a location is no name — it is a position, either where the
    parser stopped in a body it could not read (``("body", 13)``) or an item
    of a list (``("body", 0, "name")``). Positions fall away, so an
    unreadable body is reported as the body and a list item by its field."""
    parts = [str(part) for part in location if not isinstance(part, int)]
    if len(parts) > 1 and parts[0] in PLACES:
        parts = parts[1:]
    return ".".join(parts) or "body"


def _sentence(entry: dict[str, Any], language: str) -> str:
    key, needed = SENTENCE_FOR_KIND.get(str(entry.get("type", "")), (GENERAL, None))
    context = entry.get("ctx") or {}
    placeholders: dict[str, Any] = {"field": _field(tuple(entry.get("loc") or ()))}
    if needed is not None:
        placeholders[needed] = context.get(needed)
    return t(key, language, **placeholders)


def answer_for_input_error(
    request: Request, error: RequestValidationError
) -> JSONResponse:
    """FastAPI's own answer to a body that failed its checks, with every
    sentence built from the catalogue — registered in ``app/main.py`` instead
    of the framework's English one.

    One part of an entry does NOT travel on: ``input``, the value that was
    refused. FastAPI hands it back whole, and on a long one the answer is
    larger than the request that was refused — a field of 100,001 characters
    came back as an answer of 100,159, with the whole text in it. Where it
    stood, the sentence says what was wrong with it. ``type`` and ``ctx``
    stay as they are, and so does everything else the check attached; only
    the sentence is built here.

    The place (``loc``) can be as long as the value was: an unknown key of
    100,000 characters is the FIELD this check reports, and it then stands
    twice in the answer — once as the place, once in the sentence built from
    it. For that shape the answer still outgrows the request. How long a
    field name may be before it stops being one is not settled here: it is a
    ceiling somebody has to set, and until then this stays as it is.

    A check that names the refused value in its own context would hand it
    back the same way — ``ctx`` stays as the check wrote it, and only the
    sentences built from the values above were ever in view here. No check
    in this service does that today."""
    language = sprachwahl.request_language(request)
    entries = [
        {
            **{key: value for key, value in entry.items() if key != "input"},
            "msg": _sentence(entry, language),
        }
        for entry in error.errors()
    ]
    return JSONResponse({"detail": jsonable_encoder(entries)}, status_code=422)
