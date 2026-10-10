"""Projects: a name and the folders every chat in it shares.

A chat joins and leaves a project through the chat's own route
(`PATCH /chats/{id}` with `project_id`), because it is the chat that moves.
Here a project is made, renamed, given folders, put into the archive and
taken back — and deleted, which only the archive offers.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app import arbeitsordnerpruefung, ordnerwissen
from app.api.abhaengigkeiten import (
    hole_benutzer_id,
    hole_config,
    hole_repositories,
    hole_sprache,
)
from app.api.v1.chats import remove_chat
from app.api.v1.generierung import hole_generierungen
from app.api.v1.schemas import ProjectAnswer, ProjectCreate, ProjectUpdate
from app.config import Config
from app.db import Repositories
from app.db.models import Project
from app.generationen import Generierungsverwaltung
from app.i18n import t

router = APIRouter(prefix="/projects", tags=["projects"])


def _project_or_404(
    repositories: Repositories, project_id: str, user_id: str, language: str
) -> Project:
    project = repositories.projects.get(project_id, user_id=user_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=t("fehler.project_not_found", language),
        )
    return project


def _answer(project: Project, chat_count: int) -> ProjectAnswer:
    return ProjectAnswer(
        id=project.id,
        name=project.name,
        working_dirs=project.working_dirs,
        archived=project.archived,
        created_at=project.created_at,
        chat_count=chat_count,
    )


@router.get("", response_model=list[ProjectAnswer], summary="List projects")
def list_projects(
    archived: bool = Query(default=False, description="Lists the archive instead"),
    repositories: Repositories = Depends(hole_repositories),
    user_id: str = Depends(hole_benutzer_id),
) -> list[ProjectAnswer]:
    counts = repositories.projects.chat_counts(user_id=user_id)
    return [
        _answer(project, counts.get(project.id, 0))
        for project in repositories.projects.list_for(user_id=user_id, archived=archived)
    ]


@router.post("", response_model=ProjectAnswer, status_code=201, summary="Create a project")
def create_project(
    data: ProjectCreate,
    repositories: Repositories = Depends(hole_repositories),
    user_id: str = Depends(hole_benutzer_id),
    language: str = Depends(hole_sprache),
) -> ProjectAnswer:
    name = data.name.strip()
    if not name:
        raise HTTPException(400, t("fehler.project_needs_name", language))
    return _answer(repositories.projects.create(user_id=user_id, name=name), 0)


@router.patch("/{project_id}", response_model=ProjectAnswer, summary="Change a project")
def update_project(
    project_id: str,
    data: ProjectUpdate,
    repositories: Repositories = Depends(hole_repositories),
    config: Config = Depends(hole_config),
    user_id: str = Depends(hole_benutzer_id),
    language: str = Depends(hole_sprache),
) -> ProjectAnswer:
    before = _project_or_404(repositories, project_id, user_id, language)
    # A field sent as null changes nothing; an empty folder list is how the
    # folders are cleared.
    fields = {
        name: value
        for name, value in data.model_dump(exclude_unset=True).items()
        if value is not None
    }
    if "name" in fields:
        fields["name"] = fields["name"].strip()
        if not fields["name"]:
            raise HTTPException(400, t("fehler.project_needs_name", language))
    # The same check a chat's own folders get, and the same notes file for a
    # folder that is new here (app/api/v1/chats.py).
    if "working_dirs" in fields:
        fields["working_dirs"] = arbeitsordnerpruefung.pruefen(
            fields["working_dirs"], language, bekannte=before.working_dirs
        )
        new = [path for path in fields["working_dirs"] if path not in before.working_dirs]
        ordnerwissen.anlegen(new, config.datenverzeichnis)
    project = repositories.projects.update(project_id, **fields)
    assert project is not None
    counts = repositories.projects.chat_counts(user_id=user_id)
    return _answer(project, counts.get(project_id, 0))


@router.delete(
    "/{project_id}",
    response_model=list[str],
    summary="Delete a project with its chats",
)
async def delete_project(
    project_id: str,
    repositories: Repositories = Depends(hole_repositories),
    generierungen: Generierungsverwaltung = Depends(hole_generierungen),
    config: Config = Depends(hole_config),
    user_id: str = Depends(hole_benutzer_id),
    language: str = Depends(hole_sprache),
) -> list[str]:
    """Only from the archive: a project in the list is put away first.

    Answers with the ids of the chats that went with it, so the window can
    forget them the way it forgets a single deleted chat.
    """
    project = _project_or_404(repositories, project_id, user_id, language)
    if not project.archived:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=t("fehler.project_not_archived", language),
        )
    # Its chats go with it, each the way a single chat is deleted.
    chat_ids = repositories.projects.chat_ids(project_id)
    for chat_id in chat_ids:
        await remove_chat(
            chat_id,
            repositories=repositories,
            generierungen=generierungen,
            user_id=user_id,
            config=config,
        )
    repositories.projects.delete(project_id)
    return chat_ids
