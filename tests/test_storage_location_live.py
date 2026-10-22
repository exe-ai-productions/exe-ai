"""A storage location the user moves takes hold at once — for the list of
models, the command of the next start and the folder a download lands in, at
every server and not only at the first one built."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.modellrunner import Lauf, Modellrunner
from app.speicherorte import LiveFolders, setzen

SPEICHERORTE = "/api/v1/speicherorte"


def _model(folder: Path, name: str = "klein.gguf") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    datei = folder / name
    datei.write_bytes(b"GGUF" + b"\0" * 64)
    return datei


# --- The runner asks for its folder each time --------------------------------


def test_a_runner_with_a_folder_source_lists_the_folder_in_force(tmp_path):
    """Handed a function, the runner reads the folder it names at every
    listing — a folder set a moment ago is the one it lists."""
    alt, neu = tmp_path / "alt", tmp_path / "neu"
    _model(alt, "alt.gguf")
    _model(neu, "neu.gguf")
    aktuell = {"ordner": alt}
    runner = Modellrunner(lambda: aktuell["ordner"])

    assert [m.name for m in runner.modelle()] == ["alt.gguf"]
    aktuell["ordner"] = neu
    assert [m.name for m in runner.modelle()] == ["neu.gguf"]
    assert runner.ordner == neu


def test_the_start_command_names_the_folder_in_force(tmp_path):
    alt, neu = tmp_path / "alt", tmp_path / "neu"
    _model(alt)
    _model(neu)
    aktuell = {"ordner": alt}
    runner = Modellrunner(lambda: aktuell["ordner"], programm="llama-server")

    assert str(alt / "klein.gguf") in runner.befehl("klein.gguf", 4096, 33, 8081)
    aktuell["ordner"] = neu
    befehl = runner.befehl("klein.gguf", 4096, 33, 8081)
    assert str(neu / "klein.gguf") in befehl
    assert str(alt) not in " ".join(befehl)


def test_silence_a_runner_with_a_plain_folder_keeps_it(tmp_path):
    """The old form still works: a folder handed in stays the folder."""
    _model(tmp_path, "eins.gguf")
    runner = Modellrunner(tmp_path)
    assert [m.name for m in runner.modelle()] == ["eins.gguf"]
    assert runner.ordner == tmp_path


def test_the_note_of_a_running_server_is_dropped_where_it_was_written(tmp_path):
    """Moved while the server ran, the note is still taken from the folder it
    went into — not left behind as a stale pid that a later start would end."""
    alt, neu = tmp_path / "alt", tmp_path / "neu"
    alt.mkdir()
    neu.mkdir()
    aktuell = {"ordner": alt}
    runner = Modellrunner(lambda: aktuell["ordner"])

    runner._pid_merken(4242, Lauf(modell="klein.gguf", kontext=4096, schichten=None, port=8080))
    assert json.loads((alt / runner._pid_datei).read_text())["pid"] == 4242
    aktuell["ordner"] = neu
    runner._pid_vergessen()
    assert not (alt / runner._pid_datei).exists()


# --- The folders by kind follow the locations ---------------------------------


def test_the_folders_by_kind_follow_a_move(config, tmp_path):
    ordner = LiveFolders(
        config,
        {"chat": "models", "einbettung": "embedding_models"},
    )
    vorher = ordner["chat"]
    ziel = tmp_path / "andere-modelle"
    setzen(config, "models", str(ziel))

    assert ordner["chat"] == ziel.resolve()
    assert ordner["chat"] != vorher
    assert ordner.get("einbettung") == Path(config.pfad(config.app.einbettungsmodelle_verzeichnis))
    assert ordner.get("gibtsnicht") is None


# --- Through the service: every server, no restart ----------------------------


@pytest.mark.parametrize(
    ("ort", "route", "start"),
    [
        ("models", "/api/v1/runner", "modellrunner"),
        ("models", "/api/v1/agentenmodell", "agentenrunner"),
        ("embedding_models", "/api/v1/einbettungsserver", "einbettungsrunner"),
        ("speech_models", None, "sprachrunner"),
    ],
)
def test_a_moved_location_reaches_every_server_without_a_restart(
    client, tmp_path, ort, route, start
):
    ziel = tmp_path / f"neu-{ort}"
    _model(ziel, "eins.gguf")
    antwort = client.put(f"{SPEICHERORTE}/{ort}", json={"pfad": str(ziel)})
    assert antwort.status_code == 200

    runner = getattr(client.app.state, start)
    assert runner.ordner == ziel.resolve()
    assert "eins.gguf" in [m.name for m in runner.modelle()]
    if route:
        zeile = client.get(route).json()
        assert zeile["ordner"] == str(ziel.resolve())


def test_the_putzrunner_follows_the_speech_location_too(client, tmp_path):
    ziel = tmp_path / "neue-sprache"
    ziel.mkdir()
    client.put(f"{SPEICHERORTE}/speech_models", json={"pfad": str(ziel)})
    assert client.app.state.sprachputzrunner.ordner == ziel.resolve()


def test_the_download_lands_in_the_moved_folder(client, tmp_path):
    ziel = tmp_path / "neue-modelle"
    client.put(f"{SPEICHERORTE}/models", json={"pfad": str(ziel)})
    assert Path(client.app.state.modellordner_je_art["chat"]) == ziel.resolve()


def test_the_location_list_no_longer_says_a_restart_is_needed(client, tmp_path):
    for zeile in client.get(SPEICHERORTE).json():
        assert "neustart_noetig" not in zeile
    antwort = client.put(
        f"{SPEICHERORTE}/models", json={"pfad": str(tmp_path / "irgendwo")}
    ).json()
    assert "neustart_noetig" not in antwort


def test_silence_a_reset_returns_every_server_to_the_default(client, tmp_path):
    standard = client.app.state.modellrunner.ordner
    ziel = tmp_path / "weg"
    client.put(f"{SPEICHERORTE}/models", json={"pfad": str(ziel)})
    assert client.app.state.agentenrunner.ordner == ziel.resolve()
    client.delete(f"{SPEICHERORTE}/models")
    assert client.app.state.modellrunner.ordner == standard
    assert client.app.state.agentenrunner.ordner == standard


def test_the_restart_hint_text_is_gone_from_both_catalogues():
    for sprache in ("de", "en"):
        text = (
            Path(__file__).resolve().parent.parent / "app" / "locales" / f"{sprache}.json"
        ).read_text(encoding="utf-8")
        assert '"neustart"' not in json.loads(text)["speicherorte"]


def test_the_row_component_no_longer_shows_a_restart_hint():
    quelle = (
        Path(__file__).resolve().parent.parent
        / "frontend" / "src" / "teile" / "Speicherortzeile.svelte"
    ).read_text(encoding="utf-8")
    assert "speicherorte.neustart" not in quelle
    assert "neustart_noetig" not in quelle

