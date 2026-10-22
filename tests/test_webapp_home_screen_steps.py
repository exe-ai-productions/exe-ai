"""The page Web App shows how the page on the phone becomes an app on its
Home Screen: three pictures in order, each with its caption, under the setup;
the code to scan stands beside them in a tile of its own."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "frontend/src/assets/web-app"
PAGE = ROOT / "frontend/src/teile/SettingsWebApp.svelte"

# In the order of the steps: Share, Add to Home Screen, the app itself.
PICTURES = ("step-share.webp", "step-add-to-home-screen.webp", "step-home-screen-app.webp")
KEYS = ("add_to_home", "step_share", "step_add", "step_open")
TEXTS = {
    "en": ("Add to Home Screen", "Tap Share", "Choose Add to Home Screen", "Open Exe AI from your Home Screen"),
    "de": ("Zum Home-Bildschirm", "Teilen antippen", "„Zum Home-Bildschirm“ wählen", "Exe AI vom Home-Bildschirm öffnen"),
}


def test_the_three_pictures_lie_in_the_assets_at_700_by_982():
    for name in PICTURES:
        with Image.open(ASSETS / name) as picture:
            assert picture.size == (700, 982), name


def test_the_page_shows_them_in_the_order_share_add_app():
    source = PAGE.read_text(encoding="utf-8")
    imports = re.findall(r"import (\w+) from '\.\./assets/web-app/(step-[\w-]+\.webp)'", source)
    assert [file for _, file in imports] == list(PICTURES)
    names = [name for name, _ in imports]
    steps = re.search(r"const HOME_STEPS = \[(.*?)\n  \]", source, re.S)
    assert steps
    assert re.findall(r"src: (\w+), text: '(webapp\.step_\w+)'", steps.group(1)) == [
        (names[0], "webapp.step_share"),
        (names[1], "webapp.step_add"),
        (names[2], "webapp.step_open"),
    ]
    # The caption is the picture's text too, and the section has no veil: the
    # steps hold while the service stands still.
    assert "alt={t(step.text)}" in source
    opening = source[: source.index("{t('webapp.add_to_home')}")].rsplit("<section", 1)[1]
    assert "dimmed" not in opening
    # Under the setup, three equal tiles in a row; the code to scan follows
    # them as the middle column.
    assert source.index("webapp.setup") < source.index("webapp.add_to_home") < source.index("webapp.scan_qr")
    assert "grid-template-columns: repeat(3, minmax(0, 1fr))" in source


def test_the_six_texts_stand_in_both_languages():
    for language, texts in TEXTS.items():
        catalogue = json.loads((ROOT / "app/locales" / f"{language}.json").read_text(encoding="utf-8"))
        held = tuple(catalogue["webapp"][key] for key in KEYS)
        assert held == texts, language
    # Silence probe: the two languages do not hold one text for the same key.
    english = json.loads((ROOT / "app/locales/en.json").read_text(encoding="utf-8"))["webapp"]
    german = json.loads((ROOT / "app/locales/de.json").read_text(encoding="utf-8"))["webapp"]
    assert all(english[key] != german[key] for key in KEYS)


def test_no_raw_picture_of_the_phone_is_in_the_repository():
    """Silence probe: only the three blurred pictures, none of the raw ones
    and none wider than 700 px."""
    tracked = subprocess.run(
        ["git", "ls-files", "--", "*ipad-*.webp"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    assert tracked.strip() == ""
    assert not list(ASSETS.glob("ipad-*"))
    held = sorted(path.name for path in ASSETS.glob("step-*"))
    assert held == sorted(PICTURES)
    for path in ASSETS.glob("step-*"):
        with Image.open(path) as picture:
            assert picture.width <= 700, path.name
