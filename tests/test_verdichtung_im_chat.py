"""Compaction that survives the next message, and loses nothing.

A job can compact by rewriting the message list it holds: that list lives
for the whole task. A chat rebuilds its history from the database on every
single request, so a compaction that is not written down is undone by the
next thing the user types — which is exactly why a chat had no compaction
at all while jobs have had one for a long time.

What is written down is a POINTER, never a deletion. The rows that were
folded stay where they are and stay readable; they only stop being sent to
the model, because a summary now speaks for them. So there are two readings
of one chat, and the tests below are mostly about keeping them apart:
`auflisten` is what the reader sees, `fuer_das_modell` is what goes into the
request.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# The repository root, so these source-text guards read the checkout they
# live in and not a path from one particular machine.
WURZEL = Path(__file__).resolve().parent.parent

# The tool-enabled client, borrowed rather than built a second time (the
# tests about a run that folds inside itself need tools). pytest looks a
# fixture up by the MODULE attribute it is bound to, so it has to carry that
# name here — bound rather than imported under it, because an import of that
# name and a test parameter of that name read to the linter as one name
# defined twice.
from tests.test_auftraege_api import mcp_client as _mcp_client
from tests.fensterquelle import WINDOW_SOURCE

mcp_client = _mcp_client


def _chat(client):
    return client.post("/api/v1/chats", json={"title": "Verdichtung"}).json()["id"]


class _WindowsUhr:
    """A clock with Windows' granularity: it does not move.

    Windows advances its clock only about every 15.6 ms, so every row
    written inside one tick reads the same moment — and `jetzt_iso` then
    carries the stamp forward by exactly one microsecond per row rather
    than handing out the same one twice. A clock standing completely still
    is that tick taken to its end: the whole conversation lands one
    microsecond apart, which is the spacing the seam has to survive.

    Only the two members `jetzt_iso` actually calls. `fromisoformat` is
    passed straight through — the carry-forward reads its own last stamp
    back with it, and that has nothing to do with what the clock says.
    """

    STAND = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    @classmethod
    def now(cls, tz=None):
        return cls.STAND

    @staticmethod
    def fromisoformat(text):
        return datetime.fromisoformat(text)


@pytest.fixture
def windows_uhr(monkeypatch):
    """`jetzt_iso` on a Windows clock, and its memory of the last stamp
    reset so the frozen moment is where the conversation starts."""
    from app.db import connection

    monkeypatch.setattr(connection, "datetime", _WindowsUhr)
    monkeypatch.setattr(connection, "_letzter_stempel", "")


def _gespraech(repositories, chat_id, paare=6):
    """A plausible history: question, answer, question, answer..."""
    zeilen = []
    for nr in range(paare):
        zeilen.append(
            repositories.messages.speichern(
                chat_id=chat_id, role="user", content=f"Frage {nr}"
            )
        )
        zeilen.append(
            repositories.messages.speichern(
                chat_id=chat_id, role="assistant", content=f"Antwort {nr}",
                zustand="fertig",
            )
        )
    return zeilen


def test_die_gefalteten_zeilen_bleiben_lesbar(client):
    """The whole point. Compaction is not deletion."""
    repositories = client.app.state.repositories
    chat_id = _chat(client)
    zeilen = _gespraech(repositories, chat_id)
    mitte = [z.id for z in zeilen[2:8]]

    repositories.messages.verdichten(
        chat_id=chat_id, text="Zusammengefasst: Fragen 1 bis 3 geklaert.",
        ersetzte_ids=mitte,
    )

    alle = repositories.messages.auflisten(chat_id=chat_id)
    # Every original line still there, plus the summary.
    assert len(alle) == len(zeilen) + 1
    for zeile in zeilen:
        assert any(a.id == zeile.id for a in alle)


def test_das_modell_bekommt_die_zusammenfassung_statt_der_mitte(client):
    repositories = client.app.state.repositories
    chat_id = _chat(client)
    zeilen = _gespraech(repositories, chat_id)
    mitte = [z.id for z in zeilen[2:8]]

    zusammenfassung = repositories.messages.verdichten(
        chat_id=chat_id, text="Zusammengefasst: Fragen 1 bis 3 geklaert.",
        ersetzte_ids=mitte,
    )

    fuer_modell = repositories.messages.fuer_das_modell(chat_id=chat_id)
    kennungen = [z.id for z in fuer_modell]
    for gefaltet in mitte:
        assert gefaltet not in kennungen
    assert zusammenfassung.id in kennungen


def test_die_zusammenfassung_steht_an_der_stelle_der_mitte(client):
    """Not at the end of the chat.

    The list is ordered by creation time, so a summary stamped "now" would
    sort behind the messages it is supposed to come BEFORE — the model would
    read the tail of the conversation first and its summary afterwards.
    """
    repositories = client.app.state.repositories
    chat_id = _chat(client)
    zeilen = _gespraech(repositories, chat_id)
    mitte = [z.id for z in zeilen[2:8]]

    zusammenfassung = repositories.messages.verdichten(
        chat_id=chat_id, text="Die Mitte, kurz.", ersetzte_ids=mitte,
    )

    fuer_modell = repositories.messages.fuer_das_modell(chat_id=chat_id)
    stelle = [z.id for z in fuer_modell].index(zusammenfassung.id)
    # Behind the two kept opening rows, in front of the kept tail.
    assert [z.content for z in fuer_modell[:stelle]] == ["Frage 0", "Antwort 0"]
    assert fuer_modell[stelle + 1].content == "Frage 4"


def test_die_zusammenfassung_bleibt_vor_der_ersten_behaltenen_zeile(client, windows_uhr):
    """The same placement, on a clock that leaves no room.

    A microsecond after the last folded row is a step into thin air unless
    somebody checks that the next row is further away than that. On Windows
    it is not: every row written inside one ~15.6 ms tick sits exactly one
    microsecond after the one before it, so the summary tied with the first
    KEPT row — and `created_at ASC, rowid ASC` puts the summary, the newest
    row and therefore the highest `rowid`, behind it. Measured before the
    fix: `fuer_das_modell` read `Frage 0, Antwort 0, Frage 4, SUMMARY`, so
    the model saw a message before the summary of the messages that came
    before it, and the seam sat one row too low in the chat as well.

    macOS never showed it: 400 back-to-back `speichern` calls there came out
    11 us apart at the closest, and not once did the clock stand still.
    Windows is a target this program is built for.
    """
    repositories = client.app.state.repositories
    chat_id = _chat(client)
    zeilen = _gespraech(repositories, chat_id)

    # The premise of the whole test: no gap to step into anywhere.
    abstaende = {
        datetime.fromisoformat(b.created_at) - datetime.fromisoformat(a.created_at)
        for a, b in zip(zeilen, zeilen[1:], strict=False)
    }
    assert abstaende == {timedelta(microseconds=1)}

    mitte = zeilen[2:8]
    zusammenfassung = repositories.messages.verdichten(
        chat_id=chat_id, text="Die Mitte, kurz.", ersetzte_ids=[z.id for z in mitte],
    )

    # What the model reads: the summary stands where the middle stood.
    fuer_modell = repositories.messages.fuer_das_modell(chat_id=chat_id)
    stelle = [z.id for z in fuer_modell].index(zusammenfassung.id)
    assert [z.content for z in fuer_modell[:stelle]] == ["Frage 0", "Antwort 0"]
    assert fuer_modell[stelle + 1].content == "Frage 4"

    # And what the reader sees: the seam sits directly behind the folded
    # stretch, not one row further down. Both readings order the same way,
    # so a fix that held for only one of them would be no fix at all.
    alle = [z.id for z in repositories.messages.auflisten(chat_id=chat_id)]
    assert alle.index(zusammenfassung.id) == alle.index(mitte[-1].id) + 1
    assert alle.index(zusammenfassung.id) < alle.index(zeilen[8].id)


def test_die_zusammenfassung_ist_keine_antwort(client):
    """It has to be drawn as what it is, and it must never be mistaken for
    the answer being written — the whole class of bug this schema change
    exists to close."""
    repositories = client.app.state.repositories
    chat_id = _chat(client)
    zeilen = _gespraech(repositories, chat_id, paare=3)

    zusammenfassung = repositories.messages.verdichten(
        chat_id=chat_id, text="Kurz.", ersetzte_ids=[zeilen[2].id, zeilen[3].id],
    )

    assert zusammenfassung.art == "verdichtung"
    assert zusammenfassung.zustand is None


def test_ohne_zeilen_oder_ohne_text_passiert_nichts(client):
    """A provider hiccup must not fold anything away for nothing."""
    repositories = client.app.state.repositories
    chat_id = _chat(client)
    zeilen = _gespraech(repositories, chat_id, paare=2)

    assert repositories.messages.verdichten(
        chat_id=chat_id, text="", ersetzte_ids=[zeilen[0].id]
    ) is None
    assert repositories.messages.verdichten(
        chat_id=chat_id, text="Etwas", ersetzte_ids=[]
    ) is None

    assert len(repositories.messages.auflisten(chat_id=chat_id)) == len(zeilen)
    assert all(z.verdichtet_in is None for z in repositories.messages.auflisten(chat_id=chat_id))


def test_fremde_kennungen_falten_nichts(client):
    """The ids are handed in from outside; a chat must not be able to fold
    away another chat's messages."""
    repositories = client.app.state.repositories
    chat_a = _chat(client)
    chat_b = _chat(client)
    fremd = repositories.messages.speichern(
        chat_id=chat_b, role="user", content="Gehoert zu B"
    )

    assert repositories.messages.verdichten(
        chat_id=chat_a, text="Kurz.", ersetzte_ids=[fremd.id]
    ) is None
    assert repositories.messages.holen(fremd.id).verdichtet_in is None


def test_zweimal_verdichten_faltet_die_zusammenfassung_mit(client):
    """A long run compacts more than once, and the second pass has to be
    allowed to fold the first summary in — otherwise every pass leaves a
    permanent line behind and the savings shrink with each one."""
    repositories = client.app.state.repositories
    chat_id = _chat(client)
    zeilen = _gespraech(repositories, chat_id)

    erste = repositories.messages.verdichten(
        chat_id=chat_id, text="Erste Faltung.", ersetzte_ids=[z.id for z in zeilen[2:6]],
    )
    zweite = repositories.messages.verdichten(
        chat_id=chat_id, text="Zweite Faltung.",
        ersetzte_ids=[erste.id] + [z.id for z in zeilen[6:10]],
    )

    fuer_modell = repositories.messages.fuer_das_modell(chat_id=chat_id)
    kennungen = [z.id for z in fuer_modell]
    assert erste.id not in kennungen
    assert zweite.id in kennungen
    # And the reader still has all of it, both summaries included.
    assert len(repositories.messages.auflisten(chat_id=chat_id)) == len(zeilen) + 2


@pytest.mark.parametrize("kaputt", ["", "kein zeitstempel"])
def test_ein_unlesbarer_zeitstempel_kostet_die_faltung_nicht(client, kaputt):
    """The stamp comes out of the database, a boundary this does not
    control. A summary that cannot be placed a microsecond later still has
    to be placed — `rowid` breaks the tie in the same direction."""
    from app.db.repositories.messages import _kurz_nach

    assert _kurz_nach(kaputt) == kaputt
    # And the boundary is no less unreadable than the stamp. Neither of
    # them is parsed on this path, so neither can raise.
    assert _kurz_nach(kaputt, vor=kaputt) == kaputt
    assert _kurz_nach(kaputt, vor="2026-01-01T12:00:00.000001+00:00") == kaputt


def test_auch_eine_rohe_loeschung_gibt_die_gefalteten_zeilen_frei(client):
    """The release of the pointer used to be written by hand in two
    repository methods, and the next deletion path — a sweep, a repair
    script, a fixture's DELETE — would have had to remember it. The
    database does it now, so a bare DELETE releases the rows a summary
    spoke for and they go to the model again."""
    repositories = client.app.state.repositories
    chat = repositories.chats.erstellen(user_id="standard", title="Roh")
    zeilen = [
        repositories.messages.speichern(
            chat_id=chat.id, role="user" if nr % 2 == 0 else "assistant",
            content=f"Zeile {nr}", zustand=None if nr % 2 == 0 else "fertig",
        )
        for nr in range(8)
    ]
    naht = repositories.messages.verdichten(
        chat_id=chat.id, text="Zusammenfassung", ersetzte_ids=[z.id for z in zeilen[3:6]]
    )
    assert naht is not None
    assert len(repositories.messages.fuer_das_modell(chat_id=chat.id)) == 6

    repositories.messages.verbindung.execute("DELETE FROM messages WHERE id = ?", (naht.id,))

    kennungen = [z.id for z in repositories.messages.fuer_das_modell(chat_id=chat.id)]
    assert kennungen == [z.id for z in zeilen]
    assert all(z.verdichtet_in is None for z in repositories.messages.auflisten(chat_id=chat.id))


def test_ein_gleichstand_an_der_naht_wird_aufgeloest(client):
    """Two services on one database each carry their own stamp forward, so
    the last folded row and the first kept row can share one. The summary
    then had no room: it kept the folded row's stamp and, as the newest
    row, sorted BEHIND the kept row it must precede — the model read that
    row before the summary of everything that came before it.

    The kept rows on that stamp move two microseconds on and the summary
    takes the one between: the reader sees folded, summary, kept; the
    model sees summary, kept."""
    repositories = client.app.state.repositories
    chat = repositories.chats.erstellen(user_id="standard", title="Naht")
    stempel = "2026-01-01T12:00:00.000010+00:00"
    zeilen = []
    for nr in range(6):
        zeilen.append(repositories.messages.speichern(
            chat_id=chat.id, role="user" if nr % 2 == 0 else "assistant",
            content=f"Zeile {nr}", zustand=None if nr % 2 == 0 else "fertig",
        ))
    gefaltet = zeilen[:4]
    behalten = zeilen[4:]
    # Stamps set by hand, in order: the last folded row and the first kept
    # row on ONE stamp, the second kept row already two microseconds on —
    # the burst two writers produce.
    stempel_je_zeile = [
        "2026-01-01T12:00:00.000001+00:00",
        "2026-01-01T12:00:00.000002+00:00",
        "2026-01-01T12:00:00.000003+00:00",
        stempel,
        stempel,
        "2026-01-01T12:00:00.000012+00:00",
    ]
    for zeile, wert in zip(zeilen, stempel_je_zeile, strict=True):
        repositories.messages.verbindung.execute(
            "UPDATE messages SET created_at = ? WHERE id = ?", (wert, zeile.id)
        )

    naht = repositories.messages.verdichten(
        chat_id=chat.id, text="Zusammenfassung", ersetzte_ids=[z.id for z in gefaltet]
    )
    assert naht is not None

    fuers_modell = [z.id for z in repositories.messages.fuer_das_modell(chat_id=chat.id)]
    assert fuers_modell == [naht.id, behalten[0].id, behalten[1].id]
    alle = [z.id for z in repositories.messages.auflisten(chat_id=chat.id)]
    assert alle == [z.id for z in gefaltet] + [naht.id, behalten[0].id, behalten[1].id]
    # The moved rows keep their order among themselves, and the summary
    # stands one microsecond behind the folded row.
    assert naht.created_at == "2026-01-01T12:00:00.000011+00:00"
    assert repositories.messages.holen(behalten[0].id).created_at == "2026-01-01T12:00:00.000012+00:00"


def test_der_schritt_wird_nur_getan_wo_platz_dafuer_ist():
    """The microsecond is a step, and a step needs somewhere to land.

    `rowid` settles a tie in one direction only — the summary is the newest
    row, so a tie always puts it later. Right against the row it follows,
    wrong against the row it precedes. Where the next row is that one
    microsecond away, the step therefore has to stay untaken.
    """
    from app.db.repositories.messages import _kurz_nach

    letzte = "2026-01-01T12:00:00.000010+00:00"
    weiter = "2026-01-01T12:00:00.000011+00:00"

    # Room: the step is taken, exactly as it always was.
    assert _kurz_nach(letzte) == weiter
    assert _kurz_nach(letzte, vor="2026-01-01T12:00:00.000020+00:00") == weiter

    # No room: the stamp of the last folded row, and `rowid` puts the
    # summary behind that row and in front of the next one.
    assert _kurz_nach(letzte, vor=weiter) == letzte

    # And the one shape no stamp can fix: both rows on the same moment.
    # Documented rather than papered over — it takes two processes writing
    # one database file, because `jetzt_iso`'s stamps strictly increase
    # within a process.
    assert _kurz_nach(letzte, vor=letzte) == letzte


def test_eine_geloeschte_zusammenfassung_gibt_ihre_zeilen_frei(client):
    """A summary speaks FOR the rows it folded. Deleting it alone would
    leave them represented by nothing — still readable in the chat, gone
    from what the model sees, and nothing saying so."""
    repositories = client.app.state.repositories
    chat_id = _chat(client)
    zeilen = _gespraech(repositories, chat_id)
    mitte = [z.id for z in zeilen[2:8]]
    zusammenfassung = repositories.messages.verdichten(
        chat_id=chat_id, text="Kurz.", ersetzte_ids=mitte,
    )
    assert len(repositories.messages.fuer_das_modell(chat_id=chat_id)) < len(zeilen)

    repositories.messages.loeschen(zusammenfassung.id)

    fuers_modell = [z.id for z in repositories.messages.fuer_das_modell(chat_id=chat_id)]
    for gefaltet in mitte:
        assert gefaltet in fuers_modell, "the folded row stayed silent"
    assert all(
        z.verdichtet_in is None
        for z in repositories.messages.auflisten(chat_id=chat_id)
    )


def test_der_verlauf_fuers_modell_liest_die_richtige_seite(client):
    """The builder must read `fuer_das_modell`, not `auflisten`.

    Today the two return the same thing, because nothing folds yet. The day
    compaction is switched on, a builder still reading `auflisten` would
    send the summary IN ADDITION to everything it replaced — compacting
    would make the prompt bigger. Source-text guard, because the difference
    is invisible until the moment it costs everything.
    """

    quelle = (WURZEL / "app/api/v1/generierung.py").read_text()
    assert "messages.fuer_das_modell(chat_id=chat.id)" in quelle, (
        "the model's history reads auflisten again"
    )


def test_die_zusammenfassung_sagt_wie_viele_sie_gefaltet_hat(client):
    """The seam in the chat names a number, and the number has to be real."""
    repositories = client.app.state.repositories
    chat_id = _chat(client)
    zeilen = _gespraech(repositories, chat_id)
    mitte = [z.id for z in zeilen[2:8]]

    zusammenfassung = repositories.messages.verdichten(
        chat_id=chat_id, text="Kurz.", ersetzte_ids=mitte,
    )

    alle = repositories.messages.auflisten(chat_id=chat_id)
    treffer = next(z for z in alle if z.id == zusammenfassung.id)
    assert treffer.verdichtete_anzahl == len(mitte)
    # And nothing else claims to have folded anything.
    assert all(z.verdichtete_anzahl == 0 for z in alle if z.id != zusammenfassung.id)


def test_die_zahl_gilt_auch_wenn_die_seite_kuerzer_ist_als_die_faltung(client):
    """Counted in SQL, not from the rows that happen to have been fetched.

    `auflisten` pages. A window counting the folded rows IT holds would say
    "two compressed messages" about a fold of six and never look wrong doing
    it — the same "guessed from the list" defect the whole message table was
    rebuilt to remove. So the count is asked of the database, and a page too
    short to contain the fold still carries the true number.
    """
    repositories = client.app.state.repositories
    chat_id = _chat(client)
    zeilen = _gespraech(repositories, chat_id)
    mitte = [z.id for z in zeilen[2:8]]
    zusammenfassung = repositories.messages.verdichten(
        chat_id=chat_id, text="Kurz.", ersetzte_ids=mitte,
    )

    # The summary alone, without a single one of the rows it folded: the
    # folded lines stay in the chat and sort BEFORE it, so a page starting
    # at the summary holds none of them.
    stelle = [
        z.id for z in repositories.messages.auflisten(chat_id=chat_id)
    ].index(zusammenfassung.id)
    seite = repositories.messages.auflisten(
        chat_id=chat_id, limit=1, offset=stelle
    )

    assert [z.id for z in seite] == [zusammenfassung.id]
    assert seite[0].verdichtete_anzahl == 6


def test_die_zweite_faltung_zaehlt_die_erste_mit(client):
    """A second pass folds the first summary in, and says so: it now speaks
    for the first summary plus the rows it took itself."""
    repositories = client.app.state.repositories
    chat_id = _chat(client)
    zeilen = _gespraech(repositories, chat_id)

    erste = repositories.messages.verdichten(
        chat_id=chat_id, text="Erste.", ersetzte_ids=[z.id for z in zeilen[2:6]],
    )
    zweite = repositories.messages.verdichten(
        chat_id=chat_id, text="Zweite.",
        ersetzte_ids=[erste.id] + [z.id for z in zeilen[6:10]],
    )

    alle = {z.id: z for z in repositories.messages.auflisten(chat_id=chat_id)}
    assert alle[erste.id].verdichtete_anzahl == 4
    assert alle[zweite.id].verdichtete_anzahl == 5


def test_die_naht_wird_nicht_als_nachricht_gezeichnet(client):
    """A compaction is a seam in the history, not something anybody said.

    Source-text guard on the one thing that must not silently come back: the
    summary row used to fall through to the assistant branch and be drawn as
    a bubble with a mark under it. It has its own branch now, ahead of both
    other branches, and the branch must stay first — `istVonMir` is false
    for a summary, so a lost branch would put it back in the answer column
    without anything looking broken.
    """

    quelle = (WURZEL / "frontend/src/teile/Nachricht.svelte").read_text()
    assert "{#if istVerdichtung}" in quelle, "the seam no longer has a branch of its own"
    assert quelle.index("{#if istVerdichtung}") < quelle.index("{:else if istVonMir}"), (
        "the seam no longer stands before the other two branches"
    )
    assert "class=\"naht\"" in quelle


def test_die_wartezeile_kennt_das_verdichtungszeichen(client):
    """While the history is being compressed, the waiting mark is the
    compression sign and not the chat's chevron — the one place that says
    so is the `art` branch."""

    quelle = (WURZEL / "frontend/src/teile/Wartezeile.svelte").read_text()
    assert "art === 'verdichtung'" in quelle


def test_the_card_names_the_exit_code_instead_of_the_word(client):
    """Source-text guard: a call's row carries no word at its end any more;
    the label of the row names the exit code, not the word.

    The code says everything the word "failed" says and names itself as
    well, so the label is an either/or: the exit code first, the word only
    where there is none. A future edit that turns it back into two parts has
    to walk past this test."""

    quelle = (WURZEL / "frontend/src/teile/Nachricht.svelte").read_text()
    wort = quelle.split("  function callWord(werkzeug, stand) {", 1)[1].split("\n  }\n", 1)[0]
    assert "if (werkzeug.exit_code) return t('werkzeug.exit'" in wort
    assert "if (werkzeug.fehlgeschlagen) return t('werkzeug.marke_fehlgeschlagen')" in wort
    assert wort.index("werkzeug.exit_code") < wort.index("werkzeug.fehlgeschlagen"), (
        "exit code and the word stand side by side again"
    )
    zeile = quelle.split("{#snippet callRow(teil, i)}", 1)[1].split("{/snippet}", 1)[0]
    assert "werkzeug.lauf_nummer" in zeile


def test_loeschen_ab_gibt_die_gefalteten_zeilen_frei(client):
    """Deleting by TIMESTAMP crosses a summary without meaning to.

    `loeschen` releases what a summary spoke for; `loeschen_ab` deleted in
    one bare statement and left the pointers behind. The rows would stay
    readable in the chat and be dropped from `fuer_das_modell` for good,
    with nothing on screen saying so — the same failure `loeschen` is
    careful about, in the method twenty lines below it.
    """
    repositories = client.app.state.repositories
    chat_id = _chat(client)
    zeilen = _gespraech(repositories, chat_id)
    mitte = [z.id for z in zeilen[2:8]]
    zusammenfassung = repositories.messages.verdichten(
        chat_id=chat_id, text="Kurz.", ersetzte_ids=mitte,
    )

    # From the first folded row on: the summary sorts after them and goes too.
    repositories.messages.loeschen_ab(
        chat_id=chat_id, ab_zeitstempel=zeilen[2].created_at
    )

    assert repositories.messages.holen(zusammenfassung.id) is None
    uebrig = repositories.messages.auflisten(chat_id=chat_id)
    assert all(z.verdichtet_in is None for z in uebrig), (
        "a surviving row points at a deleted summary"
    )


def test_das_ende_sagt_ob_gefaltet_wurde(client):
    """The window cannot see a fold on its own.

    The summary row is written before the stream even opens, and nothing in
    the answer's events mentions it. Without a word at the end the window
    keeps drawing the folded stretch as ordinary live context until the chat
    is reopened — and nothing says the model stopped seeing it.
    """

    dienst = (WURZEL / "app/api/v1/generierung.py").read_text()
    assert "verdichtet=verdichtet_zu," in dienst, (
        "the done event no longer says whether a fold happened"
    )

    fenster = WINDOW_SOURCE.read_text()
    assert "verdichtetZu = ereignis.verdichtet" in fenster, (
        "the window does not read the notice"
    )
    assert "(verdichtetZu || zeileNachladen) &&" in fenster, (
        "the window does not refetch the list after a fold"
    )


def test_das_fenster_sagt_komprimiere_solange_gefaltet_wird():
    """Source-text guards for the three window halves of one thing: the
    program's line puts the word on the placeholder, the waiting mark draws
    it with the narrowing stack and its own text, and the answer's own
    stream takes it back once it opens. The branch in Wartezeile.svelte and
    its locale text existed before this and nothing ever reached them."""
    ohr = (WURZEL / "frontend/src/lib/ereignisstrom.svelte.js").read_text()
    assert "verdichtung_laeuft:" in ohr, "the line's ear does not know the compaction event"
    assert "platzhalter.taetigkeit = 'verdichtung'" in ohr, (
        "the event does not put the word on the placeholder"
    )
    fenster = WINDOW_SOURCE.read_text()
    # The chat's ONE waiting mark (App.svelte, `wartemarke`) draws the word now.
    assert "zeile.taetigkeit === 'verdichtung'" in fenster
    # Twice: the mark of the chat's one waiting answer, and the mark a
    # hand-made compaction wears at the end of the list while no answer
    # exists to carry one.
    assert fenster.count("t('status.komprimiert')") == 2, "the mark slot ignores the compaction word"
    assert "art={laufMarke.art}" in fenster, "the mark slot does not wear the mark's art"
    # ONE word per waiting stretch: the effect must watch the bare yes/no,
    # not the laufMarke object — that one is rebuilt on every streamed
    # chunk, and watching it re-rolled the word several times a second.
    #
    # What is drawn is a PLACE in the list, not the word: the words come out
    # of the catalogue now, so a change of language hands back a different
    # array, and drawing the word would draw a new one. The place survives
    # it and the mark simply translates.
    assert "wartestelle = markeSteht" in fenster, "the waiting word hangs on the object again"
    assert "WARTEWORTE[Math.floor(wartestelle" in fenster, (
        "the position is no longer turned into a word of the list"
    )
    assert "if (platzhalter.taetigkeit === 'verdichtung') platzhalter.taetigkeit = 'kontext'" in fenster, (
        "the answer's stream does not take the compaction word back at start"
    )


# --- A fold inside an answer, written down afterwards ------------------------


def test_eine_faltung_im_lauf_wird_als_zeile_nachtragen(mcp_client):
    """A fold INSIDE an answer is written down, so the next message continues.

    From round 1 on the rounds of an answer are not rows and never will be;
    where the request still had to shrink, they folded in memory — the way a
    job folds its own list — and nothing was written down. The next message
    then sent the unfolded stretches again and folded them anew: one request
    for the same result. Falls today: no summary row after the run, and the
    next request carries the whole history again.
    """
    from app import verdichtung
    from tests.conftest import GROSS, UEBER_DER_SCHWELLE, chatkette, senden

    repositories = mcp_client.app.state.repositories
    chat_id = _chat(mcp_client)
    vorher = _gespraech(repositories, chat_id, paare=6)
    # A row BEYOND the pinned opening is part of the folded stretch whatever
    # the constants are — taken from them rather than from a number that
    # happens to fit today.
    gefaltet_weg = vorher[min(verdichtung.ERSTE_FEST + 1, len(vorher) - 1)]
    provider = chatkette(mcp_client, runden=6, stand=UEBER_DER_SCHWELLE, ergebnis=GROSS)

    senden(mcp_client, chat_id)

    assert provider.faltungen >= 1, "the run did not fold itself"
    zeilen = repositories.messages.auflisten(chat_id=chat_id)
    assert len([z for z in zeilen if z.art == "verdichtung"]) == 1, (
        "the fold during the run is in no row"
    )

    senden(mcp_client, chat_id, content="Und weiter?")
    inhalte = [inhalt for _, inhalt in provider.aufzeichnung[-1]]
    assert any(inhalt.startswith(verdichtung.VORSPANN) for inhalt in inhalte), (
        "the next request does not begin at the summary"
    )
    assert not any(gefaltet_weg.content in inhalt for inhalt in inhalte), (
        "the folded rows travel along again"
    )


def test_der_nachtrag_markiert_nur_was_die_faltung_wirklich_hatte(client):
    """Where the rows themselves carry the weight, the fold protected a tail
    of them — and the summary must not swallow what it never covered.

    The after-run recording is handed rows, not the folded list, so it cuts
    the verbatim tail off them the way every fold cuts it. A heavy row that
    the fold kept must stay in the prompt: behind the seam it would leave the
    conversation without the summary ever mentioning it.
    """
    from app import chatverdichtung, verdichtung

    repositories = client.app.state.repositories
    chat_id = _chat(client)
    klein = _gespraech(repositories, chat_id, paare=4)
    schwer = repositories.messages.speichern(
        chat_id=chat_id, role="user", content="S" * 200_000
    )

    kennung = chatverdichtung.faltung_nachtragen(
        chat=repositories.chats.holen(chat_id),
        repositories=repositories,
        zusammenfassung=f"{verdichtung.VORSPANN}\n\nsummary",
        budget=80_000,
    )

    assert kennung, "the fold was not added"
    gefaltet = {
        z.id
        for z in repositories.messages.auflisten(chat_id=chat_id)
        if z.verdichtet_in
    }
    assert klein[3].id in gefaltet, "the old row belongs behind the seam"
    assert schwer.id not in gefaltet, "the protected row was folded along"


def test_the_write_back_keeps_the_rows_the_fold_kept_where_pictures_carry_the_weight(client):
    """Sixteen pictures with a few words each: by their text the rows do not
    fill the tail budget, by what the request carries they do. The fold of
    the answer's own rounds counted every picture at its price, so it kept
    the newest rows verbatim; the recording must not mark them as folded."""
    from app import chatverdichtung, verdichtung

    repositories = client.app.state.repositories
    chat_id = _chat(client)
    klein = _gespraech(repositories, chat_id, paare=4)
    bilder = [
        repositories.messages.speichern(
            chat_id=chat_id, role="user", content=f"Look {nr}.", anhaenge=["foto.png"]
        )
        for nr in range(16)
    ]

    kennung = chatverdichtung.faltung_nachtragen(
        chat=repositories.chats.holen(chat_id),
        repositories=repositories,
        zusammenfassung=f"{verdichtung.VORSPANN}\n\nsummary",
        budget=80_000,
    )

    assert kennung, "the fold was not added"
    gefaltet = {
        z.id
        for z in repositories.messages.auflisten(chat_id=chat_id)
        if z.verdichtet_in
    }
    assert klein[3].id in gefaltet, "the old row belongs behind the seam"
    assert bilder[-1].id not in gefaltet, "a row of the verbatim tail was folded along"


def test_ein_lauf_ohne_faltung_schreibt_keine_zeile(mcp_client):
    """Silence probe: a run that never folds adds no row of its own."""
    from tests.conftest import GROSS, KNAPP_UNTER_DER_SCHWELLE, chatkette, senden

    repositories = mcp_client.app.state.repositories
    chat_id = _chat(mcp_client)
    _gespraech(repositories, chat_id, paare=2)
    provider = chatkette(mcp_client, runden=2, stand=KNAPP_UNTER_DER_SCHWELLE, ergebnis=GROSS)

    senden(mcp_client, chat_id)

    assert provider.faltungen == 0
    zeilen = repositories.messages.auflisten(chat_id=chat_id)
    assert not [z for z in zeilen if z.art == "verdichtung"]


def test_die_faltbitte_im_lauf_eines_chats_traegt_keine_werkzeuge(mcp_client):
    """A chat that folds inside its own answer asks for the summary without
    tools, as the fold of its rows does. Offered the chat's tools, the model
    could answer with a call, which the fold reads as an empty summary.
    Silence probe: every round of the answer still carries the tools."""
    from app import verdichtung
    from tests.conftest import (
        GROSS,
        RUNDENTEXT_GROSS,
        UEBER_DER_SCHWELLE,
        chatkette,
        senden,
    )

    provider = chatkette(mcp_client, runden=6, stand=UEBER_DER_SCHWELLE, ergebnis=GROSS,
                         rundentext=RUNDENTEXT_GROSS)
    chat_id = _chat(mcp_client)

    senden(mcp_client, chat_id)

    def faltbitte(anfrage) -> bool:
        letzte = anfrage.nachrichten[-1]
        return letzte.role == "user" and (letzte.content or "").startswith(
            verdichtung.ANFRAGE_TEXT
        )

    faltungen = [a for a in provider.alle_anfragen if faltbitte(a)]
    runden = [a for a in provider.alle_anfragen if not faltbitte(a)]
    assert faltungen, "the run did not fold itself"
    assert all(a.werkzeuge == [] for a in faltungen), "the fold request offers tools"
    assert runden and all(a.werkzeuge for a in runden), "a round lost its tools"
