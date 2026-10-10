"""EXE_AI_DATEN: one program folder, several users, each with their own folder."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app import config as configmodul
from app import paketierung
from app.api.v1 import werkzeuge


@pytest.fixture
def eigene_wurzel(tmp_path, monkeypatch):
    wurzel = tmp_path / "nutzer" / "anna"
    monkeypatch.setenv(paketierung.DATEN_VARIABLE, str(wurzel))
    return wurzel


def test_ohne_variable_bleibt_es_der_programmordner(monkeypatch):
    monkeypatch.delenv(paketierung.DATEN_VARIABLE, raising=False)
    assert paketierung.daten() == Path(paketierung.__file__).resolve().parent.parent


def test_eine_leere_variable_zaehlt_nicht(monkeypatch):
    monkeypatch.setenv(paketierung.DATEN_VARIABLE, "  ")
    assert paketierung.daten() == Path(paketierung.__file__).resolve().parent.parent


def test_die_variable_gewinnt_und_legt_den_ordner_an(eigene_wurzel):
    assert not eigene_wurzel.exists()
    assert paketierung.daten() == eigene_wurzel
    assert eigene_wurzel.is_dir()


def test_schreibbare_pfade_landen_im_eigenen_ordner(eigene_wurzel):
    assert paketierung.aufloesen(".env", schreibbar=True) == eigene_wurzel / ".env"
    assert paketierung.aufloesen("config.yaml", schreibbar=True) == eigene_wurzel / "config.yaml"
    # What ships with the program is still read from the program folder.
    assert paketierung.aufloesen("config.example.yaml") == paketierung.ressourcen() / "config.example.yaml"


def test_ein_gespeichertes_token_landet_in_der_eigenen_env(client, eigene_wurzel, monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "")
    antwort = client.post("/api/v1/models/token", json={"token": "hf_beispiel_5678"})
    assert antwort.status_code == 200
    assert "HF_TOKEN=hf_beispiel_5678" in (eigene_wurzel / ".env").read_text()


def test_die_werkzeugampel_liest_die_eigene_env(eigene_wurzel, monkeypatch):
    name = "EXE_TEST_NUR_IN_DER_EIGENEN_ENV"
    monkeypatch.delenv(name, raising=False)
    assert werkzeuge._schluessel_gesetzt(name) is False
    # Asking already created the folder; the key file is what is missing.
    assert eigene_wurzel.is_dir()
    (eigene_wurzel / ".env").write_text(f"{name}=wert\n", encoding="utf-8")
    assert werkzeuge._schluessel_gesetzt(name) is True
    platzhalter = werkzeuge._platzhalter('{"mcpServers": {"x": {"env": {"T": "${' + name + '}"}}}}')
    assert [(p.name, p.gesetzt) for p in platzhalter] == [(name, True)]
    assert name not in os.environ


def test_ein_relativer_ordner_wird_abgelehnt(monkeypatch):
    monkeypatch.setenv(paketierung.DATEN_VARIABLE, "nutzer/anna")
    with pytest.raises(RuntimeError, match="absolute"):
        paketierung.daten()


@pytest.fixture
def programmordner(tmp_path, monkeypatch):
    """A program folder of somebody else, with their own .env and server list."""
    ordner = tmp_path / "programm"
    ordner.mkdir()
    (ordner / "config.example.yaml").write_bytes((paketierung.ressourcen() / "config.example.yaml").read_bytes())
    (ordner / "mcp_servers.json").write_text('{"mcpServers": {"privat": {"command": "x"}}}', encoding="utf-8")
    (ordner / "mcp_servers.example.json").write_text('{"mcpServers": {}}', encoding="utf-8")
    (ordner / ".env").write_text("EXE_TEST_SCHLUESSEL_DES_PROGRAMMORDNERS=fremd\n", encoding="utf-8")
    monkeypatch.setattr(configmodul, "PROJEKT_WURZEL", ordner)
    monkeypatch.setattr(paketierung, "ressourcen", lambda: ordner)
    return ordner


def _laden(tmp_path):
    quelle = tmp_path / "config.yaml"
    quelle.write_text("app:\n  port: 8090\n", encoding="utf-8")
    try:
        configmodul.config_laden(quelle)
    finally:
        schluessel = os.environ.pop("EXE_TEST_SCHLUESSEL_DES_PROGRAMMORDNERS", None)
    return schluessel


def test_die_env_des_programmordners_bleibt_draussen(tmp_path, programmordner, eigene_wurzel):
    assert _laden(tmp_path) is None


def test_ohne_eigenen_ordner_bleibt_alles_wie_vorher(tmp_path, programmordner, monkeypatch):
    # One person, one folder: the program folder's .env and server list are theirs.
    monkeypatch.delenv(paketierung.DATEN_VARIABLE, raising=False)
    standard = tmp_path / "standard"
    standard.mkdir()
    monkeypatch.setattr(paketierung, "daten", lambda: standard)
    assert _laden(tmp_path) == "fremd"
    assert (standard / "mcp_servers.json").read_text(encoding="utf-8") == (
        programmordner / "mcp_servers.json").read_text(encoding="utf-8")


def test_die_serverliste_des_programmordners_bleibt_draussen(tmp_path, programmordner, eigene_wurzel):
    _laden(tmp_path)
    assert (eigene_wurzel / "mcp_servers.json").read_text(encoding="utf-8") == '{"mcpServers": {}}'


def test_ein_ordner_aus_der_env_des_programmordners_gehoert_derselben_person(tmp_path, programmordner, monkeypatch):
    # Named in the program folder's own .env, the folder belongs to the same person:
    # their keys and their server list come along.
    monkeypatch.delenv(paketierung.DATEN_VARIABLE, raising=False)
    eigener = tmp_path / "eigener"
    with open(programmordner / ".env", "a", encoding="utf-8") as datei:
        datei.write(f"{paketierung.DATEN_VARIABLE}={eigener}\n")
    try:
        assert _laden(tmp_path) == "fremd"
    finally:
        os.environ.pop(paketierung.DATEN_VARIABLE, None)
    assert (eigener / "mcp_servers.json").read_text(encoding="utf-8") == (
        programmordner / "mcp_servers.json").read_text(encoding="utf-8")
