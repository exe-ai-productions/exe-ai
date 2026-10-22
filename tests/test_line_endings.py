"""SVG, HTML, script, component, style sheet and shell files keep LF line endings on every platform.

The frontend build hashes the raw bytes of a file into its output name; a
checkout that turns LF into CRLF (Windows with `core.autocrlf`) would give the
same file a different name, and a shell script with CRLF does not run. The rule lives in `.gitattributes` at the root of
the repository. The test reads only that file and never calls git, so it also
runs in an unpacked copy without a `.git` folder.
"""

from __future__ import annotations

from pathlib import Path

ATTRIBUTES = Path(__file__).resolve().parent.parent / ".gitattributes"


def _rules() -> dict[str, list[str]]:
    rules: dict[str, list[str]] = {}
    for line in ATTRIBUTES.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        pattern, *attributes = line.split()
        rules[pattern] = attributes
    return rules


PATTERNS = ("*.svg", "*.html", "*.js", "*.svelte", "*.css", "*.sh")


def test_svg_and_html_are_text_with_lf_in_every_checkout():
    rules = _rules()
    for pattern in ("*.svg", "*.html"):
        assert pattern in rules, f"no rule for {pattern}"
        assert sorted(rules[pattern]) == ["eol=lf", "text"], rules[pattern]


def test_scripts_styles_and_components_are_text_with_lf_in_every_checkout():
    rules = _rules()
    for pattern in ("*.js", "*.svelte", "*.css", "*.sh"):
        assert pattern in rules, f"no rule for {pattern}"
        assert sorted(rules[pattern]) == ["eol=lf", "text"], rules[pattern]


def test_no_other_pattern_has_a_rule():
    assert sorted(_rules()) == sorted(PATTERNS)
