"""The VAE choice of a picture model lists the tiny autoencoders under a line of
their own, and the studio locks the field of the preview's own one while the
model carries one, in a real browser.

Two pages are built as shipped. The picture server page (on the stub of
``tests/image_window_page.py``, 1500 px) opens a model and its kit: the list of
the VAE field shows the VAE files, then the line "TAE (fast)" ("TAE (schnell)")
with the files of the ``taesd`` folder; a chosen one is kept under its word.
The studio (as in ``tests/test_studio_generate_stays_chrome.py``) draws the
field "Schnell-VAE (TAESD)" with the preview set to "TAE": open while the model's
VAE is a file, locked while it is a tiny autoencoder. Skipped where there is no
Chrome or no node.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path
from unittest import mock
from uuid import uuid4

import pytest

from app import appfenster, image_families, prozessstopp
from tests import image_window_page as harness
from tests import test_studio_generate_stays_chrome as studio_page
from tests.image_window_page import needs_browser, run_cases
from tests.test_image_server_layout_chrome import ENTRY_IMPORTS, ROUTES, SHELL_IMPORTS, SHELL_SCENES

pytestmark = [
    pytest.mark.platforms("darwin", reason="the browser run of the interface is checked on macOS only"),
    needs_browser,
]

ROOT = Path(__file__).resolve().parent.parent
GERMAN = json.loads((ROOT / "app" / "locales" / "de.json").read_text(encoding="utf-8"))
ENGLISH = json.loads((ROOT / "app" / "locales" / "en.json").read_text(encoding="utf-8"))
TAE_PREFIX = "taesd:"

MODEL_ROUTE_WITH_LISTS = (
    "      programm_da: true, bau: 'master-4ff2c8a', standardmodell: '', sizes: {}, restorable: false,\n"
)
LISTS = (
    "      programm_da: true, bau: 'master-4ff2c8a', standardmodell: '', sizes: {}, restorable: false,\n"
    "      vaes: ['ae.safetensors', 'sdxl_vae.safetensors'], taesd_files: ['taesd.safetensors', 'taew2_1.safetensors'],\n"
    "      tae_kinds: { 'taesd.safetensors': 'taesd', 'taew2_1.safetensors': 'taew2_1' },\n"
)

CASES = r"""
const text = (node) => node.textContent.replace(/\s+/g, ' ').trim()
const cards = () => [...document.querySelectorAll('section.abschnitt, section.block')]
// The values block names its model in the choice at its head's left end.
const headOf = (card) => (card.matches('.block') ? text(card.querySelector('.kopf .feld .text')) : text(card.querySelector('.kopf')))
const card = (head) => cards().find((c) => headOf(c) === head)
const file = (name, size) => ({ name, size, collecting_imatrix: false, has_imatrix: false, gguf_type: null, convert_types: [] })
const keptValues = () => backend.calls.filter((c) => c.key === 'bildmodellwerte').map((c) => c.sent)
backend.files = [file('a.safetensors', 6.9e9)]

await show('page')
await wait(1800)
const values = () => card('a.safetensors')
values().querySelector('.kitkopf').click()
await wait(400)
const field = (label) => [...values().querySelectorAll('button[role="combobox"]')].find((b) => b.getAttribute('aria-label') === label)
const openList = async (label) => {
  field(label).click()
  await wait(300)
  return document.querySelector('.klapp [role="listbox"]')
}
const entries = (list) => [...list.children].map((n) => (n.classList.contains('group-name') ? { group: text(n) } : { option: text(n) }))

report.vae = entries(await openList('__VAE__'))
// A tiny autoencoder is chosen like a VAE: the list closes on it.
const list = document.querySelector('.klapp [role="listbox"]')
const tae = [...list.querySelectorAll('[role="option"]')].find((o) => text(o) === 'taew2_1.safetensors')
tae.click()
await wait(300)
report.shown = text(field('__VAE__'))
const save = [...values().querySelectorAll('.kopf .signs button')][1]
report.saveEnabled = !save.disabled
save.click()
await wait(800)
report.kept = keptValues()

// The audio VAE of a video kit stays a list of VAE files: no line of tiny autoencoders there.
report.vaeLists = {
  other: entries(await openList('__VAE__')).filter((e) => e.group).length,
}
"""


@pytest.fixture(scope="module")
def report() -> dict:
    assert MODEL_ROUTE_WITH_LISTS in ROUTES
    # The model of the card is a Wan one: of the two files only the Wan kind is offered.
    routes = ROUTES.replace(MODEL_ROUTE_WITH_LISTS, LISTS).replace("'a.safetensors': 'sdxl'", "'a.safetensors': 'wan'")
    assert "'a.safetensors': 'wan'" in routes
    routes += "  if (path === '/bild/familien') return answer(" + json.dumps(image_families.as_json()) + ")\n"
    shell = harness.SHELL.replace(
        "  import { scene } from './scene.svelte.js'\n", SHELL_IMPORTS + "  import { scene } from './scene.svelte.js'\n"
    ).replace("  {#if scene.show === 'values'}", SHELL_SCENES + "  {#if scene.show === 'values'}").replace(
        "width: 760px", "width: 1180px"
    )
    entry = harness.ENTRY_JS.replace(
        "import '../../src/stil/global.css'\n", "import '../../src/stil/global.css'\n" + ENTRY_IMPORTS
    ).replace("  if (path === '/bild/devices') return answer([])\n", routes + "  if (path === '/bild/devices') return answer([])\n")
    # The values of the model say its family, as the service does.
    entry = entry.replace(
        "  if (path === '/bild/vorgaben') return answer(PRESETS)\n",
        "  if (path === '/bild/vorgaben') return answer({ ...PRESETS, family: 'wan' })\n",
    )
    assert "family: 'wan' })" in entry
    entry = entry.replace("  calls: [],\n  delay: 0,\n}", "  calls: [],\n  delay: 0,\n  files: [],\n  update: false,\n}")
    page = harness.PAGE.replace(
        '<script src="out/entry.js"></script>',
        '<link rel="stylesheet" href="out/exe-ai-terminal-frontend.css">\n<script src="out/entry.js"></script>',
    )
    with (
        mock.patch.object(harness, "SHELL", shell),
        mock.patch.object(harness, "ENTRY_JS", entry),
        mock.patch.object(harness, "PAGE", page),
    ):
        return run_cases(CASES.replace("__VAE__", GERMAN["bild"]["vae"]), limit=240.0, window="1500,3000")


GROUP = GERMAN["bild"]["vae_group_tae"]


def test_the_vae_list_shows_the_files_then_the_line_of_the_tiny_autoencoders_with_theirs(report):
    entries = report["vae"]
    names = [e.get("option") for e in entries if "option" in e]
    assert names[:3] == [GERMAN["bild"]["vae_keins"], "ae.safetensors", "sdxl_vae.safetensors"], entries
    assert names[3:] == ["taew2_1.safetensors"], entries
    assert entries.index({"group": GROUP}) == 3 and sum("group" in e for e in entries) == 1, entries


def test_the_line_has_an_english_wording(report):
    assert (GERMAN["bild"]["vae_group_tae"], ENGLISH["bild"]["vae_group_tae"]) == ("TAE (schnell)", "TAE (fast)")


def test_a_tiny_autoencoder_is_chosen_and_kept_under_its_word(report):
    assert report["shown"] == "taew2_1.safetensors", report
    assert report["saveEnabled"] is True, report
    assert report["kept"] and report["kept"][-1]["a.safetensors"]["vae"] == f"{TAE_PREFIX}taew2_1.safetensors", report["kept"]


# --- The studio ---

STUDIO_SHELL = studio_page.SHELL.replace(
    "  import StudioBasics from '../../src/teile/StudioBasics.svelte'\n",
    "  import StudioBasics from '../../src/teile/StudioBasics.svelte'\n"
    "  import StudioDetails from '../../src/teile/StudioDetails.svelte'\n",
).replace(
    "<div style=\"flex: 1; position: relative;\"><ImageStudio zeichnen={draw} /></div>",
    "<div style=\"flex: 1; position: relative;\"><ImageStudio zeichnen={draw} /></div>\n"
    "  <div style=\"width: 420px; flex: none; position: relative; overflow: auto;\"><StudioDetails /></div>",
)
assert "StudioDetails />" in STUDIO_SHELL

STUDIO_ANSWERS = (
    "  '/bild/vorgaben': { family: '', breite: 1024, hoehe: 1024, schritte: 8, cfg: 1 },\n"
)


def _studio_entry(vae_part: str) -> str:
    answers = (
        "  '/bild/vorgaben': { family: '', breite: 1024, hoehe: 1024, schritte: 8, cfg: 1, parts: { %s } },\n" % vae_part
    )
    entry = studio_page.ENTRY_JS.replace(STUDIO_ANSWERS, answers)
    return entry.replace(
        "loras: [], sizes: {},", "loras: [], sizes: {}, taesd_files: ['taew2_1.safetensors'],"
    )


STUDIO_CASES = r"""
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
const { werte, auswahl } = window.__studio
const report = {}
for (let k = 0; k < 100 && !document.querySelector('.modeplace .mode'); k += 1) await wait(100)
await wait(800)
// This page holds no catalogue: a label stands as its key.
const unfold = [...document.querySelectorAll('button.klappe')].find((b) => b.textContent.trim() === 'bild.gruppe_feintuning')
unfold.click()
await wait(300)
werte.live_preview = 'tae'
await wait(500)
const field = () => document.querySelector('button[id$="-taesd"]')
report.found = Boolean(field())
report.locked = field() ? field().disabled : null
report.flag = auswahl.vae
document.title = 'open'
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""


@pytest.fixture(scope="module")
def studio():
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    frontend = ROOT / "frontend"
    folder = frontend / "node_modules" / f".harness-tae-decoder-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(STUDIO_SHELL, encoding="utf-8")
        (folder / "vite.config.js").write_text(studio_page.VITE_CONFIG, encoding="utf-8")
        (folder / "measure.html").write_text(studio_page.PAGE % {"cases": STUDIO_CASES}, encoding="utf-8")

        def measure(vae_part: str, name: str) -> dict:
            (folder / "entry.js").write_text(
                _studio_entry(vae_part) % {"global": "../../src/stil/global.css", "studio": "../../src/lib/studio.svelte.js"},
                encoding="utf-8",
            )
            build = subprocess.run(
                [shutil.which("vite", path=str(frontend / "node_modules" / ".bin")), "build", "--config", "vite.config.js"],
                cwd=folder, capture_output=True, text=True, timeout=240,
            )
            assert build.returncode == 0, (build.stdout + build.stderr)[-2000:]
            port = studio_page._free_port()
            browser = subprocess.Popen(
                [
                    program, "--headless=new", "--no-first-run", "--disable-background-networking",
                    "--allow-file-access-from-files", "--window-size=1920,1080",
                    f"--remote-debugging-port={port}", f"--user-data-dir={folder / ('profile-' + name)}",
                    (folder / "measure.html").as_uri() + f"?scenario={name}",
                ],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
            )
            try:
                return asyncio.run(studio_page._drive(port))
            finally:
                prozessstopp.beenden(browser, frist=5)

        yield measure
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_the_studio_field_of_the_previews_own_autoencoder_is_locked_while_the_model_carries_one(studio):
    answer = studio(f"vae: '{TAE_PREFIX}taew2_1.safetensors'", "locked")
    assert answer == {"found": True, "locked": True, "flag": f"{TAE_PREFIX}taew2_1.safetensors"}, answer


def test_silence_with_a_vae_or_none_the_field_stays_open(studio):
    with_vae = studio("vae: 'ae.safetensors'", "vae")
    without = studio("", "none")
    for answer in (with_vae, without):
        assert answer["found"] is True and answer["locked"] is False, answer
