"""The studio and the picture server show a video model's frames, and its frame
rate only where the model has one to set, measured in a real browser.

``StudioBasics.svelte`` and ``ImageStudio.svelte`` are built as shipped on the
page of ``tests/test_studio_generate_stays_chrome.py`` with the service made
up: one model of the family under test, and the start values the service
answers for it. A family that draws at one rate (Wan 2.2 S2V) answers none, and
its row is not there; the draw it asks for carries frames and no rate. Wan 2.1
and LTX-2.3 show both rows and send both values. Skipped where there is no
Chrome or no node.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from uuid import uuid4

import pytest

from app import appfenster, image_families, prozessstopp
from tests import test_studio_generate_stays_chrome as base

pytestmark = base.pytestmark

FRONTEND = base.FRONTEND

CASES = r"""
const scenario = new URLSearchParams(location.search).get('scenario')
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
const { werte, auswahl } = window.__studio
for (let k = 0; k < 100 && !document.querySelector('textarea.prompt'); k += 1) await wait(100)
await wait(600)
auswahl.medium = 'video'
await wait(800)
const rows = () => Array.from(document.querySelectorAll('[data-suche]')).map((n) => n.dataset.suche)
const report = { scenario, rows: rows(), werte: { frames: werte.video_frames, fps: werte.fps } }
const prompt = document.querySelector('textarea.prompt')
prompt.focus()
prompt.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
for (let k = 0; k < 60 && !(window.__draws || []).length; k += 1) await wait(100)
const job = (window.__draws || [])[0]
report.draw = job ? { video: job.video, video_frames: job.video_frames, fps: job.fps } : null
document.title = 'open'
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""


def _entry() -> str:
    families = json.dumps(image_families.as_json())
    entry = base.ENTRY_JS % {
        "global": "../../src/stil/global.css", "studio": "../../src/lib/studio.svelte.js",
    }
    entry = entry.replace("'/bild/familien': [],", f"'/bild/familien': {families},")
    # The model's family and its start values come with the scenario; the rate is
    # answered for every family, so that only the studio keeps it from S2V.
    entry = entry.replace(
        "modelle: ['model-a'], standardmodell: 'model-a', families: {},",
        "modelle: ['model-a'], standardmodell: 'model-a', families: { 'model-a': scenario },",
    )
    entry = entry.replace(
        "'/bild/vorgaben': { family: '', breite: 1024, hoehe: 1024, schritte: 8, cfg: 1 },",
        "'/bild/vorgaben': { family: scenario, breite: 832, hoehe: 480, schritte: 8, cfg: 1,"
        " video_frames: 17, fps: 12 },",
    )
    assert families in entry and "families: { 'model-a': scenario }" in entry
    assert "video_frames: 17" in entry
    return entry


@pytest.fixture(scope="module")
def measure():
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-video-frames-studio-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(base.SHELL, encoding="utf-8")
        (folder / "entry.js").write_text(_entry(), encoding="utf-8")
        (folder / "vite.config.js").write_text(base.VITE_CONFIG, encoding="utf-8")
        build = subprocess.run(
            [shutil.which("vite", path=str(FRONTEND / "node_modules" / ".bin")), "build", "--config", "vite.config.js"],
            cwd=folder, capture_output=True, text=True, timeout=240,
        )
        assert build.returncode == 0, (build.stdout + build.stderr)[-2000:]
        (folder / "measure.html").write_text(base.PAGE % {"cases": CASES}, encoding="utf-8")

        def run(scenario: str) -> dict:
            import asyncio

            port = base._free_port()
            browser = subprocess.Popen(
                [
                    program, "--headless=new", "--no-first-run", "--disable-background-networking",
                    "--allow-file-access-from-files", "--window-size=1920,1080",
                    f"--remote-debugging-port={port}",
                    f"--user-data-dir={folder / ('profile-' + scenario)}",
                    (folder / "measure.html").as_uri() + f"?scenario={scenario}",
                ],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
            )
            try:
                return asyncio.run(base._drive(port))
            finally:
                prozessstopp.beenden(browser, frist=5)

        yield run
    finally:
        shutil.rmtree(folder, ignore_errors=True)


@pytest.fixture(scope="module")
def s2v(measure) -> dict:
    return measure("wan22_s2v")


@pytest.fixture(scope="module")
def wan(measure) -> dict:
    return measure("wan")


@pytest.fixture(scope="module")
def ltx(measure) -> dict:
    return measure("ltx")


def test_a_speech_to_video_model_shows_frames_and_no_frame_rate(s2v):
    assert "bild.video_frames" in s2v["rows"], s2v
    assert "bild.fps" not in s2v["rows"], s2v


def test_the_draw_of_a_speech_to_video_model_carries_frames_and_no_rate(s2v):
    assert s2v["draw"] is not None, s2v
    assert s2v["draw"]["video_frames"] == 17, s2v
    assert s2v["draw"]["fps"] is None, s2v


@pytest.mark.parametrize("case", ["wan", "ltx"])
def test_silence_other_video_models_show_both_rows_and_send_both_values(case, wan, ltx):
    report = {"wan": wan, "ltx": ltx}[case]
    assert {"bild.video_frames", "bild.fps"} <= set(report["rows"]), report
    assert report["draw"] is not None, report
    assert (report["draw"]["video_frames"], report["draw"]["fps"]) == (17, 12), report

