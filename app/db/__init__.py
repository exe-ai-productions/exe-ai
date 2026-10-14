"""Database layer — the only place in the project where SQL occurs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.config import Config
from app.db.connection import Database
from app.db.repositories.auftraege import AuftragRepository
from app.db.repositories.chats import ChatRepository
from app.db.repositories.cronjobs import CronjobRepository
from app.db.repositories.documents import DocumentRepository
from app.db.repositories.einstellungen import EinstellungenRepository
from app.db.repositories.messages import MessageRepository
from app.db.repositories.projects import ProjectRepository


@dataclass
class Repositories:
    """Binder: one access point to all repositories."""

    db: Database
    chats: ChatRepository
    messages: MessageRepository
    documents: DocumentRepository
    auftraege: AuftragRepository
    cronjobs: CronjobRepository
    einstellungen: EinstellungenRepository
    projects: ProjectRepository


def repositories_erstellen(db: Database) -> Repositories:
    return Repositories(
        db=db,
        chats=ChatRepository(db),
        messages=MessageRepository(db),
        documents=DocumentRepository(db),
        auftraege=AuftragRepository(db),
        cronjobs=CronjobRepository(db),
        einstellungen=EinstellungenRepository(db),
        projects=ProjectRepository(db),
    )


def datenbank_oeffnen(config: Config | None = None, pfad: str | Path | None = None) -> Database:
    """Opens the database and sets up the schema when needed."""
    if pfad is None:
        if config is None:
            raise ValueError("Either 'config' or 'pfad' must be specified.")
        if config.database.backend != "sqlite":
            raise NotImplementedError(
                f"Backend '{config.database.backend}' is not yet implemented. The repository "
                "pattern allows another backend to be added here."
            )
        pfad = config.datenbankpfad

    # The service's own port travels with the database: every row this
    # service puts on 'laeuft' is stamped with it, and the startup cleanup
    # reads it back to leave a second service's rows alone (app/main.py).
    db = Database(pfad, dienst_port=config.app.port if config is not None else None)
    db.schema_einrichten()
    return db


__all__ = [
    "Database",
    "Repositories",
    "datenbank_oeffnen",
    "repositories_erstellen",
    "AuftragRepository",
    "ChatRepository",
    "CronjobRepository",
    "MessageRepository",
    "DocumentRepository",
    "ProjectRepository",
]
