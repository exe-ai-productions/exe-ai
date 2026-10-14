"""The speech server: its own everything, and the one door audio goes through."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from tests.conftest import sized_file
from app import sprachserver, stimme
from app.modellrunner import Lauf


# --- Nothing shared with the five other runners -----------------------------


def test_alle_runner_des_hauses_teilen_nichts(client: TestClient):
    """Six servers, six note files, six key variables, six ports.

    The rule the embedding server was written after it collided with the chat
    server on all three at once: a second server is only a second server if
    nothing about it is shared. Checked PAIRWISE and over the whole house,
    because a collision is never a property of one runner — it is a property
    of a pair, and the pair that collides is always the one nobody compared.
    """
    from app import agentenserver, einbettungsserver, modellrunner

    zettel = [
        modellrunner.PID_DATEI,
        einbettungsserver.PID_DATEI,
        agentenserver.PID_DATEI,
        sprachserver.PID_DATEI,
        sprachserver.PUTZ_PID_DATEI,
    ]
    schluessel = [
        modellrunner.SCHLUESSEL_VARIABLE,
        einbettungsserver.SCHLUESSEL_VARIABLE,
        agentenserver.SCHLUESSEL_VARIABLE,
        sprachserver.SCHLUESSEL_VARIABLE,
        sprachserver.PUTZ_SCHLUESSEL_VARIABLE,
    ]
    assert len(set(zettel)) == len(zettel), zettel
    assert len(set(schluessel)) == len(schluessel), schluessel

    config = client.app.state.config
    ports = [
        config.app.einbettung_port,
        agentenserver.PORT_VORGABE,
        config.app.sprache_port,
        config.app.sprachputz_port,
    ]
    assert len(set(ports)) == len(ports), ports


def test_die_beiden_runner_tragen_ihr_eigenes(tmp_path: Path):
    """The two built here are two, down to the last field."""
    sprache = sprachserver.runner_bauen(tmp_path, "llama-server", 8084)
    putz = sprachserver.putzrunner_bauen(tmp_path, "llama-server", 8085)
    assert sprache.port_vorgabe != putz.port_vorgabe
    assert sprache._pid_datei != putz._pid_datei  # noqa: SLF001 - the point of the test
    assert sprache._schluessel_variable != putz._schluessel_variable  # noqa: SLF001


def test_das_fenster_steht_nur_einmal_in_der_zeile(tmp_path: Path):
    """The runner writes ``--ctx-size`` itself; a second one from the flag
    list makes a command line carrying it twice — it worked by accident,
    because the engine takes the last one."""
    assert "--ctx-size" not in sprachserver.FLAGS
    runner = sprachserver.runner_bauen(tmp_path, "llama-server", 8084)
    zeile = " ".join(runner.befehl("m.gguf", 4096, 99, 8084))
    assert zeile.count("--ctx-size") == 1
    assert "--ctx-size 4096" in zeile


def test_der_sprachserver_bekommt_seine_vorlage(tmp_path: Path):
    """A speech model samples, so it needs its chat template. Measured: one
    of the two known families answers a plain sentence with backticks when
    started without one."""
    runner = sprachserver.runner_bauen(tmp_path, "llama-server", 8084)
    assert "--jinja" in runner.befehl("m.gguf", 4096, 99, 8084)


# --- Asking for a transcription ---------------------------------------------


class _Antwort:
    def __init__(self, daten, status=200):
        self._daten = daten
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("nope", request=None, response=None)

    def json(self):
        return self._daten


def test_der_hauptweg_schickt_die_wav_als_formular(monkeypatch):
    """The OpenAI form: the file, the chosen language and the instruction in
    fields made for them, signed with this server's own key."""
    gesehen: dict = {}

    def falsch(url, **kw):
        gesehen["url"] = url
        gesehen.update(kw)
        return _Antwort({"text": "hallo welt"})

    monkeypatch.setattr(sprachserver.httpx, "post", falsch)
    text = sprachserver.transkribieren(
        8084, "geheim", b"RIFF....", sprache="de", anweisung="write it down"
    )
    assert text == "hallo welt"
    assert gesehen["url"] == "http://127.0.0.1:8084/v1/audio/transcriptions"
    assert gesehen["files"]["file"][1] == b"RIFF...."
    assert gesehen["data"]["language"] == "de"
    assert gesehen["data"]["prompt"] == "write it down"
    assert gesehen["headers"]["Authorization"] == "Bearer geheim"


def test_bei_automatisch_reist_kein_sprachfeld_mit(monkeypatch):
    """An empty ``language`` is a language whose name is nothing — not the
    same as no field at all."""
    gesehen: dict = {}

    def falsch(url, **kw):
        gesehen.update(kw)
        return _Antwort({"text": "x"})

    monkeypatch.setattr(sprachserver.httpx, "post", falsch)
    sprachserver.transkribieren(8084, None, b"RIFF", sprache=None, anweisung="a")
    assert "language" not in gesehen["data"]


def test_der_rueckfallweg_baut_den_tonteil(monkeypatch):
    """The chat form, built by hand: an ``input_audio`` part beside the
    instruction, no stream, no temperature — and the text read out of
    ``choices[0].message.content``."""
    gesehen: dict = {}

    def falsch(url, **kw):
        gesehen["url"] = url
        gesehen.update(kw)
        return _Antwort({"choices": [{"message": {"content": "aufgeschrieben"}}]})

    monkeypatch.setattr(sprachserver.httpx, "post", falsch)
    monkeypatch.setattr(sprachserver, "WEG", "chat")
    text = sprachserver.transkribieren(
        8084, "geheim", b"RIFF....", sprache="German", anweisung="write it down"
    )
    assert text == "aufgeschrieben"
    assert gesehen["url"] == "http://127.0.0.1:8084/v1/chat/completions"
    teile = gesehen["json"]["messages"][0]["content"]
    assert teile[1]["type"] == "input_audio"
    assert teile[1]["input_audio"]["format"] == "wav"
    assert "German" in teile[0]["text"] and "write it down" in teile[0]["text"]
    assert gesehen["json"]["stream"] is False
    assert gesehen["json"]["temperature"] == 0
    assert gesehen["headers"]["Authorization"] == "Bearer geheim"


@pytest.mark.parametrize(
    "unfall",
    [
        httpx.ConnectError("nobody there"),
        httpx.ReadTimeout("too slow"),
        ValueError("not what we expected"),
    ],
)
def test_jeder_ausfall_wird_zu_nichts(monkeypatch, unfall):
    """None is the whole vocabulary of failure here — the route turns it into
    one sentence, and a traceback would say the same thing in a language
    nobody reads."""

    def falsch(*a, **kw):
        raise unfall

    monkeypatch.setattr(sprachserver.httpx, "post", falsch)
    assert sprachserver.transkribieren(8084, None, b"RIFF") is None


def test_eine_fremde_form_wird_zu_nichts(monkeypatch):
    monkeypatch.setattr(
        sprachserver.httpx, "post", lambda *a, **kw: _Antwort({"etwas": "anderes"})
    )
    assert sprachserver.transkribieren(8084, None, b"RIFF") is None


def test_die_eigene_marke_des_modells_faellt_weg(monkeypatch):
    """One speech family opens every answer with its own protocol token. That
    is not speech, and it is the ONE thing cut out of an answer."""
    monkeypatch.setattr(
        sprachserver.httpx,
        "post",
        lambda *a, **kw: _Antwort({"text": "language German<asr_text>Guten Tag"}),
    )
    assert sprachserver.transkribieren(8084, None, b"RIFF") == "Guten Tag"


def test_was_ein_modell_erfindet_bleibt_stehen(monkeypatch):
    """Silence makes models invent whole sentences. None of that is removed:
    it lands in the field, where the person reading it decides — which is the
    reason a dictation is never sent off by itself."""
    monkeypatch.setattr(
        sprachserver.httpx,
        "post",
        lambda *a, **kw: _Antwort({"text": "Vielen Dank fürs Zuschauen."}),
    )
    assert sprachserver.transkribieren(8084, None, b"RIFF") == "Vielen Dank fürs Zuschauen."


# --- Tidying up --------------------------------------------------------------


def test_die_bereinigung_fragt_den_gewaehlten_server(monkeypatch):
    gesehen: dict = {}

    def falsch(url, **kw):
        gesehen["url"] = url
        gesehen.update(kw)
        return _Antwort({"choices": [{"message": {"content": "Öffne die Datei."}}]})

    monkeypatch.setattr(sprachserver.httpx, "post", falsch)
    fertig = sprachserver.bereinigen(
        "http://127.0.0.1:8085/v1", "putzschluessel", "tidy this", "ähm öffne die datei"
    )
    assert fertig == "Öffne die Datei."
    assert gesehen["url"] == "http://127.0.0.1:8085/v1/chat/completions"
    assert gesehen["json"]["messages"][0]["content"] == "tidy this"
    assert gesehen["headers"]["Authorization"] == "Bearer putzschluessel"


def test_eine_stumme_bereinigung_wird_zu_nichts(monkeypatch):
    def falsch(*a, **kw):
        raise httpx.ConnectError("nobody there")

    monkeypatch.setattr(sprachserver.httpx, "post", falsch)
    assert sprachserver.bereinigen("http://127.0.0.1:8085/v1", None, "x", "y") is None


# --- The route ---------------------------------------------------------------


def _laufen_lassen(client: TestClient, monkeypatch, port=8084, schluessel="s"):
    runner = client.app.state.sprachrunner
    monkeypatch.setattr(runner, "laeuft", lambda: True)
    monkeypatch.setattr(
        type(runner), "schluessel", property(lambda self: schluessel), raising=False
    )
    monkeypatch.setattr(
        runner,
        "lauf",
        lambda: Lauf(modell="asr.gguf", kontext=4096, schichten=99, port=port),
    )
    return runner


def test_ohne_server_gibt_es_einen_satz_und_keinen_ton(client: TestClient):
    antwort = client.post(
        "/api/v1/sprachserver/transkribieren",
        content=b"RIFF",
        headers={"Content-Type": "audio/wav"},
    )
    assert antwort.status_code == 409
    assert antwort.json()["detail"]


def test_eine_zu_lange_aufnahme_wird_abgewiesen(client: TestClient, monkeypatch):
    _laufen_lassen(client, monkeypatch)
    antwort = client.post(
        "/api/v1/sprachserver/transkribieren",
        content=b"x" * (8 * 1024 * 1024 + 1),
        headers={"Content-Type": "audio/wav"},
    )
    assert antwort.status_code == 413


def test_der_ton_wird_zu_text(client: TestClient, monkeypatch):
    _laufen_lassen(client, monkeypatch, port=8099, schluessel="frisch")
    gesehen: dict = {}

    def falsch(port, schluessel, wav, **kw):
        gesehen.update({"port": port, "schluessel": schluessel, "wav": wav, **kw})
        return "Öffne die Datei."

    monkeypatch.setattr(sprachserver, "transkribieren", falsch)
    antwort = client.post(
        "/api/v1/sprachserver/transkribieren",
        content=b"RIFF-Ton",
        headers={"Content-Type": "audio/wav"},
    )
    assert antwort.status_code == 200
    assert antwort.json()["text"] == "Öffne die Datei."
    # The running server's own port and its own key, not a default.
    assert gesehen["port"] == 8099
    assert gesehen["schluessel"] == "frisch"
    assert gesehen["wav"] == b"RIFF-Ton"


def test_stille_ist_eine_gueltige_antwort(client: TestClient, monkeypatch):
    """Nothing said, nothing written — and that is a 200, not a failure."""
    _laufen_lassen(client, monkeypatch)
    monkeypatch.setattr(sprachserver, "transkribieren", lambda *a, **kw: "")
    antwort = client.post(
        "/api/v1/sprachserver/transkribieren",
        content=b"RIFF",
        headers={"Content-Type": "audio/wav"},
    )
    assert antwort.status_code == 200
    assert antwort.json()["text"] == ""


def test_ein_stummer_server_wird_gemeldet(client: TestClient, monkeypatch):
    _laufen_lassen(client, monkeypatch)
    monkeypatch.setattr(sprachserver, "transkribieren", lambda *a, **kw: None)
    antwort = client.post(
        "/api/v1/sprachserver/transkribieren",
        content=b"RIFF",
        headers={"Content-Type": "audio/wav"},
    )
    assert antwort.status_code == 502
    assert antwort.json()["detail"]


def test_bei_laufendem_server_kommt_keine_aus_meldung(client: TestClient, monkeypatch):
    """The silence test. A warning that fires whatever happens is not a
    warning — so the case where it has to say NOTHING is checked too."""
    _laufen_lassen(client, monkeypatch)
    monkeypatch.setattr(sprachserver, "transkribieren", lambda *a, **kw: "etwas")
    antwort = client.post(
        "/api/v1/sprachserver/transkribieren",
        content=b"RIFF",
        headers={"Content-Type": "audio/wav"},
    )
    daten = antwort.json()
    assert antwort.status_code == 200
    assert "detail" not in daten
    # Nothing was asked to tidy, so nothing was skipped either — a window
    # told "skipped" here would complain about a state nobody set up.
    assert daten["bereinigung"] == "aus"
    assert daten["bereinigt"] is False


def test_eine_ausgeschaltete_bereinigung_schweigt(client: TestClient, monkeypatch):
    _laufen_lassen(client, monkeypatch)
    client.put("/api/v1/settings/global/diktat", json={"wert": {"bereinigung": "aus"}})
    monkeypatch.setattr(sprachserver, "transkribieren", lambda *a, **kw: "roher text")
    daten = client.post(
        "/api/v1/sprachserver/transkribieren",
        content=b"RIFF",
        headers={"Content-Type": "audio/wav"},
    ).json()
    assert daten == {
        "text": "roher text",
        "roh": "roher text",
        "bereinigt": False,
        "bereinigung": "aus",
    }


def test_eine_ausgefallene_bereinigung_sagt_es(client: TestClient, monkeypatch):
    """The raw text goes into the field either way — it is what was said —
    but it is never passed off as cleaned."""
    _laufen_lassen(client, monkeypatch)
    client.put(
        "/api/v1/settings/global/diktat",
        json={"wert": {"bereinigung": "modell"}},
    )
    monkeypatch.setattr(sprachserver, "transkribieren", lambda *a, **kw: "roher text")
    daten = client.post(
        "/api/v1/sprachserver/transkribieren",
        content=b"RIFF",
        headers={"Content-Type": "audio/wav"},
    ).json()
    assert daten["text"] == "roher text"
    assert daten["bereinigt"] is False
    assert daten["bereinigung"] == "modell"


def test_eine_gelungene_bereinigung_zeigt_beides(client: TestClient, monkeypatch):
    _laufen_lassen(client, monkeypatch)
    client.put(
        "/api/v1/settings/global/diktat",
        json={"wert": {"bereinigung": "putzmodell", "putzmodell": "klein.gguf"}},
    )
    putz = client.app.state.sprachputzrunner
    monkeypatch.setattr(putz, "laeuft", lambda: True)
    monkeypatch.setattr(
        putz,
        "lauf",
        lambda: Lauf(modell="klein.gguf", kontext=2048, schichten=99, port=8085),
    )
    monkeypatch.setattr(sprachserver, "transkribieren", lambda *a, **kw: "ähm der text")
    monkeypatch.setattr(sprachserver, "bereinigen", lambda *a, **kw: "Der Text.")
    daten = client.post(
        "/api/v1/sprachserver/transkribieren",
        content=b"RIFF",
        headers={"Content-Type": "audio/wav"},
    ).json()
    assert daten["text"] == "Der Text."
    assert daten["roh"] == "ähm der text"
    assert daten["bereinigt"] is True


def test_das_nachlesen_waehrend_des_sprechens_bereinigt_nicht(client: TestClient, monkeypatch):
    """The reading taken while somebody still speaks skips the tidy-up —
    even with a tidy-up model running — and says so; the same request
    without the flag is tidied as always (the silence check)."""
    _laufen_lassen(client, monkeypatch)
    client.put(
        "/api/v1/settings/global/diktat",
        json={"wert": {"bereinigung": "putzmodell", "putzmodell": "klein.gguf"}},
    )
    putz = client.app.state.sprachputzrunner
    monkeypatch.setattr(putz, "laeuft", lambda: True)
    monkeypatch.setattr(
        putz,
        "lauf",
        lambda: Lauf(modell="klein.gguf", kontext=2048, schichten=99, port=8085),
    )
    gerufen: list = []
    monkeypatch.setattr(sprachserver, "transkribieren", lambda *a, **kw: "ähm der text")

    def bereinigt(*a, **kw):
        gerufen.append(1)
        return "Der Text."

    monkeypatch.setattr(sprachserver, "bereinigen", bereinigt)
    zwischen = client.post(
        "/api/v1/sprachserver/transkribieren?bereinigen=false",
        content=b"RIFF",
        headers={"Content-Type": "audio/wav"},
    ).json()
    assert zwischen == {
        "text": "ähm der text", "roh": "ähm der text", "bereinigt": False, "bereinigung": "aus",
    }
    assert gerufen == []
    schluss = client.post(
        "/api/v1/sprachserver/transkribieren",
        content=b"RIFF",
        headers={"Content-Type": "audio/wav"},
    ).json()
    assert schluss["text"] == "Der Text."
    assert gerufen == [1]


def test_die_diktat_automatik_ist_ab_werk_aus_und_wird_gespeichert(client: TestClient):
    """Auto-send is off as installed, a stored "on" is read back, and a
    non-boolean is turned into one rather than stored as it came."""
    from app import diktatsprachewahl

    repos = client.app.state.repositories
    assert diktatsprachewahl.automatik(repos) is False
    assert diktatsprachewahl.vorgaben()["automatik"] is False
    client.patch("/api/v1/settings/global/diktat", json={"wert": {"automatik": True}})
    assert diktatsprachewahl.automatik(repos) is True
    client.patch("/api/v1/settings/global/diktat", json={"wert": {"automatik": 0}})
    assert diktatsprachewahl.automatik(repos) is False
    assert diktatsprachewahl.wahl_pruefen({"automatik": "ja"}) == {"automatik": True}


def test_the_microphone_key_is_stored_and_read_back(client: TestClient):
    """Cmd + Option as installed; a recorded key is stored, read back as a
    fresh read would after a restart, and handed to the window with the
    works answers; a key that cannot be one falls back to the works key."""
    from app import diktatsprachewahl

    repos = client.app.state.repositories
    assert diktatsprachewahl.wahl(repos)["microphone_key"] == "Meta+Alt"
    assert diktatsprachewahl.vorgaben()["microphone_key"] == "Meta+Alt"
    client.patch("/api/v1/settings/global/diktat", json={"wert": {"microphone_key": "Meta+Shift+KeyD"}})
    assert diktatsprachewahl.wahl(repos)["microphone_key"] == "Meta+Shift+KeyD"
    gespeichert = client.get("/api/v1/settings/resolved/diktat").json()
    assert gespeichert["wert"]["microphone_key"] == "Meta+Shift+KeyD"
    for kaputt in ("KeyD", "Shift", "Meta+KeyD+KeyE", "Shift+Meta", "Shift+KeyD", "Meta+MetaLeft", 7):
        assert diktatsprachewahl.wahl_pruefen({"microphone_key": kaputt}) == {"microphone_key": "Meta+Alt"}


def test_ein_putzmodell_ohne_datei_gilt_als_aus(client: TestClient, monkeypatch):
    """Chosen but with no file behind it is nothing configured, so nothing
    was skipped — the window must stay quiet about it."""
    _laufen_lassen(client, monkeypatch)
    client.put(
        "/api/v1/settings/global/diktat",
        json={"wert": {"bereinigung": "putzmodell", "putzmodell": ""}},
    )
    monkeypatch.setattr(sprachserver, "transkribieren", lambda *a, **kw: "roher text")
    daten = client.post(
        "/api/v1/sprachserver/transkribieren",
        content=b"RIFF",
        headers={"Content-Type": "audio/wav"},
    ).json()
    assert daten["bereinigung"] == "aus"


# --- What the panel is told --------------------------------------------------


def test_die_auskunft_trennt_modelle_von_projektoren(client: TestClient):
    """A projector cannot start. Offered as a model it would sit in the
    picker as an entry that never answers."""
    ordner = Path(client.app.state.sprachrunner.ordner)
    (ordner / "vision").mkdir(parents=True, exist_ok=True)

    def grosse_datei(pfad: Path, gb: float) -> None:
        # Sparse on purpose: the size is what the list reports, and writing
        # two real gigabytes to prove it would be a slow test saying the
        # same thing. Bytes on the 10^9 scale, the same one the size reads
        # on (app/modellrunner.py `Modelldatei`).
        sized_file(pfad, int(gb * 1e9))

    grosse_datei(ordner / "asr-gross-Q8_0.gguf", 2)
    grosse_datei(ordner / "klein.gguf", 0.5)
    (ordner / "vision" / "asr-gross-Q8_0-mmproj-Q8_0.gguf").write_bytes(b"x")

    daten = client.get("/api/v1/sprachserver").json()
    assert {m["name"] for m in daten["modelle"]} == {"asr-gross-Q8_0.gguf", "klein.gguf"}
    # Each with its own size, the way the model server's own list carries it
    # — the window shows "name · X GB" in the picker.
    groessen = {m["name"]: m["groesse_gb"] for m in daten["modelle"]}
    assert groessen["asr-gross-Q8_0.gguf"] == pytest.approx(2.0, abs=0.1)
    assert groessen["klein.gguf"] == pytest.approx(0.5, abs=0.1)
    assert daten["mmproj"] == ["asr-gross-Q8_0-mmproj-Q8_0.gguf"]
    # And which projector belongs to which model, so the panel can say in
    # words when one has none instead of letting the start fail.
    assert daten["projektoren"]["asr-gross-Q8_0.gguf"] == "asr-gross-Q8_0-mmproj-Q8_0.gguf"
    assert daten["projektoren"]["klein.gguf"] is None


def test_die_auskunft_traegt_den_belegten_speicher(client: TestClient, monkeypatch):
    """The machine head's sum needs this server's share while it runs — the
    runner already measures it for itself."""
    runner = _laufen_lassen(client, monkeypatch)
    monkeypatch.setattr(runner, "belegt_gb", lambda: 1.8)
    daten = client.get("/api/v1/sprachserver").json()
    assert daten["belegt_gb"] == 1.8


def test_ein_stehender_server_meldet_keinen_speicher(client: TestClient):
    """Schweigeprobe: nothing running, nothing to add."""
    daten = client.get("/api/v1/sprachserver").json()
    assert daten["belegt_gb"] is None


def test_the_answer_carries_the_memory_of_the_tidy_up_server(client: TestClient, monkeypatch):
    """The tidy-up server is a process of its own: while it runs, its share
    rides along so the machine head's sum can count it."""
    runner = _laufen_lassen(client, monkeypatch)
    monkeypatch.setattr(runner, "belegt_gb", lambda: 1.8)
    monkeypatch.setattr(client.app.state.sprachputzrunner, "belegt_gb", lambda: 2.4)
    data = client.get("/api/v1/sprachserver").json()
    assert data["belegt_gb"] == 1.8
    assert data["tidy_up_used_gb"] == 2.4


def test_a_standing_tidy_up_server_reports_no_memory(client: TestClient, monkeypatch):
    """Schweigeprobe: the speech server runs, the tidy-up server does not —
    no share is added for it."""
    runner = _laufen_lassen(client, monkeypatch)
    monkeypatch.setattr(runner, "belegt_gb", lambda: 1.8)
    data = client.get("/api/v1/sprachserver").json()
    assert data["belegt_gb"] == 1.8
    assert data["tidy_up_used_gb"] is None


def test_der_start_reicht_die_regler_durch(client: TestClient, monkeypatch):
    """Window, layers and threads come from the form; the port stays this
    server's own."""
    gesehen: dict = {}
    runner = client.app.state.sprachrunner
    monkeypatch.setattr(runner, "starten", lambda modell, **kw: gesehen.update(kw))
    monkeypatch.setattr(runner, "lauf", lambda: None)

    client.post(
        "/api/v1/sprachserver/start",
        json={"modell": "asr.gguf", "kontext": 8192, "schichten": 40,
              "threads": 6, "port": 8099},
    )
    assert gesehen["kontext"] == 8192
    assert gesehen["schichten"] == 40
    assert gesehen["port"] == 8099
    assert gesehen["fein"].faeden == 6


def test_der_sprach_start_weckt_das_putzmodell_nicht(client: TestClient, monkeypatch):
    """Start and stop belong to each server alone. One button bringing both
    up was exactly how a failure of one read as a failure of the other —
    and the silence check is the point: a file is chosen for the cleaner,
    and the speech start still leaves it alone."""
    client.put(
        "/api/v1/settings/global/diktat",
        json={"wert": {"bereinigung": "putzmodell", "putzmodell": "klein.gguf"}},
    )
    runner = client.app.state.sprachrunner
    monkeypatch.setattr(runner, "starten", lambda modell, **kw: None)
    monkeypatch.setattr(runner, "laeuft", lambda: True)
    monkeypatch.setattr(
        runner,
        "lauf",
        lambda: Lauf(modell="asr.gguf", kontext=4096, schichten=99, port=8084),
    )
    gerufen: list = []

    def putz_startet(*a, **kw):
        gerufen.append(1)

    monkeypatch.setattr(client.app.state.sprachputzrunner, "starten", putz_startet)

    antwort = client.post("/api/v1/sprachserver/start", json={"modell": "asr.gguf"})
    assert antwort.status_code == 200
    assert antwort.json()["laeuft"] is True
    assert gerufen == []


def test_der_sprach_stopp_laesst_das_putzmodell_laufen(client: TestClient, monkeypatch):
    """The other half of the same rule: stopping one never stops the other
    behind its back."""
    putz_stopps: list = []

    def putz_stoppt():
        putz_stopps.append(1)

    monkeypatch.setattr(client.app.state.sprachputzrunner, "stoppen", putz_stoppt)
    monkeypatch.setattr(client.app.state.sprachrunner, "stoppen", lambda: None)

    assert client.post("/api/v1/sprachserver/stop").status_code == 200
    assert putz_stopps == []


def test_der_bereinigungsserver_startet_auf_seinem_port_und_mit_den_einstellungen(
    client: TestClient, monkeypatch
):
    """Its own route, its own port, and the numbers of its own setting on the
    command its start composes: memory and the five generation values."""
    client.put(
        "/api/v1/settings/global/diktat",
        json={"wert": {
            "putzkontext": 4096, "putzschichten": 40, "putzfaeden": 6,
            "putztemperatur": 0.5, "putztop_k": 80,
        }},
    )
    putz = client.app.state.sprachputzrunner
    assert putz.port_vorgabe == 8085
    monkeypatch.setattr(putz, "laeuft", lambda: False)
    gesehen: dict = {}
    monkeypatch.setattr(putz, "starten", lambda modell, **kw: gesehen.update(modell=modell, **kw))

    antwort = client.post(
        "/api/v1/bereinigungsserver/start", json={"modell": "klein.gguf", "port": 8085}
    )
    assert antwort.status_code == 200
    assert gesehen["modell"] == "klein.gguf"
    assert gesehen["kontext"] == 4096
    assert gesehen["schichten"] == 40
    assert gesehen["faeden"] == 6
    # The five generation values, the works answers for everything nobody
    # moved — top-p 1.0 and repeat penalty 1.0 are the cleaner's own.
    assert gesehen["sampling"] == {
        "temperature": 0.5, "top_k": 80, "top_p": 1.0,
        "min_p": 0.0, "repeat_penalty": 1.0,
    }
    assert gesehen["drafter"] == ""
    assert gesehen["vision"] == ""


def test_der_bereinigungs_stopp_laesst_den_sprachserver_laufen(
    client: TestClient, monkeypatch
):
    """The own-window rule from the other side: stopping the cleaner is not
    stopping the ears."""
    runner = client.app.state.sprachrunner
    monkeypatch.setattr(runner, "laeuft", lambda: True)
    monkeypatch.setattr(
        runner,
        "lauf",
        lambda: Lauf(modell="asr.gguf", kontext=4096, schichten=99, port=8084),
    )
    gestoppt: list = []

    def sprach_stoppt():
        gestoppt.append("sprache")

    def putz_stoppt():
        gestoppt.append("putz")

    monkeypatch.setattr(runner, "stoppen", sprach_stoppt)
    monkeypatch.setattr(client.app.state.sprachputzrunner, "stoppen", putz_stoppt)

    antwort = client.post("/api/v1/bereinigungsserver/stop")
    assert antwort.status_code == 200
    assert gestoppt == ["putz"]
    assert antwort.json()["laeuft"] is False


def test_der_sitzungsschluessel_gilt_auch_fuer_den_ton(client: TestClient):
    """An endpoint that takes audio is an endpoint every page on this machine
    can knock on. It sits behind the same lock as everything else — checked,
    not assumed, and checked on six of its seven routes rather than on the
    one that happened to come to mind (the seventh, the voice, has its own
    test below)."""
    client.headers.pop("X-Sitzungsschluessel", None)
    assert client.get("/api/v1/sprachserver").status_code == 401
    assert client.get("/api/v1/sprachserver/log").status_code == 401
    assert client.post("/api/v1/sprachserver/start", json={"modell": "a"}).status_code == 401
    assert client.post("/api/v1/sprachserver/stop").status_code == 401
    assert client.post("/api/v1/sprachserver/folder").status_code == 401
    antwort = client.post(
        "/api/v1/sprachserver/transkribieren",
        content=b"RIFF",
        headers={"Content-Type": "audio/wav"},
    )
    assert antwort.status_code == 401
    assert json.loads(antwort.text)["detail"]


def test_der_sitzungsschluessel_gilt_auch_fuer_den_bereinigungsserver(client: TestClient):
    """The clean-up server is its own door now, so it wears the same lock —
    on every one of its routes."""
    client.headers.pop("X-Sitzungsschluessel", None)
    assert client.get("/api/v1/bereinigungsserver").status_code == 401
    assert client.get("/api/v1/bereinigungsserver/log").status_code == 401
    assert client.post(
        "/api/v1/bereinigungsserver/start", json={"modell": "a"}
    ).status_code == 401
    assert client.post("/api/v1/bereinigungsserver/stop").status_code == 401


# --- Asking the voice to speak -----------------------------------------------


def _stimme_bereitstellen(client: TestClient, name="stimme-Q8_0.gguf", stimmprobe=None) -> Path:
    """A model and its matching projector, on disk in the speech folder —
    the pairing `passende_mmproj` really resolves, not a stand-in for it.

    One PUT, not several: `setzen()` replaces the stored row rather than
    merging into it (app/db/repositories/einstellungen.py), so a second
    call with only one field would wipe out what an earlier call stored.
    """
    ordner = Path(client.app.state.sprachrunner.ordner)
    (ordner / "vision").mkdir(parents=True, exist_ok=True)
    (ordner / name).write_bytes(b"x")
    projektor = name.replace(".gguf", "-mmproj-Q8_0.gguf")
    (ordner / "vision" / projektor).write_bytes(b"x")
    wert = {"stimme": name, "stimmsprache": "de"}
    if stimmprobe is not None:
        wert["stimmprobe"] = stimmprobe
    client.put("/api/v1/settings/global/diktat", json={"wert": wert})
    return ordner


def test_ohne_stimme_wird_nichts_gerufen(client: TestClient, monkeypatch):
    gerufen = []
    monkeypatch.setattr(stimme, "sprechen", lambda *a, **kw: gerufen.append(1))
    antwort = client.post("/api/v1/sprachserver/sprechen", json={"text": "Guten Tag."})
    assert antwort.status_code == 409
    assert antwort.json()["detail"]
    assert not gerufen


def test_ohne_stimmsprache_wird_nichts_gerufen(client: TestClient, monkeypatch):
    client.put("/api/v1/settings/global/diktat", json={"wert": {"stimme": "m.gguf"}})
    gerufen = []
    monkeypatch.setattr(stimme, "sprechen", lambda *a, **kw: gerufen.append(1))
    antwort = client.post("/api/v1/sprachserver/sprechen", json={"text": "Guten Tag."})
    assert antwort.status_code == 409
    assert antwort.json()["detail"]
    assert not gerufen


def test_eine_fremde_stimme_wird_abgewiesen(client: TestClient):
    """The setting is not a trusted path: a name that never was one of the
    real models in this folder must not reach `ordner / gewaehlte_stimme` —
    a `../` in it would walk out, an absolute path would replace `ordner`
    outright, and either would hand llama-tts a file this request had no
    business naming."""
    client.put(
        "/api/v1/settings/global/diktat",
        json={"wert": {"stimme": "../../etc/passwd", "stimmsprache": "de"}},
    )
    antwort = client.post("/api/v1/sprachserver/sprechen", json={"text": "Hallo."})
    assert antwort.status_code == 404


def test_ohne_projektor_wird_es_gemeldet(client: TestClient):
    """The model exists, but nothing beside it can hear — the panel says so
    in plain words rather than letting the call fail with something about a
    template."""
    ordner = Path(client.app.state.sprachrunner.ordner)
    ordner.mkdir(parents=True, exist_ok=True)
    (ordner / "einsam.gguf").write_bytes(b"x")
    client.put(
        "/api/v1/settings/global/diktat",
        json={"wert": {"stimme": "einsam.gguf", "stimmsprache": "de"}},
    )
    antwort = client.post("/api/v1/sprachserver/sprechen", json={"text": "Hallo."})
    assert antwort.status_code == 412


def test_ohne_llama_tts_wird_es_gemeldet(client: TestClient, monkeypatch):
    _stimme_bereitstellen(client)
    monkeypatch.setattr(stimme, "programm_finden", lambda llama_server: None)
    antwort = client.post("/api/v1/sprachserver/sprechen", json={"text": "Hallo."})
    assert antwort.status_code == 412


def test_der_hauptweg_ruft_llama_tts_mit_allem(client: TestClient, monkeypatch):
    """Model, projector, sample, language and memory, plus the five
    generation values — the one call this route exists to make."""
    ordner = _stimme_bereitstellen(client, stimmprobe="probe.wav")
    probe = ordner / "probe.wav"
    probe.write_bytes(b"RIFF")
    monkeypatch.setattr(stimme, "programm_finden", lambda llama_server: Path("/bin/llama-tts"))
    gesehen: dict = {}

    def falsch(programm, modell, mmproj, text, *, sprache, ordner, stimmprobe=None,
               sampling=None, schichten=None, faeden=None):
        gesehen.update(
            programm=programm, modell=modell, mmproj=mmproj, text=text,
            sprache=sprache, ordner=ordner, stimmprobe=stimmprobe,
            sampling=sampling, schichten=schichten, faeden=faeden,
        )
        return b"RIFF-WAV"

    monkeypatch.setattr(stimme, "sprechen", falsch)
    antwort = client.post("/api/v1/sprachserver/sprechen", json={"text": "Guten Tag."})
    assert antwort.status_code == 200
    assert antwort.headers["content-type"] == "audio/wav"
    assert antwort.content == b"RIFF-WAV"
    assert gesehen["programm"] == Path("/bin/llama-tts")
    assert gesehen["modell"] == ordner / "stimme-Q8_0.gguf"
    assert gesehen["mmproj"] == ordner / "vision" / "stimme-Q8_0-mmproj-Q8_0.gguf"
    assert gesehen["text"] == "Guten Tag."
    assert gesehen["sprache"] == "de"
    assert gesehen["stimmprobe"] == "probe.wav"
    # Nothing stored: the five values a voice has always been called with,
    # and its memory pair (all layers on the card, the engine's own threads).
    assert gesehen["sampling"] == {
        "temperature": stimme.TEMPERATUR, "top_k": stimme.TOP_K,
        "top_p": stimme.TOP_P, "min_p": stimme.MIN_P,
        "repeat_penalty": stimme.WIEDERHOLUNGSSTRAFE,
    }
    assert gesehen["schichten"] == 99
    assert gesehen["faeden"] == 0


def test_gespeicherte_werte_erreichen_die_stimme(client: TestClient, monkeypatch):
    """Every one of the seven settings the panel offers arrives in the same
    call — the temperature, the other four values and the memory pair."""
    _stimme_bereitstellen(client)
    client.put(
        "/api/v1/settings/global/diktat",
        json={"wert": {
            "stimme": "stimme-Q8_0.gguf", "stimmsprache": "de",
            "stimmtemperatur": 0.4, "stimmtop_k": 80, "stimmmin_p": 0.1,
            "stimmschichten": 40, "stimmfaeden": 6,
        }},
    )
    monkeypatch.setattr(stimme, "programm_finden", lambda llama_server: Path("/bin/llama-tts"))
    gesehen: dict = {}
    monkeypatch.setattr(
        stimme, "sprechen", lambda *a, **kw: gesehen.update(kw) or b"RIFF"
    )
    assert client.post("/api/v1/sprachserver/sprechen", json={"text": "Hallo."}).status_code == 200
    assert gesehen["sampling"]["temperature"] == 0.4
    assert gesehen["sampling"]["top_k"] == 80
    assert gesehen["sampling"]["min_p"] == 0.1
    # Not moved: the works answer still stands for it.
    assert gesehen["sampling"]["top_p"] == stimme.TOP_P
    assert gesehen["schichten"] == 40
    assert gesehen["faeden"] == 6


def test_eine_temperatur_ausserhalb_wird_nicht_gespeichert(client: TestClient):
    client.put("/api/v1/settings/global/diktat", json={"wert": {"stimmtemperatur": 1.5}})
    wert = client.get("/api/v1/settings/resolved/diktat").json()["wert"]
    assert "stimmtemperatur" not in wert


def test_die_auskunft_nennt_die_fuenf_stimmenwerte(client: TestClient):
    """The works values the parameter card shows while nothing is stored:
    the ones a voice has always been called with."""
    auskunft = client.get("/api/v1/sprachserver").json()
    vorgaben = auskunft["diktat_vorgaben"]
    assert vorgaben["stimmtemperatur"] == stimme.TEMPERATUR
    assert vorgaben["stimmtop_k"] == stimme.TOP_K
    assert vorgaben["stimmtop_p"] == stimme.TOP_P
    assert vorgaben["stimmmin_p"] == stimme.MIN_P
    assert vorgaben["stimmstrafe"] == stimme.WIEDERHOLUNGSSTRAFE


def test_der_sitzungsschluessel_gilt_auch_fuer_die_stimme(client: TestClient):
    client.headers.pop("X-Sitzungsschluessel", None)
    antwort = client.post("/api/v1/sprachserver/sprechen", json={"text": "Hallo."})
    assert antwort.status_code == 401
