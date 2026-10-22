"""The maker marks of the picture and video models: the delivered vectors are
in `frontend/src/lib/logos.js`, each picture family and each catalogue card of
a maker with a vector wears it, and a family without one keeps its letter.

Run rather than read: the modules are loaded by Node and asked, the way the
list, the choice and the catalogue ask them.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from app import image_families

WURZEL = Path(__file__).resolve().parent.parent
FRONTEND = WURZEL / "frontend"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")

# Family -> the key of the mark of its maker.
WITH_MARK = {
    "sd15": "stabilityai", "sd2": "stabilityai", "sdxl": "stabilityai", "sd3": "stabilityai",
    "sdxl_pix2pix": "stabilityai",
    "flux": "black-forest-labs", "flux2": "black-forest-labs", "flux2_klein": "black-forest-labs",
    "flux3_klein": "black-forest-labs",
    "sdxs": "xiaomi", "pid": "nvidia", "moss_image": "openmoss-team", "iris": "speridlabs",
    "zimage": "tongyi-mai", "krea2": "krea", "sensenova_u1": "sensenova", "longcat": "meituan-longcat",
    "ernie": "baidu", "boogu": "boogu", "ideogram4": "ideogram-ai", "pixart": "pixart-alpha",
    "ltx": "lightricks", "minimax_h3": "minimaxai", "hunyuan_video": "tencent", "lingbot_video": "robbyant",
    "wan": "wan-ai", "wan22_i2v": "wan-ai", "wan22_ti2v": "wan-ai", "wan22_s2v": "wan-ai",
    "ovis": "aidc-ai",
    "lens": "microsoft", "mage_flow": "microsoft",
}
WITHOUT_MARK = [
    "sd15_pix2pix", "hidream_o1", "chroma", "chroma_radiance", "llada_image", "minit2i", "sefi", "anima",
]
NEW_OWNERS = [
    "stabilityai", "black-forest-labs", "krea", "lightricks", "tencent", "minimaxai", "baidu",
    "meituan-longcat", "ideogram-ai", "sensenova", "tongyi-mai", "openmoss-team", "speridlabs", "boogu",
    "pixart-alpha", "robbyant", "purplesmartai", "stableyogi", "rundiffusion", "wan-ai", "aidc-ai",
]
# Cards of a maker with a vector -> the mark they name.
CARD_MARKS = {
    "pony-v6-xl": "purplesmartai", "flux2-klein-4b": "black-forest-labs", "z-image-turbo": "tongyi-mai",
    "krea-2-turbo": "krea", "ltx-23": "lightricks", "minimax-h3": "minimaxai",
    "hunyuanvideo-15": "tencent", "wan21-t2v-13b": "wan-ai", "wan21-i2v-14b": "wan-ai",
    "wan22-ti2v-5b": "wan-ai", "wan22-t2v-a14b": "wan-ai", "wan22-i2v-a14b": "wan-ai",
    "wan22-s2v-14b": "wan-ai", "moss-image-sft": "openmoss-team", "lingbot-video-13b": "robbyant",
}


def _ask(code: str) -> object:
    driver = FRONTEND / f"marks-{os.getpid()}.pruefung.mjs"
    driver.write_text(
        "import { LOGOS, ownerLogo } from './src/lib/logos.js'\n"
        "import { bildFamilienMarke, modellMarke } from './src/lib/anbieterzeichen.js'\n"
        "import { KATALOG_BILD, KATALOG_VIDEO } from './src/lib/modellempfehlungen.js'\n"
        + code,
        encoding="utf-8",
    )
    try:
        run = subprocess.run(["node", driver.name], cwd=FRONTEND, capture_output=True, text=True, timeout=60)
    finally:
        driver.unlink(missing_ok=True)
    assert run.returncode == 0, (run.stdout + run.stderr)[-3000:]
    return json.loads(run.stdout.split("---REPORT---", 1)[1].strip())


@needs_node
def test_each_family_of_a_maker_with_a_vector_wears_the_makers_mark():
    answer = _ask(
        f"const wanted = {json.dumps(WITH_MARK)}\n"
        "const bad = Object.entries(wanted).filter(([name, key]) => bildFamilienMarke(name, '') !== LOGOS[key])\n"
        "console.log('---REPORT---' + JSON.stringify(bad))\n"
    )
    assert answer == []


@needs_node
def test_a_family_without_a_vector_keeps_its_letter():
    labels = {f.name: f.label for f in image_families.FAMILIES}
    answer = _ask(
        f"const labels = {json.dumps({name: labels[name] for name in WITHOUT_MARK})}\n"
        "const marks = Object.entries(labels).map(([name, label]) => [name, bildFamilienMarke(name, label)])\n"
        "console.log('---REPORT---' + JSON.stringify(marks))\n"
    )
    assert answer == [[name, None] for name in WITHOUT_MARK]


def test_every_family_is_either_listed_here_or_known_to_have_a_mark_by_its_label():
    """The list above names real families, so a renamed family fails here."""
    names = {f.name for f in image_families.FAMILIES}
    assert set(WITH_MARK) <= names
    assert set(WITHOUT_MARK) <= names


@needs_node
def test_each_catalogue_card_of_a_maker_with_a_vector_names_the_mark():
    answer = _ask(
        f"const wanted = {json.dumps(CARD_MARKS)}\n"
        "const cards = [...KATALOG_BILD, ...KATALOG_VIDEO]\n"
        "const bad = Object.entries(wanted).filter(([id, key]) => cards.find((c) => c.id === id)?.marke !== key)\n"
        "console.log('---REPORT---' + JSON.stringify(bad))\n"
    )
    assert answer == []


@needs_node
def test_the_owner_of_a_repository_finds_each_new_mark():
    answer = _ask(
        f"const owners = {json.dumps(NEW_OWNERS)}\n"
        "const bad = owners.filter((o) => ownerLogo(o) === null || ownerLogo(o.toUpperCase()) !== ownerLogo(o))\n"
        "console.log('---REPORT---' + JSON.stringify(bad))\n"
    )
    assert answer == []


@needs_node
def test_a_hit_of_a_new_maker_wears_the_makers_mark_and_the_old_hits_stay():
    answer = _ask(
        "console.log('---REPORT---' + JSON.stringify({\n"
        "  krea: modellMarke('Krea-2-Turbo', 'krea') === LOGOS.krea,\n"
        "  wan: modellMarke('Wan2.2-T2V', 'Wan-AI') === LOGOS['wan-ai'],\n"
        "  qwen: modellMarke('Qwen3-8B-GGUF', 'unsloth') === LOGOS.qwen,\n"
        "  gemma: modellMarke('gemma-4-12b-it', 'unsloth') === LOGOS.google,\n"
        "  nobody: modellMarke('Korea-Chat', 'someone') === null,\n"
        "}))\n"
    )
    assert answer == {"krea": True, "wan": True, "qwen": True, "gemma": True, "nobody": True}


@needs_node
def test_the_new_marks_hold_no_script_style_or_raster_and_keep_their_ids_apart():
    answer = _ask(
        f"const keys = {json.dumps(NEW_OWNERS)}\n"
        "const forbidden = keys.filter((k) => /<script|<style|<image|data:image/.test(LOGOS[k].html))\n"
        "const ids = Object.entries(LOGOS).flatMap(([k, m]) => [...m.html.matchAll(/\\sid=\"([^\"]+)\"/g)].map((x) => [k, x[1]]))\n"
        "const seen = new Map()\n"
        "const twice = ids.filter(([, id]) => seen.has(id) || !seen.set(id, true))\n"
        "console.log('---REPORT---' + JSON.stringify({ forbidden, twice, ids }))\n"
    )
    assert answer["forbidden"] == []
    assert answer["twice"] == []
    for key, identifier in answer["ids"]:
        # The marks that were there before keep the ids they had.
        if key in NEW_OWNERS:
            assert identifier.startswith(key + "-"), (key, identifier)


@needs_node
def test_a_monochrome_mark_inherits_the_text_colour_and_a_coloured_one_keeps_its_colours():
    answer = _ask(
        "const mono = ['stabilityai', 'black-forest-labs', 'krea', 'lightricks', 'tencent', 'minimaxai', 'baidu',\n"
        "  'meituan-longcat', 'ideogram-ai', 'sensenova', 'speridlabs', 'rundiffusion']\n"
        "const colour = ['tongyi-mai', 'openmoss-team', 'pixart-alpha', 'purplesmartai', 'stableyogi', 'boogu', 'wan-ai', 'aidc-ai']\n"
        "console.log('---REPORT---' + JSON.stringify({\n"
        "  mono: mono.filter((k) => !LOGOS[k].html.includes('currentColor') || /fill=\"(?:#|black|white)/.test(LOGOS[k].html)),\n"
        "  colour: colour.filter((k) => !/#[0-9a-fA-F]{3,6}|url\\(#/.test(LOGOS[k].html)),\n"
        "}))\n"
    )
    assert answer == {"mono": [], "colour": []}


@needs_node
def test_the_raster_of_rundiffusion_is_gone_and_the_marks_that_were_there_stay():
    answer = _ask(
        "console.log('---REPORT---' + JSON.stringify({\n"
        "  image: /<image/.test(LOGOS.rundiffusion.html),\n"
        "  stay: ['qwen', 'microsoft', 'nvidia', 'huggingface', 'cyberdelia', 'cagliostro'].filter((k) => !LOGOS[k]),\n"
        "}))\n"
    )
    assert answer == {"image": False, "stay": []}


def test_the_viewbox_of_each_new_mark_is_a_number_box():
    source = (FRONTEND / "src" / "lib" / "logos.js").read_text(encoding="utf-8")
    for key in NEW_OWNERS:
        found = re.search(rf"\n  '?{re.escape(key)}'?: \{{\n    vb: '([^']+)'", source)
        assert found, key
        parts = found.group(1).split()
        assert len(parts) == 4 and all(re.fullmatch(r"-?[0-9.]+", part) for part in parts), key


@needs_node
def test_the_mark_of_wan_is_the_mark_of_qwen_in_red():
    """Same drawing, the two colours of the gradient turned red, and its own
    ids so the two marks never share a gradient on one page."""
    answer = _ask(
        "const paths = (m) => [...m.html.matchAll(/\\sd=\"([^\"]*)\"/g)].map((x) => x[1])\n"
        "const colours = (m) => [...new Set(m.html.match(/#[0-9A-Fa-f]{6}/g))].sort()\n"
        "console.log('---REPORT---' + JSON.stringify({\n"
        "  samePaths: JSON.stringify(paths(LOGOS['wan-ai'])) === JSON.stringify(paths(LOGOS.qwen)),\n"
        "  colours: colours(LOGOS['wan-ai']),\n"
        "  qwenColours: colours(LOGOS.qwen),\n"
        "  ids: [...LOGOS['wan-ai'].html.matchAll(/\\sid=\"([^\"]+)\"/g)].map((x) => x[1]),\n"
        "}))\n"
    )
    assert answer["samePaths"] is True
    assert answer["colours"] == ["#912E2E", "#EE5C5C"]
    assert answer["qwenColours"] == ["#332E91", "#665CEE"]
    assert answer["ids"] and all(i.startswith("wan-ai-") for i in answer["ids"])
