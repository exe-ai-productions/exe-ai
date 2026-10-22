"""The mark in front of a model of the catalogue page: the logo of the
repository's OWNER, else the owner's round picture from Hugging Face, else
the letter (`frontend/src/lib/logos.js`, `frontend/src/lib/ownerPicture.svelte.js`,
`frontend/src/teile/OwnerMark.svelte`), and the sizes written with the
decimal sign of the language.

The interface has no DOM library here: the two modules are RUN in node (the
picture module in a copy, with the service call replaced by a counting
stand-in), the markup is read.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parent.parent
FRONTEND = WURZEL / "frontend"
LIB = FRONTEND / "src" / "lib"
TEILE = FRONTEND / "src" / "teile"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")


def _quelle(pfad: Path) -> str:
    return pfad.read_text(encoding="utf-8")


def _driver(code: str) -> object:
    """Runs `code` as a module of the frontend, so the real modules are
    imported the way the page imports them."""
    treiber = FRONTEND / f"owner-{os.getpid()}.pruefung.mjs"
    treiber.write_text(code, encoding="utf-8")
    try:
        lauf = subprocess.run(
            ["node", treiber.name], cwd=FRONTEND, capture_output=True, text=True, timeout=60,
        )
    finally:
        treiber.unlink(missing_ok=True)
    assert lauf.returncode == 0, (lauf.stdout + lauf.stderr)[-3000:]
    return json.loads(lauf.stdout.split("---REPORT---", 1)[1].strip())


# --- Whose logo -------------------------------------------------------------


@needs_node
def test_the_owner_of_the_repository_decides_the_logo_not_a_word_in_the_name():
    """`unsloth` has a logo of its own; a hit of theirs called
    "Mistral-Small-…" used to wear Mistral's, by the family word in its name."""
    antwort = _driver(
        "import { LOGOS, ownerLogo } from './src/lib/logos.js'\n"
        "console.log('---REPORT---' + JSON.stringify({\n"
        "  owner: ownerLogo('unsloth') === LOGOS.unsloth,\n"
        "  upper: ownerLogo('Unsloth') === LOGOS.unsloth,\n"
        "  distinct: LOGOS.unsloth !== LOGOS.mistral,\n"
        "}))\n"
    )
    assert antwort == {"owner": True, "upper": True, "distinct": True}


@needs_node
def test_an_owner_without_a_logo_of_the_house_has_none_and_the_picture_comes_next():
    """The probe against the first one: `LiquidAI` is no key of the logos —
    and a name that is only a property of every object is no key either."""
    antwort = _driver(
        "import { ownerLogo } from './src/lib/logos.js'\n"
        "console.log('---REPORT---' + JSON.stringify([\n"
        "  ownerLogo('LiquidAI'), ownerLogo('TheDrummer'), ownerLogo('constructor'),\n"
        "  ownerLogo('__proto__'), ownerLogo(''), ownerLogo(null), ownerLogo(undefined),\n"
        "]))\n"
    )
    assert antwort == [None] * 7


@needs_node
def test_an_accessory_asks_for_the_picture_of_its_maker_not_of_the_house_repository():
    """The three face and hand detectors lie in the house repository, the
    weights are the author's: the card names the author. Every other card has
    only its repository's owner."""
    antwort = _driver(
        "import { KATALOG_ZUBEHOER } from './src/lib/modellempfehlungen.js'\n"
        "import { avatarOwnerOf } from './src/lib/logos.js'\n"
        "const by = Object.fromEntries(KATALOG_ZUBEHOER.map((k) => [k.id, avatarOwnerOf(k)]))\n"
        "console.log('---REPORT---' + JSON.stringify(by))\n"
    )
    assert antwort["ad-face-n"] == antwort["ad-face-s"] == antwort["ad-hand-n"] == "Bingsu"
    assert "exeterminal" not in antwort.values()
    assert antwort["vae-mse-15"] == "stabilityai"
    assert antwort["lora-lcm-15"] == "latent-consistency"
    assert antwort["lora-multidet-xl"] == "Stableyogi"
    assert all(antwort.values()), antwort


# --- The picture of an owner: asked once, silent when it fails ---------------

_STAND_IN = """
import { writeFileSync, mkdirSync, copyFileSync, readFileSync } from 'node:fs'
import { pathToFileURL } from 'node:url'
import { join } from 'node:path'
const dir = process.argv[2]
mkdirSync(dir, { recursive: true })
writeFileSync(join(dir, 'package.json'), '{"type":"module"}')
copyFileSync('src/lib/logos.js', join(dir, 'logos.js'))
const source = readFileSync('src/lib/ownerPicture.svelte.js', 'utf8').replace('$state({})', '({})')
writeFileSync(join(dir, 'ownerPicture.js'), source)
writeFileSync(join(dir, 'api.js'), `
export const calls = []
export let answer = () => Promise.resolve({ image: 'data:image/webp;base64,AAAA' })
export const setAnswer = (f) => { answer = f }
export const api = { ownerAvatar: (owner) => { calls.push(owner); return answer(owner) } }
`)
const { ownerPicture } = await import(pathToFileURL(join(dir, 'ownerPicture.js')).href)
const { calls, setAnswer } = await import(pathToFileURL(join(dir, 'api.js')).href)
const wait = () => new Promise((r) => setTimeout(r, 20))
const out = {}
%s
console.log('---REPORT---' + JSON.stringify(out))
"""


def _picture(scenario: str, tmp_path: Path) -> dict:
    treiber = FRONTEND / f"picture-{os.getpid()}.pruefung.mjs"
    treiber.write_text(_STAND_IN % scenario, encoding="utf-8")
    try:
        lauf = subprocess.run(
            ["node", treiber.name, str(tmp_path / "mod")],
            cwd=FRONTEND, capture_output=True, text=True, timeout=60,
        )
    finally:
        treiber.unlink(missing_ok=True)
    assert lauf.returncode == 0, (lauf.stdout + lauf.stderr)[-3000:]
    return json.loads(lauf.stdout.split("---REPORT---", 1)[1].strip())


@needs_node
def test_an_owner_with_a_logo_of_the_house_triggers_no_request(tmp_path):
    """The silence probe: `unsloth` has its logo, so nothing is asked, now or
    later."""
    out = _picture(
        "out.first = ownerPicture('unsloth'); await wait(); out.second = ownerPicture('Unsloth');\n"
        "out.calls = calls.slice()\n",
        tmp_path,
    )
    assert out == {"first": None, "second": None, "calls": []}


@needs_node
def test_an_owner_without_a_logo_is_asked_once_and_the_picture_stays(tmp_path):
    out = _picture(
        "out.first = ownerPicture('LiquidAI'); await wait();\n"
        "out.second = ownerPicture('LiquidAI'); out.lower = ownerPicture('liquidai');\n"
        "out.calls = calls.slice()\n",
        tmp_path,
    )
    assert out["first"] is None
    assert out["second"] == out["lower"] == "data:image/webp;base64,AAAA"
    assert out["calls"] == ["LiquidAI"]


@needs_node
def test_a_failed_request_leaves_the_letter_and_is_not_repeated(tmp_path):
    """The service says no, or does not answer: no picture, no throw, no
    second request for the same name."""
    out = _picture(
        "setAnswer(() => Promise.reject(new Error('boom')))\n"
        "out.first = ownerPicture('mradermacher'); await wait();\n"
        "out.second = ownerPicture('mradermacher'); await wait();\n"
        "out.calls = calls.slice()\n",
        tmp_path,
    )
    assert out == {"first": None, "second": None, "calls": ["mradermacher"]}


@needs_node
def test_an_answer_that_is_no_picture_is_not_shown(tmp_path):
    out = _picture(
        "setAnswer(() => Promise.resolve({ image: 'https://evil.example/a.png' }))\n"
        "ownerPicture('someone'); await wait(); out.one = ownerPicture('someone');\n"
        "setAnswer(() => Promise.resolve({}))\n"
        "ownerPicture('other'); await wait(); out.two = ownerPicture('other');\n",
        tmp_path,
    )
    assert out == {"one": None, "two": None}


def test_no_message_comes_from_a_missing_picture():
    quelle = _quelle(LIB / "ownerPicture.svelte.js")
    assert ".catch(() => {})" in quelle
    assert "melde" not in quelle and "zustand" not in quelle


# --- Where the mark is used -------------------------------------------------


def test_the_mark_goes_owner_logo_then_picture_then_letter():
    quelle = _quelle(TEILE / "OwnerMark.svelte")
    assert "const logo = $derived(mark ?? ownerLogo(owner))" in quelle
    assert "const picture = $derived(logo ? null : ownerPicture(owner))" in quelle
    ordnung = [quelle.index(x) for x in ("{#if logo}", "{:else if picture}", "{:else}")]
    assert ordnung == sorted(ordnung)
    # No tile behind it: the mark stands alone.
    stil = quelle.split("<style>", 1)[1]
    assert "background" not in stil


def test_a_hit_wears_the_logo_of_its_owner_and_no_longer_a_word_from_its_name():
    katalog = _quelle(TEILE / "Katalog.svelte")
    assert "<OwnerMark owner={f.anbieter} size={30} />" in katalog
    assert "owner={trefferSeite.anbieter}" in katalog
    assert "modellMarke" not in katalog
    assert 'zeichen="chevron_right"' in katalog and "▸" not in katalog


def test_a_card_and_an_accessory_have_their_logo_without_a_tile():
    karte = _quelle(TEILE / "Modellkarte.svelte")
    assert "<OwnerMark mark={marke} letter={karte.logo} size={30} />" in karte
    assert "owner={avatarOwnerOf(karte)}" in karte
    detail = _quelle(TEILE / "Modelldetail.svelte")
    assert "<OwnerMark mark={marke} {owner} letter={buchstabe} size={30} />" in detail
    for name, quelle in (("Modellkarte", karte), ("Modelldetail", detail)):
        stil = quelle.split("<style>", 1)[1]
        assert ".logo {" not in stil and ".zlogo" not in stil, name


def test_the_hugging_face_mark_is_the_original_without_a_tile_in_every_place():
    katalog = _quelle(TEILE / "Katalog.svelte")
    detail = _quelle(TEILE / "Modelldetail.svelte")
    seite = _quelle(TEILE / "Downloadseite.svelte")
    assert 'width="18" height="18"' in katalog.split('class="abschnitt tafelkopf"', 1)[1].split("</h4>", 1)[0]
    assert 'class="hf-marke" viewBox={LOGOS.huggingface.vb} width="24" height="24"' in katalog
    assert 'viewBox={huggingFace.vb} width="26" height="26"' in detail
    # On the downloads page it is small, in the corner, over the cross it stands above.
    assert 'viewBox={huggingFace.vb} width="14" height="14"' in seite
    # In the detail it has no word beside it: only the tooltip says what it is.
    assert "{t('editor.quelle_hf')}\n        </button>" not in detail


# --- The signs of the cards and rows ----------------------------------------


def test_every_button_of_the_cards_and_rows_is_a_sign_with_a_tooltip():
    # The cards and the file rows draw their state with the one download row.
    for name in ("Modellkarte", "Modelldetail"):
        markup = _quelle(TEILE / f"{name}.svelte").split("</script>", 1)[1].split("<style>", 1)[0]
        assert "<DownloadRow" in markup, name
        # The way back and the Hugging Face mark are the page's own; every
        # other button of a card or a row comes from the download row.
        assert markup.count("<button") == markup.count('class="zurueck"') + markup.count('class="hf"'), name
    quelle = _quelle(TEILE / "DownloadRow.svelte")
    markup = quelle.split("</script>", 1)[1].split("<style>", 1)[0]
    for zeichen in ("download", "kreuz", "haken"):
        assert f'zeichen="{zeichen}"' in markup, zeichen
    # No text button is left: "Download" and "Cancel" are signs.
    assert re.search(r">\s*\{t\('katalog\.(herunterladen|abbrechen)'\)\}\s*</button>", markup) is None
    buttons = re.findall(r"<button class=\"sign-button\".*?<Hauszeichen", markup, re.S)
    assert len(buttons) == 3
    for taste in buttons:
        assert "title={t(" in taste and "aria-label={t(" in taste, taste
    # The downloads page draws its second line with the same download row.
    assert "<DownloadRow" in _quelle(TEILE / "Downloadseite.svelte")
    katalog = _quelle(TEILE / "Katalog.svelte")
    assert 'zeichen="trash"' in katalog
    assert "{t('editor.hf_entfernen')}</button>" not in katalog


def test_a_loading_card_says_only_loaded_of_total_and_the_row_adds_the_speed():
    katalog = _quelle(TEILE / "Katalog.svelte")
    assert "text: fort ? fort.bytes + (mbs ? ' · ' + mbs : '') : ''," in katalog
    karte = _quelle(TEILE / "Modellkarte.svelte")
    assert "fortschritt?.bytes" in karte and "fortschritt?.text" not in karte
    assert "{anteil} %" not in karte.split("</script>", 1)[1].split("<style>", 1)[0]


def test_the_downloaded_word_is_the_one_key_every_reader_shares():
    """`katalog.im_ordner` is also read by the command-line view and the
    phone: one value, one word."""
    de = json.loads((WURZEL / "app" / "locales" / "de.json").read_text(encoding="utf-8"))
    assert de["katalog"]["im_ordner"] == "heruntergeladen"
    for pfad in (
        WURZEL / "cli" / "downloads.py",
        FRONTEND / "src" / "phone" / "catalog" / "CardView.svelte",
    ):
        assert "katalog.im_ordner" in _quelle(pfad), pfad


# --- Sizes and speed with the decimal sign of the language ------------------


@pytest.mark.parametrize("name", ["Katalog", "Modellkarte", "Modelldetail", "Downloadseite"])
def test_no_size_of_the_catalogue_pages_is_cut_with_tofixed(name):
    quelle = _quelle(TEILE / f"{name}.svelte")
    assert "toFixed" not in quelle, name
    if name != "Katalog":
        assert "formatGb(" in quelle, name


def test_the_page_writes_sizes_and_speed_through_the_shared_module():
    katalog = _quelle(TEILE / "Katalog.svelte")
    assert "const gb = (bytes) => formatGb(bytes / 1e9, texte.sprache)" in katalog
    assert "formatNumber(tempo / 1e6, 1, texte.sprache) + ' MB/s'" in katalog
    assert "{formatGb(maschineGb, texte.sprache)} GB" in katalog
    assert "formatNumber(maschineGb" not in katalog
    karte = _quelle(TEILE / "Modellkarte.svelte")
    assert "formatGb(fassung.groesse, texte.sprache)" in karte
    # The sentences about the machine's memory write it the same way, or a
    # window in German says "64,0 GB" in its head and "deine 31.6 GB" on a card.
    assert "{ gb: formatGb(maschineGb, texte.sprache) }" in katalog
    assert "{ gb: formatGb(brauchtMaschine(fassung), texte.sprache) }" in katalog
    assert "{ gb: formatGb(brauchtMaschine(fassung), texte.sprache) }" in karte
    assert "{ gb: maschineGb }" not in katalog


# --- Two columns in the page, the settings list in the sidebar ---------------


def test_the_kinds_and_the_downloads_stand_in_the_page_and_the_sidebar_carries_the_settings_list():
    """The sidebar of the catalogue pages is the list of the settings, as the
    local models carry it; the page's own column shows the kinds."""
    katalog = _quelle(TEILE / "Katalog.svelte")
    liste = katalog.split("{#snippet liste()}", 1)[1].split("{/snippet}", 1)[0]
    assert "<SettingsNav current={dlOffen ? 'downloads' : 'katalog'} />" in liste
    assert "Menuezeile" not in liste and "kindRows" not in liste
    # The two ids the sidebar highlights are rows of the list.
    rows_of_list = _quelle(WURZEL / "frontend" / "src" / "lib" / "einstellungsliste.js")
    assert "id: 'katalog'" in rows_of_list and "id: 'downloads'" in rows_of_list
    # One set of rows, drawn once: small signs and a line before the downloads,
    # in the page.
    assert katalog.count("{#snippet kindRows()}") == 1
    assert katalog.count("{@render kindRows()}") == 1
    assert '<nav class="kinds"' in katalog
    assert "grid-template-columns: 300px minmax(0, 1fr);" in katalog
    rows = katalog.split("{#snippet kindRows()}", 1)[1].split("<Seitenrahmen", 1)[0]
    rows = rows.rsplit("{/snippet}", 1)[0]
    # The downloads row is the last of the column, behind a line.
    assert rows.index('<div class="divider"') < rows.index("onclick={dlOeffnen}")
    markup = katalog.split("</script>", 1)[1].split("<style>", 1)[0]
    # The head carries the catalogue sign in its box and the title as text.
    assert '<Fensterzeichen name="katalog" groesse={22} />' in markup
    assert "Schriftzug" not in katalog


def test_the_downloaded_word_is_the_same_in_both_languages():
    for sprache, wort in (("de", "heruntergeladen"), ("en", "downloaded")):
        katalog = json.loads((WURZEL / "app" / "locales" / f"{sprache}.json").read_text(encoding="utf-8"))
        assert katalog["katalog"]["im_ordner"] == wort, sprache


def test_the_rows_of_the_gallery_share_the_height_of_the_highest_card_and_stretch_no_further():
    katalog = _quelle(TEILE / "Katalog.svelte")
    raster = katalog.split("  .raster {", 1)[1].split("}", 1)[0]
    assert "grid-auto-rows: 1fr;" in raster and "flex: 1;" not in raster
    assert "align-content: start" not in raster
