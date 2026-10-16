"""A sentence nobody waits for any more is not made to its end.

``/sprechen`` runs ``llama-tts`` (a model of a gigabyte or two, over a minute on
a small Mac). A conversation that ends while its next sentence is being made
used to leave that program running to its end. Now the route looks at the
request while it waits: a request that was given up ends the program, within
a second. A request that stays gets its WAV as before. A stand-in for the
program (a shell script that writes its process number and sleeps) stands for
a long-running one.
"""

from __future__ import annotations

import asyncio
import os
import stat
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest

from app import stimme

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="the stand-in program is a shell script")

SLEEPER = """#!/bin/sh
echo $$ > "{pid}"
exec sleep 60
"""

WRITER = """#!/bin/sh
while [ "$1" != "-o" ]; do shift; done
printf 'RIFF-spoken' > "$2"
"""


def _program(tmp_path: Path, body: str, **names: Path) -> Path:
    program = tmp_path / "llama-tts"
    program.write_text(body.format(**names))
    program.chmod(program.stat().st_mode | stat.S_IEXEC)
    return program


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _speak(program: Path, tmp_path: Path, **kwargs):
    return stimme.sprechen(
        program, tmp_path / "m.gguf", tmp_path / "mm.gguf", "Text",
        sprache="de", ordner=tmp_path, **kwargs,
    )


def test_a_cancel_ends_the_program_and_raises(tmp_path):
    pid_file = tmp_path / "pid"
    program = _program(tmp_path, SLEEPER, pid=pid_file)
    cancel = threading.Event()
    threading.Timer(0.5, cancel.set).start()

    began = time.monotonic()
    with pytest.raises(stimme.SpeakCancelled):
        _speak(program, tmp_path, cancel=cancel)

    assert time.monotonic() - began < 2
    assert not _alive(int(pid_file.read_text()))


def test_silence_without_a_cancel_the_program_runs_to_its_end(tmp_path):
    program = _program(tmp_path, WRITER)
    assert _speak(program, tmp_path, cancel=threading.Event()) == b"RIFF-spoken"
    assert _speak(program, tmp_path) == b"RIFF-spoken"


def _voice_ready(app, tmp_path: Path, program: Path, monkeypatch) -> None:
    folder = Path(app.state.sprachrunner.ordner)
    (folder / "vision").mkdir(parents=True, exist_ok=True)
    (folder / "voice-Q8_0.gguf").write_bytes(b"x")
    (folder / "vision" / "voice-Q8_0-mmproj-Q8_0.gguf").write_bytes(b"x")
    monkeypatch.setattr(stimme, "programm_finden", lambda llama_server: program)


async def _prepare(client: httpx.AsyncClient) -> None:
    answer = await client.put(
        "/api/v1/settings/global/diktat",
        json={"wert": {
            "stimme": "voice-Q8_0.gguf", "stimmsprache": "de", "keep_model_in_memory": False,
        }},
    )
    assert answer.status_code == 200, answer.text


@pytest.mark.asyncio
async def test_a_request_that_is_given_up_ends_the_program_within_a_second(
    laufender_server, tmp_path, monkeypatch
):
    app, base = laufender_server
    pid_file = tmp_path / "pid"
    _voice_ready(app, tmp_path, _program(tmp_path, SLEEPER, pid=pid_file), monkeypatch)
    headers = {"X-Sitzungsschluessel": app.state.sitzungsschluessel}
    async with httpx.AsyncClient(base_url=base, timeout=60, headers=headers) as client:
        await _prepare(client)
        request = asyncio.create_task(client.post("/api/v1/sprachserver/sprechen", json={"text": "Hallo."}))
        for _ in range(100):
            if pid_file.exists() and pid_file.read_text().strip():
                break
            await asyncio.sleep(0.05)
        pid = int(pid_file.read_text())
        assert _alive(pid)

        request.cancel()
        with pytest.raises(asyncio.CancelledError):
            await request
        for _ in range(40):
            if not _alive(pid):
                break
            await asyncio.sleep(0.05)
        assert not _alive(pid), "the program ran on after its request was given up"


@pytest.mark.asyncio
async def test_silence_a_request_that_stays_gets_its_wav(laufender_server, tmp_path, monkeypatch):
    app, base = laufender_server
    _voice_ready(app, tmp_path, _program(tmp_path, WRITER), monkeypatch)
    headers = {"X-Sitzungsschluessel": app.state.sitzungsschluessel}
    async with httpx.AsyncClient(base_url=base, timeout=60, headers=headers) as client:
        await _prepare(client)
        answer = await client.post("/api/v1/sprachserver/sprechen", json={"text": "Hallo."})
    assert answer.status_code == 200
    assert answer.headers["content-type"] == "audio/wav"
    assert answer.content == b"RIFF-spoken"


# --- the window's side, pinned in the sources --------------------------------

ROOT = Path(__file__).resolve().parent.parent
BAR = (ROOT / "frontend/src/teile/Eingabeleiste.svelte").read_text(encoding="utf-8")
API = (ROOT / "frontend/src/lib/api.js").read_text(encoding="utf-8")


def test_the_call_for_a_sentence_can_be_called_off():
    assert "spracheSprechen: async (text, { signal } = {}) =>" in API
    speak = API[API.index("spracheSprechen:"):]
    assert "signal," in speak[: speak.index("return antwort.blob()")]


def test_every_reading_carries_one_abort_and_every_sentence_asks_with_it():
    assert BAR.count("abort: new AbortController(),") == 2
    assert "api.spracheSprechen(kopf.text, { signal: v.abort.signal })" in BAR


def test_stopping_a_reading_calls_off_its_sentence_in_the_making():
    stopping = BAR[BAR.index("function vorlesungStoppen()"):]
    assert "v.abort.abort()" in stopping[: stopping.index("gespraechAudioStoppen()")]


def test_the_end_of_a_conversation_stops_the_reading_before_it_gives_the_voice_back():
    ending = BAR[BAR.index("function gespraechBeenden()"):]
    ending = ending[: ending.index("\n  }")]
    assert ending.index("vorlesungStoppen()") < ending.index("voiceKeepStop()")
