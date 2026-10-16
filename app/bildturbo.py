"""Image-Turbo: an optional persistent sd-server, so the model stays loaded.

sd-cli is the default and always works — one model load per picture. That is
right for the occasional picture, and it is what ships on. Image-Turbo is the
speed-up somebody switches on: sd-server holds the model in memory, and every
picture after the first is drawn without paying the load again. Measured on
build 820: ~12 s against ~32 s for the same SD-1.5 512 picture. Measured
again on build 920, with flash attention on both paths and the model file
already in the system's cache: 17.2 s for a warm draw against 18.1 s for a
whole sd-cli run — the load it saves is what a model costs to read, and a
small, cached one costs little.

The same split the embedding server uses, and for the same reason — a speed-up,
never a dependency:

* running     → the picture comes over HTTP, the model already in memory
* not running → sd-cli draws it, exactly as before

Its own everything: its own port, its own note file, and its own binary
(``sd-server``, which sits next to ``sd-cli`` in the fetched build). Nothing is
shared, so nothing collides.

It speaks only the server's own interface: a picture is handed in at
``/sdcpp/v1/img_gen``, which answers at once with a job, and the finished
picture is fetched from ``/sdcpp/v1/jobs/{id}``. That interface carries every
per-picture value sd-cli knows except the live preview and PuLID, so only the
model and its companions bind the server at start.
"""

from __future__ import annotations

import base64
import io
import logging
import os
import re
import subprocess
import sys
import threading
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path

import httpx

import inspect

from app import bildbausatz, image_switches, prozessstopp
from app.no_console import no_window
from app.photomaker import fingerabdruck as foto_fingerabdruck
from app.pipe_text import live_text
from app.prozessspeicher import rss_gb
from app.sddownload import ORDNER, gefundenes_programm

# The lines the server window shows: as many as the chat runner keeps
# (app/modellrunner.py), the oldest dropped first.
PROTOKOLL_ZEILEN = 400

log = logging.getLogger(__name__)

# The persistent server binary — the sibling of sd-cli in the same build.
PROGRAMM = "sd-server.exe" if sys.platform == "win32" else "sd-server"

# The note that finds an orphan again after a service restart. Its own name,
# so it never erases the model server's or the embedding server's — and its
# own name PER INSTANCE, because the data folder is shared between them.
#
# One name for all of them was a loaded gun. Every start reads this file and
# sends a signal to whatever it names, so a second instance of the program
# read the FIRST one's process id and killed a picture server that was busy
# drawing for somebody else. The app's own port is what tells two instances
# apart — it is the one thing they cannot share.
PID_DATEI = ".bildturbo.pid"


def pid_dateiname(app_port: int | None) -> str:
    """The note's name for one instance of the program.

    Without a port the plain name stands, which keeps every existing
    installation finding the orphan it wrote before this existed.
    """
    return PID_DATEI if not app_port else f".bildturbo-{int(app_port)}.pid"

# The port Image-Turbo listens on — its own, away from the model server (8080),
# the embedding server and the app itself.
#
# And its own per instance, for the same reason as the note above: two
# programs on one machine cannot both have 8191, and the one that starts
# second used to take the first one's server down to get it. The offset from
# the app's own port carries the instance identity, so a trial run beside the
# running program lands beside it here too.
PORT = 8191


def port_fuer(app_port: int | None, standard_app_port: int = 8090) -> int:
    """This instance's picture-server port.

    The shipped app port keeps the shipped picture port, so nothing moves for
    an ordinary installation. Anything else is carried along by the same
    distance it sits from the shipped one.
    """
    if not app_port or int(app_port) == standard_app_port:
        return PORT
    return PORT + (int(app_port) - standard_app_port)

# How long to wait for the model to load before calling the start a failure.
# A big SDXL checkpoint on a cold cache takes a while; too short a wait would
# report a red lamp on a server that was only still loading.
STARTFRIST = 120.0
# A Bausatz assembles a much heavier load — a Flux Gespann is a ~13 GB
# diffusion model plus a ~5 GB T5 text encoder. The plain STARTFRIST above
# would report a red lamp on a server that is only still loading.
STARTFRIST_BAUSATZ = 600.0


def start_deadline(*parts: object) -> float:
    """How long a server may load before its start counts as failed.

    ``parts`` are the files it was started with beside its model: the
    diffusion model, the text encoders, the VAE and the further kit parts.
    One of them set is enough for the long wait — the server loads every
    file it is given before it answers for the first time, whichever switch
    the model itself came in by. A model on its own keeps the short one.
    """
    return STARTFRIST_BAUSATZ if any(parts) else STARTFRIST


# The files a server loads beside its model, by the name a draw order carries
# each under; the server keeps what it was started with under the same name
# behind an underscore. Named here once, read by the route and by the server.
START_PARTS = (
    "diffusion_model", "vae", "t5xxl", "clip_l", "clip_g", "llm",
    "llm_vision", "tokenizer", "uncond_diffusion_model",
)


def start_parts(holder: object, video_parts: object, prefix: str = "") -> tuple[object, ...]:
    """What ``holder`` starts a server with beside its model: each of
    ``START_PARTS`` as it holds it — a draw order under the plain name, the
    server behind ``prefix`` — and the video kits' further parts, which
    travel as one bundle. This is what ``start_deadline`` is asked with."""
    return (*(getattr(holder, prefix + name) for name in START_PARTS), video_parts)


# How often a job is asked for its state while it draws. The step bar on the
# server's stdout already feeds the progress frame, so this only has to
# notice the end: a quarter second is below what anybody sees against a
# picture that takes ten seconds or more.
POLL_INTERVAL = 0.25

# The same step bar sd-cli prints — sd-server writes it to its stdout too,
# so the filling frame gets its honest number on the turbo path as well.
# Only bars that count iterations ("it/s", "s/it") are taken: the bars
# drawn while weights are loaded count megabytes and are no steps. The
# pattern's other half is the server's own word that a picture's painting
# begins (third group).
_SCHRITT_MUSTER = re.compile(
    r"\|\s*(\d+)/(\d+)\s*-\s*[\d.]+(?:s/it|it/s)|(generating image:)"
)


def programm_finden(datenordner: Path, variante: str | None = None) -> Path | None:
    """The sd-server binary, or nothing if this machine has none.

    Only the fetched build is looked at — sd-server is not a thing people put
    on their PATH the way they might sd-cli, and it must be the same build as
    the sd-cli that drew the one-shot pictures, or the two would disagree: it
    is taken from the folder that sd-cli starts from, never from another
    build folder that happens to stand beside it. One put loose in the bare
    folder by hand goes first, as it always did. ``variante`` is the variant
    of the program the user picked, which the build folders keep to.
    """
    wurzel = Path(datenordner).expanduser() / ORDNER
    if not wurzel.is_dir():
        return None
    direkt = wurzel / PROGRAMM
    if direkt.is_file() and os.access(direkt, os.X_OK):
        return direkt
    cli = gefundenes_programm(datenordner, variante)
    if cli is not None:
        neben = cli.parent / PROGRAMM
        return neben if neben.is_file() and os.access(neben, os.X_OK) else None
    for treffer in sorted(wurzel.rglob(PROGRAMM)):
        if treffer.is_file() and os.access(treffer, os.X_OK):
            return treffer
    return None


# How much of the picture server's own answer travels into an error message.
# Its failures are one short JSON line ({"error":"invalid lora path: …"}); the
# cap is there so a server answering with a page or a stack trace cannot push
# a wall of text into the window.
ANTWORTTEXT_GRENZE = 400


def _part_names(parts: dict | None) -> tuple[tuple[str, str], ...]:
    """Kit parts as (field, file name), sorted — what a running server is
    compared by."""
    return tuple(sorted((field, Path(path).name) for field, path in (parts or {}).items() if path))


class BildturboFehler(Exception):
    """Carries the key of the sentence to show, not the sentence itself.

    ``protokoll`` optionally carries the picture SERVER's own last words --
    the status and body it refused the request with -- shown verbatim below
    that sentence, exactly as the sd-cli path shows the painter's stderr
    (``bildrunner.BildFehler``). Without it every failure of the fast path
    reads "the picture could not be drawn" and the one line that explains it
    ("invalid lora path: x.safetensors") is thrown away.
    """

    def __init__(self, grund: str, protokoll: str | None = None) -> None:
        super().__init__(grund)
        self.grund = grund
        self.protokoll = protokoll


def _antworttext(antwort: httpx.Response) -> str:
    """One answer of the picture server, short enough to show or log.

    Only the status line and the body it sent back -- no request, no
    headers, no URL: what leaves this module has to be the server's own
    explanation of the refusal and nothing that merely travelled alongside
    it. Both callers are local-only traffic to 127.0.0.1, so the body holds
    the generator's words about model and LoRA files, nothing of the user's.
    """
    kopf = f"HTTP {antwort.status_code}"
    try:
        text = (antwort.text or "").strip()
    except Exception:  # noqa: BLE001 - unread or undecodable body: the status alone
        return kopf
    if not text:
        return kopf
    if len(text) > ANTWORTTEXT_GRENZE:
        text = text[:ANTWORTTEXT_GRENZE] + " …"
    return f"{kopf} {text}"


def _serverwort(fehler: httpx.HTTPError) -> str | None:
    """The server's own answer to a failed request, or None when there is
    none to quote -- a connection error never carried one."""
    antwort = getattr(fehler, "response", None)
    return _antworttext(antwort) if antwort is not None else None


class Bildturbo:
    """One persistent picture server, switched on and off by hand."""

    def __init__(
        self,
        datenordner: Path,
        app_port: int | None = None,
        fassung: Callable[[], str | None] | None = None,
    ) -> None:
        self._datenordner = Path(datenordner).expanduser()
        # Asked per start: the variant of the program the user picked.
        self._fassung = fassung or (lambda: None)
        # Which instance of the program this belongs to. The data folder is
        # shared between instances, so the port is what keeps their notes and
        # their servers apart.
        self._app_port = app_port
        self._port = port_fuer(app_port)
        self._prozess: subprocess.Popen | None = None
        self._modell: str | None = None
        # What the server says, for the window's server log — the same ring
        # buffer every other server keeps, filled by the one stdout reader.
        self._protokoll: deque[str] = deque(maxlen=PROTOKOLL_ZEILEN)
        # The rest of the harness the server was started with — the "Gespann".
        # VAE and detector bind at start (they are start flags, not per-request
        # HTTP fields), so a request that wants a different one needs a fresh
        # server. The LoRA and embedding folders bind at start the same way
        # (``--lora-model-dir``, ``--embd-dir``) — only the LoRA a prompt
        # picks travels per request, the folder it is resolved against does
        # not, so a folder change still needs a fresh server.
        self._vae: str | None = None
        self._ad_modell: str | None = None
        self._ad_prompt: str = ""
        # The detailer's negative prompt and detection threshold — start
        # flags exactly like the detailer's own prompt above, and like it
        # only meaningful while a detector is set at all.
        self._ad_negativ: str = ""
        self._ad_confidence: float | None = None
        # --prediction override; empty means the flag was never sent and
        # the server derives the type from the model, its own default.
        self._prediction: str = ""
        # The ControlNet model is a start flag like the VAE: the picture that
        # steers it travels per request, the network itself does not.
        self._control_net: str | None = None
        # The model-backed upscaler folder (--hires-upscalers-dir), pointed
        # at like the LoRA folder below: whenever it is given, even when the
        # first picture uses no model upscaler, so later requests on this
        # same server can still name one per request (hr_upscaler travels
        # per request, the folder it resolves against does not).
        self._upscaler_ordner: str | None = None
        self._lora_ordner: str | None = None
        self._lora_apply_mode: str = "auto"
        # Has THIS server ever answered? Popen returns long before the server
        # binds its port (measured: 0.14 s for a 7 GB SDXL on build 820, 0.13 s
        # for an SD-1.5 on build 920), and
        # a draw sent into that gap dies on a plain connection refusal. The
        # flag is what keeps the guard in ``zeichnen`` free afterwards: asked
        # once per server, never again. Cleared in ``starten`` and
        # ``_stoppen_intern``.
        self._war_bereit: bool = False
        self._embd_ordner: str | None = None
        # A Bausatz's files: --diffusion-model and its text encoder(s) are
        # start flags too, so a change here — a family switch, or swapping
        # one file for another — means a fresh server, same as the VAE.
        self._diffusion_model: str | None = None
        self._t5xxl: str | None = None
        self._clip_l: str | None = None
        self._clip_g: str | None = None
        self._llm: str | None = None
        self._vae_format: str = ""
        # The further kit parts and --model-args: start flags as well.
        self._llm_vision: str | None = None
        self._tokenizer: str | None = None
        self._uncond_diffusion_model: str | None = None
        # The video kits' further parts (bildbausatz.PART_SWITCHES), each
        # as (field, file name).
        self._video_parts: tuple[tuple[str, str], ...] = ()
        self._model_args: str = ""
        # Memory & devices: --rng, --type, --threads, --max-vram and
        # --offload-to-cpu are all start flags too, same rule as everything
        # above.
        self._rng: str = "cuda"
        self._weight_type: str = ""
        self._threads: int = -1
        self._vram_limit: str = ""
        self._offload_to_cpu: bool = False
        self._split_mode: str = ""
        self._backend: str = ""
        # The further switches of ``app.image_switches`` the server can only
        # take at start, as the flags they became, and the detailer's further
        # key=value values beside its threshold.
        self._extra_start: tuple[str, ...] = ()
        self._ad_extra: str = ""
        # PhotoMaker, same rule as VAE and the detector: --photo-maker and
        # --pm-id-images-dir are start flags too, so a change here also means
        # a fresh server. The class word is NOT here —
        # it travels in the prompt, exactly like a LoRA does. The folder
        # itself is compared by a fingerprint of its photos, not its name —
        # the name is always "faces" (app.bildwahlen.GESICHTER_ORDNER),
        # so swapping the photos in place would otherwise never be noticed.
        self._photomaker: str | None = None
        self._gesichter_fingerabdruck: str | None = None
        self._zeichnet = False
        # Set by ``abbrechen`` so the draw it interrupts reports itself as a
        # silent stop, not a failure.
        self._abgebrochen = False
        # The job the running draw waits for, so a stop can name it. The
        # small lock makes "a stop arrived" and "the job got its id" one
        # step each, so exactly one side acts on a stop pressed while the
        # job is being handed in.
        self._job: str | None = None
        self._stop_lock = threading.Lock()
        # Has THIS server drawn a picture yet? Its weights are read by the
        # first draw, not at start (see ``bereit_abwarten``), so only a
        # server that has drawn holds its model files in memory.
        self._weights_loaded = False
        # The whole start call of the running server, kept so the server can
        # step aside for one sd-cli picture and come back exactly as it was.
        self._start_values: tuple[tuple, dict] | None = None
        # The label of the control whose value sent the picture the server
        # stepped aside for to sd-cli; set only while the server is paused.
        self._paused_for: str | None = None
        self._schloss = threading.Lock()
        self._pid_datei = self._datenordner / pid_dateiname(app_port)
        # The running picture's honest step counter, fed by the stdout reader.
        # None whenever no picture is in flight — the loader prints bars too,
        # so counting is armed per request (``_zaehl``) and disarmed after.
        self._fortschritt: dict | None = None
        self._zaehl: dict | None = None

    @property
    def programm(self) -> Path | None:
        return programm_finden(self._datenordner, self._fassung())

    @property
    def modell(self) -> str | None:
        return self._modell if self.laeuft() else None

    # The rest of the running Gespann, read back the same way — None while
    # nothing runs, so the window's own restart pill (is what I am about to
    # send different from what is actually loaded?) has something honest to
    # compare against instead of showing whenever Turbo merely happens to be
    # on, which is the exact "control that lies" this exists to replace.
    @property
    def vae(self) -> str | None:
        return self._vae if self.laeuft() else None

    @property
    def ad_modell(self) -> str | None:
        return self._ad_modell if self.laeuft() else None

    @property
    def ad_prompt(self) -> str:
        return self._ad_prompt if self.laeuft() else ""

    @property
    def ad_negativ(self) -> str:
        return self._ad_negativ if self.laeuft() else ""

    @property
    def ad_confidence(self) -> float | None:
        return self._ad_confidence if self.laeuft() else None

    @property
    def prediction(self) -> str:
        return self._prediction if self.laeuft() else ""

    @property
    def control_net(self) -> str | None:
        return self._control_net if self.laeuft() else None

    # The Bausatz files the server runs with, for the same restart pill —
    # `passt_zu()` has compared them since the Bausatz arrived; these read
    # them back so the window can warn BEFORE a draw pays the restart.
    @property
    def diffusion_model(self) -> str | None:
        return self._diffusion_model if self.laeuft() else None

    @property
    def t5xxl(self) -> str | None:
        return self._t5xxl if self.laeuft() else None

    @property
    def clip_l(self) -> str | None:
        return self._clip_l if self.laeuft() else None

    @property
    def clip_g(self) -> str | None:
        return self._clip_g if self.laeuft() else None

    @property
    def llm(self) -> str | None:
        return self._llm if self.laeuft() else None

    @property
    def photomaker(self) -> str | None:
        return self._photomaker if self.laeuft() else None

    @property
    def vae_format(self) -> str:
        return self._vae_format if self.laeuft() else ""

    @property
    def rng(self) -> str:
        return self._rng if self.laeuft() else "cuda"

    @property
    def weight_type(self) -> str:
        return self._weight_type if self.laeuft() else ""

    @property
    def threads(self) -> int:
        return self._threads if self.laeuft() else -1

    @property
    def vram_limit(self) -> str:
        return self._vram_limit if self.laeuft() else ""

    @property
    def offload_to_cpu(self) -> bool:
        return self._offload_to_cpu if self.laeuft() else False

    @property
    def split_mode(self) -> str:
        return self._split_mode if self.laeuft() else ""

    @property
    def backend(self) -> str:
        return self._backend if self.laeuft() else ""

    @property
    def weights_loaded(self) -> bool:
        return self._weights_loaded if self.laeuft() else False

    def laeuft(self) -> bool:
        return self._prozess is not None and self._prozess.poll() is None

    def passt_zu(
        self,
        modell: str,
        vae: str | None = None,
        ad_modell: str | None = None,
        ad_prompt: str = "",
        ad_negativ: str = "",
        ad_confidence: float | None = None,
        prediction: str = "",
        control_net: str | None = None,
        upscaler_ordner: Path | None = None,
        photomaker: str | None = None,
        gesichter_fingerabdruck: str | None = None,
        lora_ordner: Path | None = None,
        lora_apply_mode: str = "at_runtime",
        lora_aktiv: bool = False,
        embd_ordner: Path | None = None,
        diffusion_model: str | None = None,
        t5xxl: str | None = None,
        clip_l: str | None = None,
        clip_g: str | None = None,
        llm: str | None = None,
        vae_format: str = "",
        llm_vision: str | None = None,
        tokenizer: str | None = None,
        uncond_diffusion_model: str | None = None,
        model_args: str = "",
        rng: str = "cuda",
        weight_type: str = "",
        threads: int = -1,
        vram_limit: str = "",
        offload_to_cpu: bool = False,
        split_mode: str = "",
        backend: str = "",
        extra_start: tuple[str, ...] = (),
        ad_extra: str = "",
        video_parts: dict[str, str] | None = None,
    ) -> bool:
        """Does the running server already carry this Gespann — same model, VAE,
        detector, PhotoMaker, LoRA and embedding folder, and (for a Bausatz)
        the same diffusion model, text encoders and VAE format? Then the
        picture goes straight over HTTP. A mismatch (or a stopped server)
        means the caller must restart it with the new flags first. The
        detector's prompt counts too: it is a start flag, so a different one
        is a different server; it is only compared when a detector is
        actually set. The apply mode is the same story — a start flag, only
        compared while THIS wish actually has a LoRA or a face in play
        (``lora_aktiv``, the caller's own condition for sending
        ``--lora-apply-mode`` on the sd-cli path), since it changes nothing
        for a wish that never touches either — matching the sd-cli path's own
        condition rather than the folder's mere presence, which this server
        is always started with (see ``starten``).

        ``gesichter_fingerabdruck`` is the caller's freshly computed
        ``photomaker.fingerabdruck()`` of the CURRENT photos, not the
        folder's own name or path — the folder never changes, only what is
        in it."""
        if not self.laeuft():
            return False
        soll_ad_prompt = ad_prompt if ad_modell else ""
        # Same rule as the detailer's prompt: both only mean anything while
        # a detector is set, so they are only compared then.
        soll_ad_negativ = ad_negativ if ad_modell else ""
        soll_ad_confidence = ad_confidence if ad_modell else None
        soll_ad_extra = ad_extra if ad_modell else ""
        soll_lora_ordner = str(lora_ordner) if lora_ordner is not None else None
        soll_embd_ordner = str(embd_ordner) if embd_ordner is not None else None
        soll_upscaler_ordner = str(upscaler_ordner) if upscaler_ordner is not None else None
        return (
            self._modell == modell
            and (self._vae or None) == (vae or None)
            and (self._ad_modell or None) == (ad_modell or None)
            and (self._ad_prompt or "") == (soll_ad_prompt or "")
            and (self._ad_negativ or "") == (soll_ad_negativ or "")
            and self._ad_confidence == soll_ad_confidence
            and (self._prediction or "") == (prediction or "")
            and (self._control_net or None) == (control_net or None)
            and self._upscaler_ordner == soll_upscaler_ordner
            and (self._photomaker or None) == (photomaker or None)
            and (self._gesichter_fingerabdruck or None) == (gesichter_fingerabdruck or None)
            and self._lora_ordner == soll_lora_ordner
            and (not lora_aktiv or self._lora_apply_mode == lora_apply_mode)
            and self._embd_ordner == soll_embd_ordner
            and (self._diffusion_model or None) == (diffusion_model or None)
            and (self._t5xxl or None) == (t5xxl or None)
            and (self._clip_l or None) == (clip_l or None)
            and (self._clip_g or None) == (clip_g or None)
            and (self._llm or None) == (llm or None)
            and (self._vae_format or "") == (vae_format or "")
            and (self._llm_vision or None) == (llm_vision or None)
            and (self._tokenizer or None) == (tokenizer or None)
            and (self._uncond_diffusion_model or None) == (uncond_diffusion_model or None)
            and self._video_parts == _part_names(video_parts)
            and (self._model_args or "") == (model_args or "")
            and self._rng == rng
            and (self._weight_type or "") == (weight_type or "")
            and self._threads == threads
            and self._vram_limit == vram_limit
            and self._offload_to_cpu == offload_to_cpu
            and (self._split_mode or "") == (split_mode or "")
            and (self._backend or "") == (backend or "")
            and self._extra_start == tuple(extra_start)
            and self._ad_extra == soll_ad_extra
        )

    def zustand(self) -> str:
        """What the plus-menu plaque colours itself by.

        ``aus`` (grey) → off. ``bereit`` (green) → up and idle. ``zeichnet``
        (blue) → a picture is in flight, or the server is still coming up.
        ``fehler`` (red) → it was started but the process is gone.
        """
        if self._prozess is None:
            return "aus"
        if self._prozess.poll() is not None:
            return "fehler"
        if self._zeichnet:
            return "zeichnet"
        # A server that has answered once stays answering (see
        # ``bereit_abwarten``), so only a server still coming up is asked.
        # A poll's answer is kept only for the process it was asked of: a
        # start that replaced it meanwhile must not inherit it.
        if not self._war_bereit:
            process = self._prozess
            answers = self._bereit()
            with self._schloss:
                if answers and self._prozess is process:
                    self._war_bereit = True
            if not answers:
                return "zeichnet"
        return "bereit"

    def _bereit(self) -> bool:
        """Does the server already answer? Cheap enough to ask on every
        status poll. Its own capabilities route answers as soon as the port
        is bound, the same moment the old options route did."""
        try:
            antwort = httpx.get(
                f"http://127.0.0.1:{self._port}/sdcpp/v1/capabilities", timeout=1.0
            )
            return antwort.status_code == 200
        except httpx.HTTPError:
            return False

    def starten(
        self,
        modell_pfad: Path,
        *,
        vae: Path | None = None,
        ad_modell: Path | None = None,
        ad_prompt: str = "",
        ad_negativ: str = "",
        ad_confidence: float | None = None,
        prediction: str = "",
        control_net: Path | None = None,
        upscaler_ordner: Path | None = None,
        lora_ordner: Path | None = None,
        embd_ordner: Path | None = None,
        photomaker: Path | None = None,
        gesichter_ordner: Path | None = None,
        familie: str | None = None,
        diffusion_model: Path | None = None,
        t5xxl: Path | None = None,
        clip_l: Path | None = None,
        clip_g: Path | None = None,
        llm: Path | None = None,
        vae_format: str = "",
        llm_vision: Path | None = None,
        tokenizer: Path | None = None,
        uncond_diffusion_model: Path | None = None,
        video_parts: dict[str, Path] | None = None,
        model_args: str = "",
        lora_apply_mode: str = "at_runtime",
        lora_aktiv: bool = False,
        rng: str = "cuda",
        weight_type: str = "",
        threads: int = -1,
        vram_limit: str = "",
        offload_to_cpu: bool = False,
        split_mode: str = "",
        backend: str = "",
        extra_start: tuple[str, ...] = (),
        ad_extra: str = "",
        _paused_with: tuple[tuple, dict] | None = None,
    ) -> bool:
        """Bring the server up on the given model and Gespann. Returns once the
        process is launched; the model may still be loading (the plaque shows
        blue until it answers, and ``bereit_abwarten`` is how the request path
        waits for it). Idempotent-ish: a running server is stopped first so a
        model or Gespann switch is one call.

        VAE, detector and PhotoMaker are start flags — they bind to this one
        server, so a different one means a fresh start. The LoRA folder is
        pointed at whenever it is given (even with no LoRA in this first
        picture), so later requests on this same server can still reference
        one by name. The apply mode itself is only sent when this first
        picture actually has a LoRA or a face in play (``lora_aktiv``) —
        matching the sd-cli path's own condition, since the flag would
        otherwise claim a choice this wish never made. Free by house rule,
        not locked here either. ``at_runtime`` is the one proven to render on
        this Metal build; ``auto``/``immediately`` apply 0 of N tensors and
        then abort in sampling (proven 17.08., commit aaad442).

        ``photomaker`` and ``gesichter_ordner`` only matter together — same
        as ``app/bildrunner.py``'s sd-cli path, one without the other is
        nothing to load a face from.

        A Bausatz (``diffusion_model`` set) asks ``bildbausatz`` for its
        switches instead of ``-m``, exactly like ``bildrunner.befehl()``.
        ``familie`` names which one — the caller's job to check against the
        fields it sends, same as ``bildrunner.befehl()``. The Gespann's own
        VAE is left out of it — the unconditional ``--vae`` line below
        already covers every model, Bausatz or not.
        """
        # Every parameter of this call, by name, so ``resume`` can repeat it.
        # Read against the signature, so a local added above this line is
        # never mistaken for one.
        parameters = inspect.signature(Bildturbo.starten).parameters
        call = locals()
        start_values = ((modell_pfad,), {
            name: call[name] for name in parameters
            if name not in ("self", "modell_pfad", "_paused_with")
        })
        with self._schloss:
            if _paused_with is not None and self._start_values is not _paused_with:
                # Coming back from a pause, and stopped or started anew
                # since: there is nothing to bring back.
                log.info("Image server is not started again: it was stopped since its pause")
                return False
            programm = self.programm
            if programm is None:
                raise BildturboFehler("bild.kein_programm")
            self._stoppen_intern()
            self._raeum_waise()
            if diffusion_model is not None:
                gespann = bildbausatz.Gespann(
                    familie=familie,
                    diffusion_model=diffusion_model,
                    t5xxl=t5xxl, clip_l=clip_l, clip_g=clip_g, llm=llm,
                    vae_format=vae_format, llm_vision=llm_vision, tokenizer=tokenizer,
                    uncond_diffusion_model=uncond_diffusion_model, **(video_parts or {}),
                )
                try:
                    modell_teile = bildbausatz.schalter(gespann)
                except ValueError as fehler:
                    raise BildturboFehler("bild.familie_ungueltig") from fehler
            else:
                modell_teile = ["-m", str(modell_pfad)]
                # A checkpoint without text encoders of its own is handed
                # the ones of its family; any other plain model carries none.
                modell_teile += bildbausatz.checkpoint_switches(
                    familie, t5xxl=t5xxl, clip_l=clip_l, clip_g=clip_g, llm=llm,
                    # Read only where no family decides about the model:
                    # then every part that is set goes beside the model.
                    llm_vision=llm_vision, tokenizer=tokenizer,
                    uncond_diffusion_model=uncond_diffusion_model, **(video_parts or {}),
                )
                # J2: a simple model has no Gespann, so `bildbausatz.schalter()`
                # never runs for it — the one place `vae_format` otherwise
                # becomes a flag. Without this, the server was told to
                # remember the wish (`self._vae_format` below, unconditional)
                # and reported it as set, while sd-cli itself never saw it.
                if vae_format:
                    modell_teile += ["--vae-format", vae_format]
            befehl = [
                str(programm),
                *modell_teile,
                "--listen-ip", "127.0.0.1",
                "--listen-port", str(self._port),
                # Flash attention in the diffusion model — this build supports
                # it (it is what makes the turbo a turbo), and here it is safe
                # because it is OUR binary, not an old one a user swapped in.
                "--diffusion-fa",
            ]
            if vae is not None:
                befehl += ["--vae", str(vae)]
            if model_args:
                befehl += ["--model-args", model_args]
            if ad_modell is not None:
                befehl += ["--ad-model", str(ad_modell)]
                if ad_prompt:
                    befehl += ["--ad-prompt", ad_prompt]
                # Empty inherits the main negative prompt (sd-cli's own,
                # useful behaviour) — so empty means NO flag, exactly like
                # the sd-cli path in app/bildrunner.py.
                if ad_negativ:
                    befehl += ["--ad-negative-prompt", ad_negativ]
                # One list: sd-cli reads only the last --extra-ad-args.
                ad_args = image_switches.join_list(
                    f"confidence={ad_confidence}" if ad_confidence is not None else "", ad_extra,
                )
                if ad_args:
                    befehl += ["--extra-ad-args", ad_args]
            if prediction:
                befehl += ["--prediction", prediction]
            if control_net is not None:
                befehl += ["--control-net", str(control_net)]
            # Pointed at whenever it is given, like the LoRA folder below —
            # hr_upscaler travels per request, the folder it resolves
            # against does not.
            if upscaler_ordner is not None:
                befehl += ["--hires-upscalers-dir", str(upscaler_ordner)]
            if lora_ordner is not None:
                befehl += ["--lora-model-dir", str(lora_ordner)]
                if lora_aktiv:
                    befehl += ["--lora-apply-mode", lora_apply_mode]
            if embd_ordner is not None:
                befehl += ["--embd-dir", str(embd_ordner)]
            if photomaker is not None and gesichter_ordner is not None:
                befehl += [
                    "--photo-maker", str(photomaker),
                    "--pm-id-images-dir", str(gesichter_ordner),
                ]
            befehl += ["--rng", rng]
            if weight_type:
                befehl += ["--type", weight_type]
            if threads > 0:
                befehl += ["--threads", str(threads)]
            if vram_limit:
                befehl += ["--max-vram", vram_limit]
            if offload_to_cpu:
                befehl += ["--offload-to-cpu"]
            if split_mode:
                befehl += ["--split-mode", split_mode]
            if backend:
                befehl += ["--backend", backend]
            befehl += list(extra_start)
            # Errors go into the same pipe as the progress: one reader keeps
            # both, and the server log shows why a start or a picture failed.
            # The pipe carries bytes; the reader turns them into text itself,
            # as they arrive.
            self._prozess = subprocess.Popen(
                befehl,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                **no_window(),
            )
            # Cleared once the new process stands: the old reader no longer
            # writes from here on, so nothing of the old server slips in.
            self._protokoll.clear()
            threading.Thread(
                target=self._zaehler_lesen, args=(self._prozess,), daemon=True
            ).start()
            self._modell = Path(modell_pfad).name
            self._vae = Path(vae).name if vae is not None else None
            self._ad_modell = Path(ad_modell).name if ad_modell is not None else None
            self._ad_prompt = ad_prompt if ad_modell is not None else ""
            self._ad_negativ = ad_negativ if ad_modell is not None else ""
            self._ad_confidence = ad_confidence if ad_modell is not None else None
            self._prediction = prediction
            self._control_net = Path(control_net).name if control_net is not None else None
            self._upscaler_ordner = (
                str(upscaler_ordner) if upscaler_ordner is not None else None
            )
            self._lora_ordner = str(lora_ordner) if lora_ordner is not None else None
            # Not sent above when no LoRA/face is active — so what the server
            # actually runs on then is the BINARY's own default, and that is
            # "auto", not "at_runtime". Read out of this build's own --help:
            # "the way to apply LoRA, one of [auto, immediately, at_runtime],
            # default is auto". Remembering "at_runtime" here claimed a mode
            # nobody had asked for: passt_zu() then saw a match for the first
            # LoRA picture, skipped the restart, and the LoRA was applied on a
            # server running in auto — measured on builds 820 and 920, that
            # applies 0 of 834 tensors and kills the whole server in ggml_abort.
            # Honest value, so passt_zu() pays the one restart it must.
            self._lora_apply_mode = lora_apply_mode if lora_aktiv else "auto"
            self._war_bereit = False
            self._weights_loaded = False
            self._embd_ordner = str(embd_ordner) if embd_ordner is not None else None
            # Only together, matching the flags above — a stored half-pair
            # would tell passt_zu the server carries PhotoMaker when the
            # command it was actually started with never asked for it.
            hat_gesicht = photomaker is not None and gesichter_ordner is not None
            self._photomaker = Path(photomaker).name if hat_gesicht else None
            self._gesichter_fingerabdruck = (
                foto_fingerabdruck(gesichter_ordner) if hat_gesicht else None
            )
            self._diffusion_model = (
                Path(diffusion_model).name if diffusion_model is not None else None
            )
            self._t5xxl = Path(t5xxl).name if t5xxl is not None else None
            self._clip_l = Path(clip_l).name if clip_l is not None else None
            self._clip_g = Path(clip_g).name if clip_g is not None else None
            self._llm = Path(llm).name if llm is not None else None
            self._vae_format = vae_format
            self._llm_vision = Path(llm_vision).name if llm_vision is not None else None
            self._tokenizer = Path(tokenizer).name if tokenizer is not None else None
            self._uncond_diffusion_model = (
                Path(uncond_diffusion_model).name if uncond_diffusion_model is not None else None
            )
            self._video_parts = _part_names(video_parts)
            self._model_args = model_args
            self._rng = rng
            self._weight_type = weight_type
            self._threads = threads
            self._vram_limit = vram_limit
            self._offload_to_cpu = offload_to_cpu
            self._split_mode = split_mode
            self._backend = backend
            self._extra_start = tuple(extra_start)
            self._ad_extra = ad_extra if ad_modell is not None else ""
            self._start_values = start_values
            self._paused_for = None
            self._pid_merken(self._prozess.pid)
            return True

    def _start_deadline(self) -> float:
        """The wait this server's own start is given, by the files it was
        started with."""
        return start_deadline(*start_parts(self, self._video_parts, prefix="_"))

    def bereit_abwarten(
        self, frist: float = STARTFRIST, *, stopped: Callable[[], bool] | None = None,
    ) -> bool:
        """Block until the server answers, or the deadline passes. Returns
        False if the process died or the server never came up in time —
        or when ``stopped`` says the picture this wait is for was stopped:
        the wait ends at once, and the server goes on starting untouched.

        What "answers" is worth here, measured against build 820
        (master-820-de298c2) on 01.09. over the old options route, which the
        capabilities route asked now answers alongside: it starts answering
        200 the moment the server binds its port — 0.14 s after Popen, for a
        2 GB SD-1.5 and a 7 GB SDXL alike, because the checkpoint is only
        opened and its graph built at that point, not read. The weights
        themselves are pulled in lazily by the FIRST draw ("loading tensors
        completed, taking 11.38 s" inside ``generate_image``), and that draw
        simply blocks while it happens: a txt2img posted 0.00 s after the
        first 200 came back 200 with a correct picture in 17.14 s, the next
        one in 1.30 s. So a 200 here does not mean "weights in memory" — but
        it does mean the one thing the request path needs, that a draw sent
        now will be served rather than refused. Measured again on build 920:
        the first 200 after 0.13 s, the first draw served in 23.9 s, the next
        in 17.2 s.

        The gap that DOES break a draw is the one before that first 200, and
        it is not a millisecond of theory: ``turbo/start`` returns as soon as
        Popen has forked, so a picture asked for right after switching the
        turbo on lands in it. Measured before this guard existed: HTTP 503
        after 0.04 s, twice in a row, on build 820; a refused connection
        after 0.05 s on build 920.

        ``_war_bereit`` makes the answer free once given. A server that has
        answered stays answering — it is the whole point of the add-on — and
        the flag is dropped with the server it belongs to, so a fresh one
        asks again."""
        if self._war_bereit:
            return True
        ende = time.monotonic() + frist
        while time.monotonic() < ende:
            if not self.laeuft():
                return False
            if stopped is not None and stopped():
                return False
            if self._bereit():
                self._war_bereit = True
                return True
            time.sleep(0.5)
        self._war_bereit = self._bereit()
        return self._war_bereit

    def stoppen(self) -> bool:
        """Switch the add-on off. True when there was one to switch off."""
        with self._schloss:
            return self._stoppen_intern()

    def abbrechen(self) -> bool:
        """Break off a picture being drawn right now. True when there was one.

        The job is cancelled first, which keeps the model loaded. The server
        only allows that while the job still waits in its queue: once it
        draws, the cancel is answered 409 "job is currently generating and
        cannot be interrupted yet" (its capabilities say
        ``cancel_generating: false``). Then the only way to stop the picture
        is to end the server under it; the poll then fails, and the
        ``_abgebrochen`` flag turns that failure into the silent stop the
        user asked for. When nothing is drawing, this does nothing — a stop
        pressed on an idle warm server must not tear it down."""
        if not self._zeichnet:
            return False
        with self._stop_lock:
            self._abgebrochen = True
            job = self._job
        # Still being handed in: the draw cancels its job itself the moment
        # the id comes back (see ``zeichnen``).
        if job is not None:
            self._end_job(job)
        return True

    def _end_job(self, job: str) -> None:
        """Cancel one job — or, when the server refuses because the job
        already draws (409), end the server under it. Any other refusal
        means the job is gone already (cancelled, finished): nothing more to
        stop, and a healthy server is not ended for it."""
        try:
            answer = httpx.post(
                f"http://127.0.0.1:{self._port}/sdcpp/v1/jobs/{job}/cancel", timeout=5.0
            )
        except httpx.HTTPError:
            answer = None
        if answer is not None and answer.status_code == 200:
            log.info("Image server: job %s cancelled, the model stays loaded", job)
            return
        if answer is not None and answer.status_code != 409:
            log.info("Image server: job %s has already ended (%s)", job, _antworttext(answer))
            return
        log.info(
            "Image server: job %s cannot be cancelled while it draws (%s); "
            "ending the server", job,
            _antworttext(answer) if answer is not None else "no answer",
        )
        self.stoppen()

    def belegt_gb(self) -> float | None:
        """Live resident memory of the running server, or None when idle —
        the same answer every other model server gives the memory check."""
        process = self._prozess
        if process is None or process.poll() is not None:
            return None
        return rss_gb(process.pid)

    def pause(self, control: str | None = None) -> bool:
        """End the server for a while and keep how it was started. True when
        one was running. ``resume`` brings the same server back. ``control``
        names what the picture it steps aside for needs sd-cli for, while
        the pause lasts (``paused_for``)."""
        with self._schloss:
            if not self.laeuft():
                return False
            values = self._start_values
            self._stoppen_intern()
            self._start_values = values
            self._paused_for = control
            return True

    def paused_for(self) -> str | None:
        """What the server is paused for, or None when it is not paused —
        a server that runs, was stopped or never started is not. Read
        without the lock: the state poll must not wait for a pause that is
        still ending the process."""
        if self._prozess is not None or self._start_values is None:
            return None
        return self._paused_for

    def resume(self) -> bool:
        """Start the server again exactly as it ran before ``pause`` —
        unless it was stopped since: a stop takes the kept start values
        down, and the start below looks for them once more under the lock
        the stop holds. A server stopped while the program ends does not
        come back behind it. True when it was started."""
        values = self._start_values
        # The pause is over once the server is asked to come back, whether
        # it does or not: a server that stays down is off, not paused.
        self._paused_for = None
        if values is None or self.laeuft():
            return False
        args, kwargs = values
        return self.starten(*args, **kwargs, _paused_with=values)

    def _stoppen_intern(self) -> bool:
        prozess = self._prozess
        self._modell = None
        self._vae = None
        self._ad_modell = None
        self._ad_prompt = ""
        self._ad_negativ = ""
        self._ad_confidence = None
        self._prediction = ""
        self._control_net = None
        self._upscaler_ordner = None
        self._photomaker = None
        self._gesichter_fingerabdruck = None
        self._lora_ordner = None
        self._lora_apply_mode = "auto"
        self._war_bereit = False
        self._weights_loaded = False
        self._start_values = None
        self._paused_for = None
        self._embd_ordner = None
        self._diffusion_model = None
        self._t5xxl = None
        self._clip_l = None
        self._clip_g = None
        self._llm = None
        self._vae_format = ""
        self._llm_vision = None
        self._tokenizer = None
        self._uncond_diffusion_model = None
        self._video_parts = ()
        self._model_args = ""
        self._rng = "cuda"
        self._weight_type = ""
        self._threads = -1
        self._vram_limit = ""
        self._offload_to_cpu = False
        self._split_mode = ""
        self._backend = ""
        self._zeichnet = False
        self._pid_datei.unlink(missing_ok=True)
        if prozess is None or prozess.poll() is not None:
            self._prozess = None
            return False
        prozessstopp.beenden(prozess, frist=5.0)
        self._prozess = None
        return True

    def fortschritt(self) -> dict | None:
        """The running picture's step counter, or None when nothing is in
        flight — the same shape the sd-cli runner reports, so the one
        progress endpoint can serve both paths."""
        if not self.laeuft() or not self._zeichnet:
            return None
        return self._fortschritt

    def _zeilen_aufnehmen(self, text: str, prozess: subprocess.Popen) -> str:
        """Hands every finished line of ``text`` to the server log and returns
        the unfinished rest. A progress bar redraws itself with carriage
        returns, so only what a line ends on is kept — the last state of the
        bar, not every frame of it. A reader whose server has been replaced
        writes nothing: its last words are not the new server's."""
        *fertig, rest = text.split("\n")
        if prozess is self._prozess:
            for roh in fertig:
                zeile = roh.rsplit("\r", 1)[-1].rstrip()
                if zeile:
                    self._protokoll.append(zeile)
        # Only the bar's latest frame is kept of an unfinished line, so a long
        # picture does not pile its redraws up here.
        return rest.rsplit("\r", 1)[-1]

    def protokoll(self) -> list[str]:
        """What the server has said since it was last started."""
        return list(self._protokoll)

    def _zaehler_lesen(self, prozess: subprocess.Popen) -> None:
        """Lifelong stdout reader for one server process. Counting is armed
        per request by ``zeichnen``: only bars that count iterations are
        painting passes (the loader's bars count megabytes), and pass
        counting mirrors the sd-cli reader — a step number falling back
        means the next pass (detector) began."""
        rest = ""
        letzte_zaehl = None
        zeile = ""
        # Taken piece by piece as the server writes it, so every step's bar
        # is counted when it is printed, and with the newlines a pipe in
        # text mode would hand over.
        assert prozess.stdout is not None  # opened with PIPE
        pieces = live_text(prozess.stdout, io.text_encoding(None), universal_newlines=True)
        while True:
            try:
                stueck = next(pieces, "")
            except (OSError, ValueError):
                break
            if not stueck:
                break
            zeile = self._zeilen_aufnehmen(zeile + stueck, prozess)
            zaehl = self._zaehl
            if zaehl is None:
                rest = ""
                letzte_zaehl = None
                continue
            # A fresh counter means the next picture began — drop the tail
            # carried from the last one, or a leftover bar of picture N could
            # be matched at the start of N+1 on this lifelong reader.
            if zaehl is not letzte_zaehl:
                rest = ""
                letzte_zaehl = zaehl
            text = rest + stueck
            for treffer in _SCHRITT_MUSTER.finditer(text):
                if treffer.end() <= len(rest):
                    continue  # already seen in the previous round
                if treffer.group(3):
                    # As in the sd-cli reader: the bars before this line were
                    # the preparation and are no part of the picture's share;
                    # only the first time, a later pass goes on counting.
                    if not zaehl["announced"]:
                        zaehl.update(
                            announced=True, paint_total=0, painted=0, fertige=0, letzter=0,
                        )
                        self._fortschritt = {
                            "anteil": 0.0, "schritt": 0, "gesamt": zaehl["schritte"],
                        }
                    continue
                schritt, gesamt = int(treffer.group(1)), int(treffer.group(2))
                # Same rule as the sd-cli reader: the first painting bar's
                # total is the painting pass's step count (fewer than
                # requested from a starting picture); every painting bar is
                # real remaining work and moves the share (detector faces
                # with their own step count included), extra passes stay
                # inside the last share instead of pushing past the end, and
                # only a bar of the painting pass itself names the step. A
                # bar that counts beyond the requested steps before painting
                # has begun is no painting pass.
                if not zaehl["paint_total"]:
                    if gesamt > zaehl["schritte"]:
                        continue
                    zaehl["paint_total"] = gesamt
                if schritt < zaehl["letzter"]:
                    zaehl["fertige"] = min(zaehl["fertige"] + 1, zaehl["paesse"] - 1)
                zaehl["letzter"] = schritt
                anteil = (zaehl["fertige"] + schritt / gesamt) / zaehl["paesse"]
                if gesamt == zaehl["paint_total"]:
                    zaehl["painted"] = schritt
                self._fortschritt = {
                    "anteil": min(anteil, 0.99),
                    "schritt": zaehl["painted"],
                    "gesamt": zaehl["paint_total"],
                }
            rest = text[-64:]

    def _arm_counter(self, steps: int, passes: int) -> None:
        """Start counting the bars of one picture of ``steps`` requested
        steps, planned as ``passes`` painting passes."""
        self._fortschritt = {"anteil": 0.0, "schritt": 0, "gesamt": steps}
        self._zaehl = {
            "schritte": steps,
            "paesse": passes,
            "fertige": 0,
            "letzter": 0,
            "paint_total": 0,
            "painted": 0,
            "announced": False,
        }

    def zeichnen(
        self, auftrag: dict, *, paesse: int = 0, video: bool = False,
        stopped: Callable[[], bool] | None = None, zeitgrenze: float | None = None,
    ) -> bytes:
        """Draw one picture over the running server and return its bytes.

        ``auftrag`` is the body of ``/sdcpp/v1/img_gen`` — or of
        ``/sdcpp/v1/vid_gen`` for a ``video`` —, already assembled by the
        caller: this module only speaks HTTP and knows nothing of the
        parameter names. The route answers at once with a job; the picture
        is fetched from that job once it is done — a video as one encoded
        container (api.md, "Result Payload").

        ``paesse`` is how many painting passes the caller expects. Zero means
        one, which is what everything but highres and the detector wants.

        ``stopped`` says whether this picture was stopped before it got
        here — while the server was still starting for it. Asked during the
        wait below, once more as the draw takes over, and at every look for
        the job's state after that; a stop that reaches the draw itself is
        ``abbrechen``'s.

        ``zeitgrenze`` is how many seconds the picture may take once the job
        is handed in; after it the job is ended and the draw reports that
        the limit has passed. None draws without a limit, and a video has
        none whatever is given.
        """
        if not self.laeuft():
            raise BildturboFehler("bild.turbo_aus")
        # Wait for the server to answer before posting anything at it: a
        # server started a moment ago has not bound its port yet (measured:
        # HTTP 503 in 0.04 s on build 820, a refused connection in 0.05 s on
        # build 920). Free on a server that already answered once.
        if not self.bereit_abwarten(self._start_deadline(), stopped=stopped):
            if stopped is not None and stopped():
                raise BildturboFehler("bild.abgebrochen")
            raise BildturboFehler("bild.turbo_ladefehler")
        with self._stop_lock:
            if stopped is not None and stopped():
                # Asked in the moment before: the picture is never handed
                # in, and the server is not asked to cancel anything.
                raise BildturboFehler("bild.abgebrochen")
            self._abgebrochen = False
            self._zeichnet = True
        schritte = int((auftrag.get("sample_params") or {}).get("sample_steps") or 0)
        if schritte > 0:
            self._arm_counter(schritte, paesse or 1)
        base_url = f"http://127.0.0.1:{self._port}/sdcpp/v1"
        try:
            route = "vid_gen" if video else "img_gen"
            antwort = httpx.post(f"{base_url}/{route}", json=auftrag, timeout=60.0)
            antwort.raise_for_status()
            job_id = str(antwort.json()["id"])
            with self._stop_lock:
                self._job = job_id
                stopped_early = self._abgebrochen
            log.info("Image server: picture handed in over %s as job %s", route, job_id)
            if stopped_early:
                self._end_job(job_id)
            deadline = (
                time.monotonic() + zeitgrenze if zeitgrenze and not video else None
            )
            while True:
                poll = httpx.get(f"{base_url}/jobs/{job_id}", timeout=30.0)
                poll.raise_for_status()
                job = poll.json()
                status_name = job.get("status")
                if status_name == "completed":
                    result = job.get("result") or {}
                    bilder = [result] if video else result.get("images") or []
                    if not bilder or not bilder[0].get("b64_json"):
                        raise BildturboFehler("bild.gescheitert")
                    self._weights_loaded = True
                    return base64.b64decode(bilder[0]["b64_json"])
                # A job that ends in any way after a stop was pressed ended
                # because of it: the silent stop, never a failure.
                if status_name == "cancelled" or (
                    self._abgebrochen and status_name not in ("queued", "generating")
                ):
                    raise BildturboFehler("bild.abgebrochen")
                if status_name not in ("queued", "generating"):
                    reason = (job.get("error") or {}).get("message") or status_name
                    raise BildturboFehler("bild.gescheitert", reason)
                if deadline is not None and time.monotonic() > deadline:
                    # The same limit the sd-cli path has; the job is ended
                    # with it, so nothing keeps drawing for nobody and the
                    # next picture does not queue behind it.
                    self._end_job(job_id)
                    raise BildturboFehler("bild.zeit_abgelaufen")
                if stopped is not None and not self._abgebrochen and stopped():
                    # A stop that fell between the look above and this
                    # draw's own flag: taken up here like any stop of a
                    # running draw, instead of drawing on for nobody.
                    self.abbrechen()
                time.sleep(POLL_INTERVAL)
        except (httpx.HTTPError, KeyError, ValueError, AttributeError, TypeError) as fehler:
            # A draw broken off by ``abbrechen`` (the server was ended under
            # it) is not a failure — it is the stop the user asked for, and it
            # must read as the same silent abort the sd-cli path returns.
            if self._abgebrochen:
                raise BildturboFehler("bild.abgebrochen") from fehler
            # Everything else keeps the server's own words: its 400 names the
            # file and the mistake ("invalid generation parameters"), while
            # the bare key says only that something failed.
            server_words = _serverwort(fehler) if isinstance(fehler, httpx.HTTPError) else None
            raise BildturboFehler("bild.gescheitert", server_words) from fehler
        finally:
            self._zeichnet = False
            self._abgebrochen = False
            self._job = None
            self._zaehl = None
            self._fortschritt = None

    @property
    def upscaler_folder(self) -> str | None:
        """The upscaler folder the running server was started with."""
        return self._upscaler_ordner if self.laeuft() else None

    def upscale(
        self, picture_b64: str, upscaler: str, output_format: str = "png",
        zeitgrenze: float | None = None,
    ) -> bytes:
        """Upscale one finished picture over the server's own route
        ``/sdcpp/v1/upscale`` — no model, no sampling. ``upscaler`` is a
        model's name without its ending, as the server lists it from its
        upscaler folder; ``output_format`` is ``png``, ``jpeg`` or ``webp``. The route
        answers at once with the picture. ``zeitgrenze`` is how many seconds
        the call waits for it — the route cannot be broken off, so the server
        draws on to its end; None waits without a limit."""
        if not self.laeuft():
            raise BildturboFehler("bild.turbo_aus")
        # Marked as drawing before the wait, so a stop pressed while the
        # server still loads is heard.
        with self._stop_lock:
            self._abgebrochen = False
            self._zeichnet = True
        try:
            ready = self.bereit_abwarten(self._start_deadline())
            if self._abgebrochen:
                raise BildturboFehler("bild.abgebrochen")
            if not ready:
                raise BildturboFehler("bild.turbo_ladefehler")
            response = httpx.post(
                f"http://127.0.0.1:{self._port}/sdcpp/v1/upscale",
                json={"image": picture_b64, "upscaler": upscaler, "output_format": output_format},
                timeout=zeitgrenze or None,
            )
            response.raise_for_status()
            # The route answers in one go and cannot be broken off; a stop
            # pressed meanwhile throws the answer away, so what the user
            # stopped does not land.
            if self._abgebrochen:
                raise BildturboFehler("bild.abgebrochen")
            pictures = response.json().get("images") or []
            if not pictures or not pictures[0].get("b64_json"):
                raise BildturboFehler("bild.gescheitert")
            return base64.b64decode(pictures[0]["b64_json"])
        except (httpx.HTTPError, ValueError, AttributeError, TypeError) as error:
            # A stop pressed meanwhile is the silent stop, however the
            # answer then went wrong.
            if self._abgebrochen:
                raise BildturboFehler("bild.abgebrochen") from error
            if isinstance(error, httpx.TimeoutException):
                raise BildturboFehler("bild.zeit_abgelaufen") from error
            server_words = _serverwort(error) if isinstance(error, httpx.HTTPError) else None
            raise BildturboFehler("bild.gescheitert", server_words) from error
        finally:
            self._zeichnet = False
            self._abgebrochen = False

    # --- Orphan handling: a server outlives a service crash on its own
    #     process group; after a restart the service ends the leftover so the
    #     port is free again. ------------------------------------------------

    def _pid_merken(self, pid: int) -> None:
        try:
            self._pid_datei.write_text(str(pid), encoding="utf-8")
        except OSError:
            log.debug("Picture turbo PID could not be noted", exc_info=True)

    def _raeum_waise(self) -> None:
        try:
            alt = int(self._pid_datei.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return
        try:
            antwort = subprocess.run(
                ["ps", "-p", str(alt), "-o", "comm="],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5,
                **no_window(),
            )
        except (OSError, subprocess.TimeoutExpired):
            return
        if "sd-server" in antwort.stdout:
            try:
                os.kill(alt, 15)
            except OSError:
                pass
        self._pid_datei.unlink(missing_ok=True)
