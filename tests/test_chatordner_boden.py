"""Every chat has a floor for its file tools, and the folder check runs
the moment a file tool call begins.

A chat that shares no folder used to have none: every file tool refused,
and a model could stream a whole write_file argument for minutes before
being told so. The chat's own folder (app/dokumentablage.py) is now always
in the list and made at the first call that needs it; the folder check
(app/tools/grenzen.py ``ordner_pruefen``) runs as soon as the call's name
arrives in the stream (app/api/v1/generierung.py).
"""

from __future__ import annotations

import json
import os
import shutil

import pytest

from app import dokumentablage
from app.providers import MockProvider, mock_endpunkt
from app.providers.base import Stueck, Werkzeugaufruf
from app.tools import WerkzeugRegistry
from tests.conftest import provider_setzen, cwd_command


def _ereignisse(antwort):
    return [
        json.loads(z[5:].strip()) for z in antwort.text.splitlines() if z.startswith("data:")
    ]


def _dateiwerkzeuge_an(client):
    """File tools and the shell on, and the test endpoint able to call them,
    so the request really offers them."""
    # With the data folder handed in the way the app builds its registry
    # (app/tools/aufbau.py): it tells the chat's own folder apart, which a
    # tool makes as it runs.
    from app.tools import create_folder

    client.app.state.werkzeuge = WerkzeugRegistry(
        [],
        shell_an=True,
        folder_share=create_folder.ChatFolderShare(
            client.app.state.repositories, client.app.state.config.datenverzeichnis
        ),
    )
    client.app.state.config.features.mcp = True
    client.app.state.discovery.zustaende["test"].endpunkt.capabilities.tool_calls = True


def _werkzeugantwort(provider, aufruf_name):
    """The result the model received for the call of that name, in the
    round after the call."""
    nachrichten = provider.letzte_anfrage.nachrichten
    ids = {
        aufruf.id
        for n in nachrichten
        for aufruf in (n.werkzeugaufrufe or [])
        if aufruf.name == aufruf_name
    }
    for nachricht in nachrichten:
        if nachricht.role == "tool" and nachricht.werkzeugaufruf_id in ids:
            return nachricht.content
    raise AssertionError(f"no tool result for {aufruf_name}")


class LangsamSchreibend(MockProvider):
    """A model that begins a write_file call and then writes its argument
    in many pieces — the way a long file arrives. Counts how many pieces
    the run actually took from it."""

    STUECKE = 40

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.gelesen = 0

    async def streamen(self, anfrage):
        self.letzte_anfrage = anfrage
        self.alle_anfragen.append(anfrage)
        self.durchlaeufe += 1
        if self.durchlaeufe > 1:
            yield Stueck("content", "gut")
            return
        for zeichen in range(self.STUECKE):
            self.gelesen += 1
            yield Stueck(
                "tool_call_laeuft",
                daten={"index": 0, "name": "write_file", "zeichen": zeichen * 100},
            )
        self.gelesen += 1
        yield Stueck(
            "tool_call",
            werkzeugaufrufe=[
                Werkzeugaufruf(
                    id="w1", name="write_file",
                    argumente={"path": "lang.txt", "content": "x" * 4000},
                )
            ],
        )


def test_ein_chat_ohne_freigabe_schreibt_in_seinen_eigenen_ordner(client, chat_id):
    """Nothing shared, nothing uploaded: write_file still works, in the
    chat's own folder, which is made for this very call. It used to end in
    'No working folder is shared with this chat.'"""
    _dateiwerkzeuge_an(client)
    eigen = dokumentablage.chatordner(client.app.state.config.datenverzeichnis, chat_id)
    assert not eigen.exists()
    provider = provider_setzen(
        client,
        MockProvider(
            mock_endpunkt("test"),
            haeppchen=["fertig"],
            werkzeugaufrufe=[
                Werkzeugaufruf(
                    id="w1", name="write_file",
                    argumente={"path": "notiz.txt", "content": "hallo"},
                )
            ],
        ),
    )
    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "schreib"},
    )
    assert (eigen / "notiz.txt").read_text() == "hallo"
    assert "No working folder" not in _werkzeugantwort(provider, "write_file")


def test_ein_chat_ohne_werkzeugaufruf_bekommt_keinen_ordner(client, chat_id):
    """The silence check: a plain answer leaves nothing on the disk."""
    _dateiwerkzeuge_an(client)
    eigen = dokumentablage.chatordner(client.app.state.config.datenverzeichnis, chat_id)
    provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["nur Text"]))
    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "hallo"},
    )
    assert not eigen.exists()


def test_die_ordnerpruefung_sagt_ab_bevor_das_argument_gelesen_ist(client, chat_id, tmp_path):
    """The shared folder vanished: the refusal stands after the call's first
    piece, not after all forty — the stream is cut there, and the model
    gets the reason as the call's result."""
    _dateiwerkzeuge_an(client)
    geteilt = tmp_path / "geteilt"
    geteilt.mkdir()
    antwort = client.patch(f"/api/v1/chats/{chat_id}", json={"working_dirs": [str(geteilt)]})
    assert antwort.status_code == 200
    # Sharing may leave the folder's notes file in it; the whole folder goes.
    shutil.rmtree(geteilt)
    provider = provider_setzen(client, LangsamSchreibend(mock_endpunkt("test")))
    ereignisse = _ereignisse(
        client.post(
            "/api/v1/chat/completions",
            json={"chat_id": chat_id, "endpoint_id": "test", "content": "schreib lang"},
        )
    )
    assert provider.gelesen == 1
    ergebnis = next(e for e in ereignisse if e["typ"] == "tool_result")
    assert ergebnis["fehlgeschlagen"] is True
    assert "no longer exists" in _werkzeugantwort(provider, "write_file")
    assert provider.durchlaeufe == 2


def test_mit_gueltigem_ordner_wird_nicht_frueher_abgesagt(client, chat_id, tmp_path):
    """The silence check: a folder that is there lets the whole argument
    arrive and the file be written."""
    _dateiwerkzeuge_an(client)
    geteilt = tmp_path / "geteilt"
    geteilt.mkdir()
    client.patch(f"/api/v1/chats/{chat_id}", json={"working_dirs": [str(geteilt)]})
    provider = provider_setzen(client, LangsamSchreibend(mock_endpunkt("test")))
    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "schreib lang"},
    )
    assert provider.gelesen == LangsamSchreibend.STUECKE + 1
    assert (geteilt / "lang.txt").read_text() == "x" * 4000


def test_ein_befehl_im_chat_ohne_freigabe_laeuft_im_eigenen_ordner(client, chat_id):
    """The shell works in the first of the chat's folders — with nothing
    shared that is the chat's own, which is made for the call. Without it
    the command met 'The shared folder ... no longer exists.'"""
    _dateiwerkzeuge_an(client)
    eigen = dokumentablage.chatordner(client.app.state.config.datenverzeichnis, chat_id)
    provider = provider_setzen(
        client,
        MockProvider(
            mock_endpunkt("test"),
            haeppchen=["fertig"],
            werkzeugaufrufe=[
                Werkzeugaufruf(id="s1", name="run_command", argumente={"command": cwd_command()})
            ],
        ),
    )
    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "wo bin ich"},
    )
    assert eigen.is_dir()
    assert str(eigen.resolve()) in _werkzeugantwort(provider, "run_command")


class VerschwindenderOrdner(LangsamSchreibend):
    """The same slow writer — and the job's shared folder vanishes just as
    the run begins, the way a folder is moved away under a running job."""

    def __init__(self, *args, weg, **kwargs):
        super().__init__(*args, **kwargs)
        self.weg = weg

    async def streamen(self, anfrage):
        if self.durchlaeufe == 0:
            shutil.rmtree(self.weg, ignore_errors=True)
        async for stueck in super().streamen(anfrage):
            yield stueck


def test_im_auftrag_sagt_die_ordnerpruefung_ebenso_frueh_ab(config, tmp_path):
    """The job run makes the same check as the chat, from the same module:
    cut after the call's first piece, answered with the reason."""
    import time
    from pathlib import Path

    from fastapi.testclient import TestClient

    from app.main import app_erstellen

    config.features.mcp = True
    config.mcp.servers_file = str(Path(config.app.data_dir) / "keine_server.json")
    agenten = Path(config.app.agenten_verzeichnis)
    agenten.mkdir(parents=True, exist_ok=True)
    (agenten / "schreiber.md").write_text(
        "---\ntools: [write_file]\n---\n\nSchreibt.\n", encoding="utf-8"
    )
    geteilt = tmp_path / "auftragsordner"
    geteilt.mkdir()

    with TestClient(app_erstellen(config)) as client:
        client.headers["X-Sitzungsschluessel"] = client.app.state.sitzungsschluessel
        client.app.state.discovery.zustaende["test"].endpunkt.capabilities.tool_calls = True
        provider = provider_setzen(
            client, VerschwindenderOrdner(mock_endpunkt("test"), weg=geteilt)
        )
        kennung = client.post(
            "/api/v1/jobs",
            json={"agent": "schreiber", "task": "schreib", "folders": [str(geteilt)]},
        ).json()["id"]
        frist = time.time() + 8
        stand = None
        while time.time() < frist:
            stand = client.get(f"/api/v1/jobs/{kennung}").json().get("state")
            if stand in {"fertig", "abgebrochen", "gescheitert", "unterbrochen"}:
                break
            time.sleep(0.05)

    assert stand in {"fertig", "abgebrochen", "gescheitert", "unterbrochen"}, stand
    assert provider.gelesen == 1
    assert "no longer exists" in _werkzeugantwort(provider, "write_file")


def test_ein_chat_mit_freigabe_bekommt_keinen_eigenen_ordner(client, chat_id, tmp_path):
    """With a folder of the user's shared, calls work there — the chat's own
    folder is not made for them and no empty folder is left behind."""
    _dateiwerkzeuge_an(client)
    geteilt = tmp_path / "geteilt"
    geteilt.mkdir()
    client.patch(f"/api/v1/chats/{chat_id}", json={"working_dirs": [str(geteilt)]})
    eigen = dokumentablage.chatordner(client.app.state.config.datenverzeichnis, chat_id)
    provider_setzen(client, LangsamSchreibend(mock_endpunkt("test")))
    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "schreib"},
    )
    assert (geteilt / "lang.txt").exists()
    assert not eigen.exists()


class ZweiAufrufe(LangsamSchreibend):
    """A round that begins another call first and a write_file second."""

    async def streamen(self, anfrage):
        self.letzte_anfrage = anfrage
        self.alle_anfragen.append(anfrage)
        self.durchlaeufe += 1
        if self.durchlaeufe > 1:
            yield Stueck("content", "gut")
            return
        self.gelesen += 1
        yield Stueck(
            "tool_call_laeuft", daten={"index": 0, "name": "memory_save", "zeichen": 0}
        )
        for zeichen in range(self.STUECKE):
            self.gelesen += 1
            yield Stueck(
                "tool_call_laeuft",
                daten={"index": 1, "name": "write_file", "zeichen": zeichen * 100},
            )
        yield Stueck(
            "tool_call",
            werkzeugaufrufe=[
                Werkzeugaufruf(id="f0", name="memory_save", argumente={"content": "x"}),
                Werkzeugaufruf(
                    id="w1", name="write_file", argumente={"path": "a.txt", "content": "y"}
                ),
            ],
        )


def test_ein_vorher_begonnener_aufruf_wird_nicht_verschluckt(client, chat_id, tmp_path):
    """The cut would lose a call that began before the refused one — so then
    the stream runs to its end and both calls are answered, the file call
    with the same refusal at execution."""
    _dateiwerkzeuge_an(client)
    geteilt = tmp_path / "geteilt"
    geteilt.mkdir()
    client.patch(f"/api/v1/chats/{chat_id}", json={"working_dirs": [str(geteilt)]})
    shutil.rmtree(geteilt)
    provider = provider_setzen(client, ZweiAufrufe(mock_endpunkt("test")))
    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "zwei"},
    )
    assert provider.gelesen == ZweiAufrufe.STUECKE + 1
    beantwortet = {
        n.werkzeugaufruf_id for n in provider.letzte_anfrage.nachrichten if n.role == "tool"
    }
    assert beantwortet == {"f0", "w1"}


def _gesperrter_chatordner(tmp_path):
    """A chat folder under a data folder nothing may be written into."""
    daten = tmp_path / "daten"
    daten.mkdir()
    daten.chmod(0o500)
    return daten / dokumentablage.CHATDATEIEN / "abc123"


# A data folder without write permission stops nobody running as root.
_ALS_ROOT = pytest.mark.skipif(
    getattr(os, "geteuid", lambda: -1)() == 0,
    reason="root ignores the missing write permission",
)


@_ALS_ROOT
@pytest.mark.platforms("posix", reason="a folder closed by its rights")
def test_ein_chatordner_der_nicht_angelegt_werden_kann_nennt_den_grund(tmp_path):
    """The chat's own folder was never set by the user, so the refusal names
    the folder and the reason the system gave, and asks for nothing."""
    from app.tools import grenzen

    ordner = _gesperrter_chatordner(tmp_path)
    try:
        grund = grenzen.prepare_folders([str(ordner)], tmp_path / "daten")
    finally:
        ordner.parent.parent.chmod(0o700)
    assert grund is not None
    assert grund.startswith(f"Cannot access directory {ordner.resolve()}: ")
    assert "Permission denied" in grund
    assert "select it again" not in grund


@_ALS_ROOT
@pytest.mark.platforms("posix", reason="a folder closed by its rights")
async def test_der_befehl_nennt_denselben_grund(tmp_path):
    from app.tools import shell

    ordner = _gesperrter_chatordner(tmp_path)
    try:
        with pytest.raises(shell.ShellVerboten) as fehler:
            await shell.ausfuehren(
                {"command": "ls"}, [str(ordner)], data_dir=tmp_path / "daten"
            )
    finally:
        ordner.parent.parent.chmod(0o700)
    assert str(fehler.value).startswith("Cannot access directory ")
    assert "select it again" not in str(fehler.value)


def test_a_missing_chat_folder_is_made_when_a_call_runs(tmp_path):
    from app.tools import grenzen

    data = tmp_path / "daten"
    folders = data / dokumentablage.CHATDATEIEN / "abc123"
    assert grenzen.prepare_folders([str(folders)], data) is None
    assert folders.is_dir()


def test_the_check_alone_makes_no_folder(tmp_path):
    """Checking and making are apart: the check at a call's beginning passes
    a chat's own folder that is not there yet, and leaves the disk alone —
    the call that runs makes it."""
    from app.tools import grenzen

    data = tmp_path / "daten"
    folders = data / dokumentablage.CHATDATEIEN / "abc123"
    assert grenzen.ordner_pruefen([str(folders)], data) is None
    assert not folders.exists()
    assert not data.exists()


def test_the_check_at_a_call_beginning_makes_no_folder(tmp_path):
    """The same through the check a run makes while the model still writes
    the call: it lets the call go on and creates nothing."""
    from app import werkzeugvorpruefung

    data = tmp_path / "daten"
    folders = data / dokumentablage.CHATDATEIEN / "abc123"
    check = werkzeugvorpruefung.Vorpruefung([str(folders)], ["write_file"], data)
    assert check.beginnt({"index": 0, "name": "write_file", "zeichen": 0}) is False
    assert not data.exists()


def test_a_folder_of_the_users_named_like_a_chat_folder_is_not_made(tmp_path):
    """Told apart by the real data folder, not by the name: a folder of the
    user's in a ``chat_files`` folder of its own went missing — it is theirs
    to set again, and nothing makes it behind their back."""
    from app.tools import grenzen

    data = tmp_path / "daten"
    foreign = tmp_path / "exporte" / dokumentablage.CHATDATEIEN / "abc123"
    expected = (
        f"The shared folder '{foreign.resolve()}' no longer exists. "
        "Ask the user to select it again."
    )
    assert grenzen.ordner_pruefen([str(foreign)], data) == expected
    assert grenzen.prepare_folders([str(foreign)], data) == expected
    assert not foreign.exists()


def test_without_a_data_folder_no_chat_folder_is_told_apart(tmp_path):
    """Schweigeprobe: a caller with no data folder knows no chat folder, and
    a missing folder gets the user's sentence, as it always did."""
    from app.tools import grenzen

    folders = tmp_path / "daten" / dokumentablage.CHATDATEIEN / "abc123"
    assert "no longer exists" in (grenzen.prepare_folders([str(folders)]) or "")
    assert not folders.exists()


def test_ein_geloeschter_freigegebener_ordner_bekommt_den_bisherigen_satz(tmp_path):
    """The silence probe: a folder of the user's that went missing is theirs
    to set again, and it is not made behind their back."""
    from app.tools import grenzen

    ordner = tmp_path / "projekt"
    grund = grenzen.ordner_pruefen([str(ordner)], tmp_path / "daten")
    assert grund == (
        f"The shared folder '{ordner.resolve()}' no longer exists. "
        "Ask the user to select it again."
    )
    assert not ordner.exists()
