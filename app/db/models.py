"""Data objects of the application.

Deliberately plain dataclasses instead of database rows: the application
logic works with these objects and does not know whether SQLite or something
else is behind them.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


def folders_to_column(folders: list[str]) -> str | None:
    """A folder list the way a chat's and a project's column keep it: JSON,
    and NULL for none — no difference between "none chosen" and "empty list
    stored"."""
    return json.dumps(folders, ensure_ascii=False) if folders else None


def folders_from_column(value: str | None) -> list[str]:
    return json.loads(value) if value else []


@dataclass
class Chat:
    id: str
    user_id: str
    title: str
    created_at: str
    updated_at: str
    prompt_aus: bool = False
    endpoint_id: str | None = None
    pinned: bool = False
    # The folders the model may work in for this chat (shell tool). The first
    # is the working directory commands run in, the others are additional
    # sources. Empty: none chosen. Set by the user, never by the model. For
    # a chat in a project these are the project's folders.
    working_dirs: list[str] = field(default_factory=list)
    # The open ask_user question, as the raw JSON text stored in the column
    # — see schema.sql. None once answered, or if none was ever asked.
    frage: str | None = None
    project_id: str | None = None
    archived: bool = False

    @classmethod
    def aus_zeile(cls, zeile: sqlite3.Row) -> "Chat":
        # A chat in a project works in the project's folders; the row is
        # read with them beside its own (ChatRepository, `_CHAT_SELECT`).
        ordner = zeile["project_dirs"] if zeile["project_id"] else zeile["working_dirs"]
        return cls(
            id=zeile["id"],
            user_id=zeile["user_id"],
            title=zeile["title"],
            created_at=zeile["created_at"],
            updated_at=zeile["updated_at"],
            prompt_aus=bool(zeile["prompt_aus"]),
            endpoint_id=zeile["endpoint_id"],
            pinned=bool(zeile["pinned"]),
            working_dirs=folders_from_column(ordner),
            frage=zeile["frage"],
            project_id=zeile["project_id"],
            archived=bool(zeile["archived"]),
        )


@dataclass
class Project:
    """A name and the folders every chat in it shares."""

    id: str
    user_id: str
    name: str
    created_at: str
    updated_at: str
    working_dirs: list[str] = field(default_factory=list)
    archived: bool = False

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Project":
        return cls(
            id=row["id"],
            user_id=row["user_id"],
            name=row["name"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            working_dirs=folders_from_column(row["working_dirs"]),
            archived=bool(row["archived"]),
        )


@dataclass
class Message:
    id: str
    chat_id: str
    role: str
    content: str
    created_at: str
    reasoning: str | None = None
    stats: dict[str, Any] = field(default_factory=dict)
    # File name of an attached image under data/images/ (vision, 4.x).
    #
    # `bild` and `bilder` are mutually exclusive — a row is either a
    # single picture or a run, never both. This used to be a bare
    # assumption: `lauf_bild_speichern` found its row by `stats.lauf`
    # alone, and an old single-picture row could carry the same key,
    # making a row with both a real, reachable state. Its
    # lookup now also requires `bilder IS NOT NULL`, closing that exact
    # path — the real route genuinely cannot produce this state any
    # more. The precedence rule stays anyway, as a guarantee rather than
    # a description: should a row ever carry both regardless, `bilder`
    # WINS, decided once in `bild_dateien` below and applied again by
    # `NachrichtAntwort.aus` for the API response.
    bild: str | None = None
    # Images per run: a run's own picture list, one entry per
    # requested position (`None` where a picture has not finished or did
    # not survive) — never touched by a single vision upload, which keeps
    # using `bild` above exactly as it always has.
    bilder: list[str | None] | None = None
    # id of an attached document (4.1) — text and facts in documents.
    dokument: str | None = None
    # User attachments as lists: several images and several documents on one
    # message. `bild`/`dokument` above keep carrying the FIRST attachment so
    # an older program version reading this database still shows something.
    # The accessors below apply the precedence, like `bild_dateien` does.
    anhaenge: list[str] | None = None
    dokumente: list[str] | None = None
    # What this row IS, beyond who said it — see schema.sql for the values.
    # `role` alone could not separate a model's answer from a finished
    # background run or a picture, so those posed as assistant turns and
    # every reader looking for "the running answer" believed them.
    art: str = "nachricht"
    # Where the run behind this row stands: laeuft, fertig, abgebrochen,
    # fehler. `None` on everything that has no run of its own. This used to
    # live in `stats` as the ABSENCE of a key, which put state in a display
    # blob and made every foreign row look live.
    zustand: str | None = None
    # The run this row belongs to. Was `stats["lauf"]`, and was already
    # being queried with `json_extract` — a foreign key in all but name.
    lauf_id: str | None = None
    # How full the context was after this message. Its own column because
    # it is written WHILE the run goes, not only when it ends.
    gesamt_tokens: int | None = None
    # Id of the summary that folded this message away; `None` means it still
    # goes to the model verbatim. Compaction deletes nothing — the reader
    # keeps every line, the model gets the summary in their place.
    verdichtet_in: str | None = None
    # How many rows this summary folded away. NOT stored -- counted on read,
    # because it is a property of the pointers and would go stale the moment
    # a folded row is deleted or a second pass folds this summary in turn.
    #
    # And counted in SQL rather than in the window: `auflisten` pages at 500,
    # so a window counting the rows IT has would quietly undercount a long
    # chat -- the exact class of "guessed from the list" this table was
    # rebuilt to remove. Zero on every row that is not a summary.
    verdichtete_anzahl: int = 0

    def anhang_bilder(self) -> list[str]:
        """The user-attached images of this message, list wins over scalar."""
        if self.anhaenge:
            return [a for a in self.anhaenge if a]
        return [self.bild] if self.bild else []

    def dokument_ids(self) -> list[str]:
        """The attached documents of this message, list wins over scalar."""
        if self.dokumente:
            return [d for d in self.dokumente if d]
        return [self.dokument] if self.dokument else []

    def bild_dateien(self) -> list[str]:
        """This message's own pictures, precedence already applied —
        the one place that decision is made, so every reader of a
        message's pictures (the API response, the model's own history)
        asks here instead of repeating the `bilder`-wins rule itself.

        `bilder` winning whenever it is merely not `None`
        let an EMPTY list beat a real `bild` — a row with `bild='alt.png'`
        and a damaged `bilder='[]'` lost the real picture with no trace.
        `bilder` only wins carrying at least one real name; an empty or
        all-gap list falls back to `bild` exactly like a row that never
        had `bilder` at all.
        """
        if self.bilder is not None:
            echte = [b for b in self.bilder if b]
            if echte:
                return echte
        if self.bild:
            return [self.bild]
        return []

    @classmethod
    def aus_zeile(cls, zeile: sqlite3.Row) -> "Message":
        rohe_stats = zeile["stats_json"]
        rohe_bilder = zeile["bilder"] if "bilder" in zeile.keys() else None
        return cls(
            id=zeile["id"],
            chat_id=zeile["chat_id"],
            role=zeile["role"],
            content=zeile["content"],
            created_at=zeile["created_at"],
            reasoning=zeile["reasoning"],
            stats=_json_dict_oder_leer(rohe_stats, nachricht_id=zeile["id"]),
            bild=zeile["bild"] if "bild" in zeile.keys() else None,
            bilder=_json_liste_oder_leer(rohe_bilder, nachricht_id=zeile["id"]),
            dokument=zeile["dokument"] if "dokument" in zeile.keys() else None,
            anhaenge=_namensliste(
                zeile["anhaenge"] if "anhaenge" in zeile.keys() else None
            ),
            dokumente=_namensliste(
                zeile["dokumente"] if "dokumente" in zeile.keys() else None
            ),
            # Read defensively like every column added after the fact: a
            # query that selects a narrower set of columns must not crash a
            # whole chat over a field it never asked for.
            art=(zeile["art"] if "art" in zeile.keys() else None) or "nachricht",
            zustand=zeile["zustand"] if "zustand" in zeile.keys() else None,
            lauf_id=zeile["lauf_id"] if "lauf_id" in zeile.keys() else None,
            gesamt_tokens=(
                zeile["gesamt_tokens"] if "gesamt_tokens" in zeile.keys() else None
            ),
            verdichtet_in=(
                zeile["verdichtet_in"] if "verdichtet_in" in zeile.keys() else None
            ),
            # Only `auflisten` computes this; every other query reads a row
            # without the column and gets the honest zero.
            verdichtete_anzahl=(
                zeile["verdichtete_anzahl"]
                if "verdichtete_anzahl" in zeile.keys()
                else 0
            )
            or 0,
        )


def _namensliste(roh: str | None) -> list[str] | None:
    """The attachment lists, damage-tolerant like `bilder` below: a value
    that does not parse to a list of names reads as a row that never had
    the column — one damaged row must never cost the whole chat."""
    if not roh:
        return None
    try:
        daten = json.loads(roh)
    except (TypeError, ValueError):
        return None
    if not isinstance(daten, list):
        return None
    namen = [eintrag for eintrag in daten if isinstance(eintrag, str) and eintrag]
    return namen or None


def _json_dict_oder_leer(roh: str | None, *, nachricht_id: str) -> dict:
    """`stats` is read as a mapping everywhere, so it has to arrive as one.

    Same reasoning as `_json_liste_oder_leer` below, for the neighbouring
    column: `GET .../messages` reads every row of a chat in one pass, and a
    single damaged `stats_json` used to cost the whole chat. Two ways in:
    text that does not parse at all raised `JSONDecodeError`, and text that
    parses to something that is not a mapping — `[1, 2]`, `5`, `"hallo"` —
    reached readers that call `.get` on it and raised `AttributeError` one
    call later. Both end the request with an HTTP 500 for every message in
    the chat, over one row.

    A value that is not a mapping is treated like a row that never had
    stats — the same fallback an empty column already gets — and it is
    logged, because silently healing a damaged row is itself a silent
    failure.
    """
    if not roh:
        return {}
    try:
        wert = json.loads(roh)
    except ValueError:
        log.warning("stats_json of message %s is not JSON", nachricht_id)
        return {}
    if not isinstance(wert, dict):
        log.warning(
            "stats_json of message %s is not an object but %s",
            nachricht_id,
            type(wert).__name__,
        )
        return {}
    return wert


def _json_liste_oder_leer(roh: str | None, *, nachricht_id: str) -> list[str | None] | None:
    """A single damaged `bilder` value must cost that one row, never the
    whole chat: `GET .../messages` reads every row in one pass, and this
    is the ONE place that turns the raw column into what the rest of the
    program trusts it to be — a list of names and gaps, nothing else in
    between. Read AND write share this: `lauf_bild_speichern` builds its
    next write from a row it fetched through here, so a damaged value is
    healed into a fresh, correct list the moment anything touches that
    lauf again, not just quietly tolerated on the way out.

    Checking that the value PARSES is not checking that
    it has the right SHAPE. `json.loads('5')` parses cleanly to the
    integer 5, which then reaches `NachrichtAntwort`'s own `list[str |
    None] | None` field and fails pydantic's validation instead —
    HTTP 500 all the same, just one call later. A value that is not a
    list at all — a bare number, a bool, a single quoted string (valid
    JSON, wrong shape), a dict, unparsable text — is treated like a row
    that never had `bilder` at all, the same fallback an old single-picture row
    already gets.

    A value that IS a list but has one bad entry inside
    it must not cost the whole list — `["real.png", 7]` discarding
    `real.png` along with the `7` is the exact class of loss this
    column exists to prevent, and a picture that genuinely finished is
    worth more than a tidy error. Each entry is judged on its own: a
    name or a gap survives, anything else becomes a gap in its place —
    the same shape a picture that failed to draw already leaves behind,
    not a reason to throw its neighbours away too.

    Silently discarding or healing a damaged value is
    itself a silent failure — logged now, so a corrupted row is
    findable instead of only inferable from a chat that looks a little
    too empty.

    `isinstance(entry, str)` alone lets an EMPTY string
    through as though it were a name — it is neither a name nor `None`,
    and once the chat renders `bilder` directly, an empty string turns
    into a request for a picture that was never drawn instead of the
    gap it actually is. Checked for real content now, not merely for
    being a string.

    Being non-empty was not being a real name either —
    "  " and "\\t" satisfy `bool("  ")` while still asking the server for
    a file that cannot exist. `.strip()` before judging it, so whitespace
    heals to a gap exactly like an empty string already does.
    """
    if not roh:
        return None
    try:
        wert = json.loads(roh)
    except ValueError:
        log.warning(
            "Message %s: 'bilder' is not valid JSON, discarded: %r",
            nachricht_id, roh,
        )
        return None
    if not isinstance(wert, list):
        log.warning(
            "Message %s: 'bilder' is not an array (%s), discarded: %r",
            nachricht_id, type(wert).__name__, roh,
        )
        return None
    geheilt = [
        eintrag if (eintrag is None or (isinstance(eintrag, str) and eintrag.strip())) else None
        for eintrag in wert
    ]
    if geheilt != wert:
        log.warning(
            "Message %s: unusable entries in 'bilder' replaced by gaps: "
            "%r",
            nachricht_id, roh,
        )
    return geheilt


@dataclass
class Auftrag:
    """One run of an agent — lives alongside the chats."""

    id: str
    user_id: str
    agent: str
    auftrag: str
    zustand: str
    created_at: str
    updated_at: str
    ende_grund: str | None = None
    ergebnis: str | None = None
    endpoint_id: str | None = None
    generation_id: str | None = None
    cronjob_id: str | None = None
    zwischenstand: str | None = None
    # The run that started this one — None for everything a person or a
    # schedule started. See schema.sql for what it carries.
    eltern_id: str | None = None
    # The question this run is standing on, as JSON. None whenever nothing
    # is being asked. See schema.sql.
    frage: str | None = None
    # The chat this job was started from. See schema.sql.
    chat_id: str | None = None

    @classmethod
    def aus_zeile(cls, zeile: sqlite3.Row) -> "Auftrag":
        return cls(
            id=zeile["id"],
            user_id=zeile["user_id"],
            agent=zeile["agent"],
            auftrag=zeile["auftrag"],
            zustand=zeile["zustand"],
            created_at=zeile["created_at"],
            updated_at=zeile["updated_at"],
            ende_grund=zeile["ende_grund"],
            ergebnis=zeile["ergebnis"],
            endpoint_id=zeile["endpoint_id"],
            generation_id=zeile["generation_id"],
            cronjob_id=zeile["cronjob_id"],
            zwischenstand=zeile["zwischenstand"],
            eltern_id=zeile["eltern_id"],
            frage=zeile["frage"],
            chat_id=zeile["chat_id"],
        )


@dataclass
class AuftragSchritt:
    """One line in a job's transcript. A run always keeps a record."""

    id: str
    auftrag_id: str
    nummer: int
    typ: str
    inhalt: str
    created_at: str

    @classmethod
    def aus_zeile(cls, zeile: sqlite3.Row) -> "AuftragSchritt":
        return cls(
            id=zeile["id"],
            auftrag_id=zeile["auftrag_id"],
            nummer=zeile["nummer"],
            typ=zeile["typ"],
            inhalt=zeile["inhalt"],
            created_at=zeile["created_at"],
        )


@dataclass
class Document:
    id: str
    chat_id: str
    filename: str
    created_at: str
    mime_type: str | None = None
    size_bytes: int | None = None
    extracted_text: str | None = None
    # Page count (PDF only).
    #
    # The row also carries a ``truncated`` column, left unread: a document
    # travels whole or not at all since the window is resolved before an
    # endpoint counts as reachable, so nothing can set it any more. The
    # column stays because SQLite does not drop one without rewriting the
    # table.
    pages: int | None = None
    # Where the uploaded file itself lies (app/dokumentablage.py) — inside the
    # folder shared with the chat. Empty for a chat that shares no folder, and
    # for every document uploaded before the file was kept at all.
    pfad: str | None = None
    # The agent and the job that delivered it into the chat's own folder;
    # empty for a file the person brought.
    agent: str | None = None
    job: str | None = None

    @classmethod
    def aus_zeile(cls, zeile: sqlite3.Row) -> "Document":
        spalten = zeile.keys()
        return cls(
            id=zeile["id"],
            chat_id=zeile["chat_id"],
            filename=zeile["filename"],
            created_at=zeile["created_at"],
            mime_type=zeile["mime_type"],
            size_bytes=zeile["size_bytes"],
            extracted_text=zeile["extracted_text"],
            pages=zeile["pages"] if "pages" in spalten else None,
            pfad=zeile["pfad"] if "pfad" in spalten else None,
            agent=zeile["agent"] if "agent" in spalten else None,
            job=zeile["job"] if "job" in spalten else None,
        )


@dataclass
class Cronjob:
    """One user-created standing schedule — independent of
    an agent's own single ``schedule:`` front-matter field."""

    id: str
    agent: str
    task: str
    zeitplan: str
    herkunft: str
    created_at: str
    updated_at: str
    deliver: str = "log"
    aktiv: bool = True
    zuletzt_ausgeloest: str | None = None
    # The context-full handoff chain (app/zwischenstand.py) — how many
    # "Done" bullets the last handoff carried, how many restarts in a row
    # that failed to grow, and how many restarts in total. Untouched, and
    # therefore 0/0/None, for an entry nothing has ever handed off through.
    erledigt_anzahl: int | None = None
    ohne_fortschritt: int = 0
    neustarts: int = 0
    # The chain's actual original task (app/zwischenstand.py) — set once on
    # the first handoff, unchanged after. ``None`` for an entry no handoff
    # has ever touched.
    basisaufgabe: str | None = None
    # A one-off reminder: a fire that actually ran deactivates
    # this entry instead of leaving it to come back tomorrow.
    einmalig: bool = False
    # The exact day a one-off reminder is due, 'YYYY-MM-DD' —
    # ``None`` for a daily entry, and for a one-off that only names a time.
    datum: str | None = None
    # Failed runs in a row, and how many in a row make this entry stop
    # trying. Only a run's technical outcome counts — a run that
    # looked and found nothing finishes normally and puts this back to zero.
    fehlversuche: int = 0
    fehlergrenze: int = 5
    # The goal this entry watches for, ``None`` for an entry that
    # simply runs. With one set, nothing is announced after an ordinary run
    # — only what the ``goal`` tool call carried. ``ziel_stilllegen`` says
    # whether reaching it switches the entry off, ``ziel_erreicht_am`` when
    # it was last reported, and ``laeufe_ohne_ruf`` how many runs in a row
    # ended without a report (its own count — silence is not failure).
    ziel: str | None = None
    ziel_stilllegen: bool = False
    ziel_erreicht_am: str | None = None
    laeufe_ohne_ruf: int = 0
    # What one run wrote down for the next one of the same entry,
    # ``None`` for an entry nothing has noted anything on. Written only by
    # the model, through the ``cron_note`` tool, and replaced whole on every
    # call — this is a small fixed piece of state, not a growing log.
    notiz: str | None = None
    # When that note was written. The next run is told how current the note
    # is, and this is the honest answer: ``zuletzt_ausgeloest`` is stamped
    # for a skipped due time as well as for one that fired, so it can name a
    # moment after the note was written.
    notiz_am: str | None = None
    # The entry this one continues (app/zwischenstand.py), ``None`` for an
    # entry that stands on its own. Always the real origin — a continuation
    # of a continuation carries the same id on rather than pointing at its
    # immediate predecessor.
    ursprung_id: str | None = None
    # The script this entry starts instead of a model run, ``None``
    # for an entry that runs an agent. A plain file name, resolved against the
    # scripts location at every firing and refused if it lands outside it.
    # With one set, ``agent`` carries the fixed marker ``(skript)`` — the
    # column is NOT NULL and no agent file can be called that.
    skript: str | None = None
    # How many seconds that script may run, ``None`` for the shipped default
    # (app/tools/shell.py).
    zeitgrenze: int | None = None

    @classmethod
    def aus_zeile(cls, zeile: sqlite3.Row) -> "Cronjob":
        return cls(
            id=zeile["id"],
            agent=zeile["agent"],
            task=zeile["task"],
            zeitplan=zeile["zeitplan"],
            herkunft=zeile["herkunft"],
            created_at=zeile["created_at"],
            updated_at=zeile["updated_at"],
            deliver=zeile["deliver"],
            aktiv=bool(zeile["aktiv"]),
            zuletzt_ausgeloest=zeile["zuletzt_ausgeloest"],
            erledigt_anzahl=zeile["erledigt_anzahl"],
            ohne_fortschritt=zeile["ohne_fortschritt"],
            neustarts=zeile["neustarts"],
            basisaufgabe=zeile["basisaufgabe"],
            einmalig=bool(zeile["einmalig"]),
            datum=zeile["datum"],
            fehlversuche=zeile["fehlversuche"],
            fehlergrenze=zeile["fehlergrenze"],
            ziel=zeile["ziel"],
            ziel_stilllegen=bool(zeile["ziel_stilllegen"]),
            ziel_erreicht_am=zeile["ziel_erreicht_am"],
            laeufe_ohne_ruf=zeile["laeufe_ohne_ruf"],
            notiz=zeile["notiz"],
            notiz_am=zeile["notiz_am"],
            ursprung_id=zeile["ursprung_id"],
            skript=zeile["skript"],
            zeitgrenze=zeile["zeitgrenze"],
        )
