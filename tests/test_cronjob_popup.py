"""Settings › Cronjobs: a schedule is made in the calendar and nowhere else.

The form stands in a pop-up beside the day clicked in the month (or beside
"Change"), the settings shell offers no "New cronjob" button any more, and
Escape closes the pop-up without taking the settings page with it. Read off
the source, the way the other interface tests do.
"""

from __future__ import annotations

from pathlib import Path

FRONTEND = Path(__file__).resolve().parent.parent / "frontend/src"
SEITE = (FRONTEND / "teile/SettingsCronjobs.svelte").read_text(encoding="utf-8")
FORM = (FRONTEND / "teile/ScheduleForm.svelte").read_text(encoding="utf-8")
HUELLE = (FRONTEND / "teile/SystemPrompt.svelte").read_text(encoding="utf-8")
LEISTE = (FRONTEND / "teile/ModulCronjobs.svelte").read_text(encoding="utf-8")


def test_die_seite_zeigt_den_kalender_und_oeffnet_das_formular_im_popup():
    assert "<ScheduleCalendar {kalender} gross onpick={tagGeklickt} />" in SEITE
    assert 'popover="auto"' in SEITE
    # A day clicked opens the form for a new schedule beside that day.
    klick = SEITE.split("function tagGeklickt(day, anker) {", 1)[1].split("\n  }\n", 1)[0]
    assert "form = { entry: null }" in klick
    assert "zeigen(anker)" in klick
    # "Change" opens the same pop-up with the schedule.
    assert "form = { entry: zeile }" in SEITE
    assert "<ScheduleForm entry={form.entry}" in SEITE


def test_escape_schliesst_nur_das_popup():
    """The window's key handler closes the settings page on Escape; the
    pop-up holds the focus and keeps the key to itself."""
    assert "onkeydown={taste}" in SEITE
    taste = SEITE.split("function taste(ev) {", 1)[1].split("\n  }\n", 1)[0]
    assert "ev.key === 'Escape'" in taste
    assert "ev.stopPropagation()" in taste
    assert "popup.focus()" in SEITE
    assert 'tabindex="-1"' in SEITE


def test_es_gibt_keinen_knopf_neuer_cronjob_mehr():
    """Only the agents page keeps the head's button."""
    assert "cronjobsTeil" not in HUELLE
    assert "istCronjobs ? cronjobsTeil" not in HUELLE
    assert "export function neu()" not in SEITE
    # Silence probe: the rail chooses a day and opens nothing.
    assert "onpick" not in LEISTE
    assert "popover" not in LEISTE


def test_art_und_wiederholung_sind_auswahlfelder():
    assert "<Auswahlfeld bind:wert={kind} eintraege={kindChoice}" in FORM
    assert "<Auswahlfeld bind:wert={repeat} eintraege={repeatChoice}" in FORM
    assert 'class="segments"' not in FORM
    # Side by side, one size: both foot buttons take half the row.
    fuss = FORM.split("  .foot {", 1)[1].split("}", 1)[0]
    assert "grid-template-columns: 1fr 1fr" in fuss


# --- the fields in the pop-up: glass with the house's field outline -------

GLOBAL = (FRONTEND / "stil/global.css").read_text(encoding="utf-8")
KALENDER = (FRONTEND / "teile/ScheduleCalendar.svelte").read_text(encoding="utf-8")
AUSWAHL = (FRONTEND / "teile/Auswahlfeld.svelte").read_text(encoding="utf-8")


def _luminance(colour: str) -> float:
    """Relative luminance of a #rrggbb colour, as the contrast formula wants it."""
    channels = []
    for i in (1, 3, 5):
        c = int(colour[i : i + 2], 16) / 255
        channels.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    r, g, b = channels
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a: str, b: str) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _block(selector: str) -> str:
    """The declarations of one look, by its selector — which must open exactly one block."""
    assert GLOBAL.count(selector + " {") == 1, selector
    return GLOBAL.split(selector + " {", 1)[1].split("\n}", 1)[0]


def test_die_felder_im_popup_sind_glas_mit_dem_feldrand():
    feld = FORM.split("  .field input,", 1)[1].split("}", 1)[0]
    assert "background: var(--glass-button)" in feld
    assert "border: 1px solid var(--feldstrich)" in feld
    assert "transparent" not in feld
    # No plain surface is left in the form: chips and foot buttons are glass too.
    assert "var(--bg-hoch)" not in FORM
    # The selection fields carry the same outline (glass is their one way).
    glas = AUSWAHL.split("  .feld {", 1)[1].split("}", 1)[0]
    assert "border: 1px solid var(--feldstrich)" in glas
    # Silence probe: the day line and the month grid stay without an edge.
    assert "feldstrich" not in KALENDER


def test_der_feldrand_haelt_drei_zu_eins_auf_dem_feld_in_jedem_hellen_look():
    """Pearl, Heaven and Moune: the outline is a boundary, so it holds the
    non-text minimum of 3 : 1 against the field it surrounds."""
    for selector in (":root", ":root[data-modus='heaven']", ":root[data-modus='moune']"):
        block = _block(selector)
        edge = block.split("--feldstrich: ", 1)[1].split(";", 1)[0]
        field = block.split("--bg-hoch: ", 1)[1].split(";", 1)[0]
        assert edge.startswith("#"), (selector, edge)
        assert _contrast(edge, field) >= 3.0, (selector, edge, field, _contrast(edge, field))


def test_die_dunklen_looks_zeichnen_die_glaskante_als_feldrand():
    for selector in (
        ":root[data-modus='dunkel']",
        ":root[data-modus='darkmatter']",
        # the auto-dark copy of Exe for a device in dark mode
        ":root:not([data-modus='hell'], [data-eigen='hell'])",
    ):
        block = _block(selector)
        assert "--feldstrich: var(--glass-button-edge);" in block, selector
