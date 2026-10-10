"""What a picture says about how it was made.

sd.cpp writes the prompt and its settings into the picture it draws, as one
text in the style other painters use ("parameters": the prompt, then
"Negative prompt: …", then a line of "Key: value" pairs). ``sd-cli -M
metadata`` reads that text back out of a PNG or JPEG; this module asks it
and turns the text into the values the picture window has fields for.

Only a picture somebody hands in is read, and only when asked: nothing here
runs over the pictures folder or keeps what it read.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import Path

from app.no_console import no_window

log = logging.getLogger(__name__)

# Reading the text out of a picture takes a moment, never minutes.
TIMEOUT = 30

# The keys of the settings line this module hands on, and the name each one
# goes by in the window's request.
_KEYS = {
    "Steps": "schritte",
    "CFG scale": "cfg",
    "Guidance": "guidance",
    "Seed": "seed",
    "Model": "modell",
    "Unet": "diffusion_model",
    "VAE": "vae",
}
_FILE_KEYS = ("modell", "diffusion_model", "vae")


def parameters_text(metadata: dict) -> str | None:
    """The "parameters" text in ``sd-cli -M metadata --metadata-format
    json``'s answer: a PNG text chunk names it by ``keyword``, a JPEG's
    comment by ``label``."""
    found: list[str] = []

    def walk(node) -> None:
        if isinstance(node, dict):
            name = node.get("keyword") or node.get("label")
            if name == "parameters" and isinstance(node.get("text"), str):
                found.append(node["text"])
                return
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(metadata)
    return found[0] if found else None


def _number(text: str):
    try:
        number = float(text)
    except ValueError:
        return None
    return int(number) if number.is_integer() else number


def parse(text: str) -> dict:
    """The window's values out of one "parameters" text. A key the text
    does not carry is left out, never guessed."""
    lines = text.rstrip().split("\n")
    # The settings line is the last one that starts with "Steps: ".
    settings_at = max(
        (i for i, line in enumerate(lines) if line.startswith("Steps: ")), default=None
    )
    head = lines if settings_at is None else lines[:settings_at]
    negative_at = next(
        (i for i, line in enumerate(head) if line.startswith("Negative prompt: ")), None
    )
    values: dict = {}
    prompt = "\n".join(head if negative_at is None else head[:negative_at]).strip()
    if prompt:
        values["prompt"] = prompt
    if negative_at is not None:
        negative = "\n".join(head[negative_at:])[len("Negative prompt: "):].strip()
        if negative:
            values["negativ"] = negative
    if settings_at is None:
        return values
    settings = "\n".join(lines[settings_at:])
    # "Key: value" up to the next ", Key: " — a value such as a prompt of
    # the detailer may hold commas of its own.
    pairs = re.findall(r"(?:^|, )([A-Z][A-Za-z ]*?): (.*?)(?=, [A-Z][A-Za-z ]*?: |, ?$|$)",
                       settings, re.S)
    for key, value in pairs:
        value = value.strip()
        if key in _KEYS:
            name = _KEYS[key]
            if name in _FILE_KEYS:
                if value:
                    values[name] = value
            elif (number := _number(value)) is not None:
                values[name] = number
        elif key == "Size":
            size = re.fullmatch(r"(\d+)x(\d+)", value)
            if size:
                values["breite"], values["hoehe"] = int(size.group(1)), int(size.group(2))
        elif key == "Sampler":
            # "euler_a karras": the sampler, then the scheduler when one was
            # named; a list of sigmas stands where no scheduler was used.
            sampler, _, scheduler = value.partition(" ")
            values["sampler"] = sampler
            if scheduler and not scheduler.startswith("["):
                values["scheduler"] = scheduler
    return values


def read(program: Path, picture: Path) -> dict:
    """The values ``picture`` carries — empty when it carries none."""
    try:
        result = subprocess.run(
            [str(program), "-M", "metadata", "--image", str(picture), "--metadata-format", "json"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=TIMEOUT, check=False,
            **no_window(),
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        log.warning("Picture info could not be read: %s", error)
        return {}
    try:
        metadata = json.loads(result.stdout)
    except ValueError:
        return {}
    text = parameters_text(metadata)
    return parse(text) if text else {}
