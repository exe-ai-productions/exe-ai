-- Exe AI Terminal — database schema (SQLite)
--
-- Timestamps are stored as ISO 8601 in UTC (text), so they are sortable
-- and independent of the server's time zone.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_version (
    version    INTEGER NOT NULL,
    applied_at TEXT    NOT NULL
);

-- Chats -------------------------------------------------------------------
-- user_id is there from day one, so that a later login becomes an upgrade
-- and not a rebuild. Until then it holds a fixed value.
-- The title may contain anything the user types, including emoji.
-- SQLite stores text as UTF-8; composite characters like 👨‍👩‍👧‍👦 survive
-- saving, reading, and searching unchanged.
--
-- prompt_aus: Suspends the system prompt for exactly this chat. The prompt itself
-- lives in a file and otherwise always applies; only the "no" is here.
-- working_dirs: This chat's working folders as a JSON list: folders somewhere on the
-- machine the model is allowed to work in — like `cd` in a real terminal.
-- The first is the working directory commands run in, the others are
-- additional sources. Set by the user, never by the model. NULL means:
-- none chosen. While the chat lies in a project the project's folders
-- apply instead, and this stays empty.
-- frage: The open ask_user question this chat is standing on, as JSON: the
-- call's id, the question itself and its options — the same shape and
-- the same reasoning as `auftraege.frage`. Written the moment ask_user
-- is called, cleared the moment an answer arrives or the wait times
-- out, so a window that left or reloaded finds the question standing
-- again instead of losing it for good.
-- project_id: The project the chat lies in, or NULL. No cascade: a project goes
-- only with its chats deleted one by one first, the way a chat is
-- always deleted (its settings, files and runs go with it).
-- archived: Put away into the archive: out of the list, not deleted.
CREATE TABLE IF NOT EXISTS chats (
    id            TEXT PRIMARY KEY,
    user_id       TEXT NOT NULL,
    title         TEXT NOT NULL,
    endpoint_id   TEXT,
    pinned        INTEGER NOT NULL DEFAULT 0,
    prompt_aus    INTEGER NOT NULL DEFAULT 0,
    working_dirs  TEXT,
    frage         TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    project_id    TEXT REFERENCES projects(id),
    archived      INTEGER NOT NULL DEFAULT 0
);

-- Pinned first, then the most recently used.
CREATE INDEX IF NOT EXISTS idx_chats_user_updated
    ON chats (user_id, pinned DESC, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_chats_project ON chats (project_id);

-- Projects ----------------------------------------------------------------
-- A name and the folders every chat in it shares. Archived together with
-- its chats; deleted only from the archive.
--
-- working_dirs: The shared folders as a JSON list, the same shape as a chat's own.
CREATE TABLE IF NOT EXISTS projects (
    id            TEXT PRIMARY KEY,
    user_id       TEXT NOT NULL,
    name          TEXT NOT NULL,
    working_dirs  TEXT,
    archived      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

-- Settings ------------------------------------------------------------------
-- One table for every setting, instead of one column per knob. The scope says
-- how far a value reaches; the resolution goes from general to specific and
-- the last value that is actually set wins:
--
--     default (config.yaml)  →  global  →  modell:<id>  →  chat:<id>
--
-- `bereich` is 'global', 'modell:<endpoint_id>' or 'chat:<chat_id>'.
-- `schluessel` names the setting ('parameter', 'denken', 'werkzeuge_aus' …),
-- `wert_json` holds its value. Checking belongs in the code — a JSON column
-- cannot do it (for parameters: app/parameter.py).
--
-- Why one table and not one per kind: a new setting is a new row here, not a
-- schema change. And everything lives on the server, so the values are the
-- same on every device — settings kept in browser storage were a different
-- truth on each machine.
CREATE TABLE IF NOT EXISTS einstellungen (
    bereich    TEXT NOT NULL,
    schluessel TEXT NOT NULL,
    wert_json  TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (bereich, schluessel)
);

-- Chat scopes disappear with their chat.
CREATE INDEX IF NOT EXISTS idx_einstellungen_bereich
    ON einstellungen (bereich);

-- Messages ----------------------------------------------------------------
-- reasoning is kept separate from the content, because in the UI the chain
-- of thought is its own collapsible element and must not be copied along.
-- stats_json holds metrics (tokens/second, duration, token count).
--
-- bild: Filename of an attached image under data/images/ (vision).
-- bilder: Images per run: a JSON array of filenames under data/images/, one
-- answer for the whole run instead of one row per picture.
-- dokument: id of an attached document (4.1) — text and facts in documents.
-- anhaenge: User attachments as lists: several images and several documents on one
-- message. JSON arrays (file names / document ids). The scalar columns
-- above keep carrying the FIRST attachment so an older program version
-- reading this database still shows something.
-- art: What this row IS, beyond who said it. `role` alone could not tell a
-- model's answer from a finished background run or a picture, so those
-- had to pose as assistant turns — and every reader asking "is this the
-- running answer?" believed them.
--   nachricht        an ordinary turn by a person or the model
--   werkzeugmeldung  a tool result that arrived after its run had ended
--   bild             a single picture that is not an answer
--   bildlauf         the picture row of one run
--   verdichtung      a summary standing in for the rows it folded away
-- zustand: Where the run behind this row stands. NULL on everything that has no
-- run of its own — every user message, every tool report.
-- lauf_id: The run this row belongs to, so the live answer is named rather than
-- guessed from its position in the list.
-- gesamt_tokens: How full the context was after this message. Updated WHILE the run
-- goes; the old home inside stats_json could only be written at the end.
-- verdichtet_in: Id of the summary that folded this message away. NULL means it still
-- goes to the model verbatim. Nothing is deleted by compaction — the
-- reader keeps every line, the model gets the summary instead.
-- dienst_port: Which service put this row on 'laeuft': its own port. Same purpose as
-- the column of the same name on `auftraege` — a chat answer has no job
-- row, its running state lives here, and the startup cleanup has to be
-- able to tell its own stranded answer from a second service's live one
-- (app/main.py `_startbereinigung`). NULL for rows written before this
-- column existed and for every row that was never 'laeuft'.
CREATE TABLE IF NOT EXISTS messages (
    id         TEXT NOT NULL PRIMARY KEY,
    chat_id    TEXT NOT NULL REFERENCES chats (id) ON DELETE CASCADE,
    role       TEXT NOT NULL CHECK (role IN ('system', 'user', 'assistant', 'tool')),
    content    TEXT NOT NULL,
    reasoning  TEXT,
    stats_json TEXT,
    bild       TEXT,
    bilder     TEXT,
    dokument   TEXT,
    anhaenge   TEXT,
    dokumente  TEXT,
    art        TEXT NOT NULL DEFAULT 'nachricht'
               CHECK (art IN ('nachricht', 'werkzeugmeldung', 'bild', 'bildlauf',
                              'verdichtung')),
    zustand    TEXT CHECK (zustand IS NULL
               OR zustand IN ('laeuft', 'fertig', 'abgebrochen', 'fehler')),
    lauf_id    TEXT,
    gesamt_tokens INTEGER,
    verdichtet_in TEXT,
    dienst_port INTEGER,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_chat_created
    ON messages (chat_id, created_at);

CREATE INDEX IF NOT EXISTS idx_messages_lauf
    ON messages (chat_id, lauf_id);

-- The delete trigger below looks rows up by `verdichtet_in`; without this
-- index that lookup is a full table scan per deleted row. Partial: almost
-- every row is NULL there, and NULL is never asked for.
CREATE INDEX IF NOT EXISTS idx_messages_verdichtet_in
    ON messages(verdichtet_in) WHERE verdichtet_in IS NOT NULL;

-- A summary speaks FOR the rows it folded: they stay in the chat and stop
-- being sent, because it is sent instead. Delete the summary and those
-- rows would be represented by nothing — still readable, gone from what
-- the model sees, with no way back. So whatever pointed at a deleted row
-- is released by the database itself, whichever path did the deleting: a
-- regenerate, a retention sweep, a repair script, a test fixture. Two
-- repository methods used to do this by hand, and the next deletion path
-- would have had to remember.
CREATE TRIGGER IF NOT EXISTS messages_verdichtung_freigeben
    AFTER DELETE ON messages
BEGIN
    UPDATE messages SET verdichtet_in = NULL WHERE verdichtet_in = OLD.id;
END;

-- What was SAID in a chat, searchable. The chat list used to filter on the
-- title alone, so a conversation was findable only by the words its title
-- happened to carry -- and the title is written once, by a model, from the
-- first question.
--
-- An external-content table: the text is not stored a second time, the
-- index points into `messages` by rowid. That is the whole reason this can
-- cover every message there has ever been without doubling the database.
--
-- What that costs: the link IS the rowid, and `messages` has a TEXT primary
-- key, so its rowids are the implicit ones — which a VACUUM is allowed to
-- renumber. Nothing in this program ever vacuums (checked across app/,
-- tests/ and deploy/), and whoever adds one has to rebuild the index in the
-- same breath: `INSERT INTO messages_fts (messages_fts) VALUES ('rebuild')`,
-- the same statement the migration uses.
--
-- `remove_diacritics 2` folds accents the way a person searching expects
-- ("Heizkorper" finds "Heizkörper") and, unlike mode 1, leaves characters
-- alone where the accent IS the letter.
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5 (
    content,
    content='messages',
    content_rowid='rowid',
    tokenize='unicode61 remove_diacritics 2'
);

-- An external-content index is not kept by the database on its own: these
-- three are what hold it level with the table. Without them a search finds
-- yesterday's chats and misses today's, which is worse than finding
-- nothing -- a hole nobody sees.
--
-- A delete is written as a 'delete' command carrying the OLD text, because
-- that is how FTS5 takes its tokens back out: the row is already gone from
-- `messages` by then, so the index cannot look them up any more.
CREATE TRIGGER IF NOT EXISTS messages_fts_eingefuegt
    AFTER INSERT ON messages
BEGIN
    INSERT INTO messages_fts (rowid, content) VALUES (NEW.rowid, NEW.content);
END;

CREATE TRIGGER IF NOT EXISTS messages_fts_geloescht
    AFTER DELETE ON messages
BEGIN
    INSERT INTO messages_fts (messages_fts, rowid, content)
        VALUES ('delete', OLD.rowid, OLD.content);
END;

-- Only on `content`: an answer grows by that column while it is being
-- written (`inhalt_aktualisieren`), and every other column changes without
-- moving a single word of the text.
CREATE TRIGGER IF NOT EXISTS messages_fts_geaendert
    AFTER UPDATE OF content ON messages
BEGIN
    INSERT INTO messages_fts (messages_fts, rowid, content)
        VALUES ('delete', OLD.rowid, OLD.content);
    INSERT INTO messages_fts (rowid, content) VALUES (NEW.rowid, NEW.content);
END;

-- Documents ---------------------------------------------------------------
-- Prepared for per-chat upload (phase 4.1). extracted_text is the already
-- extracted plain text that goes to the model as context.
--
-- pages: Page count (PDF only) and whether the text was truncated at the limit (4.1).
-- pfad: Where the uploaded file itself lies (app/dokumentablage.py): inside the
-- folder shared with the chat, next to its exe.md. NULL where there was
-- no folder to keep it in — then the row's text is all there is, the way
-- it was for every document before the file was kept at all. The path is
-- what lets a request that cannot carry the text name the place the model
-- can read a page of it from.
-- agent: The agent and the job that delivered the file into the chat's own
-- folder (app/tools/agentendock.py); NULL for what the person brought.
CREATE TABLE IF NOT EXISTS documents (
    id             TEXT PRIMARY KEY,
    chat_id        TEXT NOT NULL REFERENCES chats (id) ON DELETE CASCADE,
    filename       TEXT NOT NULL,
    mime_type      TEXT,
    size_bytes     INTEGER,
    extracted_text TEXT,
    pages          INTEGER,
    truncated      INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL,
    pfad           TEXT,
    agent          TEXT,
    job            TEXT
);

CREATE INDEX IF NOT EXISTS idx_documents_chat
    ON documents (chat_id, created_at);

-- Jobs --------------------------------------------------------------------
-- A job is one run of an agent (phase 6). It lives alongside the chats:
-- its own list, its own states, its own log. `wartet` means: the run is
-- stopped at a confirmation prompt and remains answerable — even across a
-- restart of the service. Only `laeuft` becomes `unterbrochen` at startup,
-- because the associated background task no longer exists after a restart.
--
-- agent: Name of the agent file (prompts/agenten/<agent>.md), without extension.
-- auftrag: The job text, exactly as it was given to the agent.
-- ende_grund: Every ending carries a readable reason (6.4): a stable key such as
-- 'zeitgrenze' or 'dienst_neustart', which the interface translates.
-- ergebnis: The report the agent checks in with at the end.
-- generation_id: Identifier of the running in-memory run, as long as one exists. After
-- a restart it points at nothing and is cleared during cleanup.
-- cronjob_id: The cron entry (cronjobs.id) that fired this run, if any — carried
-- from creation so a hard restart can find its way back to the SAME
-- chain instead of starting a fresh one (Schritt 6). NULL for a job
-- nothing has scheduled yet, including its very first run.
-- zwischenstand: The run's own status, written after every round rather than only at
-- the context-full handoff (Schritt 4) or a provider outage (Schritt
-- 5) — so a run a hard restart cuts off with neither has something to
-- resume from too. Whatever text the round produced so far; not the
-- structured handoff those two write, just enough for the next run to
-- pick the thread back up.
-- frage: The question this run is standing on, as JSON: the call's id, the
-- question itself and its options. Written the moment `ask_user` is
-- called, cleared the moment an answer arrives — so the row and the
-- state say the same thing, and a restart finds the question still
-- attached to the run that asked it.
-- dienst_port: Which service put this row on 'laeuft': its own port. Written at that
-- moment and never cleared, so the startup cleanup can tell its OWN
-- stranded rows from those of a second service on the same data folder
-- (app/main.py `_startbereinigung`) — and therefore run at all while
-- the other one is up. NULL for every row written before this column
-- existed and for every row that was never 'laeuft'.
-- eltern_id: The run that started this one, when a run did. A job an agent asked
-- for is not a NEW assignment but a PART of the one its parent was
-- given — which is what lets `start_job` work inside a job at all. It
-- is also the chain:
-- the panel shows who started whom, and a cancelled parent takes its
-- children with it. NULL for every run a person or a schedule started.
-- chat_id: The chat this job was started from, and every run under it carries
-- the same one: the report goes back there, a question stands there,
-- and deleting that chat stops the work. NULL for a job a schedule or
-- the start window started. No foreign key: the row outlives a deleted
-- chat as history.
CREATE TABLE IF NOT EXISTS auftraege (
    id            TEXT PRIMARY KEY,
    user_id       TEXT NOT NULL,
    agent         TEXT NOT NULL,
    auftrag       TEXT NOT NULL,
    zustand       TEXT NOT NULL CHECK (zustand IN
                  ('laeuft', 'wartet', 'fertig', 'abgebrochen',
                   'gescheitert', 'unterbrochen')),
    ende_grund    TEXT,
    ergebnis      TEXT,
    endpoint_id   TEXT,
    generation_id TEXT,
    cronjob_id    TEXT,
    zwischenstand TEXT,
    frage         TEXT,
    dienst_port   INTEGER,
    eltern_id     TEXT,
    chat_id       TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_auftraege_user_updated
    ON auftraege (user_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_auftraege_chat
    ON auftraege (chat_id);

-- Steps of a job ------------------------------------------------------------
-- The log: a run always records — every step, every tool call, every
-- result — regardless of where else the agent stores things.
-- `nummer` counts from 1 per job.
CREATE TABLE IF NOT EXISTS auftrag_schritte (
    id         TEXT PRIMARY KEY,
    auftrag_id TEXT NOT NULL REFERENCES auftraege (id) ON DELETE CASCADE,
    nummer     INTEGER NOT NULL,
    typ        TEXT NOT NULL,
    inhalt     TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_auftrag_schritte_auftrag
    ON auftrag_schritte (auftrag_id, nummer);

-- Cronjobs --------------------------------------------------------------
-- Independent, user-created standing schedules (6.7 extension) — several
-- per agent are possible, unlike the agent's own single `schedule:` field
-- in its front matter (app/wecker.py).
--
-- agent: Name of the agent file that runs this entry — re-read fresh at every
-- firing (app/cronablauf.py), so a change to that file's tools or
-- folders takes effect immediately and this can never end up with more
-- rights than the agent currently allows.
-- zeitplan: Daily fire time, 'HH:MM', in app.timezone — same format and the same
-- due-time rules as an agent's own schedule (app/wecker.py).
-- deliver: Where a result goes once the run ends. 'log' (default) means only the
-- run's own transcript; 'announce' additionally plays a sound and shows
-- the task text (app/cronmeldung.py). An entry with a `ziel` ignores
-- this for its ordinary runs: there, the goal decides what is announced
-- and when (Stufe 4).
-- herkunft: Who set this schedule: 'chat' (a person was watching) or 'agent' (a
-- run set its own). Audit only — the rights check itself always
-- re-reads the agent file at firing time regardless of this value.
-- erledigt_anzahl: The context-full handoff chain (app/zwischenstand.py, 6.7 extension):
-- how many "Done" bullets the last handoff carried, how many restarts in
-- a row that count failed to grow, and how many restarts this entry has
-- gone through in total. All zero/NULL for an entry nothing has ever
-- handed off through.
-- basisaufgabe: The chain's actual original task (app/zwischenstand.py), set once on
-- its first handoff and carried unchanged after that. Without this, the
-- wrapped "Continue this job..." text of the LAST restart would stand
-- in for the original on the next one — and each restart wraps it
-- again, so the opening message would grow with every restart instead
-- of the empty context this chain exists to guarantee.
-- einmalig: A one-off reminder rather than a standing daily one (Schritt 4):
-- ``zeitplan`` stays a plain 'HH:MM', but a fire that actually ran
-- deactivates this entry instead of leaving it to come back tomorrow.
-- The row itself stays — the history view still needs it.
-- datum: The exact day a one-off reminder is due, 'YYYY-MM-DD' (Schritt 5) —
-- NULL for a daily entry, and for a one-off that only names a time and
-- keeps firing at the next occurrence of it, same as before this
-- existed. Set together with ``einmalig``, never on its own.
-- fehlversuche: How many runs in a row ended failed (Stufe 2), and how many in a row
-- it takes for the entry to stop trying. What counts is only a run's
-- technical outcome: the model was unreachable, a tool was refused, the
-- run broke off. A run that looked and found nothing ends 'fertig' and
-- puts this back to zero — "goal not met" is not a failure. Neither is
-- an abort by hand; that one is the user's own doing.
-- Per entry rather than one global knob: a flaky nightly backup and a
-- minute-by-minute inbox check do not deserve the same patience.
-- ziel: The goal this entry is watching for (Stufe 4), NULL for an entry that
-- simply runs. With one set, the entry stops announcing after every run
-- and announces only what the `goal` tool call carried — the run that
-- looks and finds nothing ends in silence, which is the whole point:
-- fourteen quiet passes and then "it is here".
-- Free text on purpose, and it stays free text: a later checking build
-- (a second run judging the answer against the goal) reads this same
-- sentence, so no goal ever has to be rewritten for it.
-- ziel_stilllegen: Whether reaching the goal switches the entry off ("the mail is here,
-- stop looking") or leaves it running (a daily report). Per entry —
-- both are ordinary wishes and neither is the obvious default.
-- ziel_erreicht_am: When the goal was last reported, NULL for never. This is the answer
-- behind an entry the interface calls "finished" rather than "paused".
-- laeufe_ohne_ruf: Runs in a row that ended properly without reporting the goal. Its own
-- count, deliberately not folded into `fehlversuche`: being quiet is
-- what a goal entry does most of the time and must never switch
-- anything off. Reaching `fehlergrenze` says once that nothing has been
-- reported in that many runs — insurance against a model that forgot
-- the call — and then starts over at zero, entry still running.
-- notiz: The note one run leaves for the next one of the same entry (Stufe 5).
-- NULL for an entry nothing has written a note on. Without it the run
-- at 10:15 knows nothing of what the run at 10:00 saw: it reports the
-- same mail again, or cannot tell "new" from "old" at all.
-- Written only by the model, through the `cron_note` tool, and every
-- call REPLACES it — never appends. A note that grew by a line per run
-- would be fed back into every future run until it crowded out the
-- task itself, and the whole point is a fixed, small piece of state.
-- The program writes nothing here of its own: the previous run's
-- `ergebnis` is prose written for a person, and feeding that in would
-- mean guessing which half of it was state.
-- A script entry (Stufe 9) never gets one -- no model, no writer.
-- notiz_am: When that note was WRITTEN, NULL for an entry that has none. The
-- next run is told how current the note is, and this is the honest
-- answer to that: `zuletzt_ausgeloest` is stamped for a due time that
-- was merely SKIPPED (a run was still going, app/cronablauf.py) as
-- well as for one that fired, so it can name a moment AFTER the note
-- was written -- and everything that happened in between would count
-- as already seen and never be reported.
-- ursprung_id: The entry this one is a continuation of (app/zwischenstand.py), NULL
-- for an entry that stands on its own. A run whose context fills up
-- writes its remaining work into a fresh entry, and without this the
-- new entry knows nothing about where the work came from: the original
-- keeps firing after the chain has long reached the goal, the note the
-- chain wrote never reaches it, and a one-off that hands its work on
-- ends without anybody being told anything at all.
-- Always the REAL origin, never an intermediate link: a continuation of
-- a continuation copies this id rather than pointing at its immediate
-- predecessor, so one hop always leads to the entry a person made.
-- skript: The script this entry starts instead of a model run (Stufe 9), NULL
-- for every entry there has ever been. For a nightly backup, loading a
-- language model to say "run the backup" is nonsense: the script is the
-- work, and no model is started at all.
-- A plain FILE NAME, never a path. It is resolved against the scripts
-- location (app/speicherorte.py) at creation AND at every firing, and
-- has to come out inside that folder — links pointing out of it
-- included. That check is the whole security of this feature: a script
-- started here runs with the user's full rights and never passes Tor 3
-- (app/berechtigungen.py), which sees a tool name and its arguments and
-- has nobody to ask during an unattended run. So the guard has to sit
-- BEFORE the start: who may make such an entry (chat only — an agent
-- run cannot, or a page it read could talk it into writing itself one),
-- and what may stand in it.
-- An entry has EITHER agent+task OR a script: with a script set, the
-- NOT NULL `agent` column carries the fixed marker '(skript)', which can
-- collide with no agent file (the name pattern allows no brackets).
-- Goal, note and restart chains do not apply to such an entry — there is
-- no model to report or remember anything. The failure count does.
-- zeitgrenze: How many seconds that script may run before it is stopped and the run
-- counts as failed. NULL means the shipped default (app/tools/shell.py).
-- Per entry, because the default is the one a person waits out in a
-- chat, and a nightly backup is not that.
CREATE TABLE IF NOT EXISTS cronjobs (
    id                 TEXT PRIMARY KEY,
    agent              TEXT NOT NULL,
    task               TEXT NOT NULL,
    zeitplan           TEXT NOT NULL,
    deliver            TEXT NOT NULL DEFAULT 'log',
    aktiv              INTEGER NOT NULL DEFAULT 1,
    herkunft           TEXT NOT NULL CHECK (herkunft IN ('chat', 'agent')),
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL,
    zuletzt_ausgeloest TEXT,
    erledigt_anzahl    INTEGER,
    ohne_fortschritt   INTEGER NOT NULL DEFAULT 0,
    neustarts          INTEGER NOT NULL DEFAULT 0,
    basisaufgabe       TEXT,
    einmalig           INTEGER NOT NULL DEFAULT 0,
    datum              TEXT,
    fehlversuche       INTEGER NOT NULL DEFAULT 0,
    fehlergrenze       INTEGER NOT NULL DEFAULT 5,
    ziel               TEXT,
    ziel_stilllegen    INTEGER NOT NULL DEFAULT 0,
    ziel_erreicht_am   TEXT,
    laeufe_ohne_ruf    INTEGER NOT NULL DEFAULT 0,
    notiz              TEXT,
    notiz_am           TEXT,
    ursprung_id        TEXT,
    skript             TEXT,
    zeitgrenze         INTEGER
);

CREATE INDEX IF NOT EXISTS idx_cronjobs_agent ON cronjobs (agent);
