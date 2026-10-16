"""The voice kept loaded for a conversation (app/voice_service.py).

The process behind it is a stand-in that speaks the same protocol
(tests/voice_stub_worker.py); what is run here is the service's own code:
the lease, the one load for many pieces, the end of the conversation and
what happens when the process fails.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from app import voice_service
from app.voice_service import VoiceService, VoiceSpec, VoiceUnavailable

STUB = str(Path(__file__).resolve().parent / "voice_stub_worker.py")
SAMPLING = {"temperature": 0.9, "top_k": 50.0, "top_p": 1.0, "min_p": 0.0, "repeat_penalty": 1.05}


def _spec(model: str = "voice.gguf") -> VoiceSpec:
    return VoiceSpec(
        library_dir="/engine", model=model, mmproj="voice-mmproj.gguf",
        speaker="sample.wav", gpu_layers=99, threads=0,
    )


@pytest.fixture
def log(tmp_path: Path, monkeypatch) -> Path:
    path = tmp_path / "stub.log"
    monkeypatch.setenv("VOICE_STUB_LOG", str(path))
    monkeypatch.delenv("VOICE_STUB_MODE", raising=False)
    return path


@pytest.fixture
def service(log):
    made = VoiceService(command=lambda: [sys.executable, STUB])
    yield made
    made.stop()


def _lines(log: Path) -> list[str]:
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


def _count(log: Path, word: str) -> int:
    return sum(1 for line in _lines(log) if line.split(" ", 1)[0] == word)


def _wait(condition, seconds: float = 5.0) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(0.02)
    return False


def test_three_pieces_of_a_conversation_load_the_voice_once(service, log):
    service.hold(_spec())
    assert _wait(service.loaded)
    pieces = [service.speak(text, language="de", sampling=SAMPLING) for text in ("eins", "zwei", "drei")]
    assert pieces == [b"RIFFstub:eins", b"RIFFstub:zwei", b"RIFFstub:drei"]
    assert _count(log, "load") == 1
    assert _count(log, "speak") == 3


def test_the_first_piece_waits_for_the_load_it_asked_for(service, log):
    """A piece that comes right behind the announcement is spoken by the
    voice once it is loaded, not refused for being early."""
    service.hold(_spec())
    assert service.speak("sofort", language="en", sampling=SAMPLING) == b"RIFFstub:sofort"
    assert _count(log, "load") == 1


def test_the_end_of_the_conversation_gives_the_voice_back(service, log):
    service.hold(_spec())
    assert _wait(service.loaded)
    service.release()
    assert not service.active() and not service.loaded()
    assert _lines(log)[-2:] == ["quit", "exit"]
    # And nothing speaks without a conversation any more.
    with pytest.raises(VoiceUnavailable):
        service.speak("danach", language="de", sampling=SAMPLING)


def test_a_conversation_that_is_no_longer_announced_gives_it_back(log, monkeypatch):
    monkeypatch.setattr(voice_service, "HOLD_SECONDS", 0.3)
    monkeypatch.setattr(voice_service, "REAPER_SECONDS", 0.05)
    made = VoiceService(command=lambda: [sys.executable, STUB])
    try:
        made.hold(_spec())
        assert _wait(made.loaded)
        assert _wait(lambda: not made.loaded() and not made.active(), seconds=5.0)
        assert _lines(log)[-1] == "exit"
    finally:
        made.stop()


def test_an_announcement_repeated_keeps_it_loaded_and_loads_once(service, log, monkeypatch):
    monkeypatch.setattr(voice_service, "HOLD_SECONDS", 0.5)
    monkeypatch.setattr(voice_service, "REAPER_SECONDS", 0.05)
    service.hold(_spec())
    assert _wait(service.loaded)
    for _ in range(8):
        time.sleep(0.15)
        service.hold(_spec())
    assert service.loaded() and service.active()
    assert _count(log, "load") == 1


def test_announcements_during_a_slow_load_neither_wait_for_it_nor_load_again(service, log, monkeypatch):
    """The page repeats its announcement while the voice loads; each of
    those calls runs in a thread of the service's pool, so none may sit
    behind the load, and none may start a load of its own."""
    monkeypatch.setenv("VOICE_STUB_MODE", "slow_load")
    monkeypatch.setenv("VOICE_STUB_DELAY", "1.5")
    service.hold(_spec())
    assert _wait(lambda: _count(log, "load") == 1)
    started = time.monotonic()
    for _ in range(5):
        service.hold(_spec())
        assert service.active()
    assert time.monotonic() - started < 0.5
    assert _wait(service.loaded, seconds=10.0)
    assert _count(log, "load") == 1


def test_another_voice_is_loaded_again_and_the_old_one_given_back(service, log):
    service.hold(_spec("one.gguf"))
    assert _wait(service.loaded)
    service.hold(_spec("two.gguf"))
    assert service.speak("hallo", language="de", sampling=SAMPLING) == b"RIFFstub:hallo"
    assert _count(log, "load") == 2
    assert _count(log, "quit") == 1


def test_a_voice_that_cannot_load_is_out_for_the_conversation(service, log, monkeypatch):
    """The first piece goes the plain way, and so does every one after it —
    the failed voice is not asked again until the conversation is over."""
    monkeypatch.setenv("VOICE_STUB_MODE", "load_fails")
    service.hold(_spec())
    assert _wait(lambda: not service.active())
    with pytest.raises(VoiceUnavailable):
        service.speak("eins", language="de", sampling=SAMPLING)
    with pytest.raises(VoiceUnavailable) as second:
        service.speak("zwei", language="de", sampling=SAMPLING)
    assert second.value.reason == "failed_earlier"
    assert _count(log, "load") == 1
    # A new announcement does not try again while the conversation goes on…
    service.hold(_spec())
    time.sleep(0.2)
    assert _count(log, "load") == 1
    # …and the next conversation does.
    service.release()
    monkeypatch.delenv("VOICE_STUB_MODE")
    service.hold(_spec())
    assert service.speak("neu", language="de", sampling=SAMPLING) == b"RIFFstub:neu"
    assert _count(log, "load") == 2


def test_a_piece_that_does_not_come_out_puts_the_voice_out_for_the_conversation(
    service, log, monkeypatch,
):
    monkeypatch.setenv("VOICE_STUB_MODE", "speak_fails")
    service.hold(_spec())
    assert _wait(service.loaded)
    with pytest.raises(VoiceUnavailable) as first:
        service.speak("eins", language="de", sampling=SAMPLING)
    assert first.value.reason == "prompt_failed"
    with pytest.raises(VoiceUnavailable) as second:
        service.speak("zwei", language="de", sampling=SAMPLING)
    assert second.value.reason == "failed_earlier"
    assert _count(log, "speak") == 1
    assert not service.active() and not service.loaded()


def test_a_process_that_dies_while_speaking_is_taken_for_a_failure(service, log, monkeypatch):
    monkeypatch.setenv("VOICE_STUB_MODE", "speak_dies")
    service.hold(_spec())
    assert _wait(service.loaded)
    with pytest.raises(VoiceUnavailable) as failure:
        service.speak("eins", language="de", sampling=SAMPLING)
    assert failure.value.reason == "no_answer"
    assert not service.loaded()


def test_a_command_that_cannot_start_is_a_failure_not_a_crash(log):
    made = VoiceService(command=lambda: ["/nonexistent/voice-process"])
    made.hold(_spec())
    assert _wait(lambda: not made.active())
    with pytest.raises(VoiceUnavailable):
        made.speak("eins", language="de", sampling=SAMPLING)
    made.stop()


def test_silence_without_an_announcement_nothing_starts(service, log):
    """Outside a conversation the service starts no process, however it is
    asked."""
    assert not service.active() and not service.loaded()
    with pytest.raises(VoiceUnavailable) as refused:
        service.speak("ohne gespraech", language="de", sampling=SAMPLING)
    assert refused.value.reason == "no_conversation"
    service.release()
    assert _lines(log) == []


def test_the_command_is_the_program_itself_packaged_and_start_py_from_source(monkeypatch):
    from app import paketierung

    monkeypatch.setattr(paketierung, "ist_eingefroren", lambda: True)
    monkeypatch.setattr(paketierung, "programmpfad", lambda: Path("/app/Exe AI"))
    assert voice_service.worker_command() == [str(Path("/app/Exe AI")), "--voice"]
    monkeypatch.setattr(paketierung, "ist_eingefroren", lambda: False)
    command = voice_service.worker_command()
    assert command[0] == sys.executable and command[1].endswith("start.py")
    assert command[2:] == ["--voice"]
