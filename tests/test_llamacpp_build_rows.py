"""The builds of the server program, drawn as rows: where the machine cannot
run a build it is listed greyed (macOS), where it can the row carries its
size and the download button of a file row (Windows), and the way back to the
tested build stands under a fold that is there only when there is a build to
go back to.

The service names the greyed builds in `unavailable`; the window draws them
with `BuildRows.svelte`, a piece that asks no service of its own.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import serverdownload

SOURCE = Path(__file__).resolve().parent.parent / "frontend" / "src"
BUILD_ROWS = (SOURCE / "teile" / "BuildRows.svelte").read_text(encoding="utf-8")
SECTION = (SOURCE / "teile" / "LlamaCppSection.svelte").read_text(encoding="utf-8")

FOUR = [
    ("cpu", 19_398_918),
    ("cuda12", 264_478_423 + 391_443_627),
    ("vulkan", 33_337_769),
    ("rocm", 256_958_369),
]


def _system(monkeypatch, platform: str, machine: str) -> None:
    monkeypatch.setattr(serverdownload, "sys", SimpleNamespace(platform=platform))
    monkeypatch.setattr(serverdownload.platform, "machine", lambda: machine)


def test_a_mac_names_the_four_builds_it_cannot_run(monkeypatch):
    _system(monkeypatch, "darwin", "arm64")
    assert serverdownload.unavailable_variants() == FOUR
    # Nothing is offered there: the choice stays empty.
    assert serverdownload.waehlbare_varianten() == []


@pytest.mark.parametrize(
    ("platform", "machine"),
    [("linux", "x86_64"), ("linux", "aarch64"), ("win32", "arm64"), ("win32", "amd64")],
)
def test_silence_every_other_system_names_no_greyed_build(monkeypatch, platform, machine):
    _system(monkeypatch, platform, machine)
    assert serverdownload.unavailable_variants() == []


def test_windows_still_offers_the_same_four_builds(monkeypatch):
    """Silence probe: the choice of Windows on x64 is what it was."""
    _system(monkeypatch, "win32", "amd64")
    assert serverdownload.waehlbare_varianten() == FOUR


def test_a_build_row_ends_with_its_size_and_the_download_button_of_a_file_row():
    rows = BUILD_ROWS[BUILD_ROWS.index("{#each builds"):BUILD_ROWS.index("{@render status")]
    # The size, then the button — as the file rows of the catalogue draw it.
    assert rows.index('class="groesse"') < rows.index('<DownloadRow status="neu"')
    assert "onDownload={() => onDownload?.(b.variante)}" in rows
    assert "disabled={locked || busy}" in rows
    # The button is the row's own piece; no size of its own is set here.
    assert "import DownloadRow from './DownloadRow.svelte'" in BUILD_ROWS
    assert not re.search(r"\.sign-button|\.feldknopf", BUILD_ROWS)


def test_the_installed_build_is_green_with_a_tick():
    installed = BUILD_ROWS[BUILD_ROWS.index('class="da"'):BUILD_ROWS.index("{:else}")]
    assert "bildserver.variante_installiert" in installed
    assert 'zeichen="haken"' in installed
    # The word is text, the tick a shape: each in its own green.
    assert re.search(r"\.da\s*\{[^}]*color:\s*var\(--gruen-text\)", BUILD_ROWS)
    assert re.search(r"\.haken\s*\{[^}]*color:\s*var\(--gruen\);", BUILD_ROWS)


def test_the_fold_stands_only_with_a_build_to_go_back_to():
    fold = BUILD_ROWS[BUILD_ROWS.index("{#if restorable}"):BUILD_ROWS.index("<style>")]
    assert "modell.gruppe_erweitert" in fold
    assert "let foldOpen = $state(true)" in BUILD_ROWS
    assert "bildserver.restore_tested_build" in fold
    assert 'zeichen="refresh"' in fold


def test_the_piece_asks_no_service_of_its_own():
    assert not re.search(r"\bapi\b|lib/api", BUILD_ROWS)
    assert "fetch(" not in BUILD_ROWS


def test_the_section_hands_the_rows_over_and_keeps_the_bar_and_the_error():
    assert "import BuildRows from './BuildRows.svelte'" in SECTION
    assert "<BuildRows" in SECTION
    # The old rows and the old button of the version row are gone ...
    assert "bildserver.variante_holen" not in SECTION
    assert "bildserver.variante_installiert" not in SECTION
    assert "bildserver.restore_tested_build" not in SECTION
    assert "v_still" not in SECTION
    # ... the fetch, its bar and its error stay with the section.
    assert "serverProgrammHolen" in SECTION
    assert "bildserver.generator_fehler" in SECTION
    assert 'class="balken"' in SECTION
