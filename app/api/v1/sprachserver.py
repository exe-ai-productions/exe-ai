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
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from app import agentenserver, diktatsprachewahl, sprachserver, stimme, system_voice
from app.api.abhaengigkeiten import hole_repositories, hole_sprache
from app.api.v1.runner import Modelldatei, ProgramState, _fehler, program_state
from app.db import Repositories
from app.feineinstellungen import MAX_FAEDEN, Feineinstellungen
from app.i18n import t
from app.modellrunner import RunnerFehler, passende_mmproj
from app.ordner_oeffnen import OeffnenNichtMoeglich, ordner_oeffnen
from app.voice_service import HOLD_SECONDS, VoiceSpec, VoiceUnavailable
from app.voice_worker import ALL_LAYERS

log = logging.getLogger(__name__)

# Nginx's code for "the client closed the request"; nobody reads this answer.
_CLIENT_CLOSED_REQUEST = 499

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
# No layer count named: the engine places the layers itself.
SCHICHTEN_VORGABE = None
# Zero means "let the engine decide", which is what it does best.
THREADS_VORGABE = 0

KONTEXT_MIN, KONTEXT_MAX = 512, 1_048_576
SCHICHTEN_MIN, SCHICHTEN_MAX = 0, 999


class SystemVoiceInfo(BaseModel):
    """One voice of the operating system, as it is listed in the field
    "Stimme": its name and its language, both as the system gives them."""

    name: str
    language: str


class Auskunft(ProgramState):
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
    # The size in gigabytes of each projector in the folder, by name, as the
    # model server's answer carries it — what the memory estimate adds when
    # the chosen model starts with its projector.
    projector_size_gb: dict[str, float] = {}
    laeuft: bool = False
    modell: str | None = None
    # What a start would load: the stored choice, apart from `modell`, which
    # stays the file that runs. None where nothing is chosen.
    selected_model: str | None = None
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
    # How long each of them is, in seconds — read from the file's header; a
    # file laid out otherwise has no entry. The window shows it behind the
    # chosen sample's name.
    stimmproben_dauer: dict[str, float | None] = {}
    # The voices the system itself brings (a Mac's `say`, Windows' speech
    # synthesis; none on Linux), listed after the voice models in the field
    # "Stimme".
    system_voices: list[SystemVoiceInfo] = []


class Stimmprobe(BaseModel):
    """A recording that was just kept as a voice sample."""

    name: str
    seconds: float | None = None


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
    repositories = request.app.state.repositories
    lauf = runner.shown_run()
    ordner = Path(runner.ordner)
    dateien = runner.modelle()
    namen = [m.name for m in dateien]
    return Auskunft(
        **program_state(runner, request.app.state.config),
        ordner=str(ordner),
        modelle=[
            Modelldatei(name=m.name, groesse_gb=m.groesse_gb) for m in dateien
        ],
        mmproj=runner.mmproj(),
        projector_size_gb=runner.projector_sizes(),
        projektoren={
            name: (p.name if (p := runner.projektor_fuer(name)) else None)
            for name in namen
        },
        laeuft=lauf is not None,
        modell=lauf.modell if lauf else None,
        selected_model=(
            stored
            if (stored := diktatsprachewahl.sprachstart(repositories)["modell"]) in namen
            else (namen[0] if namen else None)
        ),
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
        stimmproben=(proben := stimme.proben_auflisten(ordner)),
        stimmproben_dauer={name: stimme.probe_dauer(ordner / name) for name in proben},
        system_voices=[
            SystemVoiceInfo(name=voice.name, language=voice.language)
            for voice in system_voice.list_voices()
        ],
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
    repositories: Repositories = Depends(hole_repositories),
    sprache: str = Depends(hole_sprache),
) -> Auskunft:
    # What the request does not name comes from the stored start values
    # (the window writes them as they are touched), then from the works
    # answers — one read of the setting for all of it.
    gespeichert = diktatsprachewahl.sprachstart(repositories)
    threads = gespeichert["threads"] if daten.threads is None else daten.threads
    # The idle time is named only while the model is not kept in memory
    # (``sprachstart`` decides); it is a start value of the engine.
    fein = Feineinstellungen(faeden=threads or None, idle_minutes=gespeichert["leerlauf"])
    try:
        _runner(request).starten(
            daten.modell,
            kontext=daten.kontext or gespeichert["kontext"],
            schichten=(
                gespeichert["schichten"] if daten.schichten is None else daten.schichten
            ),
            port=daten.port or gespeichert["port"],
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
def stoppen(request: Request, sprache: str = Depends(hole_sprache)) -> Auskunft:
    try:
        _runner(request).refuse_stop_when_shared()
    except RunnerFehler as fehler:
        raise _fehler(fehler.grund, sprache) from None
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


def _stimmprobe_waehlen(repositories: Repositories, name: str) -> None:
    """Stores which voice sample the voice speaks with ('' for none), through
    the same check and the same merge the settings route uses."""
    repositories.einstellungen.zusammenlegen(
        "global", diktatsprachewahl.SCHLUESSEL, {"stimmprobe": name},
        pruefen=diktatsprachewahl.wahl_pruefen,
    )


@router.post(
    "/voice-sample",
    response_model=Stimmprobe,
    summary="Keep a recording as a voice sample (raw WAV bytes)",
)
async def stimmprobe_sichern(
    request: Request,
    repositories: Repositories = Depends(hole_repositories),
    sprache: str = Depends(hole_sprache),
) -> Stimmprobe:
    """The recording lands in the speech model folder as ``stimmprobe-N.wav``
    with the next free number and is chosen as the voice sample at once."""
    daten = await _aufnahme_lesen(request, sprache)
    ordner = Path(_runner(request).ordner)

    def ablegen() -> Stimmprobe:
        name = stimme.probe_sichern(ordner, daten)
        _stimmprobe_waehlen(repositories, name)
        return Stimmprobe(name=name, seconds=stimme.probe_dauer(ordner / name))

    try:
        # Off the loop: a file is written and a setting stored.
        return await asyncio.to_thread(ablegen)
    except stimme.SprechenNichtMoeglich as fehler:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, t(f"fehler.{fehler.grund}", sprache)
        ) from None


@router.get("/voice-sample/{name}", summary="The voice sample as a WAV")
def stimmprobe_liefern(
    name: str, request: Request, sprache: str = Depends(hole_sprache)
) -> Response:
    try:
        pfad = stimme.probe_pfad(Path(_runner(request).ordner), name)
    except stimme.SprechenNichtMoeglich as fehler:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, t(f"fehler.{fehler.grund}", sprache)
        ) from None
    return Response(content=pfad.read_bytes(), media_type="audio/wav")


@router.delete(
    "/voice-sample/{name}",
    response_model=Auskunft,
    summary="Delete a voice sample",
)
def stimmprobe_loeschen(
    name: str,
    request: Request,
    repositories: Repositories = Depends(hole_repositories),
    sprache: str = Depends(hole_sprache),
) -> Auskunft:
    """The file goes; where it was the chosen sample, the choice goes with it
    — first, so a choice never points at a file that is gone."""
    ordner = Path(_runner(request).ordner)
    try:
        pfad = stimme.probe_pfad(ordner, name)
    except stimme.SprechenNichtMoeglich as fehler:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, t(f"fehler.{fehler.grund}", sprache)
        ) from None
    if diktatsprachewahl.stimmprobe(repositories) == name:
        _stimmprobe_waehlen(repositories, "")
    pfad.unlink()
    return _auskunft(request)


async def _aufnahme_lesen(request: Request, sprache: str) -> bytes:
    """The raw recording of a request: read in pieces up to the ceiling, so a
    limit does not speak only once the whole upload is in memory. Empty and
    over-long recordings are refused here, for every route that takes one."""
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
    return daten


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
    daten = await _aufnahme_lesen(request, sprache)

    # Off the loop: this waits on another server for up to ZEITGRENZE, and a
    # blocking wait here is a wait for everything — a chat stream mid-answer
    # stops emitting, the runner's status polling stalls, every other request
    # queues behind one dictated sentence.
    try:
        roh = await asyncio.to_thread(
            sprachserver.transkribieren,
            lauf.port,
            runner.schluessel,
            daten,
            sprache=diktatsprachewahl.sprachcode(repositories),
            anweisung=diktatsprachewahl.anweisung(repositories),
        )
    except sprachserver.SpeechServerError as fehler:
        # It answered, and said why it refused: the person reads that, not
        # that it was silent.
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            t("fehler.speech_server_reported", sprache, reason=fehler.reason),
        ) from None
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


@dataclass(frozen=True)
class _VoiceFiles:
    """What a sentence needs to be spoken: the program, the folder, the
    chosen voice and its projector, and the settings it was read from."""

    programm: Path
    ordner: Path
    stimme: str
    mmproj: Path
    sprache: str
    wahl: dict


def _voice_files(
    request: Request, repositories: Repositories, sprache: str
) -> _VoiceFiles:
    """Resolves the chosen voice, or refuses in the words of the page's own
    language — the same refusals whoever asks (the sentence itself, or the
    announcement of a conversation)."""
    # Checked before anything is resolved: a voice with nothing chosen is
    # not a failure, it is the as-installed state, and the route says so in
    # plain words rather than reaching for a program it was never told to
    # use.
    # Read once for the sentence's own fields — which voice, its language,
    # its sample. The five generation values and the memory pair come in
    # through the module's own doors, read fresh the same way.
    wahl = diktatsprachewahl.wahl(repositories)
    gewaehlte_stimme = wahl["stimme"]
    if not gewaehlte_stimme:
        raise HTTPException(
            status.HTTP_409_CONFLICT, t("fehler.stimme_keine_stimme", sprache)
        )
    # An empty language is "-": the voice model takes its own.
    gewaehlte_sprache = wahl["stimmsprache"]
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
    return _VoiceFiles(programm, ordner, gewaehlte_stimme, mmproj, gewaehlte_sprache, wahl)


def _voice_spec(
    request: Request, files: _VoiceFiles, repositories: Repositories
) -> VoiceSpec | None:
    """What the kept voice would be loaded with, or None where it cannot be
    kept: the engine's own copy is not there yet (asking for it starts its
    fetch), or the sample is refused."""
    library_dir = request.app.state.voice_library.directory()
    if library_dir is None:
        return None
    sample = None
    if files.wahl["stimmprobe"]:
        try:
            sample = str(stimme.sample_path(files.ordner, files.wahl["stimmprobe"]))
        except stimme.SprechenNichtMoeglich:
            return None
    layers, threads = diktatsprachewahl.stimmspeicher(repositories, files.wahl)
    return VoiceSpec(
        library_dir=str(library_dir),
        model=str(files.ordner / files.stimme),
        mmproj=str(files.mmproj),
        speaker=sample,
        # No count named: the C interface has no auto, so all layers.
        gpu_layers=ALL_LAYERS if layers is None else layers,
        threads=threads,
    )


class VoiceHold(BaseModel):
    # Whether the voice is kept for this conversation. False is no failure:
    # the pieces are spoken one start each, as with the switch off.
    kept: bool


@router.post(
    "/voice/hold",
    summary="Announce a conversation: keep the voice loaded for it",
    response_model=VoiceHold,
)
async def voice_hold(
    request: Request,
    repositories: Repositories = Depends(hole_repositories),
    sprache: str = Depends(hole_sprache),
) -> VoiceHold:
    """Sent when a conversation begins and repeated while it lasts. The
    first one loads the voice (in the background, the answer does not wait
    for it); each one holds it a little longer. Where the voice cannot be
    kept — a switch is off, nothing chosen, the engine's own copy is still
    being fetched — the answer says so and the pieces go the plain way."""
    service = request.app.state.voice_service
    wahl = diktatsprachewahl.wahl(repositories)
    # Nothing is read aloud without the first switch, so nothing is kept
    # loaded for it either.
    if not wahl["vorlesen"] or not diktatsprachewahl.keep_model_in_memory(repositories, wahl):
        await asyncio.to_thread(service.release)
        return VoiceHold(kept=False)
    # A voice that failed in this conversation is not kept loaded again: the
    # voice of the system speaks the pieces until the conversation is over.
    if _fallback_active(request, wahl["stimme"]):
        return VoiceHold(kept=False)
    try:
        files = _voice_files(request, repositories, sprache)
    except HTTPException:
        return VoiceHold(kept=False)
    spec = _voice_spec(request, files, repositories)
    if spec is None:
        return VoiceHold(kept=False)
    await asyncio.to_thread(service.hold, spec)
    return VoiceHold(kept=True)


@router.post(
    "/voice/release",
    summary="The conversation is over: give the voice back",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def voice_release(request: Request) -> Response:
    # The voice of the system that stood in for a failed voice stops standing
    # in: the next conversation asks the chosen voice again.
    request.app.state.voice_fallback = None
    await asyncio.to_thread(request.app.state.voice_service.release)
    request.app.state.voice_library.conversation_over()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _until_gone(
    request: Request, work: asyncio.Task, cancel: threading.Event
) -> None:
    """Waits for ``work``, or for the one who asked to be gone — then sets
    ``cancel``. Listens on the request's own channel rather than asking
    ``request.is_disconnected()``: that one cannot see a departure through the
    middleware that wraps this service."""
    listening = asyncio.create_task(request.receive())
    try:
        while True:
            await asyncio.wait({work, listening}, return_when=asyncio.FIRST_COMPLETED)
            if work.done():
                return
            if listening.result().get("type") == "http.disconnect":
                cancel.set()
                return
            listening = asyncio.create_task(request.receive())
    finally:
        listening.cancel()


def _fallback_active(request: Request, chosen: str) -> bool:
    """Whether the voice of the system stands in for the chosen voice, which
    failed earlier in this conversation. Like the kept voice, it holds as long
    as the conversation announces itself: every piece and every announcement
    holds it a little longer, and a conversation whose page went away without
    ending it lets it go when that time runs out."""
    state = getattr(request.app.state, "voice_fallback", None)
    if state is None or state[0] != chosen or time.monotonic() >= state[1]:
        return False
    request.app.state.voice_fallback = (chosen, time.monotonic() + HOLD_SECONDS)
    return True


def _fallback_start(request: Request, chosen: str) -> None:
    request.app.state.voice_fallback = (chosen, time.monotonic() + HOLD_SECONDS)


def _fallback_voice() -> str | None:
    """The voice of the system that speaks when the chosen one cannot: the one
    this machine starts with, and where the system does not have it, the voice
    the system itself uses (an empty name). None where the system has no
    voice at all."""
    if not system_voice.available():
        return None
    factory = system_voice.factory_voice()
    return factory if system_voice.has_voice(factory) else system_voice.default_voice()


async def _finish(
    request: Request, speaking: asyncio.Task, cancel: threading.Event, sprache: str
) -> Response:
    """Waits for the piece being spoken in its own thread and answers it. A
    request that is given up (a conversation that ended while its sentence was
    being made) ends the program too: nobody waits for the sound, and the model
    it loads is a gigabyte or two."""
    try:
        await _until_gone(request, speaking, cancel)
        wav = await speaking
    except stimme.SpeakCancelled:
        return Response(status_code=_CLIENT_CLOSED_REQUEST)
    except asyncio.CancelledError:
        # The server gave the request up itself: the program goes with it,
        # and nobody is left to read how it ended.
        cancel.set()
        speaking.add_done_callback(lambda task: task.cancelled() or task.exception())
        raise
    except stimme.SprechenNichtMoeglich as fehler:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, t(f"fehler.{fehler.grund}", sprache)
        ) from None
    return Response(content=wav, media_type="audio/wav")


async def _speak_with_system(
    request: Request, text: str, voice: str, sprache: str
) -> Response:
    """The piece, spoken by a voice of the system. Off the loop: it waits on a
    program."""
    cancel = threading.Event()
    speaking = asyncio.create_task(
        asyncio.to_thread(system_voice.speak, text, voice, cancel=cancel)
    )
    return await _finish(request, speaking, cancel, sprache)


async def _speak_with_fallback(
    request: Request, text: str, chosen: str, reason: str, sprache: str,
    refusal: HTTPException | None = None,
) -> Response:
    """The chosen voice cannot speak — its file is gone, its program or
    projector is missing, it failed, or the voice of the system is not on this
    machine — so the voice of the system speaks this piece and every following
    one of the conversation: a voice that failed once is not asked again until
    the conversation is over (``voice_release``). The reason is told on
    WARNING. Where the system has no voice, the refusal stands."""
    # Off the loop: the list of voices may have to be asked of the system.
    voice = await asyncio.to_thread(_fallback_voice)
    if voice is None:
        raise refusal or HTTPException(
            status.HTTP_409_CONFLICT, t("fehler.stimme_keine_stimme", sprache)
        )
    _fallback_start(request, chosen)
    log.warning(
        "The voice %r cannot speak (%s); the voice of the system speaks (%s)",
        chosen, reason, voice or "default",
    )
    return await _speak_with_system(request, text, voice, sprache)


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
    chosen = diktatsprachewahl.wahl(repositories)["stimme"]
    # "-" is no voice chosen: said in plain words, nothing is reached for.
    if not chosen:
        raise HTTPException(
            status.HTTP_409_CONFLICT, t("fehler.stimme_keine_stimme", sprache)
        )
    models = {m.name for m in _runner(request).modelle()}
    # Which way speaks follows from the chosen name: a voice model of the
    # speech folder, or a voice of the system.
    if chosen not in models:
        if await asyncio.to_thread(system_voice.has_voice, chosen):
            return await _speak_with_system(request, daten.text, chosen, sprache)
        return await _speak_with_fallback(request, daten.text, chosen, "voice not found", sprache)
    if _fallback_active(request, chosen):
        # The expected type of the call would otherwise be read from the
        # `or ""` around it, so the result is named first.
        fallback_voice = await asyncio.to_thread(_fallback_voice)
        return await _speak_with_system(request, daten.text, fallback_voice or "", sprache)
    try:
        files = _voice_files(request, repositories, sprache)
    except HTTPException as refusal:
        return await _speak_with_fallback(
            request, daten.text, chosen, f"program or projector missing ({refusal.status_code})",
            sprache, refusal,
        )
    # Off the loop for the same reason the transcription above is: this
    # waits on a subprocess for up to `stimme.ZEITGRENZE`, and a blocking
    # wait here is a wait for every other request too.
    schichten, faeden = diktatsprachewahl.stimmspeicher(repositories, files.wahl)
    sampling = diktatsprachewahl.stimmwerte(repositories, files.wahl)
    # In a conversation with the voice kept: the loaded voice speaks the
    # piece. A piece it does not bring out is spoken by the program below,
    # and so is each one after it until the conversation is over.
    service = request.app.state.voice_service
    if diktatsprachewahl.keep_model_in_memory(repositories, files.wahl) and service.active():
        spec = _voice_spec(request, files, repositories)
        if spec is not None:
            try:
                await asyncio.to_thread(service.hold, spec)
                wav = await asyncio.to_thread(
                    service.speak, daten.text, language=files.sprache, sampling=sampling,
                )
                return Response(content=wav, media_type="audio/wav")
            except VoiceUnavailable as fehler:
                log.info("The kept voice did not speak (%s); llama-tts speaks", fehler.reason)
    cancel = threading.Event()
    speaking = asyncio.create_task(
        asyncio.to_thread(
            stimme.sprechen,
            files.programm,
            files.ordner / files.stimme,
            files.mmproj,
            daten.text,
            sprache=files.sprache,
            ordner=files.ordner,
            stimmprobe=files.wahl["stimmprobe"] or None,
            sampling=sampling,
            schichten=schichten,
            faeden=faeden,
            cancel=cancel,
        )
    )
    try:
        return await _finish(request, speaking, cancel, sprache)
    except HTTPException as refusal:
        # llama-tts failed or ran out of time: the voice of the system speaks
        # this piece, where the system has one.
        return await _speak_with_fallback(
            request, daten.text, chosen, "llama-tts failed", sprache, refusal,
        )
