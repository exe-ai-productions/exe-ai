"""Database and repositories."""

from __future__ import annotations

import logging
import sqlite3

import pytest

from app.db import Database, repositories_erstellen
from app.db.connection import SCHEMA_VERSION
from app.db.folding import register_fold_function


def test_schema_wird_angelegt(db: Database):
    tabellen = {
        zeile["name"]
        for zeile in db.verbindung.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    assert {"chats", "messages", "documents", "schema_version"} <= tabellen
    assert db.schema_version() == SCHEMA_VERSION


def test_schema_einrichten_ist_wiederholbar(db: Database):
    db.schema_einrichten()
    db.schema_einrichten()
    anzahl = db.verbindung.execute("SELECT COUNT(*) AS n FROM schema_version").fetchone()["n"]
    assert anzahl == 1


# --- Chats ---------------------------------------------------------------


def test_chat_erstellen_und_holen(repos):
    chat = repos.chats.erstellen(user_id="benutzer", title="Erster Chat")
    geholt = repos.chats.holen(chat.id)
    assert geholt is not None
    assert geholt.title == "Erster Chat"
    assert geholt.user_id == "benutzer"


def test_chat_gehoert_zum_benutzer(repos):
    chat = repos.chats.erstellen(user_id="benutzer", title="Meiner")
    assert repos.chats.holen(chat.id, user_id="benutzer") is not None
    assert repos.chats.holen(chat.id, user_id="jemand_anderes") is None


def test_chats_auflisten_neueste_zuerst(repos):
    """Even with identical timestamps, the ordering must be deterministic."""
    alt = repos.chats.erstellen(user_id="benutzer", title="Alt")
    neu = repos.chats.erstellen(user_id="benutzer", title="Neu")

    liste = repos.chats.auflisten(user_id="benutzer")
    assert [chat.id for chat in liste] == [neu.id, alt.id]

    # The older chat gets touched and must move to the top as a result.
    repos.chats.zeitstempel_auffrischen(alt.id)
    liste = repos.chats.auflisten(user_id="benutzer")
    assert [chat.id for chat in liste][0] == alt.id


def test_chats_suchen_filtert_titel(repos):
    repos.chats.erstellen(user_id="benutzer", title="Netzwerk-Probleme")
    repos.chats.erstellen(user_id="benutzer", title="Kochrezepte")

    treffer = repos.chats.auflisten(user_id="benutzer", suche="Netzwerk")
    assert len(treffer) == 1
    assert treffer[0].title == "Netzwerk-Probleme"


def test_chats_suchen_findet_den_inhalt_nicht_nur_den_titel(repos):
    """What was SAID counts. The title is written once, by a model, out of
    the first question — everything discussed afterwards used to be
    unfindable."""
    chat = repos.chats.erstellen(user_id="benutzer", title="Untitled chat")
    repos.messages.speichern(
        chat_id=chat.id, role="user", content="Was kostet ein Heizkörper aus Guss?"
    )
    daneben = repos.chats.erstellen(user_id="benutzer", title="Kochrezepte")
    repos.messages.speichern(chat_id=daneben.id, role="user", content="Wie koche ich Reis?")

    treffer = repos.chats.auflisten(user_id="benutzer", suche="Heizkörper")
    assert [t.id for t in treffer] == [chat.id]
    # A prefix is enough, and the accent need not be typed — in the content
    # that is the index's tokenizer (`remove_diacritics 2`), in the title it
    # is the same folding applied to both sides.
    assert [t.id for t in repos.chats.auflisten(user_id="benutzer", suche="heizk")] == [chat.id]
    assert [t.id for t in repos.chats.auflisten(user_id="benutzer", suche="heizkorper")] == [
        chat.id
    ]
    # Two words narrow, they do not widen.
    assert repos.chats.auflisten(user_id="benutzer", suche="Heizkörper Reis") == []
    # The silence probe: a word nobody wrote finds nothing, and a chat is
    # not dragged in by the other one's messages.
    assert repos.chats.auflisten(user_id="benutzer", suche="Dachziegel") == []
    assert [t.id for t in repos.chats.auflisten(user_id="benutzer", suche="Reis")] == [daneben.id]


def test_chat_search_folds_the_title_like_the_content(repos):
    """A title is found whichever way the word was typed: accents and case
    are folded on both sides, as the message index folds them. SQLite's own
    LIKE folds ASCII case only, so "heizkorper" missed a chat titled
    "Heizkörper" while finding one that merely mentioned it."""
    radiator = repos.chats.erstellen(user_id="benutzer", title="Heizkörper")
    umlaut_chat = repos.chats.erstellen(user_id="benutzer", title="Über den Wolken")
    sharp_s_chat = repos.chats.erstellen(user_id="benutzer", title="Straße nach Köln")
    # The title typed in decomposed form (a name pasted out of Finder).
    decomposed_chat = repos.chats.erstellen(user_id="benutzer", title="Mu\u0308ller")

    def ids(query):
        return [t.id for t in repos.chats.auflisten(user_id="benutzer", suche=query)]

    assert ids("heizkorper") == [radiator.id]
    assert ids("HEIZKÖRPER") == [radiator.id]
    assert ids("Heizkörper") == [radiator.id]
    assert ids("über") == [umlaut_chat.id]
    assert ids("uber") == [umlaut_chat.id]
    assert ids("muller") == [decomposed_chat.id]
    assert ids("Müller") == [decomposed_chat.id]
    # The line with no usable word (a single letter) is folded too.
    assert sorted(ids("Ü")) == sorted([umlaut_chat.id, decomposed_chat.id])
    assert ids("ß") == [sharp_s_chat.id]
    # ß stays ß on both sides, as in the index: it is not read as "ss".
    assert ids("straße") == [sharp_s_chat.id]
    assert ids("strasse") == []
    # A piece of a word inside the title still counts.
    assert ids("zkorp") == [radiator.id]
    # Silence probe: a title without the word is not found, and neither is
    # a chat by letters that only look alike once accents are gone.
    assert ids("heizung") == []
    assert ids("koln nach strasse") == []
    # A wildcard typed alone stays literal after the folding.
    assert ids("%") == []


def test_chat_search_title_and_content_with_two_words(repos):
    """One word may sit in the title and the next in a message; a title that
    holds a wildcard character is matched literally."""
    chat = repos.chats.erstellen(user_id="benutzer", title="Köln 100% Plan")
    repos.messages.speichern(chat_id=chat.id, role="user", content="Der Dachziegel fehlt")
    other = repos.chats.erstellen(user_id="benutzer", title="Plan B")

    def ids(query):
        return [t.id for t in repos.chats.auflisten(user_id="benutzer", suche=query)]

    assert ids("koln dachziegel") == [chat.id]
    assert ids("dachziegel plan") == [chat.id]
    assert sorted(ids("plan")) == sorted([chat.id, other.id])
    assert ids("100%") == [chat.id]
    assert ids("koln heizung") == []


def test_chat_search_folds_only_what_the_index_folds(repos):
    """The folding is the index's: Latin accents go, the marks of other
    scripts stay, and a syllable of Hangul is not split into its parts."""
    hangul = repos.chats.erstellen(user_id="benutzer", title="한국어")
    greek = repos.chats.erstellen(user_id="benutzer", title="Οδός")
    sigma = repos.chats.erstellen(user_id="benutzer", title="ΟΔΟΣ")

    def ids(query):
        return [t.id for t in repos.chats.auflisten(user_id="benutzer", suche=query)]

    assert ids("한국어") == [hangul.id]
    assert ids("하") == []
    assert ids("οδοσ") == [sigma.id]
    assert ids("οδος") == [sigma.id]
    assert ids("οδός") == [greek.id]
    assert ids("οδος") != [greek.id]


def test_fold_function_passes_other_values_through():
    """A cell that is not text is handed back as it is, so one odd row never
    breaks a search; NULL stays NULL."""
    connection = sqlite3.connect(":memory:")
    register_fold_function(connection)
    row = connection.execute("SELECT fold_text(5), fold_text(NULL), fold_text(x'41'), fold_text('Ä')").fetchone()
    assert row == (5, None, b"A", "a")


def test_die_suche_haelt_mit_wenn_eine_nachricht_sich_aendert(repos):
    """The index is external content: without the triggers it would answer
    with yesterday's chats and miss today's."""
    chat = repos.chats.erstellen(user_id="benutzer", title="Untitled chat")
    zeile = repos.messages.speichern(chat_id=chat.id, role="assistant", content="Erstes Wort")

    assert repos.chats.auflisten(user_id="benutzer", suche="Erstes")
    repos.messages.inhalt_aktualisieren(zeile.id, content="Zweites Wort")
    assert repos.chats.auflisten(user_id="benutzer", suche="Erstes") == []
    assert repos.chats.auflisten(user_id="benutzer", suche="Zweites")
    repos.messages.loeschen(zeile.id)
    assert repos.chats.auflisten(user_id="benutzer", suche="Zweites") == []

    # And a whole chat going away: its messages are removed by the database
    # itself (ON DELETE CASCADE), so the trigger is the only thing that can
    # take their words back out of the index. A leftover would be the worst
    # kind of hit — one pointing at a conversation that no longer exists.
    zweiter = repos.chats.erstellen(user_id="benutzer", title="Untitled chat")
    repos.messages.speichern(chat_id=zweiter.id, role="user", content="Drittes Wort")
    assert repos.chats.auflisten(user_id="benutzer", suche="Drittes")
    repos.chats.loeschen(zweiter.id)
    assert repos.chats.auflisten(user_id="benutzer", suche="Drittes") == []


def test_jedes_wort_darf_auf_seiner_eigenen_seite_stehen(repos):
    """One word from the title, one from the conversation — the way somebody
    types who remembers both. Asked per SIDE instead of per word, this found
    nothing: the title had to carry the whole line and the messages all of
    its words."""
    chat = repos.chats.erstellen(user_id="benutzer", title="Heizkörper")
    repos.messages.speichern(
        chat_id=chat.id, role="user", content="Was kosten die Preise für Guss?"
    )

    assert [t.id for t in repos.chats.auflisten(user_id="benutzer", suche="Heizkörper")] == [
        chat.id
    ]
    assert [t.id for t in repos.chats.auflisten(user_id="benutzer", suche="Preise")] == [chat.id]
    assert [
        t.id for t in repos.chats.auflisten(user_id="benutzer", suche="Heizkörper Preise")
    ] == [chat.id]
    # Two messages, one word each: a chat is one thing, not one haystack per
    # message.
    repos.messages.speichern(chat_id=chat.id, role="assistant", content="Guss ist teuer")
    assert [t.id for t in repos.chats.auflisten(user_id="benutzer", suche="Preise teuer")] == [
        chat.id
    ]
    # The silence probe: one word that is nowhere is enough to drop the chat.
    assert repos.chats.auflisten(user_id="benutzer", suche="Heizkörper Dachziegel") == []


def test_eine_kaputte_sucheingabe_ist_keine_abfrage(repos):
    """FTS5 reads its own query language, and a quotation mark or the word OR
    in the box would end the query mid-string — an error instead of a
    result. What goes in is words."""
    from app.db.repositories.chats import fts_wort, like_muster, suchwoerter

    assert suchwoerter("Heizkörper Preise") == ["Heizkörper", "Preise"]
    assert suchwoerter('"') == []
    assert suchwoerter("  ") == []
    assert suchwoerter("a OR b") == ["a", "OR", "b"]
    assert fts_wort("heizk") == '"heizk"*'
    # What LIKE reads as a wildcard is handed over as itself.
    assert like_muster("100%") == "%100\\%%"
    assert like_muster("a_b") == "%a\\_b%"
    assert like_muster("c:\\pfad") == "%c:\\\\pfad%"

    chat = repos.chats.erstellen(user_id="benutzer", title='Ein "Titel" mit OR')
    repos.messages.speichern(chat_id=chat.id, role="user", content="nichts besonderes")
    for eingabe in ('"', "OR", "a AND", "*", "NEAR(", "()"):
        # No exception, and the title filter beside it still works.
        repos.chats.auflisten(user_id="benutzer", suche=eingabe)
    assert [t.id for t in repos.chats.auflisten(user_id="benutzer", suche="Titel")] == [chat.id]


def test_ein_jokerzeichen_im_suchfeld_listet_nicht_alles(repos):
    """`%` and `_` are what somebody typed, not a pattern. Handed to LIKE
    unescaped, a single character listed every chat that has a title."""
    repos.chats.erstellen(user_id="benutzer", title="Netzwerk-Probleme")
    repos.chats.erstellen(user_id="benutzer", title="Kochrezepte")
    mit = repos.chats.erstellen(user_id="benutzer", title="Rabatt 20% im Mai")

    # Only the title that really carries the character — not all three.
    assert [t.id for t in repos.chats.auflisten(user_id="benutzer", suche="%")] == [mit.id]
    assert [t.id for t in repos.chats.auflisten(user_id="benutzer", suche="_")] == []
    unterstrich = repos.chats.erstellen(user_id="benutzer", title="Ticket max_tokens 60")
    assert [t.id for t in repos.chats.auflisten(user_id="benutzer", suche="_")] == [
        unterstrich.id
    ]
    # Beside a word the character is a separator like any other punctuation:
    # `20%` asks for the word 20, and the wildcard is not smuggled in — the
    # chat titled "Rabatt 200 im Mai" below proves it is not a prefix either
    # way round.
    assert [t.id for t in repos.chats.auflisten(user_id="benutzer", suche="20%")] == [mit.id]
    zweihundert = repos.chats.erstellen(user_id="benutzer", title="Rabatt 200 im Mai")
    assert {t.id for t in repos.chats.auflisten(user_id="benutzer", suche="20%")} == {
        mit.id,
        zweihundert.id,
    }


def test_ein_zerlegter_umlaut_zerbricht_das_wort_nicht(repos):
    """A name pasted out of Finder arrives decomposed: "Müller" as u plus a
    combining mark. The mark is no word character, so the word used to come
    apart into "Mu" and "ller" — and "ller" is nowhere, neither as an FTS
    prefix of `muller` nor inside the composed title."""
    import unicodedata

    from app.db.repositories.chats import suchwoerter

    zerlegt = unicodedata.normalize("NFD", "Müller")
    assert zerlegt != "Müller"
    assert suchwoerter(zerlegt) == ["Müller"]

    chat = repos.chats.erstellen(user_id="benutzer", title="Müller")
    inhalt = repos.chats.erstellen(user_id="benutzer", title="Untitled chat")
    repos.messages.speichern(chat_id=inhalt.id, role="user", content="Frage an Müller")

    assert {t.id for t in repos.chats.auflisten(user_id="benutzer", suche=zerlegt)} == {
        chat.id,
        inhalt.id,
    }


def test_ein_einzelner_buchstabe_wird_weggelassen_nicht_verlangt(repos):
    """As a prefix a single letter is the most expensive question the index
    can be asked and the least useful — it keeps nearly every row. So it is
    left OUT of the conjunction, not required of the title: punctuation makes
    such words on its own, and "GPT-4" or "Level 8" would otherwise come
    back empty while the exact string stands in a message."""
    chat = repos.chats.erstellen(user_id="benutzer", title="Modellvergleich")
    repos.messages.speichern(
        chat_id=chat.id, role="user", content="Ist GPT-4 besser als Claude 3 Opus?"
    )

    for eingabe in ("GPT-4", "Claude 3", "GPT", "Claude 3 Opus"):
        assert [t.id for t in repos.chats.auflisten(user_id="benutzer", suche=eingabe)] == [
            chat.id
        ], eingabe

    # Nothing but a single letter: then the line is looked for as it stands,
    # in the title — where a one-letter search was always answered.
    titel = repos.chats.erstellen(user_id="benutzer", title="Plan X")
    nur_inhalt = repos.chats.erstellen(user_id="benutzer", title="Ohne")
    repos.messages.speichern(chat_id=nur_inhalt.id, role="user", content="X wie Xylophon")
    assert [t.id for t in repos.chats.auflisten(user_id="benutzer", suche="X")] == [titel.id]
    # Two letters are a word again, and then the conversation counts.
    assert [t.id for t in repos.chats.auflisten(user_id="benutzer", suche="Xy")] == [
        nur_inhalt.id
    ]


def test_der_wortdeckel_haelt_auch_ohne_die_jungen_namen(repos):
    """The limit is named, not handed in: `SQLITE_LIMIT_EXPR_DEPTH` is as
    young as `getlimit` (both Python 3.11). Written at the call site, an
    older interpreter would raise before the fallback could be reached — and
    every search would answer with an error instead of a list."""
    from app.db.repositories.chats import _PLATZHALTER_VORGABE, _TIEFE_VORGABE, _grenze

    verbindung = repos.chats.verbindung
    assert _grenze(verbindung, "GIBT_ES_NICHT", _TIEFE_VORGABE) == _TIEFE_VORGABE
    assert _grenze(verbindung, "GIBT_ES_NICHT", _PLATZHALTER_VORGABE) == _PLATZHALTER_VORGABE


def test_der_wortdeckel_liest_null_als_ohne_grenze(repos):
    """`0` is SQLite's value for NO limit on those two. Read as a number, the
    ceiling came out as 1, and every search but its first word was quietly
    dropped — "Heizkörper Preise" would have listed every chat about
    Heizkörper, with nothing anywhere saying so."""
    import sqlite3

    from app.db.repositories.chats import (
        _PLATZHALTER_VORGABE,
        _TIEFE_VORGABE,
        wortdeckel,
    )

    verbindung = repos.chats.verbindung
    assert wortdeckel(verbindung) > 1
    # Per limit: saying "none" has to give the same answer as saying the
    # documented default, and never the answer for "one".
    for welche, vorgabe in (
        (sqlite3.SQLITE_LIMIT_EXPR_DEPTH, _TIEFE_VORGABE),
        (sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, _PLATZHALTER_VORGABE),
    ):
        vorher = verbindung.getlimit(welche)
        try:
            verbindung.setlimit(welche, vorgabe)
            aus_vorgabe = wortdeckel(verbindung)
            verbindung.setlimit(welche, 0)
            assert verbindung.getlimit(welche) == 0
            assert wortdeckel(verbindung) == aus_vorgabe > 1
        finally:
            verbindung.setlimit(welche, vorher)
    # And the tighter of the two wins: each word binds two values.
    vorher = verbindung.getlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER)
    try:
        verbindung.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 23)
        assert wortdeckel(verbindung) == 10
    finally:
        verbindung.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, vorher)


def test_eine_ganze_seite_im_suchfeld_ist_kein_fehler(repos):
    """The box sends what it holds on every keystroke, so a pasted page of
    text reaches this query. Each word costs one level of SQLite's
    expression tree, whose limit is 1000 — unbounded, the 1000th word came
    back as an uncaught OperationalError, an HTTP 500 where "no hits" was
    the honest answer."""
    from app.db.repositories.chats import wortdeckel

    assert wortdeckel(repos.chats.verbindung) >= 1
    repos.chats.erstellen(user_id="benutzer", title="Ein Chat")

    for zahl in (999, 1000, 1001, 4000):
        # No exception — that is the whole assertion.
        assert repos.chats.auflisten(
            user_id="benutzer", suche=" ".join(f"wort{i}" for i in range(zahl))
        ) == []


def test_die_suche_findet_auch_was_vor_der_umstellung_geschrieben_wurde(db):
    """The backfill: an existing database keeps its chats, and its old
    messages have to land in the index — a search that only knew what was
    written from today on would miss exactly the conversation from three
    weeks ago somebody is looking for."""
    from app.db import repositories_erstellen

    repos = repositories_erstellen(db)
    chat = repos.chats.erstellen(user_id="benutzer", title="Untitled chat")
    repos.messages.speichern(chat_id=chat.id, role="user", content="Etwas über Dachziegel")

    # Back to the state before the step: index and triggers gone, and the
    # version row saying so.
    for anweisung in (
        "DROP TRIGGER IF EXISTS messages_fts_eingefuegt",
        "DROP TRIGGER IF EXISTS messages_fts_geloescht",
        "DROP TRIGGER IF EXISTS messages_fts_geaendert",
        "DROP TABLE IF EXISTS messages_fts",
        "DELETE FROM schema_version",
        "INSERT INTO schema_version (version, applied_at) VALUES (34, '2026-09-17T00:00:00')",
    ):
        db.verbindung.execute(anweisung)

    db.schema_einrichten()

    assert db.schema_version() == SCHEMA_VERSION
    assert [t.id for t in repos.chats.auflisten(user_id="benutzer", suche="Dachziegel")] == [
        chat.id
    ]


def test_ein_verlorener_volltextindex_wird_beim_start_nachgezogen(db: Database, caplog):
    """A messages_fts gone missing while the messages stayed: schema.sql
    would only lay the table down again — empty — and the search would miss
    everything written before, without saying so.

    The version row is deliberately left at today's stand: migration 35 is
    the only step that ever filled this index and it must not run a second
    time, so the backfill has to come from the start itself."""
    repos = repositories_erstellen(db)
    chat = repos.chats.erstellen(user_id="benutzer", title="Untitled chat")
    repos.messages.speichern(chat_id=chat.id, role="user", content="Etwas über Dachziegel")

    for anweisung in (
        "DROP TRIGGER IF EXISTS messages_fts_eingefuegt",
        "DROP TRIGGER IF EXISTS messages_fts_geloescht",
        "DROP TRIGGER IF EXISTS messages_fts_geaendert",
        "DROP TABLE IF EXISTS messages_fts",
    ):
        db.verbindung.execute(anweisung)

    with caplog.at_level(logging.INFO, logger="app.db.connection"):
        db.schema_einrichten()

    assert [t.id for t in repos.chats.auflisten(user_id="benutzer", suche="Dachziegel")] == [
        chat.id
    ]
    assert any("Full-text index" in satz.message for satz in caplog.records), (
        "the start does not name the follow-up run"
    )


def test_ein_gesunder_start_fasst_den_index_nicht_an(db: Database, caplog):
    """The other half of the same decision: only a LOST table is rebuilt.
    An index that exists is never rewritten, not even when its contents no
    longer match — every start repairing everything would be the integrity
    check on every launch nobody asked for."""
    repos = repositories_erstellen(db)
    chat = repos.chats.erstellen(user_id="benutzer", title="Untitled chat")
    repos.messages.speichern(chat_id=chat.id, role="user", content="Etwas über Dachziegel")

    # One entry taken out of the index by hand: the table is there, what it
    # holds is not what the messages say.
    zeile = db.verbindung.execute("SELECT rowid, content FROM messages").fetchone()
    db.verbindung.execute(
        "INSERT INTO messages_fts (messages_fts, rowid, content) VALUES ('delete', ?, ?)",
        (zeile["rowid"], zeile["content"]),
    )
    assert repos.chats.auflisten(user_id="benutzer", suche="Dachziegel") == []

    with caplog.at_level(logging.INFO, logger="app.db.connection"):
        db.schema_einrichten()

    assert repos.chats.auflisten(user_id="benutzer", suche="Dachziegel") == []
    # The silence probe: the catch-up line names a repair that
    # did not happen here — an existing table is never rebuilt, so nothing
    # about the full-text index belongs in this start's log.
    assert not any("Full-text index" in satz.message for satz in caplog.records), (
        "a healthy start names a follow-up run that did not happen"
    )


def test_ein_abgebrochener_nachlauf_hinterlaesst_keine_leere_tabelle(db: Database):
    """The table and its fill stand in one transaction
    (``_volltextindex_nachziehen``) on purpose — an external-content FTS5
    table answers every count out of ``messages`` itself, so a table that
    exists but was never rebuilt looks exactly like a filled one, and the
    next start's ``index_verloren`` check would find the table and never
    try again. An authorizer that denies exactly the rebuild statement
    stands in for the crash the transaction guards against — ``execute``
    itself cannot be monkeypatched, sqlite3.Connection is an immutable
    type."""
    import sqlite3

    repos = repositories_erstellen(db)
    chat = repos.chats.erstellen(user_id="benutzer", title="Untitled chat")
    repos.messages.speichern(chat_id=chat.id, role="user", content="Etwas über Dachziegel")

    for anweisung in (
        "DROP TRIGGER IF EXISTS messages_fts_eingefuegt",
        "DROP TRIGGER IF EXISTS messages_fts_geloescht",
        "DROP TRIGGER IF EXISTS messages_fts_geaendert",
        "DROP TABLE IF EXISTS messages_fts",
    ):
        db.verbindung.execute(anweisung)

    def verweigert_den_wiederaufbau(aktion, arg1, arg2, arg3, arg4):
        if aktion == sqlite3.SQLITE_INSERT and arg1 == "messages_fts":
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    db.verbindung.set_authorizer(verweigert_den_wiederaufbau)
    try:
        with pytest.raises(sqlite3.DatabaseError):
            db.schema_einrichten()
    finally:
        db.verbindung.set_authorizer(None)

    vorhanden = db.verbindung.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='messages_fts'"
    ).fetchone()
    assert vorhanden is None, (
        "the half-built table stayed — the next start finds "
        "it and keeps its hands off it"
    )


def test_eine_gesperrte_datenbank_bricht_den_nachlauf_klar_ab(tmp_path, caplog):
    """A second service on the same data folder starting while the first
    holds the write lock used to die mid-catch-up with the raw sqlite3
    "database is locked" — no cause a person reading the log could act on.

    The lock is a real second connection in BEGIN IMMEDIATE, held open for
    the whole call: busy_timeout has to run out and fail exactly the way a
    genuinely stuck second service would."""
    import sqlite3

    pfad = tmp_path / "gesperrt.db"
    eins = Database(pfad)
    eins.schema_einrichten()
    repos = repositories_erstellen(eins)
    chat = repos.chats.erstellen(user_id="benutzer", title="Untitled chat")
    repos.messages.speichern(chat_id=chat.id, role="user", content="Etwas über Dachziegel")

    for anweisung in (
        "DROP TRIGGER IF EXISTS messages_fts_eingefuegt",
        "DROP TRIGGER IF EXISTS messages_fts_geloescht",
        "DROP TRIGGER IF EXISTS messages_fts_geaendert",
        "DROP TABLE IF EXISTS messages_fts",
    ):
        eins.verbindung.execute(anweisung)

    sperre = sqlite3.connect(pfad)
    sperre.execute("BEGIN IMMEDIATE")
    sperre.execute("CREATE TABLE sperrzeile (x)")

    zwei = Database(pfad)
    # Shorter than the real 5000ms: the test does not need to wait as long
    # as a genuinely stuck service to prove the same outcome.
    zwei.verbindung.execute("PRAGMA busy_timeout = 200")

    with caplog.at_level(logging.ERROR, logger="app.db.connection"):
        with pytest.raises(sqlite3.OperationalError, match="Another Exe AI service"):
            zwei.schema_einrichten()

    assert any(
        "Another Exe AI service" in satz.message for satz in caplog.records
    ), "the aborted start does not name the cause in the log"

    sperre.rollback()
    sperre.close()
    zwei.schliessen()

    drei = Database(pfad)
    with caplog.at_level(logging.INFO, logger="app.db.connection"):
        drei.schema_einrichten()
    vorhanden = drei.verbindung.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='messages_fts'"
    ).fetchone()
    assert vorhanden is not None, (
        "the follow-up run stayed marked as missing — a start without a lock "
        "should have caught it up"
    )

    eins.schliessen()
    drei.schliessen()


def _gesperrt_starten(pfad, vorbereiten, caplog):
    """A second service starting on ``pfad`` while a real second connection
    holds the write lock in BEGIN IMMEDIATE; ``vorbereiten`` leaves the
    database with exactly one step of the start still to write."""
    import sqlite3

    eins = Database(pfad)
    eins.schema_einrichten()
    vorbereiten(eins.verbindung)
    eins.schliessen()

    sperre = sqlite3.connect(pfad)
    sperre.execute("BEGIN IMMEDIATE")
    sperre.execute("CREATE TABLE sperrzeile (x)")
    zwei = Database(pfad)
    zwei.verbindung.execute("PRAGMA busy_timeout = 200")
    try:
        with caplog.at_level(logging.ERROR, logger="app.db.connection"):
            with pytest.raises(sqlite3.OperationalError, match="Another Exe AI service"):
                zwei.schema_einrichten()
        assert any("Another Exe AI service" in satz.message for satz in caplog.records)
    finally:
        sperre.rollback()
        sperre.close()
        zwei.schliessen()


def test_eine_gesperrte_datenbank_bricht_den_migrationslauf_klar_ab(tmp_path, caplog):
    """The migrations write first on an older database; a lock held by a
    second service there used to end the start with the raw sqlite3 text."""

    def eine_version_zurueck(verbindung):
        verbindung.execute("DELETE FROM schema_version WHERE version = ?", (SCHEMA_VERSION,))

    _gesperrt_starten(tmp_path / "migration.db", eine_version_zurueck, caplog)


def test_eine_gesperrte_datenbank_bricht_das_schemaskript_klar_ab(tmp_path, caplog):
    """No migration left, but schema.sql still has something to create: the
    lock meets the script, and it names the cause the same way."""

    def ein_index_fehlt(verbindung):
        verbindung.execute("DROP INDEX idx_chats_user_updated")

    _gesperrt_starten(tmp_path / "schema.db", ein_index_fehlt, caplog)


def test_ein_echter_schemafehler_kommt_roh_durch(tmp_path, monkeypatch):
    """The silence probe: a broken step is not a second service, and its
    own text goes up unchanged."""
    import sqlite3

    from app.db import connection

    pfad = tmp_path / "kaputt.db"
    eins = Database(pfad)
    eins.schema_einrichten()
    eins.schliessen()

    monkeypatch.setattr(
        connection, "MIGRATIONEN",
        [*connection.MIGRATIONEN, (SCHEMA_VERSION + 1, ["CREATE TABLE halb ("])],
    )
    zwei = Database(pfad)
    try:
        with pytest.raises(sqlite3.OperationalError) as fehler:
            zwei.schema_einrichten()
        assert "Another Exe AI service" not in str(fehler.value)
        assert fehler.value.__cause__ is None
    finally:
        zwei.schliessen()


def test_chat_parameter_aktualisieren(repos):
    """Parameters left the chat row — they live in the settings cascade."""
    chat = repos.chats.erstellen(user_id="benutzer", title="Test")
    repos.einstellungen.setzen(f"chat:{chat.id}", "parameter", {"top_k": 30})
    assert repos.einstellungen.holen(f"chat:{chat.id}", "parameter") == {"top_k": 30}

def test_unbekanntes_feld_wird_abgewiesen(repos):
    chat = repos.chats.erstellen(user_id="benutzer", title="Test")
    with pytest.raises(ValueError):
        repos.chats.aktualisieren(chat.id, geheimnis="hallo")


def test_eine_frage_an_einen_geloeschten_chat_wird_erkannt(repos):
    """A run writes the open question, the chat is deleted under it, and the
    run writes again: the second write must say the row is gone instead of
    passing in silence."""
    chat = repos.chats.erstellen(user_id="benutzer", title="Weg damit")
    assert repos.chats.frage_setzen(chat.id, '{"frage": "Welche?"}') is True
    assert repos.chats.loeschen(chat.id) is True
    assert repos.chats.frage_setzen(chat.id, None) is False


def test_eine_frage_an_einen_bestehenden_chat_schreibt_wie_bisher(repos):
    """The silence probe: a chat that is there takes the question and the
    clearing as before."""
    chat = repos.chats.erstellen(user_id="benutzer", title="Bleibt")
    assert repos.chats.frage_setzen(chat.id, '{"frage": "Welche?"}') is True
    assert repos.chats.holen(chat.id).frage == '{"frage": "Welche?"}'
    assert repos.chats.frage_setzen(chat.id, None) is True
    assert repos.chats.holen(chat.id).frage is None


def test_chat_loeschen(repos):
    chat = repos.chats.erstellen(user_id="benutzer", title="Weg damit")
    assert repos.chats.loeschen(chat.id) is True
    assert repos.chats.holen(chat.id) is None
    assert repos.chats.loeschen(chat.id) is False


# --- Messages --------------------------------------------------------------


def test_nachricht_speichern_und_auflisten(repos):
    chat = repos.chats.erstellen(user_id="benutzer", title="Chat")
    repos.messages.speichern(chat_id=chat.id, role="user", content="Hallo")
    repos.messages.speichern(
        chat_id=chat.id,
        role="assistant",
        content="Guten Tag",
        reasoning="Kurz überlegt",
        stats={"tokens_pro_sekunde": 12.4, "tokens": 3},
    )

    nachrichten = repos.messages.auflisten(chat_id=chat.id)
    assert [n.role for n in nachrichten] == ["user", "assistant"]
    assert nachrichten[1].reasoning == "Kurz überlegt"
    assert nachrichten[1].stats["tokens_pro_sekunde"] == 12.4


def test_stats_ueberleben_die_datenbank(repos):
    chat = repos.chats.erstellen(user_id="benutzer", title="Chat")
    nachricht = repos.messages.speichern(
        chat_id=chat.id, role="assistant", content="x", stats={"dauer_sekunden": 1.5}
    )
    geholt = repos.messages.holen(nachricht.id)
    assert geholt.stats == {"dauer_sekunden": 1.5}


def test_nachricht_ohne_stats_hat_leeres_dict(repos):
    chat = repos.chats.erstellen(user_id="benutzer", title="Chat")
    nachricht = repos.messages.speichern(chat_id=chat.id, role="user", content="x")
    assert repos.messages.holen(nachricht.id).stats == {}


def test_ungueltige_rolle_wird_abgewiesen(repos):
    import sqlite3

    chat = repos.chats.erstellen(user_id="benutzer", title="Chat")
    with pytest.raises(sqlite3.IntegrityError):
        repos.messages.speichern(chat_id=chat.id, role="hausmeister", content="x")


def test_nachricht_nachtraeglich_fuellen(repos):
    """During streaming, an empty placeholder is created first."""
    chat = repos.chats.erstellen(user_id="benutzer", title="Chat")
    platzhalter = repos.messages.speichern(chat_id=chat.id, role="assistant", content="")
    gefuellt = repos.messages.inhalt_aktualisieren(
        platzhalter.id, content="Fertige Antwort", reasoning="…", stats={"tokens": 42}
    )
    assert gefuellt.content == "Fertige Antwort"
    assert gefuellt.stats["tokens"] == 42


def test_letzte_nachricht_je_rolle(repos):
    chat = repos.chats.erstellen(user_id="benutzer", title="Chat")
    repos.messages.speichern(chat_id=chat.id, role="user", content="erste")
    repos.messages.speichern(chat_id=chat.id, role="assistant", content="antwort")
    repos.messages.speichern(chat_id=chat.id, role="user", content="zweite")

    assert repos.messages.letzte(chat_id=chat.id).content == "zweite"
    assert repos.messages.letzte(chat_id=chat.id, role="assistant").content == "antwort"


def test_chat_loeschen_raeumt_nachrichten_mit_ab(repos):
    """ON DELETE CASCADE — otherwise orphans linger in the database."""
    chat = repos.chats.erstellen(user_id="benutzer", title="Chat")
    repos.messages.speichern(chat_id=chat.id, role="user", content="Hallo")
    repos.documents.speichern(chat_id=chat.id, filename="brief.pdf")

    repos.chats.loeschen(chat.id)

    assert repos.messages.auflisten(chat_id=chat.id) == []
    assert repos.documents.auflisten(chat_id=chat.id) == []


def test_nachricht_ohne_chat_wird_abgewiesen(repos):
    import sqlite3

    with pytest.raises(sqlite3.IntegrityError):
        repos.messages.speichern(chat_id="gibtsnicht", role="user", content="x")


# --- Documents -------------------------------------------------------------


def test_dokument_speichern_und_auflisten(repos):
    chat = repos.chats.erstellen(user_id="benutzer", title="Chat")
    dokument = repos.documents.speichern(
        chat_id=chat.id,
        filename="handbuch.pdf",
        mime_type="application/pdf",
        size_bytes=1024,
        extracted_text="Inhalt des Handbuchs",
    )
    liste = repos.documents.auflisten(chat_id=chat.id)
    assert len(liste) == 1
    assert liste[0].id == dokument.id
    assert liste[0].extracted_text == "Inhalt des Handbuchs"


# --- Transactions ------------------------------------------------------------


def test_transaktion_rollt_bei_fehler_zurueck(db: Database):
    repos = repositories_erstellen(db)
    vorher = repos.chats.anzahl(user_id="benutzer")

    with pytest.raises(RuntimeError):
        with db.transaktion():
            repos.chats.erstellen(user_id="benutzer", title="Wird verworfen")
            raise RuntimeError("Abbruch")

    assert repos.chats.anzahl(user_id="benutzer") == vorher



# --- Two services on one data folder -------------------------------------


def test_die_startbereinigung_laesst_fremde_zeilen_stehen(tmp_path):
    """Two services, one data folder, and each cleans up only after itself.

    The test service beside the ordinary program is a wanted case: both use
    the same `data_dir`, because it does not vary with the port. Until every
    running row carried its owner, the cleanup could not tell whose stranded
    rows it saw — so it stayed out entirely while a second service was up,
    and every row the other one left on 'laeuft' stayed that way for good.

    Here one database is opened twice, once per port. Each writes a running
    job and a running answer, then the one on 8095 restarts while the other
    is still up (``nur_eigene``): its own two rows are over, the other's two
    are untouched — and they are untouched precisely because they might be
    running right now.
    """
    pfad = tmp_path / "geteilt.db"
    eins = Database(pfad, dienst_port=8095)
    eins.schema_einrichten()
    zwei = Database(pfad, dienst_port=8093)
    repos_eins = repositories_erstellen(eins)
    repos_zwei = repositories_erstellen(zwei)

    auftrag_eins = repos_eins.auftraege.erstellen(
        user_id="lokal", agent="a", auftrag="eins"
    )
    auftrag_zwei = repos_zwei.auftraege.erstellen(
        user_id="lokal", agent="a", auftrag="zwei"
    )
    chat = repos_eins.chats.erstellen(user_id="lokal", title="c")
    antwort_eins = repos_eins.messages.speichern(
        chat_id=chat.id, role="assistant", content="", zustand="laeuft"
    )
    antwort_zwei = repos_zwei.messages.speichern(
        chat_id=chat.id, role="assistant", content="", zustand="laeuft"
    )

    assert repos_eins.auftraege.beim_start_aufraeumen(nur_eigene=True) == 1
    assert repos_eins.messages.beim_start_aufraeumen(nur_eigene=True) == 1

    assert repos_eins.auftraege.holen(auftrag_eins.id).zustand == "unterbrochen"
    assert repos_eins.auftraege.holen(auftrag_zwei.id).zustand == "laeuft"
    zustaende = {
        zeile["id"]: zeile["zustand"]
        for zeile in eins.verbindung.execute(
            "SELECT id, zustand FROM messages"
        ).fetchall()
    }
    assert zustaende[antwort_eins.id] == "abgebrochen"
    assert zustaende[antwort_zwei.id] == "laeuft"

    eins.schliessen()
    zwei.schliessen()


def test_mit_nur_einem_dienst_raeumt_sie_weiter_alles_auf(tmp_path):
    """The silence test: alone on the folder, nothing changes for the worse.

    Two kinds of row would be stranded for ever if the owner column narrowed
    this case too: one written before the column existed, which carries no
    port at all, and one left by a service that died on ANOTHER port, which
    carries a port nobody will ever start on again. Alone on the folder
    neither has anybody left to come back for it, so both are cleaned —
    exactly as they were before this column.
    """
    pfad = tmp_path / "allein.db"
    db = Database(pfad, dienst_port=8095)
    db.schema_einrichten()
    repos = repositories_erstellen(db)

    eigener = repos.auftraege.erstellen(user_id="lokal", agent="a", auftrag="eins")
    chat = repos.chats.erstellen(user_id="lokal", title="c")
    eigene_antwort = repos.messages.speichern(
        chat_id=chat.id, role="assistant", content="", zustand="laeuft"
    )
    # A row from before the column: no owner at all.
    db.verbindung.execute(
        "UPDATE auftraege SET dienst_port = NULL WHERE id = ?", (eigener.id,)
    )
    db.verbindung.execute(
        "UPDATE messages SET dienst_port = NULL WHERE id = ?", (eigene_antwort.id,)
    )

    # And one a service on another port left behind when it died.
    fremder = repos.auftraege.erstellen(user_id="lokal", agent="a", auftrag="zwei")
    db.verbindung.execute(
        "UPDATE auftraege SET dienst_port = 8099 WHERE id = ?", (fremder.id,)
    )
    fremde_antwort = repos.messages.speichern(
        chat_id=chat.id, role="assistant", content="", zustand="laeuft"
    )
    db.verbindung.execute(
        "UPDATE messages SET dienst_port = 8099 WHERE id = ?", (fremde_antwort.id,)
    )

    assert repos.auftraege.beim_start_aufraeumen() == 2
    assert repos.messages.beim_start_aufraeumen() == 2
    assert repos.auftraege.holen(eigener.id).zustand == "unterbrochen"
    assert repos.auftraege.holen(fremder.id).zustand == "unterbrochen"

    db.schliessen()


def test_ohne_kennung_gibt_es_keinen_engen_fall(tmp_path):
    """A cleanup narrowed to its own rows needs a port, and says so.

    Without one the condition would read `dienst_port = NULL`, which
    matches no row in SQLite: all three startup writes would report nothing
    to clean and be believed. Loud is the only safe way to be wrong here.
    """
    db = Database(tmp_path / "ohne.db")
    db.schema_einrichten()
    repos = repositories_erstellen(db)

    with pytest.raises(ValueError, match="dienst_port"):
        repos.auftraege.beim_start_aufraeumen(nur_eigene=True)
    with pytest.raises(ValueError, match="dienst_port"):
        repos.messages.beim_start_aufraeumen(nur_eigene=True)
    # Wide open it works without one: nobody else is on the folder.
    assert repos.auftraege.beim_start_aufraeumen() == 0

    db.schliessen()


# --- an attempt that was to replace an answer, cut off by a hard end --------


def _answer_and_attempt(repos, *, names_old: bool = True):
    chat = repos.chats.erstellen(user_id="lokal", title="c")
    repos.messages.speichern(chat_id=chat.id, role="user", content="question")
    old = repos.messages.speichern(
        chat_id=chat.id, role="assistant", content="old answer", zustand="fertig"
    )
    attempt = repos.messages.speichern(
        chat_id=chat.id,
        role="assistant",
        content="",
        zustand="laeuft",
        replaces_id=old.id if names_old else None,
    )
    return chat, old, attempt


def test_a_replacing_attempt_cut_off_by_a_hard_end_leaves_only_the_old_answer(repos):
    chat, old, attempt = _answer_and_attempt(repos)

    repos.messages.beim_start_aufraeumen()

    rows = repos.messages.auflisten(chat_id=chat.id)
    assert [r.id for r in rows if r.role == "assistant"] == [old.id]
    assert repos.messages.holen(old.id).zustand == "fertig"
    assert repos.messages.holen(attempt.id) is None


def test_silence_an_ordinary_running_answer_is_marked_stopped_as_before(repos):
    chat, old, attempt = _answer_and_attempt(repos, names_old=False)

    repos.messages.beim_start_aufraeumen()

    assert repos.messages.holen(attempt.id).zustand == "abgebrochen"
    assert repos.messages.holen(old.id).zustand == "fertig"


def test_silence_an_attempt_whose_old_answer_is_gone_is_marked_stopped(repos):
    chat, old, attempt = _answer_and_attempt(repos)
    repos.messages.loeschen(old.id)

    repos.messages.beim_start_aufraeumen()

    assert repos.messages.holen(attempt.id).zustand == "abgebrochen"


def test_silence_a_finished_replacement_stays_and_names_nobody(repos):
    chat, old, attempt = _answer_and_attempt(repos)

    repos.messages.finish_in_place_of(attempt.id, old.id, content="new answer", zustand="fertig")
    repos.messages.beim_start_aufraeumen()

    kept = repos.messages.holen(attempt.id)
    assert (kept.content, kept.zustand) == ("new answer", "fertig")
    assert repos.messages.holen(old.id) is None
    named = repos.db.verbindung.execute(
        "SELECT replaces_id FROM messages WHERE id = ?", (attempt.id,)
    ).fetchone()["replaces_id"]
    assert named is None


def test_a_replacing_attempt_of_a_second_live_service_is_left_alone(tmp_path):
    path = tmp_path / "shared-attempt.db"
    one = Database(path, dienst_port=8095)
    one.schema_einrichten()
    two = Database(path, dienst_port=8093)
    repos_one = repositories_erstellen(one)
    repos_two = repositories_erstellen(two)
    chat = repos_one.chats.erstellen(user_id="lokal", title="c")
    old_one = repos_one.messages.speichern(
        chat_id=chat.id, role="assistant", content="old", zustand="fertig"
    )
    mine = repos_one.messages.speichern(
        chat_id=chat.id, role="assistant", content="", zustand="laeuft",
        replaces_id=old_one.id,
    )
    old_two = repos_two.messages.speichern(
        chat_id=chat.id, role="assistant", content="older", zustand="fertig"
    )
    theirs = repos_two.messages.speichern(
        chat_id=chat.id, role="assistant", content="", zustand="laeuft",
        replaces_id=old_two.id,
    )

    assert repos_one.messages.beim_start_aufraeumen(nur_eigene=True) == 1

    # My own attempt is gone; the other service's is its live work.
    assert repos_one.messages.holen(mine.id) is None
    assert repos_one.messages.holen(theirs.id).zustand == "laeuft"
    assert repos_one.messages.holen(old_two.id).zustand == "fertig"
