"""Reads the style block of the schedule page, for the checks on how its views are laid out."""

from __future__ import annotations

import re
from pathlib import Path

FRONTEND = Path(__file__).resolve().parent.parent / "frontend" / "src"
PAGE = FRONTEND / "teile" / "SettingsCronjobs.svelte"
PHONE = ":global(html[data-phone])"
CONTAINER = re.compile(r"@container [^{]*\{((?:[^{}]*\{[^{}]*\})+)\s*\}")


def without_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def style() -> str:
    """The style block of the page without its comments."""
    source = PAGE.read_text(encoding="utf-8")
    block = re.search(r"<style>(.*)</style>", source, re.S)
    assert block is not None
    return without_comments(block.group(1))


def rules(css: str) -> dict[str, str]:
    """Each selector of a piece of style with its declarations."""
    found: dict[str, str] = {}
    for selector, body in re.findall(r"([^{}@]+)\{([^{}]*)\}", css):
        key = " ".join(selector.split())
        found[key] = found.get(key, "") + " " + " ".join(body.split())
    return found


def declared(rule: str, name: str) -> str | None:
    """The value of a property in a rule; the last declaration wins, as it does in the browser."""
    values = re.findall(rf"(?:^|[;\s]){re.escape(name)}:\s*([^;]+)", rule)
    return values[-1].strip() if values else None


def base_rules() -> dict[str, str]:
    """The rules that hold at every width, without those that hold only in a narrow view."""
    return rules(CONTAINER.sub("", style()))


def pixels(value: str | None) -> list[int]:
    """The pixel values in a declared value, in order."""
    assert value is not None
    return [int(number) for number in re.findall(r"(\d+)px", value)]
