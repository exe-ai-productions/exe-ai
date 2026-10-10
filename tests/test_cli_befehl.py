"""The CLI module's one shell command.

It runs through the same runner the model uses — that is the whole point, and
the tests here are about the places where a second way in would have opened:
the shared folders, the block list, and the chat it belongs to.

The one deliberate difference: outside the shared folders the CLI refuses
instead of asking. A confirmation needs a running answer to hold the call
open, and the CLI has none.
"""

from __future__ import annotations

import json

from tests.conftest import python_command

# The two commands every test here runs, the same on every system.
LISTING = python_command("import os; print(*os.listdir(), sep=chr(10))")
WHERE = python_command("import os; print(os.getcwd())")


def _chat_mit_ordner(client, chat_id, ordner):
    client.patch(f"/api/v1/chats/{chat_id}", json={"working_dirs": [str(ordner)]})


def test_ein_befehl_laeuft_im_freigegebenen_ordner(client, chat_id, tmp_path):
    (tmp_path / "notiz.txt").write_text("hallo", encoding="utf-8")
    _chat_mit_ordner(client, chat_id, tmp_path)

    antwort = client.post(f"/api/v1/laeufe/{chat_id}/befehl", json={"command": LISTING})
    assert antwort.status_code == 200
    daten = antwort.json()
    assert daten["fehlgeschlagen"] is False
    assert "notiz.txt" in daten["text"]


def test_der_lauf_taucht_im_terminal_auf(client, chat_id, tmp_path):
    """Same runs list the terminal module reads — one channel, not two."""
    _chat_mit_ordner(client, chat_id, tmp_path)
    client.post(f"/api/v1/laeufe/{chat_id}/befehl", json={"command": "echo hallo"})

    laeufe = client.get(f"/api/v1/laeufe/{chat_id}").json()["laeufe"]
    assert [l["befehl"] for l in laeufe] == ["echo hallo"]
    assert laeufe[0]["ausgabe"] == "hallo"


def test_ausserhalb_wird_abgelehnt_statt_gefragt(client, chat_id, tmp_path):
    _chat_mit_ordner(client, chat_id, tmp_path)
    outside = str(tmp_path.parent)  # beside the share, on this system
    antwort = client.post(
        f"/api/v1/laeufe/{chat_id}/befehl", json={"command": f'ls "{outside}"'}
    )
    daten = antwort.json()
    assert daten["fehlgeschlagen"] is True
    assert outside in daten["text"]


def test_die_sperrliste_gilt_auch_hier(client, chat_id, tmp_path):
    _chat_mit_ordner(client, chat_id, tmp_path)
    antwort = client.post(
        f"/api/v1/laeufe/{chat_id}/befehl", json={"command": "sudo rm etwas"}
    )
    assert antwort.json()["fehlgeschlagen"] is True


def test_konfigurierte_sperrliste_gilt_auch_hier(client, chat_id, tmp_path):
    """The operator-configurable niemals list (berechtigungen.json), not
    just the hardcoded one, must also apply to CLI commands — Tor 3 runs
    the same way here as it does for a model's tool call."""
    (tmp_path / "berechtigungen.json").write_text(
        json.dumps({"niemals": ["curl evil.example"]}), encoding="utf-8"
    )
    _chat_mit_ordner(client, chat_id, tmp_path)
    antwort = client.post(
        f"/api/v1/laeufe/{chat_id}/befehl", json={"command": "curl evil.example"}
    )
    daten = antwort.json()
    assert daten["fehlgeschlagen"] is True
    assert "never allowed" in daten["text"]


def test_cli_liest_den_konfigurierten_pfad_nicht_den_standard(client, chat_id, tmp_path, config):
    """A relocated berechtigungen_datei must be what the CLI reads too — not
    only what WerkzeugRegistry reads for the model's own tool calls."""
    wohin = tmp_path / "anderswo" / "berechtigungen.json"
    wohin.parent.mkdir()
    wohin.write_text(json.dumps({"niemals": ["curl evil.example"]}), encoding="utf-8")
    config.app.berechtigungen_datei = str(wohin)

    _chat_mit_ordner(client, chat_id, tmp_path)
    antwort = client.post(
        f"/api/v1/laeufe/{chat_id}/befehl", json={"command": "curl evil.example"}
    )
    daten = antwort.json()
    assert daten["fehlgeschlagen"] is True
    assert "never allowed" in daten["text"]


def test_cli_generische_rueckfrage_ohne_pfad_meldet_das_klar(client, chat_id, tmp_path):
    """A 'fragen' verdict can come from a plain per-tool rule, not only from
    a path outside the shared folders — the message must not claim one."""
    (tmp_path / "berechtigungen.json").write_text(
        json.dumps({"regeln": {"run_command": "fragen"}}), encoding="utf-8"
    )
    _chat_mit_ordner(client, chat_id, tmp_path)

    antwort = client.post(f"/api/v1/laeufe/{chat_id}/befehl", json={"command": "ls"})
    daten = antwort.json()
    assert daten["fehlgeschlagen"] is True
    assert "außerhalb" not in daten["text"]
    assert "Rückfrage" in daten["text"]


def test_ohne_freigegebenen_ordner_laeuft_er_im_eigenen_ordner_des_chats(client, chat_id):
    """A chat that shares nothing still has its own folder as a floor: the
    command runs there, and the folder is made for it on the way."""
    from app import dokumentablage

    config = client.app.state.config
    eigen = dokumentablage.chatordner(config.datenverzeichnis, chat_id)
    assert not eigen.exists()
    antwort = client.post(f"/api/v1/laeufe/{chat_id}/befehl", json={"command": WHERE})
    daten = antwort.json()
    assert daten["fehlgeschlagen"] is False
    assert eigen.is_dir()
    assert str(eigen.resolve()) in daten["text"]


def test_ein_fremder_chat_hat_keine_befehle(client, tmp_path):
    antwort = client.post("/api/v1/laeufe/gibtsnicht/befehl", json={"command": "ls"})
    assert antwort.status_code == 404


def test_a_command_in_a_chat_without_a_share_runs_in_its_own_folder(client, chat_id):
    """Nothing shared: the command runs in the chat's own folder, made as the
    command runs — the folder is told apart by the data folder, not by its
    name (app/tools/grenzen.py `prepare_folders`)."""
    from app import dokumentablage

    own = dokumentablage.chatordner(client.app.state.config.datenverzeichnis, chat_id)
    assert not own.exists()

    data = client.post(f"/api/v1/laeufe/{chat_id}/befehl", json={"command": WHERE}).json()

    assert data["fehlgeschlagen"] is False, data
    assert own.is_dir()
    assert str(own.resolve()) in data["text"]
