"""The voice: a subprocess call to llama-tts, and the settings behind it."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app import diktatsprachewahl, stimme


# --- Resolving the program ---------------------------------------------------


def test_findet_den_binder_neben_dem_server(tmp_path: Path):
    """The sibling of the already-resolved llama-server, not an independent
    PATH lookup — a different build found on PATH might not carry Qwen3-TTS
    support at all."""
    server = tmp_path / "llama-server"
    server.write_bytes(b"x")
    neben = tmp_path / "llama-tts"
    neben.write_bytes(b"x")
    assert stimme.programm_finden(server) == neben


def test_faellt_auf_den_pfad_zurueck_ohne_geschwister(tmp_path, monkeypatch):
    server = tmp_path / "llama-server"
    server.write_bytes(b"x")
    monkeypatch.setattr(stimme.shutil, "which", lambda name: "/usr/local/bin/llama-tts")
    assert stimme.programm_finden(server) == Path("/usr/local/bin/llama-tts")


def test_nichts_gefunden_ist_nichts(tmp_path, monkeypatch):
    server = tmp_path / "llama-server"
    server.write_bytes(b"x")
    monkeypatch.setattr(stimme.shutil, "which", lambda name: None)
    assert stimme.programm_finden(server) is None


# --- Speaking one sentence ----------------------------------------------------


class _Lauf:
    def __init__(self, returncode=0, stderr=""):
        self.returncode = returncode
        self.stderr = stderr


def test_der_befehl_traegt_alle_fuenf_werte_und_die_probe(tmp_path, monkeypatch):
    ordner = tmp_path
    probe = ordner / "probe.wav"
    probe.write_bytes(b"RIFF")
    gesehen: dict = {}

    def falsch(befehl, **kw):
        gesehen["befehl"] = befehl
        ziel = Path(befehl[befehl.index("-o") + 1])
        ziel.write_bytes(b"RIFF-WAV")
        return _Lauf()

    monkeypatch.setattr(stimme, "_laufen", falsch)
    wav = stimme.sprechen(
        Path("/bin/llama-tts"),
        ordner / "modell.gguf",
        ordner / "vision" / "mmproj.gguf",
        "Guten Tag.",
        sprache="de",
        ordner=ordner,
        stimmprobe="probe.wav",
    )
    assert wav == b"RIFF-WAV"
    befehl = gesehen["befehl"]
    assert "-m" in befehl and str(ordner / "modell.gguf") in befehl
    assert "-mm" in befehl and str(ordner / "vision" / "mmproj.gguf") in befehl
    assert "-p" in befehl and "Guten Tag." in befehl
    assert "--tts-lang" in befehl and "de" in befehl
    assert "--temp" in befehl and str(stimme.TEMPERATUR) in befehl
    assert "--top-k" in befehl and str(stimme.TOP_K) in befehl
    assert "--top-p" in befehl and str(stimme.TOP_P) in befehl
    assert "--min-p" in befehl and str(stimme.MIN_P) in befehl
    assert "--repeat-penalty" in befehl and str(stimme.WIEDERHOLUNGSSTRAFE) in befehl
    assert "--tts-speaker-file" in befehl and str(probe) in befehl


def test_die_temperatur_kommt_vom_aufrufer_und_nur_sie(tmp_path, monkeypatch):
    """The stored temperature reaches ``--temp``; the four fixed values from
    the model card stay exactly as they were."""
    gesehen: dict = {}

    def falsch(befehl, **kw):
        gesehen["befehl"] = befehl
        Path(befehl[befehl.index("-o") + 1]).write_bytes(b"x")
        return _Lauf()

    monkeypatch.setattr(stimme, "_laufen", falsch)
    stimme.sprechen(
        Path("/bin/llama-tts"), tmp_path / "m.gguf", tmp_path / "mm.gguf",
        "Text", sprache="de", ordner=tmp_path, sampling={"temperature": 0.35},
    )
    befehl = gesehen["befehl"]
    assert befehl[befehl.index("--temp") + 1] == "0.35"
    assert befehl[befehl.index("--top-k") + 1] == "50"
    assert befehl[befehl.index("--top-p") + 1] == "1.0"
    assert befehl[befehl.index("--min-p") + 1] == "0.0"
    assert befehl[befehl.index("--repeat-penalty") + 1] == "1.05"


def test_die_gesetzten_werte_stehen_auf_der_befehlszeile(tmp_path, monkeypatch):
    """Every stored value reaches its own flag, and the memory pair travels
    with it: layers always, threads only when one was set — zero means the
    engine decides, exactly as on the chat servers."""
    gesehen: dict = {}

    def falsch(befehl, **kw):
        gesehen["befehl"] = befehl
        Path(befehl[befehl.index("-o") + 1]).write_bytes(b"x")
        return _Lauf()

    monkeypatch.setattr(stimme, "_laufen", falsch)
    stimme.sprechen(
        Path("/bin/llama-tts"), tmp_path / "m.gguf", tmp_path / "mm.gguf",
        "Text", sprache="de", ordner=tmp_path,
        sampling={
            "temperature": 0.4, "top_k": 80, "top_p": 0.9,
            "min_p": 0.1, "repeat_penalty": 1.2,
        },
        schichten=40,
        faeden=6,
    )
    befehl = gesehen["befehl"]
    assert befehl[befehl.index("--temp") + 1] == "0.4"
    assert befehl[befehl.index("--top-k") + 1] == "80"
    assert befehl[befehl.index("--top-p") + 1] == "0.9"
    assert befehl[befehl.index("--min-p") + 1] == "0.1"
    assert befehl[befehl.index("--repeat-penalty") + 1] == "1.2"
    assert befehl[befehl.index("--n-gpu-layers") + 1] == "40"
    assert befehl[befehl.index("-t") + 1] == "6"


def test_ohne_einstellung_bleiben_die_speicherwerte_wie_sie_waren(tmp_path, monkeypatch):
    """The silence check for the memory pair: nothing set names no layer
    count (the engine places the layers) and sets no threads lever."""
    gesehen: dict = {}

    def falsch(befehl, **kw):
        gesehen["befehl"] = befehl
        Path(befehl[befehl.index("-o") + 1]).write_bytes(b"x")
        return _Lauf()

    monkeypatch.setattr(stimme, "_laufen", falsch)
    stimme.sprechen(
        Path("/bin/llama-tts"), tmp_path / "m.gguf", tmp_path / "mm.gguf",
        "Text", sprache="de", ordner=tmp_path,
    )
    befehl = gesehen["befehl"]
    assert "--n-gpu-layers" not in befehl
    assert "-t" not in befehl


def test_ohne_probe_bleibt_das_flag_weg(tmp_path, monkeypatch):
    gesehen: dict = {}

    def falsch(befehl, **kw):
        gesehen["befehl"] = befehl
        Path(befehl[befehl.index("-o") + 1]).write_bytes(b"x")
        return _Lauf()

    monkeypatch.setattr(stimme, "_laufen", falsch)
    stimme.sprechen(
        Path("/bin/llama-tts"), tmp_path / "m.gguf", tmp_path / "mm.gguf",
        "Text", sprache="en", ordner=tmp_path,
    )
    assert "--tts-speaker-file" not in gesehen["befehl"]


def test_eine_probe_ausserhalb_des_ordners_wird_abgewiesen(tmp_path, monkeypatch):
    """The one containment check this module relies on — the same idiom the
    model picker itself already uses."""
    aussen = tmp_path.parent / "aussen.wav"
    aussen.write_bytes(b"RIFF")
    gerufen = []
    monkeypatch.setattr(stimme, "_laufen", lambda *a, **kw: gerufen.append(1))
    with pytest.raises(stimme.SprechenNichtMoeglich) as ausfall:
        stimme.sprechen(
            Path("/bin/llama-tts"), tmp_path / "m.gguf", tmp_path / "mm.gguf",
            "Text", sprache="de", ordner=tmp_path, stimmprobe="../aussen.wav",
        )
    assert ausfall.value.grund == "stimmprobe_ungueltig"
    assert not gerufen, "llama-tts was called despite the invalid sample"


def test_ein_fehlschlag_wird_gemeldet(tmp_path, monkeypatch):
    monkeypatch.setattr(
        stimme, "_laufen", lambda *a, **kw: _Lauf(returncode=1, stderr="boom")
    )
    with pytest.raises(stimme.SprechenNichtMoeglich) as ausfall:
        stimme.sprechen(
            Path("/bin/llama-tts"), tmp_path / "m.gguf", tmp_path / "mm.gguf",
            "Text", sprache="de", ordner=tmp_path,
        )
    assert ausfall.value.grund == "stimme_fehlgeschlagen"


def test_eine_zeitueberschreitung_wird_gemeldet(tmp_path, monkeypatch):
    def falsch(*a, **kw):
        raise subprocess.TimeoutExpired(cmd="llama-tts", timeout=1)

    monkeypatch.setattr(stimme, "_laufen", falsch)
    with pytest.raises(stimme.SprechenNichtMoeglich) as ausfall:
        stimme.sprechen(
            Path("/bin/llama-tts"), tmp_path / "m.gguf", tmp_path / "mm.gguf",
            "Text", sprache="de", ordner=tmp_path,
        )
    assert ausfall.value.grund == "stimme_zeitueberschreitung"


# --- The settings --------------------------------------------------------


def test_die_vorgaben_stehen_wie_besprochen():
    vorgabe = diktatsprachewahl.VORGABE
    assert vorgabe["vorlesen"] is True
    assert vorgabe["stimme"] == ""
    assert vorgabe["stimmprobe"] == ""
    assert vorgabe["stimmsprache"] == ""
    assert vorgabe["stimmtemperatur"] == stimme.TEMPERATUR


def test_eine_temperatur_zwischen_den_stufen_bleibt_wie_eingegeben():
    """The stored value is exactly what the number field shows: the slider
    finds the nearest step by itself, so there is no reason to round a
    typed 0.33 into a 0.35 the field would then misreport."""
    assert diktatsprachewahl.wahl_pruefen({"stimmtemperatur": 0.33}) == {"stimmtemperatur": 0.33}
    assert diktatsprachewahl.wahl_pruefen({"stimmtemperatur": 0.31}) == {"stimmtemperatur": 0.31}


def test_eine_temperatur_im_bereich_wird_gespeichert():
    assert diktatsprachewahl.wahl_pruefen({"stimmtemperatur": 0.35}) == {"stimmtemperatur": 0.35}
    assert diktatsprachewahl.wahl_pruefen({"stimmtemperatur": 0}) == {"stimmtemperatur": 0.0}
    assert diktatsprachewahl.wahl_pruefen({"stimmtemperatur": 1}) == {"stimmtemperatur": 1.0}


def test_eine_temperatur_ausserhalb_wird_nicht_gespeichert():
    """Not clamped: a value outside the range is a choice nobody made."""
    for roh in (-0.1, 1.5, "0.5", True, None):
        assert diktatsprachewahl.wahl_pruefen({"stimmtemperatur": roh}) == {}


def test_die_vier_neuen_felder_ueberleben_die_pruefung():
    sauber = diktatsprachewahl.wahl_pruefen(
        {"vorlesen": False, "stimme": "stimme.gguf", "stimmprobe": "probe.wav", "stimmsprache": "de"}
    )
    assert sauber == {
        "vorlesen": False,
        "stimme": "stimme.gguf",
        "stimmprobe": "probe.wav",
        "stimmsprache": "de",
    }


def test_eine_unbekannte_stimmsprache_faellt_auf_leer_zurueck():
    """Empty, not "auto" — a voice does not guess its own language."""
    sauber = diktatsprachewahl.wahl_pruefen({"stimmsprache": "xx"})
    assert sauber["stimmsprache"] == ""


def test_die_einstellungen_ueberleben_das_speichern(client):
    client.put(
        "/api/v1/settings/global/diktat",
        json={"wert": {
            "vorlesen": False, "stimme": "m.gguf",
            "stimmprobe": "p.wav", "stimmsprache": "en",
        }},
    )
    wert = client.get("/api/v1/settings/resolved/diktat").json()["wert"]
    assert wert["vorlesen"] is False
    assert wert["stimme"] == "m.gguf"
    assert wert["stimmprobe"] == "p.wav"
    assert wert["stimmsprache"] == "en"


# --- The catalogue entry, read out of its own source -------------------------


def test_der_katalogeintrag_nennt_datei_und_projektor():
    """No test runner reaches the frontend catalogue — read out of the
    source, the same way the other catalogue checks do
    (tests/test_modellsuche.py)."""
    import re

    js = (Path(__file__).resolve().parent.parent / "frontend/src/lib/modellempfehlungen.js").read_text(
        encoding="utf-8"
    )
    eintrag = re.search(r"id: 'tts-qwen3-17b'.*?fassungen: \[\{(.*?)\}\]", js, re.S)
    assert eintrag, "the Qwen3-TTS catalogue entry is missing"
    block = eintrag.group(1)
    assert "datei: 'Qwen3-TTS-12Hz-1.7B-Base-Q4_K_M.gguf'" in block
    assert "mmproj: 'mmproj-Qwen3-TTS-12Hz-1.7B-Base-Q8_0.gguf'" in block
