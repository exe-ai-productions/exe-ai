"""Which language the interface speaks.

Its own module for the same reason the sound switch has one: the settings
route only writes what somebody vouches for, and a JSON column cannot vouch
for anything by itself.

This sat in browser storage, which is the one place the program itself
cannot look — so a service that had to write a text for its user had no way
of knowing which language that user reads.

``auto`` is a value, not the absence of one: it means "follow the device",
and it has to be storable as a deliberate choice. Somebody who picked German
on a machine set to English and later goes back to automatic is making a
decision, and a cleared entry could not tell that apart from never having
chosen.

The catalogues on disk are the list of what may be picked
(``app/i18n.verfuegbare_sprachen``) — a hard-coded list here would let the
route accept a language nobody can serve, or refuse one that was just added.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request

from app.i18n import STANDARDSPRACHE, verfuegbare_sprachen

SCHLUESSEL = "sprache"

AUTO = "auto"

# The two headers that carry a language, named once: every route declares
# them for the API's description (``hole_sprache``, app/api/abhaengigkeiten.py)
# and the callers without a route read them off the request — one home for
# the names, so a renamed header cannot be read at one place and declared at
# another.
HEADER_UI = "X-Ui-Language"
HEADER_ACCEPT = "Accept-Language"

VORGABE: dict[str, Any] = {"sprache": AUTO}


def erlaubt() -> tuple[str, ...]:
    """``auto`` plus every catalogue that is actually on disk."""
    return (AUTO, *verfuegbare_sprachen())


def wahl_pruefen(wert: Any) -> dict[str, Any] | None:
    """Keeps what is usable, drops the rest. ``None`` deletes the entry."""
    if not isinstance(wert, dict):
        return None
    if wert.get("sprache") not in erlaubt():
        return None
    return {"sprache": wert["sprache"]}


def aufgeloest(wert: Any) -> dict[str, Any]:
    """The stored value with the default behind it."""
    return {**VORGABE, **(wahl_pruefen(wert) or {})}


def interface_language(repositories: Any, configured: str | None) -> str | None:
    """The language a text the service writes for its user should be in:
    the choice stored for the interface, or — on ``auto``, where the
    device decides and the service cannot see the device — the configured
    one. Read per call, so a switch in the settings holds for the next text.
    """
    from app.db.repositories.einstellungen import GLOBAL

    wert = aufgeloest(repositories.einstellungen.holen(GLOBAL, SCHLUESSEL))
    return configured if wert["sprache"] == AUTO else wert["sprache"]


def language_from_headers(
    accept_language: str | None, ui_language: str | None, fallback: str | None
) -> str:
    """The language a request asks for: the interface's own header first,
    then the browser's ``Accept-Language``, otherwise the fallback handed in.

    The browser fills ``Accept-Language`` from the system's language, which
    need not be the one the interface shows (a German Mac with the interface
    set to English). A header of its own keeps the interface's choice apart
    from the system's, which other clients (the command line, tests) still
    send as ``Accept-Language``.

    The rule stands here, readable without a route, because four callers ask
    it: every route (``hole_sprache``), the session guard, the served page,
    and the answer to a refused input. Read per call — a catalogue laid down
    while the service runs has to become selectable.
    """
    known = verfuegbare_sprachen()
    shown = (ui_language or "").strip().lower()[:2]
    if shown in known:
        return shown
    if accept_language:
        for entry in accept_language.split(","):
            tag = entry.split(";")[0].strip().lower()[:2]
            if tag in known:
                return tag
    return fallback if fallback in known else STANDARDSPRACHE


def request_language(request: Request) -> str:
    """The rule above, read off a request — for the three callers that are no
    route: the session guard (``app/sitzungsschluessel.py``), the served
    page's texts (``app/main.py``) and the sentence a refused input gets
    (``app/input_errors.py``)."""
    return language_from_headers(
        request.headers.get(HEADER_ACCEPT),
        request.headers.get(HEADER_UI),
        request.app.state.config.app.language,
    )


def page_language(repositories: Any, request: Request) -> str:
    """The language the served page speaks: the stored choice, and on
    ``auto`` — where the device decides — the language this very request
    brought.

    ``interface_language`` cannot ask that: it writes a text while no request
    is there to ask. The page, by contrast, is asked for by the browser the
    interface runs in, and its header IS that device's language — so it is
    handed to ``interface_language`` exactly where the configured language
    would otherwise stand in for the unknown device.
    """
    wanted = request_language(request)
    # ``interface_language`` answers None only when nothing was handed to it
    # in the fallback's place; here something always is.
    return interface_language(repositories, wanted) or wanted
