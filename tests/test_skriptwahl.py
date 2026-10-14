"""A script picked off the wall is spent when the form it opened is closed.

Left standing, the pick opened the next form by itself (when the schedules
were opened again) and kept its ring on the wall. The wall lives in Settings ›
Schedules now, under the schedule list, and the list's own form is the one it
opens. The view is Svelte, so this reads the places that carry the rule: the
store that offers the reset and the list that calls it when its form closes.
"""

from pathlib import Path

FRONTEND = Path(__file__).resolve().parent.parent / "frontend/src"


def test_die_wahl_wird_beim_schliessen_des_formulars_geleert():
    speicher = (FRONTEND / "lib/skriptwahl.svelte.js").read_text(encoding="utf-8")
    liste = (FRONTEND / "teile/SettingsCronjobs.svelte").read_text(encoding="utf-8")
    assert "export function skriptWahlLeeren()" in speicher
    schliessen = liste.split("function geschlossen(row, own = form) {", 1)[1].split("\n  }\n", 1)[0]
    assert "skriptWahlLeeren()" in schliessen, "closing the form leaves the pick standing"
    # Leaving the page with the form still open spends the pick too.
    assert "$effect(() => () => skriptWahlLeeren())" in liste
    # A pick opens the page's own form with the script.
    wahl = liste.split("void skriptwahl.lauf", 1)[1].split("\n  })", 1)[0]
    assert "if (!skriptwahl.name) return" in wahl
    assert "form = { entry: null, script: name }" in wahl
    # Silence probe: opening the form from the calendar never reads or sets the pick.
    oeffnen = liste.split("function tagGeklickt(day, anker) {", 1)[1].split("\n  }\n", 1)[0]
    assert "skriptwahl" not in oeffnen


def test_der_skriptordner_steht_in_den_einstellungen_nicht_in_der_leiste():
    einstellungen = (FRONTEND / "teile/SystemPrompt.svelte").read_text(encoding="utf-8")
    teil = einstellungen.split("{:else if istCronjobs}", 1)[1].split("{:else if", 1)[0]
    assert teil.index("<SettingsCronjobs") < teil.index("<Skriptordner />")
    assert "t('cronjobs.abschnitt_skripte')" in teil
    # The settings page's schedule part opens its own form on a pick.
    seite = (FRONTEND / "teile/SettingsCronjobs.svelte").read_text(encoding="utf-8")
    assert "void skriptwahl.lauf" in seite
    assert "form = { entry: null, script: name }" in seite
    # Schweigeprobe: the rail neither shows the wall nor listens for a pick.
    leiste = (FRONTEND / "teile/ModulCronjobs.svelte").read_text(encoding="utf-8")
    assert "Skriptordner" not in leiste
    assert "skriptwahl" not in leiste
