"""Every word on a phone page stands once, under the heading it belongs to.

Four places said a word twice: the cloud page for adding a provider ("Which"
as heading and as field), the catalogue ("From Hugging Face" as heading and as
field), the server pages (the state three times; every number under
"Network") and one cloud provider (the key split over two lines, a count of
models as a heading). The catalogue also said its own name again under its
head, and "Hugging Face" over the field of the token that carries the name.
The checks read the files as they ship.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend" / "src"
PHONE = FRONTEND / "phone"

PLACES = [
    "cloud/AddProvider.svelte",
    "cloud/ProviderView.svelte",
    "pages/Catalog.svelte",
    "servers/ServerView.svelte",
]


def _read(name: str) -> str:
    return (PHONE / name).read_text(encoding="utf-8")


def _group_titles(text: str) -> list[str]:
    return re.findall(r"<Group\s+title=\{t\(\s*'([^']+)'", text)


def _labels(text: str) -> list[str]:
    return re.findall(r"\blabel=\{t\(\s*'([^']+)'", text)


@pytest.mark.parametrize("name", PLACES)
def test_no_heading_says_the_word_of_a_field_under_it(name):
    text = _read(name)
    same = set(_group_titles(text)) & set(_labels(text))
    assert not same, f"{name}: {sorted(same)} is a heading and a field label"


def test_the_add_page_says_which_only_at_the_field():
    text = _read("cloud/AddProvider.svelte")
    assert text.count("modell.anbieter_waehlen") == 1
    assert "<Pick label={t('modell.anbieter_waehlen')}" in text


def test_the_catalogue_says_from_hugging_face_only_at_the_search_field():
    text = _read("pages/Catalog.svelte")
    assert text.count("'katalog.von_hf'") == 1
    assert "<Field label={t('katalog.von_hf')}" in text


def test_the_catalogue_names_its_kinds_as_rows_and_says_catalogue_only_in_its_head():
    text = _read("pages/Catalog.svelte")
    assert "title: 'menue.katalog'" in text, "the head of the page stays"
    assert text.count("menue.katalog") == 1, "no second row or choice under the head"
    assert "<Pick" not in text
    assert re.search(r"\{#each KINDS as kind \(kind\.value\)\}\s*<Menuezeile titel=\{kind\.label\}", text)
    for kind in ("chat", "einbettung", "sprache", "bild", "zubehoer"):
        assert text.count(f"katalog.art_{kind}") == 1


def test_the_catalogue_says_hugging_face_once_and_names_the_token_only_for_a_screen_reader():
    text = _read("pages/Catalog.svelte")
    assert "<Group title={t('editor.quelle_hf')}>" not in text
    # One row of the token, whether it is set or not: the same word in both states.
    assert text.count("t('editor.quelle_hf')") == 2
    assert "<Field label={t('editor.quelle_hf')} ariaLabel={t('modell.hf_token')}" in text
    assert text.count("modell.hf_token") == 1
    assert "aria-label={ariaLabel}" in _read("parts/Field.svelte")


def test_a_tap_on_the_chosen_kind_changes_nothing():
    text = _read("pages/Catalog.svelte")
    body = text.split("function pickKind(value) {", 1)[1].split("\n  }\n", 1)[0]
    assert body.index("if (value === art) return") < body.index("art = value")


def test_a_running_server_says_its_state_once():
    text = _read("servers/ServerView.svelte")
    assert "Standpille" not in text, "the pill would say it a second time"
    top = text.split("<Group>\n  <Menuezeile", 1)[1].split("</Group>", 1)[0]
    assert "<Menuezeile" not in top, "one row only"
    assert "row.running ? t('modell.laeuft_port'" in top
    assert top.count("laeuft_port") == 1


def test_the_memory_numbers_stand_under_memory_and_the_port_alone_under_network():
    text = _read("servers/ServerView.svelte")
    assert "driver.fields.filter((name) => name !== 'port')" in text
    memory = re.search(r"<Group title=\{t\('modell\.gruppe_speicher'\)\}>(.*?)\n  </Group>", text, re.S)
    network = re.search(r"<Group title=\{t\('modell\.gruppe_netz'\)\}>(.*?)\n</Group>", text, re.S)
    assert memory and network
    assert "memoryFields" in memory.group(1)
    assert "numberTitle('port')" in network.group(1)
    assert "driver.fields" not in network.group(1)
    assert text.count("<Group title={t('modell.gruppe_netz')}>") == 1
    assert "{#each driver.fields" not in text


def test_the_network_group_never_holds_a_memory_number():
    text = _read("servers/ServerView.svelte")
    network = text.split("<Group title={t('modell.gruppe_netz')}>", 1)[1].split("</Group>", 1)[0]
    for key in ("feld_kontext", "feld_schichten", "feld_faeden"):
        assert key not in network


def test_the_image_server_page_is_left_as_it_was():
    text = _read("servers/ImageServerView.svelte")
    assert "Standpille" in text


def test_a_provider_shows_its_key_in_one_line_with_its_state():
    text = _read("cloud/ProviderView.svelte")
    row = re.search(r"<Menuezeile\s+titel=\{house\.schluessel_env\}(.*?)/>", text, re.S)
    assert row, "the key name is not a line of its own"
    assert "modell.schluessel_gesetzt" in row.group(1)
    assert "modell.schluessel_fehlt" in row.group(1)
    assert "punkt=" in row.group(1)
    assert text.count("modell.schluessel_gesetzt") == 1
    assert "<Line label={t('modell.schluessel')}" not in text


def test_a_provider_has_the_word_models_over_its_models_and_no_count_heading():
    text = _read("cloud/ProviderView.svelte")
    assert "<Group title={t('modell.feld_modell')}>" in text
    assert "modell.von_zahl" not in text


def test_the_count_stays_in_the_row_of_the_provider_in_the_list():
    text = _read("pages/ModelsCloud.svelte")
    assert "t('modell.von_zahl', { gewaehlt: house.modelle.length, gesamt: house.katalog })" in text


def test_the_desktop_pages_keep_their_own_structure():
    rules = (FRONTEND / "teile" / "Serverregler.svelte").read_text(encoding="utf-8")
    assert "t('modell.gruppe_speicher')" in rules
    assert "t('modell.gruppe_netz')" in rules
    assert "t('modell.feld_port')" in rules
    clouds = (FRONTEND / "teile" / "ModelleCloud.svelte").read_text(encoding="utf-8")
    assert "t('modell.von_zahl')" in clouds
    assert "t('modell.schluessel_gesetzt')" in clouds


def test_every_server_lists_its_port_last_so_the_network_group_always_has_it():
    text = _read("servers/drivers.js")
    lists = re.findall(r"fields:\s*\[([^\]]*)\]", text)
    assert len(lists) == 5
    for names in lists:
        assert names.split(",")[-1].strip() == "'port'"
