"""Access to messages."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any

from app.db.models import Message, _namensliste
from app.db.repositories.auftraege import _eigentuemer_filter
from app.db.repositories.base import Repository, neue_id

log = logging.getLogger(__name__)


def _kurz_nach(zeitstempel: str, *, vor: str | None = None) -> str:
    """The smallest moment after a given one — and, if asked, still before
    a second one, in the project's own notation.

    A summary has to sort in FRONT of the messages it does not replace and
    BEHIND the ones it does. The list is ordered by creation time, so "now"
    would put it at the end of the chat — past everything it is meant to
    stand before. One microsecond is the resolution `jetzt_iso` writes at,
    so it is both the smallest step that changes the sort and the smallest
    one that survives being written down.

    The two directions are NOT symmetric, and that is the whole reason `vor`
    exists. Both readings sort `created_at ASC, rowid ASC`, and a summary is
    the newest row in the table, so it holds the highest `rowid` — a tie is
    therefore always settled in favour of "later":

      * against a row the summary must FOLLOW that is exactly right. It
        lands behind that row without needing a microsecond of its own.
      * against a row the summary must PRECEDE it is exactly wrong. It
        lands behind that one too, and the model then reads a message
        BEFORE the summary of the messages that came before it.

    So the step forward is taken only while it stays strictly below `vor`,
    and otherwise the stamp is handed back as it came. One microsecond of
    room is not something to assume: `jetzt_iso` carries a stamp forward by
    exactly one microsecond whenever the clock has not moved on, which is
    what Windows' roughly 15.6 ms tick does to every row written inside one
    tick. "The next row is one microsecond away" is not a corner case there
    — it is the normal case for anything written in a burst. Reproduced
    with a 15.6 ms clock and twelve rows: the summary tied with the first
    kept row and `rowid` put it behind, so the model read that row first.

    Compared as TEXT rather than as moments, because text comparison is
    what the ORDER BY does and matching it is the point — and because `vor`
    comes out of the database, a boundary this does not control: nothing
    here parses it, so nothing here can raise on it.

    A stamp this cannot parse is handed back unchanged, which is the same
    answer as "no room": a tie with the row it follows, settled by `rowid`
    in the one direction where a tie is safe.

    `timespec` is not optional. Plain `isoformat()` drops the fractional
    part whenever it lands on zero, which it does exactly when adding the
    microsecond rolls a `.999999` over — and every other stamp in this
    database is written by `jetzt_iso` with six digits, whose own docstring
    rests the text ordering on that fixed width.
    """
    try:
        gelesen = datetime.fromisoformat(zeitstempel)
    except ValueError:
        return zeitstempel
    schritt = (gelesen + timedelta(microseconds=1)).isoformat(timespec="microseconds")
    if vor is not None and schritt >= vor:
        return zeitstempel
    return schritt


# What a row may claim to BE and where its run may stand — the same sets
# schema.sql enforces with CHECKs on a fresh database. Enforced here as
# well, because migration 28 added the columns to existing databases
# WITHOUT the checks (SQLite cannot retrofit them short of rebuilding the
# table): on every upgraded install the database swallows any string, and
# exactly the writer bugs `art` exists to end would go unseen in the field.
ARTEN = frozenset({"nachricht", "werkzeugmeldung", "bild", "bildlauf", "verdichtung"})
ZUSTAENDE = frozenset({"laeuft", "fertig", "abgebrochen", "fehler"})


def ist_dienstbericht(art: str | None) -> bool:
    """Whether a row is a report the PROGRAM wrote, not the model.

    The service's reports (``app/hintergrundmeldung.py``,
    ``app/agent_report.py``) and the brake's own note all carry this one art,
    and it is what tells a reader they are not the model's words: handed back
    as the model's own, it took the shape for its own and wrote reports of
    its own making (see ``app/verlaufsbau._als_modellnachricht``).

    Named once, beside ``ARTEN``: the word stood in that set and was compared
    by hand in more than one place, and a typo in one of them would have
    switched the rule off without a sound — the report would have gone to
    the model as its own answer again.
    """
    return art == "werkzeugmeldung"


class MessageRepository(Repository):
    def speichern(
        self,
        *,
        id: str | None = None,
        chat_id: str,
        role: str,
        content: str,
        reasoning: str | None = None,
        stats: dict[str, Any] | None = None,
        bild: str | None = None,
        dokument: str | None = None,
        anhaenge: list[str] | None = None,
        dokumente: list[str] | None = None,
        art: str = "nachricht",
        zustand: str | None = None,
        lauf_id: str | None = None,
        gesamt_tokens: int | None = None,
        replaces_id: str | None = None,
    ) -> Message:
        """``anhaenge``/``dokumente`` are the attachment LISTS; the scalar
        columns keep carrying the first entry so an older program version
        reading this database still shows something.

        ``art`` says what the row is, and every writer that is not a person
        and not the model has to say so. It defaults to an ordinary turn
        because that is what nearly every call is; the three exceptions —
        a finished background run, a picture, a run's picture row — name
        themselves. Before this existed they all posed as assistant turns,
        and every reader looking for "the running answer" believed them.

        ``zustand`` and ``lauf_id`` belong to whatever run produced the row
        and stay ``None`` for everything else. ``gesamt_tokens`` is the
        context reading; it is a column rather than a metric inside
        ``stats`` so it can be written while the run is still going.

        ``id`` lets a caller name the row itself — the interface uses this
        for a user turn, so the row it becomes carries the same id the
        bubble already showed before the round trip, and a reload racing
        the request recognizes its own row instead of doubling it. Left out,
        a fresh id is generated exactly as before.

        ``replaces_id`` names the answer a "regenerate" attempt takes the
        place of, for as long as the attempt runs (see the column in
        schema.sql and :meth:`beim_start_aufraeumen`).
        """
        if art not in ARTEN:
            raise ValueError(f"Unknown message type: {art!r}")
        if zustand is not None and zustand not in ZUSTAENDE:
            raise ValueError(f"Unknown run state: {zustand!r}")
        anhaenge = [a for a in (anhaenge or []) if a] or None
        dokumente = [d for d in (dokumente or []) if d] or None
        if anhaenge and not bild:
            bild = anhaenge[0]
        if dokumente and not dokument:
            dokument = dokumente[0]
        # A given id is only trusted where it cannot break anything: not the
        # `luecke-` shape `_luecke` below relies on staying unclaimed, and
        # not one already spoken for (a network retry re-sending the same
        # request, or simply a collision in the caller's own short id). Off
        # that path, a bare INSERT under a duplicate primary key would raise
        # straight out of a request that a client's own retry can trigger.
        if id is not None and (id.startswith("luecke-") or self.holen(id) is not None):
            id = None
        nachricht = Message(
            id=id or neue_id(),
            chat_id=chat_id,
            role=role,
            content=content,
            created_at=self.zeitstempel(),
            reasoning=reasoning,
            stats=stats or {},
            bild=bild,
            dokument=dokument,
            anhaenge=anhaenge,
            dokumente=dokumente,
            art=art,
            zustand=zustand,
            lauf_id=lauf_id,
            gesamt_tokens=gesamt_tokens,
        )
        self.verbindung.execute(
            """
            INSERT INTO messages (id, chat_id, role, content, reasoning, stats_json,
                                  bild, dokument, anhaenge, dokumente, created_at,
                                  art, zustand, lauf_id, gesamt_tokens, dienst_port,
                                  replaces_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                nachricht.id,
                nachricht.chat_id,
                nachricht.role,
                nachricht.content,
                nachricht.reasoning,
                json.dumps(nachricht.stats, ensure_ascii=False) if nachricht.stats else None,
                nachricht.bild,
                nachricht.dokument,
                json.dumps(nachricht.anhaenge) if nachricht.anhaenge else None,
                json.dumps(nachricht.dokumente) if nachricht.dokumente else None,
                nachricht.created_at,
                nachricht.art,
                nachricht.zustand,
                nachricht.lauf_id,
                nachricht.gesamt_tokens,
                # Whoever writes a row as RUNNING signs it with its own port
                # (see the column in schema.sql): the startup cleanup reads
                # the signature back and leaves a second service's live
                # answer alone. A row born in any other state has nobody to
                # name — nothing but a running row is ever stranded.
                self.db.dienst_port if nachricht.zustand == "laeuft" else None,
                replaces_id,
            ),
        )
        return nachricht

    def anhang_entfernen(
        self, message_id: str, *, bild: str | None = None, dokument: str | None = None
    ) -> Message | None:
        """Removes ONE attachment from a message — the ✕ on a chat attachment.

        Both representations are updated together: the list loses the entry,
        and the scalar column follows the new first entry, so old and new
        readers keep telling the same story.
        """
        nachricht = self.holen(message_id)
        if nachricht is None:
            return None
        if bild is not None:
            bilder = [b for b in nachricht.anhang_bilder() if b != bild]
            self.verbindung.execute(
                "UPDATE messages SET bild = ?, anhaenge = ? WHERE id = ?",
                (
                    bilder[0] if bilder else None,
                    json.dumps(bilder) if len(bilder) > 1 else None,
                    message_id,
                ),
            )
        if dokument is not None:
            dokumente = [d for d in nachricht.dokument_ids() if d != dokument]
            self.verbindung.execute(
                "UPDATE messages SET dokument = ?, dokumente = ? WHERE id = ?",
                (
                    dokumente[0] if dokumente else None,
                    json.dumps(dokumente) if len(dokumente) > 1 else None,
                    message_id,
                ),
            )
        return self.holen(message_id)

    def attach_document(self, message_id: str, document_id: str) -> None:
        """Hangs one more document on a message that already exists — the
        file a chat's model delivers lands on the answer it is writing.

        Both representations together, the way ``anhang_entfernen`` keeps
        them: the scalar carries the first entry, the list all of them once
        there is more than one. A row that is gone, or one that carries the
        document already, is left as it is.
        """
        row = self.holen(message_id)
        if row is None:
            return
        attached = row.dokument_ids()
        if document_id in attached:
            return
        attached.append(document_id)
        self.verbindung.execute(
            "UPDATE messages SET dokument = ?, dokumente = ? WHERE id = ?",
            (
                attached[0],
                json.dumps(attached) if len(attached) > 1 else None,
                message_id,
            ),
        )

    def holen(self, message_id: str) -> Message | None:
        zeile = self.verbindung.execute(
            "SELECT * FROM messages WHERE id = ?", (message_id,)
        ).fetchone()
        return Message.aus_zeile(zeile) if zeile else None

    def hoechste_laufnummer(self, *, chat_id: str) -> int:
        """The highest command-run number any row of this chat carries —
        zero where none does.

        Runs are numbered per chat and live in memory, but the number is
        written into the tool log of the answer that started the run (and
        into the run's report row), and the window pairs call and run by
        it. Numbering continues from here after a restart, so a new run
        never wears a stored call's number. Read in Python rather than
        through SQLite's JSON functions: the log is a list of dicts inside
        the metrics blob, and a blob that is not valid JSON must count as
        nothing, not fail the query.
        """
        zeilen = self.verbindung.execute(
            "SELECT stats_json FROM messages "
            "WHERE chat_id = ? AND stats_json LIKE '%lauf_nummer%'",
            (chat_id,),
        ).fetchall()
        hoechste = 0
        for zeile in zeilen:
            try:
                stats = json.loads(zeile["stats_json"] or "{}")
            except (TypeError, ValueError):
                continue
            eintraege = stats.get("werkzeuge") if isinstance(stats, dict) else None
            for eintrag in eintraege if isinstance(eintraege, list) else []:
                nummer = eintrag.get("lauf_nummer") if isinstance(eintrag, dict) else None
                if isinstance(nummer, int) and not isinstance(nummer, bool):
                    hoechste = max(hoechste, nummer)
        return hoechste

    def auflisten(
        self,
        *,
        chat_id: str,
        limit: int = 500,
        offset: int = 0,
        neueste: bool = False,
    ) -> list[Message]:
        """Oldest first — the order of the conversation.

        Carries one computed column beside the row: how many messages each
        summary folded away. Counted here rather than in the window, because
        this query PAGES — a window counting the folded rows it happens to
        hold would say "12 compressed messages" about a fold of two hundred
        and never once look wrong doing it.

        Asked only of the summaries. `verdichtet_in` carries no index, so
        the subquery is a scan; run for all five hundred rows of a page that
        would be five hundred scans for the handful of rows that can ever
        answer anything but zero. And a scan of THIS chat only: a folded
        row can only point at a summary of its own chat, so the chat index
        narrows the walk to the rows that can answer at all — without the
        `chat_id` term every summary cost a walk over every message of
        every chat, on every page load.

        ``neueste`` counts the window from the OTHER END of the chat, which
        is the end a chat window opens at: ``offset=0`` is the LAST ``limit``
        rows, ``offset=limit`` the page before those. The rows come back
        oldest first either way — that is the order of the conversation, not
        a property of the paging.

        It exists because paging from the front was the wrong default for
        the only caller there is. Every reader took ``limit=500,
        offset=0``, so past its five hundredth row a chat showed its
        BEGINNING and silently lost its end: after a reload the newest
        messages — the ones just typed — were the missing ones. And a chat
        reaches five hundred rows faster the more of this program it uses:
        compaction deletes nothing and adds a summary row per fold, a
        finished background command adds its report, a wake adds an answer.
        The chats that grow fastest are exactly the ones those features were
        built for.

        Counted from the end in ONE statement rather than by subtracting a
        counted total from the offset. A row saved between a `COUNT(*)` and
        the read would shift the window by one and drop the newest row —
        which is the defect this method is being fixed for, in miniature.
        """
        if neueste:
            zeilen = self.verbindung.execute(
                """
                SELECT * FROM (
                    SELECT m.*,
                           m.rowid AS reihe,
                           CASE WHEN m.art = 'verdichtung' THEN
                               (SELECT COUNT(*) FROM messages g
                                WHERE g.chat_id = m.chat_id
                                  AND g.verdichtet_in = m.id)
                           ELSE 0 END AS verdichtete_anzahl
                    FROM messages m
                    WHERE m.chat_id = ?
                    ORDER BY m.created_at DESC, m.rowid DESC
                    LIMIT ? OFFSET ?
                )
                ORDER BY created_at ASC, reihe ASC
                """,
                (chat_id, limit, offset),
            ).fetchall()
            return [Message.aus_zeile(zeile) for zeile in zeilen]
        zeilen = self.verbindung.execute(
            """
            SELECT m.*,
                   CASE WHEN m.art = 'verdichtung' THEN
                       (SELECT COUNT(*) FROM messages g
                        WHERE g.chat_id = m.chat_id
                          AND g.verdichtet_in = m.id)
                   ELSE 0 END AS verdichtete_anzahl
            FROM messages m
            WHERE m.chat_id = ?
            ORDER BY m.created_at ASC, m.rowid ASC
            LIMIT ? OFFSET ?
            """,
            (chat_id, limit, offset),
        ).fetchall()
        return [Message.aus_zeile(zeile) for zeile in zeilen]

    def letzte(self, *, chat_id: str, role: str | None = None) -> Message | None:
        sql = "SELECT * FROM messages WHERE chat_id = ?"
        parameter: list[object] = [chat_id]
        if role is not None:
            sql += " AND role = ?"
            parameter.append(role)
        sql += " ORDER BY created_at DESC, rowid DESC LIMIT 1"
        zeile = self.verbindung.execute(sql, parameter).fetchone()
        return Message.aus_zeile(zeile) if zeile else None

    def last_answer(self, *, chat_id: str) -> Message | None:
        """The chat's newest answer of the model's own.

        Not ``letzte`` with a role: a finished background command and a
        picture are stored under the same role and are not answers — the
        row's kind says which it is.
        """
        zeile = self.verbindung.execute(
            "SELECT * FROM messages WHERE chat_id = ? AND role = 'assistant' "
            "AND art = 'nachricht' ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (chat_id,),
        ).fetchone()
        return Message.aus_zeile(zeile) if zeile else None

    def finish_in_place_of(
        self, message_id: str, replaced_id: str, **closing_write: Any
    ) -> Message | None:
        """An answer's closing write and the end of the answer it replaces,
        as one step.

        The replaced answer stays stored for as long as the new one is being
        written; it goes in the very transaction that stores the new one as
        finished, so the chat never stands without an answer and never keeps
        both. ``closing_write`` is what ``inhalt_aktualisieren`` takes.
        """
        with self.db.transaktion() as verbindung:
            written = self.inhalt_aktualisieren(message_id, **closing_write)
            verbindung.execute("DELETE FROM messages WHERE id = ?", (replaced_id,))
            verbindung.execute(
                "UPDATE messages SET replaces_id = NULL WHERE id = ?", (message_id,)
            )
        return written

    def run_again(self, message_id: str) -> Message | None:
        """An answer's row taken up by a run once more: the state only.

        The run that asks a failed answer's model call again writes into the
        same row. It is marked as being written, signed with this service's
        port like every running row (``speichern``), and nothing else of it
        is touched — what it holds stays until the run has something to put
        in its place.
        """
        self.verbindung.execute(
            "UPDATE messages SET zustand = 'laeuft', dienst_port = ? WHERE id = ?",
            (self.db.dienst_port, message_id),
        )
        return self.holen(message_id)

    def inhalt_aktualisieren(
        self,
        message_id: str,
        *,
        content: str,
        reasoning: str | None = None,
        stats: dict[str, Any] | None = None,
        bild: str | None = None,
        zustand: str | None = None,
        gesamt_tokens: int | None = None,
    ) -> Message | None:
        """Needed for streaming: create a placeholder, fill it at the end.

        ``bild``: file name of a tool image under data/images/.
        COALESCE, so None does not wipe away an image that may exist.

        ``zustand`` and ``gesamt_tokens`` are COALESCEd like the picture,
        for the same reason: this method is called over and over WHILE a run
        writes, and a caller that only has new text must not blank the state
        or the context reading it does not carry. Both stay ``None`` on the
        running saves and are handed in when they are actually known — the
        token count as soon as a round reports it, the state when the run
        ends.

        The state is checked the way ``speichern`` checks it: a fresh
        database refuses an unknown one through its CHECK, an older one
        that migrated without the CHECKs would swallow it — one rule for
        both, applied before the write.
        """
        if zustand is not None and zustand not in ZUSTAENDE:
            raise ValueError(f"Unknown run state: {zustand!r}")
        self.verbindung.execute(
            "UPDATE messages SET content = ?, reasoning = ?, stats_json = ?, "
            + "bild = COALESCE(?, bild), "
            + "zustand = COALESCE(?, zustand), "
            + "gesamt_tokens = COALESCE(?, gesamt_tokens) "
            + "WHERE id = ?",
            (
                content,
                reasoning,
                json.dumps(stats, ensure_ascii=False) if stats else None,
                bild,
                zustand,
                gesamt_tokens,
                message_id,
            ),
        )
        return self.holen(message_id)

    def neueste_fuer_das_modell(self, *, chat_id: str) -> Message | None:
        """The newest row the model still sees — the last thing in its
        history. What stands there says whether a report has been read: a
        background report is followed by the answer that read it, or by
        nothing yet (``app/hintergrundwecken.py``)."""
        zeile = self.verbindung.execute(
            """
            SELECT * FROM messages
            WHERE chat_id = ? AND verdichtet_in IS NULL
            ORDER BY created_at DESC, rowid DESC
            LIMIT 1
            """,
            (chat_id,),
        ).fetchone()
        return Message.aus_zeile(zeile) if zeile else None

    def letzter_tokenstand(self, *, chat_id: str) -> int | None:
        """The newest context reading the model's history still carries.

        One row, asked of the database, rather than the whole history read
        and walked backwards for a single integer — which is what stood
        here before, three times per answer. Only rows the model still sees
        (`verdichtet_in IS NULL`): a row a summary speaks for is no longer
        in the prompt, so its reading must not stand in for the size of one.
        Zero is no reading, the same as before the walk moved here.
        """
        zeile = self.verbindung.execute(
            """
            SELECT gesamt_tokens FROM messages
            WHERE chat_id = ? AND verdichtet_in IS NULL
              AND gesamt_tokens IS NOT NULL AND gesamt_tokens != 0
            ORDER BY created_at DESC, rowid DESC
            LIMIT 1
            """,
            (chat_id,),
        ).fetchone()
        return int(zeile["gesamt_tokens"]) if zeile else None

    def tokenstand_setzen(self, message_id: str, gesamt_tokens: int) -> None:
        """The context reading, on its own and nothing else.

        A run reports its token count far more often than it flushes text,
        and the bar in the window is the only reader. Writing one integer
        beats rewriting the whole answer for it — and it cannot lose a
        concurrent text write, because it touches no other column.
        """
        self.verbindung.execute(
            "UPDATE messages SET gesamt_tokens = ? WHERE id = ?",
            (gesamt_tokens, message_id),
        )

    def _set_metric(self, message_id: str, key: str, wert, meldung: str) -> None:
        """Writes ONE key of a row's metrics and leaves the rest alone.

        The one road for both writers below: the blob is read, the key is
        set, the blob is written back — so a key written yesterday survives
        a key written today, whatever order they come in.

        A blob that is not valid JSON is left alone and logged: it is not
        this method's to repair, and a row whose metrics were thrown away
        costs more than the one value that could not be written.
        """
        zeile = self.verbindung.execute(
            "SELECT stats_json FROM messages WHERE id = ?", (message_id,)
        ).fetchone()
        if zeile is None:
            return
        try:
            stats = json.loads(zeile["stats_json"] or "{}")
        except (TypeError, ValueError):
            stats = None
        if not isinstance(stats, dict):
            log.warning("Message %s: metrics are not readable, %s", message_id, meldung)
            return
        stats[key] = wert
        self.verbindung.execute(
            "UPDATE messages SET stats_json = ? WHERE id = ?",
            (json.dumps(stats, ensure_ascii=False), message_id),
        )

    def dokumentstand_setzen(self, message_id: str, stand: dict[str, str]) -> None:
        """What the latest answer carried of each document on this row —
        ``ganz`` or ``kein_platz`` per document id — under the metrics key
        ``dokumente``.

        A card without the word is better than a row whose metrics were
        thrown away — the rule ``_set_metric`` above follows.
        """
        self._set_metric(message_id, "dokumente", dict(stand), "document state not written")

    def set_clock_sentence(self, message_id: str, sentence: str) -> None:
        """Remembers what a user turn carried in front of its text when it
        went out — under the metrics key ``clock_sentence``.

        That is the date block of that day
        (``app/grundprompt.environment_block``), or, in rows written before
        it, a sentence naming the very minute. A request is only read again
        from the first
        byte that differs: worked out fresh for every request, such a prefix
        would move one row in the middle of the history — every minute, or
        at the turn of the day — and make the server read everything behind
        it again (``app/verlaufsbau.py`` reads it back there). Written once,
        read back byte for byte.
        """
        self._set_metric(message_id, "clock_sentence", sentence, "clock sentence not written")

    def set_skill_invocation(self, message_id: str, text: str) -> None:
        """Remembers the skill the user picked for this turn — the note and
        the instruction that go in front of their words (app/skills.py,
        ``invocation``) — under the metrics key ``skill_invocation``. Out of the
        stored text, so the chat still shows what they typed; sent with the
        turn every time after, the way it first went out
        (``app/verlaufsbau.py``)."""
        self._set_metric(message_id, "skill_invocation", text, "skill invocation not written")

    def set_wake_notice(self, message_id: str, text: str) -> None:
        """Remembers the notice a wake was started with on the report that
        woke it (app/hintergrundwecken.py) — under the metrics key
        ``wake_notice``. It goes out behind the report in the user's turn
        from then on (``app/verlaufsbau.py``) instead of in the system
        message, which stays the same bytes; and it is never a row of its
        own, so nothing the user did not write stands as theirs."""
        self._set_metric(message_id, "wake_notice", text, "wake notice not written")

    def beim_start_aufraeumen(self, *, nur_eigene: bool = False) -> int:
        """Answers that were still being written when the service stopped.

        `zustand` only ever leaves 'laeuft' through the run's own closing
        write, so a service killed mid-stream leaves the row saying it is
        live forever — and nothing else would ever correct it. The window
        then draws that row as a running answer for good, waiting mark and
        clock included, and the context bar reads its token count as the
        current one.

        The same cleanup jobs have had since they existed
        (`auftraege.beim_start_aufraeumen`), and for the same reason: what
        was running at the last stop is, honestly, over. 'abgebrochen'
        rather than 'fertig' — the answer did not finish, and saying it did
        would hide that whatever it was writing was cut off.

        **It asks who wrote the row.** Every row put on 'laeuft' carries the
        port of the service that did it (`dienst_port`, schema.sql), so this
        statement can do what it could not before: run while a SECOND
        service is on the same data folder and still leave that service's
        live answer alone. Before the column it asked what state a row is in
        and never which process put it there — right only while this process
        was the only service on the folder, and `data_dir` does not vary
        with the port, so a trial run beside the running program read its
        live answer here and called it stranded. That is why the whole
        cleanup used to stay out as soon as a second service was up, and why
        rows the other one stranded stayed 'laeuft' for good.

        Which rows that is, exactly, stands at `_eigentuemer_filter` in
        the jobs repository — both cleanups share it, because both ask the
        same question of the same column.

        **An attempt that was to replace an answer is deleted, not marked.**
        A "regenerate" attempt that is stopped by hand leaves no row: the old
        answer stands (app/api/v1/generierung.py). A hard end is the same
        thing seen from outside, and marked stopped the attempt would stand
        beside the old answer as a second reply to one question. Only where
        the answer it names is still there; otherwise it is marked like
        every other row.
        """
        bedingung, eigner = _eigentuemer_filter(
            self.db.dienst_port, nur_eigene=nur_eigene
        )
        discarded_attempts = self.verbindung.execute(
            "DELETE FROM messages WHERE zustand = 'laeuft' AND replaces_id IS NOT NULL "
            "AND EXISTS (SELECT 1 FROM messages AS alt WHERE alt.id = messages.replaces_id) "
            + bedingung,
            eigner,
        )
        cursor = self.verbindung.execute(
            "UPDATE messages SET zustand = 'abgebrochen' WHERE zustand = 'laeuft' "
            + bedingung,
            eigner,
        )
        return discarded_attempts.rowcount + cursor.rowcount

    def verdichten(
        self, *, chat_id: str, text: str, ersetzte_ids: list[str]
    ) -> Message | None:
        """Folds a stretch of a chat into one summary — and DELETES nothing.

        A job could compact by rewriting the list it holds in memory, because
        that list lives for the whole task. A chat rebuilds its history from
        this table on every single request, so a compaction that is not
        written down here is undone by the next thing the user types.

        So the folded rows stay exactly where they are, readable, and only
        gain a pointer to the summary that now speaks for them. The model is
        handed the summary; the reader still has every line. That is the
        difference between compacting a conversation and losing it.

        The summary is timestamped INTO THE SEAM it closes — after the last
        row it replaces, before the first row it does not — and not "now":
        the list is ordered by creation time, and a summary written at the
        current moment would sort to the very end of the chat, behind the
        messages it is supposed to stand in FRONT of.

        Both ends of that seam are read here, and both are needed. `rowid`
        settles a tie in exactly one direction — the summary is the newest
        row, so a tie always puts it later — which is right against the row
        it must follow and wrong against the row it must precede. A step of
        one microsecond that is not checked against the next row therefore
        overshoots wherever the two rows are a single microsecond apart,
        which on Windows is every pair written inside one ~15.6 ms tick
        (`jetzt_iso`).

        The boundary is asked of the DATABASE rather than handed in by the
        caller. The caller knows the next row of ITS reading — the middle
        comes out of `fuer_das_modell`, which leaves already folded rows out
        — while `auflisten` shows those rows too and has to be ordered just
        as correctly. The next row of the CHAT covers both readings at once,
        and it is one less thing a caller can get wrong about a stretch it
        only names by id.

        Where the two rows carry the SAME stamp there is no moment between
        them and nothing here can invent one: the summary takes the stamp of
        the last folded row and `rowid` puts it behind the tying row, which
        is the defect above in the one shape that cannot be timestamped
        away. It is not reachable through `jetzt_iso`, whose stamps strictly
        increase per process; it takes two processes writing one database
        file, and that is a defect of its own and belongs with the fix for
        it. Not papered over here — the alternative would be to order the
        summary by its folded rows' position instead of by its own stamp,
        and `loeschen_ab` deletes BY TIMESTAMP, so a summary whose sort
        place no longer follows its stamp would start surviving deletions
        that take the rows it speaks for.

        All of it in one transaction. A summary without its pointers would
        be a duplicate of what it summarizes, and pointers without their
        summary would silently take that stretch out of the conversation.
        """
        if not ersetzte_ids or not text.strip():
            return None

        platzhalter = ",".join("?" for _ in ersetzte_ids)
        zeile = self.verbindung.execute(
            f"SELECT MAX(created_at) AS letzte FROM messages "  # noqa: S608 - only "?" placeholders
            f"WHERE chat_id = ? AND id IN ({platzhalter})",
            (chat_id, *ersetzte_ids),
        ).fetchone()
        letzte = zeile["letzte"] if zeile else None
        if letzte is None:
            return None

        # The other end of the seam: the earliest row of this chat that is
        # not one of the folded ones and does not sort before them. `>=`
        # rather than `>`, so a row that merely TIES with the last folded
        # one is seen — a tie is precisely the case that leaves no room, and
        # missing it would be the whole defect again. That a tying row might
        # in truth sort ahead of the block (lower `rowid`) costs nothing but
        # the microsecond: the summary keeps the stamp it must follow, which
        # is behind that row either way.
        zeile = self.verbindung.execute(
            f"SELECT MIN(created_at) AS naechste FROM messages "  # noqa: S608 - only "?" placeholders
            f"WHERE chat_id = ? AND created_at >= ? AND verdichtet_in IS NULL "
            f"AND id NOT IN ({platzhalter})",
            (chat_id, letzte, *ersetzte_ids),
        ).fetchone()
        naechste = zeile["naechste"] if zeile else None

        # A tie between the two ends: the first kept row carries the very
        # stamp of the last folded one. Two services writing one database
        # do that — each carries its own monotonic stamp forward — and then
        # the seam has no room at all: the summary keeps the folded row's
        # stamp and, being the newest row, sorts BEHIND the kept row it must
        # precede. So the room is made: every kept row on that stamp moves
        # two microseconds on, and the summary takes the one between. Rows
        # that already sat two microseconds on merely gain company on their
        # stamp, and `rowid` keeps them in the order they were written.
        # Only where the stamp can be stepped at all; an unreadable one is
        # left alone, as `_kurz_nach` leaves it.
        verschieben = None
        if naechste is not None and naechste == letzte:
            zwei_weiter = _kurz_nach(_kurz_nach(letzte))
            if zwei_weiter != letzte:
                verschieben = zwei_weiter
                naechste = zwei_weiter

        nachricht = Message(
            id=neue_id(),
            chat_id=chat_id,
            # `user`, matching what compaction already hands a job: the model
            # reads a summary of its own earlier work best when it arrives as
            # something it was TOLD, not as something it apparently said.
            role="user",
            content=text,
            created_at=_kurz_nach(letzte, vor=naechste),
            art="verdichtung",
        )
        with self.db.transaktion() as verbindung:
            if verschieben is not None:
                verbindung.execute(
                    # Only rows that still SPEAK move. A row an earlier fold
                    # already folded keeps its stamp: it is skipped for the
                    # model either way, and moving it re-sorted it behind the
                    # very summary that speaks for it in the reader's view —
                    # `_kurz_nach` itself creates such ties, a seam with no
                    # room keeps the last folded row's exact stamp.
                    f"UPDATE messages SET created_at = ? "  # noqa: S608 - only "?" placeholders
                    f"WHERE chat_id = ? AND created_at = ? AND verdichtet_in IS NULL "
                    f"AND id NOT IN ({platzhalter})",
                    (verschieben, chat_id, letzte, *ersetzte_ids),
                )
            verbindung.execute(
                """
                INSERT INTO messages (id, chat_id, role, content, created_at, art)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    nachricht.id, nachricht.chat_id, nachricht.role,
                    nachricht.content, nachricht.created_at, nachricht.art,
                ),
            )
            verbindung.execute(
                f"UPDATE messages SET verdichtet_in = ? "  # noqa: S608 - only "?" placeholders
                f"WHERE chat_id = ? AND id IN ({platzhalter})",
                (nachricht.id, chat_id, *ersetzte_ids),
            )
        return nachricht

    def fuer_das_modell(self, *, chat_id: str, limit: int = 500) -> list[Message]:
        """The history as the MODEL should see it: folded rows left out.

        `auflisten` stays what it is — everything, in order — because that is
        what the reader gets. This is the one other reading, and it differs
        by exactly one thing: a row that a summary already speaks for is not
        sent again. Its summary stands in the same place, so the order of
        the conversation is unchanged.

        ``limit`` is the backstop under all of that, and it used to cut from
        the front: `LIMIT 500` on an ascending read hands over the OLDEST
        five hundred unfolded rows. A chat past that point answered its
        newest question out of a history that stopped several hundred
        messages ago, and nothing anywhere said so. Worse than merely wrong:
        compaction reads its middle from THIS list, so it protected the tail
        of the first five hundred rows and folded around it, while the rows
        that were actually newest sat outside the reading entirely — neither
        sent, nor folded, nor protected.

        So the cut is taken from the front of the conversation now, which is
        the only end that can afford it, and three things travel with it:

        * **The opening stays pinned.** `chatverdichtung._mitte_suchen` never
          folds the first `ERSTE_FEST` rows, because they say what the
          conversation is ABOUT — and it identifies them by position, as
          ``zeilen[:ERSTE_FEST]`` of whatever this method returns. Handing
          back the newest N alone would put three arbitrary mid-conversation
          rows in that slot: the real opening would leave the model's view at
          row 501 and never come back, and compaction would pin a stretch it
          was never meant to pin. The same rows it protects are therefore the
          rows kept here, and the number is IMPORTED rather than repeated —
          a boundary written twice is a boundary that drifts.
        * **The gap says it is a gap.** A history that starts mid-sentence
          and does not admit it is a history the model will reason over as if
          it were whole. The notice below stands where the missing stretch
          was, and it is the one row in this list that has no row in the
          table behind it.
        * **Nothing is lost.** This is a reading. `auflisten` still carries
          every line, and the omitted rows are neither deleted nor marked.

        The cut is a backstop and not the mechanism: compaction is what keeps
        a chat's history small, and while it works this list never reaches
        ``limit``. It is reachable exactly where compaction cannot run — no
        context reading, or a model whose context size nobody confirmed — and
        it closes itself again as soon as folding brings the count back down.
        """
        # One row over the cap, so "the cap bit" is something this read KNOWS
        # rather than something a second query has to go and ask. Taken from
        # the newest end and turned around, so the rows that survive a cut
        # are the newest ones; under the cap this is the whole history in
        # exactly the order it always came back in.
        zeilen = [
            Message.aus_zeile(zeile)
            for zeile in reversed(
                self.verbindung.execute(
                    """
                    SELECT * FROM messages
                    WHERE chat_id = ? AND verdichtet_in IS NULL
                    ORDER BY created_at DESC, rowid DESC
                    LIMIT ?
                    """,
                    (chat_id, limit + 1),
                ).fetchall()
            )
        ]
        if len(zeilen) <= limit:
            return zeilen

        # Imported where it is used rather than at the top of the module: the
        # compaction policy sits above the database layer and pulls the
        # provider stack in behind it, and a repository that has to be
        # importable on its own should not carry that.
        from app.verdichtung import ERSTE_FEST

        # A cap with no room for an opening AND a notice AND a tail cannot
        # keep its promise, so it does not pretend to: the newest rows, and
        # nothing else. Not reachable from the program — the default is 500
        # and the one caller does not pass one — but a silent wrong answer
        # for a small `limit` is not something to leave lying in a backstop.
        if limit < ERSTE_FEST + 2:
            return zeilen[-limit:]

        # The opening is asked for separately, and it has to be: the read
        # above is the newest `limit + 1` rows, so ITS first rows are as far
        # from the start of the chat as the chat is long. Taking them would
        # have looked right in every list — three rows, in order, at the
        # front — while being three arbitrary rows out of the middle.
        anfang = [
            Message.aus_zeile(zeile)
            for zeile in self.verbindung.execute(
                """
                SELECT * FROM messages
                WHERE chat_id = ? AND verdichtet_in IS NULL
                ORDER BY created_at ASC, rowid ASC
                LIMIT ?
                """,
                (chat_id, ERSTE_FEST),
            ).fetchall()
        ]
        schwanz = zeilen[-(limit - len(anfang) - 1):]
        offen = self.verbindung.execute(
            "SELECT COUNT(*) AS anzahl FROM messages "
            "WHERE chat_id = ? AND verdichtet_in IS NULL",
            (chat_id,),
        ).fetchone()
        ausgelassen = int(offen["anzahl"]) - len(anfang) - len(schwanz)
        return [*anfang, self._luecke(chat_id, anfang, schwanz, ausgelassen), *schwanz]

    def bilder_von(self, *, chat_id: str | None = None, projekt_id: str | None = None) -> list[str]:
        """Every picture a chat's rows carry — drawn, attached or taken from
        a run — or those of every chat of a project; newest first, each name
        once. A picture lies once in the picture folder and belongs to a chat
        through the row that names it, and to a project through its chat."""
        if chat_id is None and projekt_id is None:
            return []
        bedingung, wert = ("m.chat_id = ?", chat_id) if chat_id is not None else ("c.project_id = ?", projekt_id)
        namen: list[str] = []
        gesehen: set[str] = set()
        for bild, bilder, anhaenge in self.verbindung.execute(
            f"""
            SELECT m.bild, m.bilder, m.anhaenge
            FROM messages m JOIN chats c ON c.id = m.chat_id
            WHERE {bedingung}
              AND (m.bild IS NOT NULL OR m.bilder IS NOT NULL OR m.anhaenge IS NOT NULL)
            ORDER BY m.created_at DESC, m.rowid DESC
            """,
            (wert,),
        ).fetchall():
            zeile: list[str] = []
            # A column that does not hold a list of names names nothing —
            # one damaged row must not stop a chat from being deleted.
            for liste in (bilder, anhaenge):
                zeile.extend(_namensliste(liste) or [])
            if bild:
                zeile.append(bild)
            # A run's pictures in the order they were drawn: the last one is
            # the newest.
            for name in reversed(zeile):
                if name not in gesehen:
                    gesehen.add(name)
                    namen.append(name)
        return namen

    def noch_genannt(self, namen: list[str]) -> set[str]:
        """Which of these pictures a row still names — drawn, attached or
        taken from a run. One pass over the rows that carry a picture at
        all, however many names are asked."""
        gesucht = set(namen)
        gefunden: set[str] = set()
        if not gesucht:
            return gefunden
        for bild, bilder, anhaenge in self.verbindung.execute(
            "SELECT bild, bilder, anhaenge FROM messages "
            "WHERE bild IS NOT NULL OR bilder IS NOT NULL OR anhaenge IS NOT NULL"
        ):
            if bild in gesucht:
                gefunden.add(bild)
            for liste in (bilder, anhaenge):
                gefunden.update(n for n in _namensliste(liste) or [] if n in gesucht)
        return gefunden

    def bildanhaenge(self, *, chat_id: str) -> list[str]:
        """The attached picture names of a chat's rows — the list the answer
        route warms its picture copies from (app/verlaufsbau.bilder_vorbereiten).
        A light pass of its own ON PURPOSE: the one history read
        stays the one (pinned in tests/test_generierung.py). Only rows that
        carry an attachment are read at all, and which of the columns wins is
        the model's own rule (`Message.anhang_bilder`, reached through
        `aus_zeile` — its narrow selects are anticipated there).

        Narrow like the send path, not wider:

        * only NON-assistant rows — a picture on an assistant row is its own
          work (a drawing) or a report's, and `_verlauf_bauen` answers those
          with a sentence instead of an image URL, never asking for a copy;
        * no folded rows — compaction took them out of every later request
          (`fuer_das_modell` leaves them out), so their pictures are never
          sent again either.

        The history read's 500-row backstop is deliberately NOT copied: its
        exact cut (pinned opening plus newest tail) would be this reading a
        second time, and warming a picture the tail leaves out costs one
        lookup — while a wrong cap would skip one the history keeps."""
        namen: list[str] = []
        for zeile in self.verbindung.execute(
            """
            SELECT id, chat_id, role, content, created_at, reasoning,
                   stats_json, anhaenge, bild
            FROM messages
            WHERE chat_id = ?
              AND role != 'assistant'
              AND verdichtet_in IS NULL
              AND (anhaenge IS NOT NULL OR bild IS NOT NULL)
            """,
            (chat_id,),
        ).fetchall():
            namen.extend(Message.aus_zeile(zeile).anhang_bilder())
        return namen

    def tool_entry_values(self, *, chat_id: str, key: str, newest: int) -> list[str]:
        """The newest ``newest`` text values stored under ``key`` in
        the tool entries of a chat's answers, oldest first — what the answer
        route warms the pictures of earlier tool reads from
        (app/verlaufsbau.py ``bilder_vorbereiten``). A light pass of its own
        for the same reason as :meth:`bildanhaenge`: the one history read
        stays the one. Only answers that stand in the model's history are
        read (no folded rows), only those whose log names the key at all,
        and newest first, so a long chat stops at the answers it needs."""
        newest_values: list[str] = []
        for zeile in self.verbindung.execute(
            """
            SELECT stats_json
            FROM messages
            WHERE chat_id = ?
              AND role = 'assistant'
              AND verdichtet_in IS NULL
              AND stats_json LIKE ?
            ORDER BY created_at DESC, rowid DESC
            """,
            (chat_id, f"%{key}%"),
        ):
            try:
                stats = json.loads(zeile["stats_json"] or "{}")
            except (TypeError, ValueError):
                continue
            eintraege = stats.get("werkzeuge") if isinstance(stats, dict) else None
            values = [
                eintrag[key]
                for eintrag in (eintraege if isinstance(eintraege, list) else [])
                if isinstance(eintrag, dict)
                and isinstance(eintrag.get(key), str)
                and eintrag[key]
            ]
            newest_values.extend(reversed(values))
            if len(newest_values) >= newest:
                break
        return list(reversed(newest_values[:newest]))

    def _luecke(
        self,
        chat_id: str,
        anfang: list[Message],
        schwanz: list[Message],
        ausgelassen: int,
    ) -> Message:
        """The stand-in for a stretch this reading had to leave out.

        Built, never stored. It exists only for the length of one request and
        is rebuilt from the same facts on the next one, so it heals itself:
        fold enough of the chat away and the gap closes and the notice is
        simply not there any more.

        Shaped like the summary `verdichten` writes, and for the same
        reasons. ``role='user'``, because a model reads a statement about its
        own earlier work best as something it was TOLD rather than as
        something it apparently said. ``art='verdichtung'``, because that is
        what `_mitte_suchen` reads to refuse a middle that is nothing but
        stand-ins — without it, a middle consisting of this one row would be
        sent off to be summarized, and a summary of a gap notice is a request
        spent on nothing.

        The id cannot collide with a real one (`neue_id` writes bare hex) and
        is stable per chat, so a reading taken twice names this row the same
        way twice. It reaches `verdichten` whenever the middle spans the gap:
        there it matches no row, updates nothing, and the notice is rebuilt
        on the next read as long as the gap is still there.

        Timestamped into the seam with the same helper the summary uses —
        after the opening, before the tail — so the list stays ordered the
        way every reader of it assumes.
        """
        return Message(
            id=f"luecke-{chat_id}",
            chat_id=chat_id,
            role="user",
            content=(
                f"[{ausgelassen} messages from this conversation are not included here. Its "
                "opening appears above this line and its most recent messages below. The "
                "intervening messages were omitted because the history no longer fits in a "
                "single request. Nothing was deleted; all messages remain in the chat.]"
            ),
            created_at=_kurz_nach(
                anfang[-1].created_at, vor=schwanz[0].created_at
            ),
            art="verdichtung",
        )

    def loeschen(self, message_id: str) -> bool:
        """Deletes one message — and never takes another one's voice with it.

        A summary speaks FOR the rows it folded: they stay in the chat and
        stop being sent, because it is sent instead. Delete the summary
        alone and those rows would be represented by nothing — still
        readable, but gone from what the model sees. The database releases
        whatever pointed at a deleted row (`messages_verdichtung_freigeben`
        in schema.sql), so every deletion path is covered, this one and the
        ones nobody has written yet.
        """
        with self.db.transaktion() as verbindung:
            cursor = verbindung.execute(
                "DELETE FROM messages WHERE id = ?", (message_id,)
            )
        return cursor.rowcount > 0

    def loeschen_ab(self, *, chat_id: str, ab_zeitstempel: str) -> int:
        """For "regenerate": discard everything from a point in the history on.

        A deletion by TIMESTAMP is exactly the shape that crosses a summary
        without meaning to; the rows that summary spoke for are released by
        the database the moment it goes (`messages_verdichtung_freigeben`),
        the same as for `loeschen` above.

        Nothing calls this today.
        """
        with self.db.transaktion() as verbindung:
            cursor = verbindung.execute(
                "DELETE FROM messages WHERE chat_id = ? AND created_at >= ?",
                (chat_id, ab_zeitstempel),
            )
        return cursor.rowcount

    def run_row(self, *, chat_id: str, lauf_kennung: str) -> Message | None:
        """The row a run's pictures stand in, or None while it has none."""
        # `lauf_id` is a column now, not a key dug out of the stats blob on
        # every row of the chat, and `art` says what this row is instead of
        # it having to pass as an answer. `bilder IS NOT NULL` stays as the
        # guarantee it always was — see the precedence note on `Message`.
        zeile = self.verbindung.execute(
            "SELECT * FROM messages WHERE chat_id = ? AND art = 'bildlauf' "
            "AND lauf_id = ? AND bilder IS NOT NULL "
            "ORDER BY created_at ASC, rowid ASC LIMIT 1",
            (chat_id, lauf_kennung),
        ).fetchone()
        return Message.aus_zeile(zeile) if zeile is not None else None

    def lauf_bild_speichern(
        self, *, chat_id: str, lauf_kennung: str, nr: int | None, von: int, bild: str,
        seed: int | None, drawn_with: dict | None = None,
    ) -> Message | None:
        """Images per run: a run's pictures all belong to ONE
        answer row. The first picture of a lauf to reach this creates it;
        every later one of the same run finds it again and is written
        into its own place in the list — by `nr`, not by arrival order,
        so a picture that finishes out of turn still lands where it
        belongs instead of after whatever got there first. A gap left by
        a picture that has not finished (or never will) stays `None`,
        never a placeholder string — the true count is whatever is not
        `None`, not the length of the list.

        ``nr=None`` is a run whose size nobody knows beforehand — the
        pictures a model draws while it answers: the picture takes the
        next place at the end and the run's ``von`` grows with it, so the
        total is always the number of pictures that are there and never
        reads as a shortfall. ``von`` is not read in that case.

        Read-modify-write, not COALESCE: a naive single-value overwrite
        would replace the whole list instead of adding to it — the exact
        trap `inhalt_aktualisieren` above avoids for `bild`, and the
        reason this reads the existing row before writing anything back.

        ``drawn_with`` is what this picture was drawn with. It stands
        beside the picture's seed, place by place like the seeds, so each
        picture of a run keeps its own (``drawn_with`` below reads it).
        """
        if nr is not None and nr < 1:
            raise ValueError(f"nr must be at least 1; received {nr}.")

        bestehend = self.run_row(chat_id=chat_id, lauf_kennung=lauf_kennung)
        grows = nr is None
        if nr is None:
            # The next place at the end; the run is exactly that long now.
            nr = len(bestehend.bilder or []) + 1 if bestehend is not None else 1
            von = nr
        if bestehend is None:
            bilder: list[str | None] = [None] * von
            bilder[nr - 1] = bild
            seeds: list[int | None] = [None] * von
            seeds[nr - 1] = seed
            stats: dict[str, Any] = {"von": von, "seeds": seeds}
            if drawn_with is not None:
                stats["drawn_with"] = [None] * von
                stats["drawn_with"][nr - 1] = drawn_with
            nachricht = Message(
                id=neue_id(),
                chat_id=chat_id,
                # Still `assistant` for the model's history — this row does
                # belong to the answer's turn — but `art` now says out loud
                # that it is a picture row and not the answer itself, so
                # nothing mistakes it for a reply that is still being
                # written. `von` stays in `stats`: it is the run's own
                # arithmetic, read only where the tiles are drawn.
                role="assistant",
                content="",
                created_at=self.zeitstempel(),
                stats=stats,
                bilder=bilder,
                art="bildlauf",
                lauf_id=lauf_kennung,
            )
            self.verbindung.execute(
                """
                INSERT INTO messages (id, chat_id, role, content, stats_json, bilder,
                                      created_at, art, lauf_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    nachricht.id, nachricht.chat_id, nachricht.role, nachricht.content,
                    json.dumps(nachricht.stats, ensure_ascii=False),
                    json.dumps(nachricht.bilder), nachricht.created_at,
                    nachricht.art, nachricht.lauf_id,
                ),
            )
            return nachricht

        bilder = list(bestehend.bilder or [])
        while len(bilder) < von:
            bilder.append(None)
        bilder[nr - 1] = bild
        stats = dict(bestehend.stats)
        seeds = list(stats.get("seeds") or [])
        while len(seeds) < von:
            seeds.append(None)
        seeds[nr - 1] = seed
        stats["seeds"] = seeds
        if drawn_with is not None:
            drawn = list(stats.get("drawn_with") or [])
            while len(drawn) < von:
                drawn.append(None)
            drawn[nr - 1] = drawn_with
            stats["drawn_with"] = drawn
        if grows:
            stats["von"] = von
        self.verbindung.execute(
            "UPDATE messages SET bilder = ?, stats_json = ? WHERE id = ?",
            (json.dumps(bilder), json.dumps(stats, ensure_ascii=False), bestehend.id),
        )
        return self.holen(bestehend.id)

    def drawn_with(self, name: str) -> dict:
        """What the picture of this name was drawn with, as the draw kept
        it beside the picture's seed: in the stats of the picture's own row,
        or at the picture's place in the row of its run. Empty for a picture
        no row carries and for one drawn before this was kept. The values go
        with the row — a deleted row takes them along."""
        for bild, bilder, stats_json in self.verbindung.execute(
            "SELECT bild, bilder, stats_json FROM messages "
            "WHERE bild = ? OR bilder LIKE ? ORDER BY created_at DESC, rowid DESC",
            (name, f'%"{name}"%'),
        ).fetchall():
            try:
                kept = json.loads(stats_json or "{}").get("drawn_with")
                names = json.loads(bilder or "[]")
            except (ValueError, AttributeError):
                continue
            if bild == name and isinstance(kept, dict):
                return kept
            if isinstance(kept, list) and isinstance(names, list) and name in names:
                place = names.index(name)
                if place < len(kept) and isinstance(kept[place], dict):
                    return kept[place]
        return {}

    def lauf_hat_nachricht(self, *, chat_id: str, lauf_kennung: str) -> bool:
        """Has this images-per-run lauf's own QUESTION already landed in
        this chat? Images per run can fail partway through (a picture's own
        draw fails before a message is ever written for it) — this is how
        the route tells "nobody has written this lauf's question yet"
        apart from "somebody already did", regardless of which position in
        the run actually made it first.

        Checked against the question specifically (role='user'), not any
        row carrying the lauf: a picture surviving the question's own
        deletion (regenerate, "send again") would otherwise still count as
        proof a question exists, and the question would then be gone for
        good — nothing left ever writing it again."""
        zeile = self.verbindung.execute(
            "SELECT 1 FROM messages WHERE chat_id = ? AND role = 'user' "
            "AND lauf_id = ? LIMIT 1",
            (chat_id, lauf_kennung),
        ).fetchone()
        return zeile is not None

    def anzahl(self, *, chat_id: str) -> int:
        zeile = self.verbindung.execute(
            "SELECT COUNT(*) AS anzahl FROM messages WHERE chat_id = ?", (chat_id,)
        ).fetchone()
        return int(zeile["anzahl"])

    def dokument_angehaengt(self, document_id: str) -> bool:
        """Whether any message already carries this document (4.1).

        The guard for dropping an upload that never made it into a sent
        message: a document a chat merely uploaded on attaching it is free
        to delete, but once a message carries it, only that message's own
        ✕ (`anhang_entfernen` above) may remove it. Run in SQL, not by
        paging every message in Python — `auflisten` pages at 500, and a
        long chat would make this check the slow, incomplete kind.
        """
        zeile = self.verbindung.execute(
            """
            SELECT 1 FROM messages
            WHERE dokument = ?
               OR EXISTS (SELECT 1 FROM json_each(dokumente) WHERE value = ?)
            LIMIT 1
            """,
            (document_id, document_id),
        ).fetchone()
        return zeile is not None
