"""The shape of the schema text itself: no ``--`` comment inside a
``CREATE TABLE ( … )`` parenthesis.

SQLite keeps the CREATE TABLE text and rewrites it on ``ALTER TABLE … DROP
COLUMN``. The 3.45.1 that Python 3.11 brings on Windows stumbles over a
comment between the columns while doing so ("incomplete input") and the
migration fails; the newer SQLite of the Mac does not. So the comments stand
in front of the statement, never inside it — in app/db/schema.sql and in the
two tables app/db/connection.py creates itself.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"
SCHEMA = APP / "db" / "schema.sql"
CONNECTION = APP / "db" / "connection.py"

_CREATE = re.compile(r"CREATE (?:VIRTUAL )?TABLE IF NOT EXISTS (\w+)")


def _table_bodies(text: str) -> list[tuple[str, str]]:
    """Every ``CREATE TABLE`` and the text between its outer parentheses —
    nested ones (a CHECK with an IN list) counted, not cut."""
    bodies = []
    for match in _CREATE.finditer(text):
        start = text.index("(", match.end())
        depth = 0
        for position in range(start, len(text)):
            if text[position] == "(":
                depth += 1
            elif text[position] == ")":
                depth -= 1
                if depth == 0:
                    bodies.append((match.group(1), text[start : position + 1]))
                    break
    return bodies


def test_no_table_in_the_schema_carries_a_comment_between_its_columns():
    tables = _table_bodies(SCHEMA.read_text(encoding="utf-8"))
    assert len(tables) == 10, [name for name, _ in tables]
    with_comments = [name for name, body in tables if "--" in body]
    assert with_comments == [], f"comments inside CREATE TABLE: {with_comments}"


def test_no_table_the_migrations_create_carries_a_comment_either():
    tables = _table_bodies(CONNECTION.read_text(encoding="utf-8"))
    assert tables, "connection.py creates no table any more"
    assert [name for name, body in tables if "--" in body] == []


def test_the_schema_still_builds_the_same_tables(tmp_path):
    """The silence side: the comments moved, nothing else did — the schema
    runs through, and the chats table keeps its columns in their order
    (the table the Windows migration dropped columns from)."""
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA.read_text(encoding="utf-8"))
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"chats", "projects", "messages", "documents", "auftraege", "cronjobs"} <= tables
    columns = [r[1] for r in con.execute("PRAGMA table_info(chats)")]
    assert columns == [
        "id", "user_id", "title", "endpoint_id", "pinned", "prompt_aus", "working_dirs",
        "frage", "created_at", "updated_at", "project_id", "archived",
    ]
    # The stored text is what DROP COLUMN rewrites: no comment in it either.
    stored = con.execute("SELECT sql FROM sqlite_master WHERE name = 'chats'").fetchone()[0]
    assert "--" not in stored
    con.execute("ALTER TABLE chats DROP COLUMN frage")
    assert "frage" not in [r[1] for r in con.execute("PRAGMA table_info(chats)")]
