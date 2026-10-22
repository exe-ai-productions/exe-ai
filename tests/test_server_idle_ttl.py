"""The idle time of the local servers: after that many minutes without a request
a server frees its model, and the next request loads it again.

The five llama servers take it as ``--sleep-idle-seconds`` (minutes times 60);
the one place that writes the word is ``feineinstellungen.flags``, and every
server hands its stored idle time to it. The speech server leaves it out for as
long as "keep the model in memory" is on. The picture server has no such switch,
so the program ends the process once nothing was drawn for the stored time.
Empty is never, and a start without a time says exactly what it said before.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import bild_leerlauf, bildgeraete, diktatsprachewahl, embedding_start_choice
from app import agentenmodellwahl, feineinstellungenwahl, runnermodellwahl
from app.bildturbo import Bildturbo
from app.feineinstellungen import MAX_IDLE_MINUTES, Feineinstellungen, flags

WORD = "--sleep-idle-seconds"


# --- The one word ---------------------------------------------------------


def test_ten_minutes_are_six_hundred_seconds_on_the_command_line():
    assert flags(Feineinstellungen(idle_minutes=10)) == [WORD, "600"]


def test_without_a_time_the_command_line_has_no_word_for_it():
    assert flags(Feineinstellungen()) == []
    assert WORD not in flags(Feineinstellungen(idle_minutes=None, parallel=4, festnageln=True))


def test_an_empty_or_zero_time_is_never_and_nonsense_does_not_reach_the_engine():
    for roh in (None, "", 0, "abc", [], {}):
        assert Feineinstellungen.aus_daten({"idle_minutes": roh}).idle_minutes is None, roh
    assert Feineinstellungen.aus_daten({"idle_minutes": -5}).idle_minutes == 1
    # The engine reads seconds as a 32-bit number: the last whole minute below it.
    assert MAX_IDLE_MINUTES * 60 <= 2**31 - 1 < (MAX_IDLE_MINUTES + 1) * 60
    assert Feineinstellungen.aus_daten({"idle_minutes": 10**12}).idle_minutes == MAX_IDLE_MINUTES


def test_the_other_levers_keep_their_words_beside_the_time():
    fein = Feineinstellungen(faeden=4, festnageln=True, parallel=2, idle_minutes=3)
    zeile = flags(fein)
    assert zeile[:-2] == flags(Feineinstellungen(faeden=4, festnageln=True, parallel=2))
    assert zeile[-2:] == [WORD, "180"]


# --- Every server's own store holds it and hands it to the start ----------


def test_the_model_server_choice_holds_the_time(client: TestClient):
    client.app.state.repositories.einstellungen.setzen(
        "global", feineinstellungenwahl.SCHLUESSEL, {"idle_minutes": 25}
    )
    fein = runnermodellwahl.startwerte(client.app.state.repositories, "m.gguf")["fein"]
    assert fein.idle_minutes == 25 and flags(fein) == [WORD, "1500"]


def test_the_agent_server_choice_holds_the_time(client: TestClient):
    client.app.state.repositories.einstellungen.setzen(
        "global", agentenmodellwahl.SCHLUESSEL, {"fein": {"idle_minutes": 5}}
    )
    fein = agentenmodellwahl.slot_startwerte(client.app.state.repositories)["fein"]
    assert fein.idle_minutes == 5 and flags(fein) == [WORD, "300"]


def test_the_embedding_server_choice_holds_the_time_and_the_start_carries_it():
    assert embedding_start_choice.wahl_pruefen({"idle_minutes": "15"}) == {"idle_minutes": 15}
    assert embedding_start_choice.wahl_pruefen({"idle_minutes": ""}) == {"idle_minutes": None}
    assert embedding_start_choice.wahl_pruefen({"idle_minutes": "x"}) == {}
    assert embedding_start_choice.VORGABE["idle_minutes"] is None


def test_the_embedding_start_command_names_the_time(client: TestClient, monkeypatch):
    seen: dict = {}
    runner = client.app.state.einbettungsrunner
    monkeypatch.setattr(runner, "starten", lambda modell, **kw: seen.update(kw))
    client.patch("/api/v1/settings/global/embedding", json={"wert": {"idle_minutes": 10}})
    assert client.post("/api/v1/einbettungsserver/start", json={"modell": "e.gguf"}).status_code == 200
    befehl = runner.befehl("e.gguf", seen["kontext"], seen["schichten"], 8081,
                           fein=seen["fein"], extra_flags=seen["extra_flags"])
    assert befehl[befehl.index(WORD) + 1] == "600"
    # And the answer to the window carries it back.
    assert client.get("/api/v1/einbettungsserver").json()["idle_minutes"] == 10


def test_the_embedding_start_without_a_time_has_no_word_for_it(client: TestClient, monkeypatch):
    seen: dict = {}
    runner = client.app.state.einbettungsrunner
    monkeypatch.setattr(runner, "starten", lambda modell, **kw: seen.update(kw))
    assert client.post("/api/v1/einbettungsserver/start", json={"modell": "e.gguf"}).status_code == 200
    befehl = runner.befehl("e.gguf", seen["kontext"], seen["schichten"], 8081,
                           fein=seen["fein"], extra_flags=seen["extra_flags"])
    assert WORD not in befehl
    assert client.get("/api/v1/einbettungsserver").json()["idle_minutes"] is None


def test_the_speech_and_cleanup_times_are_checked_like_the_other_numbers():
    pruefen = diktatsprachewahl.wahl_pruefen
    assert pruefen({"speech_idle_minutes": "5", "cleanup_idle_minutes": 7}) == {
        "speech_idle_minutes": 5, "cleanup_idle_minutes": 7,
    }
    # Empty and zero are "not set": the key is not there, the works answer (never) stands.
    assert pruefen({"speech_idle_minutes": 0, "cleanup_idle_minutes": ""}) == {}
    assert pruefen({"speech_idle_minutes": "x"}) == {}
    assert diktatsprachewahl.VORGABE["speech_idle_minutes"] is None
    assert diktatsprachewahl.VORGABE["cleanup_idle_minutes"] is None


def _diktat(client: TestClient, wert: dict) -> None:
    client.app.state.repositories.einstellungen.setzen("global", diktatsprachewahl.SCHLUESSEL, wert)


def test_the_speech_server_names_the_time_only_while_the_model_is_not_kept(client: TestClient):
    repositories = client.app.state.repositories
    _diktat(client, {"speech_idle_minutes": 7, "keep_model_in_memory": False})
    assert diktatsprachewahl.sprachstart(repositories)["leerlauf"] == 7
    _diktat(client, {"speech_idle_minutes": 7, "keep_model_in_memory": True})
    assert diktatsprachewahl.sprachstart(repositories)["leerlauf"] is None


def test_the_speech_start_hands_the_time_to_the_command(client: TestClient, monkeypatch):
    seen: dict = {}
    runner = client.app.state.sprachrunner
    monkeypatch.setattr(runner, "starten", lambda modell, **kw: seen.update(kw))
    _diktat(client, {"speech_idle_minutes": 7, "keep_model_in_memory": False})
    assert client.post("/api/v1/sprachserver/start", json={"modell": "s.gguf"}).status_code == 200
    assert flags(seen["fein"]) == [WORD, "420"]
    # With the model kept in memory the server never sleeps: no word.
    seen.clear()
    _diktat(client, {"speech_idle_minutes": 7, "keep_model_in_memory": True})
    assert client.post("/api/v1/sprachserver/start", json={"modell": "s.gguf"}).status_code == 200
    assert WORD not in flags(seen["fein"])


def test_the_cleanup_start_hands_the_time_to_the_command_and_nothing_without_one(
    client: TestClient, monkeypatch,
):
    seen: dict = {}
    runner = client.app.state.sprachputzrunner
    monkeypatch.setattr(runner, "starten", lambda modell, **kw: seen.update(kw))
    _diktat(client, {"cleanup_idle_minutes": 12})
    assert client.post("/api/v1/bereinigungsserver/start", json={"modell": "p.gguf"}).status_code == 200
    assert flags(seen["fein"]) == [WORD, "720"]
    assert diktatsprachewahl.putzleerlauf(client.app.state.repositories) == 12
    # Nothing stored: the start hands over no levers at all, as before.
    seen.clear()
    _diktat(client, {})
    assert client.post("/api/v1/bereinigungsserver/start", json={"modell": "p.gguf"}).status_code == 200
    assert seen["fein"] is None


# --- The picture server: ended by the program ------------------------------


def test_the_picture_settings_keep_the_idle_time_as_whole_minutes():
    assert bildgeraete.pruefen({"idle_minutes": 5}) == {"idle_minutes": 5}
    for roh in (0, -1, 2.5, "5", True, None):
        assert bildgeraete.pruefen({"idle_minutes": roh}) == {"idle_minutes": None}, roh
    assert bildgeraete.pruefen({"idle_minutes": MAX_IDLE_MINUTES + 1}) == {"idle_minutes": None}


class _Prozess:
    """A running process that records how it was ended."""

    pid = 4242

    def poll(self):
        return None


def _server(tmp_path, monkeypatch):
    """A picture server that thinks it runs; ending it is recorded, not done."""
    turbo = Bildturbo(tmp_path)
    turbo._prozess = _Prozess()
    ended: list[bool] = []
    monkeypatch.setattr(
        "app.bildturbo.prozessstopp.beenden", lambda prozess, frist=5.0: ended.append(True)
    )
    return turbo, ended


def test_the_picture_server_is_ended_once_nothing_was_drawn_for_the_time(tmp_path, monkeypatch):
    turbo, ended = _server(tmp_path, monkeypatch)
    start = turbo._zuletzt
    assert turbo.im_leerlauf_stoppen(1, start + 59) is False
    assert turbo._prozess is not None and ended == []
    assert turbo.im_leerlauf_stoppen(1, start + 60) is True
    assert turbo._prozess is None and ended == [True]


def test_a_picture_in_between_moves_the_time_on(tmp_path, monkeypatch):
    turbo, ended = _server(tmp_path, monkeypatch)
    start = turbo._zuletzt
    turbo._zuletzt = start + 50  # a picture ended at 50 s
    assert turbo.im_leerlauf_stoppen(1, start + 100) is False
    assert turbo.im_leerlauf_stoppen(1, start + 110) is True
    assert ended == [True]


def test_a_server_that_draws_or_stands_aside_is_never_ended(tmp_path, monkeypatch):
    turbo, ended = _server(tmp_path, monkeypatch)
    far = turbo._zuletzt + 10_000
    turbo._zeichnet = True
    assert turbo.im_leerlauf_stoppen(1, far) is False
    turbo._zeichnet = False
    turbo._paused_for = "x"
    assert turbo.im_leerlauf_stoppen(1, far) is False
    assert ended == []


def test_without_a_time_or_a_process_nothing_happens(tmp_path, monkeypatch):
    turbo, ended = _server(tmp_path, monkeypatch)
    far = turbo._zuletzt + 10_000
    for minuten in (None, 0):
        assert turbo.im_leerlauf_stoppen(minuten, far) is False
    assert Bildturbo(tmp_path).im_leerlauf_stoppen(1, far) is False
    assert ended == []


def test_a_server_ended_by_its_idle_time_is_remembered_until_started_or_stopped(tmp_path, monkeypatch):
    turbo, _ended = _server(tmp_path, monkeypatch)
    assert turbo.im_leerlauf_beendet() is False
    assert turbo.im_leerlauf_stoppen(1, turbo._zuletzt + 60) is True
    assert turbo.im_leerlauf_beendet() is True
    # A stop by hand is a wish to have it off: no picture starts it then.
    turbo.stoppen()
    assert turbo.im_leerlauf_beendet() is False


def test_a_server_that_was_never_ended_by_idle_is_not_remembered(tmp_path, monkeypatch):
    turbo, _ended = _server(tmp_path, monkeypatch)
    turbo.pause("x")
    assert turbo.im_leerlauf_beendet() is False
    assert Bildturbo(tmp_path).im_leerlauf_stoppen(1, 10_000.0) is False


def test_the_next_picture_goes_to_the_server_its_idle_time_ended(tmp_path, monkeypatch):
    from app.api.v1 import bild

    monkeypatch.setattr(bild, "_cli_only_reason", lambda auftrag, lora_aktiv: None)
    turbo, _ended = _server(tmp_path, monkeypatch)
    assert bild._draws_on_server(turbo, object(), False) is True  # type: ignore[arg-type]
    turbo.im_leerlauf_stoppen(1, turbo._zuletzt + 60)
    assert turbo.laeuft() is False
    assert bild._draws_on_server(turbo, object(), False) is True  # type: ignore[arg-type]
    # Stopped by hand, the picture goes to sd-cli as it always did.
    turbo.stoppen()
    assert bild._draws_on_server(turbo, object(), False) is False  # type: ignore[arg-type]


def test_the_look_at_the_status_is_no_picture(tmp_path, monkeypatch):
    """The page asks ``zustand`` every few seconds: that must not move the time."""
    turbo, ended = _server(tmp_path, monkeypatch)
    monkeypatch.setattr(turbo, "_bereit", lambda: True)
    start = turbo._zuletzt
    turbo.zustand()
    assert turbo._zuletzt == start


def test_the_watch_reads_the_stored_time_at_every_look(client: TestClient, monkeypatch):
    turbo = client.app.state.bildturbo
    seen: list = []

    def merken(minuten, jetzt=None):
        seen.append(minuten)
        return False

    monkeypatch.setattr(turbo, "im_leerlauf_stoppen", merken)
    repositories = client.app.state.repositories
    assert bild_leerlauf.pruefen(client.app) is False
    assert seen == []  # no time stored: the server is not even asked
    repositories.einstellungen.setzen("global", bildgeraete.SCHLUESSEL, {"idle_minutes": 3})
    bild_leerlauf.pruefen(client.app)
    assert seen == [3]
    repositories.einstellungen.setzen("global", bildgeraete.SCHLUESSEL, {"idle_minutes": 9})
    bild_leerlauf.pruefen(client.app)
    assert seen == [3, 9]


def test_silence_the_shipped_answers_carry_no_idle_time():
    assert Feineinstellungen().idle_minutes is None
    assert embedding_start_choice.VORGABE["idle_minutes"] is None
    assert diktatsprachewahl.VORGABE["speech_idle_minutes"] is None
    assert diktatsprachewahl.VORGABE["cleanup_idle_minutes"] is None
