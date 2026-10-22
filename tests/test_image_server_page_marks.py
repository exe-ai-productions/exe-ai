"""The picture server's page, as the drawing shows it: its two heads carry
their signs, the model card's head carries the picture, the catalogue door is
as tall as the picker's neighbour, the sizes of the models in the folder
carry the decimal sign of the language, and the generator's builds are the
rows of the shared piece — greyed on a Mac, where the service names them.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import sddownload

TEILE = Path(__file__).resolve().parent.parent / "frontend" / "src" / "teile"
SERVERTAFEL = (TEILE / "Servertafel.svelte").read_text(encoding="utf-8")
BILDSERVER = (TEILE / "Bildserver.svelte").read_text(encoding="utf-8")
BILDGERAETE = (TEILE / "BildGeraete.svelte").read_text(encoding="utf-8")
AUFBEREITUNG = (TEILE / "Promptaufbereitung.svelte").read_text(encoding="utf-8")
SERVERABSCHNITT = (TEILE / "Serverabschnitt.svelte").read_text(encoding="utf-8")
FILES = (TEILE / "ImageServerFiles.svelte").read_text(encoding="utf-8")
SERVERS = [
    "Modellserver.svelte", "Agentserver.svelte", "Einbettungsserver.svelte",
    "Sprachserver.svelte", "Bereinigungsserver.svelte",
]

FOUR = [
    {"variante": "cpu", "groesse": 0},
    {"variante": "cuda12", "groesse": 0},
    {"variante": "vulkan", "groesse": 0},
    {"variante": "rocm", "groesse": 0},
]


def _four() -> list[dict]:
    # CUDA brings its runtime down with it, so its size counts both.
    sizes = {name: size for name, (_, size) in sddownload._PAKETE_WIN32.items()}
    sizes["cuda12"] += sddownload._CUDART[1]
    return [{**row, "groesse": sizes[row["variante"]]} for row in FOUR]


def _system(monkeypatch, platform: str, machine: str) -> None:
    monkeypatch.setattr(sddownload, "sys", SimpleNamespace(platform=platform))
    monkeypatch.setattr(sddownload.platform, "machine", lambda: machine)


def test_the_memory_head_carries_the_chip_with_a_bolt_and_the_preparation_head_the_broom():
    assert "<Serverabschnitt zeichen=\"chip_bolt\" titel={t('bild.gruppe_speicher')}>" in BILDGERAETE
    assert "<Serverabschnitt zeichen=\"besen\" titel={t('bildserver.aufbereitung')}>" in AUFBEREITUNG


def test_setting_the_instruction_back_is_a_sign_button_with_the_word_as_its_tooltip():
    button = AUFBEREITUNG[AUFBEREITUNG.index('<button class="rowsign"'):AUFBEREITUNG.index("</button>")]
    assert 'zeichen="refresh"' in button
    assert "title={t('sprachserver.zuruecksetzen')}" in button
    assert "aria-label={t('sprachserver.zuruecksetzen')}" in button
    # The word stands nowhere as a button's text any more.
    assert "stillknopf" not in AUFBEREITUNG
    markup = AUFBEREITUNG.split("</script>", 1)[1].split("<style>", 1)[0]
    assert not re.search(r">\s*\{t\('sprachserver\.zuruecksetzen'\)\}\s*<", markup)
    # The sign stands in the title line of the instruction, the field under it.
    assert markup.index('class="obenzeile"') < markup.index('class="rowsign"') < markup.index("<WachsendesFeld")
    # The sign's size is the card's rule, shared by every window that has such a row.
    assert re.search(r"\.rowsign\)?\s*\{[^}]*width:\s*30px;[^}]*height:\s*30px;", SERVERABSCHNITT)
    assert "<style>" not in AUFBEREITUNG


def test_the_sizes_in_the_folder_carry_the_decimal_sign_of_the_language():
    assert "import { formatGb } from '../lib/numberDisplay.js'" in FILES
    assert "formatGb(bytes / 1e9, texte.sprache)" in FILES
    assert "toLocaleString" not in FILES


def test_the_catalogue_door_is_34_square():
    door = SERVERTAFEL[SERVERTAFEL.index("  .katalogtuer {"):SERVERTAFEL.index("  .katalogtuer:hover")]
    assert "width: 34px;" in door and "height: 34px;" in door


def test_the_head_of_the_model_card_takes_its_sign_from_the_page_and_the_picture_server_gives_the_picture():
    assert "zeichen = 'paket'," in SERVERTAFEL
    assert (
        "<Serverabschnitt {zeichen} titel={modellBeschriftung} info={modellInfo} gewicht={modellGewicht}>"
        in SERVERTAFEL
    )
    assert re.search(r"<Servertafel\s+zeichen=\"bild\"", BILDSERVER)
    # Silence: no other page passes a sign, so every other page keeps the packet.
    for page in SERVERS:
        source = (TEILE / page).read_text(encoding="utf-8")
        opening = source.split("<Servertafel", 1)[1].split("{#snippet", 1)[0]
        assert not re.search(r"^\s+zeichen=", opening, re.M), page


def test_the_generators_builds_are_the_rows_of_the_shared_piece():
    assert "import BuildRows from './BuildRows.svelte'" in BILDSERVER
    assert "<BuildRows" in BILDSERVER
    assert "installed={varianten?.installiert}" in BILDSERVER
    for gone in ("bildserver.variante_holen", "bildserver.variante_installiert",
                 "bildserver.restore_tested_build", "groesseText"):
        assert gone not in BILDSERVER, gone
    # The version row keeps the one offer of a newer build, as one sign.
    assert "<UpdateButton" in BILDSERVER
    assert "bildserver.nach_updates_suchen" not in BILDSERVER


def test_a_mac_names_the_four_builds_with_the_sizes_of_windows(monkeypatch):
    _system(monkeypatch, "darwin", "arm64")
    assert [(v, g) for v, g in sddownload.unavailable_variants()] == [
        (row["variante"], row["groesse"]) for row in _four()]
    # Nothing is offered there: the choice stays empty.
    assert sddownload.waehlbare_varianten() == []


@pytest.mark.parametrize(
    ("platform", "machine"),
    [("linux", "x86_64"), ("linux", "aarch64"), ("win32", "AMD64"), ("win32", "arm64")],
)
def test_silence_every_other_system_names_no_greyed_build(monkeypatch, platform, machine):
    _system(monkeypatch, platform, machine)
    assert sddownload.unavailable_variants() == []


def test_the_route_names_the_greyed_builds_on_a_mac_and_none_elsewhere(client: TestClient, monkeypatch):
    _system(monkeypatch, "darwin", "arm64")
    mac = client.get("/api/v1/bild/programm/varianten").json()
    assert mac["varianten"] == []
    assert mac["unavailable"] == _four()
    _system(monkeypatch, "win32", "AMD64")
    windows = client.get("/api/v1/bild/programm/varianten").json()
    assert windows["unavailable"] == []
    assert [row["variante"] for row in windows["varianten"]] == ["cpu", "cuda12", "vulkan", "rocm"]
    _system(monkeypatch, "linux", "x86_64")
    assert client.get("/api/v1/bild/programm/varianten").json()["unavailable"] == []
