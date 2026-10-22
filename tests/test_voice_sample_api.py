"""A voice sample can be recorded, played and deleted through the service.

The window records into the speech model folder: a recording is kept as
``stimmprobe-N.wav`` with the next free number and chosen as the voice sample
at once, the sample is handed back as a WAV, and deleting it takes the choice
along when it was the chosen one. Only a WAV that lies flat in that folder is
ever read or removed.
"""

from __future__ import annotations

import io
import wave
from pathlib import Path

from fastapi.testclient import TestClient

BASE = "/api/v1/sprachserver"
SAMPLE = f"{BASE}/voice-sample"
SETTING = "/api/v1/settings/global/diktat"


def _wav(seconds: float = 1.0, rate: int = 16000) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as datei:
        datei.setnchannels(1)
        datei.setsampwidth(2)
        datei.setframerate(rate)
        datei.writeframes(b"\x00\x00" * int(rate * seconds))
    return buffer.getvalue()


def _folder(client: TestClient) -> Path:
    folder = Path(client.app.state.sprachrunner.ordner)
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _save(client: TestClient, data: bytes | None = None):
    return client.post(SAMPLE, content=_wav() if data is None else data, headers={"Content-Type": "audio/wav"})


def test_the_first_recording_is_called_stimmprobe_1_and_lies_in_the_folder(client: TestClient):
    answer = _save(client)
    assert answer.status_code == 200, answer.text
    assert answer.json()["name"] == "stimmprobe-1.wav"
    assert (_folder(client) / "stimmprobe-1.wav").read_bytes() == _wav()


def test_the_next_recording_takes_the_next_free_number(client: TestClient):
    assert _save(client).json()["name"] == "stimmprobe-1.wav"
    assert _save(client).json()["name"] == "stimmprobe-2.wav"
    assert _save(client).json()["name"] == "stimmprobe-3.wav"


def test_after_the_first_is_deleted_the_next_recording_takes_its_number_again(client: TestClient):
    _save(client)
    _save(client)
    assert client.delete(f"{SAMPLE}/stimmprobe-1.wav").status_code == 200
    assert _save(client).json()["name"] == "stimmprobe-1.wav"
    assert client.get(BASE).json()["stimmproben"] == ["stimmprobe-1.wav", "stimmprobe-2.wav"]


def test_a_name_taken_by_something_that_is_no_file_is_skipped_not_waited_on(client: TestClient):
    # A folder under the first name: the list does not show it, the next
    # recording must still find a free name instead of trying it forever.
    (_folder(client) / "stimmprobe-1.wav").mkdir()
    assert _save(client).json()["name"] == "stimmprobe-2.wav"


def test_a_header_without_a_known_length_has_no_length_and_no_error(client: TestClient):
    streamed = bytearray(_wav())
    streamed[40:44] = b"\xff\xff\xff\xff"
    _save(client, bytes(streamed))
    assert client.get(BASE).json()["stimmproben_dauer"] == {"stimmprobe-1.wav": None}


def test_a_new_recording_is_chosen_as_the_voice_sample_at_once(client: TestClient):
    _save(client)
    assert client.get(SETTING).json()["wert"]["stimmprobe"] == "stimmprobe-1.wav"
    _save(client)
    assert client.get(SETTING).json()["wert"]["stimmprobe"] == "stimmprobe-2.wav"


def test_the_answer_of_the_service_lists_the_new_file_with_its_length(client: TestClient):
    answer = client.post(SAMPLE, content=_wav(2.5), headers={"Content-Type": "audio/wav"}).json()
    assert answer["seconds"] == 2.5
    state = client.get(BASE).json()
    assert state["stimmproben"] == ["stimmprobe-1.wav"]
    assert state["stimmproben_dauer"] == {"stimmprobe-1.wav": 2.5}


def test_only_a_wav_in_the_folder_is_handed_out(client: TestClient):
    _save(client)
    folder = _folder(client)
    (folder / "notes.txt").write_bytes(b"x")
    (folder.parent / "outside.wav").write_bytes(_wav())
    assert client.get(f"{SAMPLE}/stimmprobe-1.wav").content == _wav()
    assert client.get(f"{SAMPLE}/stimmprobe-1.wav").headers["content-type"] == "audio/wav"
    for refused in ("notes.txt", "outside.wav", "..%2Foutside.wav", "missing.wav"):
        assert client.get(f"{SAMPLE}/{refused}").status_code == 404, refused


def test_only_a_wav_in_the_folder_is_deleted(client: TestClient):
    folder = _folder(client)
    (folder / "notes.txt").write_bytes(b"x")
    (folder.parent / "outside.wav").write_bytes(_wav())
    for refused in ("notes.txt", "outside.wav", "..%2Foutside.wav", "missing.wav"):
        # A name with a slash in it matches no route at all, which is a refusal too.
        assert client.delete(f"{SAMPLE}/{refused}").status_code in (404, 405), refused
    assert (folder / "notes.txt").exists()
    assert (folder.parent / "outside.wav").exists()


def test_deleting_the_chosen_sample_empties_the_choice(client: TestClient):
    _save(client)
    answer = client.delete(f"{SAMPLE}/stimmprobe-1.wav")
    assert answer.status_code == 200
    assert answer.json()["stimmproben"] == []
    assert client.get(SETTING).json()["wert"]["stimmprobe"] == ""
    assert not (_folder(client) / "stimmprobe-1.wav").exists()


def test_deleting_another_sample_keeps_the_choice(client: TestClient):
    _save(client)
    _save(client)
    client.delete(f"{SAMPLE}/stimmprobe-1.wav")
    assert client.get(SETTING).json()["wert"]["stimmprobe"] == "stimmprobe-2.wav"


def test_a_recording_that_is_no_wav_or_empty_is_refused_and_nothing_is_written(client: TestClient):
    assert _save(client, b"not a wav at all").status_code == 400
    assert _save(client, b"").status_code == 400
    assert client.get(BASE).json()["stimmproben"] == []


def test_a_recording_over_the_ceiling_is_refused(client: TestClient):
    from app.api.v1.sprachserver import MAX_BYTES

    big = _wav() + b"\x00" * MAX_BYTES
    assert _save(client, big).status_code == 413
    assert client.get(BASE).json()["stimmproben"] == []


def test_silence_the_samples_already_in_the_folder_are_listed_as_before(client: TestClient):
    folder = _folder(client)
    (folder / "own.wav").write_bytes(b"RIFF")
    state = client.get(BASE).json()
    assert state["stimmproben"] == ["own.wav"]
    # A file whose header cannot be read has a length of nothing, not an error.
    assert state["stimmproben_dauer"] == {"own.wav": None}


def test_silence_the_speaking_and_transcribing_routes_still_answer_as_before(client: TestClient):
    # No server running: the same refusal the routes gave before.
    assert client.post(f"{BASE}/transkribieren", content=_wav(), headers={"Content-Type": "audio/wav"}).status_code == 409
    assert client.post(f"{BASE}/stop").status_code == 200
