"""Jobs: an agent works on its own.

A job run uses the same machinery as a chat — provider, tool registry, run
management from 6.1 — but with four differences:

  1. It is **not bound to a connection**: browser closed, run keeps running.
     You can watch at any time via ``GET /api/v1/chat/stream/{generation_id}``,
     in the same event format as a chat — so the UI (6.5) can use the same
     reader.
  2. **The prompt is stacked**: global prompt, then agent prompt.
     The job text is the user message.
  3. **The approval lives in the agent**: only the intersection
     of its ``tools`` list and the registry is offered, and whatever is
     offered runs without asking back. The registry remains the outer
     boundary — it checks once more itself when executing.
  4. **It always keeps a log**:
     every step, every tool call, every result — into the database,
     regardless of wherever else the agent stores things.

Two restraints per agent, rounds and time (6.4). If one runs out
or the context is full, the run ends **with a report** instead of a crash:
whatever has been produced so far is in the result, and the reason is stated
readably on the job.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

import re
import sqlite3

from app import (
    ablehnungslernen,
    agentendock,
    agentenfelder,
    agentenmodellwahl,
    agentenname,
    agentenserver,
    antwortende,
    antwortgrenze,
    arbeitsordnerpruefung,
    auftragdenklaengewahl,
    auftragsende,
    auftragsfrage,
    auftragtokenwahl,
    befehlszeitwahl,
    cronablauf,
    denkablehnung,
    dokumentablage,
    faltpause,
    gedaechtnis,
    grundprompt,
    kontextdruck,
    kontextverbrauch,
    kurzlauf,
    ordnerwissen,
    parameter,
    reasoning,
    skills,
    skillwahl,
    verdichtung,
    verdichtungswahl,
    wachhalten,
    werkzeugbild,
    werkzeugvorpruefung,
    werkzeugwahl,
    wiederversuch,
    zwischenstand,
)
from app.agenten import (
    Agent,
    AgentDateiKaputt,
    agent_aus_text,
    agent_text_lesen,
    kaputte_datei_satz,
    agenten_laden,
    geloeschte_agenten,
    loeschung_merken,
    loeschung_vergessen,
)
from app.api.abhaengigkeiten import hole_benutzer_id, hole_repositories, hole_sprache
from app.api.v1.generierung import (
    # One sender for both streams: every event carries `zeitpunkt_ms`, so a
    # reattached job's tool clock starts from when the call began.
    _auf_entscheidung_warten,
    _sse,
    _werkzeug_ausfuehren,
    hole_discovery,
    hole_generierungen,
    with_move_note,
)
from app.api.v1.schemas import (
    AgentAntwort,
    AgentDatei,
    AgentDateiEintrag,
    AgentDateiSchreiben,
    AgentFelderSchreiben,
    AuftragAnlegen,
    AuftragAntwort,
    AuftragAntwortSchreiben,
    AuftragDetail,
    LaufmodellAntwort,
    werk_von,
)
from app.db import Repositories
from app.db.repositories.auftraege import ENDZUSTAENDE
from app.events import Ereignisse, bus
from app.discovery import Discovery, denklaenge_erlaubt, refusal_key
from app.generationen import Generierung, Generierungsverwaltung
from app import i18n
from app.i18n import t
from app import faltversuche, helper, kontextvoll, round_end, stop_note, task_images
from app.providers import ChatNachricht, Generierungsanfrage, ProviderFehler, openai_responses
from app.schleifenwaechter import Schleifenwaechter
from app.tools import agentendock as ablage_werkzeug
from app.tools import registry as tool_registry
from app.tools import (
    bild_werkzeug,
    auftrag_werkzeug, datei_aendern, datei_schreiben, dateiwerkzeuge,
    frage_werkzeug, hintergrund, memory, shell, skill, ziel_werkzeug,
)

log = logging.getLogger(__name__)


class Refusal(HTTPException):
    """A refusal with the model's copy beside the window's sentence.

    The route answers a person, in the language the interface is set to. One
    caller has a MODEL at the other end instead — ``start_job``, called from a
    chat (app/api/v1/generierung.py) and from a running job (``_kind_starten``)
    — and a model handed the window's German would answer in German. Both
    copies are built here from the same catalogue key, so a caller reads the
    one it needs (``detail`` for the window, ``model`` for the model) and
    never has to match on a finished sentence.
    """

    def __init__(self, code: int, key: str, sprache: str, **values: object) -> None:
        super().__init__(code, t(key, sprache, **values))
        # Both copies are built HERE, from the same key — no caller has to
        # hold on to the key or rebuild a sentence from the finished one.
        self.model = t(key, i18n.STANDARDSPRACHE, **values)


def job_could_not_start(text: str) -> str:
    """The frame around a refused job start, written once.

    Three places say it — the chat's window copy, the chat's model copy and a
    running job that tried to start another — and a frame written out three
    times is how one of them ends up carrying the wrong language.
    """
    return f"The job could not start: {text}"


router = APIRouter(tags=["auftraege"])

# This much of a tool result ends up in the log and in the stream — the
# same cut the chat makes (WERKZEUGERGEBNIS_GRENZE in generierung.py), and
# the same one the shell tool caps its own output at. A job is the place a
# long download or a long listing actually happens, so cutting it shorter
# than the chat does is where a run's own evidence goes missing.
ERGEBNIS_KUERZUNG = 20_000
# The reasoning is display, not result — truncated is enough.
GEDANKE_KUERZUNG = 4000


def _agenten_verzeichnis(request: Request):
    """The USER's folder — the only one this API ever writes into."""
    config = request.app.state.config
    return config.pfad(config.app.agenten_verzeichnis)


def _agentenverzeichnisse(request: Request):
    """Both layers for reading, shipped first so the user's file wins."""
    return request.app.state.config.agentenverzeichnisse


# --- Agents -----------------------------------------------------------------


@router.get("/agents", response_model=list[AgentAntwort], summary="Available agents")
def agenten_auflisten(request: Request) -> list[AgentAntwort]:
    """Fresh from disk — broken files are missing and show up in the log."""
    agenten = agenten_laden(*_agentenverzeichnisse(request))
    return [AgentAntwort.aus(agent) for agent in agenten.values()]


# Agent names are file names. This check is the barrier against path tricks
# ('../', absolute paths) — whatever doesn't match here never reaches the
# filesystem in the first place.
AGENT_NAME_MUSTER = re.compile(r"^[A-Za-z0-9_-]{1,100}$")


def _agenten_datei(request: Request, name: str, sprache: str):
    if not AGENT_NAME_MUSTER.match(name):
        raise HTTPException(400, t("fehler.agent_name_ungueltig", sprache))
    return _agenten_verzeichnis(request) / f"{name}.md"



def _datei_antwort(name: str, text: str, sprache: str) -> AgentDatei:
    try:
        agent = agent_aus_text(name, text)
        kaputt = None
        prompt = agent.prompt
    except AgentDateiKaputt as fehler:
        kaputt = fehler.text(sprache)
        # No split to hand out: the header is what tells prompt from front
        # matter, and it is the header that is broken.
        prompt = None
    return AgentDatei(name=name, content=text, kaputt=kaputt, prompt=prompt)


@router.get(
    "/agent-files",
    response_model=list[AgentDateiEintrag],
    summary="All agent files, broken ones too (for the editing window)",
)
def agent_dateien_auflisten(
    request: Request, sprache: str = Depends(hole_sprache)
) -> list[AgentDateiEintrag]:
    """A separate path instead of ``/agents/something`` — ``files`` would be a
    valid agent name, and the paths must not get in each other's way."""
    # Both layers, keyed by name so a user's file shadows the shipped one —
    # the editor shows one row per agent, exactly like the run picks one.
    # A deleted shipped agent is deleted here too: the editor must not list
    # what the run no longer offers.
    geloescht = geloeschte_agenten(_agenten_verzeichnis(request))
    gefunden: dict[str, AgentDateiEintrag] = {}
    verzeichnisse = _agentenverzeichnisse(request)
    for verzeichnis in verzeichnisse:
        letzte = verzeichnis == verzeichnisse[-1]
        if not verzeichnis.is_dir():
            continue
        for datei in sorted(verzeichnis.glob("*.md")):
            if not letzte and datei.stem in geloescht:
                continue
            try:
                agent_aus_text(datei.stem, agent_text_lesen(datei))
                kaputt = None
            except AgentDateiKaputt as fehler:
                # The file's name travels in front of the reason, and the
                # reason comes from the catalogue in the page's language —
                # the same shape for every kind of broken agent file.
                kaputt = fehler.text(sprache)
            except OSError as fehler:
                # An unreadable file is this one agent's own breakage, named
                # like the broken ones beside it: the file in front, the
                # sentence of the page's language behind. What the system
                # says is English and carries the private path — that belongs
                # in the log.
                log.warning("Agent file cannot be read: %s", fehler)
                kaputt = kaputte_datei_satz(datei.name, t("agent_file.unreadable", sprache))
            gefunden[datei.stem] = AgentDateiEintrag(name=datei.stem, kaputt=kaputt)
    return [gefunden[name] for name in sorted(gefunden)]


@router.get(
    "/agents/{name}",
    response_model=AgentDatei,
    summary="The raw agent file (for the editing window)",
)
def agent_datei_lesen(
    name: str, request: Request, sprache: str = Depends(hole_sprache)
) -> AgentDatei:
    # The user's file first, the shipped one as the fallback — the editor
    # reads whichever is in force. Saving always writes the user's copy
    # (below), so editing a shipped agent shadows it instead of touching it.
    datei = _agenten_datei(request, name, sprache)
    if not datei.is_file():
        mitgeliefert, _ = _agentenverzeichnisse(request)
        datei = mitgeliefert / f"{name}.md"
    # A deleted shipped agent reads as what it is: gone. Only the shipped
    # fallback is silenced — a user's file on disk is the user's word.
    if datei.parent != _agenten_verzeichnis(request) and name in geloeschte_agenten(
        _agenten_verzeichnis(request)
    ):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            t("fehler.agent_nicht_gefunden", sprache, name=name),
        )
    if not datei.is_file():
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            t("fehler.agent_nicht_gefunden", sprache, name=name),
        )
    try:
        # Through the one read place (app/agenten.py): utf-8-sig, so a byte
        # order mark at the front is what a Windows editor leaves behind and
        # not a broken file — and bytes that are no UTF-8 at all come back
        # as this file's own breakage, with its name in front.
        text = agent_text_lesen(datei)
    except AgentDateiKaputt as fehler:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, fehler.text(sprache)
        ) from fehler
    except FileNotFoundError as fehler:
        # Gone between the look and the read — that is a missing agent, not
        # an unreadable one.
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, t("fehler.agent_nicht_gefunden", sprache, name=name)
        ) from fehler
    except OSError as fehler:
        # A file nobody can read is not a service that fell over: say so in
        # the editor, with the file's name in front like the decode error
        # above. The system's own line is English and names the private path
        # — it goes to the log.
        log.warning("Agent file cannot be read: %s", fehler)
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            kaputte_datei_satz(datei.name, t("agent_file.unreadable", sprache)),
        ) from fehler
    return _datei_antwort(name, text, sprache)


@router.put(
    "/agents/{name}",
    response_model=AgentDatei,
    summary="Save an agent file",
)
def agent_datei_schreiben(
    name: str,
    daten: AgentDateiSchreiben,
    request: Request,
    sprache: str = Depends(hole_sprache),
) -> AgentDatei:
    """Always saves — it is the user's file.

    If the front matter is no good, the reason goes into ``kaputt``: the agent
    is out of play, the service keeps running, the editor window can show it.
    Same approach as when loading (6.3), just visible earlier.
    """
    datei = _agenten_datei(request, name, sprache)
    datei.parent.mkdir(parents=True, exist_ok=True)
    datei.write_text(daten.content, encoding="utf-8")
    # A fresh save beats an old deletion — otherwise the file would exist
    # and the agent still count as gone.
    loeschung_vergessen(datei.parent, name)
    return _datei_antwort(name, daten.content, sprache)


@router.put(
    "/agents/{name}/fields",
    response_model=AgentDatei,
    summary="Save an agent's fields",
)
def agent_felder_schreiben(
    name: str,
    daten: AgentFelderSchreiben,
    request: Request,
    sprache: str = Depends(hole_sprache),
) -> AgentDatei:
    """Saves the form's fields into the file without losing the rest of it.

    The raw-text route above stays the hand editor's way; this one is the
    form's. Only the fields the request carries are touched
    (``app/agentenfelder.py``) — a ``permissions`` block, comments or fields
    from a newer version survive a form save untouched.

    Unlike the raw route this one validates BEFORE writing: a form has
    controls, so a value that would break the file is a bug worth stopping,
    not a user's word worth keeping.
    """
    datei = _agenten_datei(request, name, sprache)
    quelle = datei
    if not quelle.is_file():
        # Editing a shipped agent through the form shadows it, exactly like
        # the raw editor: the shipped text is the base, the user's folder
        # gets the result.
        mitgeliefert, _ = _agentenverzeichnisse(request)
        quelle = mitgeliefert / f"{name}.md"

    genannt = daten.model_fields_set
    felder = {
        feldname: getattr(daten, feldname)
        for feldname in agentenfelder.FORMULAR_FELDER
        if feldname in genannt
    }
    prompt = daten.prompt if "prompt" in genannt else None

    try:
        if quelle.is_file():
            text = agentenfelder.felder_anwenden(
                agent_text_lesen(quelle), felder, prompt
            )
        else:
            if not (prompt or "").strip():
                raise agentenfelder.KopfteilKaputt("new_without_prompt")
            text = agentenfelder.neu_bauen(felder, prompt)
        agent_aus_text(name, text)
    except (agentenfelder.KopfteilKaputt, AgentDateiKaputt) as fehler:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, fehler.text(sprache)
        ) from fehler
    except FileNotFoundError as fehler:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, t("fehler.agent_nicht_gefunden", sprache, name=name)
        ) from fehler
    except OSError as fehler:
        # Unreadable on disk: writing over it would need reading it first,
        # and guessing at the bytes is not this route's job. The system's own
        # line is English, names the private path and stays in the log; the
        # window is told in its own language, with the file's name in front.
        log.warning("Agent file cannot be read: %s", fehler)
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            kaputte_datei_satz(quelle.name, t("agent_file.unreadable", sprache)),
        ) from fehler

    datei.parent.mkdir(parents=True, exist_ok=True)
    datei.write_text(text, encoding="utf-8")
    loeschung_vergessen(datei.parent, name)
    return _datei_antwort(name, text, sprache)


@router.delete(
    "/agents/{name}",
    status_code=status.HTTP_204_NO_CONTENT,
    # The same trio as for chat deletion: 204 explicitly means no response
    # body, and FastAPI wants all three settings, otherwise it rejects the
    # route at startup.
    response_class=Response,
    response_model=None,
    summary="Delete an agent file",
)
def agent_datei_loeschen(
    name: str, request: Request, sprache: str = Depends(hole_sprache)
) -> None:
    """Deleted is deleted, whichever layer the file lies in.

    The user's file is removed; a shipped file cannot be removed (the next
    update would bring it back anyway), so its deletion is noted and the
    loaders silence it until that update. Only a name neither layer knows
    is a 404 — deleting a shipped agent used to be one, because only the
    user's folder was ever checked.
    """
    datei = _agenten_datei(request, name, sprache)
    mitgeliefert, _ = _agentenverzeichnisse(request)
    ausgeliefert = mitgeliefert / f"{name}.md"
    if not datei.is_file() and not (
        ausgeliefert.is_file()
        and name not in geloeschte_agenten(_agenten_verzeichnis(request))
    ):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            t("fehler.agent_nicht_gefunden", sprache, name=name),
        )
    if datei.is_file():
        datei.unlink()
    if ausgeliefert.is_file():
        loeschung_merken(_agenten_verzeichnis(request), name)


# --- Jobs -------------------------------------------------------------------


@router.post(
    "/jobs",
    response_model=AuftragAntwort,
    status_code=status.HTTP_201_CREATED,
    summary="Give an agent a job",
)
async def auftrag_starten(
    daten: AuftragAnlegen,
    request: Request,
    repositories: Repositories = Depends(hole_repositories),
    discovery: Discovery = Depends(hole_discovery),
    generierungen: Generierungsverwaltung = Depends(hole_generierungen),
    user_id: str = Depends(hole_benutzer_id),
    sprache: str = Depends(hole_sprache),
) -> AuftragAntwort:
    agenten = agenten_laden(*_agentenverzeichnisse(request))
    agent = agenten.get(daten.agent)
    if agent is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            t(
                "fehler.agent_nicht_gefunden_beim_start",
                sprache,
                name=daten.agent,
                verfuegbar=agentenname.namen_satz(agenten),
            ),
        )

    # Folders picked in the start window, checked like a chat's shares. When
    # none were picked this stays None, and the agent's own folders apply.
    ordner = (
        arbeitsordnerpruefung.pruefen(daten.folders, sprache)
        if daten.folders is not None
        else None
    )

    auftrag = auftrag_anstossen(
        config=request.app.state.config,
        repositories=repositories,
        discovery=discovery,
        generierungen=generierungen,
        registry=getattr(request.app.state, "werkzeuge", None),
        agent=agent,
        task=daten.task,
        endpoint_id=daten.endpoint_id,
        ordner=ordner,
        user_id=user_id,
        sprache=sprache,
    )
    werk, urspruenglicher_text = _kettendaten(repositories, auftrag)
    return AuftragAntwort.aus(auftrag, werk=werk, urspruenglicher_text=urspruenglicher_text)


def _work_of(
    repositories: Repositories, *, eltern_id: str | None, cronjob_id: str | None
):
    """The chat of the run this one carries on, and — for a continuation —
    the run its work began with. Each may be None.

    A continuation's entry names the run the work began with
    (``ursprung_id``, app/zwischenstand.py); for work a schedule began, that
    is an entry, not a run, and there is no chat to find.
    """
    if eltern_id:
        parent = repositories.auftraege.holen(eltern_id)
        return (parent.chat_id if parent is not None else None), None
    origin = work_origin(repositories, cronjob_id)
    return (origin.chat_id if origin is not None else None), origin


def work_origin(repositories: Repositories, cronjob_id: str | None):
    """The run a continuation carries on — the one its work began with — or
    None for a run no continuation fired."""
    if not cronjob_id:
        return None
    entry = repositories.cronjobs.holen(cronjob_id)
    if entry is None or not entry.ursprung_id:
        return None
    return repositories.auftraege.holen(entry.ursprung_id)


def previous_run_of_work(
    repositories: Repositories, origin, cronjob_id: str | None, current_id: str
):
    """The run right before this one in the work a continuation carries on —
    the newest other run its entry fired, however it ended, or ``origin``,
    the run the work began with, where the entry fired none before. None
    for a run no continuation fired (``origin`` None): a fresh run has no
    reply of its own before it."""
    if origin is None or cronjob_id is None:
        return None
    return repositories.auftraege.previous_run(cronjob_id, current_id) or origin


# What the model of a run the chat model sent off reads when its call was
# asked about in the chat and nobody answered within the confirmation's
# usual wait. That one call is refused; the run goes on. The model is told
# plainly that nobody can approve the request and not to retry it.
NOBODY_APPROVED = (
    "Nobody was there to approve '{name}', so it did not run. "
    "Do not try this call again; carry on without it."
)


def refusal_for(entscheidung, name: str) -> str | None:
    """What the model reads for an answer to a call asked about in the chat
    — None for a yes, the call then runs. English: only the model reads it.
    The same sentences the chat's own calls get, except for no answer at
    all, which in a run nobody is watching must also say not to try again."""
    if entscheidung is True:
        return None
    if entscheidung is None:
        return NOBODY_APPROVED.format(name=name)
    if isinstance(entscheidung, str):
        return t("fehler.tool_declined_with_words", "en", name=name, text=entscheidung)
    return t("fehler.werkzeug_abgelehnt", "en", name=name)


async def _ask_in_chat(
    *,
    generierung,
    repositories: Repositories,
    registry,
    aufruf,
    ordner: list[str],
    agent_name: str,
    chat_id: str | None,
    sprache: str,
):
    """Asks about one call of a run the chat model sent off, and waits.

    The same event the chat's own calls are asked about with
    (``tool_confirm``, app/api/v1/generierung.py), in the run's own stream,
    with the agent's name and the chat beside it; answered through the same
    route (``POST /api/v1/chat/confirm``) under this run's generation id.
    The run stands in the job list as waiting while it waits — the state
    goes to ``wartet`` and back, as for a question of its own
    (``app/auftragsfrage.py``) — and ``Ereignisse.AUFTRAG_FRAGT`` tells an
    open window so without it asking.

    Waits as long as the chat waits for its own (``BESTAETIGUNG_WARTEZEIT``)
    and hands back what the chat's wait hands back: ``True``/``False``, the
    user's words, or ``None`` where no answer came or the run was stopped.
    """
    anlass = registry.bestaetigungsgrund(aufruf.name, aufruf.argumente, ordner)
    generierung.melden(
        _sse(
            "tool_confirm",
            name=aufruf.name,
            argumente=aufruf.argumente,
            # The window's sentence, in the window's language.
            grund=t(anlass[0], sprache, **{anlass[1]: anlass[2]}) if anlass else "",
            grund_wert=anlass[2] if anlass else "",
            aufruf_id=aufruf.id,
            agent=agent_name,
            chat_id=chat_id,
            generation_id=generierung.id,
        )
    )
    # The run's id: job runs are registered under it (``auftrag_anstossen``).
    auftrag_id = generierung.chat_id
    repositories.auftraege.zustand_setzen(auftrag_id, "wartet")
    bus.veroeffentlichen_ohne_warten(
        Ereignisse.AUFTRAG_FRAGT, auftrag_id=auftrag_id, agent=agent_name, wartet=True
    )
    try:
        return await _auf_entscheidung_warten(generierung, aufruf.id, aufruf.name)
    finally:
        # Back to running — but never over an ending: a stop while waiting
        # has already written its own state.
        stand = repositories.auftraege.holen(auftrag_id)
        if stand is not None and stand.zustand == "wartet":
            repositories.auftraege.zustand_setzen(auftrag_id, "laeuft")
        bus.veroeffentlichen_ohne_warten(
            Ereignisse.AUFTRAG_FRAGT,
            auftrag_id=generierung.chat_id,
            agent=agent_name,
            wartet=False,
        )


def run_folders(ordner: list[str] | None, agent: Agent) -> list[str]:
    """The folders a run gets: the ones picked for it, or the agent's own.
    One rule, read by the run and by whoever prepares what the run is
    handed (``app/task_images.py``)."""
    return list(ordner) if ordner is not None else list(agent.ordner)


def chat_run_folders(data_dir, chat, agent: Agent) -> tuple[list[str] | None, str | None]:
    """The folders picked for a run a chat sent off, and which of them is
    the chat's own.

    They are the folders that chat's own tools work in
    (``dokumentablage.ordner_dieses_chats``): the shared ones, then the
    chat's own folder — first where nothing is shared. So a relative path
    of the run lands where the same path lands in the chat, and not on the
    dock, which the run gets behind them like every run.

    They win the way a pick in the start window wins over the agent's own.
    Only a chat that shares nothing leaves an agent the folders its file
    names: None then, and ``run_folders`` answers with those.

    The chat's own folder is named apart, as it is in the chat: the program
    made it, the user did not share it — unless they did, and then it is a
    share like any other and the second answer is None.
    """
    if agent.ordner and not chat.working_dirs:
        return None, None
    folders = dokumentablage.ordner_dieses_chats(data_dir, chat.working_dirs, chat.id)
    return folders, dokumentablage.own_folder_in(data_dir, chat.id, chat.working_dirs, folders)


def _first_message(environment_block: str, task_text: str, images, *, vision: bool):
    """The run's first user message: the environment block, the task, and
    the pictures handed over with it (``app/task_images.py``)."""
    urls, lines = task_images.for_model(list(images or []), vision)
    content = f"{environment_block}\n\n{task_text}"
    if lines:
        content = f"{content}\n\n" + "\n".join(lines)
    return ChatNachricht(role="user", content=content, bild_urls=urls)


def widen_tools(agent: Agent, *, hat_ziel: bool) -> Agent:
    """The agent with the always-offered tools added to its own list.

    What goes on that list is not written out here: it is the same list the
    offer, the settings window and the tools window read
    (``app/tools/registry.py``, ``EVER_OFFERED``), and each entry says for
    which runs it is widened — the clock for every run that uses tools at
    all, the goal only where there is a goal to report.

    A widened COPY for this run only, never the agent file: an agent has one
    list, and a schedule lending a run its goal tool must not rewrite it.

    An empty list is left empty (for the clock): written out, ``[]`` is
    somebody saying "none of them" on purpose, and widening it would turn
    the whole run into one that uses tools at all. The goal is the
    exception — the schedule's entry IS the instruction to report.
    """
    for e in tool_registry.EVER_OFFERED:
        if not e.widened and not hat_ziel:
            continue
        if agent.werkzeuge is None:
            continue
        if not agent.werkzeuge and not e.even_empty:
            continue
        if e.tool.WERKZEUG_NAME not in agent.werkzeuge:
            agent = dataclasses.replace(
                agent, werkzeuge=[*agent.werkzeuge, e.tool.WERKZEUG_NAME]
            )
    return agent


def auftrag_anstossen(
    *,
    config,
    repositories: Repositories,
    discovery: Discovery,
    generierungen: Generierungsverwaltung,
    registry,
    agent: Agent,
    task: str,
    endpoint_id: str | None,
    ordner: list[str] | None = None,
    own_folder: str | None = None,
    user_id: str,
    sprache: str,
    cronjob_id: str | None = None,
    eltern_id: str | None = None,
    chat_id: str | None = None,
    ask_in_chat: bool = False,
    images: list[task_images.TaskImage] | None = None,
):
    """Creates the job and starts the background run.

    ``cronjob_id`` is set only when a cron entry (app/cronablauf.py) is what
    fired this run — it is how a context-full handoff (app/zwischenstand.py)
    finds its way back to the SAME entry instead of creating a new one on
    every restart.

    Extracted from the route because the scheduler (6.7) takes the same path —
    errors come as ``HTTPException``: the route passes them through, the
    scheduler catches them and tries again on the next pass.

    ``ordner`` are the folders picked for this run: in the start window, or
    by the chat that sends it off (``chat_run_folders``). They win over the
    agent's own — the same way the window's model wins over the one in the
    front matter. The scheduler passes none and the agent's folders apply.

    ``own_folder`` is the one of ``ordner`` that is the sending chat's own
    folder (``chat_run_folders``). The run works in it like in any of its
    folders; it is named apart in the prompt and gets no folder notes,
    because the program made it and the user shared nothing there.

    ``eltern_id`` is the run that asked for this one, when a run did. It is
    what lets ``start_job`` work inside a job at all: a run an agent asks for
    is not a new assignment but a PART of the one its parent was given. It
    also carries the chain —
    the panel shows who started whom, and cancelling a run walks down it.

    ``chat_id`` is the chat whose ``start_job`` this is. A run another run
    started, and the continuation of a run that handed its work on, take the
    chat of the run they carry on (``_work_of``) — so the report, a question
    and the stop of a deleted chat reach every part of the work.

    ``ask_in_chat`` is set for a run the chat MODEL sent off (``start_job``
    in a chat) and for nothing else: its calls are judged by the chat's mode
    and rules, and a call the chat would ask about is asked about in that
    chat (``_auftragslauf``). A run started by hand, by a schedule, by
    another run or as a continuation keeps the agent's own mode, where a
    call that would be asked about is refused.

    ``images`` are the pictures the chat model handed over with
    ``start_job``, already read (``app/task_images.py``). They travel in the
    run's first message — as pictures where its model can see, as a line per
    picture where it cannot.
    """
    # How many helpers may run at once holds where a run is made, whoever
    # asked for it. A continuation is exempt: it carries on work whose run
    # has just ended, and refusing it would drop that work.
    if helper.is_helper(agent.name) and cronjob_id is None:
        reason = helper.refusal(repositories)
        if reason:
            raise HTTPException(status.HTTP_409_CONFLICT, reason)
    # The run the work began with, looked up once: the folders below and the
    # stop note further down both read it.
    origin = None
    if chat_id is None:
        chat_id, origin = _work_of(repositories, eltern_id=eltern_id, cronjob_id=cronjob_id)
        # A continuation of the work a chat handed off goes on in that chat's
        # folders — as they stand now, the way a new start would get them. A
        # run under another run, and its continuation, keep the agent's own.
        if ordner is None and origin is not None and origin.chat_id and not origin.eltern_id:
            chat = repositories.chats.holen(origin.chat_id)
            if chat is not None:
                ordner, own_folder = chat_run_folders(config.datenverzeichnis, chat, agent)
    # An agent that names tools has to name ones that exist here. Left
    # unchecked, a typo turns the run into a different one without a word:
    # the offer comes out empty or half, and the model works with fewer
    # tools than the agent intended (or with none of them). Measured against
    # everything this run could resolve — the built-ins of this program and
    # the tools a configured server declares — never against the running
    # offer alone: a tool of a server that is set up but stopped, or one
    # that is merely switched off, is somebody's configuration and not a
    # mistake. Where a configured server declares nothing, the space is open
    # and nothing is refused (``known_names()`` says so with ``None``). A run
    # with an EMPTY list is untouched: `[]` is a deliberate "no tools".
    #
    # Asked FIRST, before this run writes anything — a note file into every
    # folder it was given, the shelf folder onto the disk: an agent file with
    # one typo in it must not leave files behind on a start that never was.
    if registry is not None and agent.werkzeuge:
        bekannt = registry.known_names()
        unbekannt = (
            []
            if bekannt is None
            else sorted(n for n in agent.werkzeuge if n not in bekannt)
        )
        if unbekannt:
            raise Refusal(
                400,
                "fehler.werkzeug_unbekannt",
                sprache,
                namen=", ".join(unbekannt),
                agent=agent.name,
            )

    # The start window beats the file; without a pick the agent's own folders
    # stand. These are the shares the file tools may reach in this run.
    ordner_effektiv = run_folders(ordner, agent)
    # And this is where an agent's own folders get their exe.md. They come
    # out of the front matter of an agent file and never pass through
    # arbeitsordnerpruefung.pruefen(), so hanging the creation off the chat's
    # sharing route alone would leave exactly the folders agents work in
    # without one. Nothing happens where a file is already there. The
    # sending chat's own folder gets none, as it gets none in the chat.
    ordnerwissen.anlegen(
        [o for o in ordner_effektiv if o != own_folder], config.datenverzeichnis
    )
    # And the shelf, always — after the note files, so the shelf does not
    # get one: it is the place agents PUT things, not a folder somebody
    # keeps notes about.
    #
    # An agent could deliver onto the dock (``deliver_file``) but not look
    # inside it: the file tools check against the run's folders, and the
    # dock was never among them. So the programme showed a chosen folder
    # with a button to move it, and the agent it belongs to could not get
    # in.
    #
    # Three limits, and each of them is why this reads as it does:
    #
    #   * The dock folder ITSELF, never the directory above it — that one
    #     holds chats, keys and the configuration.
    #   * On the RUN, not in the agent file. A shipped agent file must never
    #     carry a path from this machine.
    #   * Only for a job. The dock is where agents put things; a chat has a
    #     shelf of its own.
    #
    # Asked for by name rather than written down: ``ort()`` answers with the
    # place the dock is ACTUALLY kept, so a folder somebody moved is still
    # the one the agent may read. A hardcoded path would be this machine's.
    #
    # And it is MADE if it is not there yet. A share whose folder does not
    # exist is refused by the file tools themselves ("The shared folder …
    # no longer exists"), so an untouched installation — where the shelf is
    # only created by the first delivery — would hand every run a share it
    # cannot use. A folder that cannot be made (a moved location on a drive
    # that is not plugged in) is not worth failing a run over: the share is
    # simply refused later, exactly as it is today.
    #
    # The picture folder rides along the same way, after the dock: a run is
    # handed a picture by its path, and draws its own into it.
    dock, image_folder = dokumentablage.program_folders(config)
    # Whether the program added it — and not the start window or the agent
    # file, which share it like any other folder. Only an added dock is
    # named apart in the prompt and kept out of the folder notes: it is the
    # program's place for handed-over files, not a folder the user shared.
    dock_added = dock not in ordner_effektiv
    if dock_added:
        ordner_effektiv.append(dock)
    images_added = image_folder not in ordner_effektiv
    if images_added:
        ordner_effektiv.append(image_folder)
    # A schedule that watches for a goal lends this run the `goal` tool, on
    # top of whatever its agent's own ``tools:`` names. The first build refused such an entry at creation time — "pick an
    # agent that may call it" — which taught the user about a wiring detail
    # instead of getting the wiring right. The entry IS the instruction to
    # report, so an agent list that leaves the tool out cannot have meant
    # "and never report this goal either".
    #
    # Done by widening the run's OWN copy of the agent's list, at this one
    # place, rather than by an exception in each gate the call passes. There
    # are three of them — whether the run uses tools at all, the list handed
    # to the model (app/tools/registry.py), and the execution gate that
    # checks the same list again at call time (app/berechtigungen.py, Hole
    # B). An exception in the second alone offers a tool that the third then
    # refuses.
    #
    # What it does NOT override: a tool switched off in the tools window,
    # and an agent's own ``permissions:`` saying ``goal: nein``. Both are
    # somebody's deliberate no, and neither is this schedule's to overrule.
    # An agent that names tools has to name ones that exist here. Left
    # unchecked, a typo turns the run into a different one without a word:
    # the offer comes out empty or half, and the model works with fewer
    # tools than the agent intended (or with none of them). Measured against
    # everything this run could resolve — built-ins and the tools a
    # configured server declares — never against the running offer alone:
    # a tool of a server that is set up but stopped is somebody's
    # configuration, not a mistake. A run with an EMPTY list is untouched:
    # `[]` is a deliberate "no tools" and stays one.
    zieleintrag = repositories.cronjobs.holen(cronjob_id) if cronjob_id else None
    # What goes on that list is not written out here: it is the same list the
    # offer, the settings window and the tools window read
    # (app/tools/registry.py, EVER_OFFERED), and each entry says whether a
    # run is widened for it. The goal is only where there is a goal to
    # report — which only a schedule's run has; a run that reports nothing
    # has no use for the tool that reports.
    agent = widen_tools(agent, hat_ziel=zieleintrag is not None and bool(zieleintrag.ziel))
    # And the shelf, on the same argument and for every run rather than for a
    # schedule's. The dock is the way OUT of a job — the one place a run can
    # put something where a person will find it — and an agent that named its
    # tools without it delivers into a folder nobody opens. The shipped
    # research agent is exactly that case: five tools, none of them the
    # shelf, and a `write_file` that makes the miss look like a choice.
    #
    # So it is not a capability to switch on per agent, it is the exit. Same
    # three limits as above: a widened copy for THIS run only, the tools
    # window's off-switch still holds, and an agent's own
    # ``permissions: deliver_file: nein`` is still a deliberate no.
    #
    # An EMPTY list is the one case this must not touch. Written out, `[]`
    # is somebody saying "none of them" on purpose — and widening it would
    # not merely add a tool, it would turn the whole run into one that uses
    # tools at all (``benutzt_werkzeuge`` right below reads exactly that).
    if (
        agent.werkzeuge
        and ablage_werkzeug.WERKZEUG_NAME not in agent.werkzeuge
    ):
        agent = dataclasses.replace(
            agent, werkzeuge=[*agent.werkzeuge, ablage_werkzeug.WERKZEUG_NAME]
        )
    # The clock is widened into every run, the goal only into a schedule's
    # (both in the loop above). An agent that named its tools left the clock
    # out of a list it wrote before there was such a tool, and a run is
    # where the time matters most: nothing else in the request names a
    # minute any more (app/grundprompt.environment_block carries the date
    # and the zone), so without it "in ten minutes" and "how long since"
    # would be guesses — and a run a schedule fired is asked exactly that
    # (app/cronablauf.py).
    # A helper works with its chat's tools: what the chat switched off, the
    # helper does not get either — the goal and the shelf added above
    # included. Narrowed here, last, where the chat is known for a fresh
    # start and a continuation alike; the run itself applies only the
    # global off-list.
    if helper.is_helper(agent.name) and chat_id and agent.werkzeuge:
        chat_off = werkzeugwahl.abgeschaltete(repositories, chat=chat_id)
        agent = dataclasses.replace(
            agent, werkzeuge=[name for name in agent.werkzeuge if name not in chat_off]
        )
    # tools: left out entirely means every approved tool, an explicit
    # [] means none — only the second one is "this agent has no use for
    # tool calls" for the purposes below.
    benutzt_werkzeuge = agent.werkzeuge != []
    # And whether this run would really be GIVEN any — the two house-wide
    # conditions on top of the agent's own list, the same three
    # ``werkzeuge_aktiv`` reads further down minus the capability itself.
    # This is the question the model choice below has to ask, and it is
    # narrower than ``benutzt_werkzeuge`` on purpose: with tools switched
    # off house-wide there are no tools to lose, and no reason to send a
    # run somewhere other than where the field points.
    werkzeuge_moeglich = bool(
        registry is not None and config.features.mcp and benutzt_werkzeuge
    )

    # Which model runs this, in the order the two remaining places of choice
    # stand:
    #
    #   1. ``endpoint_id`` — the hand pick in the start window. The exception
    #      for THIS one run, stored nowhere.
    #   2. The one field (app/agentenmodellwahl.py) — what everything that
    #      runs without a pick uses. It answers with ONE id, whichever of its
    #      three kinds it holds: the slot's endpoint id, ``runner`` for the
    #      main server's loaded model, or a cloud ``endpunkt:modell``.
    #   3. The main model — and where it is not there, the next reachable
    #      LOCAL endpoint.
    #
    # All three kinds resolve through the same ``aufloesen`` below, so there
    # is no second path for any of them.
    #
    # The order itself lives in `agentenmodellwahl.lauf_kennung`: the cron
    # pre-check asks the same question before it calls a due schedule ready
    # (app/cronablauf.py), and an order this size written down twice is how
    # the two answers drift apart — one of them saying "ready" for a run the
    # other refuses.
    #
    # The agent file's own ``model:`` used to sit between 1 and 3. It is
    # retired (app/agenten.py): a stored model per agent is a third place
    # that answers "which one counts now", and it binds an agent to one
    # machine's hardware.
    endpoint_id = agentenmodellwahl.lauf_kennung(
        repositories,
        discovery,
        slot_id=agentenserver.ENDPUNKT_ID,
        endpoint_id=endpoint_id,
        werkzeuge=werkzeuge_moeglich,
    )
    # What is left to do here is to report what that order came back with.
    # A run with no model at all is the one case the choice cannot answer:
    # nothing is chosen, the main server is down and no local endpoint
    # answers either.
    if not endpoint_id:
        raise Refusal(400, "fehler.kein_modell_verfuegbar", sprache)
    gefunden = discovery.aufloesen(endpoint_id)
    if gefunden is None:
        raise Refusal(404, "fehler.modell_nicht_erreichbar", sprache, name=endpoint_id)
    zustand, modellname = gefunden
    if not zustand.erreichbar:
        raise Refusal(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "fehler.modell_nicht_erreichbar",
            sprache,
            name=zustand.endpunkt.name,
        )

    auftrag = repositories.auftraege.erstellen(
        user_id=user_id, agent=agent.name, auftrag=task, endpoint_id=endpoint_id,
        # Carried onto the row itself so a hard restart mid-run
        # can find its way back to the same chain — the in-memory value
        # this closure holds does not survive that kind of restart.
        cronjob_id=cronjob_id,
        eltern_id=eltern_id,
        chat_id=chat_id,
    )
    # The window hears about this rather than finding it on its next tick
    # (app/ereignisstrom.py). Not through app/auftragsende.py: that module
    # exists for the rules an ENDING has to keep — once per run, and not at
    # all for a run that handed its work on — and a beginning has none.
    bus.veroeffentlichen_ohne_warten(
        Ereignisse.AUFTRAG_BEGONNEN,
        auftrag_id=auftrag.id,
        agent=auftrag.agent,
        cronjob_id=cronjob_id,
    )

    # What this run will actually offer, worked out before the prompt is
    # built — the prompt needs to know whether file tools are among them to
    # include their usage instructions (dateiwerkzeuge=), the same way a
    # chat already does. Computed once, reused below for anfrage.werkzeuge
    # too instead of asking the registry the same question twice.
    werkzeuge_aktiv = bool(
        registry is not None and config.features.mcp
        and zustand.kann("tool_calls") and benutzt_werkzeuge
    )
    # How long one shell command may run in this job. Same resolution as the
    # token budget right below: the agent head wins outright, then the
    # cascade (global, then the model's own setting) — a job has no chat
    # scope of its own. Resolved before the tool list is built, because the
    # shell's description has to name this very value.
    befehl_zeitgrenze = befehlszeitwahl.sekunden(
        repositories, modell=endpoint_id, agent_wert=agent.befehlssekunden
    )
    # Whether the memory travels with this run — read before the offer:
    # memory_save's description promises only what holds on this side.
    mit_gedaechtnis = gedaechtnis.mitschicken(repositories, zustand)
    genannt: set[str] | None = None
    angeboten_werkzeuge: list[dict] = []
    if werkzeuge_aktiv:
        # A job has no chat scope of its own, so the global off-list applies:
        # switching a tool off is meant to hold for everything, not only for
        # what happens to be typed by hand.
        werkzeugwahl.anwenden(registry, repositories)
        genannt = set(agent.werkzeuge) if agent.werkzeuge is not None else None
        # The chat this run came from, and its picture window: a job draws
        # with the same image model a question in that chat would use, and
        # the description has to say which one that is (one reading, see
        # `bild_werkzeug.fenster_familie`).
        angeboten_werkzeuge = registry.als_openai_werkzeuge(
            nur=genannt, shell_zeitgrenze=befehl_zeitgrenze,
            bild_fenster=lambda: bild_werkzeug.fensterbild(
                repositories, auftrag.chat_id, config
            ),
            # The note tool belongs to a cron entry, so only a run
            # a cron entry started is offered it. A job somebody launched by
            # hand has nothing for it to write to — and unlike `goal`, which
            # any conversation can be given something to report, there is no
            # second meaning it could have outside a schedule.
            cron_notiz_an=cronjob_id is not None,
            # This is the one place a job's tool list is built, and the
            # tools that hand something over read it: deliver_file names
            # the doc folder as its place here, and the painters say their
            # picture stays in the pictures folder — a job has no answer
            # for either to hang on.
            for_job=True,
            # A helper is one level below the chat: a run starts none
            # (app/helper.py).
            helpers=False,
            memory_shown=mit_gedaechtnis,
        )
        # Nothing is filtered out of a job's list any more.
        #
        # start_job's rule was never "not in a job": a run an agent asks for
        # is a part of the assignment its parent was given rather than a new
        # one.
        #
        # ask_user was taken away for a reason that was true and is no
        # longer: a job had no PLACE to put a question. It has one now — the
        # run goes to 'wartet', the question hangs on the run, and it stands
        # in the waiting group until somebody answers. What has NOT been
        # loosened is the confirmation: a job still asks nobody for
        # permission for its tools. This is a question about the work, not a
        # request for a yes.
        #
        # Both are intercepted in the run loop below, the same way the chat
        # intercepts them, minus the window nobody is sitting in front of.
        # A call that reaches the registry with no run holding it open is
        # still refused there.
    angebotene_namen = {w["function"]["name"] for w in angeboten_werkzeuge}
    # An agent can name tools the server ends up offering none of (all
    # filtered out, or all missing from the registry) — the prompt must not
    # tell the model to reach for tools it will never see in its list.
    werkzeuge_im_prompt = werkzeuge_aktiv and bool(angeboten_werkzeuge)
    write_file_angeboten = datei_schreiben.WERKZEUG_NAME in angebotene_namen

    # What this run actually has in hand, on every job — also for an agent
    # whose front matter names no tools at all. The "not available" step
    # below only fires for tools the agent NAMED; an agent without a list
    # whose search server is down would otherwise run with silently nothing
    # and answer from the model's own head, which reads like research and
    # is none. This line makes that visible on the job itself.
    repositories.auftraege.schritt_anlegen(
        auftrag.id,
        "status",
        "Werkzeuge angeboten: "
        + (", ".join(sorted(angebotene_namen)) if angebotene_namen else "keine"),
    )

    # Stacked: global prompt, then agent prompt. A single
    # system message, because not every local server can handle several.
    #
    # Same three layers as in the chat: shipped instructions, the user's
    # prompt, what is known about them — and the agent's prompt on top, since
    # that is what makes this run an agent at all.
    #
    # The folder section is named, not merely announced: a model told folders
    # exist but not which ones only finds the one its shell starts in. The
    # memory rides along under the same switch — a job runs on the same models
    # and sends to the same providers (``mit_gedaechtnis``, read above).
    # The date and the zone in front of the task, not in the system text:
    # the same road the chat takes (app/verlaufsbau.py), so the system text
    # is the same bytes from one build to the next and stays in the server's
    # cache.
    #
    # Unconditional, where the former clock sentence was gated on a tool: a
    # job is built once at its start and then runs for as long as it runs,
    # and a run a SCHEDULE fired is handed the moment the previous one wrote
    # its note (app/cronablauf.py) and asked to work out what has happened
    # since — which it cannot do without knowing which day it is. The minute
    # it asks the clock tool for (app/tools/uhr.py), which every run with
    # tools carries.
    environment_block = grundprompt.environment_block(config.app.timezone)
    # Same rule as the chat (app/api/v1/generierung.py): only when
    # skill_load is actually among this run's own tools — a catalogue
    # without it names doors the agent could never open. No
    # chat scope for the per-model on/off switch either, same reason as
    # everywhere else in this function: a job has none of its own.
    skill_katalog: list[tuple[str, str]] = []
    if skill.LADEN in angebotene_namen and skillwahl.selbst_waehlen(
        repositories, modell=zustand.endpunkt.id
    ):
        vorhanden = skills.skills_laden(*config.skillverzeichnisse)
        skill_katalog = [
            (s.name, s.beschreibung)
            for s in skills.automatische(vorhanden, angebotene_namen)
        ]
    # The same folder notes a chat gets (app/ordnerwissen.py). Without them
    # an agent would be the one run that works inside a folder without ever
    # being told what the user wrote down about it.
    #
    # The folders the user shared — the run's folders without the sending
    # chat's own folder and without the dock and the picture folder the
    # program added. None of them gets an exe.md (see above), so none has
    # notes or a duty to keep any.
    shared_folders = [
        o
        for o in ordner_effektiv
        if o != own_folder
        and not (dock_added and o == dock)
        and not (images_added and o == image_folder)
    ]
    notizen = ordnerwissen.lesen(shared_folders)
    ordnerwissen.sichern(notizen, config.datenverzeichnis)
    ordnerwissen.melden(auftrag.id, notizen)
    # Same sentence for an agent, from the column of the rules that judges
    # its calls: the agent's own — where "asks" is "no", because nobody is
    # there to answer — or, for a run the chat model sent off, the chat's,
    # whose questions are put to the user in that chat (``_ask_in_chat``).
    zugriff = None
    if ordner_effektiv:
        from app import berechtigungen
        from app.berechtigungsregeln import laden as regeln_laden

        zugriff = berechtigungen.zugriffslage(
            "chat" if ask_in_chat else "agent",
            regeln=regeln_laden(getattr(registry, "berechtigungen_pfad", None)),
        )
    model_name, provider_name = grundprompt.model_lines(zustand, modellname)
    grund = grundprompt.bauen(
        werkzeuge=werkzeuge_im_prompt,
        ordner=ordner_effektiv,
        # The sending chat's own folder, named as that chat names it.
        own_folder=own_folder,
        # Named as the place handed-over files are kept, last in the list,
        # and not as a folder the user shared.
        dock=dock if dock_added else None,
        images=image_folder if images_added else None,
        zugriff=zugriff,
        skills=skill_katalog,
        # The names this run has, not a yes: an agent told to reach for
        # search_files it was never given calls it once and is refused.
        dateiwerkzeuge=[n for n in dateiwerkzeuge.NAMEN if n in angebotene_namen],
        # The shell's own sentence, and only with the shell. It used to ride
        # along with "you have tools", so an agent that may read files and
        # nothing else was being told how `cd` behaves between commands it
        # cannot make.
        befehle=shell.WERKZEUG_NAME in angebotene_namen,
        skills_schreiben=skill.SCHREIBEN in angebotene_namen,
        # Only when ask_user is really in this run's list — an agent whose
        # tools leave it out must not be told to reach for something it will
        # never see.
        #
        # What arrives in a job is NOT the chat's paragraph: grundprompt
        # holds that one back whenever an ``agentenlauf`` is passed, and the
        # run gets its own wording instead. The two disagree on purpose —
        # a chat may ask about taste, a run at three in the morning may not.
        fragen=frage_werkzeug.WERKZEUG_NAME in angebotene_namen,
        # Same reading the memory switch uses (app/gedaechtnis.py).
        lokal=getattr(zustand.endpunkt, "group", None) == "local",
        kann=grundprompt.faehigkeiten(angebotene_namen),
        suche=grundprompt.hat_suche(angebotene_namen),
        # No anhaenge=: a job has no chat and therefore no attachments. And
        # no agenten= either — that block talks about a conversation staying
        # usable, and there is none here; what a job needs told about handing
        # work on rides in ``agentenlauf`` below, in its own words.
        gedaechtnis_schreiben=memory.WERKZEUG_NAME in angebotene_namen,
        ordnerwissen=ordnerwissen.fuer_prompt(notizen),
        # Same gate as the chat: the duty names write_file and edit_file, so
        # both have to be in this run's own list before it is stated.
        ordnerwissen_pflegen=bool(shared_folders)
        and {datei_schreiben.WERKZEUG_NAME, datei_aendern.WERKZEUG_NAME}
        <= angebotene_namen,
        # The part a chat never sees. It takes back what UMFANG and WERKZEUGE
        # say about asking for PERMISSION — there is no confirmation prompt in
        # a job, except in one the chat model sent off, which asks in its
        # chat (`ask_in_chat`) — and it names the run's own budget instead of
        # calling it "limited", since both numbers are known right here.
        # Whether the run may ask a QUESTION is a different matter and
        # travels as `fragen`.
        agentenlauf=grundprompt.Agentenlauf(
            runden=agent.runden,
            minuten=agent.minuten,
            befehle=shell.WERKZEUG_NAME in angebotene_namen,
            ablegen=ablage_werkzeug.WERKZEUG_NAME in angebotene_namen,
            beauftragen=auftrag_werkzeug.WERKZEUG_NAME in angebotene_namen,
            fragen=frage_werkzeug.WERKZEUG_NAME in angebotene_namen,
            ask_in_chat=ask_in_chat,
        ),
        # The two lines naming the model and its endpoint, and what the
        # three sections that depend on the run need: this run's tools, and
        # whether the memory travels with it.
        model_name=model_name,
        provider_name=provider_name,
        tool_names=angebotene_namen,
        memory_travels=mit_gedaechtnis,
    )
    basis = gedaechtnis.anhaengen(
        grundprompt.mit_benutzerprompt(grund, config.system_prompt_lesen()),
        config.memory_lesen() if mit_gedaechtnis else "",
    )
    system_teile = [teil for teil in (basis, agent.prompt) if teil]
    nachrichten = [ChatNachricht(role="system", content="\n\n".join(system_teile))]
    # Work carried on after its previous run was stopped: the model is told
    # so in front of the task, the way a chat turn after a stopped reply is
    # (app/stop_note.py) — in this request only; the task as stored stays
    # as it was given.
    task_text = (
        stop_note.with_stop_note(
            task,
            stop_note.previous_reply_stopped(
                previous_run_of_work(repositories, origin, cronjob_id, auftrag.id)
            ),
        )
        or task
    )
    nachrichten.append(
        _first_message(environment_block, task_text, images, vision=zustand.kann("vision"))
    )

    # Its own budget rather than the chat's (decision: jobs get a budget of
    # their own) — same cascade a chat reads, with the agent head allowed to
    # override it outright. ``None`` means nothing is set: "Auto".
    eingestellte_grenze = auftragtokenwahl.aufgeloest(
        repositories,
        modell=endpoint_id,
        agent_wert=agent.max_tokens,
    )
    assert zustand.context_tokens is not None, (
        "a reachable endpoint always has a resolved window (app/fenstergroesse.py)"
    )
    anfrage = Generierungsanfrage(
        nachrichten=nachrichten,
        # The same one calculation the chat path uses: what is set wins,
        # otherwise the largest number that still fits this model's window
        # once this request's own input is taken off it
        # (app/antwortgrenze.py). The tools are not in the estimate yet —
        # they are attached below, after the request exists — and an estimate
        # that falls short is what the lowering in app/kontextvoll.py is for.
        max_tokens=antwortgrenze.aufloesen(
            eingestellte_grenze,
            antwortgrenze.geltender_deckel(zustand, modellname),
            zustand.context_tokens or 0,
            antwortgrenze.eingabe_schaetzen(nachrichten),
            anthropic=antwortgrenze.anthropic_draht(zustand),
        ),
        modell=modellname,
    )

    # How long the model may think first, resolved through the same two
    # layers the budget above uses. Left unsaid by both, nothing goes along
    # and the server keeps its own habit — a job that never asked for a
    # thinking length must not start sending one.
    denklaenge = auftragdenklaengewahl.aufgeloest(
        repositories, modell=endpoint_id, agent_wert=agent.denklaenge
    )
    if denklaenge is not None:
        anfrage.parameter["reasoning_budget"] = denklaenge
    # A thinking length only travels where the knob is open for THIS model —
    # the same decision the chat and the fold ask for. The
    # stored value stays untouched in the agent file and in the settings.
    anfrage.parameter = parameter.ohne_gesperrte_denklaenge(
        anfrage.parameter,
        freigegeben=denklaenge_erlaubt(zustand, modellname, repositories.einstellungen),
    )

    if werkzeuge_aktiv:
        # Only the intersection of the agent's list and the registry. Whatever
        # the agent names but the server doesn't know is made visible instead
        # of silently swallowed — otherwise you'd go hunting for the bug in
        # the model. tools: left out means every approved tool (nur=None,
        # same as a chat) — genannt stays None and nothing can be "missing"
        # from a list the agent never wrote.
        anfrage.werkzeuge = angeboten_werkzeuge
        # What the agent named and this run does not get — measured against
        # what the run is really OFFERED (the list right above), not against
        # every name the program knows: `draw_image` at a picture window that
        # cannot draw from text is known here and still not offered, and a
        # run that starts without it and says nothing leaves nobody able to
        # tell why it never drew.
        #
        # Two kinds are taken out, because neither is a tool the agent named
        # and failed to get: the names the run widened its OWN list with
        # (the clock and the goal, app/tools/registry.py `EVER_OFFERED`, and
        # the shelf added a few lines up) — no agent wrote those — and the
        # ones switched off on purpose, which every run lacks by
        # configuration and never by a typo (the same reason `known_names`
        # counts them as known, app/tools/registry.py).
        fehlend = (
            genannt - angebotene_namen - registry.abgeschaltet
            if genannt is not None
            else set()
        )
        if fehlend:
            repositories.auftraege.schritt_anlegen(
                auftrag.id,
                "status",
                f"Werkzeuge nicht verfügbar: {', '.join(sorted(fehlend))}",
            )

    lauf = generierungen.starten(
        # chat_id carries the job id here — the run management doesn't ask
        # what's behind it, and the ids cannot collide.
        chat_id=auftrag.id,
        endpoint_id=endpoint_id,
        arbeit=_auftragslauf(
            auftrag_id=auftrag.id,
            endpoint_id=endpoint_id,
            agent=agent,
            anfrage=anfrage,
            zustand=zustand,
            registry=registry,
            repositories=repositories,
            generierungen=generierungen,
            discovery=discovery,
            ordner=ordner_effektiv,
            sprache=sprache,
            config=config,
            task=task,
            user_id=user_id,
            cronjob_id=cronjob_id,
            write_file_angeboten=write_file_angeboten,
            befehl_zeitgrenze=befehl_zeitgrenze,
            # What the user set, if anything — the run works its own ceiling
            # out from it again for every round (app/antwortgrenze.py).
            eingestellte_grenze=eingestellte_grenze,
            chat_id=auftrag.chat_id,
            ask_in_chat=ask_in_chat,
        ),
        an_verbindung_gebunden=False,
    )
    repositories.auftraege.generation_verknuepfen(auftrag.id, lauf.id)

    return repositories.auftraege.holen(auftrag.id)


def _frage_von(auftrag) -> dict | None:
    """The question standing on a run, or nothing.

    A row written by an older version, or one edited by hand, must not take
    the route down: an unreadable question is the same as no question.
    """
    if not auftrag.frage:
        return None
    try:
        wert = json.loads(auftrag.frage)
    except (TypeError, ValueError):
        return None
    return wert if isinstance(wert, dict) else None


# A 404 saying the picked model plainly does not exist — the wordings
# providers commonly use for it, plus OpenAI's "not a chat model" for a
# completion-only endpoint fed a model built for something else, which none
# of the common wordings cover. A retry can never fix either: the model
# named in the request stays what it is on every attempt.
_MODELL_NICHT_GEFUNDEN_MUSTER = (
    "is not a valid model", "invalid model", "model not found", "model_not_found",
    "does not exist", "no such model", "unknown model", "unsupported model",
    "no endpoints found that support tool use", "not a chat model",
)


def _modell_nicht_gefunden(fehler: ProviderFehler) -> bool:
    """Whether a 404 is this one deterministic case rather than an ordinary
    outage — the run ends here instead of spending five attempts and an
    outage restart on a mistake no attempt can correct."""
    if fehler.status != 404:
        return False
    text = (fehler.rohtext or str(fehler)).lower()
    return any(muster in text for muster in _MODELL_NICHT_GEFUNDEN_MUSTER)


def _kettendaten(repositories: Repositories, auftrag) -> tuple[str, str | None]:
    """The two things a route with a single run in hand reads off its cron
    entry: which WORK it belongs to (``werk_von``), and, when the entry
    marks a restart chain, the chain's own original task
    (app/zwischenstand.py ``basisaufgabe``) instead of this run's own
    wrapped restart prompt. Read once for both — the list route below asks
    the table once for every run instead."""
    eintrag = (
        repositories.cronjobs.holen(auftrag.cronjob_id) if auftrag.cronjob_id else None
    )
    return werk_von(auftrag, eintrag), (eintrag.basisaufgabe if eintrag else None)


@router.get(
    "/jobs/laufmodell",
    response_model=LaufmodellAntwort,
    summary="Which model a job would take",
)
def laufmodell(
    repositories: Repositories = Depends(hole_repositories),
    discovery: Discovery = Depends(hole_discovery),
    sprache: str = Depends(hole_sprache),
    endpoint_id: str | None = None,
    werkzeuge: bool = False,
) -> LaufmodellAntwort:
    """What a run started now would land on — asked by the start window.

    The answer for the row the window stands on, resolved by the same call
    the start itself makes (`agentenmodellwahl.lauf_kennung`). The window used
    to work this out for itself, from the reachable list and its own reading
    of the tool rule, and the two could part company: the preview named an
    endpoint the run then never went to — a paid provider among them.
    A preview that is not the same answer as the run's is not a
    preview, it is a second opinion.

    ``endpoint_id`` is the row's pick (one of the two servers), ``werkzeuge``
    whether this agent works through tools at all. Both are read exactly as
    the start reads them, so nothing here can drift from there.

    Both fields of the answer are empty when no model is reachable: the
    window shows the run as unstartable in that case, the same way the start
    refuses it with 400.

    ``denklaenge`` rides along for the agent MASK, which has no model pick of
    its own (the model of a run is said in the model window's field): the
    thinking-length row for the model named here, out of the same
    `unterstuetzte()` the model window draws its slider from. Handed out
    rather than worked out in the mask, so the field there is locked by the
    same two conditions and names the same reason.
    """
    kennung = agentenmodellwahl.lauf_kennung(
        repositories,
        discovery,
        slot_id=agentenserver.ENDPUNKT_ID,
        endpoint_id=endpoint_id,
        werkzeuge=werkzeuge,
    )
    if not kennung:
        return LaufmodellAntwort()
    gefunden = discovery.aufloesen(kennung)
    # What the window puts under the row is the display name and not the
    # reported one: a local server reports its model as the full path it was
    # started with, and that path carries the user's folder structure into
    # the window (app/discovery.py `anzeigename`).
    reihe = None
    if gefunden:
        zustand, modell = gefunden
        reihe = next(
            (
                p
                for p in zustand.als_dict(
                    modell,
                    sprache,
                    # A stage this model has already refused can leave it
                    # without any thinking at all — the same reading the model
                    # window gets, so the mask cannot lock where the slider
                    # does not, or the other way round. Looked up under
                    # ``refusal_key``, the id the model list reads them under:
                    # the id a run books with may name a catalogue server
                    # alone, and would be a second list for the same model.
                    abgelehnt=denkablehnung.gemerkt(
                        repositories.einstellungen, refusal_key(zustand, modell)
                    ),
                )["parameter"]
                if p["name"] == "reasoning_budget"
            ),
            None,
        )
    return LaufmodellAntwort(
        endpoint_id=kennung,
        name=(gefunden[0].anzeigename if gefunden else None) or kennung,
        denklaenge=reihe,
    )


@router.get("/jobs", response_model=list[AuftragAntwort], summary="List jobs")
def auftraege_auflisten(
    repositories: Repositories = Depends(hole_repositories),
    user_id: str = Depends(hole_benutzer_id),
    limit: int = 100,
    offset: int = 0,
) -> list[AuftragAntwort]:
    eintraege = repositories.auftraege.auflisten(
        user_id=user_id, limit=limit, offset=offset
    )
    # One pass over the cron table rather than a lookup per run: this list is
    # fetched again on every job announcement of the live line — each context
    # reading of a running job among them — and a hundred rows would
    # otherwise be a hundred queries a fetch.
    termine = {termin.id: termin for termin in repositories.cronjobs.auflisten()}
    # The same for each run's context reading: one query for the page.
    kontexte = repositories.auftraege.letzte_kontextstaende([a.id for a in eintraege])
    # And the step a running agent is on, for its row in the chat.
    werkzeuge = repositories.auftraege.last_tool_calls(
        [a.id for a in eintraege if a.zustand in ("laeuft", "wartet")]
    )
    return [
        AuftragAntwort.aus(
            auftrag,
            werk=werk_von(auftrag, eintrag := termine.get(auftrag.cronjob_id or "")),
            urspruenglicher_text=eintrag.basisaufgabe if eintrag else None,
            kontext=kontexte.get(auftrag.id),
            last_tool=werkzeuge.get(auftrag.id),
        )
        for auftrag in eintraege
    ]


@router.get(
    "/jobs/{auftrag_id}",
    response_model=AuftragDetail,
    summary="One job with its log",
)
def auftrag_holen(
    auftrag_id: str,
    repositories: Repositories = Depends(hole_repositories),
    user_id: str = Depends(hole_benutzer_id),
    sprache: str = Depends(hole_sprache),
) -> AuftragDetail:
    auftrag = repositories.auftraege.holen(auftrag_id, user_id=user_id)
    if auftrag is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, t("fehler.auftrag_nicht_gefunden", sprache)
        )
    werk, urspruenglicher_text = _kettendaten(repositories, auftrag)
    return AuftragDetail.aus_mit_schritten(
        auftrag,
        repositories.auftraege.schritte(auftrag.id),
        werk=werk,
        urspruenglicher_text=urspruenglicher_text,
    )


@router.post(
    "/jobs/{auftrag_id}/cancel",
    response_model=AuftragAntwort,
    summary="Cancel a job",
)
def auftrag_abbrechen(
    auftrag_id: str,
    repositories: Repositories = Depends(hole_repositories),
    generierungen: Generierungsverwaltung = Depends(hole_generierungen),
    user_id: str = Depends(hole_benutzer_id),
    sprache: str = Depends(hole_sprache),
) -> AuftragAntwort:
    auftrag = repositories.auftraege.holen(auftrag_id, user_id=user_id)
    if auftrag is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, t("fehler.auftrag_nicht_gefunden", sprache)
        )

    # Downwards first. A run an agent started is a part of this assignment,
    # so stopping the assignment stops it too — otherwise a branch nobody
    # can see keeps working for a run that is already over. Depth-first and
    # link by link, because no depth is fixed: each child stops its own
    # children on the way.
    for kind in repositories.auftraege.kinder(auftrag.id):
        if kind.zustand in ENDZUSTAENDE:
            continue
        _lauf_abbrechen(repositories, generierungen, kind)

    # The stop button names its own reason, so a stop that follows it — the
    # chat deleted a moment later — cannot rewrite who stopped the run.
    if auftrag.generation_id and generierungen.abbrechen(
        auftrag.generation_id, reason="benutzer_abbruch"
    ):
        # The run is alive: it gets the signal and records state and reason
        # itself once it has stopped — exactly like the stop button in chat.
        werk, urspruenglicher_text = _kettendaten(repositories, auftrag)
        return AuftragAntwort.aus(auftrag, werk=werk, urspruenglicher_text=urspruenglicher_text)

    if auftrag.zustand not in ENDZUSTAENDE:
        # No live run (waiting/interrupted): record it directly.
        auftrag = auftragsende.beenden(
            repositories, auftrag.id, "abgebrochen", ende_grund="benutzer_abbruch"
        )
    werk, urspruenglicher_text = _kettendaten(repositories, auftrag)
    return AuftragAntwort.aus(auftrag, werk=werk, urspruenglicher_text=urspruenglicher_text)


def stop_jobs_of_chat(
    repositories: Repositories, generierungen: Generierungsverwaltung, chat_id: str
) -> int:
    """Stops every job started from a chat that is being deleted, and every
    run under it. Returns how many were still open.

    The same two ways as the cancel route: a live run gets the signal and
    writes its own ending, a waiting one is recorded here — as stopped with
    its chat. What a run has already delivered stays where it was put.
    """
    open_jobs = repositories.auftraege.open_for_chat(chat_id)
    for auftrag in open_jobs:
        _lauf_abbrechen(repositories, generierungen, auftrag, reason="chat_deleted")
    # And the work that was handed on and has not picked up again yet: its
    # continuation waits as an active entry naming the run the work began
    # with (``ursprung_id``, app/zwischenstand.py), and it would start a
    # minute from now for a chat that is gone. Switched off, not deleted:
    # the runs that already came from the chain still name it as their work.
    chat_job_ids = set(repositories.auftraege.ids_for_chat(chat_id))
    continuations = [
        entry.id
        for entry in repositories.cronjobs.aktive()
        if entry.ursprung_id in chat_job_ids
    ]
    for entry_id in continuations:
        repositories.cronjobs.aktiv_setzen(entry_id, False)
    if open_jobs or continuations:
        log.info(
            "Chat %s deleted: %d job(s) stopped with it (%s), %d continuation(s) switched off",
            chat_id,
            len(open_jobs),
            ", ".join(auftrag.id for auftrag in open_jobs),
            len(continuations),
            extra={"ereignis": "auftrag_mit_chat_gestoppt", "chat": chat_id},
        )
    return len(open_jobs)


def _lauf_abbrechen(
    repositories: Repositories,
    generierungen: Generierungsverwaltung,
    auftrag,
    *,
    reason: str = "eltern_abbruch",
) -> None:
    """Stops one run and everything it started, without going through the
    route again — the route answers for the run somebody clicked on, this
    walks the branch under it.

    The two ways a run ends are the route's own two: a live run gets the
    signal and writes its own ending, a waiting or interrupted one is
    recorded here.
    """
    for kind in repositories.auftraege.kinder(auftrag.id):
        if kind.zustand not in ENDZUSTAENDE:
            _lauf_abbrechen(repositories, generierungen, kind, reason=reason)
    if auftrag.generation_id and generierungen.abbrechen(
        auftrag.generation_id, reason=reason
    ):
        return
    # Read again: a run above this one may have ended it a moment ago on the
    # same walk.
    current = repositories.auftraege.holen(auftrag.id)
    if current is not None and current.zustand not in ENDZUSTAENDE:
        auftragsende.beenden(
            repositories, auftrag.id, "abgebrochen", ende_grund=reason
        )


@router.post(
    "/jobs/{auftrag_id}/answer",
    response_model=AuftragAntwort,
    summary="Answer a job's question",
)
def auftrag_beantworten(
    auftrag_id: str,
    daten: AuftragAntwortSchreiben,
    request: Request,
    repositories: Repositories = Depends(hole_repositories),
    generierungen: Generierungsverwaltung = Depends(hole_generierungen),
    user_id: str = Depends(hole_benutzer_id),
    sprache: str = Depends(hole_sprache),
) -> AuftragAntwort:
    """The answer to a question a run asked with ``ask_user``.

    ONE way in for both cases, because the person answering cannot see which
    of them they are in — and should not have to:

      * **The run is alive.** The answer goes into the open call, on the same
        future the chat uses, and the run carries on where it stopped. This
        is the normal case.
      * **The run is gone.** A service restart leaves the row and its
        question standing but takes the process with it, so there is no call
        left to hand anything to. The answer is not thrown away for that: the
        run is carried on from its own status, with the question and this
        answer folded into the assignment
        (``app/zwischenstand.py``). It comes back as a fresh run a minute
        later, knowing what it asked and what it was told.

    Refused when there is nothing to answer — a run that is not waiting, or
    one whose question has already been taken.
    """
    auftrag = repositories.auftraege.holen(auftrag_id, user_id=user_id)
    if auftrag is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, t("fehler.auftrag_nicht_gefunden", sprache)
        )
    frage = _frage_von(auftrag)
    if auftrag.zustand != "wartet" or frage is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, t("fehler.auftrag_fragt_nicht", sprache)
        )
    antwort = daten.antwort.strip()
    if not antwort:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            t("fehler.auftrag_antwort_leer", sprache),
        )

    aufruf_id = str(frage.get("aufruf_id") or "")
    if auftrag.generation_id and generierungen.bestaetigen(
        auftrag.generation_id, aufruf_id, True, antwort
    ):
        # Delivered: the run itself writes the state back and clears the
        # question as it goes on (app/auftragsfrage.py).
        werk, urspruenglicher_text = _kettendaten(repositories, auftrag)
        return AuftragAntwort.aus(auftrag, werk=werk, urspruenglicher_text=urspruenglicher_text)

    # Nobody is holding the call open any more. The row ends honestly — a
    # restart is what cut it — and the work is picked up again from its own
    # status, which is what this answer is for.
    repositories.auftraege.frage_setzen(auftrag_id, None)
    fortgesetzt = zwischenstand.fortsetzung_planen(
        request.app.state.config,
        repositories,
        auftrag,
        zusatz=(
            f"You asked the user: {frage.get('frage') or ''}\n"
            f"They answered: {antwort}"
        ),
    )
    # Two different endings, and the difference is not cosmetic: a run whose
    # work was handed on is not news (``weitergereicht``), so it raises no
    # notice and does not stand in the reports list as a second row about the
    # same piece of work. One whose continuation was refused — the restart
    # ceiling — really did end here, and says so with the reason it ended for.
    auftrag = auftragsende.beenden(
        repositories,
        auftrag_id,
        "unterbrochen",
        ende_grund=(
            "frage_beantwortet" if fortgesetzt else auftragsende.GRUND_DIENST_NEUSTART
        ),
    )
    werk, urspruenglicher_text = _kettendaten(repositories, auftrag)
    return AuftragAntwort.aus(auftrag, werk=werk, urspruenglicher_text=urspruenglicher_text)


@router.delete(
    "/jobs/{auftrag_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    # The 204 trio, as with chat and agent deletion: explicitly no response
    # body, otherwise FastAPI rejects the route at startup.
    response_class=Response,
    response_model=None,
    summary="Delete a job",
)
def auftrag_loeschen(
    auftrag_id: str,
    repositories: Repositories = Depends(hole_repositories),
    generierungen: Generierungsverwaltung = Depends(hole_generierungen),
    user_id: str = Depends(hole_benutzer_id),
    sprache: str = Depends(hole_sprache),
) -> None:
    auftrag = repositories.auftraege.holen(auftrag_id, user_id=user_id)
    if auftrag is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, t("fehler.auftrag_nicht_gefunden", sprache)
        )
    # A still-living run is stopped first — gone means gone, not
    # "keeps running headless". On completion the run notices itself that
    # its job has disappeared and writes nothing more.
    if auftrag.generation_id:
        generierungen.abbrechen(auftrag.generation_id)
    repositories.auftraege.loeschen(auftrag_id, user_id=user_id)


# --- The run itself ---------------------------------------------------------


def _kind_starten(
    *,
    aufruf,
    eltern_id: str,
    config,
    repositories: Repositories,
    discovery: Discovery,
    generierungen: Generierungsverwaltung,
    registry,
    user_id: str,
    sprache: str,
    protokoll,
) -> tuple[str, bool]:
    """A ``start_job`` call from inside a job: the result text, and whether
    it failed.

    The chat shows the task in an editable window before anything starts
    (app/api/v1/generierung.py). A job has nobody in front of one — and needs
    none: what starts here is a PART of the assignment the user already
    confirmed, and it says so by carrying ``eltern_id``. That is the whole of
    what makes this allowed, so it is not optional and not a parameter this
    function would work without.

    The chain is written into the log of BOTH runs, because a branch nobody
    can see is a branch nobody can stop.
    """
    eltern = repositories.auftraege.holen(eltern_id)
    # A helper is one level below the chat: it starts nothing, and a run
    # starts no helper (app/helper.py).
    refused = helper.refused_call(eltern.agent if eltern else None, aufruf.name)
    if refused:
        return refused, True
    try:
        agent_name, task = auftrag_werkzeug.geprueft(aufruf.argumente)
        if not agent_name or helper.is_helper(agent_name):
            raise auftrag_werkzeug.AuftragVerboten(helper.CHAT_ONLY)
        agenten = agenten_laden(*config.agentenverzeichnisse)
        kind_agent = agenten.get(agent_name)
        if kind_agent is None:
            raise auftrag_werkzeug.AuftragVerboten(
                f"No agent named '{agent_name}'. Available: "
                f"{', '.join(sorted(agenten)) or 'none'}."
            )
    except auftrag_werkzeug.AuftragVerboten as fehler:
        return str(fehler), True

    # The child runs on the server its parent runs on. Resolved on its own,
    # it would take whatever the settings name today, and a chain measured
    # against one server would end up on two without anybody seeing it. The
    # tool names no server of its own, so the parent's is the child's.
    #
    # The server, not the model the main server had loaded when the parent
    # started: the parent's row names that one (`runner:<model>`), and handed
    # on as a pick it would ask the main server to load it again, under
    # whatever runs there now.
    geerbt = eltern.endpoint_id if eltern is not None else None
    if geerbt and agentenmodellwahl.ist_hauptmodell(geerbt):
        geerbt = agentenmodellwahl.HAUPTMODELL
    try:
        kind = auftrag_anstossen(
            config=config,
            repositories=repositories,
            discovery=discovery,
            generierungen=generierungen,
            registry=registry,
            agent=kind_agent,
            task=task,
            endpoint_id=geerbt,
            ordner=None,
            user_id=user_id,
            sprache=sprache,
            eltern_id=eltern_id,
        )
    except HTTPException as fehler:
        # The model reads this one — it is the tool result of its own call.
        # A refusal of this route carries the English copy (Refusal); any
        # other HTTPException has only the sentence it was raised with.
        return job_could_not_start(
            fehler.model if isinstance(fehler, Refusal) else fehler.detail
        ), True

    protokoll("status", f"Started job {kind.id} ('{agent_name}').")
    repositories.auftraege.schritt_anlegen(
        kind.id, "status", f"Started by job {eltern_id}."
    )
    return (
        f"Job started: agent '{agent_name}', id {kind.id}. It runs under this "
        "one — it stops when this run is stopped, and its report lands in the "
        "agents panel.",
        False,
    )


def _auftragslauf(
    *,
    auftrag_id: str,
    endpoint_id: str,
    agent: Agent,
    anfrage: Generierungsanfrage,
    zustand,
    registry,
    repositories: Repositories,
    generierungen: Generierungsverwaltung,
    discovery: Discovery,
    ordner: list[str],
    sprache: str,
    config,
    task: str,
    user_id: str,
    cronjob_id: str | None = None,
    write_file_angeboten: bool = False,
    befehl_zeitgrenze: int | None = None,
    eingestellte_grenze: int | None = None,
    chat_id: str | None = None,
    ask_in_chat: bool = False,
):
    """Builds the background work for a job.

    Returns the ``arbeit`` function that the run management executes. The
    loop is the one from chat, but without confirmation prompts — the
    approval has already been made, it lives in the agent.

    ``ordner`` are the shared working folders for this run — the file tools
    reach into them and nowhere else, the same boundary a chat's shares are.

    ``ask_in_chat``: the chat model sent this run off (``auftrag_anstossen``).
    Its calls are judged by the chat's mode and rules, and one the chat would
    ask about is asked about in ``chat_id`` (``_ask_in_chat``). Nobody
    answering refuses that one call; the run goes on without it.

    ``cronjob_id`` is the cron entry (app/cronablauf.py) that fired this run,
    if any — see ``auftrag_anstossen``.

    ``endpoint_id`` is the id the run was booked under. The refused thinking
    stages (app/denkablehnung.py) are NOT kept under it: the run's folds read
    and write them under ``refusal_key`` (app/discovery.py), the one id the
    model list and a chat on the same server use — the booked id may name a
    catalogue server alone.

    ``write_file_angeboten`` is whether this run's tools included
    ``write_file`` at all — nothing to report on a run that was
    never offered the tool in the first place.

    ``befehl_zeitgrenze`` is the command time limit resolved for this run
    (app/befehlszeitwahl.py) — handed in rather than re-resolved, so the
    limit that stops a command is the very number the tool description
    promised the model.

    ``discovery`` and ``user_id`` are here for one thing: a ``start_job``
    call in this run starts a child, and starting one needs the same world
    ``auftrag_anstossen`` needs.

    ``chat_id`` is the chat this work belongs to, if any — only read for the
    folders that chat re-chose, whose new place a refused file call is told.
    """
    # The refused thinking stages of this model, under the id the model list
    # reads them under (see the docstring).
    refusal_id = refusal_key(zustand, anfrage.modell)

    def protokoll(typ: str, inhalt: str) -> None:
        # A job deleted under its run takes its transcript with it; a line
        # the run still writes afterwards has no row to belong to and is
        # dropped instead of failing the run.
        try:
            repositories.auftraege.schritt_anlegen(auftrag_id, typ, inhalt)
        except sqlite3.IntegrityError as error:
            # Only the missing job; any other broken line stays loud.
            if error.sqlite_errorname != "SQLITE_CONSTRAINT_FOREIGNKEY":
                raise
            log.info("Job %s is gone, its transcript line is dropped", auftrag_id)

    # One transcript line per running tool call, and its id while the run
    # lasts: the first progress event opens the line, every later one
    # REWRITES it. A line per event would bury the transcript — a single
    # call reports dozens of times (measured: 36, 74, 87 events), and the
    # argument of one call is written over minutes.
    #
    # The id lives here and not in the database on purpose: it is a fact
    # about THIS run (which call is line number seven right now), and the
    # line itself is what survives the run.
    fortschrittszeilen: dict[str, str] = {}

    def fortschritt_protokollieren(daten: dict, runde: int) -> None:
        """The line the tool progress writes, opened once and then moved.

        What it says is what has actually arrived — the tool's name and how
        many characters of its argument are here — never the argument. The
        chat shows the argument's tail; a transcript is a log, and a log
        that carries half-written JSON stops being readable.

        The ROUND is part of the key, and that is not a detail: the index is
        the call's position in its round, so every round numbers its calls
        from zero again. Without the round, the second `read_file` of a run
        would keep rewriting the first one's line — five calls, one line,
        somewhere up the transcript, with a number that jumps backwards.

        The wording comes from the catalogue in the user's own language: the
        line is stored and read back as it stands, so it cannot be
        translated later, and a German sentence on an English installation
        would be a text nobody ever sees the source of.
        """
        kennung = f"{runde}:{daten.get('index')}:{daten.get('name') or ''}"
        name = daten.get("name") or "?"
        zeichen = daten.get("zeichen")
        # The number is optional in the event's shape, and a missing one may
        # not take the run down: a log line is not worth a lost job.
        text = t(
            "werkzeug.schreibt",
            sprache,
            name=name,
            zeichen=f"{(zeichen if isinstance(zeichen, int) else 0):,}".replace(",", "."),
        )
        zeile = fortschrittszeilen.get(kennung)
        if zeile is None:
            schritt = repositories.auftraege.schritt_anlegen(
                auftrag_id, "werkzeug", text
            )
            fortschrittszeilen[kennung] = schritt.id
            return
        repositories.auftraege.schritt_fortschreiben(zeile, text)

    def kontext_protokollieren(stand: kontextverbrauch.Kontextstand | None) -> None:
        """A ``kontext`` step — the one thing a job's context bar reads.
        Nothing to log without a reading."""
        if stand is not None:
            protokoll("kontext", json.dumps(dataclasses.asdict(stand), ensure_ascii=False))
            bus.veroeffentlichen_ohne_warten(
                Ereignisse.AUFTRAG_KONTEXT, auftrag_id=auftrag_id
            )

    async def arbeit(generierung: Generierung) -> None:
        antwort_text: list[str] = []
        messwerte: dict = {}
        fehlertext: str | None = None
        # The same error in the language of the window, where the two differ
        # (app/providers/base.py): the stored ending is the model's copy, the
        # run panel's red line is the person's.
        fehlertext_fenster: str | None = None
        # An ending with no explanation behind it at all (see the except
        # clause far below): the one case whose sentence may not be stored,
        # because it is written in the window's language.
        unerwartet = False
        ende_grund: str | None = None
        # Set only on a proactive context-full handoff (app/zwischenstand.py)
        # — overrides the plain concatenation of the round texts as the
        # report, since that handoff text IS the report in that case.
        zwischenstand_ergebnis: str | None = None
        # Whether a successful write_file call ever happened —
        # only tracked when the tool was offered at all (see the "fertig"
        # ending below).
        datei_geschrieben = False
        # The deliveries to the agent dock this run promised and
        # never got onto the shelf, BY NAME. A refused `deliver_file` puts
        # its name in, a delivery that lands takes its own name out — so a
        # model that miscalls once and then delivers the same file is a
        # finished run, while one that delivered `bericht.md` and lost
        # `daten.csv` is not. Measured before this existed: the refused
        # delivery stood at one step in the log and the run ended "fertig",
        # which is exactly how a schedule loses its report unnoticed.
        #
        # A set and not a flag: the flag was the LAST
        # call's verdict whatever it was about, so the third file's success
        # wiped out the second file's failure and three deliveries with a
        # refusal in the middle ended "fertig" again — the very loss the
        # ending was built against, one file wide instead of one run wide.
        #
        # It starts from the task text, not empty: a
        # continuation is handed what the previous run still owes
        # (app/zwischenstand.py), so a debt survives a context overflow
        # instead of dying with the run that noticed it.
        offene_ablagen: set[str] = zwischenstand.offene_ablagen_lesen(task)
        # What the `goal` tool call carried, if this run made one.
        # Read out of the call as it happens rather than out of the step log
        # afterwards — the run knows it for certain here, and the entry's
        # end path (app/cronablauf.py) is handed the answer instead of
        # parsing it back out of JSON. Stays None in a run that reported
        # nothing, which is the normal case for a goal entry.
        ziel_bericht: str | None = None
        # Whether this run ended by handing its work on to a scheduled
        # continuation — set at the one place that
        # actually writes one, the context-full handoff with a decision to
        # carry on. Read once, at the end path, by the failure counter.
        fortsetzung_geplant = False
        abgebrochen = False
        quelle = None
        start_zeit = time.monotonic()
        frist = start_zeit + agent.minuten * 60
        # The loop variable itself, kept for the "how much of
        # the budget did this run actually use" check in the finally below
        # — -1 so a run that never even entered the loop reports 0 rounds
        # used rather than crashing on an undefined name.
        runde = -1
        # The thinking of the round that is running, and nothing before it —
        # the same cut `runden_text` makes for the text. Declared out here
        # like `runde` above: the one swap at the end of the run reads it
        # (app/reasoning.denktext_als_antwort), and a run that never entered
        # the loop must find an empty one rather than an undefined name.
        runden_gedanke: list[str] = []
        # The text of that same round, declared out here for the same reason:
        # the swap at the end asks whether the closing round wrote anything,
        # not whether the whole run did.
        runden_text: list[str] = []
        # The same call, rejected three times running, means the
        # model has not understood why — ends the run instead of burning
        # the rest of its rounds against a wall it cannot read.
        schleifenwaechter = Schleifenwaechter()
        # An attempt that did not actually shrink the history means the
        # genuine middle is gone — every further attempt this run would
        # only summarize the previous summary, costing a request each round
        # for nothing. Once that happens, stop trying for the rest of THIS
        # run; a later run starts with a fresh transcript and gets its own
        # chance.
        verdichtung_abgeschaltet = False

        generierung.melden(
            _sse(
                "start",
                generation_id=generierung.id,
                auftrag_id=auftrag_id,
                agent=agent.name,
                endpoint_id=zustand.endpunkt.id,
            )
        )
        protokoll("status", "gestartet")
        # An unattended overnight run is worth nothing if the
        # Mac sleeps through it — released in the finally below no matter
        # how this run ends.
        wachhalten.sicherstellen()
        # Calls refused the moment they began, by id: the reason is what the
        # model gets back as the call's result (app/werkzeugvorpruefung.py).
        fruehe_absagen: dict[str, str] = {}
        # What a refusal of this run brought its ceiling down to: an output
        # limit the provider named binds the retry, every round after it and
        # the handoff, so a provider is not turned down once per round for
        # the same number; a ceiling one round's input led to binds that
        # round's retries. Never on the endpoint state another job, chat or
        # fold at the same address reads (app/antwortgrenze.py `Zug`).
        zug = antwortgrenze.Zug()

        try:
            for runde in range(agent.runden + 1):
                # Retry with growing backoff: a provider outage
                # mid-run used to be one ProviderFehler away from ending the
                # whole run. Each attempt starts the round fresh — a
                # mid-stream failure's partial text belongs to an attempt
                # that never finished, not to the round's own result.
                versuch = 0
                # Attempts of this round after the provider called it too
                # long (app/kontextvoll.py) — a lower answer ceiling or a
                # forced fold, counted apart from `versuch`, which is about
                # outages. `faltungen` counts the fold steps among them; a
                # lowered ceiling is held by the run's holder (`zug`).
                zu_lang_versuche = 0
                faltungen = 0
                # Set once a fold step of this round ended without folding
                # anything a smaller step could still fold. No further fold
                # step follows: the next one would ask about the same history
                # again and end the same way — inside the pause a failure
                # booked (app/faltpause.py), with no room to write a summary
                # in, or with a summary that saves nothing.
                notfall_gefaltet = False
                zug.round_begins()
                # The ceiling for THIS round, worked out again: every round
                # is its own request and each carries more than the last —
                # the previous round's tool calls and their results are in
                # the history now. Under "Auto" the ceiling is what is left
                # of the window, so one kept from the first round would claim
                # room the input has since taken, and a server that adds the
                # two up refuses exactly that.
                #
                # What a refusal of an earlier round of this run named is
                # read here too (`zug`); a number somebody set is brought
                # down to it where the round goes out.
                anfrage.max_tokens = antwortgrenze.aufloesen(
                    eingestellte_grenze,
                    antwortgrenze.geltender_deckel(zustand, anfrage.modell, zug),
                    zustand.context_tokens or 0,
                    antwortgrenze.eingabe_schaetzen(anfrage.nachrichten, anfrage.werkzeuge),
                    anthropic=antwortgrenze.anthropic_draht(zustand),
                )
                # Before the round goes out at all: does Auto still leave
                # room for an answer? Where it does not, the number above is
                # not a ceiling but the bare edge, and a round carrying it
                # is the one failure nothing downstream can see. The server
                # does not refuse it — it answers with a single token — so
                # neither the lowering nor the fold below ever runs, and the
                # round is booked as done with a word and a half in it.
                #
                # So the same cure a refusal gets, without the detour over
                # the server: fold the list in memory, then ask the
                # arithmetic again. The same fold, the same counters and the
                # same ceiling as the refusal path below uses, so this round
                # cannot fold more often than FALTVERSUCHE between the two of
                # them; and once a fold step ended without a summary, no
                # further step follows here either.
                while antwortgrenze.reicht_nicht(
                    eingestellte_grenze,
                    antwortgrenze.geltender_deckel(zustand, anfrage.modell, zug),
                    zustand.context_tokens or 0,
                    antwortgrenze.eingabe_schaetzen(anfrage.nachrichten, anfrage.werkzeuge),
                    anthropic=antwortgrenze.anthropic_draht(zustand),
                ):
                    if (
                        notfall_gefaltet
                        or zu_lang_versuche >= kontextvoll.FALTVERSUCHE
                        or generierung.soll_abbrechen
                    ):
                        # The round goes out with the edge rather than not
                        # at all, and the answer that comes back says it
                        # stopped at the ceiling (app/antwortende.py).
                        log.info(
                            "Auftrag %s: nothing left to fold, the round goes out with "
                            "the smallest ceiling there is",
                            auftrag_id,
                        )
                        break
                    zu_lang_versuche += 1
                    faltungen += 1
                    log.info(
                        "Auftrag %s: the input leaves no room for an answer, folding "
                        "before the round goes out (attempt %d/%d)",
                        auftrag_id,
                        zu_lang_versuche,
                        kontextvoll.FALTVERSUCHE,
                    )
                    try:
                        faltergebnis = await verdichtung.verdichten(
                            zustand,
                            anfrage,
                            kontextvoll.faltbudget(
                                verdichtung.schwanz_budget(
                                    zustand.context_tokens,
                                    verdichtungswahl.schwelle(
                                        repositories,
                                        modell=zustand.endpunkt.id,
                                        chat=auftrag_id,
                                    ),
                                ),
                                faltungen,
                            ),
                            schluessel=auftrag_id,
                            einstellungen=repositories.einstellungen,
                            endpoint_id=refusal_id,
                            erzwungen=True,
                        )
                    except Exception:  # noqa: BLE001 - a failed fold must not end the run here
                        # Not the run's end, and not a smaller step either: a
                        # step that broke says nothing about a middle a
                        # smaller one could fold, so the round goes out with
                        # the edge, the same as after a summary that failed.
                        log.warning(
                            "Auftrag %s: fold before sending failed", auftrag_id, exc_info=True
                        )
                        notfall_gefaltet = True
                        continue
                    if faltergebnis.notfall:
                        protokoll("status", "fold failed — the history stays unfolded")
                        # Asked here as well as at the round's end, for the
                        # same reason the refusal path asks it: a forced fold
                        # can complete the run of failures that switches
                        # automatic folding off, and after that the
                        # round-end path never runs again — so the notice
                        # would never be given at all.
                        if faltpause.hinweis_faellig(auftrag_id):
                            protokoll("status", "automatic folding stopped for this run")
                    if not faltergebnis.angewendet:
                        # A step whose tail budget covers this history whole
                        # folds nothing. On to the next, smaller one without
                        # sending — the same move the refusal path makes, and
                        # the normal case for a short job: giving up here
                        # would send the round out with the edge while a
                        # smaller budget still had a middle to fold. Every
                        # other step that folded nothing is the last one.
                        notfall_gefaltet = not faltergebnis.keine_mitte
                        continue
                    protokoll(
                        "status",
                        "The input left no room for an answer: compacted the history "
                        f"(attempt {zu_lang_versuche}/{kontextvoll.FALTVERSUCHE}).",
                    )
                    # Folded: the ceiling is worked out again from what is
                    # left, the same question asked of a smaller input.
                    anfrage.max_tokens = antwortgrenze.aufloesen(
                        eingestellte_grenze,
                        antwortgrenze.geltender_deckel(zustand, anfrage.modell, zug),
                        zustand.context_tokens or 0,
                        antwortgrenze.eingabe_schaetzen(
                            anfrage.nachrichten, anfrage.werkzeuge
                        ),
                        anthropic=antwortgrenze.anthropic_draht(zustand),
                    )
                if generierung.soll_abbrechen:
                    # Stopped while folding: nothing of this round has gone
                    # out, so there is nothing to keep and no reason to send
                    # it now. Ends as the ordinary abort it is, the same as
                    # every other stop in this run.
                    abgebrochen = True
                    break
                ausfall_erschoepft = False
                ausfall_text = ""
                while True:
                    versuch += 1
                    runden_text = []
                    # Whether this attempt has written a visible character
                    # yet: its first one is set a blank line below the text
                    # of the rounds before (app/reasoning.paragraph_break).
                    round_wrote_visible = False
                    # Every attempt starts its round fresh: a mid-stream
                    # failure's thinking belongs to an attempt that never
                    # finished, not to the round that ended the run.
                    runden_gedanke = []
                    # This round's finished items on OpenAI's Responses wire,
                    # handed back in the next round and nowhere else
                    # (app/providers/openai_responses.py).
                    runden_teile: list[dict] = []
                    # This round's content blocks on the Anthropic wire, in the
                    # order the answer brought them, handed back in the next round
                    # and nowhere else (app/providers/anthropic.py).
                    round_blocks: list[dict] = []
                    aufrufe: list = []
                    # Kept separate from `messwerte`: that one is meant to
                    # carry the last known reading through to the final
                    # report even when a later round happens to bring none
                    # of its own — using it here too would log this round's
                    # context stand from numbers that are actually a
                    # previous round's.
                    runden_messwerte: dict | None = None
                    # The folder check at the start of a call, the same one
                    # the chat run makes (app/werkzeugvorpruefung.py).
                    vorpruefung = werkzeugvorpruefung.Vorpruefung(
                        ordner, werkzeugvorpruefung.angebotene_namen(anfrage.werkzeuge),
                        config.datenverzeichnis,
                    )
                    # Every send of this run goes out with no more than the
                    # ceiling a refusal brought it down to: the retry, a
                    # send after a fold, and every round after it.
                    quelle = zustand.provider.streamen(
                        kontextvoll.mit_grenze(
                            anfrage,
                            antwortgrenze.forced_ceiling(anfrage.max_tokens, zug),
                            zustand,
                        )
                    )
                    try:
                        while True:
                            # See app/api/v1/generierung.py's own version of
                            # this loop: a plain ``async for`` never wakes
                            # for a stop while the server sends nothing but
                            # bare keepalives, and a round of a job hangs
                            # exactly the same way a chat answer would.
                            stueck, abbruch_hat_gewonnen = await generierung.naechstes_stueck(
                                quelle
                            )
                            if stueck is None:
                                abgebrochen = abbruch_hat_gewonnen
                                break
                            if stueck.sorte == "content":
                                # A round's first visible text stands one
                                # blank line below the rounds before it, as
                                # in a chat answer (app/api/v1/generierung.py):
                                # in the round's own text, so the report, the
                                # step log and the stream all carry the same
                                # text, and the rounds joined are the report.
                                piece = stueck.text
                                if not round_wrote_visible and piece.strip():
                                    round_wrote_visible = True
                                    # The rounds before, and the bare line
                                    # breaks this one wrote ahead of it:
                                    # `antwort_text` takes a round only
                                    # when it ends.
                                    davor = "".join(antwort_text) + "".join(runden_text)
                                    piece = reasoning.paragraph_break(davor, piece) + piece
                                runden_text.append(piece)
                                generierung.melden(_sse("content", text=piece))
                            elif stueck.sorte == "reasoning":
                                runden_gedanke.append(stueck.text)
                                generierung.melden(_sse("reasoning", text=stueck.text))
                            elif stueck.sorte == "stats":
                                messwerte = stueck.daten
                                runden_messwerte = stueck.daten
                            elif stueck.sorte == "tool_call_laeuft":
                                # The same kind the chat run forwards
                                # (app/api/v1/generierung.py): a tool call is
                                # only complete at the end of the stream, so a
                                # model writing a long argument means minutes
                                # in which data flows and a watcher sees
                                # nothing. The providers were already sending
                                # it (app/providers/anthropic.py,
                                # app/providers/openai_kompatibel.py); this
                                # branch was missing, so it fell through to
                                # nobody. Throttled where it is sent
                                # (WerkzeugFortschrittsDrossel): the argument
                                # has to have grown, and then either the
                                # minimum interval has passed or it grew by
                                # the minimum step — whichever comes first,
                                # so the rate follows the model's speed and
                                # not the argument's length. Measured on real
                                # runs: 36 events for an argument of 1,364
                                # characters, 74 for one of 2,272 — and that
                                # is no ceiling: minutes of writing are
                                # hundreds of lines. They are kept for the
                                # life of the run and replayed to a watcher
                                # who reattaches (app/generationen.py), which
                                # is what the chat path does with them too.
                                generierung.melden(
                                    _sse("tool_call_laeuft", **stueck.daten)
                                )
                                fortschritt_protokollieren(stueck.daten, runde)
                                # A call that works in folders which are not
                                # there is cut off as it begins, not after
                                # its whole argument has streamed.
                                if vorpruefung.beginnt(stueck.daten):
                                    break
                            elif stueck.sorte == "response_item":
                                runden_teile.append(stueck.daten["eintrag"])
                            elif stueck.sorte == "anthropic_block":
                                round_blocks.append(stueck.daten["block"])
                            elif stueck.sorte == "tool_call":
                                aufrufe = stueck.werkzeugaufrufe
                            elif stueck.sorte == "error":
                                fehlertext = stueck.text
                        await quelle.aclose()
                        quelle = None
                        # The call cut short by the folder check stands in the
                        # history as it began, and its result is the reason.
                        if vorpruefung.absage is not None and not abgebrochen:
                            ersatz, ersatz_grund = vorpruefung.ersatz()
                            fruehe_absagen[ersatz.id] = ersatz_grund
                            aufrufe = [ersatz]
                        break
                    except ProviderFehler as fehler:
                        quelle = None
                        # A stop or delete only ever sets this same signal
                        # (app/generationen.py) — never a Task.cancel(), so
                        # neither the async-for above nor a plain sleep would
                        # ever see it. Checked before anything else: a run
                        # someone stopped must not reschedule itself, only
                        # end as the ordinary abort it already is.
                        if generierung.soll_abbrechen:
                            abgebrochen = True
                            break
                        text = str(fehler)
                        # The same error for the step log, in the language
                        # the window shows: the log is the person's, and the
                        # sentence above is the model's (app/providers/base).
                        fenstertext = fehler.text(sprache)
                        if _modell_nicht_gefunden(fehler):
                            # Deterministic and permanent: the model named in
                            # the request is wrong on every attempt, so this
                            # ends the run instead of burning the five
                            # outage attempts and an outage restart on it.
                            log.info(
                                "Auftrag %s: model not found (404), not retrying: %s",
                                auftrag_id, text,
                            )
                            # The same rule the outage ending below already
                            # keeps: earlier rounds of this same run may have
                            # produced real output, and this ending must not
                            # silently drop it behind the bare refusal text.
                            bisher = "".join(antwort_text)
                            zwischenstand_ergebnis = text + (
                                f"\n\nProduced so far:\n{bisher}" if bisher else ""
                            )
                            ende_grund = "modell_nicht_gefunden"
                            abgebrochen = False
                            break
                        # Asking also learns: both halves of the request take
                        # what the refusal names (app/ablehnungslernen.py).
                        if ablehnungslernen.fenster_voll(
                            repositories, zustand, fehler, zug
                        ):
                            # Not transient, so no outage attempt. Up to
                            # FALTVERSUCHE attempts, each what
                            # kontextvoll.abhilfe reads off the refusal:
                            #
                            # * The answer's ceiling alone fills the window:
                            #   the round goes again with a lower ceiling, on
                            #   a copy of the request, for this round only —
                            #   the run's own ceiling stays. Where the input
                            #   leaves nothing free for an answer, no attempt
                            #   is made at all.
                            # * Otherwise the list is folded in memory and the
                            #   round sent again, each fold step keeping less
                            #   of the history word for word — also where
                            #   automatic compaction was switched off for this
                            #   run, since the round cannot go out at all
                            #   otherwise. A step that folds nothing moves on
                            #   to the next, smaller one without resending:
                            #   with no known window the first budget is the
                            #   ceiling, which a whole short history fits
                            #   inside.
                            #
                            # Where nothing cures it, the outage handling
                            # further down applies, unchanged; a stop while
                            # folding ends the run as the abort it is.
                            weg, frei = kontextvoll.abhilfe(
                                fehler,
                                eingestellte_grenze=eingestellte_grenze,
                                fenster=zustand.context_tokens,
                            )
                            if weg == kontextvoll.LIMIT_TOO_LARGE:
                                # The answer length somebody set is as large
                                # as the whole window: three folds would cost
                                # three summaries and change nothing.
                                # The run ends and says what to
                                # change.
                                log.info(
                                    "Auftrag %s: the set answer length is too large "
                                    "for this model, not retrying",
                                    auftrag_id,
                                )
                                ende_grund = "antwortlaenge_zu_gross"
                                abgebrochen = False
                                break
                            if weg == kontextvoll.KARTE:
                                log.info(
                                    "Auftrag %s: the input leaves no room for an answer, not retrying",
                                    auftrag_id,
                                )
                                raise
                            if weg == kontextvoll.GRENZE:
                                if zu_lang_versuche >= kontextvoll.FALTVERSUCHE:
                                    raise
                                zu_lang_versuche += 1
                                zug.lower_round(frei)
                                meldung = (
                                    f"answer ceiling lowered to {zug.held()} for this round "
                                    f"(attempt {zu_lang_versuche}/{kontextvoll.FALTVERSUCHE})"
                                )
                                log.info("Job %s: %s", auftrag_id, meldung)
                                protokoll(
                                    "status",
                                    f"The provider called the request too long: {meldung}, "
                                    "sending the round again.",
                                )
                                versuch -= 1
                                continue
                            if notfall_gefaltet:
                                # A fold step of this round already ended
                                # without a summary, and the round came back
                                # refused. Every further step would end the
                                # same way (see `notfall_gefaltet`) — it is the
                                # context-full ending from here.
                                log.info(
                                    "Auftrag %s: the fold ended without a summary, "
                                    "the round ends",
                                    auftrag_id,
                                )
                                raise
                            gefaltet = False
                            vor_der_faltung = antwortgrenze.eingabe_schaetzen(
                                anfrage.nachrichten, anfrage.werkzeuge
                            )
                            while (
                                not gefaltet
                                and not notfall_gefaltet
                                and zu_lang_versuche < kontextvoll.FALTVERSUCHE
                                and not generierung.soll_abbrechen
                            ):
                                zu_lang_versuche += 1
                                faltungen += 1
                                try:
                                    faltergebnis = await verdichtung.verdichten(
                                        zustand,
                                        anfrage,
                                        kontextvoll.faltbudget(
                                            verdichtung.schwanz_budget(
                                                zustand.context_tokens,
                                                verdichtungswahl.schwelle(
                                                    repositories,
                                                    modell=zustand.endpunkt.id,
                                                    chat=auftrag_id,
                                                ),
                                            ),
                                            faltungen,
                                        ),
                                        schluessel=auftrag_id,
                                        einstellungen=repositories.einstellungen,
                                        endpoint_id=refusal_id,
                                        erzwungen=True,
                                    )
                                except Exception:  # noqa: BLE001 - a failed fold ends as context-full, not as a crash
                                    log.warning(
                                        "Job %s: forced fold failed", auftrag_id, exc_info=True
                                    )
                                    notfall_gefaltet = True
                                    break
                                gefaltet = faltergebnis.angewendet
                                # The same rule as the check before sending:
                                # only a step that found no middle at its
                                # budget leaves a smaller one something to
                                # fold.
                                notfall_gefaltet = (
                                    not gefaltet and not faltergebnis.keine_mitte
                                )
                                if faltergebnis.notfall:
                                    protokoll(
                                        "status", "fold failed — the history stays unfolded"
                                    )
                                    # Asked here as well as at the round's
                                    # end: the run of failures that switches
                                    # automatic folding off can be completed
                                    # by a FORCED fold, and after that the
                                    # round-end path never runs again — so
                                    # the notice would never be given at all.
                                    if faltpause.hinweis_faellig(auftrag_id):
                                        protokoll(
                                            "status",
                                            "automatic folding stopped for this run",
                                        )
                            if generierung.soll_abbrechen:
                                abgebrochen = True
                                break
                            if not gefaltet:
                                raise
                            protokoll(
                                "status",
                                f"The provider called the request too long: compacted the "
                                f"history (attempt {zu_lang_versuche}/{kontextvoll.FALTVERSUCHE}) "
                                "and sending the round again.",
                            )
                            # Folded: a ceiling a refusal brought this round
                            # down to was the room left beside the input
                            # before the fold. The room grew by what the
                            # fold freed, and the round's own ceiling is
                            # worked out again from what is left.
                            zug.input_folded(
                                vor_der_faltung
                                - antwortgrenze.eingabe_schaetzen(
                                    anfrage.nachrichten, anfrage.werkzeuge
                                )
                            )
                            anfrage.max_tokens = antwortgrenze.aufloesen(
                                eingestellte_grenze,
                                antwortgrenze.geltender_deckel(zustand, anfrage.modell, zug),
                                zustand.context_tokens or 0,
                                antwortgrenze.eingabe_schaetzen(
                                    anfrage.nachrichten, anfrage.werkzeuge
                                ),
                                anthropic=antwortgrenze.anthropic_draht(zustand),
                            )
                            versuch -= 1
                            continue
                        if versuch >= wiederversuch.VERSUCHE:
                            ausfall_erschoepft = True
                            ausfall_text = text
                            break
                        protokoll(
                            "status",
                            f"Anbieter nicht erreichbar (Versuch {versuch}/"
                            f"{wiederversuch.VERSUCHE}): {fenstertext}",
                        )
                        # Races the backoff against the same stop signal
                        # instead of a plain sleep, so a stop mid-wait ends
                        # the run right away rather than after the full
                        # remaining backoff.
                        try:
                            await asyncio.wait_for(
                                generierung.signal.wait(), timeout=wiederversuch.abstand(versuch)
                            )
                        except asyncio.TimeoutError:
                            pass
                        if generierung.soll_abbrechen:
                            abgebrochen = True
                            break

                # No separate check for `abgebrochen` here: every place that
                # sets it breaks the retry loop immediately, before
                # `ausfall_erschoepft` could also end up true — an aborted
                # attempt still needs the normal post-round handling below
                # (the round's own text kept, then the existing abgebrochen
                # check further down ends the run) rather than skipping it.
                if ausfall_erschoepft:
                    protokoll(
                        "status",
                        f"Anbieter nach {wiederversuch.VERSUCHE} Versuchen weiter "
                        f"nicht erreichbar: {fenstertext}",
                    )
                    vorheriger = (
                        repositories.cronjobs.holen(cronjob_id) if cronjob_id else None
                    )
                    neustarts = (vorheriger.neustarts if vorheriger else 0) + 1
                    bisher = "".join(antwort_text)
                    status = (
                        f"The model server was unreachable after "
                        f"{wiederversuch.VERSUCHE} attempts ({ausfall_text})."
                        + (f"\n\nProduced so far:\n{bisher}" if bisher else "")
                    )
                    zwischenstand_ergebnis = status
                    if neustarts < zwischenstand.MAX_NEUSTARTS:
                        basis = zwischenstand.urspruengliche_aufgabe(vorheriger, task)
                        # What this run still owes the shelf travels with the
                        # work — an outage does not
                        # settle a delivery that never arrived.
                        neue_aufgabe = zwischenstand.naechste_aufgabe(
                            basis, status, offene_ablagen
                        )
                        zeitplan = zwischenstand.bald(config)
                        if zwischenstand.ist_kette(vorheriger):
                            # Only a chain's own entry is adopted — a
                            # schedule someone made themselves keeps its own
                            # text, time and state; a
                            # fresh chain entry is created below instead.
                            ziel_id = vorheriger.id
                            repositories.cronjobs.aktualisieren(
                                ziel_id, task=neue_aufgabe, zeitplan=zeitplan,
                                basisaufgabe=basis,
                                # Armed again together with the new task —
                                # see app/zwischenstand.py.
                                aktiv=True,
                            )
                        else:
                            ziel_id = repositories.cronjobs.erstellen(
                                agent=agent.name, task=neue_aufgabe,
                                zeitplan=zeitplan, herkunft="agent",
                                basisaufgabe=basis,
                                # The goal, the one-off flag and the origin
                                # travel with the work — see
                                # app/zwischenstand.py.
                                **zwischenstand.kettenfelder(vorheriger, auftrag_id),
                            ).id
                        repositories.cronjobs.fortschritt_setzen(
                            ziel_id,
                            erledigt_anzahl=vorheriger.erledigt_anzahl if vorheriger else None,
                            ohne_fortschritt=vorheriger.ohne_fortschritt if vorheriger else 0,
                            neustarts=neustarts,
                        )
                        # An outage that handed its work on is not a failed
                        # run either — the same rule already decided for the
                        # context overflow below, and the same reasoning:
                        # this run could not reach the model, but it wrote
                        # down where it stood and put the rest on the clock.
                        # Counted, the failure limit would switch off the
                        # very entry the continuation was just written into,
                        # and an outage chain would die at `fehlergrenze`
                        # instead of at the restart ceiling that governs it.
                        # Narrow in exactly the same way: only where a
                        # continuation was really written and scheduled —
                        # the ceiling case in the branch below is a real
                        # ending with nothing behind it and keeps counting.
                        fortsetzung_geplant = True
                    elif zwischenstand.ist_kette(vorheriger):
                        # The absolute ceiling shared with the outage retry — a
                        # permanently gone endpoint stops being retried too.
                        # Only a chain's own entry, never someone's own
                        # schedule.
                        repositories.cronjobs.aktiv_setzen(vorheriger.id, False)
                    ende_grund = "anbieter_ausfall"
                    break

                antwort_text.extend(runden_text)
                if runden_gedanke:
                    protokoll("reasoning", "".join(runden_gedanke)[:GEDANKE_KUERZUNG])
                if runden_text:
                    protokoll("text", "".join(runden_text))

                # Written after every round rather than only at
                # the context-full handoff or a provider outage — a hard
                # restart mid-run then always has something on the row to
                # resume this job from, not only a run that happened to
                # cross one of those two triggers.
                if antwort_text:
                    # With the debt behind it — this
                    # write would otherwise overwrite the one the tool path
                    # above just made, and the refusal would be gone again
                    # one round later.
                    #
                    # And the model's own text scrubbed first: this row is what the service restart reads
                    # the debt back out of (app/zwischenstand.py), and it
                    # reads it RAW, before ``naechste_aufgabe`` cleans the
                    # status up for the model to look at. A run whose text
                    # echoed the block therefore handed its restarted self a
                    # file nobody ever asked for — measured on the row,
                    # ``{'phantom.md'}`` against the empty set the
                    # context-overflow path already returned for the very
                    # same text. Scrubbed here, the last block on the row is
                    # always the one ``mit_offenen_ablagen`` appends, which
                    # is the rule the rest of the program already keeps.
                    repositories.auftraege.zwischenstand_setzen(
                        auftrag_id,
                        zwischenstand.mit_offenen_ablagen(
                            zwischenstand.ohne_ablagebloecke("".join(antwort_text)),
                            offene_ablagen,
                        ),
                    )

                # How full the context is after this round — written every
                # round so a full context is known before it becomes the
                # ProviderFehler app/kontextvoll.py recognizes. Nothing to log
                # when the provider's stats chunk carries no usable usage
                # numbers, or the context size was never confirmed.
                kontextstand = kontextverbrauch.stand(runden_messwerte, zustand.context_tokens)
                kontext_protokollieren(kontextstand)

                # The round ran the window out. Until now a run only ever
                # learned that from the text of a refusal, and a full window
                # is not always a refusal: an OpenAI-compatible server that
                # fills it mid-answer reports an ordinary length stop, and
                # Anthropic's own word for it arrives as a perfectly normal
                # end of stream. Either way nothing was raised, so the run
                # was booked as finished over an answer that had been cut
                # off. It ends here instead, with the same reason the
                # refusal below gives it — the round's own numbers are the
                # evidence (app/antwortende.py).
                if (
                    not abgebrochen
                    and not fehlertext
                    and antwortende.fenster_voll(
                        (runden_messwerte or {}).get("ende_grund"),
                        gesamt_tokens=kontextverbrauch.tokens_aus_messwerten(runden_messwerte),
                        fenster=zustand.context_tokens,
                        eigene_grenze=bool(eingestellte_grenze),
                    )
                ):
                    ende_grund = "kontext_voll"
                    break

                # The thinking pass used up the whole answer length and left
                # no visible text (app/antwortende.py). The run ends with the
                # sentence that says whose length it was — the user's own or
                # the provider's; there is no continuation.
                if (
                    not abgebrochen
                    and not fehlertext
                    and antwortende.denken_aufgebraucht(
                        (runden_messwerte or {}).get("ende_grund"),
                        denktext="".join(runden_gedanke),
                        sichtbarer_text="".join(runden_text),
                    )
                ):
                    ende_grund = (
                        "denken_aufgebraucht_eigene_grenze"
                        if eingestellte_grenze
                        else "denken_aufgebraucht"
                    )
                    break

                # The same ending, one reading further: the answer stopped at
                # a limit of the PROVIDER's while the window still had room
                # (app/antwortende.py). The run ends exactly as it does for a
                # full window — only the reason it names is a different one.
                if (
                    not abgebrochen
                    and not fehlertext
                    and antwortende.anbietergrenze(
                        (runden_messwerte or {}).get("ende_grund"),
                        gesamt_tokens=kontextverbrauch.tokens_aus_messwerten(runden_messwerte),
                        fenster=zustand.context_tokens,
                        eigene_grenze=bool(eingestellte_grenze),
                    )
                ):
                    ende_grund = "anbietergrenze"
                    break

                if abgebrochen or fehlertext or not aufrufe:
                    break

                # The two restraints (6.4): rounds first, then time.
                # Checked at the round boundary — cutting off mid-answer
                # would mean throwing away what has already been produced.
                if runde >= agent.runden:
                    ende_grund = "rundengrenze"
                    break
                if time.monotonic() > frist:
                    ende_grund = "zeitgrenze"
                    break

                # Proactive handoff: a round's own token reading
                # crossing the threshold, still with room to ask — instead
                # of letting the NEXT round crash into ProviderFehler further
                # down. The current round's own tool calls are dropped
                # rather than appended: an assistant turn with unanswered
                # tool_calls followed by anything but their results is
                # invalid history for several providers, and this run is
                # ending regardless of what those calls would have found.
                #
                # Read through `app/kontextdruck.py` like the bar and the
                # fold trigger, so all three answer out of one module.
                # Nothing has been appended since
                # the reading above, so what is new is zero and the number
                # is the measured one — and `stand` rather than `prozent`
                # because it rounds to one decimal exactly the way the bar's
                # step does: the raw share would hand 89.96 to a comparison
                # while the bar already reads 90.0, and the bar would name a
                # number nothing acted on. THE MOMENT is what makes the two
                # equal here: at the end of a round the trigger reads the
                # same module for what the NEXT request will carry, which is
                # larger by this round's tool results (measured at window
                # 114688: 96000 answered plus 8000 returned reads 83.7 here
                # and 90.7 there) — two questions, one module, and the fold
                # at 80 per cent exists so this ending rarely has to happen
                # (app/verdichtungswahl.py).
                uebergabedruck = (
                    kontextdruck.stand(kontextstand.tokens, 0, zustand.context_tokens)
                    if kontextstand is not None
                    else None
                )
                if (
                    uebergabedruck is not None
                    and uebergabedruck.prozent is not None
                    and uebergabedruck.prozent >= zwischenstand.SCHWELLE_PROZENT
                ):
                    if generierung.soll_abbrechen:
                        # Stopped before the handoff was asked for: none is.
                        abgebrochen = True
                        break
                    # The handoff is a request of this run too: it goes out
                    # with no more than the ceiling a refusal of the run
                    # brought it down to, as an upper bound beside the room
                    # the transcript leaves.
                    #
                    # And it offers no tools, the same rule as a fold's
                    # request (app/faltversuche.py `without_tools`): answered
                    # with a call instead of text, the handoff came back
                    # empty and the run failed. Its ceiling is measured
                    # against the same copy, so without them as well.
                    text = await zwischenstand.anfordern(
                        zustand,
                        faltversuche.without_tools(anfrage),
                        antwortgrenze.capped_setting(eingestellte_grenze, zug),
                        generierung,
                    )
                    if text is None or generierung.soll_abbrechen:
                        # Stopped while the handoff was being written, or in
                        # the tick it finished: the run ends as stopped with
                        # its own answer as the result, and nothing is
                        # handed on or scheduled.
                        abgebrochen = True
                        break
                    if text:
                        zwischenstand_ergebnis = text
                        vorheriger = (
                            repositories.cronjobs.holen(cronjob_id) if cronjob_id else None
                        )
                        entscheidung = zwischenstand.entscheiden(
                            vorheriger, zwischenstand.erledigt_zaehlen(text)
                        )
                        if entscheidung.weiter:
                            # The chain's real original task — carried on
                            # the entry, never re-derived from `task`, which
                            # from the second restart on is already the
                            # previous handoff's own wrapped text. Re-wrapping
                            # THAT every time would grow the opening message
                            # with every restart, exactly what carrying the
                            # original task on the entry exists to prevent.
                            basis = zwischenstand.urspruengliche_aufgabe(
                                vorheriger, task
                            )
                            # And the deliveries still owed: the run that noticed the refusal is
                            # the one ending here, so unless the debt is
                            # written into the continuation's own task, the
                            # next run finishes "fertig" over a file that
                            # never arrived.
                            neue_aufgabe = zwischenstand.naechste_aufgabe(
                                basis, text, offene_ablagen
                            )
                            zeitplan = zwischenstand.bald(config)
                            if zwischenstand.ist_kette(vorheriger):
                                # ``basisaufgabe`` written here too, not only
                                # in ``erstellen`` below: a chain that starts
                                # from an entry someone else already created
                                # (the tool, a human) never went through
                                # ``erstellen`` with this field set — its
                                # first handoff is the only chance to fill it
                                # in before the next restart has nothing but
                                # the already-wrapped text to fall back on.
                                #
                                # Only a chain's own entry, though — a
                                # schedule someone made themselves keeps its
                                # own text, time and state; a fresh chain entry is created below
                                # instead.
                                ziel_id = vorheriger.id
                                repositories.cronjobs.aktualisieren(
                                    ziel_id, task=neue_aufgabe, zeitplan=zeitplan,
                                    basisaufgabe=basis,
                                    # Armed again together with the new
                                    # task: a chain that inherited
                                    # ``einmalig`` switched itself off the
                                    # moment it fired, and this row is the
                                    # one that has to run next. Not
                                    # ``aktiv_setzen``, which would clear
                                    # counts that belong to the chain.
                                    aktiv=True,
                                )
                            else:
                                ziel_id = repositories.cronjobs.erstellen(
                                    agent=agent.name, task=neue_aufgabe,
                                    zeitplan=zeitplan, herkunft="agent",
                                    basisaufgabe=basis,
                                    # The goal travels with the work:
                                    #without it the
                                    # continuation that actually finds the
                                    # thing has no goal to book against —
                                    # nothing stamped, nothing switched off —
                                    # and is not even offered the `goal` tool
                                    # when its agent's own list leaves it out.
                                    #
                                    # The one-off flag and the origin travel
                                    # with it for the same reason: without
                                    # the flag a continued `once` entry ends
                                    # in silence instead of saying it found
                                    # nothing, and without the origin
                                    # nothing the chain reaches ever gets
                                    # back to the entry a person made.
                                    **zwischenstand.kettenfelder(vorheriger, auftrag_id),
                                ).id
                            repositories.cronjobs.fortschritt_setzen(
                                ziel_id,
                                erledigt_anzahl=entscheidung.erledigt_anzahl,
                                ohne_fortschritt=entscheidung.ohne_fortschritt,
                                neustarts=entscheidung.neustarts,
                            )
                            ende_grund = "kontext_voll"
                            # This is the ONE ending that hands the work on:
                            # the continuation is written,
                            # scheduled and about to run. The failure counter
                            # must not see it — see the end path below.
                            fortsetzung_geplant = True
                        else:
                            # Three restarts running in place, or the
                            # absolute ceiling reached — this chain stops
                            # being rescheduled, on purpose. Only a chain's
                            # own entry, never someone's own schedule.
                            if zwischenstand.ist_kette(vorheriger):
                                repositories.cronjobs.aktiv_setzen(vorheriger.id, False)
                            ende_grund = "kein_fortschritt"
                    else:
                        # Nothing came back to hand off — the reactive
                        # ending further down would have said the same.
                        ende_grund = "kontext_voll"
                    break

                denkteile, textteile = openai_responses.rundenteile(runden_teile)
                anfrage.nachrichten.append(
                    ChatNachricht(
                        role="assistant",
                        content="".join(runden_text),
                        werkzeugaufrufe=aufrufe,
                        reasoning_items=denkteile,
                        message_items=textteile,
                        anthropic_blocks=round_blocks,
                    )
                )

                # Where the round's own answer ends in `anfrage.nachrichten`
                # — remembered here, right after it and before the tool
                # calls below add anything, so the fold trigger at the end
                # of the round can tell what arrived AFTER `kontextstand`
                # was read apart from everything that was already in it
                # (the answer itself included — it is already counted once,
                # inside `kontextstand.tokens`).
                laenge_nach_antwort = len(anfrage.nachrichten)

                # Pictures this round's tools want the model to LOOK at
                # (app/werkzeugbild.py), collected for the whole round and
                # handed over after it — a call and its result have to stay
                # adjacent, so nothing may be pushed in between them. Same
                # shape as the chat's run (app/api/v1/generierung.py).
                gelesene_bildnamen: list[str] = []
                gelesene_bild_urls: list[str] = []
                # Where each picture came from, so a request that retires it
                # later can say where to read it again (app/werkzeugbild.py).
                gelesene_bildpfade: list[str] = []

                def modellbild(name: str, daten_url: str, pfad: str = "") -> None:
                    gelesene_bildnamen.append(name)
                    gelesene_bild_urls.append(daten_url)
                    gelesene_bildpfade.append(pfad)

                def report_result(
                    aufruf, server: str, ergebnis: str, fehlgeschlagen: bool, dauer: float,
                    lauf_nummer: int | None = None,
                ) -> None:
                    """One call's result, in the stream with the chat's fields
                    and in the stored log with its server: the time it took,
                    and for a shell command the number of the run it started,
                    so a reader of either can tell which run belongs to it.
                    A job never sends a picture to a window — a picture a
                    tool hands the model (`modellbild` above) goes to the
                    model, not the stream."""
                    lauf = {"lauf_nummer": lauf_nummer} if lauf_nummer is not None else {}
                    generierung.melden(
                        _sse(
                            "tool_result",
                            name=aufruf.name,
                            aufruf_id=aufruf.id,
                            fehlgeschlagen=fehlgeschlagen,
                            text=ergebnis[:ERGEBNIS_KUERZUNG],
                            bild=None,
                            dauer_sekunden=dauer,
                            **lauf,
                        )
                    )
                    protokoll(
                        "tool_result",
                        json.dumps(
                            # The short fields first: the transcript shows
                            # each line cut to one row, and the text is long.
                            {
                                "name": aufruf.name,
                                "server": server,
                                "fehlgeschlagen": fehlgeschlagen,
                                "dauer_sekunden": dauer,
                                **lauf,
                                "text": ergebnis[:ERGEBNIS_KUERZUNG],
                            },
                            ensure_ascii=False,
                        ),
                    )

                for aufruf in aufrufe:
                    # The same fields the chat's stream carries for a call and
                    # its result (app/api/v1/generierung.py): the server the
                    # UI picks the tool's mark by, and the time the call took.
                    server = registry.server_von(aufruf.name) if registry else ""
                    generierung.melden(
                        _sse(
                            "tool_call",
                            name=aufruf.name,
                            server=server,
                            argumente=aufruf.argumente,
                            aufruf_id=aufruf.id,
                        )
                    )
                    aufruf_beginn = time.monotonic()
                    protokoll(
                        "tool_call",
                        json.dumps(
                            {"name": aufruf.name, "server": server, "argumente": aufruf.argumente},
                            ensure_ascii=False,
                        ),
                    )
                    # start_job is started here, not executed by the
                    # registry — starting a run needs the config, the
                    # repositories, the discovery and the run management,
                    # none of which the registry has. The same shape the
                    # chat's own interception has (app/api/v1/generierung.py):
                    # the child is a part of the assignment THIS run was
                    # given.
                    if aufruf.name == auftrag_werkzeug.WERKZEUG_NAME:
                        ergebnis, fehlgeschlagen = _kind_starten(
                            aufruf=aufruf,
                            eltern_id=auftrag_id,
                            config=config,
                            repositories=repositories,
                            discovery=discovery,
                            generierungen=generierungen,
                            registry=registry,
                            user_id=user_id,
                            sprache=sprache,
                            protokoll=protokoll,
                        )
                        report_result(
                            aufruf, server, ergebnis, fehlgeschlagen,
                            round(time.monotonic() - aufruf_beginn, 3),
                        )
                        anfrage.nachrichten.append(
                            ChatNachricht(
                                role="tool",
                                content=ergebnis,
                                werkzeugaufruf_id=aufruf.id,
                            )
                        )
                        continue

                    # ask_user is not executed but answered — here as much as
                    # in a chat. The difference is where the question goes:
                    # the chat puts it above the input field of somebody who
                    # is sitting there, and a job puts it ON the run, which
                    # then stands in the waiting group until somebody comes
                    # (app/auftragsfrage.py).
                    if aufruf.name == frage_werkzeug.WERKZEUG_NAME:
                        # The time spent waiting on the person, kept out of
                        # the call's own duration as it is kept out of the
                        # run's budget below.
                        gewartet = 0.0
                        try:
                            refused = helper.refused_call(agent.name, aufruf.name)
                            if refused:
                                raise frage_werkzeug.FrageUngueltig(refused)
                            frage_text, frage_optionen = frage_werkzeug.gepruefte_frage(
                                aufruf.argumente
                            )
                        except frage_werkzeug.FrageUngueltig as fehler:
                            ergebnis, fehlgeschlagen = str(fehler), True
                        else:
                            # Anybody watching the run's stream gets the same
                            # event the chat gets, in the same shape.
                            generierung.melden(
                                _sse(
                                    "user_ask",
                                    frage=frage_text,
                                    optionen=frage_optionen,
                                    aufruf_id=aufruf.id,
                                )
                            )
                            gewartet_ab = time.monotonic()
                            antwort = await auftragsfrage.stellen(
                                generierung=generierung,
                                repositories=repositories,
                                auftrag_id=auftrag_id,
                                agent=agent.name,
                                aufruf_id=aufruf.id,
                                frage=frage_text,
                                optionen=frage_optionen,
                            )
                            # The budget is for WORK. However long somebody
                            # took to answer is given back to the run — both
                            # to the deadline and to the reading of how much
                            # of its time it actually spent.
                            gewartet = time.monotonic() - gewartet_ab
                            frist += gewartet
                            start_zeit += gewartet
                            if antwort is None and generierung.soll_abbrechen:
                                # The open call gets its result before the
                                # run ends, so no row stays "running" and
                                # every call in the history has its answer.
                                # The run stops after the report below.
                                ergebnis = t("nachricht.abgebrochen_kurz", sprache)
                                fehlgeschlagen = True
                                abgebrochen = True
                            else:
                                ergebnis = (
                                    antwort
                                    if isinstance(antwort, str) and antwort.strip()
                                    else frage_werkzeug.OHNE_ANTWORT
                                )
                                fehlgeschlagen = False
                        report_result(
                            aufruf, server, ergebnis, fehlgeschlagen,
                            max(0.0, round(time.monotonic() - aufruf_beginn - gewartet, 3)),
                        )
                        if abgebrochen:
                            break
                        anfrage.nachrichten.append(
                            ChatNachricht(
                                role="tool",
                                content=ergebnis,
                                werkzeugaufruf_id=aufruf.id,
                            )
                        )
                        continue

                    # No confirmation prompt: whatever the agent
                    # names is approved. The registry still checks once more —
                    # it remains the outer boundary (Tor 3, app/berechtigungen.py):
                    # a tool the agent did not name, or a path outside its
                    # shared folders, comes back as a refusal instead of
                    # running. The shared folders travel with the call so the
                    # file tools can actually reach them.
                    # Refused while it was still being written: nothing to
                    # run, the reason is the result.
                    # A tool a helper is not offered does not run for it
                    # either, whatever the rule file says (app/helper.py).
                    # `at_path`: the refusal is about the call's path or the
                    # run's folders, not about the tool — the one kind told
                    # where a moved folder went (`with_move_note` below).
                    refused = helper.refused_call(agent.name, aufruf.name)
                    declined: str | None = None
                    if (
                        ask_in_chat
                        and not refused
                        and aufruf.id not in fruehe_absagen
                        and registry is not None
                        and registry.urteil(
                            aufruf.name, aufruf.argumente, ordner, "agent", agent,
                            rules_of="chat",
                        ).antwort == "fragen"
                    ):
                        # The chat would ask about this call, so the run
                        # asks there and stands still until it is answered.
                        # The wait is the person's, not the run's: it is
                        # given back to the budget the way a question's is.
                        gewartet_ab = time.monotonic()
                        entscheidung = await _ask_in_chat(
                            generierung=generierung,
                            repositories=repositories,
                            registry=registry,
                            aufruf=aufruf,
                            ordner=ordner,
                            agent_name=agent.name,
                            chat_id=chat_id,
                            sprache=sprache,
                        )
                        gewartet = time.monotonic() - gewartet_ab
                        frist += gewartet
                        start_zeit += gewartet
                        # The call's own time starts after the answer, as
                        # in the chat: a slow click is not a slow tool.
                        aufruf_beginn = time.monotonic()
                        if entscheidung is None and generierung.soll_abbrechen:
                            ergebnis = t("nachricht.abgebrochen_kurz", sprache)
                            report_result(aufruf, server, ergebnis, True, 0.0)
                            abgebrochen = True
                            break
                        declined = refusal_for(entscheidung, aufruf.name)
                    if refused:
                        ergebnis, fehlgeschlagen, abgelehnt, at_path = refused, True, True, False
                    elif aufruf.id in fruehe_absagen:
                        ergebnis, fehlgeschlagen, abgelehnt, at_path = (
                            fruehe_absagen[aufruf.id], True, True, True
                        )
                    elif declined is not None:
                        ergebnis, fehlgeschlagen, abgelehnt, at_path = declined, True, True, False
                    else:
                        ergebnis, fehlgeschlagen, abgelehnt, at_path = await _werkzeug_ausfuehren(
                            registry, aufruf, sprache, ordner=ordner, chat_id=auftrag_id,
                            herkunft="agent", agent=agent,
                            shell_zeitgrenze=befehl_zeitgrenze,
                            # Which entry a `cron_note` call writes to.
                            # From the run, never from the call's arguments.
                            cronjob_id=cronjob_id,
                            # One report per run: the
                            # second `goal` call is refused instead of setting
                            # off the same sound and the same notification
                            # again. The run holds the answer; the tool holds
                            # the rule.
                            ziel_gemeldet=ziel_bericht is not None,
                            # Only where the model has eyes. Without them
                            # `read_file` says it cannot show the picture
                            # instead of handing over one nobody can see.
                            modellbild=modellbild if zustand.kann("vision") else None,
                            # The memory's switch for this model's side, as in
                            # the chat: not in the prompt, not in a listing.
                            gedaechtnis_zeigen=aufruf.name == memory.WERKZEUG_NAME
                            and gedaechtnis.mitschicken(repositories, zustand),
                            # A run the chat model sent off is judged by the
                            # chat's mode; what that mode asks about was
                            # asked about above.
                            rules_of="chat" if ask_in_chat else None,
                            # The job's stop reaches a picture being drawn.
                            abbruch=generierung.signal,
                        )
                    if aufruf.name == datei_schreiben.WERKZEUG_NAME and not fehlgeschlagen:
                        datei_geschrieben = True
                    if aufruf.name == ablage_werkzeug.WERKZEUG_NAME:
                        # Per FILE, not per run. "Made good" means the same
                        # name arrived after all — a different file landing
                        # says nothing about the one that was refused, and
                        # reading it as an all-clear is how three deliveries
                        # with a failure in the middle passed for finished.
                        # A call with no name at all named no file, so there
                        # is nothing to owe: the tool refuses it outright and
                        # the model can simply call again.
                        #
                        # Under the shelf's own name, not the raw argument
                        # the raw one is the
                        # model's text, and it went into a bulleted list in
                        # the handoff — a name carrying a newline could close
                        # that list and wipe a second, real name out of it.
                        # It also made "out/daten.csv" a different debt from
                        # the "daten.csv" tile that then really did land.
                        ablage_name = agentendock.eintragsname(
                            (aufruf.argumente or {}).get("name") or ""
                        )
                        if ablage_name:
                            vorher = set(offene_ablagen)
                            if fehlgeschlagen:
                                offene_ablagen.add(ablage_name)
                            else:
                                offene_ablagen.discard(ablage_name)
                            if offene_ablagen != vorher:
                                # Onto the row at the moment it
                                # changes, not only at the end of the next
                                # round. A hard restart between the refusal
                                # and the next round's status write used to
                                # lose exactly this — the run came back
                                # owing nothing.
                                #
                                # Scrubbed like the round's own write above
                                # — the same row, read back
                                # raw by the same restart.
                                repositories.auftraege.zwischenstand_setzen(
                                    auftrag_id,
                                    zwischenstand.mit_offenen_ablagen(
                                        zwischenstand.ohne_ablagebloecke(
                                            "".join(antwort_text)
                                        ),
                                        offene_ablagen,
                                    ),
                                )
                    if aufruf.name == ziel_werkzeug.WERKZEUG_NAME and not fehlgeschlagen:
                        try:
                            # The tool's own reading of the call, not the raw
                            # argument — one cleaning, not two, exactly as in
                            # the chat's path (app/api/v1/generierung.py).
                            ziel_bericht = ziel_werkzeug.bericht(aufruf.argumente)
                        except ziel_werkzeug.ZielVerboten:
                            # The call ran, so this cannot normally happen —
                            # and the report was already announced by the
                            # tool either way.
                            log.warning(
                                "goal call without a usable report: %s", aufruf.argumente
                            )
                    # A shell command that really ran has a run behind it,
                    # and the result names it as the chat's does: only a run
                    # that began at THIS call, under the job's id, asked the
                    # way the tool names it — never for a refused call.
                    lauf_nummer: int | None = None
                    if aufruf.name == shell.WERKZEUG_NAME and not abgelehnt:
                        gestartet = hintergrund.laeufe.juengster(
                            auftrag_id,
                            str(aufruf.argumente.get("command") or "").strip(),
                            seit=aufruf_beginn,
                        )
                        if gestartet is not None:
                            lauf_nummer = gestartet.nummer
                    report_result(
                        aufruf, server, ergebnis, fehlgeschlagen,
                        round(time.monotonic() - aufruf_beginn, 3), lauf_nummer,
                    )
                    anfrage.nachrichten.append(
                        ChatNachricht(
                            role="tool",
                            # What a tool answers is the model's text — the
                            # tools write it in English for exactly this
                            # reader (see the chat's own round, which hands
                            # over the same string). A refused file call
                            # aimed under a folder the chat of this work
                            # re-chose is told where it went — the model's
                            # copy only, under the chat's own condition.
                            content=with_move_note(
                                ergebnis,
                                refused=at_path,
                                werkzeuge_an=registry is not None,
                                chat_id=chat_id,
                                aufruf=aufruf,
                                ordner=ordner,
                            ),
                            werkzeugaufruf_id=aufruf.id,
                        )
                    )

                    if schleifenwaechter.aufruf(aufruf.name, aufruf.argumente, abgelehnt=abgelehnt):
                        protokoll(
                            "status",
                            f"'{aufruf.name}' was rejected the same way "
                            f"{Schleifenwaechter.GRENZE} times in a row — ending the run "
                            "instead of burning the remaining rounds against it.",
                        )
                        ende_grund = "wiederholte_ablehnung"
                        break

                # Every result of the round is in place, so a picture one of
                # them read may follow now — as a user turn, the only role an
                # image part is valid on.
                bildzug = werkzeugbild.nachricht(
                    gelesene_bildnamen, gelesene_bild_urls, gelesene_bildpfade
                )
                if bildzug is not None:
                    anfrage.nachrichten.append(bildzug)

                if ende_grund == "wiederholte_ablehnung":
                    break

                # The fold trigger, asked at the true end of the round: the
                # earlier reads above (`kontextstand`) name what the round's
                # OWN request and answer used, taken before this round's
                # tool calls existed at all. Asked there, the check fires a
                # round late — on the round AFTER the one that actually grew
                # past the threshold, because every tool result just
                # appended above is still uncounted. Reaching this line
                # means the round already cleared the rounds/time limit and
                # the emergency handoff above, so a next round is coming
                # regardless — unless THIS round is the one that just ended
                # the run early (`abgebrochen`), in which case there is no
                # next round to save anything for, and the check is skipped
                # rather than spending a real provider call on a run that is
                # already stopping.
                #
                # `verdichtung_abgeschaltet` guards the FOLD below and not the
                # reading here any more: the free step ahead of it costs no
                # request and still has work after the fold gave up, because
                # the protected end moves on with every round — what was the
                # model's working memory in one round is an old result in the
                # next. An estimate per round is a sum over a list; the fold
                # is a request to a model, and only that one is worth
                # switching off.
                if not abgebrochen:
                    # `kontextstand.tokens` is the real total the provider
                    # counted for the round; the answer itself is already in
                    # it, so only the rows appended AFTER it — this round's
                    # own tool results, from `laenge_nach_antwort` on — are
                    # new.
                    #
                    # Report, clear, report again, fold: the one step the
                    # chat takes between its rounds too (app/round_end.py).
                    # Every reading is logged for the context bar: the step
                    # written after the answer could not count this round's
                    # own tool results yet, and after a fold the bar shows
                    # what the folded request weighs.
                    #
                    # The same threshold setting the chat reads, resolved
                    # for this run: `zustand.endpunkt.id` is the model this
                    # job is actually talking to, and the job's own id
                    # stands in for the chat scope — the run management
                    # already treats the two the same way
                    # (`generierungen.starten`).
                    async for schritt in round_end.between_rounds(
                        zustand,
                        anfrage,
                        last_reading=(
                            kontextstand.tokens if kontextstand is not None else None
                        ),
                        appended_from=laenge_nach_antwort,
                        threshold=verdichtungswahl.schwelle(
                            repositories,
                            modell=zustand.endpunkt.id,
                            chat=auftrag_id,
                        ),
                        set_limit=eingestellte_grenze,
                        fold_allowed=not verdichtung_abgeschaltet,
                        key=auftrag_id,
                        settings=repositories.einstellungen,
                        endpoint_id=refusal_id,
                    ):
                        if isinstance(schritt, kontextverbrauch.Kontextstand):
                            kontext_protokollieren(schritt)
                        elif isinstance(schritt, round_end.Cleared):
                            protokoll(
                                "status",
                                f"Cleared {schritt.count} old tool results from the "
                                "request to save context space.",
                            )
                        elif schritt.result.notfall:
                            # One the model failed to write leaves the history
                            # untouched and books a pause, and the run goes on
                            # — a fold that fails has never been a reason to
                            # end it.
                            protokoll(
                                "status", "fold failed — the history stays unfolded"
                            )
                            if faltpause.hinweis_faellig(auftrag_id):
                                protokoll(
                                    "status",
                                    "automatic folding stopped for this run",
                                )
                        elif schritt.result.angewendet:
                            protokoll(
                                "status",
                                "Compacted the history to keep the context from "
                                "filling up.",
                            )
                        elif schritt.result.ohne_ersparnis:
                            verdichtung_abgeschaltet = True
                            protokoll(
                                "status",
                                "Compacting stopped for this run: the last attempt "
                                "did not shrink the history.",
                            )

        except ProviderFehler as fehler:
            # Two readers, two languages, built together here so the pair is
            # whole wherever either is used: ``text`` is the model's (it ends
            # up stored and in the handoff), ``fenstertext`` the person's, for
            # the red line in the run's own stream below.
            text = str(fehler)
            fehlertext_fenster = fehler.text(sprache)
            # Asking also learns: both halves of the request take what the
            # refusal names (app/ablehnungslernen.py).
            if ablehnungslernen.fenster_voll(repositories, zustand, fehler):
                # A full context is not a crash: the run ends
                # cleanly, and what has been produced so far is the report.
                # Where the answer's length was what the model did not take,
                # the run ends under that reason instead — never "the
                # context is full" (app/kontextvoll.py `is_output_cap`).
                # Only where a length is set: under Auto there is no number
                # to lower, so the run keeps the ending it always had.
                ende_grund = (
                    "antwortlaenge_zu_gross"
                    if eingestellte_grenze is not None
                    and kontextvoll.output_cap_error(fehler)
                    else "kontext_voll"
                )
            else:
                fehlertext = text
            log.warning("Job %s, provider: %s", auftrag_id, fehler)
        except asyncio.CancelledError:
            abgebrochen = True
            raise
        except Exception:  # noqa: BLE001 - one run must not drag down the service
            # Two things at once, and they are not the same thing. The window
            # is told that something went wrong, in its own language — that
            # is `fehlertext`, and it is what the error line in the stream
            # carries. What is STORED is an identifier, never a sentence: the
            # job list shows it from the catalogue in the window's language,
            # and the model's report reads the same entry in English
            # (app/agent_report.py). A sentence from this spot would be the
            # one German text the model must not get.
            unerwartet = True
            fehlertext = fehlertext_fenster = t("fehler.allgemein", sprache)
            log.exception("Job %s failed unexpectedly", auftrag_id)
        finally:
            wachhalten.freigeben()
            # This run's fold pause and its run of emergency folds end with
            # it: they are facts about a transcript that no longer exists,
            # and the next run starts with a fresh one.
            faltpause.freigeben(auftrag_id)
            if quelle is not None:
                await quelle.aclose()

            if abgebrochen:
                # The stop button's reason, unless whoever stopped the run
                # named another: the run above it, or its deleted chat.
                zustand_ende, grund = "abgebrochen", generierung.stop_reason or "benutzer_abbruch"
            elif unerwartet:
                # It outranks anything an earlier round left in `fehlertext`:
                # that text belongs to a step that did not end the run.
                zustand_ende, grund = "gescheitert", "fehler_allgemein"
            elif fehlertext:
                zustand_ende = "gescheitert"
                grund = f"fehler: {fehlertext}"[:300]
            elif ende_grund in (
                "rundengrenze", "zeitgrenze", "kontext_voll", "kein_fortschritt",
                "anbieter_ausfall", "wiederholte_ablehnung", "anbietergrenze",
                "denken_aufgebraucht", "denken_aufgebraucht_eigene_grenze",
                "antwortlaenge_zu_gross", "modell_nicht_gefunden",
            ):
                # A snapped restraint is not a success — but it is a clean
                # ending with a report: whatever exists is in the result.
                #
                # And a run that handed its work on did not FAIL: the whole
                # rest of this file already says so — the failure counter
                # skips it, the goal booking is told about it by name, the
                # notification stays quiet for it — and the one field the
                # eye actually reads said 'gescheitert' anyway. The reports
                # list painted a red "context window full" over a run whose
                # work was already on the clock.
                #
                # ``unterbrochen`` is this program's own word for exactly
                # that: "a run that can still be resumed, not a result"
                # (CRONJOB_AUSGAENGE, app/db/repositories/auftraege.py) —
                # the state a hard restart leaves behind, and the state that
                # is deliberately left out of a cron entry's outcome
                # history. Nothing new had to be invented, nothing new had
                # to be stored, and ``fortsetzung_geplant`` now reaches the
                # screen as the state itself.
                #
                # The reason stays what it was: WHY this run stopped is
                # still 'kontext_voll' or 'anbieter_ausfall', and the row
                # says so — quietly, because it is not a fault.
                #
                # An overflow with no continuation behind it — the handoff
                # came back empty, the restart ceiling is reached, the
                # provider never came back — sets no flag and stays
                # 'gescheitert', red and final, which is the truth there.
                zustand_ende = "unterbrochen" if fortsetzung_geplant else "gescheitert"
                grund = ende_grund
            elif offene_ablagen:
                # The run said what it wanted to hand over and the
                # shelf did not take it. Nothing else about the run stopped,
                # so without this it would end "fertig" and the missing file
                # would live at one line of the step log — the silent loss
                # this ending exists to end. One name still open is enough:
                # the run owes a file it never handed over, whatever else it
                # managed to deliver.
                zustand_ende, grund = "gescheitert", ablage_werkzeug.GRUND_NICHT_ABGELEGT
            else:
                zustand_ende, grund = "fertig", "fertig"

            # The report, and the one swap the thinking owes on top of it —
            # the same swap the chat makes, in the same place at the end of
            # the run (app/reasoning.denktext_als_antwort). A model that
            # ended its run itself with a closing round that wrote not one
            # visible character thought its report instead of writing it,
            # and the result would be empty — "The agent left no report."
            # (app/agent_report.py) — or only the sentence an earlier round
            # wrote before its tool call. The thought of the round the run
            # ENDED in is the report then, behind that sentence; the
            # deliberation of the rounds before it stays in this run's step
            # log, where it always was. Both halves are the same text here:
            # a job keeps the thinking of its last round and nothing else,
            # so there is nothing left over to hold back.
            #
            # The closing state decides, exactly as it does in the chat: a
            # run that was stopped, that failed or that stopped against a
            # restraint is no finished answer, whatever word its last round
            # reported.
            # A result set on the way (a handoff, which made the swap where it
            # was written in app/zwischenstand.py, or a refusal's text) is one
            # text of its own and its own closing text.
            closing_thought = "".join(runden_gedanke)
            bericht = (
                zwischenstand_ergebnis if zwischenstand_ergebnis is not None
                else "".join(antwort_text)
            )
            ergebnis, _ = reasoning.denktext_als_antwort(
                bericht,
                closing_thought,
                closing_thought,
                schlusstext=(
                    bericht if zwischenstand_ergebnis is not None
                    else "".join(runden_text)
                ),
                ende_grund=messwerte.get("ende_grund"),
                zustand=zustand_ende,
            )

            auftrag_vorhanden = repositories.auftraege.holen(auftrag_id) is not None
            if auftrag_vorhanden:
                if zustand_ende == "fertig":
                    runden_benutzt = runde + 1
                    minuten_benutzt = (time.monotonic() - start_zeit) / 60
                    if kurzlauf.kurz(runden_benutzt, agent.runden, minuten_benutzt, agent.minuten):
                        protokoll(
                            "status",
                            kurzlauf.hinweis(
                                runden_benutzt, agent.runden, minuten_benutzt, agent.minuten,
                            ),
                        )
                if (
                    zustand_ende == "fertig"
                    and write_file_angeboten
                    and not datei_geschrieben
                ):
                    # Nothing stopped the run from finishing
                    # without writing one, so at least this makes the gap
                    # visible instead of passing for a normal, complete run.
                    # Worded about THIS run only — a restart chain
                    # can have written the file in an earlier
                    # one, and this run has no way to know that.
                    protokoll(
                        "status",
                        "This run wrote no file — if this job restarted, an "
                        "earlier run may already have.",
                    )
                if (
                    cronjob_id
                    and not fortsetzung_geplant
                    and zustand_ende != "abgebrochen"
                ):
                    # A restart chain's cron entry
                    # exists only to fire the SAME job again — once the job
                    # actually finishes, there is nothing left to continue.
                    # ``basisaufgabe`` is the marker: only zwischenstand.py's
                    # own chain-continuation ever sets it, never a standing
                    # schedule the cronjob tool created — that one is meant
                    # to keep firing daily and must be left alone.
                    #
                    # It is not only a finished job that
                    # leaves that row with nothing to do. A chain run that
                    # ends at the round limit, at the time limit, on three
                    # rejected calls, on a plain error, or on a handoff that
                    # came back empty writes no continuation either — and
                    # ITS row stayed active. The schedule ``bald()`` gave it
                    # is a daily 'HH:MM', so it fires again tomorrow, with
                    # the stale continuation text, next to the fresh chain
                    # the origin opens: two chains for one job, both booking
                    # failed runs on the same origin. So the condition is
                    # the other way round now — an ending that handed the
                    # work on keeps the row (that IS the continuation), and
                    # every other ending retires it.
                    #
                    # Not to be confused with the origin firing again
                    # tomorrow, which is wanted and untouched: ``ist_kette``
                    # is exactly that line.
                    #
                    # An abort is left out for the same reason it is left out
                    # of the failure count below — the user stopped this run
                    # a second ago, and what happens to the chain after that
                    # is theirs to decide.
                    kette = repositories.cronjobs.holen(cronjob_id)
                    if zwischenstand.ist_kette(kette) and kette.aktiv:
                        repositories.cronjobs.aktiv_setzen(kette.id, False)
                protokoll("ende", grund)
                auftragsende.beenden(
                    repositories, auftrag_id, zustand_ende,
                    ende_grund=grund, ergebnis=ergebnis or None,
                )
                repositories.auftraege.generation_verknuepfen(auftrag_id, None)
            # Otherwise: the job was deleted while the run was going (DELETE
            # stops first, then deletes) — there is no row left to write the
            # ending, the link or the schedule's next step onto.
            generierungen.abmelden(generierung.id)

            if fehlertext:
                # The red line the run panel draws is the PERSON's, so it
                # takes the twin; where none was built (a text that only the
                # model ever reads) the one text is both.
                generierung.melden(_sse("error", text=fehlertext_fenster or fehlertext))
            generierung.melden(_sse("stats", daten=dict(messwerte or {})))
            generierung.melden(
                _sse("done", auftrag_id=auftrag_id, zustand=zustand_ende, grund=grund)
            )

            # After every other end-of-run bookkeeping, never inside it: this
            # can wait up to two commands' worth of speaking, and the run
            # must already be fully wrapped up — recorded, unsubscribed,
            # reported to the UI — by the time it does. An abort is the
            # user's own action a second ago; it gets no announcement.
            if auftrag_vorhanden and zustand_ende != "abgebrochen":
                # The failure count first: it is bookkeeping on the
                # entry itself and has to be written whatever the
                # announcement below does or does not do. An abort is
                # excluded by the same guard for the same reason — it is the
                # user's own action, not a fault of the schedule.
                # What an announcement says this run was about: the ENTRY's
                # own task text, not this run's. With a goal set, the run's
                # text carries the goal instruction appended at firing time
                # (app/cronablauf.py), and that whole paragraph has
                # no business in a system notification. Falls back to the
                # run's own text for a job no cron entry fired, and for one
                # whose entry was deleted while it ran.
                # And for a restart chain, the ORIGINAL job's text rather
                # than the chain's own: a continuation's `task` is the
                # wrapped "Continue this job. Original task: … Status from
                # the previous run: …" — a whole handoff document, and a
                # system notification is one line. ``basisaufgabe`` is that
                # same original sentence, carried on the chain entry
                # already (app/zwischenstand.py).
                zieleintrag = (
                    repositories.cronjobs.holen(cronjob_id) if cronjob_id else None
                )
                meldetext = (
                    (zieleintrag.basisaufgabe or zieleintrag.task)
                    if zieleintrag is not None else task
                )
                # A run that handed its work on is never a failed run. The
                # failure counter's own rule is "the run
                # could not do its work at all" — this one did its work,
                # got far, wrote down where it stood and put the
                # continuation on the clock. Counting it would kill the
                # very entry the continuation was just written into, and
                # would kill a big daily job after five perfectly normal
                # days: every handed-off run carries the ORIGINAL entry's
                # id, and a 'fertig' never reaches that entry, because it
                # is the continuation that finishes, not the original.
                #
                # Narrow on purpose. A context overflow with NO continuation
                # — the handoff came back empty, or the provider refused the
                # request outright — is a real ending with nothing behind
                # it and keeps counting, as does a provider outage: there
                # the model was unreachable, which is the counter's own
                # definition of a failure. Neither sets this flag.
                #
                # The count is left where it stands rather than reset: this
                # run says nothing about the entry's health in either
                # direction.
                #
                # And a run that reported its goal is not a failed run
                # either, whatever tripped it afterwards. A run can call `goal` and then walk into the
                # round limit — which ends it 'gescheitert'. Counted, that
                # entry could be switched off with "stopped after N failed
                # runs" in the same breath as the finding it was made for,
                # and with `stop_when_reached` it would be switched off
                # twice over, once as finished and once as broken. The
                # counter's own rule settles it: "the run could not do its
                # work at all" is the opposite of a run that reported the
                # very thing it was watching for.
                zaehlt_als_erfolg = zustand_ende == "fertig" or ziel_bericht is not None
                angehalten = False
                if not fortsetzung_geplant:
                    angehalten = await cronablauf.ausgang_verbuchen(
                        repositories, cronjob_id, meldetext,
                        erfolgreich=zaehlt_als_erfolg,
                    )
                # Then the goal: the stamp, the switch-off once it
                # is reached, and the count of runs that stayed quiet. It
                # announces nothing on the good path — the tool already did,
                # at the moment it was called.
                await cronablauf.ziel_verbuchen(
                    repositories, cronjob_id, meldetext,
                    bericht=ziel_bericht,
                    erfolgreich=zustand_ende == "fertig",
                    # A handed-off run looked and found nothing yet, so it
                    # counts as a quiet run — and a one-off must not report
                    # "not reached" while its continuation is still on the
                    # clock.
                    fortsetzung_geplant=fortsetzung_geplant,
                    schon_gemeldet=angehalten,
                )
                # And last the blanket announcement, which an entry with a
                # goal no longer gets at all — and which a run that handed
                # its work on does not get either.
                # ``announce`` means "tell me when this is through": a
                # handoff is not through, and the continuation that finishes
                # the work is the one that says so. Same reading the failure
                # count above and the goal booking in between already use,
                # which is why the flag travels to all three.
                await cronablauf.melde_wenn_faellig(
                    repositories, cronjob_id, meldetext,
                    erfolgreich=zustand_ende == "fertig",
                    fortsetzung_geplant=fortsetzung_geplant,
                    # Why it ended, into the same notification: without it
                    # an announcing entry said "Failed — <task>" and
                    # nothing else, and the reason lived only in a step log
                    # that closes as the run ends.
                    grund=grund,
                    # And not a second time when the failure limit has just
                    # spoken for this very run. ``ausgang_verbuchen``
                    # announces "… — stopped after N failed runs" itself on
                    # the run that reaches the limit, and this call went out
                    # regardless — so an announcing entry got TWO
                    # notifications about one ending, which the goal booking
                    # in between has been avoiding by name all along.
                    # One piece of work says its piece once; the sentence
                    # that survives is the limit's, because it carries the
                    # one fact the other does not: this schedule has
                    # stopped.
                    schon_gemeldet=angehalten,
                )

    return arbeit
