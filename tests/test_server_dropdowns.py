"""The server window's "Advanced" card: the KV cache and flash attention as
dropdowns, the chat template as a dropdown with its pencil and its folder.

The command line each choice makes is checked on its own; the real window
parts (`Serverregler`, `ChatTemplateRow`) are built as shipped and clicked in
headless Chrome (tests/preview_harness.py).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from app.feineinstellungen import Feineinstellungen, flags
from tests import preview_harness as harness

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
ENGLISH = json.loads((ROOT / "app" / "locales" / "en.json").read_text(encoding="utf-8"))["modell"]

needs_browser = [
    pytest.mark.platforms("darwin", reason="the browser run of the interface is checked on macOS only"),
    pytest.mark.skipif(
        shutil.which("node") is None or not (FRONTEND / "node_modules" / "vite").exists(),
        reason="no node or no frontend dependencies on this machine",
    ),
]


# --- The command line --------------------------------------------------------------


@pytest.mark.parametrize("stufe", ["q8_0", "q5_0", "q4_0"])
def test_a_smaller_cache_goes_to_the_engine_for_k_and_v_together(stufe: str):
    # As a stored choice arrives: through the clamp, which must let it pass.
    zeile = flags(Feineinstellungen.aus_daten({"kv_cache": stufe}))
    assert zeile == ["--cache-type-k", stufe, "--cache-type-v", stufe]


@pytest.mark.parametrize("wert", ["on", "off"])
def test_flash_attention_on_and_off_are_said_and_auto_is_not(wert: str):
    assert flags(Feineinstellungen.aus_daten({"flash_attention": wert})) == ["--flash-attn", wert]
    assert "--flash-attn" not in flags(Feineinstellungen(flash_attention="auto"))


def test_the_five_bit_cache_with_flash_on_says_both():
    zeile = flags(Feineinstellungen.aus_daten({"kv_cache": "q5_0", "flash_attention": "on"}))
    assert zeile == ["--cache-type-k", "q5_0", "--cache-type-v", "q5_0", "--flash-attn", "on"]


@pytest.mark.parametrize("stufe", ["q8_0", "q5_0", "q4_0"])
def test_off_with_a_smaller_cache_is_refused_before_it_is_a_command(stufe: str):
    """The pair the engine cannot start with never reaches it: the stored
    choice is brought back to Auto."""
    einstellung = Feineinstellungen.aus_daten({"kv_cache": stufe, "flash_attention": "off"})
    assert einstellung.flash_attention == "auto"
    assert "off" not in flags(einstellung)


def test_the_template_copy_goes_to_the_engine_while_it_is_there(tmp_path: Path):
    kopie = tmp_path / "m.gguf.jinja"
    kopie.write_text("x", encoding="utf-8")
    einstellung = Feineinstellungen.aus_daten({"chat_template": "file", "chat_template_file": str(kopie)})
    assert flags(einstellung) == ["--chat-template-file", str(kopie)]
    kopie.unlink()
    assert flags(einstellung) == [], "a path that has gone would stop the engine from starting"


def test_the_models_own_template_says_nothing_even_with_a_path_standing(tmp_path: Path):
    kopie = tmp_path / "m.gguf.jinja"
    kopie.write_text("x", encoding="utf-8")
    assert flags(Feineinstellungen.aus_daten({"chat_template": "model", "chat_template_file": str(kopie)})) == []
    assert flags(Feineinstellungen.aus_daten({"chat_template": "erfunden"})) == []


def test_silence_the_shipped_choices_make_the_command_they_always_made():
    assert flags(Feineinstellungen()) == []
    assert flags(Feineinstellungen.aus_daten({})) == flags(None) == []
    assert Feineinstellungen().als_daten()["chat_template"] == "model"


# --- The window parts, clicked ------------------------------------------------------

SHELL = """<script>
  import Serverregler from '../../src/teile/Serverregler.svelte'
  import ChatTemplateRow from '../../src/teile/ChatTemplateRow.svelte'

  let fein = $state({ kv_cache: 'f16', flash_attention: 'auto', chat_template: 'model', chat_template_file: '',
                      moe_auf_cpu: false, festnageln: false, kv_unified: true, idle_minutes: null })
  let vorladen = $state(true)
  let parallel = $state(null)
  let port = $state(8080)
  const gesehen = []
  window.__fein = () => ({ ...fein })
  window.__gesehen = gesehen
  window.__setze = (name, wert) => { fein[name] = wert }
</script>

<div id="karte" style="width: 560px; padding: 16px;">
  <Serverregler kennung="t" teil="fein" bind:fein bind:vorladen bind:parallel bind:port idle={null} />
</div>
<div id="vorlage" style="width: 560px; padding: 16px;">
  <ChatTemplateRow modell="m.gguf" bind:wert={fein.chat_template}
                    onchoose={(neu) => gesehen.push(['choose', neu])}
                    onedit={() => gesehen.push(['edit'])}
                    onreveal={() => gesehen.push(['reveal'])} />
</div>
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import '../../src/stil/global.css'
import '../../src/stil/tiles.css'
import english from '../../../app/locales/en.json'
import { texte } from '../../src/lib/texte.svelte.js'

window.__errors = []
window.addEventListener('error', (e) => window.__errors.push(String(e.message)))
window.addEventListener('unhandledrejection', (e) => window.__errors.push(String(e.reason && (e.reason.stack || e.reason.message) || e.reason)))
texte.sprache = 'en'
texte.katalog = english
mount(Shell, { target: document.getElementById('wurzel') })
"""

CASES = r"""
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
await wait(500)
const report = {}
const options = () => [...document.querySelectorAll('.klapp [role=option]')]
const textOf = (o) => o.textContent.trim()
const open = async (selector) => { document.querySelector(selector).click(); await wait(250) }
const pick = async (selector, index) => { await open(selector); options()[index].click(); await wait(250) }
const field = (selector) => document.querySelector(selector).textContent.trim()

// The cache.
await open('#t-kv')
report.kvList = options().map(textOf)
options()[0].click()
await wait(200)
await pick('#t-kv', 2)
report.kvFive = { fein: window.__fein().kv_cache, shown: field('#t-kv') }

// Flash attention: "off" stands in the list but is locked while the cache is smaller.
await open('#t-flash')
report.flashList = options().map(textOf)
report.flashLocked = options().map((o) => o.getAttribute('aria-disabled') === 'true')
options()[2].click()
await wait(250)
report.offTried = window.__fein().flash_attention
options()[0].click()
await wait(100)
await pick('#t-flash', 1)
report.flashOn = window.__fein().flash_attention

// Back to the 16-bit cache: "off" can be taken now; a smaller cache takes it back to Auto.
await pick('#t-kv', 0)
report.kvBack = window.__fein().kv_cache
await pick('#t-flash', 2)
report.flashOff = window.__fein().flash_attention
await pick('#t-kv', 3)
report.afterSmaller = { kv: window.__fein().kv_cache, flash: window.__fein().flash_attention, shown: field('#t-flash') }

// The chat template row.
const row = document.querySelector('#vorlage')
report.template = {
  name: row.querySelector('.name').textContent.trim(),
  file: row.querySelector('.file').textContent.trim(),
  buttons: [...row.querySelectorAll('button.rowsign')].map((b) => b.getAttribute('aria-label')),
  shown: row.querySelector('.feld').textContent.trim(),
}
row.querySelector('.feld').click()
await wait(250)
report.template.list = options().map(textOf)
options()[1].click()
await wait(250)
report.template.chosen = window.__fein().chat_template
const signs = row.querySelectorAll('button.rowsign')
signs[0].click()
signs[1].click()
await wait(100)
report.template.seen = window.__gesehen
report.errors = window.__errors.slice(0, 6)
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""


@pytest.fixture(scope="module")
def report() -> dict:
    return harness.run_page(SHELL, ENTRY_JS, CASES, {})


def browser(test):
    for mark in needs_browser:
        test = mark(test)
    return test


@browser
def test_the_cache_dropdown_offers_four_stages_and_takes_the_one_chosen(report):
    wanted = [ENGLISH[k] for k in ("kv_f16", "kv_q8", "kv_q5", "kv_q4")]
    assert report["kvList"] == wanted, report["kvList"]
    assert report["kvFive"] == {"fein": "q5_0", "shown": ENGLISH["kv_q5"]}


@browser
def test_flash_attention_offers_auto_on_and_off_and_off_is_locked_with_a_smaller_cache(report):
    assert report["flashList"] == [ENGLISH["flash_auto"], ENGLISH["flash_an"], ENGLISH["flash_inaktiv"]]
    assert report["flashLocked"] == [False, False, True], report["flashLocked"]
    assert report["offTried"] == "auto", "a locked entry cannot be taken"
    assert report["flashOn"] == "on"


@browser
def test_off_can_be_taken_with_the_16_bit_cache_and_a_smaller_cache_takes_it_back_to_auto(report):
    assert report["kvBack"] == "f16" and report["flashOff"] == "off"
    assert report["afterSmaller"] == {"kv": "q4_0", "flash": "auto", "shown": ENGLISH["flash_auto"]}


@browser
def test_the_chat_template_row_names_the_model_and_has_its_dropdown_pencil_and_folder(report):
    row = report["template"]
    assert row["name"] == ENGLISH["feld_chat_vorlage"] and row["file"] == "m.gguf"
    assert row["buttons"] == [ENGLISH["vorlage_bearbeiten"], ENGLISH["vorlage_zeigen"]]
    assert row["shown"] == ENGLISH["vorlage_jinja"]
    assert row["list"] == [ENGLISH["vorlage_jinja"], ENGLISH["vorlage_datei"]]
    assert row["chosen"] == "file"
    assert row["seen"] == [["choose", "file"], ["edit"], ["reveal"]], row["seen"]


@browser
def test_nothing_was_refused_or_failed_while_drawing(report):
    assert report["errors"] == [], report["errors"]


def test_the_pages_stand_on_the_one_row_and_the_old_switch_is_gone():
    teile = FRONTEND / "src" / "teile"
    regler = (teile / "Serverregler.svelte").read_text(encoding="utf-8")
    assert "feld_kv_wert" not in regler and "fein.kv_cache === 'q8_0'" not in regler
    for datei, route in (("Modellserver.svelte", "runnerChatTemplate"), ("Agentserver.svelte", "agentenmodellChatTemplate")):
        quelle = (teile / datei).read_text(encoding="utf-8")
        assert "<ChatTemplateRow" in quelle and f"api.{route}Edit" in quelle, datei
        assert f"api.{route}Reveal" in quelle, datei
        assert "KV_ALT" not in quelle and "=== 'q4_0'" not in quelle, datei
