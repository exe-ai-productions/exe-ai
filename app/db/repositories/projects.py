"""Access to projects: a name, the folders its chats share, the archive flag.

A chat joins a project and leaves it here, because both change the folders
of two rows at once — the chat's own and the project's — and they must
change together or not at all.
"""

from __future__ import annotations

from app.db.models import Project, folders_from_column, folders_to_column
from app.db.repositories.base import Repository, neue_id


class ProjectRepository(Repository):
    def create(self, *, user_id: str, name: str) -> Project:
        stamp = self.zeitstempel()
        project = Project(
            id=neue_id(), user_id=user_id, name=name, created_at=stamp, updated_at=stamp
        )
        self.verbindung.execute(
            """
            INSERT INTO projects (id, user_id, name, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (project.id, project.user_id, project.name, stamp, stamp),
        )
        return project

    def get(self, project_id: str, *, user_id: str | None = None) -> Project | None:
        sql = "SELECT * FROM projects WHERE id = ?"
        parameters: list[object] = [project_id]
        if user_id is not None:
            sql += " AND user_id = ?"
            parameters.append(user_id)
        row = self.verbindung.execute(sql, parameters).fetchone()
        return Project.from_row(row) if row else None

    def list_for(self, *, user_id: str, archived: bool = False) -> list[Project]:
        """In the order they were made, the way their chats are listed too."""
        rows = self.verbindung.execute(
            "SELECT * FROM projects WHERE user_id = ? AND archived = ?"
            " ORDER BY created_at, rowid",
            (user_id, int(archived)),
        ).fetchall()
        return [Project.from_row(row) for row in rows]

    def chat_ids(self, project_id: str) -> list[str]:
        rows = self.verbindung.execute(
            "SELECT id FROM chats WHERE project_id = ? ORDER BY created_at, rowid",
            (project_id,),
        ).fetchall()
        return [row["id"] for row in rows]

    def chat_counts(self, *, user_id: str) -> dict[str, int]:
        rows = self.verbindung.execute(
            "SELECT project_id, COUNT(*) AS count FROM chats"
            " WHERE user_id = ? AND project_id IS NOT NULL GROUP BY project_id",
            (user_id,),
        ).fetchall()
        return {row["project_id"]: int(row["count"]) for row in rows}

    def update(self, project_id: str, **fields: object) -> Project | None:
        """Changes the name, the folders or the archive flag."""
        allowed = {"name", "working_dirs", "archived"}
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"Unknown fields: {', '.join(sorted(unknown))}")
        folders = fields.get("working_dirs")
        if isinstance(folders, list):
            fields["working_dirs"] = folders_to_column(folders)
        if not fields:
            return self.get(project_id)
        assignments = ", ".join(f"{name} = ?" for name in fields)
        values = [int(value) if isinstance(value, bool) else value for value in fields.values()]
        values.extend([self.zeitstempel(), project_id])
        self.verbindung.execute(
            f"UPDATE projects SET {assignments}, updated_at = ? WHERE id = ?", values
        )
        return self.get(project_id)

    def add_chat(self, project_id: str, chat_id: str) -> None:
        """Puts a chat into a project. Its own folders join the project's —
        they belong to the project from now on — and the chat keeps none of
        its own while it lies there. A chat coming from another project
        leaves that one first and so brings its folders along."""
        with self.db.transaktion() as connection:
            self._leave(connection, chat_id)
            own = connection.execute(
                "SELECT working_dirs FROM chats WHERE id = ?", (chat_id,)
            ).fetchone()
            shared = connection.execute(
                "SELECT working_dirs FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
            folders = folders_from_column(shared["working_dirs"])
            for folder in folders_from_column(own["working_dirs"]):
                if folder not in folders:
                    folders.append(folder)
            connection.execute(
                "UPDATE projects SET working_dirs = ?, updated_at = ? WHERE id = ?",
                (folders_to_column(folders), self.zeitstempel(), project_id),
            )
            connection.execute(
                "UPDATE chats SET project_id = ?, working_dirs = NULL WHERE id = ?",
                (project_id, chat_id),
            )

    def remove_chat(self, chat_id: str) -> None:
        """Takes a chat out of its project. It keeps every folder of the
        project as its own."""
        with self.db.transaktion() as connection:
            self._leave(connection, chat_id)

    @staticmethod
    def _leave(connection, chat_id: str) -> None:
        row = connection.execute(
            "SELECT projects.working_dirs FROM chats"
            " JOIN projects ON projects.id = chats.project_id WHERE chats.id = ?",
            (chat_id,),
        ).fetchone()
        if row is None:
            return
        connection.execute(
            "UPDATE chats SET project_id = NULL, working_dirs = ? WHERE id = ?",
            (row["working_dirs"], chat_id),
        )

    def delete(self, project_id: str) -> bool:
        """The row alone. Its chats are deleted one by one before, the way
        every chat is deleted — see app/api/v1/projects.py."""
        cursor = self.verbindung.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        return cursor.rowcount > 0
