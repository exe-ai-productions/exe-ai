"""Access to chats."""

from __future__ import annotations

import re
from collections.abc import Callable
import sqlite3
import unicodedata
from pathlib import Path

from app import dokumentablage
from app.db.folding import FOLD_FUNCTION, fold_text
from app.db.models import Chat, folders_from_column, folders_to_column
from app.db.repositories.base import Repository, neue_id

# Everything that is not a letter or a digit separates two words — for the
# search box, not for FTS5: its own query language would read a stray
# quotation mark, a hyphen or the word OR as syntax and answer with an error
# instead of a result. What goes in is words; what is built from them below
# is the query.
#
# The underscore counts as a separator even though `\w` calls it a word
# character, and it is the only one that has to be named: it is the single
# character that is BOTH a LIKE wildcard and part of `\w`, so as a word it
# would reach FTS5 as `"_"*` — a phrase with no tokens at all, since the
# tokenizer separates on it too. Out here it stays what somebody typed.
_WORTGRENZE = re.compile(r"[\W_]+")

# What LIKE reads as a wildcard, and the escape character itself. A search
# box hands over what somebody typed, not a pattern: without this a single
# `%` matched every chat that has a title at all, and an `_` matched every
# single character.
_LIKE_JOKER = str.maketrans({"\\": "\\\\", "%": "\\%", "_": "\\_"})

# Every read of a chat brings its project along: a chat in a project works
# in the project's folders (Chat.aus_zeile), and a chat in an archived
# project is out of the list with it.
_CHAT_SELECT = (
    "SELECT chats.*, projects.working_dirs AS project_dirs"
    " FROM chats LEFT JOIN projects ON projects.id = chats.project_id"
)


def suchwoerter(suche: str) -> list[str]:
    """The words somebody typed, in order — or an empty list for none.

    Words, not the line: each of them has to be found somewhere in the chat
    (see ``auflisten``), and a line split nowhere could only ever be looked
    for as a whole.

    Composed first, and that is not cosmetic: a combining mark is not a word
    character, so decomposed text — a name pasted out of Finder — shattered
    mid-word. "Müller" as NFD came apart into "Mu" and "ller", and "ller"
    then had to be found as a word of its own, which it is nowhere: neither
    as an FTS prefix of the token `muller` nor inside the composed title.
    A chat plainly containing the name came back with no hits at all.
    """
    return [wort for wort in _WORTGRENZE.split(unicodedata.normalize("NFC", suche)) if wort]


def fts_wort(wort: str) -> str:
    """One word as an FTS5 query: a PREFIX, so typing "heizk" finds the
    conversation about Heizkörper.

    Quoted, never handed over raw: FTS5 reads its own query language, and a
    broken query comes back as an ERROR, not as an empty list. The quotes do
    the work here even though ``suchwoerter`` yields nothing but word
    characters — the quoting belongs beside the query, not beside the caller
    that happens to be safe today.
    """
    return f'"{wort}"*'


def like_muster(text: str) -> str:
    """``text`` as a LIKE pattern that matches it literally, wildcards and
    all. Used with ``ESCAPE '\\'``."""
    return f"%{text.translate(_LIKE_JOKER)}%"


# SQLite's documented defaults, for the two limits below — used where the
# engine cannot be asked (`getlimit` arrived in Python 3.11) and where it
# answers "no limit".
_TIEFE_VORGABE = 1000
_PLATZHALTER_VORGABE = 999


def _grenze(verbindung: sqlite3.Connection, name: str, vorgabe: int) -> int:
    """One of SQLite's own limits, or the documented default.

    **Zero means NO limit**, not "one" — that is what a build compiled with
    the maximum set to 0 reports. Read as a number it made the ceiling below
    come out as 1, and every search but its first word was then quietly
    dropped: "Heizkörper Preise" would list every chat about Heizkörper, with
    nothing anywhere saying that the second word had been ignored.

    The limit is named rather than handed in, because the NAMES are as young
    as the method: both arrived in Python 3.11. Written as
    ``sqlite3.SQLITE_LIMIT_EXPR_DEPTH`` at the call, an older interpreter
    would raise before this function is entered at all — the fallback would
    sit here unreachable while every search answered with an error.
    """
    welche = getattr(sqlite3, name, None)
    if welche is None:
        return vorgabe
    try:
        wert = verbindung.getlimit(welche)
    except (AttributeError, sqlite3.NotSupportedError):
        return vorgabe
    return wert if wert > 0 else vorgabe


def wortdeckel(verbindung: sqlite3.Connection) -> int:
    """How many words one search may carry — asked of SQLite, not chosen.

    Two of the engine's limits decide it, and the smaller one wins:

    * the **expression tree**, because each word adds exactly one level to
      the query below (measured: 999 words pass, the 1000th raises
      "Expression tree is too large"). Half of that limit, so that
      everything else in the statement has the other half.
    * the **number of bound values**, because each word binds two of them
      (its LIKE pattern and its FTS term) beside the three the statement
      carries anyway. Old SQLite allowed 999 of them, which the same word
      count would overrun — a different error, the same HTTP 500.

    There has to be a ceiling somewhere: the search box sends what it holds
    on every keystroke, and a pasted page of text used to come back as an
    uncaught error where "no hits" was the honest answer. Words past the
    ceiling are left out of the question, which can only ever make the
    answer WIDER, never wrong in the other direction; at hundreds of
    required words it is empty either way.
    """
    tiefe = _grenze(verbindung, "SQLITE_LIMIT_EXPR_DEPTH", _TIEFE_VORGABE)
    platzhalter = _grenze(verbindung, "SQLITE_LIMIT_VARIABLE_NUMBER", _PLATZHALTER_VORGABE)
    return max(1, min(tiefe // 2, (platzhalter - 3) // 2))


class ChatRepository(Repository):
    def erstellen(
        self,
        *,
        user_id: str,
        title: str,
        endpoint_id: str | None = None,
    ) -> Chat:
        chat = Chat(
            id=neue_id(),
            user_id=user_id,
            title=title,
            created_at=self.zeitstempel(),
            updated_at=self.zeitstempel(),
            endpoint_id=endpoint_id,
        )
        self.verbindung.execute(
            """
            INSERT INTO chats (id, user_id, title, endpoint_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                chat.id,
                chat.user_id,
                chat.title,
                chat.endpoint_id,
                chat.created_at,
                chat.updated_at,
            ),
        )
        return chat

    def holen(self, chat_id: str, *, user_id: str | None = None) -> Chat | None:
        sql = _CHAT_SELECT + " WHERE chats.id = ?"
        parameter: list[object] = [chat_id]
        if user_id is not None:
            sql += " AND chats.user_id = ?"
            parameter.append(user_id)
        zeile = self.verbindung.execute(sql, parameter).fetchone()
        return Chat.aus_zeile(zeile) if zeile else None

    def auflisten(
        self,
        *,
        user_id: str,
        suche: str | None = None,
        limit: int = 100,
        offset: int = 0,
        archived: bool = False,
    ) -> list[Chat]:
        """Pinned first, then the newest. ``suche`` filters title AND content.

        ``archived`` lists the archive instead: the chats put away one by
        one. A chat that went with its project is listed under the project
        (``ProjectRepository.chat_ids``), not here.
        """
        sql = (
            _CHAT_SELECT
            + " WHERE chats.user_id = ? AND chats.archived = ?"
            + " AND (projects.archived IS NULL OR projects.archived = 0)"
        )
        parameter: list[object] = [user_id, int(archived)]
        if suche:
            # EVERY word has to be found in the chat, and each one may be
            # found on either side of it: in the title, or in something that
            # was said. Per WORD and not per side — somebody who remembers
            # one word from the title and one from the conversation types
            # both, and a chat is one thing, not two haystacks.
            #
            # The title is still asked as a substring, so a piece of a word
            # inside it counts; the content is asked as a prefix, because
            # that is what an index of words can answer. Both sides of the
            # title are folded the way the index folds (case and accents),
            # so a word is found in a title whichever way it was typed.
            #
            # Through `messages` rather than reading `chat_id` off the index:
            # an external-content table stores no column but the indexed
            # text, so the row it points at is where the chat is named.
            # Folded rows count too — they are still in the conversation the
            # reader is looking for, only not in what the model is sent.
            # Words of one character are LEFT OUT of the question, not asked
            # of the title alone. As an FTS prefix a single letter is the
            # most expensive question the index can be asked and the least
            # useful one — it walks the doclist of every term beginning with
            # it and keeps nearly every row (measured on 50 000 messages:
            # 0.64 s, matching all of them) — but REQUIRING it of the title
            # was worse than either: punctuation makes such words on its own,
            # so "GPT-4", "Claude 3", "Level 8" and a Windows path came
            # back empty while the exact string stood in a message. Leaving a
            # word out can only ever make the answer wider; requiring it in
            # the one place it cannot be made it wrong.
            worte = [
                wort
                for wort in suchwoerter(suche)[: wortdeckel(self.verbindung)]
                if len(wort) > 1
            ]
            for wort in worte:
                sql += (
                    f" AND ({FOLD_FUNCTION}(title) LIKE ? ESCAPE '\\'"
                    " OR chats.id IN (SELECT chat_id FROM messages WHERE rowid IN"
                    " (SELECT rowid FROM messages_fts WHERE messages_fts MATCH ?)))"
                )
                parameter.extend([like_muster(fold_text(wort)), fts_wort(wort)])
            if not worte:
                # Not one usable word — a single letter, or nothing but
                # punctuation. Then the line is looked for as it stands, and
                # literally: the box shows something, and a filter that
                # quietly matched everything would say the opposite. The
                # title answers it, which is where a one-letter search was
                # always answered and costs nothing.
                sql += f" AND {FOLD_FUNCTION}(title) LIKE ? ESCAPE '\\'"
                parameter.append(like_muster(fold_text(suche)))
        # Pinned ones always sit on top. rowid as tiebreaker: equal
        # timestamps must not lead to a random order.
        sql += " ORDER BY pinned DESC, chats.updated_at DESC, chats.rowid DESC LIMIT ? OFFSET ?"
        parameter.extend([limit, offset])
        zeilen = self.verbindung.execute(sql, parameter).fetchall()
        return [Chat.aus_zeile(zeile) for zeile in zeilen]

    def aktualisieren(self, chat_id: str, **felder: object) -> Chat | None:
        """Changes individual fields. Unknown field names are rejected."""
        erlaubt = {
            "title",
            "prompt_aus",
            "endpoint_id",
            "pinned",
            "working_dirs",
        }
        # Model parameters do not live here any more: they are settings and
        # sit in the cascade (app/db/repositories/einstellungen.py), where a
        # value can hold for one chat, one model, or everything.
        # The working folders: a list from the outside, JSON in the
        # column. An empty list means NULL — no difference between "none
        # chosen" and "empty list stored".
        folders = felder.get("working_dirs")
        if isinstance(folders, list):
            felder["working_dirs"] = folders_to_column(folders)
        unbekannt = set(felder) - erlaubt
        if unbekannt:
            raise ValueError(f"Unknown fields: {', '.join(sorted(unbekannt))}")
        if not felder:
            return self.holen(chat_id)

        zuweisungen = ", ".join(f"{name} = ?" for name in felder)
        # SQLite has no boolean — True/False become 1/0.
        werte = [int(wert) if isinstance(wert, bool) else wert for wert in felder.values()]
        werte.extend([self.zeitstempel(), chat_id])
        self.verbindung.execute(
            f"UPDATE chats SET {zuweisungen}, updated_at = ? WHERE id = ?", werte
        )
        return self.holen(chat_id)

    def anheften(self, chat_id: str, angeheftet: bool = True) -> Chat | None:
        """Lifts a chat permanently to the top of the list.

        Deliberately does not touch ``updated_at``: pinning is not usage.
        Otherwise, on unpinning, a chat would jump to a spot where it has no
        business being, content-wise.
        """
        self.verbindung.execute(
            "UPDATE chats SET pinned = ? WHERE id = ?", (int(angeheftet), chat_id)
        )
        return self.holen(chat_id)

    def set_archived(self, chat_id: str, archived: bool) -> Chat | None:
        """Into the archive or back. Leaves ``updated_at`` alone, for the
        reason ``anheften`` gives: putting a chat away is not using it."""
        self.verbindung.execute(
            "UPDATE chats SET archived = ? WHERE id = ?", (int(archived), chat_id)
        )
        return self.holen(chat_id)

    def frage_setzen(self, chat_id: str, frage_json: str | None) -> bool:
        """The open ask_user question, as JSON — or None once it is
        answered, times out, or the run ends. Deliberately outside
        `aktualisieren` and untouching `updated_at`, the same reasoning
        `anheften` gives: a question being asked or answered is not the
        user reordering their own list.

        False when the chat is gone: a run whose chat was deleted under it
        would otherwise go on writing to a row that no longer exists, and
        nobody would learn of it.
        """
        cursor = self.verbindung.execute(
            "UPDATE chats SET frage = ? WHERE id = ?", (frage_json, chat_id)
        )
        return cursor.rowcount > 0

    def zeitstempel_auffrischen(self, chat_id: str) -> None:
        """Lifts a chat upward in the sort order (new message)."""
        self.verbindung.execute(
            "UPDATE chats SET updated_at = ? WHERE id = ?", (self.zeitstempel(), chat_id)
        )

    def loeschen(
        self,
        chat_id: str,
        *,
        user_id: str | None = None,
        datenverzeichnis: Path | None = None,
    ) -> bool:
        """Deletes the chat along with messages and documents (ON DELETE CASCADE).

        ``datenverzeichnis`` is the program's data folder, handed in by the
        caller because a repository knows the database and nothing else
        (``app/db/repositories/base.py``). Given one, the chat's own document
        folder goes with the row — the folder a chat without a shared folder
        of its own wrote its uploads into. The path is built inside
        ``app/dokumentablage.py`` from that folder and the id, never read off
        a row, so a folder of the user's can never end up under this call.
        """
        sql = "DELETE FROM chats WHERE id = ?"
        parameter: list[object] = [chat_id]
        if user_id is not None:
            sql += " AND user_id = ?"
            parameter.append(user_id)
        cursor = self.verbindung.execute(sql, parameter)
        geloescht = cursor.rowcount > 0
        if geloescht:
            # Settings of this chat go with it. The database cannot do this by
            # itself: the scope is a text field, not a foreign key, so nothing
            # cascades — without this the rows would outlive their chat.
            self.verbindung.execute(
                "DELETE FROM einstellungen WHERE bereich = ?", (f"chat:{chat_id}",)
            )
            # And the files, for the same reason: they are not rows, so no
            # cascade reaches them. Without this every document a folderless
            # chat ever uploaded would outlive the conversation that held it,
            # with nothing left that could name it.
            if datenverzeichnis is not None:
                dokumentablage.aufraeumen(datenverzeichnis, chat_id)
        return geloescht

    def anzahl(self, *, user_id: str) -> int:
        zeile = self.verbindung.execute(
            "SELECT COUNT(*) AS anzahl FROM chats WHERE user_id = ?", (user_id,)
        ).fetchone()
        return int(zeile["anzahl"])

    def shares_moved(self, follow: Callable[[str], Path | None]) -> int:
        """Moves shared folders to where ``follow`` says they lie now, in
        the chats and the projects alike — after the program itself renamed
        a folder (app/folder_names.py). Only where the folder really lies
        there; the order of the list stays. Returns how many lists were
        rewritten."""
        moved = 0
        for table in ("chats", "projects"):
            rows = self.verbindung.execute(
                f"SELECT id, working_dirs FROM {table} WHERE working_dirs IS NOT NULL"
            ).fetchall()
            for row in rows:
                try:
                    folders = folders_from_column(row["working_dirs"])
                except ValueError:
                    continue
                if not isinstance(folders, list) or not all(
                    isinstance(folder, str) for folder in folders
                ):
                    # A list this cannot read is left as it is; the rows
                    # after it are still looked at.
                    continue
                renewed = []
                for folder in folders:
                    target = follow(folder)
                    try:
                        there = target is not None and target.is_dir()
                    except OSError:
                        there = False
                    moved_to = str(target) if there else folder
                    if moved_to not in renewed:
                        renewed.append(moved_to)
                if renewed != folders:
                    self.verbindung.execute(
                        f"UPDATE {table} SET working_dirs = ? WHERE id = ?",
                        (folders_to_column(renewed), row["id"]),
                    )
                    moved += 1
        return moved
