"""The version of an accessory in the model catalogue is named after the
format of its file (`frontend/src/lib/modellempfehlungen.js`).

Run rather than read: the catalogue module is loaded by Node and its lists
are asked, so a name built in a helper is seen as the card reads it.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parent.parent
FRONTEND = WURZEL / "frontend"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")


def _catalogue() -> dict:
    """Every picture model and every accessory of the catalogue, with the
    versions' name, id, file and target."""
    driver = FRONTEND / f"zubehoer-{os.getpid()}.pruefung.mjs"
    driver.write_text(
        "import { KATALOG_BILD, KATALOG_ZUBEHOER } from './src/lib/modellempfehlungen.js'\n"
        "const flat = (list) => list.map((e) => ({ id: e.id, fassungen: e.fassungen }))\n"
        "console.log('---REPORT---' + JSON.stringify({ bild: flat(KATALOG_BILD), zubehoer: flat(KATALOG_ZUBEHOER) }))\n",
        encoding="utf-8",
    )
    try:
        run = subprocess.run(
            ["node", driver.name], cwd=FRONTEND, capture_output=True, text=True, encoding="utf-8", timeout=60,
        )
    finally:
        driver.unlink(missing_ok=True)
    assert run.returncode == 0, (run.stdout + run.stderr)[-3000:]
    return json.loads(run.stdout.split("---REPORT---", 1)[1].strip())


@needs_node
def test_each_accessory_version_is_named_after_the_format_of_its_file():
    """The one version of an accessory used to be called "Datei" in every
    window language; the picture models beside it name theirs after the
    format. An accessory's version now does the same, whatever its file's
    extension is, and the name is the one identifier in both languages."""
    catalogue = _catalogue()
    assert len(catalogue["zubehoer"]) >= 13
    for entry in catalogue["zubehoer"]:
        assert entry["fassungen"], entry["id"]
        for version in entry["fassungen"]:
            assert version["name"] == version["datei"].rsplit(".", 1)[1], entry["id"]
            assert version["name"] != "Datei", entry["id"]
    # Today every accessory is a safetensors file.
    names = {v["name"] for e in catalogue["zubehoer"] for v in e["fassungen"]}
    assert names <= {"safetensors", "gguf"} and "safetensors" in names


@needs_node
def test_the_other_parts_of_an_accessory_and_the_picture_models_stay():
    """The silence probe: the picture models keep `safetensors`, and every
    accessory keeps its repository id, its file, its target name and its
    size next to the new name."""
    catalogue = _catalogue()
    named = {e["id"]: {v["name"] for v in e["fassungen"]} for e in catalogue["bild"]}
    for kept in ("cyberrealistic-xl", "juggernaut-xl", "animagine-xl"):
        assert named[kept] == {"safetensors"}, kept
    # A new picture model is named after the format of its own file.
    assert named["qwen-image-21"] == {"4-Bit · Q4_K_M"}
    by_id = {e["id"]: e["fassungen"][0] for e in catalogue["zubehoer"]}
    mse = by_id["vae-mse-15"]
    assert mse["id"] == "stabilityai/sd-vae-ft-mse-original"
    assert mse["datei"] == "vae-ft-mse-840000-ema-pruned.safetensors"
    assert mse["groesse"] == 0.34
    assert "ziel" not in mse
    lcm = by_id["lora-lcm-15"]
    assert lcm["id"] == "latent-consistency/lcm-lora-sdv1-5"
    assert lcm["datei"] == "pytorch_lora_weights.safetensors"
    assert lcm["ziel"] == "lcm-lora-sdv1-5.safetensors"
    assert set(lcm) == {"id", "name", "datei", "ziel", "groesse"}
