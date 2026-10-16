"""The routes of the kept voice: the announcement of a conversation, its
end, and what `/sprechen` does in and outside of one."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import diktatsprachewahl, stimme
from app.voice_service import VoiceSpec, VoiceUnavailable

HOLD = "/api/v1/sprachserver/voice/hold"
RELEASE = "/api/v1/sprachserver/voice/release"
SPEAK = "/api/v1/sprachserver/sprechen"
SETTING = "/api/v1/settings/global/diktat"


class FakeVoice:
    """What the app's state holds in place of the service: no process, only
    the calls it was given."""

    def __init__(self) -> None:
        self.running = False
        self.held: list[VoiceSpec] = []
        self.spoken: list[tuple[str, str, dict]] = []
        self.released = 0
        self.fail: str | None = None

    def hold(self, spec: VoiceSpec) -> None:
        self.running = True
        self.held.append(spec)

    def release(self) -> None:
        self.running = False
        self.released += 1

    def active(self) -> bool:
        return self.running

    def speak(self, text: str, *, language: str, sampling: dict) -> bytes:
        if self.fail:
            raise VoiceUnavailable(self.fail)
        self.spoken.append((text, language, sampling))
        return b"RIFF-kept:" + text.encode()

    def stop(self) -> None:
        self.running = False


class FakeLibrary:
    """The engine's own copy, as the app's state holds it in place of the
    real one: a folder (or none yet) and a count of conversations that ended."""

    def __init__(self, folder: Path | None) -> None:
        self.folder = folder
        self.over = 0

    def directory(self) -> Path | None:
        return self.folder

    def conversation_over(self) -> None:
        self.over += 1


@pytest.fixture
def voice(client: TestClient, monkeypatch) -> FakeVoice:
    fake = FakeVoice()
    client.app.state.voice_service = fake
    client.app.state.voice_library = FakeLibrary(Path("/engine"))
    # The works answer for "keep the model loaded" follows the machine's memory;
    # these tests are about a machine that has plenty.
    monkeypatch.setattr(diktatsprachewahl, "gesamt_gb", lambda: 64.0)
    monkeypatch.setattr(stimme, "programm_finden", lambda llama_server: Path("/bin/llama-tts"))
    return fake


def _voice_files(client: TestClient, **setting) -> Path:
    folder = Path(client.app.state.sprachrunner.ordner)
    (folder / "vision").mkdir(parents=True, exist_ok=True)
    (folder / "voice-Q8_0.gguf").write_bytes(b"x")
    (folder / "vision" / "voice-Q8_0-mmproj-Q8_0.gguf").write_bytes(b"x")
    (folder / "sample.wav").write_bytes(b"RIFF")
    wert = {"stimme": "voice-Q8_0.gguf", "stimmsprache": "de", "stimmprobe": "sample.wav", **setting}
    client.put(SETTING, json={"wert": wert})
    return folder


@pytest.fixture
def plain(monkeypatch) -> list:
    """`llama-tts`, as the program that speaks when the kept voice does not."""
    calls: list = []
    monkeypatch.setattr(stimme, "sprechen", lambda *a, **kw: calls.append(a[3]) or b"RIFF-plain")
    return calls


def test_the_conversation_is_announced_with_what_the_voice_is_loaded_with(
    client: TestClient, voice: FakeVoice,
):
    folder = _voice_files(client, stimmschichten=40, stimmfaeden=6)
    answer = client.post(HOLD)
    assert answer.status_code == 200 and answer.json() == {"kept": True}
    assert voice.held == [VoiceSpec(
        library_dir="/engine", model=str(folder / "voice-Q8_0.gguf"),
        mmproj=str(folder / "vision" / "voice-Q8_0-mmproj-Q8_0.gguf"),
        speaker=str(folder / "sample.wav"), gpu_layers=40, threads=6,
    )]


def test_the_switch_ships_on_and_a_stored_off_is_kept(client: TestClient, monkeypatch):
    monkeypatch.setattr(diktatsprachewahl, "gesamt_gb", lambda: 64.0)
    shown = client.get("/api/v1/sprachserver").json()["diktat_vorgaben"]
    assert shown["keep_model_in_memory"] is True
    client.put(SETTING, json={"wert": {"keep_model_in_memory": False}})
    stored = client.get("/api/v1/settings/resolved/diktat").json()["wert"]
    assert stored["keep_model_in_memory"] is False


def test_with_the_switch_off_nothing_is_kept_and_what_is_held_goes_back(
    client: TestClient, voice: FakeVoice,
):
    _voice_files(client, keep_model_in_memory=False)
    answer = client.post(HOLD)
    assert answer.json() == {"kept": False}
    assert voice.held == [] and voice.released == 1


def test_without_reading_aloud_no_voice_is_kept_loaded_for_nothing(
    client: TestClient, voice: FakeVoice,
):
    """Nothing is spoken with the first switch off, so the conversation does
    not load the voice either, however the second switch stands."""
    _voice_files(client, vorlesen=False, keep_model_in_memory=True)
    assert client.post(HOLD).json() == {"kept": False}
    assert voice.held == [] and voice.released == 1


def test_a_conversation_without_a_chosen_voice_is_no_failure(client: TestClient, voice: FakeVoice):
    """The announcement is answered, not refused: the conversation goes on
    and the sentence route says what is missing when a piece is asked for."""
    answer = client.post(HOLD)
    assert answer.status_code == 200 and answer.json() == {"kept": False}
    assert voice.held == []


def test_without_the_engines_own_copy_nothing_is_kept(client: TestClient, voice: FakeVoice):
    _voice_files(client)
    client.app.state.voice_library.folder = None
    assert client.post(HOLD).json() == {"kept": False}
    assert voice.held == []


def test_the_end_of_the_conversation_is_told_to_the_service(client: TestClient, voice: FakeVoice):
    assert client.post(RELEASE).status_code == 204
    assert voice.released == 1
    assert client.app.state.voice_library.over == 1


def test_in_a_conversation_the_kept_voice_speaks_and_llama_tts_does_not(
    client: TestClient, voice: FakeVoice, plain: list,
):
    _voice_files(client, stimmtemperatur=0.4)
    client.post(HOLD)
    answer = client.post(SPEAK, json={"text": "Guten Tag."})
    assert answer.status_code == 200
    assert answer.headers["content-type"] == "audio/wav"
    assert answer.content == b"RIFF-kept:Guten Tag."
    assert plain == []
    text, language, sampling = voice.spoken[0]
    assert (text, language) == ("Guten Tag.", "de")
    assert sampling["temperature"] == 0.4 and sampling["top_k"] == stimme.TOP_K


def test_outside_a_conversation_llama_tts_speaks_and_nothing_is_started(
    client: TestClient, voice: FakeVoice, plain: list,
):
    _voice_files(client)
    answer = client.post(SPEAK, json={"text": "Einzeln."})
    assert answer.content == b"RIFF-plain"
    assert plain == ["Einzeln."]
    assert voice.spoken == [] and voice.held == []


def test_with_the_switch_off_llama_tts_speaks_even_in_a_conversation(
    client: TestClient, voice: FakeVoice, plain: list,
):
    _voice_files(client)
    client.post(HOLD)
    # The whole stored row, as the setting is written: a put replaces it.
    _voice_files(client, keep_model_in_memory=False)
    answer = client.post(SPEAK, json={"text": "Aus."})
    assert answer.content == b"RIFF-plain"
    assert voice.spoken == []


def test_a_piece_the_kept_voice_does_not_bring_out_is_spoken_by_llama_tts(
    client: TestClient, voice: FakeVoice, plain: list,
):
    _voice_files(client)
    client.post(HOLD)
    voice.fail = "prompt_failed"
    answer = client.post(SPEAK, json={"text": "Trotzdem."})
    assert answer.status_code == 200
    assert answer.content == b"RIFF-plain"
    assert plain == ["Trotzdem."]


def test_the_session_key_covers_the_new_routes(client: TestClient):
    client.headers.pop("X-Sitzungsschluessel", None)
    assert client.post(HOLD).status_code == 401
    assert client.post(RELEASE).status_code == 401
