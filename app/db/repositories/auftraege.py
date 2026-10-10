"""Access to jobs and their transcript.

The states are listed here again even though the database already enforces
them via CHECK: the code should be able to report a typo before SQLite
answers with a terse IntegrityError.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from app.db.models import Auftrag, AuftragSchritt
from app.db.repositories.base import Repository, neue_id

ZUSTAENDE = {"laeuft", "wartet", "fertig", "abgebrochen", "gescheitert", "unterbrochen"}

# States in which a job is over. Everything else is still alive.
ENDZUSTAENDE = {"fertig", "abgebrochen", "gescheitert", "unterbrochen"}

# Runs a cron entry's own history (app/api/v1/cronjobs.py) can report an
# outcome for. ``unterbrochen`` is a run that can still be resumed, not a
# result — it is left out, along with the still-active ``laeuft``/``wartet``.
CRONJOB_AUSGAENGE = {"fertig": "gut", "gescheitert": "gescheitert", "abgebrochen": "gescheitert"}


def _eigentuemer_filter(
    port: int | None, *, nur_eigene: bool
) -> tuple[str, tuple[int | None, ...]]:
    """Which rows a startup cleanup may touch, as SQL and its bindings.

    Both halves come from one call on purpose: the condition and the value
    it binds are the same decision, and handing them out separately is how
    a statement ends up with a binding it no longer has a `?` for.

    Two lands, and the caller knows which one it stands in.

    **Alone on the data folder** (``nur_eigene`` false): everything that says
    'laeuft' is over, whoever wrote it. That is what the cleanup has always
    done and has to keep doing — a service that died on another port left
    rows nobody else will ever come back for, and an unsigned row from
    before this column has nobody to come back at all. Narrowing this case
    to our own port would trade one leak for another.

    **Beside a second, LIVING service** (``nur_eigene`` true): only rows
    carrying our own port. Everything else may be that service's live work,
    and calling a live run stranded is the damage this column exists to
    prevent. Unsigned rows stay too: a NULL means "nobody said", and one of
    its causes is a service that knows no port of its own.

    The third case — a second service on the SAME port — is not decided
    here: there the stamp cannot tell the two apart, and the caller leaves
    the cleanup out entirely (app/main.py).

    Placed here rather than written twice: jobs and answers ask the same
    question of the same column, and two copies of it would drift.

    Refuses ``nur_eigene`` without a port instead of building
    ``dienst_port = NULL``, which matches no row in SQLite: the cleanup
    would report nothing to clean and be believed. A service always knows
    its port; a connection that does not (a script opening the database by
    path) is never in the narrow case to begin with.
    """
    if nur_eigene and port is None:
        raise ValueError(
            "A cleanup narrowed to its own rows needs the port of the "
            "service running it (Database.dienst_port), and none was given."
        )
    return ("AND dienst_port = ?", (port,)) if nur_eigene else ("", ())


def _stored(moment: datetime) -> str:
    """A moment in the form ``created_at`` is stored in (UTC, microseconds)."""
    return moment.astimezone(timezone.utc).isoformat(timespec="microseconds")


class AuftragRepository(Repository):
    # --- Jobs ------------------------------------------------------------

    def erstellen(
        self,
        *,
        user_id: str,
        agent: str,
        auftrag: str,
        endpoint_id: str | None = None,
        zustand: str = "laeuft",
        cronjob_id: str | None = None,
        eltern_id: str | None = None,
        chat_id: str | None = None,
    ) -> Auftrag:
        self._zustand_pruefen(zustand)
        eintrag = Auftrag(
            id=neue_id(),
            user_id=user_id,
            agent=agent,
            auftrag=auftrag,
            zustand=zustand,
            endpoint_id=endpoint_id,
            cronjob_id=cronjob_id,
            eltern_id=eltern_id,
            chat_id=chat_id,
            created_at=self.zeitstempel(),
            updated_at=self.zeitstempel(),
        )
        self.verbindung.execute(
            """
            INSERT INTO auftraege (id, user_id, agent, auftrag, zustand,
                                   endpoint_id, cronjob_id, eltern_id,
                                   dienst_port, chat_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                eintrag.id,
                eintrag.user_id,
                eintrag.agent,
                eintrag.auftrag,
                eintrag.zustand,
                eintrag.endpoint_id,
                eintrag.cronjob_id,
                eintrag.eltern_id,
                # Signed at birth where the row is born running — which is
                # the ordinary case here (`zustand` defaults to 'laeuft').
                self.db.dienst_port if eintrag.zustand == "laeuft" else None,
                eintrag.chat_id,
                eintrag.created_at,
                eintrag.updated_at,
            ),
        )
        return eintrag

    def open_for_chat(self, chat_id: str) -> list[Auftrag]:
        """The runs of a chat that are not over yet — running or standing on
        a question — oldest first."""
        rows = self.verbindung.execute(
            "SELECT * FROM auftraege WHERE chat_id = ? AND zustand IN ('laeuft', 'wartet')"
            " ORDER BY created_at, rowid",
            (chat_id,),
        ).fetchall()
        return [Auftrag.aus_zeile(row) for row in rows]

    def ids_for_chat(self, chat_id: str) -> list[str]:
        """Every run a chat's work ever had, in any state."""
        rows = self.verbindung.execute(
            "SELECT id FROM auftraege WHERE chat_id = ?", (chat_id,)
        ).fetchall()
        return [row["id"] for row in rows]

    def chats_and_projects(self) -> dict[str, tuple[str, str | None]]:
        """Every job that came from a chat still there: its chat, and that
        chat's project. One read for the doc folder (app/docfolder.py)."""
        rows = self.verbindung.execute(
            "SELECT auftraege.id, chats.id AS chat_id, chats.project_id"
            " FROM auftraege JOIN chats ON chats.id = auftraege.chat_id"
        ).fetchall()
        return {row["id"]: (row["chat_id"], row["project_id"]) for row in rows}

    def cron_job_ids(self) -> set[str]:
        """Every job a cron entry started. One read for the doc folder
        (app/docfolder.py), which tells a cron job's delivery from one of a
        job started by hand."""
        rows = self.verbindung.execute(
            "SELECT id FROM auftraege WHERE cronjob_id IS NOT NULL"
        ).fetchall()
        return {row["id"] for row in rows}

    def kinder(self, auftrag_id: str) -> list[Auftrag]:
        """The runs this one started, oldest first.

        One level, not the whole tree: cancelling walks down link by link
        (app/api/v1/auftraege.py), and a query that fetched the tree in one
        go would have to know how deep it goes — and no depth is fixed.
        """
        zeilen = self.verbindung.execute(
            "SELECT * FROM auftraege WHERE eltern_id = ? ORDER BY created_at, rowid",
            (auftrag_id,),
        ).fetchall()
        return [Auftrag.aus_zeile(zeile) for zeile in zeilen]

    def holen(self, auftrag_id: str, *, user_id: str | None = None) -> Auftrag | None:
        sql = "SELECT * FROM auftraege WHERE id = ?"
        parameter: list[object] = [auftrag_id]
        if user_id is not None:
            sql += " AND user_id = ?"
            parameter.append(user_id)
        zeile = self.verbindung.execute(sql, parameter).fetchone()
        return Auftrag.aus_zeile(zeile) if zeile else None

    def auflisten(
        self, *, user_id: str, limit: int = 100, offset: int = 0
    ) -> list[Auftrag]:
        """Most recently touched first. rowid as tiebreaker, as with chats."""
        zeilen = self.verbindung.execute(
            "SELECT * FROM auftraege WHERE user_id = ? "
            "ORDER BY updated_at DESC, rowid DESC LIMIT ? OFFSET ?",
            (user_id, limit, offset),
        ).fetchall()
        return [Auftrag.aus_zeile(zeile) for zeile in zeilen]

    def zustand_setzen(
        self,
        auftrag_id: str,
        zustand: str,
        *,
        ende_grund: str | None = None,
        ergebnis: str | None = None,
    ) -> Auftrag | None:
        """Sets the state — and, at an ending, the readable reason (6.4).

        ``ende_grund`` and ``ergebnis`` are only written when they come
        along: a state change ``wartet`` → ``laeuft`` must not wipe away a
        previously set reason.
        """
        self._zustand_pruefen(zustand)
        zuweisungen = ["zustand = ?", "updated_at = ?"]
        werte: list[object] = [zustand, self.zeitstempel()]
        # Whoever puts a row on 'laeuft' signs it. Only here, and never
        # cleared afterwards by an ENDING: the signature is what the startup
        # cleanup asks for, and a row that ended keeps saying who ran it,
        # which costs nothing and reads better in the database.
        #
        # A connection with no port of its own writes NULL here, and that is
        # the honest answer, not a lost signature: whatever ran that row
        # this time round, nobody named a port for it. NULL means "nobody
        # said", and the cleanup treats it as such — cleaned when this
        # service is alone on the folder, left alone beside a second one.
        if zustand == "laeuft":
            zuweisungen.append("dienst_port = ?")
            werte.append(self.db.dienst_port)
        if ende_grund is not None:
            zuweisungen.append("ende_grund = ?")
            werte.append(ende_grund)
        if ergebnis is not None:
            zuweisungen.append("ergebnis = ?")
            werte.append(ergebnis)
        werte.append(auftrag_id)
        self.verbindung.execute(
            f"UPDATE auftraege SET {', '.join(zuweisungen)} WHERE id = ?", werte
        )
        return self.holen(auftrag_id)

    def generation_verknuepfen(self, auftrag_id: str, generation_id: str | None) -> None:
        """Remembers the living in-memory run — or clears the reference."""
        self.verbindung.execute(
            "UPDATE auftraege SET generation_id = ? WHERE id = ?",
            (generation_id, auftrag_id),
        )

    def zwischenstand_setzen(self, auftrag_id: str, text: str | None) -> None:
        """The run's own running status, written after every
        round rather than only at the context-full handoff or a provider
        outage — so a hard restart always finds something to resume a job
        from. Bookkeeping, not user-visible activity: ``updated_at`` is left
        alone, the same as ``generation_verknuepfen`` above.

        ``None`` clears it — marks a resumption as already scheduled, so the
        next service start does not find this same row again through
        ``unterbrochene_mit_zwischenstand`` and plan a second one for it."""
        self.verbindung.execute(
            "UPDATE auftraege SET zwischenstand = ? WHERE id = ?",
            (text, auftrag_id),
        )

    def frage_setzen(self, auftrag_id: str, text: str | None) -> None:
        """The question a run is standing on — ``None`` clears it.

        Bookkeeping about the same moment ``zustand_setzen`` records, so it
        leaves ``updated_at`` alone: the state change beside it is what
        moves the row in the list, and stamping twice would move it twice.
        """
        self.verbindung.execute(
            "UPDATE auftraege SET frage = ? WHERE id = ?", (text, auftrag_id)
        )

    def loeschen(self, auftrag_id: str, *, user_id: str | None = None) -> bool:
        """Deletes the job along with its transcript (ON DELETE CASCADE)."""
        sql = "DELETE FROM auftraege WHERE id = ?"
        parameter: list[object] = [auftrag_id]
        if user_id is not None:
            sql += " AND user_id = ?"
            parameter.append(user_id)
        cursor = self.verbindung.execute(sql, parameter)
        return cursor.rowcount > 0

    def anzahl(self, *, user_id: str) -> int:
        zeile = self.verbindung.execute(
            "SELECT COUNT(*) AS anzahl FROM auftraege WHERE user_id = ?", (user_id,)
        ).fetchone()
        return int(zeile["anzahl"])

    # --- For the alarm clock (6.7) ---------------------------------------

    def laeuft_gerade(self, *, agent: str) -> bool:
        """Whether a run of the agent is still active (running or waiting)."""
        return self.open_count(agent=agent) > 0

    def open_count(self, *, agent: str) -> int:
        """How many runs of the agent are still active (running or waiting)."""
        row = self.verbindung.execute(
            "SELECT COUNT(*) FROM auftraege WHERE agent = ? "
            "AND zustand IN ('laeuft', 'wartet')",
            (agent,),
        ).fetchone()
        return int(row[0])

    def laeuft_fuer_cronjob(self, cronjob_id: str) -> bool:
        """Whether a run this ONE cron entry started is still going.

        The agent-name question above cannot answer this for a script entry:
        every script entry carries the same marker in ``agent``
        (app/skriptlauf.py), so asking by name would let one long backup hold
        up every other script in the table. The entry's own id is the only
        thing that is per entry, and it is already on the run.
        """
        zeile = self.verbindung.execute(
            "SELECT 1 FROM auftraege WHERE cronjob_id = ? "
            "AND zustand IN ('laeuft', 'wartet') LIMIT 1",
            (cronjob_id,),
        ).fetchone()
        return zeile is not None

    def previous_run(self, cronjob_id: str, current_id: str) -> Auftrag | None:
        """The newest run this cron entry fired other than ``current_id`` —
        the run right before it, however that one ended. Unlike the history
        below, a run that handed its work on (``unterbrochen``) counts: it is
        the step just before, and skipping it would reach past it to an
        older one."""
        zeile = self.verbindung.execute(
            "SELECT * FROM auftraege WHERE cronjob_id = ? AND id != ? "
            "ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (cronjob_id, current_id),
        ).fetchone()
        return Auftrag.aus_zeile(zeile) if zeile else None

    # --- For the cron settings list -----------------------------------------

    def laeufe_fuer_cronjob(self, cronjob_id: str) -> list[Auftrag]:
        """Ended runs a cron entry fired, newest first — the source for
        History and Failed runs. A cron entry with no runs
        yet, or none that ever reached an outcome, gets an empty list."""
        platzhalter = ", ".join("?" for _ in CRONJOB_AUSGAENGE)
        zeilen = self.verbindung.execute(
            f"SELECT * FROM auftraege WHERE cronjob_id = ? "
            f"AND zustand IN ({platzhalter}) ORDER BY created_at DESC, rowid DESC",
            (cronjob_id, *CRONJOB_AUSGAENGE.keys()),
        ).fetchall()
        return [Auftrag.aus_zeile(zeile) for zeile in zeilen]

    def alle_cronlaeufe(self, *, je_termin: int = 5) -> list[Auftrag]:
        """The newest ended runs of every schedule, newest first — whether or
        not the entry that fired it still exists.

        Capped per schedule, not overall: one cap for all of them let a busy
        schedule push every older one out, and a schedule whose last run
        failed weeks ago showed no runs at all beside its red dot. Five per
        schedule are what its page shows.

        The history used to be gathered per ENTRY: one request each, and a
        run whose entry had been deleted was gone from the window although it
        was still in the table. Measured on a live installation: 155 runs,
        none of them visible, because the schedules had been removed. A
        history that empties when you delete a schedule is not a history.

        Same outcome filter as ``laeufe_fuer_cronjob`` — a run still going,
        waiting, or cut off by a restart has no outcome to list yet.
        """
        platzhalter = ", ".join("?" for _ in CRONJOB_AUSGAENGE)
        zeilen = self.verbindung.execute(
            f"SELECT * FROM ("
            f"SELECT *, ROW_NUMBER() OVER ("
            f"PARTITION BY cronjob_id ORDER BY created_at DESC, rowid DESC"
            f") AS platz FROM auftraege WHERE cronjob_id IS NOT NULL "
            f"AND zustand IN ({platzhalter})"
            f") WHERE platz <= ? ORDER BY created_at DESC",
            (*CRONJOB_AUSGAENGE.keys(), je_termin),
        ).fetchall()
        return [Auftrag.aus_zeile(zeile) for zeile in zeilen]

    def cron_runs_between(
        self, start: datetime, end: datetime
    ) -> list[tuple[str, str, str, str, str]]:
        """Every run a schedule fired whose start lies in ``[start, end)``,
        in any state, as ``(cronjob_id, created_at, agent, task, state)`` —
        for the calendar (app/schedule_calendar.py), which shows what happened
        on a day, not only what ended well, and the state of the latest run
        beside it: a schedule every minute leaves forty thousand runs in a
        month, and their results are not read here.

        The bounds are turned into the stored form (UTC, ``jetzt_iso``)
        first: the column compares as text, and a bound written with another
        offset would cut the day in the wrong place."""
        rows = self.verbindung.execute(
            "SELECT cronjob_id, created_at, agent, auftrag, zustand FROM auftraege "
            "WHERE cronjob_id IS NOT NULL AND created_at >= ? AND created_at < ? "
            "ORDER BY created_at",
            (_stored(start), _stored(end)),
        ).fetchall()
        return [(row[0], row[1], row[2], row[3], row[4]) for row in rows]

    def letzte_auslaeufe(self) -> dict[str, str]:
        """Most recent outcome ('gut'/'gescheitert') per cron entry, in one
        query — so the cronjob list (``letzter_ausgang``) does not need a
        second request per entry to know whether its last run failed.

        Same 'newest' rule as ``letzter_auslauf`` and ``laeufe_fuer_cronjob``
        — ``created_at`` first, ``rowid`` only as its tiebreaker — so all
        three agree on which run is the last one, even if a clock ever ran
        backwards between two inserts. A window function ranks every ended
        run within its own cron entry in one pass; a correlated subquery
        expressing the same rule rescans the table per row and turns
        quadratic on a cron entry with a long history."""
        platzhalter = ", ".join("?" for _ in CRONJOB_AUSGAENGE)
        # ROW_NUMBER() OVER (...) needs SQLite >= 3.25 (2018); the bundled
        # interpreter carries its own (3.53), so this is a note for anyone
        # running against a system copy, not a runtime risk.
        zeilen = self.verbindung.execute(
            f"""
            SELECT cronjob_id, zustand FROM (
                SELECT cronjob_id, zustand,
                       ROW_NUMBER() OVER (
                           PARTITION BY cronjob_id
                           ORDER BY created_at DESC, rowid DESC
                       ) AS rang
                FROM auftraege
                WHERE cronjob_id IS NOT NULL AND zustand IN ({platzhalter})
            )
            WHERE rang = 1
            """,
            tuple(CRONJOB_AUSGAENGE.keys()),
        ).fetchall()
        return {zeile["cronjob_id"]: CRONJOB_AUSGAENGE[zeile["zustand"]] for zeile in zeilen}

    def letzte_kontextstaende(self, auftrag_ids: list[str]) -> dict[str, str]:
        """The newest ``kontext`` step of each of these runs, as written —
        in one query, so the job list can carry every run's context reading
        without fetching a transcript per row. A run without one is missing
        from the result.

        "Newest" is the highest step number, the transcript's own order:
        SQLite hands a bare column of a ``MAX()`` aggregate over from the
        row that holds the maximum. The ids go in slices, so a page of any
        size stays under SQLite's limit on bound parameters."""
        staende: dict[str, str] = {}
        for anfang in range(0, len(auftrag_ids), 500):
            teil = auftrag_ids[anfang:anfang + 500]
            platzhalter = ", ".join("?" for _ in teil)
            zeilen = self.verbindung.execute(
                f"SELECT auftrag_id, inhalt, MAX(nummer) FROM auftrag_schritte "
                f"WHERE typ = 'kontext' AND auftrag_id IN ({platzhalter}) "
                f"GROUP BY auftrag_id",
                tuple(teil),
            ).fetchall()
            staende.update({zeile["auftrag_id"]: zeile["inhalt"] for zeile in zeilen})
        return staende

    def last_tool_calls(self, auftrag_ids: list[str]) -> dict[str, str]:
        """The tool each of these runs called last, by name — the step a
        chat's agent row shows. One query per slice, the way
        ``letzte_kontextstaende`` reads the context readings."""
        names: dict[str, str] = {}
        for start in range(0, len(auftrag_ids), 500):
            part = auftrag_ids[start:start + 500]
            placeholders = ", ".join("?" for _ in part)
            rows = self.verbindung.execute(
                f"SELECT auftrag_id, inhalt, MAX(nummer) FROM auftrag_schritte "
                f"WHERE typ = 'tool_call' AND auftrag_id IN ({placeholders}) "
                f"GROUP BY auftrag_id",
                tuple(part),
            ).fetchall()
            for row in rows:
                try:
                    name = json.loads(row["inhalt"]).get("name")
                except (ValueError, AttributeError):
                    continue
                if isinstance(name, str) and name:
                    names[row["auftrag_id"]] = name
        return names

    def letzter_auslauf(self, cronjob_id: str) -> str | None:
        """Same outcome as ``letzte_auslaeufe``, for the one cron entry a
        route already has in hand (``/pause``, ``/resume``) — so their
        response does not silently claim 'no outcome yet' for an entry the
        list endpoint reports one for."""
        platzhalter = ", ".join("?" for _ in CRONJOB_AUSGAENGE)
        zeile = self.verbindung.execute(
            f"SELECT zustand FROM auftraege WHERE cronjob_id = ? "
            f"AND zustand IN ({platzhalter}) ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (cronjob_id, *CRONJOB_AUSGAENGE.keys()),
        ).fetchone()
        return CRONJOB_AUSGAENGE[zeile["zustand"]] if zeile else None

    # --- Transcript ------------------------------------------------------

    def schritt_anlegen(self, auftrag_id: str, typ: str, inhalt: str) -> AuftragSchritt:
        """Appends a line to the transcript. The number counts from 1 per job.

        MAX+1 instead of a dedicated counter: SQLite allows only one writer
        at a time anyway, so a race for the same number is ruled out.
        """
        schritt = AuftragSchritt(
            id=neue_id(),
            auftrag_id=auftrag_id,
            nummer=0,
            typ=typ,
            inhalt=inhalt,
            created_at=self.zeitstempel(),
        )
        cursor = self.verbindung.execute(
            """
            INSERT INTO auftrag_schritte (id, auftrag_id, nummer, typ, inhalt, created_at)
            VALUES (?, ?,
                    (SELECT COALESCE(MAX(nummer), 0) + 1
                       FROM auftrag_schritte WHERE auftrag_id = ?),
                    ?, ?, ?)
            RETURNING nummer
            """,
            (schritt.id, auftrag_id, auftrag_id, typ, inhalt, schritt.created_at),
        )
        schritt.nummer = int(cursor.fetchone()["nummer"])
        return schritt

    def schritt_fortschreiben(self, schritt_id: str, inhalt: str) -> None:
        """Rewrites ONE transcript line instead of appending a new one.

        A tool call reports while it is still being written — measured: 36,
        74 and 87 events for a single call. A line per event would bury the
        transcript it exists to make readable, so the caller keeps the id of
        the line it opened for this call and updates it here as the argument
        grows. The caller holds that id because it lives exactly as long as
        the run does (app/api/v1/auftraege.py); nothing about it belongs in
        the database.

        What a reader sees is the line moving: the tool's name and how much
        of its argument has arrived so far.
        """
        self.verbindung.execute(
            "UPDATE auftrag_schritte SET inhalt = ? WHERE id = ?",
            (inhalt, schritt_id),
        )

    def schritte(self, auftrag_id: str) -> list[AuftragSchritt]:
        zeilen = self.verbindung.execute(
            "SELECT * FROM auftrag_schritte WHERE auftrag_id = ? ORDER BY nummer",
            (auftrag_id,),
        ).fetchall()
        return [AuftragSchritt.aus_zeile(zeile) for zeile in zeilen]

    # --- Service startup -------------------------------------------------

    def beim_start_aufraeumen(self, *, nur_eigene: bool = False) -> int:
        """Whatever is on ``laeuft`` becomes ``unterbrochen`` — ``wartet`` stays.

        After a restart, a running background
        task no longer exists, so the job is, honestly, interrupted. A
        waiting confirmation prompt, on the other hand, can still be
        answered — it only loses its dead in-memory reference.

        Under ``nur_eigene`` both statements skip a row that carries no
        port, the ``wartet`` one included. A prompt left open across the
        upgrade that added the column has never been signed, so the first
        start after it — and only if a second service is up at that very
        moment — leaves its dead ``generation_id`` in place one more time.
        The next start alone on the folder clears it.
        """
        bedingung, eigner = _eigentuemer_filter(
            self.db.dienst_port, nur_eigene=nur_eigene
        )
        cursor = self.verbindung.execute(
            "UPDATE auftraege SET zustand = 'unterbrochen', ende_grund = ?, "
            "generation_id = NULL, updated_at = ? WHERE zustand = 'laeuft' "
            + bedingung,
            ("dienst_neustart", self.zeitstempel(), *eigner),
        )
        self.verbindung.execute(
            "UPDATE auftraege SET generation_id = NULL WHERE zustand = 'wartet' "
            + bedingung,
            eigner,
        )
        return cursor.rowcount

    def unterbrochene_mit_zwischenstand(
        self, *, nur_eigene: bool = False
    ) -> list[Auftrag]:
        """Jobs a hard restart just cut off mid-run that have something to
        resume from — the periodic write during the run is what
        makes this non-empty even for one that never crossed the context
        threshold or survived to a provider-outage retry. Called right
        after ``beim_start_aufraeumen`` moved them to ``unterbrochen``.

        ``nur_eigene`` asks the same ownership question that cleanup asks,
        and for the same reason: this is the third write of one startup, and
        picking up a job another service owns would restart work that
        service may well be doing right now. The state is no filter of its
        own here — 'unterbrochen' is exactly what the other service's
        cleanup writes when IT restarts.
        """
        bedingung, eigner = _eigentuemer_filter(
            self.db.dienst_port, nur_eigene=nur_eigene
        )
        zeilen = self.verbindung.execute(
            "SELECT * FROM auftraege WHERE zustand = 'unterbrochen' "
            "AND ende_grund = 'dienst_neustart' AND zwischenstand IS NOT NULL "
            + bedingung,
            eigner,
        ).fetchall()
        return [Auftrag.aus_zeile(zeile) for zeile in zeilen]

    # --- Internal --------------------------------------------------------

    @staticmethod
    def _zustand_pruefen(zustand: str) -> None:
        if zustand not in ZUSTAENDE:
            raise ValueError(
                f"Unbekannter Zustand '{zustand}'. "
                f"Erlaubt: {', '.join(sorted(ZUSTAENDE))}"
            )
