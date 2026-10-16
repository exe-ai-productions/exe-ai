"""Settings as a cascade.

One table for every setting, and one rule for resolving them: go from general
to specific, and the last value that is actually set wins.

    default (config.yaml)  →  global  →  modell:<id>  →  chat:<id>

Before this, a value could only live on a single chat. Whatever was set there
applied to that one conversation and to nothing else, so every new chat began
at the endpoint's defaults and had to be corrected by hand. Other settings sat
in browser storage, which meant a different truth on every device.

Adding a setting means adding a row, not changing the schema. What is stored
is checked by the caller — a JSON column cannot do it.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from typing import Any

from app.db.repositories.base import Repository

GLOBAL = "global"

# Serialises the read-modify-write in `zusammenlegen`. FastAPI runs the sync
# route handlers in a threadpool and every thread gets a connection of its
# own in autocommit mode, so two PATCHes on one row can land at once: both
# read the same starting object, and the second write drops the first's key.
# That is the very loss the PATCH route exists to prevent, arrived at from
# below — the queue in the browser store orders one window's writes and can
# say nothing about a second window. The same lock, for the same reason, is
# what app/speicherorte.py holds around its own read-modify-write.
_MISCH_SCHLOSS = threading.Lock()

# A model's measured load time, keyed by model name — never
# by endpoint id, so it lives outside the cascade below entirely. It is a
# fact about a run, not a setting, and `kette()` only ever builds
# `global`/`modell:`/`chat:`: this scope can never surface in it.
MESSWERTE = "messwerte"

# A context window learned from a provider's own "too long" refusal
# (app/fenstergroesse.py), keyed by endpoint and model together. Also a fact
# rather than a setting, and outside the cascade for the same reason as
# above — it must never be offered as something a chat or a model scope
# could override.
GELERNTE_FENSTERGROESSEN = "gelernte_fenstergroessen"

class WriteRefused(Exception):
    """A whole-row check refuses a write (a cap on the row's size). The
    route answers it with 400 and nothing is written; any other error stays
    what it is."""


def _carries_something(value: Any) -> bool:
    """False for a set that holds nothing but empty sets — what is left of
    a sent nested value once the check dropped everything inside it."""
    if isinstance(value, dict):
        return any(_carries_something(inner) for inner in value.values())
    return True


def _tief_mischen(alt: dict[str, Any], neu: dict[str, Any]) -> dict[str, Any]:
    """``neu`` laid over ``alt``, key by key, at every depth both are sets.

    Written for a table two levels deep (the module memory: a set of files,
    each a set of roles), and it goes on merging below that rather than
    stopping at the level it was written for. Nothing stored today is
    deeper — this says what the code does, so a third level added later is
    not a surprise.
    """
    zusammen = dict(alt)
    for name, wert in neu.items():
        vorher = zusammen.get(name)
        if isinstance(vorher, dict) and isinstance(wert, dict):
            zusammen[name] = _tief_mischen(vorher, wert)
        else:
            zusammen[name] = wert
    return zusammen


def modell_bereich(endpoint_id: str) -> str:
    return f"modell:{endpoint_id}"


def chat_bereich(chat_id: str) -> str:
    return f"chat:{chat_id}"


def _restore_refused(judged: dict, stored: Any, sent: dict) -> dict:
    """The set the check left, with every entry that was sent with a value
    the check dropped put back as it was stored. An entry sent as unset
    (None, "" or False) is meant to go and stays gone; one sent with a real
    value the check would not take is a refusal, and a refusal must not
    take the stored value with it."""
    if not isinstance(stored, dict):
        return judged
    restored = dict(judged)
    for key, value in sent.items():
        if key in restored or key not in stored:
            continue
        if value is None or value == "" or value is False:
            continue
        restored[key] = stored[key]
    return restored


class EinstellungenRepository(Repository):
    # --- single scopes ----------------------------------------------------

    def holen(self, bereich: str, schluessel: str) -> Any | None:
        """The value of exactly this scope, or None if nothing is set there.

        None means "not set" and never "set to nothing" — that difference is
        what makes the cascade work: an unset scope steps aside for the one
        above it instead of overwriting it with emptiness.
        """
        zeile = self.verbindung.execute(
            "SELECT wert_json FROM einstellungen WHERE bereich = ? AND schluessel = ?",
            (bereich, schluessel),
        ).fetchone()
        if zeile is None:
            return None
        try:
            return json.loads(zeile["wert_json"])
        except json.JSONDecodeError:
            # An unreadable row must not take the chat down: it counts as
            # unset, and the next save overwrites it.
            return None

    def setzen(self, bereich: str, schluessel: str, wert: Any) -> None:
        """Stores a value. `None` removes the entry — see `holen`."""
        if wert is None:
            self.loeschen(bereich, schluessel)
            return
        self.verbindung.execute(
            """
            INSERT INTO einstellungen (bereich, schluessel, wert_json, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (bereich, schluessel) DO UPDATE SET
                wert_json = excluded.wert_json,
                updated_at = excluded.updated_at
            """,
            (bereich, schluessel, json.dumps(wert, ensure_ascii=False), self.zeitstempel()),
        )

    def zusammenlegen(
        self,
        bereich: str,
        schluessel: str,
        wert: dict[str, Any],
        pruefen: Callable[[Any], Any] | None = None,
        row_check: Callable[[Any, Any], None] | None = None,
        as_sent: frozenset[str] = frozenset(),
        as_kept: frozenset[str] = frozenset(),
        null_unsets: frozenset[str] = frozenset(),
    ) -> dict[str, Any] | None:
        """Stores only the keys given, into what this scope already holds.

        ``setzen`` replaces, which is right for a value one writer owns. It is
        wrong the moment two writers hold the same row: each of them has to
        send the whole object to keep the parts it did not change, and the
        whole object it sends is the copy it read when its page opened. Two
        browser windows on the model server did exactly that — the second one
        to touch a slider carried its stale copy out and undid the module the
        first one had just picked. In ``localStorage``, where every value had
        a key of its own, that could not happen.

        So the writer sends what it changed and this merges it in, key by key.
        Nested sets merge the same way one level down, because the module
        memory is a set of sets: two windows on two different model files must
        not be one another's loss either.

        A value that is not a set replaces — a list has no keys to merge along
        (see ``zusammengefuehrt``), and ``None`` is an answer like any other.

        ``pruefen``, when given, judges the sent values beside the stored
        ones: a sent set is first merged deep into the stored set of the same
        key, every other sent value is laid over the stored row as it is, and
        the result is checked. A part can be meaningless on its own and fine
        next to what is already there ("above" needs the stored offset beside
        it), and a check that fills in what a set lacks must see the stored
        values, or it fills in defaults over them. The keys in ``as_sent`` are
        judged as they were sent, not merged first. Only what the check keeps
        of the SENT keys is written; a sent key it drops leaves the stored
        value of that key as it was, and the other stored values are not
        trimmed. ``row_check``, when given, is then handed the stored row and
        the merged one; it refuses the write by raising ``WriteRefused`` (a
        cap on the row's size), and the stored row stays as it was. When the
        check keeps none of the sent values — none of the sent keys, or only
        sets it emptied — nothing is written and the answer is ``None``.

        The keys in ``as_kept`` are sets in which the check has the last word:
        what it keeps of the sent set merged into the stored one replaces the
        stored set. Merging alone can only add and change, so an entry sent as
        unset — a switch turned off — would stay stored for good; here the
        check drops it and it is gone, and a set the check empties is written
        empty, the last entry being as good to unset as any other. An entry
        sent with a value the check REFUSED is not unset: it keeps the value
        it had. The entries that were not sent stay, as everywhere else.

        Read, check and write are one step, not three. They are statements on
        a connection in autocommit mode, and the route that calls this is a
        sync handler — FastAPI runs those in a threadpool, so two PATCHes can
        be inside this method at the same moment. Both would read the same
        starting object and the second write would drop the first's key,
        which is the loss this method exists to prevent. See
        ``_MISCH_SCHLOSS``.

        The keys in ``null_unsets`` are the ones a sent ``None`` unsets: the
        key is taken out of the stored row, so the works answer stands again.
        The check never sees them — a ``None`` is no value, and a check that
        drops it would leave a field that was emptied unable to go back to
        "not set".

        The answer is the row as stored.
        """
        with _MISCH_SCHLOSS:
            alt = self.holen(bereich, schluessel)
            stored = alt if isinstance(alt, dict) else {}
            unset = {name for name, value in wert.items() if value is None and name in null_unsets}
            wert = {name: value for name, value in wert.items() if name not in unset}
            if pruefen is not None:
                context = dict(stored)
                for name, value in wert.items():
                    below = stored.get(name)
                    if name not in as_sent and isinstance(value, dict) and isinstance(below, dict):
                        context[name] = _tief_mischen(below, value)
                    else:
                        context[name] = value
                judged = pruefen(context)
                if not isinstance(judged, dict):
                    return None
                # Only a sent set is taken as the check left it; anything else
                # sent under such a key is judged like every other value.
                kept = {
                    name: _restore_refused(judged[name], stored.get(name), value)
                    for name, value in wert.items()
                    if name in as_kept and isinstance(value, dict) and isinstance(judged.get(name), dict)
                }
                wert = {name: judged[name] for name in wert if name in judged}
                if not kept and not unset and not any(
                    _carries_something(value) for value in wert.values()
                ):
                    return None
            else:
                kept = {}
            merged = {
                name: value
                for name, value in {**_tief_mischen(stored, wert), **kept}.items()
                if name not in unset
            }
            if row_check is not None:
                row_check(stored, merged)
            self.setzen(bereich, schluessel, merged)
            return merged

    def loeschen(self, bereich: str, schluessel: str) -> None:
        self.verbindung.execute(
            "DELETE FROM einstellungen WHERE bereich = ? AND schluessel = ?",
            (bereich, schluessel),
        )

    def all_with_key(self, key: str) -> list[tuple[str, Any]]:
        """Every scope that has ``key`` set, with its value — the
        global one, each model's and each chat's. For a value that has to be
        moved in all of them at once; a row that cannot be read is left out."""
        found: list[tuple[str, Any]] = []
        for row in self.verbindung.execute(
            "SELECT bereich, wert_json FROM einstellungen WHERE schluessel = ?",
            (key,),
        ).fetchall():
            try:
                found.append((row["bereich"], json.loads(row["wert_json"])))
            except json.JSONDecodeError:
                continue
        return found

    def bereich_leeren(self, bereich: str) -> None:
        """Everything of one scope — used when a chat is deleted."""
        self.verbindung.execute("DELETE FROM einstellungen WHERE bereich = ?", (bereich,))

    # --- the cascade ------------------------------------------------------

    def kette(self, schluessel: str, *, modell: str | None = None,
              chat: str | None = None) -> list[str]:
        """The scopes to ask, from general to specific."""
        bereiche = [GLOBAL]
        if modell:
            bereiche.append(modell_bereich(modell))
        if chat:
            bereiche.append(chat_bereich(chat))
        return bereiche

    def aufgeloest(self, schluessel: str, *, modell: str | None = None,
                   chat: str | None = None, vorgabe: Any = None) -> Any:
        """The value that applies here — the most specific one that is set."""
        wert = vorgabe
        for bereich in self.kette(schluessel, modell=modell, chat=chat):
            gefunden = self.holen(bereich, schluessel)
            if gefunden is not None:
                wert = gefunden
        return wert

    def zusammengefuehrt(self, schluessel: str, *, modell: str | None = None,
                         chat: str | None = None,
                         vorgabe: dict[str, Any] | None = None) -> Any:
        """Same, but for settings that are a set of values.

        Merged key by key instead of replaced wholesale: a model that sets
        only the temperature keeps the global top-p rather than dropping it.
        That is what makes a cascade useful — you override one knob, not the
        whole panel.

        Not everything is a set of values, though. A list has no keys to merge
        along, and merging two of them would mean either concatenating (which
        no scope asked for) or dropping one silently. So only two sets are
        merged; anything else is replaced whole, and the more specific scope
        always wins — a set over a list, and a list over a set alike.
        """
        return self.value_and_origin(schluessel, modell=modell, chat=chat, vorgabe=vorgabe)[0]

    def value_and_origin(
        self,
        schluessel: str,
        *,
        modell: str | None = None,
        chat: str | None = None,
        vorgabe: dict[str, Any] | None = None,
        pruefen: Callable[[Any], Any] | None = None,
    ) -> tuple[Any, dict[str, str], str | None]:
        """The merged value (see ``zusammengefuehrt``) and, per field of it,
        the scope it came from — read from each scope once, for both. The
        origin is what the UI shows, so nobody has to guess whether a number
        is theirs, the model's, or the default.

        The origin only names fields the value actually has: a value that is
        not a set has no fields, so it has no field origin either, and a field
        that only the default fills in names no scope. Such a value travels
        whole from the most specific scope that set it, and that scope is
        the third part of the answer — ``None`` for a set of values and for
        a value no scope has set.

        ``pruefen``, when given, checks each scope on its own BEFORE the
        merge, and a scope it throws out counts as unset. A row is only
        meaningful as a whole — merged first, a part of one scope could lean
        on a neighbour from another scope that it was never written beside.
        """
        merged: Any = dict(vorgabe or {})
        woher: dict[str, str] = {}
        whole: str | None = None
        for bereich in self.kette(schluessel, modell=modell, chat=chat):
            gefunden = self.holen(bereich, schluessel)
            if gefunden is not None and pruefen is not None:
                gefunden = pruefen(gefunden)
            if gefunden is None:
                continue
            if isinstance(gefunden, dict) and isinstance(merged, dict):
                merged = {**merged, **gefunden}
            else:
                # Not two sets: the more specific scope replaces what lies
                # below it, and with it the origin of every field below.
                merged = gefunden
                woher = {}
            if isinstance(gefunden, dict):
                whole = None
                for name in gefunden:
                    woher[name] = bereich
            else:
                whole = bereich
        return merged, woher, whole
