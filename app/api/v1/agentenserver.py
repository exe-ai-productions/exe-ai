"""The agent model slot, from outside.

The same questions the model server's own route answers (app/api/v1/runner.py),
about the second process: which local models are there, what is running with
which settings, and switch it on or off. It used to answer three of them and
say so — "everything that decides HOW it runs follows the runner's own
defaults and is not offered here". That was wrong, and measurably so: the
runner's default window was 8192 back then, an agent run's system prompt with
fifteen tools takes about 6300 of it, and what was left for the task, the tool
results and the answer together was roughly 1800 tokens. Nobody chose that
number and nobody could change it.

So HOW it runs is offered now, in the window this slot has of its own — and
none of it is stored here. Every value lives in the one field's setting
(app/agentenmodellwahl.py), the same key the model file lives in, and both
start paths read it from there: this route when somebody presses the button,
and the autostart at program launch (app/agentenserver.py) when nobody is
watching. That is what keeps the two from starting the same slot differently,
and it is why the start body carries only the file name — a second copy of
the numbers travelling in the request would be a second place they could be
wrong.

Which of the three kinds of answer the one field currently holds is NOT asked
here: this route is about the process. A field pointing at the main model or
at a cloud endpoint has nothing to start, and the window simply never calls
this.

Its own route rather than a mode of the runner route next door, for the same
reason the embedding server has one: the servers must be startable
independently, and a shared route is how they end up sharing a port.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app import agentenmodellwahl
from app.feineinstellungen import context_per_request
from app.agentenserver import ENDPUNKT_ID, MODELL_VORGABE, endpunkt_bauen
from app.api.abhaengigkeiten import hole_config, hole_sprache
from app import chat_template_doors
from app.api.v1.runner import Modelldatei, ProgramState, _zuordnung, program_state
from app.config import Config
from app.i18n import t
from app.modellrunner import RunnerFehler
from app.systemspeicher import gesamt_gb

router = APIRouter(prefix="/agentenmodell", tags=["agentenmodell"])


class Auskunft(ProgramState):
    """What the slot's own page needs to draw itself.

    Deliberately the same shape as the model server's answer: the two pages
    show the same controls, and a second, thinner shape here would mean the
    page below has to ask a different question for every field it mirrors.
    """

    ordner: str
    # The models this server could be given. The same folder the chat model
    # uses — a small model is a model. With sizes, because the memory
    # estimate on the page is drawn from them.
    modelle: list[Modelldatei]
    # The vision projectors in the folder. Their own list: they cannot start,
    # but the page needs to know they are there to offer one.
    mmproj: list[str] = []
    # The size in gigabytes of each projector above, by name.
    projector_size_gb: dict[str, float] = {}
    # The prediction modules — the built-in drafts, with sizes because a
    # draft is a passenger in the memory plan.
    mtp: list[Modelldatei] = []
    speicher_gb: float | None = None
    kerne: int | None = None
    belegt_gb: float | None = None
    laeuft: bool
    modell: str | None = None
    # What a start would load: the stored choice, apart from `modell`, which
    # stays the file that runs. None where nothing is chosen.
    selected_model: str | None = None
    # What the RUNNING process was started with — None while it is off. The
    # page then shows the stored choice instead, exactly as the model server's
    # does.
    kontext: int | None = None
    schichten: int | None = None
    # The context one request gets while the slots do not share the cache
    # (several slots, `kv_unified` off) — None where every request may use
    # the whole window.
    kontext_je_anfrage: int | None = None
    port: int | None = None
    drafter: str | None = None
    vision: str | None = None
    fein: dict | None = None
    flash_aktiv: bool | None = None
    mtp_aktiv: str | None = None
    # The architecture the last start failed on because the server's build
    # does not know it — the same word the model server's answer carries.
    unknown_architecture: str | None = None
    zuordnung: dict[str, dict[str, str | None]] = {}
    # What is chosen when nobody has chosen: the one file this slot has
    # actually been measured on.
    vorgabe: str = MODELL_VORGABE
    # What an unset field falls back to — window, layers, port, the modules
    # and the engine levers. Sent rather than written into the page, so there
    # is exactly one place that decides them (app/agentenmodellwahl.py). A
    # page carrying its own copy is the same bug as a module carrying one,
    # only harder to find: the two would agree until somebody changed one.
    vorgaben: dict = {}


class Start(BaseModel):
    """Only the file. Everything else comes from the stored field.

    Not laziness — the point. The autostart has no request to read numbers
    out of, so if the numbers travelled in the body there would be two
    answers to "how does this slot run", and the restart would silently pick
    the other one.
    """

    modell: str = Field(min_length=1, max_length=200)


def _runner(request: Request):
    return request.app.state.agentenrunner


def _auskunft(request: Request) -> Auskunft:
    runner = _runner(request)
    lauf = runner.shown_run()
    files = runner.modelle()
    slot = agentenmodellwahl.slot_datei(request.app.state.repositories)
    return Auskunft(
        **program_state(runner, request.app.state.config),
        ordner=str(runner.ordner),
        modelle=[Modelldatei(name=m.name, groesse_gb=m.groesse_gb) for m in files],
        mmproj=runner.mmproj(),
        projector_size_gb=runner.projector_sizes(),
        mtp=[Modelldatei(name=m.name, groesse_gb=m.groesse_gb) for m in runner.mtp()],
        speicher_gb=gesamt_gb(),
        kerne=os.cpu_count(),
        belegt_gb=runner.belegt_gb(),
        laeuft=lauf is not None,
        modell=lauf.modell if lauf else None,
        selected_model=slot if slot in {m.name for m in files} else None,
        kontext=lauf.kontext if lauf else None,
        schichten=lauf.schichten if lauf else None,
        kontext_je_anfrage=(
            context_per_request(lauf.kontext, lauf.fein) if lauf else None
        ),
        port=lauf.port if lauf else runner.port_vorgabe,
        drafter=lauf.drafter if lauf else None,
        vision=lauf.vision if lauf else None,
        fein=lauf.fein.als_daten() if lauf and lauf.fein else None,
        flash_aktiv=runner.flash_attn_zustand(),
        mtp_aktiv=runner.mtp_zustand(),
        unknown_architecture=runner.unknown_architecture(),
        zuordnung=_zuordnung(runner),
        vorgaben={
            name: wert
            for name, wert in agentenmodellwahl.VORGABE.items()
            # The choice itself is answered by the field, not by a fallback.
            if name not in ("sorte", "wert", "module")
        },
    )


@router.get("", response_model=Auskunft, summary="Agent model — status")
def auskunft(request: Request) -> Auskunft:
    return _auskunft(request)


@router.get("/log", response_model=list[str], summary="Server messages")
def protokoll(request: Request) -> list[str]:
    return _runner(request).protokoll()


@router.post("/start", response_model=Auskunft, summary="Switch the agent model on")
async def starten(
    daten: Start,
    request: Request,
    config: Config = Depends(hole_config),
    sprache: str = Depends(hole_sprache),
) -> Auskunft:
    repositories = request.app.state.repositories
    try:
        # Window, layers, port, speed module, projector and the engine levers,
        # all read from the one field's setting — the same call the autostart
        # makes. Nothing about how this slot runs is decided in this file.
        startwerte = agentenmodellwahl.slot_startwerte(repositories, daten.modell)
        lauf = _runner(request).starten(daten.modell, **startwerte)
    except RunnerFehler as fehler:
        lage = {
            "laeuft_schon": status.HTTP_409_CONFLICT,
            "port_belegt": status.HTTP_409_CONFLICT,
            "server_geteilt": status.HTTP_409_CONFLICT,
            "kein_programm": status.HTTP_412_PRECONDITION_FAILED,
            "kein_modell": status.HTTP_404_NOT_FOUND,
        }.get(fehler.grund, status.HTTP_400_BAD_REQUEST)
        raise HTTPException(lage, t(f"fehler.runner_{fehler.grund}", sprache)) from None
    # The file that came up is the one the field names from now on, whoever
    # started it — the window, the command line, a second window.
    agentenmodellwahl.remember_file(repositories, daten.modell)
    # The started server joins the model list by itself, exactly as the main
    # runner's does (app/api/v1/runner.py). This is what makes the one field
    # work without a second resolution path: a slot choice resolves through
    # ``discovery.aufloesen`` like every other id, because the slot IS an
    # ordinary endpoint from the moment it comes up.
    #
    # Which also means it appears in the chat's model picker. The comment
    # that used to stand here said the opposite ("deliberately NOT registered
    # with the discovery") and was right for the guardian, whose server was
    # started for one private purpose. Chatting with the small model is now
    # something one may do on purpose.
    #
    # The port comes out of the start itself, not out of ``lauf()`` afterwards:
    # that one answers None for a process that has already died, and what used
    # to stand behind it was the slot's DEFAULT port — which registers a wrong
    # address whenever the start choice names another one. Behind the start's
    # own answer stands the port that was ASKED for.
    await request.app.state.discovery.anmelden(
        endpunkt_bauen(lauf.port if lauf else startwerte.get("port"))
    )
    return _auskunft(request)


@router.post("/chat-template/edit", response_model=chat_template_doors.TemplatePath,
             summary="Copy the model's chat template out and open it in the text editor")
def edit_chat_template(
    daten: chat_template_doors.TemplateRequest, request: Request, sprache: str = Depends(hole_sprache)
) -> chat_template_doors.TemplatePath:
    return chat_template_doors.edit(request, _runner(request), daten.modell, sprache)


@router.post("/chat-template/reveal", response_model=bool,
             summary="Show the chat template file in the file manager")
def reveal_chat_template(
    daten: chat_template_doors.TemplateRequest, request: Request, sprache: str = Depends(hole_sprache)
) -> bool:
    return chat_template_doors.reveal(request, _runner(request), daten.modell, sprache)


@router.post("/stop", response_model=Auskunft, summary="Switch the agent model off")
async def stoppen(request: Request, sprache: str = Depends(hole_sprache)) -> Auskunft:
    try:
        _runner(request).refuse_stop_when_shared()
    except RunnerFehler as fehler:
        raise HTTPException(
            status.HTTP_409_CONFLICT, t(f"fehler.runner_{fehler.grund}", sprache)
        ) from None
    _runner(request).stoppen()
    # Unregistered the moment the process goes, so nothing keeps offering a
    # model that is no longer there — the picker loses the entry, and a run
    # that would have gone to it finds "not reachable" instead of a timeout.
    await request.app.state.discovery.abmelden(ENDPUNKT_ID)
    return _auskunft(request)
