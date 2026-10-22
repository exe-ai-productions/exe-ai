"""The windows the phone page takes over from the desktop: the picture row and
the swipe of the viewer, the studio page, the large server log, the manual
row, and the picture queue that moved out of the app shell.

The decisions of the swipe live in an import-free module (`bildreihe.js`),
so they run here exactly as they ship. The rest checks the shape of the
files: what the pages mount, what they leave alone, and that the texts they
read exist in both catalogues.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
SRC = FRONTEND / "src"
PHONE = SRC / "phone"
LOCALES = ROOT / "app" / "locales"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")


def _run(body: str) -> object:
    driver = FRONTEND / f"phone_viewer.{os.getpid()}.check.mjs"
    driver.write_text(
        "import * as row from './src/lib/bildreihe.js'\n" + textwrap.dedent(body),
        encoding="utf-8",
    )
    try:
        done = subprocess.run(
            ["node", driver.name], cwd=FRONTEND, capture_output=True, text=True, timeout=60
        )
    finally:
        driver.unlink(missing_ok=True)
    assert done.returncode == 0, (done.stdout + done.stderr)[-2000:]
    return json.loads(done.stdout.strip().splitlines()[-1])


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ——— the swipe ———


@needs_node
def test_a_swipe_to_the_left_asks_for_the_next_picture_and_to_the_right_for_the_one_before():
    out = _run(
        """
        console.log(JSON.stringify([
          row.wischSchritt({ dx: -120, dy: 6, dauer: 180 }),
          row.wischSchritt({ dx: 120, dy: -6, dauer: 180 }),
        ]))
        """
    )
    assert out == [1, -1]


@needs_node
def test_silence_a_short_a_slow_or_an_up_and_down_move_is_no_page_turn():
    out = _run(
        """
        console.log(JSON.stringify([
          row.wischSchritt({ dx: -30, dy: 0, dauer: 120 }),
          row.wischSchritt({ dx: -200, dy: 0, dauer: 1500 }),
          row.wischSchritt({ dx: -90, dy: 160, dauer: 200 }),
          row.wischSchritt({ dx: 0, dy: 0, dauer: 0 }),
        ]))
        """
    )
    assert out == [0, 0, 0, 0]


@needs_node
def test_the_edge_of_a_swipe_counts_as_a_turn_and_one_step_under_it_does_not():
    out = _run(
        """
        console.log(JSON.stringify([
          row.wischSchritt({ dx: -56, dy: 0, dauer: 700 }),
          row.wischSchritt({ dx: -55, dy: 0, dauer: 700 }),
          row.wischSchritt({ dx: -56, dy: 0, dauer: 701 }),
        ]))
        """
    )
    assert out == [1, 0, 0]


# ——— the row ———


@needs_node
def test_the_row_is_the_first_one_that_holds_the_picture_and_a_query_does_not_matter():
    out = _run(
        """
        const chat = ['/a.png', '/b.png', '/c.png']
        const gallery = ['/c.png', '/d.png']
        console.log(JSON.stringify([
          row.reiheMit('/b.png?k=1', [chat, gallery]),
          row.reiheMit('/d.png', [chat, gallery]),
          row.reiheMit('/c.png', [chat, gallery]),
          row.reiheMit('/zzz.png', [chat, gallery]),
          row.reiheMit('', [chat, gallery]),
        ]))
        """
    )
    assert out == [
        ["/a.png", "/b.png", "/c.png"],
        ["/c.png", "/d.png"],
        ["/a.png", "/b.png", "/c.png"],
        [],
        [],
    ]


@needs_node
def test_the_place_is_counted_from_one_and_zero_when_the_picture_is_in_no_row():
    out = _run(
        """
        const reihe = ['/a.png', '/b.png', '/c.png']
        console.log(JSON.stringify([
          row.stelleIn(reihe, '/a.png'),
          row.stelleIn(reihe, '/c.png?x=2'),
          row.stelleIn(reihe, '/nope.png'),
        ]))
        """
    )
    assert out == [
        {"nummer": 1, "von": 3},
        {"nummer": 3, "von": 3},
        {"nummer": 0, "von": 0},
    ]


@needs_node
def test_a_step_goes_to_the_neighbour_and_at_either_end_nothing_happens():
    out = _run(
        """
        const reihe = ['/a.png', '/b.png', '/c.png']
        console.log(JSON.stringify([
          row.nachbar(reihe, '/a.png', 1),
          row.nachbar(reihe, '/b.png', -1),
          row.nachbar(reihe, '/c.png', 1),
          row.nachbar(reihe, '/a.png', -1),
          row.nachbar(reihe, '/nope.png', 1),
        ]))
        """
    )
    assert out == ["/b.png", "/a.png", None, None, None]


@needs_node
def test_the_pictures_of_a_message_skip_the_empty_places_of_a_run_that_is_not_done():
    out = _run(
        """
        console.log(JSON.stringify([
          row.bilderVon({ bilder: ['/a.png', null, '/b.png'] }),
          row.bilderVon({ bilder: [null, null], bild: '/old.png' }),
          row.bilderVon({ bild: '/old.png' }),
          row.bilderVon({}),
          row.bilderVon(null),
        ]))
        """
    )
    assert out == [["/a.png", "/b.png"], ["/old.png"], ["/old.png"], [], []]


# ——— the shape of the pages ———


def test_the_viewer_steps_through_its_row_by_finger():
    text = _read(SRC / "teile" / "Bildschau.svelte")
    # The fingers are heard by the gesture action (a swipe to the side steps).
    assert "use:gestures" in text and "swipe: true" in text and "onswipe:" in text
    assert "ontouchstart" not in text and "ontouchend" not in text
    assert "reiheMit" in text and "stelleIn" in text


def test_the_row_of_the_place_a_picture_was_opened_from_comes_first_and_a_video_is_in_a_row_too():
    text = _read(SRC / "teile" / "Bildschau.svelte")
    assert "bildschau.folder === 'images' ? [folder, chat, gallery]" in text
    assert "studio.offen ? [gallery, chat, folder]" in text
    assert "!isVideo(bildschau.adresse)" not in text.split("const row = $derived.by", 1)[1].split("const place", 1)[0]
    # A video keeps its own controls: the gestures stand on the picture's stage only.
    video = text.split("<video", 1)[1].split(">", 1)[0]
    assert "use:gestures" not in video
    assert "use:gestures" in text.split("{:else}", 1)[1]


def test_only_the_log_that_opened_the_large_window_feeds_it():
    text = _read(PHONE / "parts" / "Log.svelte")
    assert "opened = true" in text and "else if (opened) setzeProtokollZeilen" in text


def test_the_studio_page_has_its_own_surface_and_marks_the_studio_open():
    text = _read(PHONE / "pages" / "Studio.svelte")
    assert "<ImageStudio" not in text and "<Area" in text
    assert "studio.offen = true" in text and "studio.offen = false" in text
    assert "<StudioBasics" in text and "<StudioDetails" in text
    assert "name: 'studio'" in text


def test_the_help_row_has_no_page_and_opens_the_manual():
    text = _read(PHONE / "pages" / "Help.svelte")
    assert "<script module>" in text
    assert "action:" in text
    assert "<" not in text.split("</script>", 1)[1].strip()


def test_a_page_with_an_action_runs_it_instead_of_opening():
    text = _read(PHONE / "pages.svelte.js")
    assert "page.action" in text


def test_the_server_log_has_a_button_that_takes_it_to_the_large_window():
    text = _read(PHONE / "parts" / "Log.svelte")
    assert "oeffneProtokoll" in text and "setzeProtokollZeilen" in text
    assert "modell.protokoll_vergroessern" in text


def test_the_phone_shell_mounts_the_job_windows_and_the_log_window():
    text = _read(PHONE / "Phone.svelte")
    for part in ("AuftragBestaetigen", "AuftragStarten", "Protokollfenster", "Bildschau"):
        assert f"<{part}" in text, part


def test_the_picture_queue_lives_in_its_own_module_and_the_shell_only_uses_it():
    queue = _read(SRC / "lib" / "bildlinie.svelte.js")
    for name in ("bildLokalZeichnen", "stopOnePicture", "removeWaitingPicture"):
        assert f"export async function {name}" in queue or f"export function {name}" in queue, name
    shell = _read(SRC / "App.svelte")
    assert "lib/bildlinie.svelte.js" in shell
    assert "async function bildLokalZeichnen" not in shell


def test_the_texts_the_new_pages_read_exist_in_both_catalogues():
    for lang in ("de", "en"):
        catalogue = json.loads(_read(LOCALES / f"{lang}.json"))
        for group, key in (
            ("studio", "titel"),
            ("studio", "feinheiten"),
            ("menue", "hilfe"),
            ("modell", "protokoll_vergroessern"),
            ("modell", "protokoll_titel"),
            ("app", "schliessen"),
        ):
            assert catalogue[group][key], (lang, group, key)
