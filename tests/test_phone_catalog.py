"""The catalogue on the phone page: the curated cards of every kind, the
builds of one card, and what a tap on a build turns into.

The decisions live in an import-free module (`catalog.js`), so they run here
exactly as they ship. The rest checks the shape of the files: the page leads
with the curated cards, hides them while a search runs, and reaches every
kind the desktop catalogue has.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
PHONE = FRONTEND / "src" / "phone"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")

TARGETS = "{ mmproj: { unterordner: 'vision' }, mtp: { unterordner: 'mtp' } }"


def _run(body: str) -> object:
    driver = FRONTEND / f"phone_catalog.{os.getpid()}.check.mjs"
    driver.write_text(
        "import * as catalog from './src/phone/catalog.js'\n"
        "import { ARTEN, ZUBEHOER_ZIEL, katalogFuer } from './src/lib/modellempfehlungen.js'\n"
        + textwrap.dedent(body),
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


BUILD = (
    "{ id: 'a/b', datei: 'm.gguf', mmproj: 'p.gguf', mmproj_ziel: 'p-local.gguf', "
    "drafter: 'd.gguf', drafter_ziel: 'd-local.gguf', drafter_repo: 'a/draft' }"
)


# ——— the state of a build ———


@needs_node
def test_a_build_is_new_ready_or_being_fetched_by_its_own_file_or_a_companion():
    out = _run(
        f"""
        const build = {BUILD}
        const running = (datei) => ({{ datei, fertig: false, fehler: null }})
        console.log(JSON.stringify([
          catalog.buildState(build, [], null),
          catalog.buildState(build, ['m.gguf'], null),
          catalog.buildState(build, [], running('m.gguf')),
          catalog.buildState(build, ['m.gguf'], running('p-local.gguf')),
          catalog.buildState(build, ['m.gguf'], running('d-local.gguf')),
        ]))
        """
    )
    assert out == ["neu", "bereit", "laedt", "laedt", "laedt"]


@needs_node
def test_silence_another_file_a_finished_or_a_failed_download_is_no_fetching():
    out = _run(
        f"""
        const build = {BUILD}
        console.log(JSON.stringify([
          catalog.buildState(build, [], {{ datei: 'other.gguf', fertig: false, fehler: null }}),
          catalog.buildState(build, [], {{ datei: 'm.gguf', fertig: true, fehler: null }}),
          catalog.buildState(build, [], {{ datei: 'm.gguf', fertig: false, fehler: 'abgebrochen' }}),
          catalog.buildProgress(build, {{ datei: 'other.gguf', fertig: false, fehler: null }}),
          catalog.buildProgress(build, null),
        ]))
        """
    )
    assert out == ["neu", "neu", "neu", None, None]


@needs_node
def test_progress_says_how_far_and_which_part_runs():
    out = _run(
        f"""
        const build = {BUILD}
        const at = (datei) => ({{ datei, anteil: 0.456, geladen: 5, gesamt: 11, fertig: false, fehler: null }})
        console.log(JSON.stringify([
          catalog.buildProgress(build, at('m.gguf')),
          catalog.buildProgress(build, at('p-local.gguf')).part,
          catalog.buildProgress(build, at('d-local.gguf')).part,
        ]))
        """
    )
    assert out == [{"part": None, "percent": 46, "loaded": 5, "total": 11}, "mmproj", "drafter"]


# ——— what a tap fetches ———


@needs_node
def test_a_tap_fetches_the_model_then_its_projector_then_its_speed_module():
    out = _run(
        f"""
        const plan = catalog.planBuild({{
          build: {BUILD}, present: [], route: {{ art: 'chat' }}, targets: {TARGETS},
        }})
        console.log(JSON.stringify([plan.art, plan.queue.map((job) => [job.repo, job.datei, job.ziel, job.rolle, job.unterordner, job.gehoert_zu])]))
        """
    )
    assert out == [
        "chat",
        [
            ["a/b", "m.gguf", None, None, None, None],
            ["a/b", "p.gguf", "p-local.gguf", "mmproj", "vision", "m.gguf"],
            ["a/draft", "d.gguf", "d-local.gguf", "mtp", "mtp", "m.gguf"],
        ],
    ]


@needs_node
def test_silence_a_build_that_lies_here_with_its_companions_fetches_nothing():
    out = _run(
        f"""
        const plan = catalog.planBuild({{
          build: {BUILD}, present: ['m.gguf', 'p-local.gguf', 'd-local.gguf'],
          route: {{ art: 'chat' }}, targets: {TARGETS},
        }})
        console.log(JSON.stringify(plan.queue))
        """
    )
    assert out == []


@needs_node
def test_a_build_that_lies_here_still_fetches_the_companion_that_never_arrived():
    out = _run(
        f"""
        const plan = catalog.planBuild({{
          build: {BUILD}, present: ['m.gguf', 'p-local.gguf'], route: {{ art: 'chat' }}, targets: {TARGETS},
        }})
        console.log(JSON.stringify(plan.queue.map((job) => job.datei)))
        """
    )
    assert out == ["d.gguf"]


@needs_node
def test_an_accessory_goes_to_its_own_folder_and_role_and_a_plain_card_to_the_page_kind():
    out = _run(
        """
        const lora = { id: 'x/y', datei: 'l.safetensors', ziel: 'l-local.safetensors' }
        const plain = catalog.planBuild({ build: lora, present: [], route: { art: 'bild' }, targets: ZUBEHOER_ZIEL })
        const sorted = catalog.planBuild({ build: lora, present: [], route: ZUBEHOER_ZIEL.lora, targets: ZUBEHOER_ZIEL })
        const drafter = catalog.planBuild({ build: lora, present: [], route: ZUBEHOER_ZIEL.mtp, targets: ZUBEHOER_ZIEL })
        console.log(JSON.stringify([
          plain.art, plain.queue[0].unterordner, plain.queue[0].ziel,
          sorted.art, sorted.queue[0].unterordner, sorted.queue[0].rolle,
          drafter.art, drafter.queue[0].unterordner, drafter.queue[0].rolle,
        ]))
        """
    )
    assert out == [
        "bild", None, "l-local.safetensors",
        "bild", "lora", None,
        "chat", "mtp", "mtp",
    ]


# ——— the shape of the page ———


def test_the_catalogue_page_leads_with_the_curated_cards_and_hides_them_while_a_search_runs():
    page = (PHONE / "pages" / "Catalog.svelte").read_text(encoding="utf-8")
    assert "katalogFuer(art)" in page
    assert "{#if !searchOn}" in page
    assert "<CardView" in page
    assert "katalog.keine_kuratierten" in page


@needs_node
def test_the_page_reaches_every_kind_the_desktop_catalogue_has():
    out = _run("console.log(JSON.stringify(ARTEN))")
    page = (PHONE / "pages" / "Catalog.svelte").read_text(encoding="utf-8")
    kinds = re.search(r"const KINDS = \$derived\(\[(.*?)\]\)", page, re.S).group(1)
    for kind in out:
        assert f"value: '{kind}'" in kinds, kind
    for kind in out:
        assert f"{kind}: 'katalog.vorauswahl_{kind}'" in page, kind


@needs_node
def test_every_kind_has_cards_to_show_and_every_accessory_kind_a_list():
    out = _run(
        """
        console.log(JSON.stringify(ARTEN.map((kind) => [kind, katalogFuer(kind).length > 0])))
        """
    )
    assert all(has for _, has in out)
    page = (PHONE / "pages" / "Catalog.svelte").read_text(encoding="utf-8")
    assert "SPALTEN_ZUBEHOER" in page and "entry.sorte === sorte" in page


def test_the_card_page_fetches_through_the_plan_and_names_what_fits():
    view = (PHONE / "catalog" / "CardView.svelte").read_text(encoding="utf-8")
    assert "planBuild(" in view and "enqueue(" in view
    for key in ("katalog.empfohlen_fuer", "katalog.passt_fuer", "katalog.braucht_maschine", "katalog.abbrechen"):
        assert key in view, key


@needs_node
def test_silence_a_report_without_a_file_name_marks_no_build_as_fetching():
    out = _run(
        """
        const plain = { id: 'a/b', datei: 'm.gguf' }
        const stand = { fertig: false, fehler: null }
        console.log(JSON.stringify([catalog.buildProgress(plain, stand), catalog.buildState(plain, [], stand)]))
        """
    )
    assert out == [None, "neu"]


def test_an_accessory_names_its_model_class_and_a_change_of_kind_drops_the_old_search():
    view = (PHONE / "catalog" / "CardView.svelte").read_text(encoding="utf-8")
    assert "card.klasse" in view and "{#if classWord}" in view
    page = (PHONE / "pages" / "Catalog.svelte").read_text(encoding="utf-8")
    kind = page.split("function pickKind(value) {", 1)[1].split("\n  }\n", 1)[0]
    assert "clearTimeout(timer)" in kind and "run += 1" in kind


def test_the_page_reads_what_the_machine_holds_from_the_download_feed():
    page = (PHONE / "pages" / "Catalog.svelte").read_text(encoding="utf-8")
    assert "feed.memoryGb" in page and "runnerAuskunft" not in page
    assert "memoryGb" in (PHONE / "downloadFeed.svelte.js").read_text(encoding="utf-8")
