"""One head on the phone page: while a page inside a page is open, the head of
the whole page says it, and the inner page draws no head of its own.

What the head says lives in an import-free module (`headname.js`), so it runs
here exactly as it ships. The rest checks the shape of the files: the ten
places that open an inner page hand their name and their way back to the one
head, the frame reads it, and a page without an inner page keeps its head.
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

TEN = [
    "pages/Settings.svelte",
    "catalog/CardView.svelte",
    "catalog/RepoView.svelte",
    "cloud/AddProvider.svelte",
    "cloud/ProviderView.svelte",
    "servers/ServerView.svelte",
    "servers/ImageServerView.svelte",
    "servers/StorageView.svelte",
    "servers/ModelParams.svelte",
    "tools/SourceView.svelte",
]


def _run(body: str) -> object:
    driver = FRONTEND / f"phone_one_head.{os.getpid()}.check.mjs"
    driver.write_text(
        "import * as name from './src/phone/headname.js'\n" + textwrap.dedent(body),
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


def _read(path: str) -> str:
    return (PHONE / path).read_text(encoding="utf-8")


# ——— what the head says ———


@needs_node
def test_an_inner_page_owns_the_head_and_the_way_back_names_the_page_before_it():
    out = _run(
        """
        const one = [{ title: 'Appearance' }]
        const two = [{ title: 'Local' }, { title: 'Speech server' }]
        console.log(JSON.stringify([
          name.topOf(one).title, name.nameBefore(one, 'Settings'),
          name.topOf(two).title, name.nameBefore(two, 'Models'),
        ]))
        """
    )
    assert out == ["Appearance", "Settings", "Speech server", "Local"]


@needs_node
def test_silence_a_page_without_an_inner_page_keeps_its_own_head():
    out = _run(
        """
        console.log(JSON.stringify([name.topOf([]), name.nameBefore([], 'Downloads')]))
        """
    )
    assert out == [None, "Downloads"]


# ——— the shape of the files ———


def test_no_place_draws_a_head_of_its_own_under_the_head_of_the_page():
    sub = _read("parts/SubHead.svelte")
    assert "<h2" not in sub and "<button" not in sub and "<div" not in sub
    assert "<style" not in sub
    assert "headPush(entry)" in sub


@pytest.mark.parametrize("path", TEN)
def test_each_place_hands_its_name_and_its_way_back_to_the_one_head(path):
    text = _read(path)
    assert "import SubHead from" in text, path
    assert re.search(r"<SubHead\s+(title=\{[^}]+\}|\{title\})\s+(onback=\{[^}]+\}|\{onback\})\s*/>", text), path
    # And nothing of its own that looks like a second head.
    assert "class=\"subhead\"" not in text and "<h2" not in text, path


def test_the_frame_says_the_inner_page_and_has_one_back_button():
    frame = _read("PageFrame.svelte")
    assert "headTop()" in frame and "headBefore(title)" in frame
    assert "{inner ? inner.title : title}" in frame
    assert "inner ? inner.onback : onback" in frame
    # One way back at a time: the arrow, or — where an inner page asks for a
    # word — the word instead of it. The third button is the right end.
    assert frame.count("<button") == 3
    assert "{#if inner?.backText}" in frame and "{:else}" in frame
    # The name the button shows is in its spoken name too.
    assert "${t('app.zurueck')}: ${headBefore(title)}" in frame


def test_the_page_frame_sets_the_inner_look_only_while_an_inner_page_stands():
    frame = _read("PageFrame.svelte")
    assert "class:inner={Boolean(inner)}" in frame
    assert ".head.inner h1" in frame and "grid-template-columns" in frame


def test_the_head_state_is_kept_in_one_module_and_changes_without_loops():
    state = _read("head.svelte.js")
    # Pushing reads the stack it writes: untracked, or the effect would run again for ever.
    assert "untrack(() => head.stack.push(entry))" in state
    assert "export const head = $state(" in state
