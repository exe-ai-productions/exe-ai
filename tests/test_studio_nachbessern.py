"""The studio's "Repair faces" and "Upscale" never draw with a word of the
surface, and "Upscale" has a model of its own.

With the prompt bar empty, the faces of a picture are redone with the prompt
the program kept for that picture. Where it kept none — a picture that was
uploaded — nothing is drawn and the studio says the prompt is missing; the
menu's own word used to go out as the prompt, drew along, and stood in the
chat and in the picture's infos.

Upscaling reads no prompt: the new picture keeps the one the program kept
for the original, otherwise the bar's, otherwise none — and it is enlarged
all the same. The model it enlarges with is the one chosen in the row
"Upscaler", apart from the highres pass's own.

Run rather than read: the studio's module for what "···" does with a picture
is compiled with the Svelte compiler (it uses runes) and run in node; the
modules around it are stand-ins that record what they are asked.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# The fixtures of the route tests: a fake picture folder, a model, and a mode
# run on a finished picture.
from tests.test_bild_lauf_api import _info, bild_senden, mode_run  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
LIB = FRONTEND / "src/lib"

needs_node = pytest.mark.skipif(
    shutil.which("node") is None or not (FRONTEND / "node_modules").is_dir(),
    reason="no Node or no frontend dependencies on this machine",
)

STUBS = """
export const said = []
export const drawn = []
export const asked = []
export const answers = { kept: {} }
export const werte = {
  prompt: '', ad_modell: 'face_yolov8n.pt', hires_upscaler: 'ESRGAN_4x', upscale_model: '',
}
export const listen = { upscalers: ['ESRGAN_4x'] }
export const auswahl = {}
export const chatanzeige = { chatId: 'chat-1' }
export const emptyArea = () => {}
export const familie = () => null
export const pictureMissing = () => false
export const startbildWaehlen = () => {}
export const melde = (text, kind) => said.push([text, kind ?? ''])
export const t = (key) => key
export const studioZeichnen = (wish) => { drawn.push(wish) }
export const api = {
  drawnWith: async (name) => {
    asked.push(name)
    if (answers.kept instanceof Error) throw answers.kept
    if (typeof answers.hook === 'function') answers.hook()
    return answers.kept
  },
  pictureInfo: async () => ({}),
  bildBlob: async () => null,
}
"""

DRIVER = """
import { compileModule } from 'svelte/compiler'
import { readFileSync, writeFileSync } from 'fs'
const LEAVE = ['api.js', 'chatanzeige.svelte.js', 'studio.svelte.js', 'studiozeichnen.svelte.js',
  'texte.svelte.js', 'zustand.svelte.js']
let code = compileModule(
  readFileSync(%(lib)r + '/studiobilder.svelte.js', 'utf-8'),
  { filename: 'studiobilder.svelte.js', generate: 'client' },
).js.code
for (const other of LEAVE) code = code.replaceAll(`from './${other}'`, "from './nachbessern.stubs.mjs'")
writeFileSync('nachbessern.studiobilder.mjs', code)
const stubs = await import('./nachbessern.stubs.mjs')
const pictures = await import('./nachbessern.studiobilder.mjs')
const { said, drawn, asked, answers, werte, chatanzeige, listen } = stubs
const reset = () => {
  said.length = 0; drawn.length = 0; asked.length = 0
  answers.kept = {}; answers.hook = null
  werte.prompt = ''; werte.ad_modell = 'face_yolov8n.pt'
  werte.hires_upscaler = 'ESRGAN_4x'; werte.upscale_model = ''
  listen.upscalers = ['ESRGAN_4x']
  chatanzeige.chatId = 'chat-1'
}
const report = await (async () => {
%(scenario)s
})()
console.log('---REPORT---' + JSON.stringify(report))
process.exit(0)
"""


def _run(scenario: str) -> dict:
    files = {
        FRONTEND / "nachbessern.stubs.mjs": STUBS,
        FRONTEND / "nachbessern.driver.mjs": DRIVER % {"lib": str(LIB), "scenario": scenario},
    }
    for path, content in files.items():
        path.write_text(content, encoding="utf-8")
    try:
        done = subprocess.run(
            ["node", "nachbessern.driver.mjs"], cwd=FRONTEND, capture_output=True, text=True, timeout=120,
        )
    finally:
        for path in [*files, FRONTEND / "nachbessern.studiobilder.mjs"]:
            path.unlink(missing_ok=True)
    assert done.returncode == 0, (done.stdout + done.stderr)[-3000:]
    mark = "---REPORT---"
    assert mark in done.stdout, done.stdout[-3000:]
    return json.loads(done.stdout.split(mark, 1)[1].strip())


@needs_node
def test_an_empty_bar_draws_with_the_prompt_kept_for_the_picture():
    """Falls over without the fix: the menu's own word goes out as the prompt."""
    report = _run("""
    reset()
    answers.kept = { prompt: 'a red car', modell: 'm.safetensors' }
    await pictures.nachbessern('car.png')
    return { drawn, asked, said }
    """)
    assert report["asked"] == ["car.png"]
    assert report["drawn"] == [
        {"mode": "adetailer", "startbild": "car.png", "maske": None, "prompt": "a red car"}
    ]
    assert report["said"] == []


@needs_node
@pytest.mark.parametrize("kept", ["{}", "{ prompt: '   ' }", "{ modell: 'm.safetensors' }", "new Error('no answer')"])
def test_a_picture_with_no_kept_prompt_draws_nothing_and_says_so(kept):
    """An uploaded picture: nothing kept, an empty answer, an answer without a
    prompt, a question that fails. Never a word of the surface as the prompt."""
    report = _run(f"""
    reset()
    answers.kept = {kept}
    await pictures.nachbessern('uploaded.png')
    return {{ drawn, said }}
    """)
    assert report["drawn"] == []
    assert report["said"] == [["studio.no_prompt", "hinweis"]]


@needs_node
def test_silence_the_text_of_the_bar_goes_as_it_stands_and_nothing_is_asked():
    report = _run("""
    reset()
    werte.prompt = '  a blue house  '
    answers.kept = { prompt: 'a red car' }
    await pictures.nachbessern('car.png')
    return { drawn, asked, said }
    """)
    assert report["asked"] == []
    assert report["drawn"] == [
        {"mode": "adetailer", "startbild": "car.png", "maske": None, "prompt": "a blue house"}
    ]
    assert report["said"] == []


@needs_node
def test_silence_without_a_face_model_the_old_message_stands_and_nothing_is_asked():
    report = _run("""
    reset()
    werte.ad_modell = ''
    answers.kept = { prompt: 'a red car' }
    await pictures.nachbessern('car.png')
    return { drawn, asked, said }
    """)
    assert report["asked"] == [] and report["drawn"] == []
    assert report["said"] == [["bild.modus_unvollstaendig", "fehler"]]


@needs_node
def test_a_chat_opened_while_the_question_is_on_its_way_changes_nothing():
    """The studio belongs to no chat: the question's answer is drawn from
    whichever chat is open."""
    report = _run("""
    reset()
    answers.kept = { prompt: 'a red car' }
    answers.hook = () => { chatanzeige.chatId = 'chat-2' }
    await pictures.nachbessern('car.png')
    return { drawn, said }
    """)
    assert [wish["prompt"] for wish in report["drawn"]] == ["a red car"] and report["said"] == []


@needs_node
def test_upscaling_enlarges_with_the_model_of_its_own_row_and_not_the_highres_one():
    """Falls over without the fix: the highres pass's choice was taken."""
    report = _run("""
    reset()
    listen.upscalers = ['a.pth', 'b.pth']
    werte.upscale_model = 'b.pth'
    werte.hires_upscaler = 'a.pth'
    answers.kept = { prompt: 'a red car' }
    await pictures.hochskalieren('car.png')
    return { drawn }
    """)
    assert [wish["upscale_model"] for wish in report["drawn"]] == ["b.pth"]


@needs_node
@pytest.mark.parametrize("chosen", ["''", "'gone.pth'"])
def test_a_model_not_chosen_or_no_longer_in_the_folder_is_the_first_of_the_folder(chosen):
    """The row shows the first file then, and that is the one that is used."""
    report = _run(f"""
    reset()
    listen.upscalers = ['a.pth', 'b.pth']
    werte.upscale_model = {chosen}
    werte.hires_upscaler = 'b.pth'
    answers.kept = {{ prompt: 'a red car' }}
    await pictures.hochskalieren('car.png')
    return {{ drawn }}
    """)
    assert [wish["upscale_model"] for wish in report["drawn"]] == ["a.pth"]


@needs_node
def test_upscaling_with_an_empty_folder_asks_nothing_and_says_so():
    report = _run("""
    reset()
    listen.upscalers = []
    answers.kept = { prompt: 'a red car' }
    await pictures.hochskalieren('car.png')
    return { drawn, asked, said }
    """)
    assert report["drawn"] == [] and report["asked"] == []
    assert report["said"] == [["bild.modus_unvollstaendig", "fehler"]]


@pytest.mark.parametrize(
    ("bar", "kept", "sent"),
    [
        ("", "{ prompt: 'a red car' }", "a red car"),
        ("a blue house", "{ prompt: 'a red car' }", "a red car"),
        ("a blue house", "{}", "a blue house"),
        ("", "{ prompt: '   ' }", ""),
        ("", "{}", ""),
        ("", "new Error('no answer')", ""),
    ],
)
@needs_node
def test_upscaling_sends_the_kept_prompt_before_the_bar_and_never_a_word_of_the_surface(bar, kept, sent):
    """Falls over without the fix: the menu's own word went out for an empty
    bar, and the bar's text before the prompt the picture was drawn with."""
    report = _run(f"""
    reset()
    werte.prompt = {bar!r}
    answers.kept = {kept}
    await pictures.hochskalieren('car.png')
    return {{ drawn, asked, said }}
    """)
    assert report["asked"] == ["car.png"]
    assert report["said"] == []
    assert report["drawn"] == [{
        "mode": "upscale", "startbild": "car.png", "maske": None,
        "upscale_model": "ESRGAN_4x", "prompt": sent,
    }]


@needs_node
def test_a_chat_opened_while_the_question_for_the_upscale_is_on_its_way_changes_nothing():
    report = _run("""
    reset()
    answers.kept = { prompt: 'a red car' }
    answers.hook = () => { chatanzeige.chatId = 'chat-2' }
    await pictures.hochskalieren('car.png')
    return { drawn, said }
    """)
    assert [wish["prompt"] for wish in report["drawn"]] == ["a red car"] and report["said"] == []


def _upscaling_section() -> str:
    source = (FRONTEND / "src/teile/StudioDetails.svelte").read_text(encoding="utf-8")
    return source.split("t('bild.gruppe_upscaling')", 1)[1].split("t('bild.gruppe_feintuning')", 1)[0]


def test_the_row_upscaler_stands_above_the_highres_switch_and_is_always_there():
    """The row is the model "Upscale" enlarges with: not behind the highres
    switch, and only the files of the folder (no built-in names — the
    enlarging needs a file)."""
    section = _upscaling_section()
    row = section.index("data-suche={t('bild.upscaler')}")
    highres = section.index("data-suche={t('bild.hires')}")
    assert row < highres
    # Nothing that opens a condition lies between the section's start and the row.
    assert "{#if" not in section[:row]
    own = section[row:highres]
    assert "upscalerFeste" not in own
    assert "bind:wert={upscaleAnzeige, upscaleSetzen}" in own


def test_silence_the_highres_upscaler_row_keeps_its_condition_and_its_built_in_names():
    section = _upscaling_section()
    row = section.index("data-suche={t('bild.hires_upscaler')}")
    # It stays inside the part that shows with the highres switch on.
    assert section.index("{#if hires}") < row
    after = section[row:]
    assert "bind:wert={werte.hires_upscaler}" in after
    assert "listen.upscalerFeste" in after


# --- The values of an enlarged picture are its original's --------------------


def test_an_enlarged_picture_keeps_the_values_of_its_original(
    mode_run, bild_senden, client: TestClient, chat_id,  # noqa: F811
):
    """The new picture names the values its original was kept with — model,
    size, steps, CFG, seed, prompt — not the route's defaults of 512 x 512,
    20 steps and CFG 7 and not the studio's model."""
    original = bild_senden(
        chat_id, prompt="a lighthouse", negativ="fog", breite=1024, hoehe=1024, schritte=9,
        cfg=1.0, seed=5, sampler="euler",
    )
    kept = _info(client, original["bild"])
    assert (kept["breite"], kept["schritte"], kept["cfg"], kept["seed"]) == (1024, 9, 1.0, 5)
    enlarged = bild_senden(
        chat_id, prompt="a lighthouse", startbild=original["bild"], mode="upscale",
        upscale_model="big.pth", frage_erstellen=False,
    )
    assert _info(client, enlarged["bild"]) == kept


def test_an_enlarged_picture_without_kept_values_has_only_its_prompt(
    mode_run, bild_senden, client: TestClient, chat_id,  # noqa: F811
):
    """Silence: an original nothing is kept for (one that was uploaded) gives
    its enlargement no value of the route — the prompt of the bar alone, or
    nothing."""
    mode_run(chat_id, "upscale")
    with_prompt = bild_senden(
        chat_id, prompt="a red car", startbild="finished.png", mode="upscale",
        upscale_model="big.pth", frage_erstellen=False,
    )
    assert _info(client, with_prompt["bild"]) == {"prompt": "a red car"}
    without = bild_senden(
        chat_id, prompt="", startbild="finished.png", mode="upscale",
        upscale_model="big.pth", frage_erstellen=False,
    )
    assert _info(client, without["bild"]) == {}


def test_a_normally_drawn_picture_keeps_its_own_values(
    bild_senden, client: TestClient, chat_id,  # noqa: F811
):
    """Silence: only an enlarging takes its values from an original."""
    first = bild_senden(chat_id, prompt="a harbour", breite=768, hoehe=512, schritte=6, seed=3)
    second = bild_senden(
        chat_id, prompt="a ship", breite=640, hoehe=640, schritte=12, seed=4,
        startbild=first["bild"], staerke=0.5,
    )
    kept = _info(client, second["bild"])
    assert (kept["prompt"], kept["breite"], kept["schritte"], kept["seed"]) == ("a ship", 640, 12, 4)

