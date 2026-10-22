"""Keeps the voice loaded for as long as a conversation lasts.

A conversation speaks many pieces in a row. ``llama-tts`` (app/stimme.py)
loads the model, the projector and the voice sample for every one of them;
this keeps them loaded in a process of its own (app/voice_worker.py) and
speaks the pieces without loading again.

It lives exactly as long as the conversation:

  * the page announces the conversation and repeats the announcement every
    few seconds (``hold``); a page that went away stops repeating it and the
    voice is given back when the time of that announcement runs out;
  * the end of the conversation gives it back at once (``release``);
  * the service ending takes the process with it: the process reads its
    input until that closes.

Nothing here is a second way to speak. Whatever goes wrong — the process
does not start, the library does not load, a piece does not come out —
the piece is spoken by ``llama-tts`` as before, and so is every following
piece of that conversation: a voice that failed once is not asked again
until the conversation is over.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import tempfile
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from app import paketierung
from app.no_console import no_window

log = logging.getLogger(__name__)

# How long an announcement of a conversation holds without a new one.
HOLD_SECONDS = 30.0
# How often the reaper looks at it.
REAPER_SECONDS = 5.0
# The same safety valve as a single call to ``llama-tts`` has (app/stimme.py):
# not a limit on what is said.
SPEAK_TIMEOUT = 600.0
# Loading is the model and the projector and the voice sample, and on a
# first start the engine compiles its kernels as well.
LOAD_TIMEOUT = 300.0


class VoiceUnavailable(Exception):
    """The kept voice cannot speak this piece; ``reason`` says why, for the log."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class VoiceSpec:
    """Everything the loaded voice depends on. A different spec is a
    different voice, and it is loaded again."""

    library_dir: str
    model: str
    mmproj: str
    speaker: str | None
    gpu_layers: int
    threads: int


def worker_command() -> list[str]:
    """How this program starts itself as the voice process: packaged, the
    program is its own tool (``--voice``); from source, ``start.py`` is."""
    if paketierung.ist_eingefroren():
        return [str(paketierung.programmpfad()), "--voice"]
    start = Path(__file__).resolve().parent.parent / "start.py"
    return [sys.executable, str(start), "--voice"]


class VoiceService:
    def __init__(self, command: Callable[[], list[str]] = worker_command,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._command = command
        self._clock = clock
        # Two locks, always taken in this order. ``_work`` is held for as long
        # as a load or a piece takes (minutes at the worst); ``_state`` only
        # for a moment, so the page's announcements and the route's questions
        # never wait for the process.
        self._work = threading.Lock()
        self._state = threading.Lock()
        self._process: subprocess.Popen | None = None
        self._loaded: VoiceSpec | None = None
        self._spec: VoiceSpec | None = None
        self._until = 0.0
        # A voice that failed in this conversation stays out of it.
        self._failed = False
        # The spec a background load is under way for, so one announcement
        # after another does not start one load after another.
        self._loading: VoiceSpec | None = None
        self._reaper: threading.Thread | None = None
        self._stderr: deque[str] = deque(maxlen=40)

    # --- the page's side ---------------------------------------------------

    def hold(self, spec: VoiceSpec) -> None:
        """A conversation is on. Loads the voice in the background when it is
        not loaded yet, and holds it for another stretch of time."""
        with self._state:
            self._until = self._clock() + HOLD_SECONDS
            self._spec = spec
            failed = self._failed
            start_reaper = self._reaper is None or not self._reaper.is_alive()
            if start_reaper:
                self._reaper = threading.Thread(target=self._reap, name="voice-reaper", daemon=True)
                self._reaper.start()
        # A load already running holds ``_work`` and loads this very spec
        # (or the one before it, which the next announcement corrects): do
        # not queue a second one behind it.
        if failed or self._loading == spec or (self._process is not None and self._loaded == spec):
            return
        self._loading = spec
        threading.Thread(target=self._prepare, args=(spec,), name="voice-load", daemon=True).start()

    def release(self) -> None:
        """The conversation is over: the voice goes back, a failure is forgotten."""
        with self._state:
            self._until = 0.0
            self._spec = None
            self._failed = False
        with self._work:
            self._stop_process()

    def active(self) -> bool:
        """Whether a conversation holds the voice and it has not failed."""
        with self._state:
            return self._clock() < self._until and not self._failed and self._spec is not None

    def loaded(self) -> bool:
        return self._process is not None and self._loaded is not None

    # --- speaking ------------------------------------------------------------

    def speak(self, text: str, *, language: str, sampling: dict[str, float]) -> bytes:
        """One piece, as WAV bytes. Raises ``VoiceUnavailable`` for anything
        that stops it; the caller speaks it through ``llama-tts`` then."""
        with self._work:
            with self._state:
                failed, spec = self._failed, self._spec
            if failed:
                raise VoiceUnavailable("failed_earlier")
            if spec is None:
                raise VoiceUnavailable("no_conversation")
            try:
                self._ensure_loaded(spec)
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp) / "voice.wav"
                    reply = self._ask(
                        {"op": "speak", "text": text, "language": language,
                         "sampling": sampling, "out": str(target)},
                        SPEAK_TIMEOUT,
                    )
                    if not reply.get("ok") or not target.is_file():
                        raise VoiceUnavailable(str(reply.get("error") or "no_output"))
                    return target.read_bytes()
            except VoiceUnavailable as error:
                self._fail(error.reason)
                raise

    # --- ending ----------------------------------------------------------------

    def stop(self, wait: float | None = None) -> None:
        """The service is ending.

        ``wait`` is how long to wait for the work that holds the voice (a
        load takes minutes): when it is not over by then, the process is ended
        from outside, which ends the work too, as its pipe closes. ``None`` is
        the unlimited wait of before, for every caller that is not a shutdown.
        """
        with self._state:
            self._until = 0.0
        if wait is None:
            self._work.acquire()
        elif not self._work.acquire(timeout=wait):
            process = self._process
            if process is not None and process.poll() is None:
                process.kill()
            return
        try:
            self._stop_process(5 if wait is None else wait)
        finally:
            self._work.release()

    # --- inside ------------------------------------------------------------------

    def _prepare(self, spec: VoiceSpec) -> None:
        """The background load a ``hold`` starts. A failure marks the
        conversation, and the first piece goes through ``llama-tts``."""
        with self._work:
            try:
                with self._state:
                    if self._failed or self._spec != spec:
                        return
                try:
                    self._ensure_loaded(spec)
                except VoiceUnavailable as error:
                    self._fail(error.reason)
            finally:
                self._loading = None

    def _ensure_loaded(self, spec: VoiceSpec) -> None:
        """Under ``_work``: the process runs and holds this spec."""
        if self._process is not None and self._process.poll() is not None:
            self._process = None
            self._loaded = None
        if self._process is not None and self._loaded == spec:
            return
        self._stop_process()
        try:
            self._process = subprocess.Popen(
                self._command(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                **no_window(),
            )
        except OSError as error:
            raise VoiceUnavailable(f"start: {error}") from None
        threading.Thread(
            target=self._drain, args=(self._process,), name="voice-stderr", daemon=True
        ).start()
        started = self._clock()
        reply = self._ask(
            {"op": "load", "library_dir": spec.library_dir, "model": spec.model,
             "mmproj": spec.mmproj, "speaker": spec.speaker,
             "gpu_layers": spec.gpu_layers, "threads": spec.threads},
            LOAD_TIMEOUT,
        )
        if not reply.get("ok"):
            raise VoiceUnavailable(str(reply.get("error") or "not_loaded"))
        self._loaded = spec
        log.info("Voice loaded in %.1fs and kept for the conversation", self._clock() - started)

    def _ask(self, request: dict, timeout: float) -> dict:
        """One request, one reply, with a time limit. A process that ends or
        does not answer is gone afterwards."""
        process = self._process
        if process is None or process.stdin is None or process.stdout is None:
            raise VoiceUnavailable("no_process")
        answer: list[str] = []

        def read() -> None:
            try:
                answer.append(process.stdout.readline())  # type: ignore[union-attr]
            except (OSError, ValueError):
                answer.append("")

        try:
            process.stdin.write(json.dumps(request) + "\n")
            process.stdin.flush()
        except (OSError, ValueError):
            self._stop_process()
            raise VoiceUnavailable("pipe_closed") from None
        reader = threading.Thread(target=read, name="voice-reply", daemon=True)
        reader.start()
        reader.join(timeout)
        if reader.is_alive() or not answer or not answer[0]:
            tail = " | ".join(list(self._stderr)[-5:])
            self._stop_process()
            log.warning("Voice process gave no answer (%s): %s", request.get("op"), tail[-500:])
            raise VoiceUnavailable("no_answer")
        try:
            return json.loads(answer[0])
        except ValueError:
            self._stop_process()
            raise VoiceUnavailable("bad_answer") from None

    def _drain(self, process: subprocess.Popen) -> None:
        """The engine writes a great deal to standard error; an unread pipe
        would fill and stop it. The last lines are kept for a failure."""
        stream = process.stderr
        if stream is None:
            return
        try:
            for line in stream:
                self._stderr.append(line.rstrip())
        except (OSError, ValueError):
            pass

    def _stop_process(self, wait: float = 5) -> None:
        """Under ``_work``: asks the process to end, and ends it if it does not;
        ``wait`` seconds for the polite end, and as many for the hard one."""
        process, self._process, self._loaded = self._process, None, None
        if process is None:
            return
        try:
            if process.stdin is not None:
                process.stdin.write(json.dumps({"op": "quit"}) + "\n")
                process.stdin.flush()
                process.stdin.close()
        except (OSError, ValueError):
            pass
        try:
            process.wait(timeout=wait)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                process.wait(timeout=wait)
            except subprocess.TimeoutExpired:
                log.warning("Voice process did not end")

    def _fail(self, reason: str) -> None:
        """Under ``_work``."""
        with self._state:
            first = not self._failed
            self._failed = True
        if first:
            log.warning("Voice kept loaded is out for this conversation: %s", reason)
        self._stop_process()

    def _reap(self) -> None:
        """Gives the voice back when nobody announces the conversation any more."""
        while True:
            time.sleep(REAPER_SECONDS)
            with self._work:
                with self._state:
                    if self._clock() < self._until:
                        continue
                    self._spec = None
                    self._failed = False
                self._stop_process()
                return


__all__ = [
    "HOLD_SECONDS",
    "VoiceService",
    "VoiceSpec",
    "VoiceUnavailable",
    "worker_command",
]
