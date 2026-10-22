"""The studio's prompt bar never grows past the room the area keeps free under
itself, measured in a real browser.

`ImageStudio.svelte` is built as shipped and drawn in headless Chrome with the
answers of the service made up in the page: a picture in the area. The surface
has the size a window leaves it — 615 x 784 is a 1280 x 800 window, 775 x 884 a
1440 x 900 one, 1255 x 1064 a 1920 x 1080 one.

* With the prompt and the negative prompt both filled to their limit, the top
  of the bar lies at least 12 px under the bottom of the area, and both fields
  scroll inside (each at most 160 px high).
* Silence probes: with a short prompt, and with one full field, the bar is as
  high as it was before (one full field fills the room exactly), no field
  scrolls where its text fits, and the area is as high as before at all three
  sizes (348, 448 and 668 px).

Skipped where there is no Chrome or no node, like the other browser tests.
"""

from __future__ import annotations

import asyncio
import base64
import json
import shutil
import struct
import subprocess
import zlib
from urllib.parse import quote
from uuid import uuid4

import pytest

from app import appfenster, prozessstopp
from tests import test_studio_generate_stays_chrome as page

FRONTEND = page.FRONTEND
ROOT = page.ROOT

pytestmark = [
    pytest.mark.platforms("darwin", reason="the browser run of the interface is checked on macOS only"),
    pytest.mark.skipif(
        shutil.which("node") is None or not (FRONTEND / "node_modules" / "vite").exists(),
        reason="no node or no frontend dependencies on this machine",
    ),
]


def _picture() -> str:
    """A plain 64 x 64 picture as an address of its own."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    rows = b"".join(b"\x00" + b"\xcc\xcc\xcc" * 64 for _ in range(64))
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 64, 64, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )
    return "data:image/png;base64," + base64.b64encode(png).decode()


SHELL = """<script>
  import ImageStudio from '../../src/teile/ImageStudio.svelte'

  const q = JSON.parse(new URLSearchParams(location.search).get('s'))
</script>

<div id="frame" style="width: {q.w}px; height: {q.h}px; position: relative; display: flex;">
  <ImageStudio zeichnen={() => {}} />
</div>
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import %(global)r
import german from %(german)r
import english from %(english)r
import { texte } from %(texts)r
import { api } from %(api)r
import { werte } from %(studio)r

const q = JSON.parse(new URLSearchParams(location.search).get('s'))
texte.sprache = q.lang
texte.katalog = q.lang === 'de' ? german : english
api.bildAdresse = () => %(picture)r
const names = ['a', 'b', 'c'].map((c) => c.repeat(32) + '.png')
const answers = {
  '/bild/modelle': {
    programm_da: true, modelle: ['model-a'], standardmodell: 'model-a', families: {}, sampler: [], scheduler: [],
    loras: [], sizes: {},
  },
  '/bild/familien': [],
  '/bild/vorgaben': { family: '', breite: q.areaW, hoehe: q.areaH, schritte: 8, cfg: 1 },
  '/bilder': { bilder: names },
  '/settings/resolved/bildfenster': { wert: { modell: 'model-a', prompt: q.initial } },
}
window.fetch = async (address) => {
  const path = String(address).replace(/^.*?\\/api\\/v1/, '').split('?')[0]
  const body = path in answers ? answers[path] : {}
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}
document.documentElement.dataset.modus = 'hell'
werte.breite = q.areaW
werte.hoehe = q.areaH
werte.startbild = q.picture ? 'a-picture.png' : ''
window.__werte = werte
mount(Shell, { target: document.getElementById('wurzel') })
"""

CASES = r"""
const q = JSON.parse(new URLSearchParams(location.search).get('s'))
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
const cut = (el) => {
  if (!el) return null
  const r = el.getBoundingClientRect()
  return { l: r.left, t: r.top, r: r.right, b: r.bottom, w: r.width, h: r.height }
}
for (let k = 0; k < 100 && !(document.querySelector('.studio .bereich') && document.querySelector('.leiste[role=group]')); k += 1) await wait(100)
await wait(500)
const long = Array.from({ length: 40 }, (_, i) => 'word' + i).join(' ').repeat(3)
if (q.prompt === 'long') window.__werte.prompt = long
if (q.negative === 'long') {
  window.__werte.negativ = long
  document.querySelector('.leiste[role=group] .reihe .pille').click()
}
await wait(600)
const bar = document.querySelector('.leiste[role=group]')
const fields = [...bar.querySelectorAll('textarea')].map((el) => ({
  client: el.clientHeight, scroll: el.scrollHeight, h: el.getBoundingClientRect().height,
}))
const surface = document.querySelector('.studio > .flaeche').getBoundingClientRect()
document.title = 'open'
document.getElementById('ergebnis').textContent = JSON.stringify({
  q, surface: { w: surface.width, h: surface.height, b: surface.bottom },
  area: cut(document.querySelector('.studio .bereich')), bar: cut(bar), fields,
})
"""

# Surface sizes of a 1280 x 800, a 1440 x 900 and a 1920 x 1080 window, with the area's height they keep.
SIZES = {"1280": (615, 784, 348), "1440": (775, 884, 448), "1920": (1255, 1064, 668)}
KINDS = {
    "short": dict(prompt="short", negative="short"),
    "one_full": dict(prompt="long", negative="short"),
    "both_full": dict(prompt="long", negative="long"),
}
SCENARIOS = {
    f"{size}_{kind}": dict(w=w, h=h, lang="en", areaW=1024, areaH=1024, initial="a cat", **options)
    for size, (w, h, _) in SIZES.items()
    for kind, options in KINDS.items()
}


@pytest.fixture(scope="module")
def reports() -> dict:
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-prompt-bar-cap-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(SHELL, encoding="utf-8")
        (folder / "entry.js").write_text(
            ENTRY_JS
            % {
                "global": "../../src/stil/global.css",
                "german": str(ROOT / "app" / "locales" / "de.json"),
                "english": str(ROOT / "app" / "locales" / "en.json"),
                "texts": "../../src/lib/texte.svelte.js",
                "api": "../../src/lib/api.js",
                "studio": "../../src/lib/studio.svelte.js",
                "picture": _picture(),
            },
            encoding="utf-8",
        )
        (folder / "vite.config.js").write_text(page.VITE_CONFIG, encoding="utf-8")
        build = subprocess.run(
            [shutil.which("vite", path=str(FRONTEND / "node_modules" / ".bin")), "build", "--config", "vite.config.js"],
            cwd=folder, capture_output=True, text=True, timeout=240,
        )
        assert build.returncode == 0, (build.stdout + build.stderr)[-2000:]
        (folder / "measure.html").write_text(page.PAGE % {"cases": CASES}, encoding="utf-8")
        out: dict = {}
        for name, scenario in SCENARIOS.items():
            scenario = {"picture": True, **scenario}
            port = page._free_port()
            browser = subprocess.Popen(
                [
                    program, "--headless=new", "--no-first-run", "--disable-background-networking",
                    "--allow-file-access-from-files", "--window-size=1920,1080",
                    f"--remote-debugging-port={port}", f"--user-data-dir={folder / ('profile-' + name)}",
                    (folder / "measure.html").as_uri() + "?s=" + quote(json.dumps(scenario)),
                ],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
            )
            try:
                out[name] = asyncio.run(page._drive(port))
            finally:
                prozessstopp.beenden(browser, frist=5)
        return out
    finally:
        shutil.rmtree(folder, ignore_errors=True)


@pytest.mark.parametrize("size", list(SIZES))
def test_with_both_fields_full_the_bar_stays_12px_under_the_area(reports, size):
    report = reports[f"{size}_both_full"]
    gap = report["bar"]["t"] - report["area"]["b"]
    assert gap >= 12 - 0.5, (size, gap, report["bar"], report["area"])


@pytest.mark.parametrize("size", list(SIZES))
def test_with_both_fields_full_both_fields_scroll_inside_and_stay_under_160px(reports, size):
    fields = reports[f"{size}_both_full"]["fields"]
    assert len(fields) == 2, fields
    for field in fields:
        assert field["scroll"] > field["client"] + 1, (size, field)
        assert field["h"] <= 160 + 0.5, (size, field)


@pytest.mark.parametrize("size", list(SIZES))
def test_the_bar_never_reaches_up_past_its_room(reports, size):
    """The bar never grows past the room under the area less its edge and the air."""
    for kind in KINDS:
        report = reports[f"{size}_{kind}"]
        assert report["bar"]["h"] <= 274 - 44 - 12 + 0.5, (size, kind, report["bar"])


@pytest.mark.parametrize("size", list(SIZES))
def test_silence_probe_the_area_is_as_high_as_before(reports, size):
    expected = SIZES[size][2]
    for kind in KINDS:
        assert abs(reports[f"{size}_{kind}"]["area"]["h"] - expected) <= 1, (size, kind)


@pytest.mark.parametrize("size", list(SIZES))
def test_silence_probe_a_short_prompt_leaves_the_bar_low_and_its_field_whole(reports, size):
    report = reports[f"{size}_short"]
    assert report["bar"]["h"] < 120, (size, report["bar"])
    for field in report["fields"]:
        assert field["scroll"] <= field["client"] + 1, (size, field)


@pytest.mark.parametrize("size", ["1440", "1920"])
def test_silence_probe_one_full_field_fills_the_room_exactly_as_before(reports, size):
    report = reports[f"{size}_one_full"]
    (field,) = report["fields"]
    assert abs(field["h"] - 160) <= 0.5, (size, field)
    assert abs(report["bar"]["h"] - 218) <= 0.5, (size, report["bar"])


def test_in_the_narrow_bar_the_row_breaks_and_one_full_field_gives_way_by_what_it_took(reports):
    """At 1280 the bar is 382 px wide, its lower row breaks into two lines (36 px more):
    the full field would cover the area by that much, so it shrinks by it."""
    report = reports["1280_one_full"]
    (field,) = report["fields"]
    assert abs(report["bar"]["h"] - 218) <= 0.5, report["bar"]
    assert abs(field["h"] - 124) <= 0.5, field
    assert report["bar"]["t"] - report["area"]["b"] >= 12 - 0.5, report
