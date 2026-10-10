"""Access to the cron table — independent, user-created
schedules, reachable through the ``cronjob`` tool (app/tools/cronjob.py) and
fired by ``app/cronablauf.py``.
"""

from __future__ import annotations

from app.db.models import Cronjob
from app.db.repositories.base import Repository, neue_id


class CronjobRepository(Repository):
    def erstellen(
        self,
        *,
        agent: str,
        task: str,
        zeitplan: str,
        herkunft: str,
        deliver: str = "log",
        basisaufgabe: str | None = None,
        einmalig: bool = False,
        datum: str | None = None,
        fehlergrenze: int | None = None,
        ziel: str | None = None,
        ziel_stilllegen: bool = False,
        ursprung_id: str | None = None,
        notiz: str | None = None,
        notiz_am: str | None = None,
        skript: str | None = None,
        zeitgrenze: int | None = None,
    ) -> Cronjob:
        eintrag = Cronjob(
            id=neue_id(),
            agent=agent,
            task=task,
            zeitplan=zeitplan,
            herkunft=herkunft,
            created_at=self.zeitstempel(),
            updated_at=self.zeitstempel(),
            deliver=deliver,
            basisaufgabe=basisaufgabe,
            einmalig=einmalig,
            datum=datum,
            ziel=ziel,
            ziel_stilllegen=ziel_stilllegen,
            ursprung_id=ursprung_id,
            notiz=notiz,
            notiz_am=notiz_am,
            skript=skript,
            zeitgrenze=zeitgrenze,
        )
        # Left out means "whatever the default is" — and that default is
        # written down once, on the dataclass, instead of a second time in
        # every caller that does not care.
        if fehlergrenze is not None:
            eintrag.fehlergrenze = fehlergrenze
        # ``notiz_am`` is taken rather than stamped here, unlike in
        # ``notiz_setzen``: the one caller that passes a note is a restart
        # chain inheriting the note of the entry whose work it takes over
        # (app/zwischenstand.py), and what that note needs to keep saying is
        # when it was WRITTEN. Stamped with the moment of the handoff
        # instead, it would tell the continuation its own state is fresher
        # than it is, and everything between the write and the handoff would
        # count as already seen.
        self.verbindung.execute(
            """
            INSERT INTO cronjobs (id, agent, task, zeitplan, deliver, aktiv,
                                   herkunft, created_at, updated_at, basisaufgabe,
                                   einmalig, datum, fehlergrenze, ziel,
                                   ziel_stilllegen, ursprung_id, notiz, notiz_am,
                                   skript, zeitgrenze)
            VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                eintrag.id,
                eintrag.agent,
                eintrag.task,
                eintrag.zeitplan,
                eintrag.deliver,
                eintrag.herkunft,
                eintrag.created_at,
                eintrag.updated_at,
                eintrag.basisaufgabe,
                int(eintrag.einmalig),
                eintrag.datum,
                eintrag.fehlergrenze,
                eintrag.ziel,
                int(eintrag.ziel_stilllegen),
                eintrag.ursprung_id,
                eintrag.notiz,
                eintrag.notiz_am,
                eintrag.skript,
                eintrag.zeitgrenze,
            ),
        )
        return eintrag

    def holen(self, cronjob_id: str) -> Cronjob | None:
        zeile = self.verbindung.execute(
            "SELECT * FROM cronjobs WHERE id = ?", (cronjob_id,)
        ).fetchone()
        return Cronjob.aus_zeile(zeile) if zeile else None

    def auflisten(self) -> list[Cronjob]:
        zeilen = self.verbindung.execute(
            "SELECT * FROM cronjobs ORDER BY created_at, rowid"
        ).fetchall()
        return [Cronjob.aus_zeile(zeile) for zeile in zeilen]

    def aktive(self) -> list[Cronjob]:
        """Entries the firing loop (app/cronablauf.py) has to consider."""
        zeilen = self.verbindung.execute(
            "SELECT * FROM cronjobs WHERE aktiv = 1 ORDER BY created_at, rowid"
        ).fetchall()
        return [Cronjob.aus_zeile(zeile) for zeile in zeilen]

    def aktiv_setzen(self, cronjob_id: str, aktiv: bool) -> Cronjob | None:
        """Switching an entry ON also clears its two run counts (the failure
        count and the count of runs without a goal report).

        Otherwise an entry the counter switched off could never really be
        armed again: the count would still sit at the limit, and the very
        next failed run would push it over and switch the entry straight
        back off. Arming it again is exactly the statement "try this once
        more, from the top" — from the mask's switch, from the tool's
        'resume', from anywhere. The quiet count goes with it for the same
        reason: an entry armed anew should get its full run of quiet passes
        before it says nobody has reported anything. Switching OFF leaves
        both alone: those are the numbers the announcement and the mask
        report.

        ``ziel_erreicht_am`` is deliberately NOT cleared — it is a record of
        when something was last reported, not a state to be reset, and the
        interface only ever reads it on an entry that is switched off."""
        zusatz = ", fehlversuche = 0, laeufe_ohne_ruf = 0" if aktiv else ""
        self.verbindung.execute(
            f"UPDATE cronjobs SET aktiv = ?{zusatz}, updated_at = ? WHERE id = ?",
            (int(aktiv), self.zeitstempel(), cronjob_id),
        )
        return self.holen(cronjob_id)

    def fehlversuch_zaehlen(self, cronjob_id: str) -> Cronjob | None:
        """One more failed run in a row.

        Counted in SQL rather than read-add-write in Python: two runs of the
        same entry ending in the same moment would otherwise both read the
        same old number and both write the same new one, and one failure
        would go missing from the very count that is supposed to stop the
        entry."""
        self.verbindung.execute(
            "UPDATE cronjobs SET fehlversuche = fehlversuche + 1, updated_at = ? "
            "WHERE id = ?",
            (self.zeitstempel(), cronjob_id),
        )
        return self.holen(cronjob_id)

    def fehlversuche_zuruecksetzen(self, cronjob_id: str) -> Cronjob | None:
        """Back to zero — a run that ended properly says the entry works
        again, whatever it did or did not find while it was looking."""
        self.verbindung.execute(
            "UPDATE cronjobs SET fehlversuche = 0, updated_at = ? WHERE id = ?",
            (self.zeitstempel(), cronjob_id),
        )
        return self.holen(cronjob_id)

    def ziel_erreicht_setzen(self, cronjob_id: str, wann: str) -> Cronjob | None:
        """The goal was reported: stamped, and the quiet count put
        back to zero in the same statement — the report is exactly the
        answer that count was waiting for."""
        self.verbindung.execute(
            "UPDATE cronjobs SET ziel_erreicht_am = ?, laeufe_ohne_ruf = 0, "
            "updated_at = ? WHERE id = ?",
            (wann, self.zeitstempel(), cronjob_id),
        )
        return self.holen(cronjob_id)

    def stillen_lauf_zaehlen(self, cronjob_id: str) -> Cronjob | None:
        """One more run that ended properly without reporting the goal.

        Counted in SQL for the same reason ``fehlversuch_zaehlen`` is: two
        runs of one entry ending in the same moment would otherwise read the
        same old number and write the same new one, and a run would go
        missing from the very count that decides when to speak up."""
        self.verbindung.execute(
            "UPDATE cronjobs SET laeufe_ohne_ruf = laeufe_ohne_ruf + 1, "
            "updated_at = ? WHERE id = ?",
            (self.zeitstempel(), cronjob_id),
        )
        return self.holen(cronjob_id)

    def stille_laeufe_zuruecksetzen(self, cronjob_id: str) -> Cronjob | None:
        """Back to zero after the "nothing reported in N runs" notice went
        out — the entry keeps running, and the next N quiet runs earn their
        own notice rather than one on every single run from here on."""
        self.verbindung.execute(
            "UPDATE cronjobs SET laeufe_ohne_ruf = 0, updated_at = ? WHERE id = ?",
            (self.zeitstempel(), cronjob_id),
        )
        return self.holen(cronjob_id)

    def notiz_setzen(self, cronjob_id: str, notiz: str | None) -> Cronjob | None:
        """The note one run leaves for the next one.

        Replaces outright — the tool has no "append" and this has no
        read-modify-write, so two runs of the same entry ending in the same
        moment cannot interleave into half of each other's text. The last
        writer wins, which is the right answer for a field whose whole
        meaning is "where things stood when I last looked".

        ``None`` clears it: the model calling the tool with an empty note is
        saying there is nothing left to carry over, and an empty string in
        the column would otherwise read as a note and be fed into the next
        run as a blank line about nothing.

        The moment of the write is stored with it, and that is the whole
        point of ``notiz_am``: the next run is told how current the note is,
        and until this existed it was told ``zuletzt_ausgeloest`` instead —
        a stamp that is also set for a due time merely SKIPPED because a run
        was still going (app/cronablauf.py). It can therefore name a moment
        AFTER the note was written, and everything that happened in between
        would count as already seen and never be reported."""
        self.verbindung.execute(
            "UPDATE cronjobs SET notiz = ?, notiz_am = ?, updated_at = ? WHERE id = ?",
            (notiz, self.zeitstempel() if notiz is not None else None,
             self.zeitstempel(), cronjob_id),
        )
        return self.holen(cronjob_id)

    def aktualisieren(
        self,
        cronjob_id: str,
        *,
        agent: str | None = None,
        task: str | None = None,
        zeitplan: str | None = None,
        deliver: str | None = None,
        basisaufgabe: str | None = None,
        einmalig: bool | None = None,
        datum: str | None = None,
        datum_loeschen: bool = False,
        fehlergrenze: int | None = None,
        ziel: str | None = None,
        ziel_loeschen: bool = False,
        ziel_stilllegen: bool | None = None,
        aktiv: bool | None = None,
        skript: str | None = None,
        zeitgrenze: int | None = None,
    ) -> Cronjob | None:
        """Partial update — a field left out (``None``) keeps its old value.

        ``aktiv`` here is deliberately NOT ``aktiv_setzen``: that one also
        clears the two run counts, which is right when a person arms an
        entry again and wrong for the one caller here — a restart chain
        being handed the next piece of its own work (app/zwischenstand.py).
        A chain entry that inherited ``einmalig`` switched itself off the
        moment it fired, and without arming it again in the same breath as
        the new task, the handoff would be written into a row that can never
        run. Its counts belong to the chain and travel with it.

        ``datum_loeschen`` clears ``datum`` outright rather than leaving it
        alone — turning ``einmalig`` back off has to take a dated entry's
        fixed day down with it, or the two would disagree about what the
        entry even is. It takes priority over
        ``datum``; the caller never sends both, since they answer opposite
        questions (clear it vs. set it).

        ``ziel_loeschen`` works the same way and for the same reason: an entry without a goal cannot be one that stops when its goal
        is reached, so clearing the goal takes ``ziel_stilllegen`` down with
        it in the same statement. Left behind, the flag would sit on an
        entry nothing can ever reach a goal on."""
        zuweisungen = ["updated_at = ?"]
        werte: list[object] = [self.zeitstempel()]
        if agent is not None:
            zuweisungen.append("agent = ?")
            werte.append(agent)
        if task is not None:
            zuweisungen.append("task = ?")
            werte.append(task)
        if zeitplan is not None:
            zuweisungen.append("zeitplan = ?")
            werte.append(zeitplan)
        if deliver is not None:
            zuweisungen.append("deliver = ?")
            werte.append(deliver)
        if basisaufgabe is not None:
            zuweisungen.append("basisaufgabe = ?")
            werte.append(basisaufgabe)
        if einmalig is not None:
            zuweisungen.append("einmalig = ?")
            werte.append(int(einmalig))
        if fehlergrenze is not None:
            zuweisungen.append("fehlergrenze = ?")
            werte.append(fehlergrenze)
        if aktiv is not None:
            zuweisungen.append("aktiv = ?")
            werte.append(int(aktiv))
        if datum_loeschen:
            zuweisungen.append("datum = NULL")
        elif datum is not None:
            zuweisungen.append("datum = ?")
            werte.append(datum)
        if ziel_loeschen:
            zuweisungen.append("ziel = NULL")
            zuweisungen.append("ziel_stilllegen = 0")
        else:
            if ziel is not None:
                zuweisungen.append("ziel = ?")
                werte.append(ziel)
            if ziel_stilllegen is not None:
                zuweisungen.append("ziel_stilllegen = ?")
                werte.append(int(ziel_stilllegen))
        if skript is not None:
            zuweisungen.append("skript = ?")
            werte.append(skript)
        # A limit of its own is only ever set, never cleared: there is no
        # 'back to the default' wish to express here that setting the default
        # number itself would not answer, and a second spelling for it would
        # be a second thing to keep in step.
        if zeitgrenze is not None:
            zuweisungen.append("zeitgrenze = ?")
            werte.append(zeitgrenze)
        werte.append(cronjob_id)
        self.verbindung.execute(
            f"UPDATE cronjobs SET {', '.join(zuweisungen)} WHERE id = ?", werte
        )
        return self.holen(cronjob_id)

    def loeschen(self, cronjob_id: str) -> bool:
        cursor = self.verbindung.execute(
            "DELETE FROM cronjobs WHERE id = ?", (cronjob_id,)
        )
        return cursor.rowcount > 0

    def fortschritt_setzen(
        self,
        cronjob_id: str,
        *,
        erledigt_anzahl: int | None,
        ohne_fortschritt: int,
        neustarts: int,
    ) -> Cronjob | None:
        """Records one restart's counters — a context-full handoff
        (app/zwischenstand.py) or a provider-outage retry
        (app/wiederversuch.py). ``erledigt_anzahl`` stays ``None`` for the
        latter: an outage says nothing about task progress, so it must not
        read as a stall toward the done-count breaker."""
        self.verbindung.execute(
            "UPDATE cronjobs SET erledigt_anzahl = ?, ohne_fortschritt = ?, "
            "neustarts = ?, updated_at = ? WHERE id = ?",
            (erledigt_anzahl, ohne_fortschritt, neustarts, self.zeitstempel(), cronjob_id),
        )
        return self.holen(cronjob_id)

    def ausgeloest_setzen(self, cronjob_id: str, termin_iso: str) -> None:
        """Marks a due time handled — fired or deliberately skipped, the
        same distinction the alarm clock's in-memory ``_behandelt`` makes
        for an agent's own schedule (app/wecker.py), just persisted here so
        a restart does not refire something already done."""
        self.verbindung.execute(
            "UPDATE cronjobs SET zuletzt_ausgeloest = ?, updated_at = ? WHERE id = ?",
            (termin_iso, self.zeitstempel(), cronjob_id),
        )
