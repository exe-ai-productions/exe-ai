"""Access to uploaded documents (per chat).

Present from day one so the schema does not
have to move later.
"""

from __future__ import annotations

from pathlib import Path
from collections.abc import Callable
from typing import Any

from app import dokumentablage
from app.db.models import Document
from app.db.repositories.base import Repository, neue_id


class DocumentRepository(Repository):
    def speichern(
        self,
        *,
        chat_id: str,
        filename: str,
        mime_type: str | None = None,
        size_bytes: int | None = None,
        extracted_text: str | None = None,
        pages: int | None = None,
        pfad: str | None = None,
        agent: str | None = None,
        job: str | None = None,
    ) -> Document:
        dokument = Document(
            id=neue_id(),
            chat_id=chat_id,
            filename=filename,
            created_at=self.zeitstempel(),
            mime_type=mime_type,
            size_bytes=size_bytes,
            extracted_text=extracted_text,
            pages=pages,
            pfad=pfad,
            agent=agent,
            job=job,
        )
        # The table's ``truncated`` column is not written: a document travels
        # whole or not at all, so nothing here has anything to say about it.
        # Its NOT NULL default fills the column in.
        self.verbindung.execute(
            """
            INSERT INTO documents (id, chat_id, filename, mime_type, size_bytes,
                                   extracted_text, pages, created_at, pfad,
                                   agent, job)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                dokument.id,
                dokument.chat_id,
                dokument.filename,
                dokument.mime_type,
                dokument.size_bytes,
                dokument.extracted_text,
                dokument.pages,
                dokument.created_at,
                dokument.pfad,
                dokument.agent,
                dokument.job,
            ),
        )
        return dokument

    def holen(self, document_id: str) -> Document | None:
        zeile = self.verbindung.execute(
            "SELECT * FROM documents WHERE id = ?", (document_id,)
        ).fetchone()
        return Document.aus_zeile(zeile) if zeile else None

    def auflisten(self, *, chat_id: str) -> list[Document]:
        zeilen = self.verbindung.execute(
            "SELECT * FROM documents WHERE chat_id = ? ORDER BY created_at ASC",
            (chat_id,),
        ).fetchall()
        return [Document.aus_zeile(zeile) for zeile in zeilen]

    def for_folder(self) -> list[dict[str, Any]]:
        """Every document of every chat, with its chat's project, for the doc
        folder (app/docfolder.py). Without the extracted text: the folder
        shows files, and the text can be the size of a book."""
        zeilen = self.verbindung.execute(
            "SELECT documents.id, documents.chat_id, documents.filename,"
            " documents.mime_type, documents.size_bytes, documents.created_at,"
            " documents.pfad, documents.agent, documents.job, chats.project_id"
            " FROM documents JOIN chats ON chats.id = documents.chat_id"
        ).fetchall()
        return [dict(zeile) for zeile in zeilen]

    def anzahl(self, *, chat_id: str) -> int:
        """How many documents hang on a chat — without reading their bodies."""
        zeile = self.verbindung.execute(
            "SELECT COUNT(*) FROM documents WHERE chat_id = ?", (chat_id,)
        ).fetchone()
        return int(zeile[0]) if zeile else 0

    def loeschen(self, document_id: str, *, datenverzeichnis: Path | None = None) -> bool:
        """Drops the row — and, given the data folder, the file with it.

        Only ever a file in the chat's OWN folder; the check for that sits in
        ``app/dokumentablage.py``, so a file in a folder of the user's is
        never touched here. Without this the upload of a chat that shares no
        folder outlived the only row that could name it, and nothing but
        deleting the whole chat ever cleared it.

        ``datenverzeichnis`` is handed in by the caller, the same way the
        chat delete does it: a repository knows the database and nothing else
        (``app/db/repositories/base.py``).
        """
        dokument = self.holen(document_id)
        cursor = self.verbindung.execute(
            "DELETE FROM documents WHERE id = ?", (document_id,)
        )
        geloescht = cursor.rowcount > 0
        if geloescht and datenverzeichnis is not None and dokument and dokument.pfad:
            # Only once no row points at that file any more. The same bytes
            # uploaded twice land on ONE file (app/dokumentablage.py), and
            # removing it here would leave the other row naming nothing.
            noch_gebraucht = self.verbindung.execute(
                "SELECT 1 FROM documents WHERE pfad = ? LIMIT 1", (dokument.pfad,)
            ).fetchone()
            if not noch_gebraucht:
                dokumentablage.eigene_datei_entfernen(
                    datenverzeichnis, dokument.chat_id, dokument.pfad
                )
        return geloescht

    def pfade_umziehen(self, *, chat_id: str, alt: str, neu: str) -> int:
        """Moves this chat's document paths from under ``alt`` to under ``neu``.

        The pair comes from the button the user pressed on the folder that is
        missing — never from comparing the old list of shares with the new
        one. That comparison reads as "one went out, one came in" and starts
        guessing the moment two folders are missing at once, which is exactly
        the case the window answers by asking once per folder.

        Three limits, and each of them is a decision:

        * only rows of THIS chat — another conversation shared its own
          folders and nobody said anything about those;
        * only paths BELOW ``alt`` — a document that never lay in the moved
          folder did not move with it;
        * only where the file really lies at the new place. A path pointing
          at nothing is more honest than one pointing at the wrong file, and
          a folder can be moved while a single file in it was not.

        Returns how many rows were rewritten, which is what the log line
        above the call reports.
        """
        alter_ordner = Path(alt)
        neuer_ordner = Path(neu)
        gezogen = 0
        for dokument in self.auflisten(chat_id=chat_id):
            if not dokument.pfad:
                continue
            try:
                rest = Path(dokument.pfad).relative_to(alter_ordner)
            except ValueError:
                continue
            ziel = neuer_ordner / rest
            if not ziel.is_file():
                continue
            self.verbindung.execute(
                "UPDATE documents SET pfad = ? WHERE id = ?", (str(ziel), dokument.id)
            )
            gezogen += 1
        return gezogen

    def all_paths_moved(self, follow: Callable[[str], Path | None]) -> int:
        """Moves the paths of every chat's documents to where ``follow``
        says they lie now — a folder the program itself renamed
        (app/folder_names.py) held the uploads of many chats, so no single
        chat is the one to ask. Only where the file really lies there. Only
        the id and path are read: a document row carries its whole
        extracted text."""
        rows = self.verbindung.execute(
            "SELECT id, pfad FROM documents WHERE pfad IS NOT NULL"
        ).fetchall()
        moved = 0
        for row in rows:
            target = follow(row["pfad"])
            try:
                if target is None or not target.is_file():
                    continue
            except OSError:
                # One unreadable file stops no other row.
                continue
            self.verbindung.execute(
                "UPDATE documents SET pfad = ? WHERE id = ?", (str(target), row["id"])
            )
            moved += 1
        return moved
