"""The model server, seen and switched from the program.

Everything this offers is a fact the window can show: is the program there,
which files could be loaded, what is running with which settings, and what
the server itself is saying right now.

The command is handed out as well, and deliberately so — it is the same list
that gets executed, so what the window shows cannot drift away from what
actually starts.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app import kit_bond, modellzuordnung, runnermodellwahl
from app.api.abhaengigkeiten import hole_sprache
from app.config import EndpointConfig
from app.i18n import t
from app.modelldownload import BILD_ENDUNGEN, DownloadFehler, Modelldownload
from app.modellrunner import Modellrunner, RunnerFehler, SCHLUESSEL_VARIABLE
from app.systemspeicher import gesamt_gb
from app.ordner_oeffnen import OeffnenNichtMoeglich, ordner_oeffnen
from app.serverdownload import Serverdownload, ServerdownloadFehler

router = APIRouter(prefix="/runner", tags=["runner"])

# The id under which the started server appears among the models. Fixed, so
# a second start replaces the first entry instead of adding one.
RUNNER_ID = "runner"


def _runner_endpunkt(port: int) -> EndpointConfig:
    """The endpoint the started server answers on.

    Built here and not written to the configuration: the entry lives exactly
    as long as the server it describes, and its port is whatever the form
    said at start.
    """
    return EndpointConfig(
        id=RUNNER_ID,
        base_url=f"http://127.0.0.1:{port}/v1",
        provider="openai_compatible",
        parameter_dialect="llama_cpp",
        group="local",
        # The runner hands its server a fresh key at every start; requests
        # without it are turned away — the lock against web pages knocking
        # on localhost from inside the user's browser.
        api_key_env=SCHLUESSEL_VARIABLE,
    )


class Modelldatei(BaseModel):
    name: str
    groesse_gb: float


class Auskunft(BaseModel):
    programm: str | None
    ordner: str
    modelle: list[Modelldatei]
    # Vision companions in the folder. Their own list, not model entries:
    # they cannot start, but the window needs to know they are there.
    mmproj: list[str] = []
    # Prediction modules in the folder — the built-in drafts. Their own
    # list for the same reason, with sizes because a draft is a passenger
    # in the memory plan.
    mtp: list[Modelldatei] = []
    # The machine's memory — the honest ceiling any start plan has to fit.
    speicher_gb: float | None = None
    # How many threads this machine can actually run at once. The thread
    # count is the one setting where more is not better: past the core count
    # the threads fight each other for the same cores and the run gets
    # SLOWER. The window needs the number to be able to stop the slider
    # there instead of offering a value that only hurts.
    kerne: int | None = None
    # What the running server holds right now — None while it is off.
    belegt_gb: float | None = None
    laeuft: bool
    modell: str | None = None
    kontext: int | None = None
    schichten: int | None = None
    port: int | None = None
    drafter: str | None = None
    # The vision projector the running server was started with by hand — None
    # when the server auto-paired one or runs mute.
    vision: str | None = None
    # The engine levers the running server was started with, so the drawer
    # can show what is actually in force instead of its own defaults. None
    # while nothing runs — then the form falls back to the stored choice.
    fein: dict | None = None
    # Whether flash attention ended up on — read off the server's own log,
    # not off what was asked for, because the flag sent is always "auto".
    # None while nothing runs yet or the log has not reached that line.
    flash_aktiv: bool | None = None
    # Whether the drafter (MTP / speculative decoding) actually engaged — read
    # off the server's own log, not off the fact that one was configured.
    # None → none asked for or still loading; "aktiv" → its init line passed
    # (the bolt lights blue); "fehler" → the server came up without it, so a
    # drafter was set but never took (the bolt turns red).
    mtp_aktiv: str | None = None
    # The architecture the last start failed on because llama-server does
    # not know it (a newer model than the server's build), or null.
    unknown_architecture: str | None = None
    # The declared bond of each model to its companions, read from the folder
    # manifest and filtered to files that are still there. Keyed by model
    # file name; each value carries the projector and the draft, or null. The
    # window shows the association and pre-selects the right draft without
    # guessing from name prefixes.
    zuordnung: dict[str, dict[str, str | None]] = {}
    # What an unset field falls back to — window, layers, port. Sent rather
    # than written into the page, so there is exactly one place that decides
    # them (app/runnermodellwahl.py). A page carrying its own copy is the
    # same bug as a module carrying one, only harder to find: the two would
    # agree until somebody changed one.
    vorgaben: dict = {}


class Start(BaseModel):
    """Only the file. Everything else comes from the stored choice.

    Not laziness — the point. Window, layers, port, the modules
    and the engine levers used to travel in this body, which meant the
    browser was the only thing that knew them: a start path with no page
    behind it had nothing to read. They live in one setting now
    (app/runnermodellwahl.py), and every start path reads that same setting,
    so no two of them can bring this server up differently.
    """

    modell: str = Field(min_length=1, max_length=200)


def hole_runner(request: Request) -> Modellrunner:
    return request.app.state.modellrunner


def _zuordnung(runner: Modellrunner) -> dict[str, dict[str, str | None]]:
    """The folder manifest, filtered to model files that are still present.

    A model whose file is gone drops out entirely, and inside each entry a
    deleted companion drops out too, so the window never offers a bond to a
    file that is no longer there. The same folder boundary as the start: a
    key that resolves outside the model folder is ignored.
    """
    ordner = Path(runner.ordner)
    basis = ordner.resolve()
    ergebnis: dict[str, dict[str, str | None]] = {}
    for modell in modellzuordnung.lade(ordner):
        ziel = (ordner / modell).resolve()
        if ziel.parent != basis or not ziel.is_file():
            continue
        ergebnis[modell] = modellzuordnung.fuer(ordner, modell)
    return ergebnis


def _fehler(grund: str, sprache: str) -> HTTPException:
    lage = {
        "laeuft_schon": status.HTTP_409_CONFLICT,
        "port_belegt": status.HTTP_409_CONFLICT,
        "kein_programm": status.HTTP_412_PRECONDITION_FAILED,
        "kein_modell": status.HTTP_404_NOT_FOUND,
    }.get(grund, status.HTTP_400_BAD_REQUEST)
    return HTTPException(lage, t(f"fehler.runner_{grund}", sprache))


@router.get("", response_model=Auskunft, summary="Model server — status")
def auskunft(runner: Modellrunner = Depends(hole_runner)) -> Auskunft:
    lauf = runner.lauf()
    # Read once: finding the program walks the own build's folder.
    programm = runner.programm
    return Auskunft(
        programm=str(programm) if programm else None,
        ordner=str(runner.ordner),
        modelle=[Modelldatei(name=m.name, groesse_gb=m.groesse_gb) for m in runner.modelle()],
        mmproj=runner.mmproj(),
        mtp=[Modelldatei(name=m.name, groesse_gb=m.groesse_gb) for m in runner.mtp()],
        speicher_gb=gesamt_gb(),
        kerne=os.cpu_count(),
        belegt_gb=runner.belegt_gb(),
        laeuft=runner.laeuft(),
        modell=lauf.modell if lauf else None,
        kontext=lauf.kontext if lauf else None,
        schichten=lauf.schichten if lauf else None,
        # Idle, this is the port a start would take — the server's own,
        # which only the server knows. The page needs it to be able to show
        # the port field without repeating the number; the
        # slot's route answers the same way.
        port=lauf.port if lauf else runner.port_vorgabe,
        drafter=lauf.drafter if lauf else None,
        vision=lauf.vision if lauf else None,
        fein=lauf.fein.als_daten() if lauf and lauf.fein else None,
        flash_aktiv=runner.flash_attn_zustand(),
        mtp_aktiv=runner.mtp_zustand(),
        unknown_architecture=runner.unknown_architecture(),
        zuordnung=_zuordnung(runner),
        vorgaben=runnermodellwahl.vorgaben(),
    )


@router.get("/log", response_model=list[str], summary="What the server says")
def protokoll(runner: Modellrunner = Depends(hole_runner)) -> list[str]:
    return runner.protokoll()


@router.post("/start", response_model=Auskunft, summary="Start the model server")
async def starten(
    daten: Start,
    request: Request,
    runner: Modellrunner = Depends(hole_runner),
    sprache: str = Depends(hole_sprache),
) -> Auskunft:
    repositories = request.app.state.repositories
    # Window, layers, port, the module chosen for exactly this file and the
    # engine levers, all read from the stored choice — never from the body.
    # Nothing about how this server runs is decided in this file.
    werte = runnermodellwahl.startwerte(repositories, daten.modell)
    try:
        lauf = runner.starten(daten.modell, **werte)
    except RunnerFehler as fehler:
        raise _fehler(fehler.grund, sprache) from None
    # Whatever started IS the main model from now on. The window already
    # writes the pick the moment it is made; this is the same record for
    # every other way a start happens — the catalogue's button above all,
    # which used to start one file while the remembered choice went on
    # naming the one before it.
    runnermodellwahl.modell_merken(repositories, daten.modell)
    # The started server joins the model list by itself. Without this the
    # chain broke exactly at its last link: fetch, start — and the chat still
    # said no model was reachable, because nobody had told the discovery.
    #
    # The port comes out of the start itself, not out of ``lauf()`` afterwards:
    # that one answers None for a process that has already died, and what used
    # to stand behind it was the runner's DEFAULT port — which registers a
    # wrong address whenever the start choice names another one, and points
    # the discovery at whatever else happens to hold that port. Behind the
    # start's own answer stands the port that was ASKED for, and only where
    # none was chosen does the runner's default become the right answer.
    await request.app.state.discovery.anmelden(
        _runner_endpunkt(
            lauf.port if lauf else (werte.get("port") or runner.port_vorgabe)
        )
    )
    return auskunft(runner)


@router.post("/stop", response_model=Auskunft, summary="Stop the model server")
async def stoppen(
    request: Request, runner: Modellrunner = Depends(hole_runner)
) -> Auskunft:
    runner.stoppen()
    await request.app.state.discovery.abmelden(RUNNER_ID)
    return auskunft(runner)


# --- Fetching a model -----------------------------------------------------


class Holen(BaseModel):
    repo: str = Field(min_length=1, max_length=200)
    datei: str = Field(min_length=1, max_length=200)
    # Local name, when it must differ from the remote one — see
    # Modelldownload.starten.
    ziel: str | None = Field(None, min_length=1, max_length=200)
    # The model this file is a companion of, and which place it takes next to
    # it. Set together, they write the bond into the folder manifest once the
    # file has arrived; absent, the download behaves as before. The role is
    # constrained here, so nothing but a projector, a draft or a kit part is
    # ever declared. A kit part — a text encoder or the VAE — is tied to the
    # picture model it came for in the model's own values (app/kit_bond.py),
    # not in the folder manifest.
    gehoert_zu: str | None = Field(None, min_length=1, max_length=200)
    rolle: Literal["mmproj", "mtp", "vae", "llm", "t5xxl", "clip_l", "clip_g"] | None = None
    # Which kind of model this is — one of the catalogue's tabs. It decides
    # the destination folder, because each server reads only its own folder:
    # an embedding model in the chat folder is invisible to the embedding
    # server and a broken entry in the chat list.
    art: Literal["chat", "einbettung", "sprache", "bild"] = "chat"
    # A companion lands in a sub-folder of its server, so it shows up where it
    # belongs at once and its folder shows only its own kind: a VAE in vae/, a
    # text encoder in text_encoders/, a LoRA in lora/, a face detector in
    # adetailer/ on the picture side; a drafter in mtp/, a projector in
    # vision/ on the chat side. A closed whitelist, never a free path — the
    # download can never write outside these. A file already lying in its
    # folder is not fetched again: kits share their parts.
    unterordner: Literal[
        "vae", "text_encoders", "lora", "adetailer", "mtp", "vision"
    ] | None = None


class Fortschritt(BaseModel):
    datei: str
    geladen: int
    gesamt: int
    anteil: float
    fertig: bool
    fehler: str | None = None


def hole_download(request: Request) -> Modelldownload:
    return request.app.state.modelldownload


def _stand(download: Modelldownload) -> Fortschritt | None:
    stand = download.stand()
    if stand is None:
        return None
    return Fortschritt(
        datei=stand.datei,
        geladen=stand.geladen,
        gesamt=stand.gesamt,
        anteil=stand.anteil,
        fertig=stand.fertig,
        fehler=stand.fehler,
    )


@router.get("/download", response_model=Fortschritt | None, summary="How far the model download is")
def fortschritt(download: Modelldownload = Depends(hole_download)) -> Fortschritt | None:
    return _stand(download)


@router.post("/download", response_model=Fortschritt, summary="Fetch a model")
def holen(
    daten: Holen,
    request: Request,
    download: Modelldownload = Depends(hole_download),
    sprache: str = Depends(hole_sprache),
) -> Fortschritt:
    wurzel = request.app.state.modellordner_je_art.get(daten.art)
    # A companion goes into its sub-folder of the same art. The whitelist on
    # the field is what makes the join safe — no "../" can reach this point.
    # The manifest stays with the model (the art root), not in the sub-folder,
    # so the runner reads the bond from where the model lies.
    ordner = wurzel
    if wurzel is not None and daten.unterordner:
        ordner = str(Path(wurzel) / daten.unterordner)
    # An image model may be safetensors; a chat or embedding model is GGUF
    # only — the one form the runner can start.
    endungen = BILD_ENDUNGEN if daten.art == "bild" else (".gguf",)
    rolle = daten.rolle
    nach: Callable[[], None] | None = None
    if rolle in kit_bond.FIELDS:
        # A kit part is tied to the picture model it came for in the model's
        # own values, written when the file is in place. A part the picture
        # side already offers is only tied: it is the model's part whether
        # this click fetched it or an earlier one did — unless the model
        # carries one of its own by then.
        field, rolle = rolle, None
        if daten.art == "bild" and daten.gehoert_zu and wurzel is not None:
            name = daten.ziel or daten.datei.rsplit("/", 1)[-1]
            modell = daten.gehoert_zu
            repositories = request.app.state.repositories
            folder = Path(wurzel)

            def tie_part() -> None:
                kit_bond.tie(repositories, folder, modell, field, name)

            nach = tie_part
            if name in kit_bond.offered(folder, field):
                kit_bond.tie(repositories, folder, modell, field, name, keep_own=True)
                # Nothing was fetched, so there is nothing to count.
                return Fortschritt(datei=name, geladen=0, gesamt=0, anteil=1.0, fertig=True)
    elif rolle is None and daten.art == "bild" and wurzel is not None and not daten.unterordner:
        # A picture model: once it lies in the folder, the parts of its kit
        # that are there already are written at it — it may have been asked
        # for while they were still on their way for another model.
        arrived = daten.ziel or daten.datei.rsplit("/", 1)[-1]
        model_folder = Path(wurzel)
        model_repositories = request.app.state.repositories

        def tie_offered() -> None:
            kit_bond.tie_offered(model_repositories, model_folder, arrived)

        nach = tie_offered
    try:
        download.starten(
            daten.repo, daten.datei, daten.ziel, daten.gehoert_zu, rolle,
            ordner=ordner, endungen=endungen, manifest_ordner=wurzel, nach=nach,
        )
    except DownloadFehler as fehler:
        lage = {
            "laeuft_schon": status.HTTP_409_CONFLICT,
            "schon_da": status.HTTP_409_CONFLICT,
        }.get(fehler.grund, status.HTTP_400_BAD_REQUEST)
        raise HTTPException(lage, t(f"fehler.download_{fehler.grund}", sprache)) from None
    stand = _stand(download)
    assert stand is not None
    return stand


@router.delete("/download", response_model=bool, summary="Cancel the fetch")
def abbrechen(download: Modelldownload = Depends(hole_download)) -> bool:
    return download.abbrechen()


# --- Fetching the model server itself -------------------------------------


class ServerFortschritt(BaseModel):
    geladen: int
    gesamt: int
    anteil: float
    fertig: bool
    fehler: str | None = None


def hole_serverdownload(request: Request) -> Serverdownload:
    return request.app.state.serverdownload


def _serverstand(download: Serverdownload) -> ServerFortschritt | None:
    stand = download.stand()
    if stand is None:
        return None
    return ServerFortschritt(
        geladen=stand.geladen,
        gesamt=stand.gesamt,
        anteil=stand.anteil,
        fertig=stand.fertig,
        fehler=stand.fehler,
    )


@router.get(
    "/programm", response_model=ServerFortschritt | None, summary="How far the server download is"
)
def server_fortschritt(
    download: Serverdownload = Depends(hole_serverdownload),
) -> ServerFortschritt | None:
    return _serverstand(download)


@router.post("/programm", response_model=ServerFortschritt, summary="Fetch the model server")
def server_holen(
    download: Serverdownload = Depends(hole_serverdownload),
    sprache: str = Depends(hole_sprache),
) -> ServerFortschritt:
    """Fetches llama-server from the official llama.cpp release.

    The one step that used to be an instruction ("install llama.cpp") is a
    button now — a machine without the server gets it in one click, into
    the user's data folder, where the runner looks by itself.
    """
    try:
        download.starten()
    except ServerdownloadFehler as fehler:
        lage = {
            "laeuft_schon": status.HTTP_409_CONFLICT,
            "schon_da": status.HTTP_409_CONFLICT,
        }.get(fehler.grund, status.HTTP_400_BAD_REQUEST)
        raise HTTPException(
            lage, t(f"fehler.serverdownload_{fehler.grund}", sprache)
        ) from None
    stand = _serverstand(download)
    assert stand is not None
    return stand


@router.post("/folder", response_model=bool, summary="Show the model folder")
def ordner_zeigen(
    runner: Modellrunner = Depends(hole_runner),
    sprache: str = Depends(hole_sprache),
) -> bool:
    """Opens the model folder in the file manager.

    Always this one folder and never a path from outside — the request
    carries no body on purpose.
    """
    try:
        ordner_oeffnen(runner.ordner)
    except OeffnenNichtMoeglich:
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED, t("fehler.ordner_oeffnen", sprache)
        ) from None
    return True


@router.post("/begleiter-folder/{unterordner}", response_model=bool,
             summary="Show a companion folder")
def begleiterordner_zeigen(
    unterordner: Literal["mtp", "vision"],
    runner: Modellrunner = Depends(hole_runner),
    sprache: str = Depends(hole_sprache),
) -> bool:
    """Open the drafter or projector sub-folder of the model folder so a file
    can be dropped in by hand. Created if missing; the whitelist on the path is
    what keeps this from opening anything but a companion folder."""
    ordner = runner.ordner / unterordner
    ordner.mkdir(parents=True, exist_ok=True)
    try:
        ordner_oeffnen(ordner)
    except OeffnenNichtMoeglich:
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED, t("fehler.ordner_oeffnen", sprache)
        ) from None
    return True
