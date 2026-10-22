"""The settings row reads "Help" in both languages and the manual lives at /help/.

The folder of the manual is `static/help/`; the service hands it out from the
root with `html=True`, so the folder name is the address. The window opens
that address, the desktop shell recognises the manual by it, and the two pages
of the manual point their language switch and their pictures at it. Nothing
answers at the old German address any more.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
PAGES = {"en": STATIC / "help" / "index.html", "de": STATIC / "help" / "de" / "index.html"}
RULE = ROOT / "fenster-electron" / "adressregel.js"
OPENER = ROOT / "frontend" / "src" / "lib" / "handbuch.js"
SHELL = ROOT / "fenster-electron" / "main.js"
LIST = ROOT / "frontend" / "src" / "lib" / "einstellungsliste.js"


def _catalogue(language: str) -> dict:
    return json.loads((ROOT / "app" / "locales" / f"{language}.json").read_text(encoding="utf-8"))


def test_the_settings_row_reads_help_in_both_languages():
    assert _catalogue("en")["menue"]["hilfe"] == "Help"
    assert _catalogue("de")["menue"]["hilfe"] == "Hilfe"


def test_the_row_is_still_in_the_settings_list_under_its_own_name():
    text = LIST.read_text(encoding="utf-8")
    assert "{ id: 'hilfe', zeichen: 'hilfe', titel: 'menue.hilfe', ziel: { hilfe: true } }" in text


def test_the_manual_folder_is_called_help_and_the_old_one_is_gone():
    assert PAGES["en"].is_file() and PAGES["de"].is_file()
    assert (STATIC / "help" / "bilder").is_dir()
    assert not (STATIC / "hilfe").exists()


def test_the_service_answers_the_manual_at_help_and_nothing_at_hilfe(client: TestClient):
    assert client.get("/help/").status_code == 200
    assert client.get("/help/de/").status_code == 200
    assert client.get("/help/bilder/held-exe.webp").status_code == 200
    for old in ("/hilfe/", "/hilfe/de/", "/hilfe/bilder/held-exe.webp"):
        assert client.get(old).status_code == 404, old


@pytest.mark.parametrize("language", ["en", "de"])
def test_no_address_in_the_manual_names_the_old_folder(language):
    text = PAGES[language].read_text(encoding="utf-8")
    assert "/hilfe" not in text


@pytest.mark.parametrize("language", ["en", "de"])
def test_every_address_of_the_manual_points_at_a_file_that_is_there(language):
    text = PAGES[language].read_text(encoding="utf-8")
    pictures = set(re.findall(r'src="/help/([^"]+)"', text))
    assert pictures, language
    for name in pictures:
        assert (STATIC / "help" / name).is_file(), (language, name)
    # The switch of language and, on the English page, the jump to the German one.
    assert ("/help/de/" if language == "en" else "/help/?sprache=en") in text


def test_the_window_opens_the_manual_at_help():
    text = OPENER.read_text(encoding="utf-8")
    assert "window.open('/help/', '_blank')" in text
    assert "/hilfe" not in text


def test_the_shell_names_no_old_address():
    assert "/hilfe/" not in SHELL.read_text(encoding="utf-8")


def test_no_source_of_the_program_names_the_old_address():
    # The window, the shell, the service and the phone pages: a later
    # `window.open('/hilfe/')` anywhere would open a page nothing answers.
    suffixes = {".js", ".svelte", ".py", ".json", ".html"}
    found = []
    for folder in ("frontend/src", "fenster-electron", "app", "cli"):
        for path in (ROOT / folder).rglob("*"):
            if path.suffix not in suffixes or {"node_modules", "dist"} & set(path.parts) or not path.is_file():
                continue
            if "/hilfe/" in path.read_text(encoding="utf-8", errors="ignore"):
                found.append(str(path.relative_to(ROOT)))
    assert not found, found


def test_the_shell_recognises_the_manual_by_its_new_address():
    if not shutil.which("node"):
        pytest.skip("node is missing")
    script = """
    const rules = require(%s)
    console.log(JSON.stringify({
      path: rules.HANDBUCH_PFAD,
      help: rules.istHandbuch('http://127.0.0.1:8090/help/'),
      below: rules.istHandbuch('http://127.0.0.1:8090/help/de/'),
      hilfe: rules.istHandbuch('http://127.0.0.1:8090/hilfe/'),
      app: rules.istHandbuch('http://127.0.0.1:8090/app/'),
    }))
    """ % json.dumps(str(RULE))
    run = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, (run.stdout + run.stderr)[-2000:]
    answer = json.loads(run.stdout)
    assert answer == {"path": "/help/", "help": True, "below": True, "hilfe": False, "app": False}


def test_silence_the_help_of_the_cli_and_the_skill_keep_their_words():
    assert _catalogue("de")["cli"]["help_help"] == "Diese Hilfe anzeigen"
    assert _catalogue("en")["cli"]["help_help"] == "Show this help"
    assert (ROOT / "skills" / "help" / "SKILL.md").is_file()
    # The other rows of the list and the inner names stay.
    assert _catalogue("de")["menue"]["settings"] == "Einstellungen"
    assert _catalogue("de")["menue"]["lokal"] == "Lokal"
