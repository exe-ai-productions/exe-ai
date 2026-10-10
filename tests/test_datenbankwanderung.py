"""An update must not cost anybody their chats.

schema.sql describes the target state and every statement in it says IF NOT
EXISTS, so a database that already exists gets new tables for free. What it
does NOT get for free is a new COLUMN on a table it already has — IF NOT
EXISTS does nothing there, and the ALTER has to be written down as a
migration.

These tests build a database at an older schema version, run the upgrade over
it the way a service start does, and check both halves: the new shape is
there, and the old content is still there.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from app.db import Database, connection
from app.db.connection import MIGRATIONEN, SCHEMA_VERSION


def _spalten(db: Database, tabelle: str) -> set[str]:
    return {
        zeile["name"]
        for zeile in db.verbindung.execute(f"PRAGMA table_info({tabelle})").fetchall()
    }


def _auf_version_zuruecksetzen(db: Database, version: int) -> None:
    """Make the database look like it was built before `version` ran."""
    db.verbindung.execute("DELETE FROM schema_version WHERE version > ?", (version,))
    db.verbindung.commit()


# The five columns migration 28 adds, in the order it adds them.
SPALTEN_28 = ("art", "zustand", "lauf_id", "gesamt_tokens", "verdichtet_in")


def _echte_27er_datenbank(db: Database) -> None:
    """Not just "forget the version" — actually take migration 28 back out.

    `_auf_version_zuruecksetzen` leaves the columns in place, which is enough
    to re-run the backfills but says nothing about the ALTERs. A test that
    wants to know whether a failed step leaves the SHAPE behind has to start
    from a database that really does not have them yet. The index and the
    trigger go first: SQLite refuses to drop a column either still names.
    """
    db.verbindung.execute("DROP INDEX IF EXISTS idx_messages_lauf")
    db.verbindung.execute("DROP TRIGGER IF EXISTS messages_verdichtung_freigeben")
    # The partial index rides on `verdichtet_in` and blocks the DROP COLUMN
    # below just like the trigger does.
    db.verbindung.execute("DROP INDEX IF EXISTS idx_messages_verdichtet_in")
    for spalte in SPALTEN_28:
        db.verbindung.execute(f"ALTER TABLE messages DROP COLUMN {spalte}")
    _auf_version_zuruecksetzen(db, 27)


def _spalten_von_28(db: Database) -> list[str]:
    vorhanden = _spalten(db, "messages")
    return [spalte for spalte in SPALTEN_28 if spalte in vorhanden]


# --- The shape ------------------------------------------------------------


def test_eine_neue_datenbank_hat_alles(db: Database):
    assert "truncated" in _spalten(db, "documents")


def test_die_wanderungen_sind_lueckenlos_bis_zur_version():
    """A version nobody wrote a step for is a step that never runs."""
    nummern = [nummer for nummer, _ in MIGRATIONEN]
    assert nummern == sorted(nummern), "migrations are not in order"
    assert len(nummern) == len(set(nummern)), "a version number is duplicated"
    assert max(nummern) <= SCHEMA_VERSION


# --- The upgrade ----------------------------------------------------------


def _v32_datenbank(tmp_path, name="alt.db"):
    """A database built with the columns and the table migration 33 removes —
    as an install that reached version 32 and never went further would
    have them."""
    pfad = tmp_path / name
    db = Database(pfad)
    db.schema_einrichten()
    db.verbindung.executescript(
        """
        ALTER TABLE documents ADD COLUMN zusammenfassung TEXT;
        ALTER TABLE documents ADD COLUMN zusammenfassung_ziel INTEGER;
        CREATE TABLE dokument_abschnitte (
            id          TEXT PRIMARY KEY,
            document_id TEXT NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
            nummer      INTEGER NOT NULL,
            text        TEXT NOT NULL,
            vektor      BLOB NOT NULL,
            modell      TEXT NOT NULL DEFAULT '',
            created_at  TEXT NOT NULL
        );
        CREATE INDEX idx_abschnitte_dokument ON dokument_abschnitte (document_id, nummer);
        """
    )
    _auf_version_zuruecksetzen(db, 32)
    return db


def test_eine_bestehende_datenbank_verliert_die_verdichtungsspalten(tmp_path):
    db = _v32_datenbank(tmp_path)
    assert "zusammenfassung" in _spalten(db, "documents")
    assert "zusammenfassung_ziel" in _spalten(db, "documents")

    # What a service start does.
    db.schema_einrichten()

    assert "zusammenfassung" not in _spalten(db, "documents")
    assert "zusammenfassung_ziel" not in _spalten(db, "documents")
    assert not db.verbindung.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'dokument_abschnitte'"
    ).fetchone()


def test_eine_v32_datenbank_mit_werten_wandert_sauber(tmp_path):
    """The real case: a document that already carries a condensed version
    and sections with real vectors, on a database that really reached
    version 32. The columns and the table go, the document and its chat
    stay exactly as they were otherwise."""
    db = _v32_datenbank(tmp_path)
    db.verbindung.execute(
        "INSERT INTO chats (id, user_id, title, created_at, updated_at)"
        " VALUES ('c1', 'u1', 'Ein Bericht', '2020-01-01', '2020-01-01')"
    )
    db.verbindung.execute(
        "INSERT INTO documents (id, chat_id, filename, extracted_text,"
        " zusammenfassung, zusammenfassung_ziel, created_at)"
        " VALUES ('d1', 'c1', 'bericht.pdf', ?, 'Das Wesentliche.', 2000, '2020-01-01')",
        ("A" * 300_000,),
    )
    db.verbindung.execute(
        "INSERT INTO dokument_abschnitte (id, document_id, nummer, text, vektor, modell,"
        " created_at) VALUES ('a1', 'd1', 0, 'Abschnitt 0', X'00000000', 'm', '2020-01-01')"
    )
    db.verbindung.commit()

    db.schema_einrichten()

    assert "zusammenfassung" not in _spalten(db, "documents")
    assert "zusammenfassung_ziel" not in _spalten(db, "documents")
    assert not db.verbindung.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'dokument_abschnitte'"
    ).fetchone()
    dokument = db.verbindung.execute(
        "SELECT filename, extracted_text FROM documents WHERE id = 'd1'"
    ).fetchone()
    assert dokument["filename"] == "bericht.pdf"
    assert dokument["extracted_text"] == "A" * 300000
    chat = db.verbindung.execute("SELECT title FROM chats WHERE id = 'c1'").fetchone()
    assert chat["title"] == "Ein Bericht"


def test_der_inhalt_ueberlebt_die_wanderung(tmp_path):
    """The point of the whole exercise."""
    db = _v32_datenbank(tmp_path)
    db.verbindung.execute(
        "INSERT INTO chats (id, user_id, title, created_at, updated_at)"
        " VALUES ('c1', 'u1', 'Ein alter Chat', '2020-01-01', '2020-01-01')"
    )
    db.verbindung.commit()

    db.schema_einrichten()

    zeile = db.verbindung.execute("SELECT title FROM chats WHERE id = 'c1'").fetchone()
    assert zeile is not None
    assert zeile["title"] == "Ein alter Chat"


def test_zweimal_wandern_aendert_nichts_mehr(tmp_path):
    db = _v32_datenbank(tmp_path)

    db.schema_einrichten()
    db.schema_einrichten()

    assert "zusammenfassung" not in _spalten(db, "documents")
    assert not db.verbindung.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'dokument_abschnitte'"
    ).fetchone()


def test_eine_datenbank_aelter_als_die_tabelle_wandert_trotzdem(tmp_path):
    """The oldest case, and the one that caught this.

    Migrations run before schema.sql. A column added to a young table is
    therefore asked for on databases that do not have that table yet — and
    the ALTER fails with "no such table". schema.sql creates it a moment
    later, with the column already in it, so there is nothing to repair;
    the step simply has nothing to do. Migration 33 drops the column again
    right after, so what such an install ends up with is simply not having
    it at all — which is also the target state, so nothing here needs to
    repair anything either.
    """
    pfad = tmp_path / "sehr_alt.db"
    db = Database(pfad)
    db.schema_einrichten()

    # An installation from before the condensed version existed at all.
    _auf_version_zuruecksetzen(db, 1)
    db.verbindung.commit()

    db.schema_einrichten()

    assert "zusammenfassung" not in _spalten(db, "documents")


def test_die_wanderung_stolpert_nicht_ueber_eine_spalte_die_schon_weg_ist(tmp_path):
    """A database built from the current schema.sql never had the column."""
    pfad = tmp_path / "neu.db"
    db = Database(pfad)
    db.schema_einrichten()
    _auf_version_zuruecksetzen(db, 32)

    # Must not raise: the DROP hits a column that is already gone, which
    # means the step has effectively already happened.
    db.schema_einrichten()
    assert "zusammenfassung" not in _spalten(db, "documents")


def test_cronjobs_datum_wandert_ohne_datenverlust(tmp_path):
    """An existing cron table gets ``datum`` added, and a row
    already in it keeps everything it had."""
    pfad = tmp_path / "alt.db"
    db = Database(pfad)
    db.schema_einrichten()
    db.verbindung.execute(
        "INSERT INTO cronjobs (id, agent, task, zeitplan, herkunft, created_at, updated_at)"
        " VALUES ('c1', 'a', 'Los', '08:00', 'chat', '2020-01-01', '2020-01-01')"
    )
    db.verbindung.commit()

    db.verbindung.execute("ALTER TABLE cronjobs DROP COLUMN datum")
    _auf_version_zuruecksetzen(db, 16)
    assert "datum" not in _spalten(db, "cronjobs")

    db.schema_einrichten()

    assert "datum" in _spalten(db, "cronjobs")
    zeile = db.verbindung.execute(
        "SELECT task, datum FROM cronjobs WHERE id = 'c1'"
    ).fetchone()
    assert zeile["task"] == "Los"
    assert zeile["datum"] is None


def test_cronjobs_stray_datum_auf_taeglichem_eintrag_wird_geraeumt(tmp_path):
    """A row from before 'update' enforced the
    rule loses a stray 'datum' on a daily entry, but keeps everything else,
    and a one-off's own date is left alone."""
    pfad = tmp_path / "alt.db"
    db = Database(pfad)
    db.schema_einrichten()
    db.verbindung.execute(
        "INSERT INTO cronjobs (id, agent, task, zeitplan, herkunft, created_at,"
        " updated_at, einmalig, datum)"
        " VALUES ('c1', 'a', 'Los', '08:00', 'chat', '2020-01-01', '2020-01-01', 0, '2020-01-02')"
    )
    db.verbindung.execute(
        "INSERT INTO cronjobs (id, agent, task, zeitplan, herkunft, created_at,"
        " updated_at, einmalig, datum)"
        " VALUES ('c2', 'a', 'Termin', '09:00', 'chat', '2020-01-01', '2020-01-01', 1, '2099-01-01')"
    )
    db.verbindung.commit()
    _auf_version_zuruecksetzen(db, 17)

    db.schema_einrichten()

    taeglich = db.verbindung.execute(
        "SELECT task, datum FROM cronjobs WHERE id = 'c1'"
    ).fetchone()
    assert taeglich["task"] == "Los"
    assert taeglich["datum"] is None

    einmalig = db.verbindung.execute(
        "SELECT datum FROM cronjobs WHERE id = 'c2'"
    ).fetchone()
    assert einmalig["datum"] == "2099-01-01"


def test_bilder_spalte_wandert_ohne_datenverlust(tmp_path):
    """Messages gets 'bilder' for a run's own picture
    list. A bank already carrying real images-per-run rows (one question,
    several picture answers, each stats_json with lauf/nr/von) must come
    through byte for byte — not just the same row COUNT, which a delete
    paired with an insert would still pass."""
    pfad = tmp_path / "alt.db"
    db = Database(pfad)
    db.schema_einrichten()
    db.verbindung.execute(
        "INSERT INTO chats (id, user_id, title, created_at, updated_at)"
        " VALUES ('c1', 'u1', 'Ein Lauf', '2020-01-01', '2020-01-01')"
    )
    db.verbindung.execute(
        "INSERT INTO messages (id, chat_id, role, content, stats_json, created_at)"
        " VALUES ('m1', 'c1', 'user', 'ein rotes fahrrad',"
        " '{\"lauf\": \"lauf-x\"}', '2020-01-01T00:00:00')"
    )
    for nr in (1, 2):
        db.verbindung.execute(
            "INSERT INTO messages (id, chat_id, role, content, bild, stats_json, created_at)"
            " VALUES (?, 'c1', 'assistant', '', ?,"
            " ?, ?)",
            (
                f"m{nr + 1}",
                f"bild-{nr}.png",
                f'{{"lauf": "lauf-x", "nr": {nr}, "von": 2}}',
                f"2020-01-01T00:0{nr}:00",
            ),
        )
    db.verbindung.commit()

    vorher = {
        z["id"]: (z["content"], z["bild"])
        for z in db.verbindung.execute("SELECT id, content, bild FROM messages").fetchall()
    }
    db.verbindung.execute("ALTER TABLE messages DROP COLUMN bilder")
    _auf_version_zuruecksetzen(db, 18)
    assert "bilder" not in _spalten(db, "messages")

    db.schema_einrichten()

    assert "bilder" in _spalten(db, "messages")
    nachher = {
        z["id"]: (z["content"], z["bild"])
        for z in db.verbindung.execute("SELECT id, content, bild FROM messages").fetchall()
    }
    assert nachher == vorher
    # The new column exists but writes nothing on its own — a run's old
    # single-filename rows are not runs and are left exactly as they were.
    leer = db.verbindung.execute(
        "SELECT COUNT(*) n FROM messages WHERE bilder IS NOT NULL"
    ).fetchone()["n"]
    assert leer == 0


def test_neue_datenbank_hat_die_bilder_spalte(db: Database):
    assert "bilder" in _spalten(db, "messages")


# --- What the column is for -----------------------------------------------


def test_wanderung_28_erkennt_eine_werkzeugmeldung_am_werkzeugprotokoll(db: Database):
    """The header alone is not evidence.

    An answer that merely QUOTES a report it was just shown starts with the
    same words, and a misfiled answer loses its regenerate arrow and has its
    text hidden under whatever tool card it carries. What only a real report
    has is the shape `hintergrundmeldung.py` writes: one tool entry, for
    `run_command`, with `background` true.
    """
    echt = json.dumps({"werkzeuge": [{
        "name": "run_command", "server": "shell",
        "argumente": {"command": "brew install node", "background": True},
        "fehlgeschlagen": False, "ergebnis": "ok",
    }]})
    # Same opening words, an ordinary answer that used a tool along the way.
    zitiert = json.dumps({"werkzeuge": [{
        "name": "read_file", "server": "dateien",
        "argumente": {"path": "notiz.md"}, "fehlgeschlagen": False, "ergebnis": "…",
    }]})
    db.verbindung.execute(
        "INSERT INTO chats (id, user_id, title, created_at, updated_at) "
        "VALUES ('c-w28', 'u', 'Wanderung', '2020-01-01T00:00:00', '2020-01-01T00:00:00')"
    )
    for kennung, stats in (("m-echt", echt), ("m-zitiert", zitiert)):
        db.verbindung.execute(
            "INSERT INTO messages (id, chat_id, role, content, stats_json, created_at) "
            "VALUES (?, 'c-w28', 'assistant', "
            "'[background run #4 finished: brew install node]', ?, '2020-01-01T00:00:01')",
            (kennung, stats),
        )
    db.verbindung.execute("UPDATE messages SET art = 'nachricht'")
    _auf_version_zuruecksetzen(db, 27)

    db.schema_einrichten()

    arten = dict(
        db.verbindung.execute("SELECT id, art FROM messages WHERE chat_id = 'c-w28'")
    )
    assert arten["m-echt"] == "werkzeugmeldung"
    assert arten["m-zitiert"] == "nachricht"


def test_wanderung_28_erkennt_das_bild_aus_dem_bildfenster(db: Database):
    """The picture window's row is a picture, and has no run.

    Before `art` existed the window wrote its answer as an ordinary
    assistant turn with empty content (``bild.py``: ``role="assistant",
    content="", bild=name, stats={"seed": seed}``). Left as `nachricht`,
    such a row becomes `letzteAntwort` in App.svelte, gets the regenerate
    arrow drawn on it — and that arrow deletes the row before fetching a
    text answer in its place. The picture would be thrown away on a
    migrated database, which is exactly the state before the change.

    `zustand` is the second half: the backfill hands 'fertig' to every
    remaining assistant row, and a picture has no run whose end could be
    reported.
    """
    db.verbindung.execute(
        "INSERT INTO chats (id, user_id, title, created_at, updated_at) "
        "VALUES ('c-b28', 'u', 'Bilder', '2020-01-01T00:00:00', '2020-01-01T00:00:00')"
    )
    # A question with a picture hanging on it: a vision attachment, and an
    # ordinary message — the `role` half of the test.
    db.verbindung.execute(
        "INSERT INTO messages (id, chat_id, role, content, bild, created_at) "
        "VALUES ('m-sicht', 'c-b28', 'user', 'Was ist das?', 'foto.png', "
        "'2020-01-01T00:00:01')"
    )
    # What the picture window wrote.
    db.verbindung.execute(
        "INSERT INTO messages (id, chat_id, role, content, bild, stats_json, created_at) "
        "VALUES ('m-fenster', 'c-b28', 'assistant', '', 'bild-1.png', ?, "
        "'2020-01-01T00:00:02')",
        (json.dumps({"seed": 4711}),),
    )
    # A run's picture row, which `bilder` already identified.
    db.verbindung.execute(
        "INSERT INTO messages (id, chat_id, role, content, bild, bilder, stats_json, created_at) "
        "VALUES ('m-lauf', 'c-b28', 'assistant', '', 'b1.png', ?, ?, "
        "'2020-01-01T00:00:03')",
        (json.dumps(["b1.png"]), json.dumps({"lauf": "lauf-x"})),
    )
    # An ordinary answer, which must keep both its kind and its state — the
    # step must not be wide enough to swallow a real turn.
    db.verbindung.execute(
        "INSERT INTO messages (id, chat_id, role, content, stats_json, created_at) "
        "VALUES ('m-antwort', 'c-b28', 'assistant', 'Bitte sehr.', '{}', "
        "'2020-01-01T00:00:04')"
    )
    db.verbindung.execute("UPDATE messages SET art = 'nachricht', zustand = NULL")
    _auf_version_zuruecksetzen(db, 27)

    db.schema_einrichten()

    def stand() -> dict[str, tuple[str, str | None]]:
        return {
            z["id"]: (z["art"], z["zustand"])
            for z in db.verbindung.execute(
                "SELECT id, art, zustand FROM messages WHERE chat_id = 'c-b28'"
            )
        }

    erwartet = {
        "m-sicht": ("nachricht", None),
        "m-fenster": ("bild", None),
        "m-lauf": ("bildlauf", None),
        "m-antwort": ("nachricht", "fertig"),
    }
    assert stand() == erwartet

    # The list is applied statement by statement, and a run that dies in the
    # middle of it leaves the version unraised — so the whole list runs again
    # on the next start. A second pass has to end where the first one did.
    _auf_version_zuruecksetzen(db, 27)
    db.schema_einrichten()
    assert stand() == erwartet


def _chat_mit_werkzeugbild(db: Database, *, art: str, zustand: str | None) -> None:
    """One chat, two rows: a picture the window wrote, and a chat answer whose
    model drew one picture through a tool and wrote nothing beside it. On the
    disk the two look the same — empty content, a lone `bild`, no `bilder` —
    and only the tool log tells them apart."""
    db.verbindung.execute(
        "INSERT INTO chats (id, user_id, title, created_at, updated_at) "
        "VALUES ('c-wb', 'u', 'Werkzeugbild', '2020-01-01T00:00:00', '2020-01-01T00:00:00')"
    )
    db.verbindung.execute(
        "INSERT INTO messages (id, chat_id, role, content, bild, stats_json, art, created_at) "
        "VALUES ('m-fenster', 'c-wb', 'assistant', '', 'bild-1.png', ?, ?, '2020-01-01T00:00:02')",
        (json.dumps({"seed": 4711}), art),
    )
    db.verbindung.execute(
        "INSERT INTO messages (id, chat_id, role, content, bild, stats_json, art, zustand, created_at) "
        "VALUES ('m-werkzeug', 'c-wb', 'assistant', '', 'werkzeug.png', ?, ?, ?, "
        "'2020-01-01T00:00:03')",
        (json.dumps({"werkzeuge": [{"name": "draw_picture", "argumente": {}}]}), art, zustand),
    )


def _stand_werkzeugbild(db: Database) -> dict[str, tuple[str, str | None]]:
    return {
        z["id"]: (z["art"], z["zustand"])
        for z in db.verbindung.execute(
            "SELECT id, art, zustand FROM messages WHERE chat_id = 'c-wb'"
        )
    }


def test_wanderung_28_laesst_eine_werkzeugbild_antwort_eine_antwort(db: Database):
    """A chat answer that consists of one tool-drawn picture has the picture
    window's shape on disk — empty content, a lone `bild`, no `bilder` — but
    it IS a turn: it has a run, a state, and the regenerate arrow belongs on
    it. Filed as a picture it would lose all three, and the arrow would move
    onto the answer before it, which "send again" then deletes. The tool
    log is what tells it apart from the window's row."""
    _chat_mit_werkzeugbild(db, art="nachricht", zustand=None)
    _auf_version_zuruecksetzen(db, 27)

    db.schema_einrichten()

    assert _stand_werkzeugbild(db) == {
        "m-fenster": ("bild", None),
        "m-werkzeug": ("nachricht", "fertig"),
    }


def test_wanderung_29_holt_eine_misfiled_werkzeugbild_antwort_zurueck(db: Database):
    """A database that crossed 28 before the step learned to read the tool
    log carries the misfiling already; 28 cannot be re-run for it. Step 29
    puts the kind and the state back, and leaves the window's own row alone."""
    _chat_mit_werkzeugbild(db, art="bild", zustand=None)
    _auf_version_zuruecksetzen(db, 28)

    db.schema_einrichten()

    erwartet = {
        "m-fenster": ("bild", None),
        "m-werkzeug": ("nachricht", "fertig"),
    }
    assert _stand_werkzeugbild(db) == erwartet

    _auf_version_zuruecksetzen(db, 28)
    db.schema_einrichten()
    assert _stand_werkzeugbild(db) == erwartet


def test_wanderung_30_bringt_den_ausloeser_auf_eine_bestehende_datenbank(db: Database):
    """A database that crossed 29 has no trigger; step 30 gives it the same
    one schema.sql creates for a fresh database, and a second pass leaves
    it as it is."""
    _auf_version_zuruecksetzen(db, 29)
    db.verbindung.execute("DROP TRIGGER IF EXISTS messages_verdichtung_freigeben")
    assert not db.verbindung.execute(
        "SELECT name FROM sqlite_master WHERE type = 'trigger' AND name = 'messages_verdichtung_freigeben'"
    ).fetchone()

    db.schema_einrichten()

    assert db.verbindung.execute(
        "SELECT name FROM sqlite_master WHERE type = 'trigger' AND name = 'messages_verdichtung_freigeben'"
    ).fetchone()
    _auf_version_zuruecksetzen(db, 29)
    db.schema_einrichten()
    assert db.schema_version() == SCHEMA_VERSION


# --- What an unreadable stats blob must not do ----------------------------
#
# Migration 28 reads `stats_json` five times, and SQLite's JSON functions do
# not answer NULL on rubbish — they raise. One row the migration cannot read
# therefore stopped it in the middle of its own list: the columns were added,
# the version stayed at 27, and every following start died at the same row.
# Nothing healed, because nothing ever got as far as writing the version.


def _zeile(db: Database, kennung: str, role: str, content: str, stats: str | None,
           bild: str | None = None, bilder: str | None = None) -> None:
    db.verbindung.execute(
        "INSERT INTO messages (id, chat_id, role, content, stats_json, bild, bilder,"
        " created_at) VALUES (?, 'c-28', ?, ?, ?, ?, ?, '2020-01-01T00:00:00')",
        (kennung, role, content, stats, bild, bilder),
    )


def _chat(db: Database) -> None:
    db.verbindung.execute(
        "INSERT INTO chats (id, user_id, title, created_at, updated_at) "
        "VALUES ('c-28', 'u', 'Wanderung', '2020-01-01', '2020-01-01')"
    )


def _vor_28(db: Database) -> None:
    """The state migration 28 finds: the columns carry nothing but their default."""
    db.verbindung.execute(
        "UPDATE messages SET art = 'nachricht', zustand = NULL, lauf_id = NULL,"
        " gesamt_tokens = NULL"
    )
    _auf_version_zuruecksetzen(db, 27)


KOPF = "[background run #4 finished: brew install node]"


def test_wanderung_28_ueberlebt_werkzeuge_als_zeichenkette(tmp_path):
    """A readable blob whose `werkzeuge` is a STRING, on a real 27er database.

    Reachable through the API: `stats` is a free dict, so a client could post
    `{"werkzeuge": "run_command"}` under a background header. The old test
    was `json_array_length(json_extract(...))`, and `json_extract` unwraps a
    JSON string into plain SQL text that `json_array_length` then tries to
    parse a second time — so a blob SQLite reads perfectly well raised
    "malformed JSON" and took the service start with it.
    """
    db = Database(tmp_path / "alt.db")
    db.schema_einrichten()
    _chat(db)
    _zeile(db, "m-string", "assistant", KOPF, json.dumps({"werkzeuge": "run_command"}))
    _echte_27er_datenbank(db)
    assert _spalten_von_28(db) == []

    db.schema_einrichten()

    assert db.schema_version() == SCHEMA_VERSION
    assert _spalten_von_28(db) == list(SPALTEN_28)
    # A row whose tool log cannot be read is not a tool report — it is an
    # answer whose run is over, which is what every other unreadable row gets.
    zeile = db.verbindung.execute(
        "SELECT art, zustand FROM messages WHERE id = 'm-string'"
    ).fetchone()
    assert (zeile["art"], zeile["zustand"]) == ("nachricht", "fertig")


def test_wanderung_28_ueberlebt_einen_voellig_kaputten_stats_blob(tmp_path):
    """Not JSON at all — and it needs no crafted header to do damage.

    The `werkzeuge` case is only reached by a row that already starts with
    the background header; the `lauf_id` step below it has no guard on role
    or content at all, so ANY row carrying an unparseable blob, a user's
    question included, stopped the migration there.
    """
    db = Database(tmp_path / "alt.db")
    db.schema_einrichten()
    _chat(db)
    _zeile(db, "m-kaputt", "assistant", "Eine ganz gewoehnliche Antwort.", "kein json")
    _zeile(db, "m-frage", "user", "Und?", "auch kein json")
    _echte_27er_datenbank(db)

    db.schema_einrichten()

    assert db.schema_version() == SCHEMA_VERSION
    stand = dict(db.verbindung.execute("SELECT id, art FROM messages"))
    assert stand == {"m-kaputt": "nachricht", "m-frage": "nachricht"}


def test_wanderung_28_wiederholt_sich_nicht_bei_jedem_start(tmp_path):
    """The half of the defect that made it permanent.

    The five ALTERs commit on their own — the connection is in autocommit —
    while the version row is only written once the whole list is through. A
    step that died therefore left the shape changed and the version at 27, so
    the next start ran the same list again and died at the same row, for
    ever. Three starts in a row have to end in the same finished state.
    """
    db = Database(tmp_path / "alt.db")
    db.schema_einrichten()
    _chat(db)
    _zeile(db, "m-string", "assistant", KOPF, json.dumps({"werkzeuge": "run_command"}))
    _echte_27er_datenbank(db)

    for _ in range(3):
        db.schema_einrichten()
        assert db.schema_version() == SCHEMA_VERSION
        assert _spalten_von_28(db) == list(SPALTEN_28)


def test_wanderung_28_deutet_lesbare_zeilen_unveraendert(tmp_path):
    """The guards must not have moved a single readable row.

    Every expected value below is what the statements produced BEFORE the
    guards were added — the whole table was run through both versions of the
    list side by side, over 5520 well-formed rows, and they agreed on all of
    them. The rubbish rows stand in the same database on purpose: before the
    fix the migration died on them, and then none of the good rows below got
    their `art` or `zustand` either.
    """
    db = Database(tmp_path / "alt.db")
    db.schema_einrichten()
    _chat(db)
    echt = json.dumps({"werkzeuge": [{
        "name": "run_command", "server": "shell",
        "argumente": {"command": "brew install node", "background": True},
        "fehlgeschlagen": False, "ergebnis": "ok",
    }]})
    zitiert = json.dumps({"werkzeuge": [{"name": "read_file", "argumente": {}}]})

    _zeile(db, "m-meldung", "assistant", KOPF, echt)
    _zeile(db, "m-zitiert", "assistant", KOPF, zitiert)
    _zeile(db, "m-bild", "assistant", "", json.dumps({"seed": 4711}), bild="b.png")
    _zeile(db, "m-bildlauf", "assistant", "", json.dumps({"lauf": "l-1"}),
           bild="b1.png", bilder=json.dumps(["b1.png"]))
    _zeile(db, "m-abbruch", "assistant", "halb",
           json.dumps({"abgebrochen": True, "lauf": "l-2", "gesamt_tokens": 120}))
    _zeile(db, "m-fehler", "assistant", "kaputt", json.dumps({"fehler": "boom"}))
    _zeile(db, "m-fertig", "assistant", "Bitte sehr.", json.dumps({"gesamt_tokens": 99}))
    _zeile(db, "m-frage", "user", "Was ist das?", None, bild="foto.png")
    # The two rows that used to end the migration right here.
    _zeile(db, "m-string", "assistant", KOPF, json.dumps({"werkzeuge": "run_command"}))
    _zeile(db, "m-kaputt", "assistant", "gewoehnlich", "kein json")
    _vor_28(db)

    db.schema_einrichten()

    stand = {
        z["id"]: (z["art"], z["zustand"], z["lauf_id"], z["gesamt_tokens"])
        for z in db.verbindung.execute(
            "SELECT id, art, zustand, lauf_id, gesamt_tokens FROM messages"
        )
    }
    assert stand == {
        "m-meldung": ("werkzeugmeldung", None, None, None),
        "m-zitiert": ("nachricht", "fertig", None, None),
        "m-bild": ("bild", None, None, None),
        "m-bildlauf": ("bildlauf", None, "l-1", None),
        "m-abbruch": ("nachricht", "abgebrochen", "l-2", 120),
        "m-fehler": ("nachricht", "fehler", None, None),
        "m-fertig": ("nachricht", "fertig", None, 99),
        "m-frage": ("nachricht", None, None, None),
        "m-string": ("nachricht", "fertig", None, None),
        "m-kaputt": ("nachricht", "fertig", None, None),
    }


def test_ein_schritt_der_stirbt_laesst_nichts_zurueck(db: Database, monkeypatch):
    """A migration is one thing or it is nothing.

    In autocommit each statement stood on its own, so a step that died in the
    middle left its first statements applied while the version said they had
    never run — a shape belonging to no version anybody wrote down, with new
    columns that exist and were never filled in. The step is now one
    transaction together with the row that says it ran.
    """
    _chat(db)
    # A row for the failing statement to stumble over: an UPDATE that matches
    # nothing never evaluates its expression, and would not fail at all.
    _zeile(db, "m-1", "assistant", "Bitte sehr.", "kein json")
    monkeypatch.setattr(
        connection,
        "MIGRATIONEN",
        [(SCHEMA_VERSION + 1, [
            "ALTER TABLE messages ADD COLUMN probe TEXT",
            "UPDATE messages SET probe = json_extract(stats_json, '$.x')",
        ])],
    )

    with pytest.raises(sqlite3.OperationalError):
        db.schema_einrichten()

    assert "probe" not in _spalten(db, "messages")
    assert db.schema_version() == SCHEMA_VERSION


def test_ein_unbekannter_fehler_wird_nicht_verschluckt(db: Database, monkeypatch):
    """Loud is the point.

    The runner swallows exactly three messages, and each one PROVES the step
    had nothing left to do. Anything else proves the opposite — a row was not
    migrated — and swallowing it would stamp the new version on a database
    whose new columns nobody ever filled in. A migration that stops can be
    repaired; one that is skipped in silence cannot even be found.
    """
    monkeypatch.setattr(
        connection,
        "MIGRATIONEN",
        [(SCHEMA_VERSION + 1, ["UPDATE messages SET content = nichtsowas(1)"])],
    )

    with pytest.raises(sqlite3.OperationalError):
        db.schema_einrichten()
    assert db.schema_version() == SCHEMA_VERSION


def test_wanderung_31_legt_den_verdichtet_in_index_an(tmp_path):
    """The delete trigger looks rows up by `verdichtet_in`; without an
    index that lookup is one full table scan per deleted row — measured at
    ~800x on a chat deletion. The index is partial: almost every row is
    NULL there, and NULL is never asked for. Fresh and migrated databases
    must both carry it."""
    db = Database(tmp_path / "alt.db")
    db.schema_einrichten()
    # And once more from one version back, so the MIGRATION is what made
    # the index, not only the fresh schema.
    db.verbindung.execute("DROP INDEX idx_messages_verdichtet_in")
    _auf_version_zuruecksetzen(db, 30)
    db.schema_einrichten()
    indizes = {
        z[0]
        for z in db.verbindung.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'"
        )
    }
    assert "idx_messages_verdichtet_in" in indizes
    plan = db.verbindung.execute(
        "EXPLAIN QUERY PLAN SELECT id FROM messages WHERE verdichtet_in = 'x'"
    ).fetchall()
    assert any("idx_messages_verdichtet_in" in z["detail"] for z in plan), [
        tuple(z) for z in plan
    ]


def test_der_schreiber_weist_kaputte_art_und_zustand_ab(tmp_path):
    """Migration 28 added `art` and `zustand` without the CHECKs a fresh
    schema carries, and SQLite cannot retrofit them — so on every upgraded
    install the database swallows any string. The repository refuses them
    instead, one rule for fresh and old databases alike."""
    from app.db import repositories_erstellen

    db = Database(tmp_path / "neu.db")
    db.schema_einrichten()
    repos = repositories_erstellen(db)
    chat = repos.chats.erstellen(user_id="u", title="t", endpoint_id="e")
    with pytest.raises(ValueError):
        repos.messages.speichern(chat_id=chat.id, role="assistant", content="x", art="quatsch")
    with pytest.raises(ValueError):
        repos.messages.speichern(
            chat_id=chat.id, role="assistant", content="x", zustand="halbgar"
        )
    repos.messages.speichern(chat_id=chat.id, role="assistant", content="x")
