"""Database connection and schema setup.

This file and the repositories are the only places in the project that know
SQL. If SQLite is later replaced by PostgreSQL, the swap happens right here.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from app.db.folding import register_fold_function

log = logging.getLogger(__name__)

# The last stamp handed out, and the lock that keeps two threads from
# handing out the same one. Both belong to jetzt_iso() below.
_letzter_stempel = ""
_stempel_sperre = threading.Lock()

SCHEMA_DATEI = Path(__file__).resolve().parent / "schema.sql"
SCHEMA_VERSION = 43

# What a locked database at startup means to a person, not to SQLite: the raw
# "database is locked" names no cause anybody could act on, while this does.
DATENBANK_GESPERRT_MELDUNG = (
    "Another Exe AI service is already using this data folder. Stop that service and try "
    "again."
)

# Schema changes for databases that already exist.
#
# schema.sql always describes the target state — for a new database it is
# enough. An existing database, however, must be brought along without losing
# chats. Each entry here runs exactly once.
#
# Rule: only append, never rewrite. A step once published stays put, even if
# it later seems superfluous — otherwise databases end up in different states
# depending on their age.
MIGRATIONEN: list[tuple[int, list[str]]] = [
    (
        2,
        [
            "ALTER TABLE chats ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0",
            # The old index does not know the new column and would no longer
            # kick in for sorting.
            "DROP INDEX IF EXISTS idx_chats_user_updated",
        ],
    ),
    (
        3,
        [
            # Further model parameters as JSON. Deliberately one column
            # instead of one per knob: which ones exist depends on the
            # backend and changes with its versions. A table change for every
            # new knob would be the wrong price.
            "ALTER TABLE chats ADD COLUMN parameter_json TEXT",
        ],
    ),
    (
        4,
        [
            # The system prompt moves from the database into a file and is
            # freshly prepended on every request. What remains on the chat is
            # only the question of whether it is suspended for this one chat.
            "ALTER TABLE chats ADD COLUMN prompt_aus INTEGER NOT NULL DEFAULT 0",
            # The old copy goes away. It was a snapshot from the time of
            # creation and never saw later changes — exactly the reason for
            # the rework.
            "ALTER TABLE chats DROP COLUMN system_prompt",
        ],
    ),
    (
        5,
        # Persist runs: the tables auftraege and
        # auftrag_schritte are pure additions and live in schema.sql, which
        # runs after the migrations anyway. The entry here only bumps the
        # version so the database knows it is aware of the addition.
        [],
    ),
    (
        6,
        [
            # Vision: a user message can carry an
            # image. Only the file name under data/images/ is stored — the
            # bytes belong in the file system, not in the database.
            "ALTER TABLE messages ADD COLUMN bild TEXT",
        ],
    ),
    (
        7,
        [
            # Document upload (4.1): a user message can carry a
            # document — only the id is stored; text and facts live in
            # documents (ready since phase 1, and it gains two columns:
            # page count and whether it was truncated).
            "ALTER TABLE messages ADD COLUMN dokument TEXT",
            "ALTER TABLE documents ADD COLUMN pages INTEGER",
            "ALTER TABLE documents ADD COLUMN truncated INTEGER NOT NULL DEFAULT 0",
        ],
    ),
    (
        8,
        [
            # The working directory (shell tool): every
            # chat may have its own folder the model is later allowed to
            # work in — like `cd` in a real terminal. It is set by the user,
            # never by the model. NULL means: none chosen, the shell tool
            # stays closed.
            "ALTER TABLE chats ADD COLUMN working_dir TEXT",
        ],
    ),
    (
        9,
        [
            # One folder becomes several: a chat may have
            # up to four folders shared with it — the first is the working
            # directory commands run in, the others are additional sources.
            # The limit lives in the handler.
            #
            # The old single column moves over as a one-element list and is
            # then dropped: two columns for the same thing would be exactly
            # the kind of leftover someone later reads the wrong one of.
            "ALTER TABLE chats ADD COLUMN working_dirs TEXT",
            "UPDATE chats SET working_dirs = json_array(working_dir) "
            "WHERE working_dir IS NOT NULL",
            "ALTER TABLE chats DROP COLUMN working_dir",
        ],
    ),
    (
        10,
        [
            # Settings become a cascade. Until now a value could only live on
            # a single chat, so every new chat started at the endpoint's
            # defaults and had to be set by hand again. The table itself is in
            # schema.sql, which runs after the migrations; what happens here
            # is the move.
            #
            # Existing chat values keep working: they become 'chat:<id>'
            # entries, the most specific scope, so nothing changes for an old
            # conversation. Afterwards the four columns go — two places for
            # one setting is exactly the leftover somebody later reads the
            # wrong one from.
            #
            # The table is created here and not left to schema.sql: that one
            # runs AFTER the migrations, and the move below needs it now.
            """
            CREATE TABLE IF NOT EXISTS einstellungen (
                bereich    TEXT NOT NULL,
                schluessel TEXT NOT NULL,
                wert_json  TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (bereich, schluessel)
            )
            """,
            """
            INSERT OR REPLACE INTO einstellungen (bereich, schluessel, wert_json, updated_at)
            SELECT 'chat:' || id, 'parameter',
                   json_patch(
                       COALESCE(parameter_json, '{}'),
                       json_object(
                           'temperature', temperature,
                           'top_p',       top_p,
                           'max_tokens',  max_tokens
                       )
                   ),
                   updated_at
              FROM chats
             WHERE parameter_json IS NOT NULL
                OR temperature IS NOT NULL
                OR top_p IS NOT NULL
                OR max_tokens IS NOT NULL
            """,
            "ALTER TABLE chats DROP COLUMN parameter_json",
            "ALTER TABLE chats DROP COLUMN temperature",
            "ALTER TABLE chats DROP COLUMN top_p",
            "ALTER TABLE chats DROP COLUMN max_tokens",
        ],
    ),
    (
        11,
        [
            # Which embedding model a vector came out of. Without it, sections
            # written by one model are compared against a question embedded by
            # another: the numbers line up, the similarities sort, and the
            # answer is built from whichever sections happened to be stored
            # first. Sections from before this step carry the empty name and
            # are therefore never compared — they are recomputed on the next
            # upload, which is cheaper than guessing which model wrote them.
            "ALTER TABLE dokument_abschnitte ADD COLUMN modell TEXT NOT NULL DEFAULT ''",
        ],
    ),
    (
        12,
        # Cronjobs: a pure addition living in schema.sql,
        # the same as auftraege/auftrag_schritte at version 5 — the entry
        # here only bumps the version.
        [],
    ),
    (
        13,
        [
            # The context-full handoff chain (app/zwischenstand.py) needs
            # somewhere to keep its counters between restarts.
            "ALTER TABLE cronjobs ADD COLUMN erledigt_anzahl INTEGER",
            "ALTER TABLE cronjobs ADD COLUMN ohne_fortschritt INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE cronjobs ADD COLUMN neustarts INTEGER NOT NULL DEFAULT 0",
        ],
    ),
    (
        14,
        [
            # The chain's actual original task, carried unchanged across
            # restarts — see schema.sql for why the wrapped text itself
            # cannot stand in for it.
            "ALTER TABLE cronjobs ADD COLUMN basisaufgabe TEXT",
        ],
    ),
    (
        15,
        [
            # A hard restart needs its way back to the same
            # chain, and a run that never crossed the context threshold or
            # a provider outage needs a status to resume from at all.
            "ALTER TABLE auftraege ADD COLUMN cronjob_id TEXT",
            "ALTER TABLE auftraege ADD COLUMN zwischenstand TEXT",
        ],
    ),
    (
        16,
        [
            # A one-off reminder deactivates itself once it has
            # actually fired, instead of coming back the next day.
            "ALTER TABLE cronjobs ADD COLUMN einmalig INTEGER NOT NULL DEFAULT 0",
        ],
    ),
    (
        17,
        [
            # A one-off reminder can now name the exact day it is
            # due, not only the time — NULL leaves every existing entry
            # (daily or one-off) firing exactly as it did before.
            "ALTER TABLE cronjobs ADD COLUMN datum TEXT",
        ],
    ),
    (
        18,
        [
            # The schema only ever allows
            # 'datum' together with 'einmalig' — a row from before 'update'
            # enforced that rule could still carry a stale date on a daily
            # entry, and 'list' would show a day that no longer applies.
            "UPDATE cronjobs SET datum = NULL WHERE einmalig = 0 AND datum IS NOT NULL",
        ],
    ),
    (
        19,
        [
            # Images per run: a run's pictures all belong to one
            # answer, so they ride together as a JSON array of filenames —
            # the same one-column-for-the-set choice as parameter_json,
            # not one column per picture. 'bild' stays exactly as it is:
            # a single vision upload or an old row is not a run and keeps
            # its own single filename, untouched by this column existing.
            "ALTER TABLE messages ADD COLUMN bilder TEXT",
        ],
    ),
    (
        20,
        [
            # User attachments as lists: several images and several documents
            # on one message. Same one-column-for-the-set choice as 'bilder'.
            # The scalar 'bild'/'dokument' columns keep the FIRST attachment
            # so an older program version still shows something.
            "ALTER TABLE messages ADD COLUMN anhaenge TEXT",
            "ALTER TABLE messages ADD COLUMN dokumente TEXT",
        ],
    ),
    (
        21,
        [
            # A cron entry that keeps failing stops trying: how
            # many runs in a row came back failed, and how many in a row it
            # takes to switch this entry off. Per entry rather than one
            # global knob — a flaky nightly backup and a minute-by-minute
            # inbox check do not deserve the same patience.
            "ALTER TABLE cronjobs ADD COLUMN fehlversuche INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE cronjobs ADD COLUMN fehlergrenze INTEGER NOT NULL DEFAULT 5",
        ],
    ),
    (
        22,
        [
            # A goal per entry: the entry announces only once the
            # goal is actually met, instead of after every single run. Free
            # text, because a goal is a sentence — and because a later
            # checking build has to be able to read the very same sentence
            # without anything being rewritten for it.
            "ALTER TABLE cronjobs ADD COLUMN ziel TEXT",
            "ALTER TABLE cronjobs ADD COLUMN ziel_stilllegen INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE cronjobs ADD COLUMN ziel_erreicht_am TEXT",
            # Runs in a row that finished without reporting the goal. Its
            # own count, next to and never mixed with the failure count:
            # staying quiet is what a goal entry is supposed to do most of
            # the time, and must never switch anything off.
            "ALTER TABLE cronjobs ADD COLUMN laeufe_ohne_ruf INTEGER NOT NULL DEFAULT 0",
        ],
    ),
    (
        23,
        [
            # The note one run leaves for the next one of the same entry.
            #Written by the model through the `cron_note` tool
            # and REPLACED on every call, never appended — a column that
            # grows by a line per run would end up in the task text of every
            # future run until it crowds out the task itself.
            "ALTER TABLE cronjobs ADD COLUMN notiz TEXT",
        ],
    ),
    (
        24,
        [
            # The band between a restart chain and the entry it continues.
            # A run that overflows writes a continuation entry that carries
            # the work on, and until now that entry knew nothing about where
            # it came from: `basisaufgabe` holds the original TEXT, and
            # `herkunft='agent'` only says that this is a chain at all.
            # Everything the chain learned or reached therefore never
            # reached the entry a person actually made.
            # Points at the REAL origin, never at an intermediate link — a
            # continuation of a continuation passes the same id on.
            "ALTER TABLE cronjobs ADD COLUMN ursprung_id TEXT",
            # When the note was WRITTEN. Until now the note was
            # handed to the next run stamped with `zuletzt_ausgeloest`, and
            # that stamp is also set for a due time that was SKIPPED because
            # a run was still going — so it can be later than the moment the
            # note describes, and everything in between silently counts as
            # already seen.
            "ALTER TABLE cronjobs ADD COLUMN notiz_am TEXT",
        ],
    ),
    (
        25,
        [
            # A cron entry that starts a SCRIPT instead of a model run.
            #The file name, never a path: it is resolved against
            # the scripts location at every firing and has to land inside it.
            # NULL is every entry there has ever been — an agent and a task.
            "ALTER TABLE cronjobs ADD COLUMN skript TEXT",
            # How many seconds that script may run, NULL for the shipped
            # default (app/tools/shell.py). Its own column rather than the
            # command tool's setting cascade: a nightly backup and a shell
            # command a person is watching have nothing to do with one
            # another, and the whole point of the field is that a long
            # backup must not die on a limit meant for the chat.
            "ALTER TABLE cronjobs ADD COLUMN zeitgrenze INTEGER",
        ],
    ),
    (
        26,
        [
            # The run that started this one. A job an agent asked for is a
            # PART of the assignment its parent was given, not a new one —
            # that is what lets `start_job` work inside a job. It carries the
            # chain
            # as well: who started whom, and whom a cancelled run takes with
            # it. NULL for every run a person or a schedule started.
            "ALTER TABLE auftraege ADD COLUMN eltern_id TEXT",
        ],
    ),
    (
        27,
        [
            # The open question of a run that called `ask_user`, as JSON:
            # the call's id, the question, its options. On the run rather
            # than only in its transcript, because three displays need it
            # without reading a log — the waiting group, the banner, and the
            # buttons themselves. NULL whenever nothing is being asked,
            # which is nearly always.
            "ALTER TABLE auftraege ADD COLUMN frage TEXT",
        ],
    ),
    (
        28,
        [
            # What a message IS, beyond who said it. Until now `role` was
            # the only answer, so everything that is not a person and not a
            # model had to disguise itself as an assistant turn: a finished
            # background run, a picture from the picture window, a run's
            # picture row. Three writers, one lie, and every reader that
            # asked "is this the running answer?" got it wrong — the reply
            # was adopted, blanked and rewritten, which is how one answer
            # ended up in the chat two dozen times.
            "ALTER TABLE messages ADD COLUMN art TEXT NOT NULL DEFAULT 'nachricht'",
            # Where a run stands. This lived inside `stats_json` as the
            # ABSENCE of a key (`stats.abgebrochen === undefined` meant
            # "still running"), which made a display blob carry state and
            # made every row written by somebody else look live.
            "ALTER TABLE messages ADD COLUMN zustand TEXT",
            # The run this row belongs to. Already existed as
            # `stats_json -> '$.lauf'` and was even queried with
            # `json_extract`, so it was a foreign key in all but name.
            "ALTER TABLE messages ADD COLUMN lauf_id TEXT",
            # How full the context was after this message. In `stats_json`
            # it could only be written once, at the end of a run; a column
            # can be updated while the run goes, which is what the context
            # bar needs to move at all.
            "ALTER TABLE messages ADD COLUMN gesamt_tokens INTEGER",
            # Set to the id of the summary that folded this message away.
            # NULL means the message still goes to the model verbatim.
            # Compaction needs somewhere to write its result back to;
            # a job could keep it in memory because its list lives for the
            # whole task, a chat rebuilds the list from here every time.
            "ALTER TABLE messages ADD COLUMN verdichtet_in TEXT",
            # Backfill, in the order the old data can actually answer.
            #
            # A run's picture row is the one identified by `bilder`, the
            # same test `lauf_bild_speichern` uses; a single `bild` is a
            # vision attachment on an ordinary message and must NOT count.
            "UPDATE messages SET art = 'bildlauf' WHERE bilder IS NOT NULL",
            # The picture window's own row — the third writer the comment
            # above names, and the one nobody backfilled. It carries a lone
            # `bild` and no `bilder`, so the step before this one walks past
            # it, and left alone it stays an ordinary turn: the regenerate
            # arrow settles on it, and that arrow DELETES what it regenerates
            # before asking the LANGUAGE model for a replacement. The picture
            # would be thrown away to make room for a text answer, which is
            # the exact state `art` was added to end.
            #
            # `content = ''` on an ASSISTANT row with a lone `bild` is what
            # the picture window wrote — and also what a chat answer looks
            # like whose model drew one picture through a tool and said
            # nothing beside it. The two are told apart by the tool log:
            # the window's row carries a seed and no `werkzeuge`, the chat's
            # answer carries the call that drew the picture. A row with a
            # tool log is a turn and keeps its kind, its arrow and its state.
            # A lone `bild` on a user row is a vision attachment and stays a
            # message.
            #
            # The exclusion is spelled as an OR chain with the cheap tests
            # first, for the same reason the guards further down put
            # `json_valid` before every reader: `json_type` raises on a blob
            # that is not JSON, and the chain has to be settled before it is
            # ever asked. A NULL blob settles it on the first term.
            #
            # It has to stand HERE, above the `zustand` backfill: that one is
            # restricted to `art = 'nachricht'`, and a picture has no run of
            # its own. Written the other way round it would come out of the
            # migration wearing the state of a run that never existed.
            "UPDATE messages SET art = 'bild' "
            "WHERE role = 'assistant' AND content = '' "
            "AND bild IS NOT NULL AND bilder IS NULL "
            "AND (stats_json IS NULL OR NOT json_valid(stats_json) "
            "OR json_type(stats_json, '$.werkzeuge') IS NOT 'array')",
            # A finished background run left two marks: the header it wrote
            # into the text, and a tool log holding exactly one entry, for
            # `run_command`, with `background` true. Both are required.
            #
            # The header alone would be enough to misfile a real answer that
            # merely QUOTES a report it was just shown, and a misfiled
            # answer loses its regenerate arrow and has its text hidden
            # under the tool card. The tool log alone would catch any answer
            # whose last tool call happened to be a background command. Only
            # rows `hintergrundmeldung.py` actually wrote carry both; new
            # rows carry `art` from the start and need no guessing.
            #
            # Every step from here on reads `stats_json`, a blob nobody ever
            # validated on the way in, and SQLite's JSON functions do not
            # return NULL on rubbish — they RAISE. A single unreadable blob
            # would therefore stop the migration in the middle of its own
            # list, leaving the columns added and the version unraised, and
            # every following start would die at the same row. Two different
            # kinds of rubbish get in, and each needs its own answer:
            #
            #   `json_valid(stats_json)` covers a blob that is not JSON at
            #   all. It has to stand BEFORE the first reader in the same
            #   AND chain — SQLite evaluates the terms left to right and
            #   stops at the first false one, so the guard is what keeps
            #   the reader from ever seeing the row. It changes nothing for
            #   readable rows: `json_valid` is 1 for them. For NULL it is
            #   NULL, which is false here — and a NULL blob was already
            #   excluded, because every reader below returns NULL for it.
            #
            #   `json_array_length(stats_json, '$.werkzeuge')` replaces the
            #   nested `json_array_length(json_extract(...))`. The nesting
            #   was the actual trap: `json_extract` UNWRAPS a JSON string
            #   into plain SQL text, and `json_array_length` then parses
            #   that text as JSON a second time — so a perfectly readable
            #   blob carrying `"werkzeuge": "run_command"` raised. The
            #   two-argument form walks the path itself and answers 0 for
            #   everything that is not an array, which is what the `= 1`
            #   below was asking all along.
            "UPDATE messages SET art = 'werkzeugmeldung' "
            "WHERE role = 'assistant' AND content LIKE '[background run #%' "
            "AND json_valid(stats_json) "
            "AND json_array_length(stats_json, '$.werkzeuge') = 1 "
            "AND json_extract(stats_json, '$.werkzeuge[0].name') = 'run_command' "
            "AND json_extract(stats_json, '$.werkzeuge[0].argumente.background') = 1",
            "UPDATE messages SET lauf_id = json_extract(stats_json, '$.lauf') "
            "WHERE stats_json IS NOT NULL AND json_valid(stats_json) "
            "AND json_extract(stats_json, '$.lauf') IS NOT NULL",
            "UPDATE messages SET gesamt_tokens = json_extract(stats_json, '$.gesamt_tokens') "
            "WHERE stats_json IS NOT NULL AND json_valid(stats_json) "
            "AND json_extract(stats_json, '$.gesamt_tokens') IS NOT NULL",
            # Nothing is running while this migration runs — the service
            # applies it at startup, before a single generation is
            # registered. Every stored answer is therefore over, and the
            # only question left is HOW it ended.
            #
            # Restricted to `art = 'nachricht'`, which the two statements
            # above have already assigned: a tool report and a picture row
            # have no run of their own, and giving them a state would put
            # back exactly the kind of untrue field this whole change is
            # here to remove.
            "UPDATE messages SET zustand = 'abgebrochen' "
            "WHERE role = 'assistant' AND art = 'nachricht' "
            "AND json_valid(stats_json) "
            "AND json_extract(stats_json, '$.abgebrochen') = 1",
            "UPDATE messages SET zustand = 'fehler' "
            "WHERE role = 'assistant' AND art = 'nachricht' AND zustand IS NULL "
            "AND json_valid(stats_json) "
            "AND json_extract(stats_json, '$.fehler') IS NOT NULL",
            # No guard here and none needed: the step reads no blob. It is
            # also what an unreadable row now lands on — the two steps above
            # walk past it, this one calls the run over, which is true of
            # every stored answer whatever its stats say.
            "UPDATE messages SET zustand = 'fertig' "
            "WHERE role = 'assistant' AND art = 'nachricht' AND zustand IS NULL",
            # The lookup that used to go through `json_extract` on every
            # row of a chat.
            "CREATE INDEX IF NOT EXISTS idx_messages_lauf ON messages (chat_id, lauf_id)",
        ],
    ),
    (
        29,
        [
            # Migration 28, as first shipped, filed every empty assistant row
            # with a lone `bild` as the picture window's — and a chat answer
            # whose model drew one picture through a tool and wrote no text
            # has exactly that shape. Those answers came out as `art = 'bild'`
            # with no state, lost their regenerate arrow, and the arrow
            # settled on the answer before them instead. A database that has
            # already crossed 28 carries the misfiling; the corrected step
            # above only helps a database that has not.
            #
            # The tool log is what tells the two apart, the same way the
            # corrected step reads it: the window's row has no `werkzeuge`.
            "UPDATE messages SET art = 'nachricht' "
            "WHERE role = 'assistant' AND art = 'bild' "
            "AND json_valid(stats_json) "
            "AND json_type(stats_json, '$.werkzeuge') = 'array'",
            # The state such a row was denied, by the same three rules as
            # in 28. Every stored answer is over when a migration runs, so
            # the only question is how it ended; `zustand IS NULL` keeps
            # every row that already has an answer as it is.
            "UPDATE messages SET zustand = 'abgebrochen' "
            "WHERE role = 'assistant' AND art = 'nachricht' AND zustand IS NULL "
            "AND json_valid(stats_json) "
            "AND json_extract(stats_json, '$.abgebrochen') = 1",
            "UPDATE messages SET zustand = 'fehler' "
            "WHERE role = 'assistant' AND art = 'nachricht' AND zustand IS NULL "
            "AND json_valid(stats_json) "
            "AND json_extract(stats_json, '$.fehler') IS NOT NULL",
            "UPDATE messages SET zustand = 'fertig' "
            "WHERE role = 'assistant' AND art = 'nachricht' AND zustand IS NULL",
        ],
    ),
    (
        30,
        [
            # The release of `verdichtet_in` moves from two repository
            # methods into the database: a deleted row lets go of every row
            # that pointed at it, whichever path did the deleting. The same
            # trigger schema.sql creates for a fresh database.
            "CREATE TRIGGER IF NOT EXISTS messages_verdichtung_freigeben "
            "AFTER DELETE ON messages "
            "BEGIN "
            "UPDATE messages SET verdichtet_in = NULL WHERE verdichtet_in = OLD.id; "
            "END",
        ],
    ),
    (
        31,
        [
            # The trigger above runs its UPDATE once per deleted row, and
            # `verdichtet_in` had no index: deleting a chat (cascade) was
            # one full table scan per message — measured at 40k rows,
            # deleting a 2,000-message chat went from 0.002 s to 1.6 s,
            # holding the write lock throughout. Partial, because almost
            # every row carries NULL there and NULL is never looked up.
            "CREATE INDEX IF NOT EXISTS idx_messages_verdichtet_in "
            "ON messages(verdichtet_in) WHERE verdichtet_in IS NOT NULL",
        ],
    ),
    (
        32,
        [
            # A document too big for the model's window travels as a
            # condensed version the model made once per size step
            # (app/dokumentzusammenfassung.py). Kept with the document
            # together with the size it was made for, NULL until one was
            # needed.
            "ALTER TABLE documents ADD COLUMN zusammenfassung TEXT",
            "ALTER TABLE documents ADD COLUMN zusammenfassung_ziel INTEGER",
        ],
    ),
    (
        33,
        [
            # A document too big for the model's window now travels as
            # nothing rather than a condensed version — the section search
            # and the model-made summary are both gone. The columns and the
            # table behind them go with them; the model server that made
            # the vectors is a separate step (Commit 2).
            "ALTER TABLE documents DROP COLUMN zusammenfassung",
            "ALTER TABLE documents DROP COLUMN zusammenfassung_ziel",
            "DROP INDEX IF EXISTS idx_abschnitte_dokument",
            "DROP TABLE IF EXISTS dokument_abschnitte",
        ],
    ),
    (
        34,
        [
            # Where an uploaded document's file lies on disk
            # (app/dokumentablage.py). Documents from before this step have
            # none: their bytes were dropped after the text was pulled out,
            # and nothing can bring them back — the column stays NULL for
            # them, and a request says the document is too large without
            # being able to name a place to read it from.
            "ALTER TABLE documents ADD COLUMN pfad TEXT",
        ],
    ),
    (
        35,
        [
            # Full-text search over what was said in a chat, not only over
            # its title (see schema.sql for the shape and the three
            # triggers). Repeated here because schema.sql only ever runs
            # AFTER the migrations: without this step an existing database
            # would get the table and its triggers a moment later, but
            # nothing would ever have put its old messages into it.
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5 (
                content,
                content='messages',
                content_rowid='rowid',
                tokenize='unicode61 remove_diacritics 2'
            )
            """,
            """
            CREATE TRIGGER IF NOT EXISTS messages_fts_eingefuegt
                AFTER INSERT ON messages
            BEGIN
                INSERT INTO messages_fts (rowid, content) VALUES (NEW.rowid, NEW.content);
            END
            """,
            """
            CREATE TRIGGER IF NOT EXISTS messages_fts_geloescht
                AFTER DELETE ON messages
            BEGIN
                INSERT INTO messages_fts (messages_fts, rowid, content)
                    VALUES ('delete', OLD.rowid, OLD.content);
            END
            """,
            """
            CREATE TRIGGER IF NOT EXISTS messages_fts_geaendert
                AFTER UPDATE OF content ON messages
            BEGIN
                INSERT INTO messages_fts (messages_fts, rowid, content)
                    VALUES ('delete', OLD.rowid, OLD.content);
                INSERT INTO messages_fts (rowid, content) VALUES (NEW.rowid, NEW.content);
            END
            """,
            # Every message that already exists, read out of the table the
            # index points at. FTS5's own command for exactly this, and the
            # reason the search is not "from now on": a conversation from
            # three weeks ago is the one somebody is looking for.
            "INSERT INTO messages_fts (messages_fts) VALUES ('rebuild')",
        ],
    ),
    (
        36,
        [
            # Who put a row on 'laeuft' — the port of the service that did
            # it. Two services may share a data folder (the test service
            # beside the ordinary one is a wanted case), and until now the
            # startup cleanup could not tell whose stranded rows it was
            # looking at: it asked what state a row is in, never which
            # process put it there. So it stayed out entirely as soon as a
            # second service was there, and rows the other one left on
            # 'laeuft' stayed that way for good. With the owner written down
            # the cleanup runs either way and touches only its own.
            #
            # Two plain columns, no table rebuild: both tables are ordinary
            # CREATE TABLEs, and the whole mechanism here is made of steps
            # like these.
            "ALTER TABLE auftraege ADD COLUMN dienst_port INTEGER",
            "ALTER TABLE messages ADD COLUMN dienst_port INTEGER",
        ],
    ),
    (
        37,
        [
            # The open ask_user question of a chat — same shape and the
            # same reasoning as `auftraege.frage`: without it
            # the question lived only in the run's own in-memory Future, and
            # a window that left the chat or reloaded had nothing left to
            # show it from.
            "ALTER TABLE chats ADD COLUMN frage TEXT",
        ],
    ),
    (
        38,
        [
            # Projects and the archive. Every chat that exists stays where
            # it was: in no project, not archived — the two defaults. The
            # projects table itself comes from schema.sql, which runs after
            # this list.
            "ALTER TABLE chats ADD COLUMN project_id TEXT REFERENCES projects(id)",
            "ALTER TABLE chats ADD COLUMN archived INTEGER NOT NULL DEFAULT 0",
        ],
    ),
    (
        39,
        [
            # The chat a job was started from. Every job that exists stays
            # without one: none of them can say any more where it came from.
            "ALTER TABLE auftraege ADD COLUMN chat_id TEXT",
        ],
    ),
    (
        40,
        [
            # Who put a chat's file there: a job started from a chat
            # delivers into that chat's own folder, and the doc folder names
            # the agent and tells a cron job's delivery from a hand-started
            # one through the job. Every document that exists stays without
            # both: the person uploaded it.
            "ALTER TABLE documents ADD COLUMN agent TEXT",
            "ALTER TABLE documents ADD COLUMN job TEXT",
        ],
    ),
    (
        41,
        [
            # The permission mode exists once, in the global scope: it
            # rewrites the one rule file every chat and every model is
            # judged by. An earlier version stored it at a chat or a model
            # as well; such a row is read by nothing, and the settings route
            # refuses every write of these two keys outside the global
            # scope, the write that would take it back included. So the rows
            # go here. The global value and every other setting stay.
            """
            DELETE FROM einstellungen
            WHERE schluessel IN ('berechtigungsmodus_chat', 'berechtigungsmodus_agent')
              AND bereich != 'global'
            """,
        ],
    ),
    (
        42,
        [
            # The answer a "regenerate" attempt is to replace, written on the
            # attempt's row for as long as it runs. A stop by hand deletes
            # the attempt and the old answer stands; a service that ended
            # hard left the attempt on 'laeuft', and the startup cleanup
            # could only mark it stopped — two answers to one question. With
            # the old answer named, the cleanup does what the stop does.
            # Every row that exists names none.
            "ALTER TABLE messages ADD COLUMN replaces_id TEXT",
        ],
    ),
    (
        43,
        [
            # The memory travels to cloud models and custom servers from the
            # start now. A stored "cloud": false was written by an earlier
            # default as much as by a hand — the window wrote both keys on
            # every switch — so the two cannot be told apart, and every such
            # value, in every scope, is set to true once. "lokal" stays.
            # After this step what the user switches is what stands.
            """
            UPDATE einstellungen
            SET wert_json = json_set(wert_json, '$.cloud', json('true'))
            WHERE schluessel = 'gedaechtnis'
              AND json_valid(wert_json)
              AND json_extract(wert_json, '$.cloud') = 0
            """,
        ],
    ),
]


def jetzt_iso() -> str:
    """Current moment as ISO 8601 in UTC — uniform across the whole project.

    Microseconds are necessary: at coarser resolution, two chats changed in
    quick succession get the same timestamp and the sorting in the sidebar
    becomes random. The notation stays sortable because ISO 8601 with a
    fixed number of digits also compares correctly as text.

    Asking the clock is not enough by itself. Windows advances its clock
    only about every sixteen milliseconds, so everything written inside one
    tick would carry identical microseconds and sort by chance after all —
    which is exactly what the sidebar must not do. Whenever the clock has
    not moved on, the stamp is carried forward by a microsecond instead:
    the order then follows the order things were written in, and it never
    runs ahead of the real time by more than the tick it is bridging.
    """
    global _letzter_stempel

    with _stempel_sperre:
        stempel = datetime.now(timezone.utc).isoformat(timespec="microseconds")
        if stempel <= _letzter_stempel:
            stempel = (
                datetime.fromisoformat(_letzter_stempel) + timedelta(microseconds=1)
            ).isoformat(timespec="microseconds")
        _letzter_stempel = stempel
        return stempel


class Database:
    """Thin shell around SQLite: connection, transactions, schema setup."""

    def __init__(self, pfad: str | Path, dienst_port: int | None = None) -> None:
        self.pfad = Path(pfad)
        # The port this service listens on, or None where nobody said (tests,
        # one-off scripts). It is the OWNER stamped on every row this service
        # puts on 'laeuft', and the startup cleanup asks for it — see the
        # `dienst_port` columns in schema.sql. It sits here rather than in
        # every repository's signature because it is one fact about the
        # process, the same for all of them.
        self.dienst_port = dienst_port
        self._lokal = threading.local()
        if str(self.pfad) != ":memory:":
            self.pfad.parent.mkdir(parents=True, exist_ok=True)
        # For ":memory:" the same connection must persist, otherwise the
        # database is empty again after every close.
        self._geteilte_speicher_verbindung: sqlite3.Connection | None = None

    # --- Connection ------------------------------------------------------

    def _neue_verbindung(self) -> sqlite3.Connection:
        verbindung = sqlite3.connect(
            self.pfad, check_same_thread=False, isolation_level=None
        )
        verbindung.row_factory = sqlite3.Row
        register_fold_function(verbindung)
        verbindung.execute("PRAGMA foreign_keys = ON")
        if str(self.pfad) != ":memory:":
            verbindung.execute("PRAGMA journal_mode = WAL")
        verbindung.execute("PRAGMA busy_timeout = 5000")
        return verbindung

    @property
    def verbindung(self) -> sqlite3.Connection:
        if str(self.pfad) == ":memory:":
            if self._geteilte_speicher_verbindung is None:
                self._geteilte_speicher_verbindung = self._neue_verbindung()
            return self._geteilte_speicher_verbindung

        vorhandene = getattr(self._lokal, "verbindung", None)
        if vorhandene is None:
            vorhandene = self._neue_verbindung()
            self._lokal.verbindung = vorhandene
        return vorhandene

    @contextmanager
    def transaktion(self) -> Iterator[sqlite3.Connection]:
        """All or nothing — on an exception we roll back."""
        verbindung = self.verbindung
        verbindung.execute("BEGIN")
        try:
            yield verbindung
        except Exception:
            verbindung.execute("ROLLBACK")
            raise
        else:
            verbindung.execute("COMMIT")

    def schliessen(self) -> None:
        if self._geteilte_speicher_verbindung is not None:
            self._geteilte_speicher_verbindung.close()
            self._geteilte_speicher_verbindung = None
        vorhandene = getattr(self._lokal, "verbindung", None)
        if vorhandene is not None:
            vorhandene.close()
            self._lokal.verbindung = None

    # --- Schema ----------------------------------------------------------

    def schema_einrichten(self) -> None:
        """Creates tables if they are missing and brings the schema up to date.

        Order matters: on an existing database the migrations run first, then
        schema.sql. The other way around, schema.sql would stumble over
        columns that do not exist yet.

        Every step of it writes, so a second service holding the write lock
        can meet any of them — one catch around all of them names it.
        """
        with self._sperre_benannt():
            self._schema_schreiben()

    def _schema_schreiben(self) -> None:
        verbindung = self.verbindung
        neu = (
            verbindung.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='chats'"
            ).fetchone()
            is None
        )

        if neu:
            # Fresh database: schema.sql already describes the target state,
            # the migrations are already contained in it.
            verbindung.executescript(SCHEMA_DATEI.read_text(encoding="utf-8"))
            verbindung.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                (SCHEMA_VERSION, jetzt_iso()),
            )
            log.info("Schema created (version %s) in %s", SCHEMA_VERSION, self.pfad)
            return

        self._migrationen_anwenden()
        # Asked BEFORE schema.sql runs: a messages_fts that is gone while
        # messages still holds rows has lost its contents. schema.sql below
        # would only create it again — empty — and from then on a search
        # would answer "nothing found" without an error, for everything
        # written before today. The one migration that ever filled it (35)
        # does not run a second time, so the backfill has to happen here.
        index_verloren = (
            verbindung.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='messages_fts'"
            ).fetchone()
            is None
        )
        if index_verloren:
            self._volltextindex_nachziehen()
        # Afterwards schema.sql creates everything that has been added since —
        # new tables as well as renewed indexes.
        verbindung.executescript(SCHEMA_DATEI.read_text(encoding="utf-8"))

    @contextmanager
    def _sperre_benannt(self) -> Iterator[None]:
        """Turns a write lock held by a second service into the sentence a
        person can act on; every other error goes up unchanged.

        A second service on the same data folder can hold the write lock
        right through busy_timeout — the raw "database is locked" names no
        cause a person could act on. The exact SQLITE_BUSY wording, not a
        bare "locked": "database table X is locked" and "database schema is
        locked" are SQLITE_LOCKED, a same-connection conflict with an
        unrelated cause, and must not be told apart from a second service.
        One place for the whole start (``schema_einrichten``), so the
        sentence and the way to it exist once.
        """
        try:
            yield
        except sqlite3.OperationalError as fehler:
            if "database is locked" not in str(fehler):
                raise
            log.error(DATENBANK_GESPERRT_MELDUNG)
            raise sqlite3.OperationalError(DATENBANK_GESPERRT_MELDUNG) from fehler

    def _volltextindex_nachziehen(self) -> None:
        """Builds a missing full-text index and fills it in one go.

        Reached only when messages_fts was not there and messages already
        held rows (see schema_einrichten). Both halves must happen together:
        an empty index cannot be told apart from a filled one — an
        external-content index answers every count out of its content table,
        so the two always agree. A run that died between laying the table
        down and filling it would leave exactly that state, permanently
        unrepairable, because the next start finds a table and asks no
        further. Hence the transaction: it either stands complete or leaves
        the table absent, and the next start tries again.

        The table is created here rather than left to schema.sql, which runs
        a moment later and finds it already in place. Its shape is the one
        schema.sql spells out, repeated for the same reason migration 35
        repeats it: it has to exist before that script has its turn.

        The command is FTS5's own and the same one migration 35 sends: it
        reads the contents out of ``messages``, the table the index points
        at. Deliberately no comparison of counts anywhere — such a check
        would compare the index against itself and prove nothing.
        """
        verbindung = self.verbindung
        anzahl = verbindung.execute("SELECT count(*) FROM messages").fetchone()[0]
        if not anzahl:
            return
        with self.transaktion():
            verbindung.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5 (
                    content,
                    content='messages',
                    content_rowid='rowid',
                    tokenize='unicode61 remove_diacritics 2'
                )
                """
            )
            verbindung.execute("INSERT INTO messages_fts (messages_fts) VALUES ('rebuild')")
        log.info(
            "Full-text index over %d messages rebuilt in %s", anzahl, self.pfad
        )

    def _migrationen_anwenden(self) -> None:
        verbindung = self.verbindung
        zeile = verbindung.execute(
            "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
        ).fetchone()
        stand = zeile["version"] if zeile else 0

        for version, anweisungen in MIGRATIONEN:
            if version <= stand:
                continue
            # One step, one transaction — its statements and the version row
            # that says they ran either land together or not at all.
            #
            # Without this the connection is in autocommit (see
            # `_neue_verbindung`), so a step that dies halfway leaves its
            # first statements standing while the version stays where it
            # was: a database whose shape belongs to no version anybody
            # wrote down. That is worse than the failure that caused it,
            # because the next start reads the OLD version and runs the
            # whole list again over half-changed data — and a reader in
            # between sees columns that exist but were never filled in.
            #
            # Every statement in this list is an ALTER, CREATE, DROP,
            # INSERT, UPDATE or DELETE, and SQLite rolls all of those back,
            # schema changes included. A failing statement does not by
            # itself end the transaction either, which is what lets the
            # "nothing to do" cases below carry on inside it.
            with self.transaktion():
                for anweisung in anweisungen:
                    try:
                        verbindung.execute(anweisung)
                    except sqlite3.OperationalError as fehler:
                        # A step that has nothing left to do is not a failure.
                        # Three ways that shows: the column an ADD wants is
                        # already there, the column a DROP wants is already gone,
                        # or the whole table is still missing.
                        #
                        # The last one is the case of a database older than the
                        # table itself. Migrations run before schema.sql, so a
                        # column added to a young table is asked for while the
                        # table does not exist yet — and schema.sql, a moment
                        # later, creates it with the column already in place.
                        # Everything else is a real error and goes up.
                        #
                        # The list stays exactly this short on purpose. Each
                        # of the three PROVES the step had nothing left to do;
                        # anything else proves the opposite — that a row was
                        # not migrated. Swallowing that would stamp the new
                        # version on a database whose new columns were never
                        # filled in, and every reader afterwards would believe
                        # them. A migration that stops loudly can be repaired;
                        # one that is skipped in silence cannot even be found.
                        text = str(fehler).lower()
                        if not any(
                            satz in text
                            for satz in ("duplicate column", "no such column", "no such table")
                        ):
                            raise
                        log.info("Migration %s had nothing to do", version)
                verbindung.execute(
                    "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                    (version, jetzt_iso()),
                )
            log.info("Schema raised to version %s", version)

        if stand > SCHEMA_VERSION:
            log.warning(
                "The database has schema version %s, this build only knows %s — "
                "is an older version of the program running here?",
                stand,
                SCHEMA_VERSION,
            )

    def schema_version(self) -> int | None:
        zeile = self.verbindung.execute(
            "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
        ).fetchone()
        return zeile["version"] if zeile else None
