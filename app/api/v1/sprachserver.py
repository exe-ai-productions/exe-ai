"""The speech server, from outside — and the one door the audio goes through.

The five questions every server panel asks (what is there, is it running,
start it, stop it, show me the folder), plus the one this server exists for:
a recording in, a text out.

That last one is why the window never talks to the engine itself. The page
knows exactly one address, ``POST /transkribieren``, and what stands behind
it is this service's business — today a llama-server, tomorrow possibly a
second program for the model families it cannot read. Nothing about the
button, the recording or the panel changes when that happens.

The body arrives RAW, as ``audio/wav``: one blob, one request, no multipart
and no base64 round trip through a JSON string. The recording is made in the
one shape the engine reads (app/../frontend/src/lib/aufnahme.svelte.js), so
there is nothing to convert on the way and no decoder to ship.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from app import agentenserver, diktatsprachewahl, sprachserver, stimme
from app.api.abhaengigkeiten import hole_repositories, hole_sprache
from app.api.v1.runner import Modelldatei, _fehler
from app.db import Repositories
from app.feineinstellungen import MAX_FAEDEN, Feineinstellungen
from app.i18n import t
from app.modellrunner import RunnerFehler, passende_mmproj
from app.ordner_oeffnen import OeffnenNichtMoeglich, ordner_oeffnen

router = APIRouter(prefix="/sprachserver", tags=["sprachserver"])

# What a recording may weigh. Eight megabytes is a little over four minutes
# at the rate the recording is made in (16 kHz, mono, 16 bit — 32 KB per
# second), which is the ceiling the recorder stops itself at anyway. The
# limit is here as well because a route may be called by something that is
# not that recorder.
MAX_BYTES = 8 * 1024 * 1024

# What the panel's fields fall back to when nothing was set. Sent in the
# answer rather than written into the page, so one place decides them.
KONTEXT_VORGABE = 4096
SCHICHTEN_VORGABE = 99
# Zero means "let the engine decide", which is what it does best.
THREADS_VORGABE = 0

KONTEXT_MIN, KONTEXT_MAX = 512, 1_048_576
SCHICHTEN_MIN, SCHICHTEN_MAX = 0, 999


class Auskunft(BaseModel):
    programm: str | None = None
    ordner: str
    # Every startable file in the folder, with its size like the model
    # server's own list — the speech model AND the small text model that
    # may tidy beside it. Which is which is answered by the two picker
    # fields, never by a filter on the name: a folder the user fills has
    # no naming convention we may lean on.
    modelle: list[Modelldatei] = []
    # The projectors lying next to them. Their own list: a projector cannot
    # start, and offered as a model it would sit in the picker as an entry
    # that never answers.
    mmproj: list[str] = []
    # Which projector belongs to which model, as the start would pair them.
    # A model with no entry here starts mute, which for a speech model means
    # it cannot hear at all — so the panel says so in plain words instead of
    # letting the start fail with something about a template.
    projektoren: dict[str, str | None] = {}
    laeuft: bool = False
    modell: str | None = None
    port: int | None = None
    kontext: int | None = None
    schichten: int | None = None
    threads: int | None = None
    # Live resident memory of the running server, for the machine head's sum
    # — the same measurement the runner already keeps for itself.
    belegt_gb: float | None = None
    # The same measurement for the tidy-up server, which is a second process
    # of its own; None while it is not running.
    tidy_up_used_gb: float | None = None
    # The architecture the last start failed on because the server's build
    # does not know it.
    unknown_architecture: str | None = None
    kerne: int | None = None
    vorgaben: dict = {}
    # The works answers for the dictation fields — language, the two
    # instructions, who tidies. Sent rather than written into the page, so the
    # panel's "restore" button puts back exactly the text the service would
    # use instead of a second copy that agrees with it until one of them
    # changes.
    diktat_vorgaben: dict = {}
    # The voice samples lying in this same folder — its own list, the way
    # the projectors have theirs: a sample is not a model and cannot be
    # started, so it never belongs in "modelle".
    stimmproben: list[str] = []


class Start(BaseModel):
    modell: str = Field(min_length=1, max_length=200)
    # Its own port, because sharing one with the chat model is exactly what a
    # server of its own is for.
    port: int | None = Field(default=None, ge=1024, le=65535)
    kontext: int | None = Field(default=None, ge=KONTEXT_MIN, le=KONTEXT_MAX)
    schichten: int | None = Field(default=None, ge=SCHICHTEN_MIN, le=SCHICHTEN_MAX)
    threads: int | None = Field(default=None, ge=0, le=MAX_FAEDEN)


class SprechenAnfrage(BaseModel):
    # No length ceiling: how long a spoken answer runs is deliberately not
    # bounded by the length of its text.
    text: str = Field(min_length=1)


class Transkript(BaseModel):
    # What belongs in the input field: the tidied text where tidying
    # happened, the raw one where it did not.
    text: str
    # What the speech model actually wrote. Kept beside the finished text so
    # the difference is visible rather than claimed.
    roh: str
    bereinigt: bool = False
    # Who was asked to tidy, as it applied to THIS request. The window needs
    # it to tell "switched off" (say nothing) from "was meant to happen and
    # did not" (say so) — its own copy of the setting is as old as the last
    # time the panel was open.
    bereinigung: str = "aus"


def _runner(request: Request):
    return request.app.state.sprachrunner


def _putzrunner(request: Request):
    return request.app.state.sprachputzrunner


def _auskunft(request: Request) -> Auskunft:
    import os

    runner = _runner(request)
    lauf = runner.lauf()
    ordner = Path(runner.ordner)
    dateien = runner.modelle()
    namen = [m.name for m in dateien]
    return Auskunft(
        programm=str(runner.programm) if runner.programm else None,
        ordner=str(ordner),
        modelle=[
            Modelldatei(name=m.name, groesse_gb=m.groesse_gb) for m in dateien
        ],
        mmproj=runner.mmproj(),
        projektoren={
            name: (p.name if (p := passende_mmproj(ordner, name)) else None)
            for name in namen
        },
        laeuft=runner.laeuft(),
        modell=lauf.modell if lauf else None,
        port=lauf.port if lauf else runner.port_vorgabe,
        kontext=lauf.kontext if lauf else None,
        schichten=lauf.schichten if lauf else None,
        threads=(lauf.fein.faeden if lauf and lauf.fein else None),
        belegt_gb=runner.belegt_gb(),
        tidy_up_used_gb=_putzrunner(request).belegt_gb(),
        unknown_architecture=runner.unknown_architecture(),
        kerne=os.cpu_count(),
        vorgaben={
            "kontext": KONTEXT_VORGABE,
            "schichten": SCHICHTEN_VORGABE,
            "threads": THREADS_VORGABE,
        },
        diktat_vorgaben=diktatsprachewahl.vorgaben(),
        stimmproben=stimme.proben_auflisten(ordner),
    )


@router.get("", response_model=Auskunft, summary="Speech server — status")
def auskunft(request: Request) -> Auskunft:
    return _auskunft(request)


@router.get("/log", response_model=list[str], summary="Server messages")
def protokoll(request: Request) -> list[str]:
    return _runner(request).protokoll()


@router.post("/start", response_model=Auskunft, summary="Start the speech server")
def starten(
    daten: Start,
    request: Request,
    sprache: str = Depends(hole_sprache),
) -> Auskunft:
    fein = Feineinstellungen(faeden=daten.threads or None)
    try:
        _runner(request).starten(
            daten.modell,
            kontext=daten.kontext or KONTEXT_VORGABE,
            schichten=(
                SCHICHTEN_VORGABE if daten.schichten is None else daten.schichten
            ),
            port=daten.port,
            fein=fein,
            # No speed module here, ever: a speech model has no draft to
            # ride along, and the folder manifest may well name one for the
            # small text model lying beside it.
            drafter="",
        )
    except RunnerFehler as fehler:
        raise _fehler(fehler.grund, sprache) from None
    # Deliberately NOT registered with the discovery: this server writes down
    # speech, it does not hold a conversation. Offered in a model picker it
    # would let somebody send a chat to something that cannot answer one.
    return _auskunft(request)


@router.post("/stop", response_model=Auskunft, summary="Stop the speech server")
def stoppen(request: Request) -> Auskunft:
    _runner(request).stoppen()
    return _auskunft(request)


@router.post("/folder", response_model=bool, summary="Show the speech models")
def ordner_zeigen(request: Request, sprache: str = Depends(hole_sprache)) -> bool:
    """Its OWN folder — the one the panel reads its list from."""
    try:
        ordner_oeffnen(Path(_runner(request).ordner))
    except OeffnenNichtMoeglich:
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED, t("fehler.ordner_oeffnen", sprache)
        ) from None
    return True


def _putzziel(request: Request, wer: str) -> tuple[str, str | None] | None:
    """Which server tidies, as a base address and its key — or None when the
    one that was chosen is not up right now."""
    if wer == "putzmodell":
        putz = _putzrunner(request)
        lauf = putz.lauf()
        return (f"http://127.0.0.1:{lauf.port}/v1", putz.schluessel) if lauf else None
    if wer == "modell":
        runner = request.app.state.modellrunner
        lauf = runner.lauf()
        return (f"http://127.0.0.1:{lauf.port}/v1", runner.schluessel) if lauf else None
    if wer == "agent":
        runner = request.app.state.agentenrunner
        lauf = runner.lauf()
        port = lauf.port if lauf else agentenserver.PORT_VORGABE
        return (f"http://127.0.0.1:{port}/v1", runner.schluessel) if lauf else None
    return None


@router.post(
    "/transkribieren",
    response_model=Transkript,
    summary="Transcribe a recording (raw WAV bytes)",
)
async def transkribieren(
    request: Request,
    repositories: Repositories = Depends(hole_repositories),
    sprache: str = Depends(hole_sprache),
    # False for the reading taken while somebody is still speaking: it is
    # thrown away a second later, and a tidy-up on every one of them would
    # put a second model's answer time on top of the first one's — once a
    # second. The pass after the recording is stopped tidies as always.
    bereinigen: bool = True,
) -> Transkript:
    runner = _runner(request)
    lauf = runner.lauf()
    if lauf is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, t("fehler.sprachserver_aus", sprache)
        )
    # Read in pieces and stop at the ceiling, rather than materialising the
    # whole upload and measuring it afterwards. A limit that only speaks once
    # the payload is already in memory rejects the request but not its cost.
    stuecke: list[bytes] = []
    gelesen = 0
    async for stueck in request.stream():
        gelesen += len(stueck)
        if gelesen > MAX_BYTES:
            raise HTTPException(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                t("fehler.aufnahme_zu_gross", sprache),
            )
        stuecke.append(stueck)
    daten = b"".join(stuecke)
    if not daten:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, t("fehler.aufnahme_leer", sprache)
        )

    # Off the loop: this waits on another server for up to ZEITGRENZE, and a
    # blocking wait here is a wait for everything — a chat stream mid-answer
    # stops emitting, the runner's status polling stalls, every other request
    # queues behind one dictated sentence.
    roh = await asyncio.to_thread(
        sprachserver.transkribieren,
        lauf.port,
        runner.schluessel,
        daten,
        sprache=diktatsprachewahl.sprachcode(repositories),
        anweisung=diktatsprachewahl.anweisung(repositories),
    )
    if roh is None:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, t("fehler.sprachserver_stumm", sprache)
        )
    roh = roh.strip()

    # An empty transcription is a valid answer — that is what silence sounds
    # like — and there is nothing in it to tidy; a reading taken mid-speech
    # is not tidied either. Neither needs the setting read.
    wer = (
        diktatsprachewahl.bereinigung(repositories) if bereinigen and roh else "aus"
    )
    if wer == "aus":
        return Transkript(text=roh, roh=roh, bereinigt=False, bereinigung="aus")

    ziel = _putzziel(request, wer)
    # Off the loop for the same reason as the transcription above.
    sauber = (
        await asyncio.to_thread(
            sprachserver.bereinigen,
            ziel[0],
            ziel[1],
            diktatsprachewahl.bereinigung_anweisung(repositories),
            roh,
        )
        if ziel
        else None
    )
    if sauber is None:
        # The chosen server was off or silent. The raw text goes into the
        # field either way — it is what was said — and the answer says out
        # loud that nobody tidied it, so the window can too. Passing it off
        # as cleaned would be the one lie this route must never tell.
        return Transkript(text=roh, roh=roh, bereinigt=False, bereinigung=wer)
    return Transkript(text=sauber, roh=roh, bereinigt=True, bereinigung=wer)


@router.post(
    "/sprechen",
    summary="Convert text to speech (returns WAV bytes)",
    response_class=Response,
)
async def sprechen(
    daten: SprechenAnfrage,
    request: Request,
    repositories: Repositories = Depends(hole_repositories),
    sprache: str = Depends(hole_sprache),
) -> Response:
    # Checked before anything is resolved: a voice with nothing chosen is
    # not a failure, it is the as-installed state, and the route says so in
    # plain words rather than reaching for a program it was never told to
    # use.
    # Read once for the sentence's own fields — which voice, its language,
    # its sample. The five generation values and the memory pair come in
    # through the module's own doors below, read fresh the same way.
    wahl = diktatsprachewahl.wahl(repositories)
    gewaehlte_stimme = wahl["stimme"]
    if not gewaehlte_stimme:
        raise HTTPException(
            status.HTTP_409_CONFLICT, t("fehler.stimme_keine_stimme", sprache)
        )
    gewaehlte_sprache = wahl["stimmsprache"]
    if not gewaehlte_sprache:
        raise HTTPException(
            status.HTTP_409_CONFLICT, t("fehler.stimme_keine_sprache", sprache)
        )
    runner = _runner(request)
    ordner = Path(runner.ordner)
    # A stored setting, not something this request chooses — but stored
    # values are not trusted paths either. The same check every picker in
    # this folder is bound by: the chosen name must be one of the actual
    # models lying here, or `ordner / gewaehlte_stimme` below could walk out
    # of it (a `../` in the setting) or replace it outright (an absolute
    # path), handing llama-tts a file this request had no business naming.
    if gewaehlte_stimme not in {m.name for m in runner.modelle()}:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, t("fehler.runner_kein_modell", sprache)
        )
    programm = stimme.programm_finden(runner.programm)
    if programm is None:
        raise HTTPException(
            status.HTTP_412_PRECONDITION_FAILED, t("fehler.stimme_kein_programm", sprache)
        )
    mmproj = passende_mmproj(ordner, gewaehlte_stimme)
    if mmproj is None:
        raise HTTPException(
            status.HTTP_412_PRECONDITION_FAILED, t("fehler.stimme_kein_projektor", sprache)
        )
    # Off the loop for the same reason the transcription above is: this
    # waits on a subprocess for up to `stimme.ZEITGRENZE`, and a blocking
    # wait here is a wait for every other request too.
    schichten, faeden = diktatsprachewahl.stimmspeicher(repositories, wahl)
    try:
        wav = await asyncio.to_thread(
            stimme.sprechen,
            programm,
            ordner / gewaehlte_stimme,
            mmproj,
            daten.text,
            sprache=gewaehlte_sprache,
            ordner=ordner,
            stimmprobe=wahl["stimmprobe"] or None,
            sampling=diktatsprachewahl.stimmwerte(repositories, wahl),
            schichten=schichten,
            faeden=faeden,
        )
    except stimme.SprechenNichtMoeglich as fehler:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, t(f"fehler.{fehler.grund}", sprache)
        ) from None
    return Response(content=wav, media_type="audio/wav")
