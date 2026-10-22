"""Any voice model runs, and the voices of the system speak by name.

The voice was cut to Qwen3-TTS: the language flag and the five generation
values went to every voice model, and without a language the route refused.
Now "-" in the language and "Auto" in any of the five values leave that flag
out and the program takes its own; a stored value is sent to every voice model,
not only to Qwen. The values a machine starts with stay the ones Qwen was
measured with, so Qwen speaks as before.

The voices of the system share the field "Stimme" with the voice models: a
name the system lists speaks through the system; a voice that cannot speak
(its file is gone, its program or projector is missing, it fails) is replaced
by the voice of the system for the rest of the conversation, and the reason
stands on WARNING.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import diktatsprachewahl, stimme, system_voice, voice_worker

ROW = "/api/v1/settings/global/diktat"
SPEAK = "/api/v1/sprachserver/sprechen"
FIVE = ("stimmtemperatur", "stimmtop_k", "stimmtop_p", "stimmmin_p", "stimmstrafe")


class _Run:
    def __init__(self, returncode: int = 0, stderr: str = "") -> None:
        self.returncode = returncode
        self.stderr = stderr


def _command(tmp_path, monkeypatch, **kwargs) -> list[str]:
    """The command ``stimme.sprechen`` builds, without starting anything."""
    seen: dict = {}

    def run(befehl, **kw):
        seen["befehl"] = befehl
        Path(befehl[befehl.index("-o") + 1]).write_bytes(b"x")
        return _Run()

    monkeypatch.setattr(stimme, "_laufen", run)
    stimme.sprechen(
        Path("/bin/llama-tts"), tmp_path / "m.gguf", tmp_path / "mm.gguf", "Text",
        ordner=tmp_path, **kwargs,
    )
    return seen["befehl"]


def test_no_language_and_five_values_on_auto_leave_all_six_flags_out(tmp_path, monkeypatch):
    befehl = _command(tmp_path, monkeypatch, sprache="", sampling={})
    for flag in ("--tts-lang", "--temp", "--top-k", "--top-p", "--min-p", "--repeat-penalty"):
        assert flag not in befehl, flag
    # The rest of the command stays: model, projector, text, the fixed context.
    assert befehl[:7] == [str(Path("/bin/llama-tts")), "-m", str(tmp_path / "m.gguf"), "-mm", str(tmp_path / "mm.gguf"), "-p", "Text"]
    assert "-c" in befehl


def test_one_value_on_auto_leaves_only_its_own_flag_out(tmp_path, monkeypatch):
    befehl = _command(
        tmp_path, monkeypatch, sprache="de",
        sampling={"temperature": 0.5, "top_p": 1.0, "min_p": 0.0, "repeat_penalty": 1.05},
    )
    assert "--top-k" not in befehl
    assert befehl[befehl.index("--temp") + 1] == "0.5"
    assert befehl[befehl.index("--tts-lang") + 1] == "de"


def test_silence_german_and_the_values_of_qwen_give_the_command_of_before(tmp_path, monkeypatch):
    """Character for character what was always sent for Qwen."""
    values = {
        "temperature": stimme.TEMPERATUR, "top_k": stimme.TOP_K, "top_p": stimme.TOP_P,
        "min_p": stimme.MIN_P, "repeat_penalty": stimme.WIEDERHOLUNGSSTRAFE,
    }
    befehl = _command(tmp_path, monkeypatch, sprache="de", sampling=values)
    ziel = befehl[befehl.index("-o") + 1]
    assert befehl == [
        str(Path("/bin/llama-tts")), "-m", str(tmp_path / "m.gguf"), "-mm", str(tmp_path / "mm.gguf"), "-p", "Text",
        "--tts-lang", "de", "-o", ziel, "-c", "4096",
        "--temp", "0.9", "--top-k", "50", "--top-p", "1.0", "--min-p", "0.0", "--repeat-penalty", "1.05",
    ]
    # Without a dict of values the constants stand in, the same command.
    assert _command(tmp_path, monkeypatch, sprache="de")[7:9] == ["--tts-lang", "de"]


def test_auto_is_stored_as_the_word_for_the_voice_only():
    stored = diktatsprachewahl.wahl_pruefen({name: "auto" for name in FIVE})
    assert stored == {name: "auto" for name in FIVE}
    # The tidy-up server's values take no Auto: the word would reach its start.
    assert diktatsprachewahl.wahl_pruefen({"putztop_k": "auto", "putztemperatur": "auto"}) == {}
    # Nonsense is no choice.
    assert diktatsprachewahl.wahl_pruefen({"stimmtop_k": "x", "stimmtemperatur": "x"}) == {}


def test_the_values_on_auto_are_left_out_of_what_the_voice_is_asked_with(client: TestClient):
    client.patch(ROW, json={"wert": {"stimmtop_k": "auto", "stimmtemperatur": 0.4}})
    # Read fresh from the stored setting, the way the route reads it.
    repositories = client.app.state.repositories
    assert diktatsprachewahl.stimmwerte(repositories) == {
        "temperature": 0.4, "top_p": 1.0, "min_p": 0.0, "repeat_penalty": 1.05,
    }


def test_a_null_goes_back_to_the_value_of_qwen_and_not_to_auto(client: TestClient):
    client.patch(ROW, json={"wert": {"stimmtop_k": "auto"}})
    client.patch(ROW, json={"wert": {"stimmtop_k": None}})
    repositories = client.app.state.repositories
    assert diktatsprachewahl.stimmwerte(repositories)["top_k"] == float(stimme.TOP_K)


def test_the_report_names_where_the_sliders_rest_on_auto():
    vorgaben = diktatsprachewahl.vorgaben()
    assert vorgaben["stimmauto"] == {
        "stimmtemperatur": 0.8, "stimmtop_k": 40, "stimmtop_p": 0.95, "stimmmin_p": 0.05, "stimmstrafe": 1.05,
    }
    assert vorgaben["stimme"] == system_voice.factory_voice()


def test_the_kept_voice_takes_the_values_of_the_program_for_what_is_left_out():
    """The voice process fills a value that is not there with what `llama-tts`
    of the same build takes without being told (its own `--help`)."""
    assert voice_worker.AUTO_SAMPLING == {
        "temperature": 0.8, "top_k": 40, "top_p": 0.95, "min_p": 0.05, "repeat_penalty": 1.05,
    }
    calls: list[tuple[str, tuple]] = []

    class Llama:
        def llama_sampler_chain_default_params(self):
            return None

        def llama_sampler_chain_init(self, params):
            return "chain"

        def llama_sampler_chain_add(self, chain, stage):
            pass

        def __getattr__(self, name):
            if name.startswith("llama_sampler_init_"):
                def make(*args):
                    calls.append((name.removeprefix("llama_sampler_init_"), args))
                    return name
                return make
            raise AttributeError(name)

    voice = voice_worker.Voice()
    voice.llama = Llama()
    voice._sampler_chain({})
    seen = dict(calls)
    assert seen["penalties"][1] == 1.05
    assert seen["top_k"] == (40,)
    assert seen["top_p"][0] == 0.95
    assert seen["min_p"][0] == 0.05
    assert seen["temp"] == (0.8,)
    calls.clear()
    voice._sampler_chain({"temperature": 0.9, "top_k": 50, "top_p": 1.0, "min_p": 0.0, "repeat_penalty": 1.05})
    seen = dict(calls)
    assert seen["top_k"] == (50,) and seen["temp"] == (0.9,)


# --- the route ---------------------------------------------------------------


def _model(client: TestClient, name="stimme-Q8_0.gguf", **wert) -> Path:
    ordner = Path(client.app.state.sprachrunner.ordner)
    (ordner / "vision").mkdir(parents=True, exist_ok=True)
    (ordner / name).write_bytes(b"x")
    (ordner / "vision" / name.replace(".gguf", "-mmproj-Q8_0.gguf")).write_bytes(b"x")
    client.put(ROW, json={"wert": {"stimme": name, "stimmsprache": "de", **wert}})
    return ordner


@pytest.fixture
def system(monkeypatch):
    """A Mac with the voice "Anna" that records what it is asked to say."""
    monkeypatch.setattr(system_voice, "available", lambda: True)
    monkeypatch.setattr(system_voice, "factory_voice", lambda: "Anna")
    monkeypatch.setattr(
        system_voice, "_read_voices",
        lambda: [system_voice.SystemVoice("Anna", "de_DE"), system_voice.SystemVoice("Albert", "en_US")],
    )
    system_voice.forget_voices()
    spoken: list[tuple[str, str]] = []

    def speak(text, voice, *, cancel=None):
        spoken.append((voice, text))
        return b"RIFF-SYSTEM"

    monkeypatch.setattr(system_voice, "speak", speak)
    return spoken


@pytest.fixture
def tts(monkeypatch):
    """`llama-tts` is found; what it is asked is recorded, and `fail` makes it fail."""
    monkeypatch.setattr(stimme, "programm_finden", lambda llama_server: Path("/bin/llama-tts"))
    asked: list[dict] = []
    state = {"fail": False}

    def sprechen(programm, modell, mmproj, text, **kw):
        asked.append({"text": text, **kw})
        if state["fail"]:
            raise stimme.SprechenNichtMoeglich("stimme_fehlgeschlagen")
        return b"RIFF-TTS"

    monkeypatch.setattr(stimme, "sprechen", sprechen)
    asked_state = type("Tts", (), {"asked": asked, "state": state})
    return asked_state


def test_the_values_on_auto_never_reach_the_program(client: TestClient, tts):
    _model(client, stimmtop_k="auto", stimmtemperatur="auto")
    assert client.post(SPEAK, json={"text": "Hallo."}).status_code == 200
    sampling = tts.asked[-1]["sampling"]
    assert "top_k" not in sampling and "temperature" not in sampling
    assert sampling["top_p"] == 1.0 and sampling["repeat_penalty"] == 1.05


def test_a_value_that_is_set_goes_to_every_voice_model(client: TestClient, tts):
    _model(client, "pocket-tts.gguf", stimmtop_k=33)
    assert client.post(SPEAK, json={"text": "Hallo."}).status_code == 200
    assert tts.asked[-1]["sampling"]["top_k"] == 33.0


def test_a_voice_of_the_system_speaks_by_name_and_no_program_is_asked(client: TestClient, tts, system):
    client.put(ROW, json={"wert": {"stimme": "Albert", "stimmsprache": "de"}})
    answer = client.post(SPEAK, json={"text": "Hello."})
    assert answer.status_code == 200 and answer.content == b"RIFF-SYSTEM"
    assert system == [("Albert", "Hello.")]
    assert tts.asked == []


def test_the_voice_a_machine_starts_with_speaks_while_nothing_is_stored(client: TestClient, tts, system):
    answer = client.post(SPEAK, json={"text": "Guten Tag."})
    assert answer.status_code == 200
    assert system == [("Anna", "Guten Tag.")]


def test_the_empty_choice_still_refuses_in_plain_words(client: TestClient, tts, system):
    client.put(ROW, json={"wert": {"stimme": ""}})
    answer = client.post(SPEAK, json={"text": "Hallo."})
    assert answer.status_code == 409 and answer.json()["detail"]
    assert system == [] and tts.asked == []


def test_a_voice_model_that_fails_is_replaced_for_the_rest_of_the_conversation(
    client: TestClient, tts, system, caplog
):
    _model(client)
    tts.state["fail"] = True
    with caplog.at_level("WARNING", logger="app.api.v1.sprachserver"):
        first = client.post(SPEAK, json={"text": "Eins."})
    assert first.status_code == 200 and first.content == b"RIFF-SYSTEM"
    assert "cannot speak" in caplog.text and "llama-tts failed" in caplog.text
    assert system == [("Anna", "Eins.")]
    assert len(tts.asked) == 1
    # Even where the program would speak again, it is not asked again until
    # the conversation is over.
    tts.state["fail"] = False
    second = client.post(SPEAK, json={"text": "Zwei."})
    assert second.content == b"RIFF-SYSTEM"
    assert system[-1] == ("Anna", "Zwei.")
    assert len(tts.asked) == 1
    # The end of the conversation asks it again.
    assert client.post("/api/v1/sprachserver/voice/release").status_code == 204
    third = client.post(SPEAK, json={"text": "Drei."})
    assert third.content == b"RIFF-TTS"
    assert len(tts.asked) == 2


def test_a_conversation_whose_page_went_away_lets_the_voice_model_be_asked_again(
    client: TestClient, tts, system
):
    """The stand-in holds as long as the conversation announces itself; with
    no word for the time it holds, the chosen voice is asked again."""
    _model(client)
    tts.state["fail"] = True
    client.post(SPEAK, json={"text": "Eins."})
    assert len(tts.asked) == 1
    tts.state["fail"] = False
    name, _deadline = client.app.state.voice_fallback
    client.app.state.voice_fallback = (name, 0.0)
    assert client.post(SPEAK, json={"text": "Zwei."}).content == b"RIFF-TTS"
    assert len(tts.asked) == 2


def test_silence_a_voice_model_that_speaks_is_asked_every_time_and_the_system_is_not(
    client: TestClient, tts, system
):
    _model(client)
    for text in ("Eins.", "Zwei."):
        assert client.post(SPEAK, json={"text": text}).content == b"RIFF-TTS"
    assert len(tts.asked) == 2 and system == []


def test_the_voice_of_the_system_fills_in_with_the_default_voice_where_it_is_missing(
    client: TestClient, tts, system, monkeypatch
):
    monkeypatch.setattr(system_voice, "factory_voice", lambda: "Anette")
    client.put(ROW, json={"wert": {"stimme": "gone.gguf"}})
    answer = client.post(SPEAK, json={"text": "Hallo."})
    assert answer.status_code == 200
    # An empty name is the voice the system itself uses.
    assert system == [("", "Hallo.")]


def test_a_failing_voice_with_no_voice_to_fall_back_on_is_reported(client: TestClient, tts, monkeypatch):
    monkeypatch.setattr(system_voice, "available", lambda: False)
    _model(client)
    tts.state["fail"] = True
    assert client.post(SPEAK, json={"text": "Hallo."}).status_code == 502


def test_the_report_lists_the_voices_of_the_system_with_their_language(client: TestClient, system):
    report = client.get("/api/v1/sprachserver").json()
    assert report["system_voices"] == [
        {"name": "Anna", "language": "de_DE"}, {"name": "Albert", "language": "en_US"},
    ]
    # The voice a machine starts with is read once, from the system the
    # program runs on: a Mac "Anna", Windows "Microsoft Katja".
    assert report["diktat_vorgaben"]["stimme"] == diktatsprachewahl.VORGABE["stimme"]


def test_a_voice_of_the_system_is_not_kept_loaded(client: TestClient, tts, system):
    client.put(ROW, json={"wert": {"stimme": "Anna"}})
    answer = client.post("/api/v1/sprachserver/voice/hold")
    assert answer.status_code == 200 and answer.json() == {"kept": False}


def test_a_voice_that_failed_is_not_kept_loaded_again_in_the_same_conversation(
    client: TestClient, tts, system
):
    _model(client)
    tts.state["fail"] = True
    client.post(SPEAK, json={"text": "Eins."})
    assert client.post("/api/v1/sprachserver/voice/hold").json() == {"kept": False}
