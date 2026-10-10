"""The permission mode switch — Auto / Manuell / Restricted.

A mode is a shortcut into berechtigungen.json (app/berechtigungswahl.py), not
a thing Tor 3 evaluates on its own — so the tests here check both ends: the
cascade value the switch is, and the two lines it writes.
"""

from __future__ import annotations

import json
from pathlib import Path

from app import berechtigungen, berechtigungswahl
from app.berechtigungsregeln import Regeldatei, laden

WURZEL = Path(__file__).resolve().parent.parent


def test_gueltige_werte_kommen_durch():
    assert berechtigungswahl.wahl_pruefen("auto") == "auto"
    assert berechtigungswahl.wahl_pruefen("manuell") == "manuell"
    assert berechtigungswahl.wahl_pruefen("restricted") == "restricted"


def test_unbekannter_wert_faellt_raus():
    assert berechtigungswahl.wahl_pruefen("frei") is None
    assert berechtigungswahl.wahl_pruefen(None) is None
    assert berechtigungswahl.wahl_pruefen(3) is None


def test_auto_setzt_beide_felder_auf_ja(tmp_path):
    pfad = tmp_path / "berechtigungen.json"
    berechtigungswahl.anwenden(pfad, "chat", "auto")

    rohdaten = json.loads(pfad.read_text(encoding="utf-8"))
    assert rohdaten["standard"]["chat"] == "ja"
    assert rohdaten["dateien"]["innerhalb_der_ordner"]["chat"] == "ja"
    assert rohdaten["dateien"]["ausserhalb_der_ordner"]["chat"] == "ja"


def test_restricted_fragt_auch_innerhalb_des_ordners(tmp_path):
    pfad = tmp_path / "berechtigungen.json"
    berechtigungswahl.anwenden(pfad, "agent", "restricted")

    regeln = laden(pfad)
    assert regeln.innerhalb_der_ordner["agent"] == "fragen"
    assert regeln.ausserhalb_der_ordner["agent"] == "fragen"
    # An agent cannot be asked — Tor 3 turns both into "nein" on its own.
    urteil = berechtigungen.urteil(
        "read_file", {"path": "notiz.md"}, [str(tmp_path)], "agent", regeln=regeln,
    )
    assert urteil.antwort == "nein"


def test_ein_modus_laesst_die_andere_herkunft_unangetastet(tmp_path):
    pfad = tmp_path / "berechtigungen.json"
    berechtigungswahl.anwenden(pfad, "chat", "restricted")
    berechtigungswahl.anwenden(pfad, "agent", "auto")

    regeln = laden(pfad)
    assert regeln.innerhalb_der_ordner == {"chat": "fragen", "agent": "ja"}
    assert regeln.ausserhalb_der_ordner == {"chat": "fragen", "agent": "ja"}
    assert regeln.standard == {"chat": "fragen", "agent": "ja"}


def test_ein_modus_laesst_andere_regeln_unangetastet(tmp_path):
    pfad = tmp_path / "berechtigungen.json"
    pfad.write_text(
        json.dumps({"regeln": {"web_search": "nein"}, "niemals": ["rm -rf /"]}),
        encoding="utf-8",
    )
    berechtigungswahl.anwenden(pfad, "chat", "auto")

    regeln = laden(pfad)
    assert regeln.regeln == {"web_search": "nein"}
    assert regeln.niemals == ("rm -rf /",)


def test_altes_kurzformat_bei_standard_wird_nicht_verworfen(tmp_path):
    # A file written before the chat/agent split still has `"standard": "fragen"`
    # as a bare string, meaning both origins. Applying a mode for one origin
    # must not wipe the other origin's half of that shorthand down to the
    # class default.
    pfad = tmp_path / "berechtigungen.json"
    pfad.write_text(json.dumps({"standard": "fragen"}), encoding="utf-8")
    berechtigungswahl.anwenden(pfad, "chat", "auto")

    regeln = laden(pfad)
    assert regeln.standard == {"chat": "ja", "agent": "fragen"}


def test_kaputte_datei_wird_aus_den_vorgaben_neu_angelegt(tmp_path):
    pfad = tmp_path / "berechtigungen.json"
    pfad.write_text("{kaputt", encoding="utf-8")
    berechtigungswahl.anwenden(pfad, "chat", "manuell")

    regeln = laden(pfad)
    assert regeln.kaputt is None
    assert regeln.standard["chat"] == "fragen"


def test_die_route_speichert_und_schreibt_die_regeldatei(client, config):
    antwort = client.put(
        "/api/v1/settings/global/berechtigungsmodus_agent", json={"wert": "restricted"}
    )
    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["wert"] == "restricted"


def test_ein_gescopter_bereich_schreibt_die_datei_nicht(client, config):
    """There is one shared rule file, not one per chat — a scoped write must
    not silently lock down the file for everyone."""
    vorher = laden(config.pfad(config.app.berechtigungen_datei))

    antwort = client.put(
        "/api/v1/settings/chat:irgendein-chat/berechtigungsmodus_chat",
        json={"wert": "restricted"},
    )
    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["wert"] == "restricted"

    nachher = laden(config.pfad(config.app.berechtigungen_datei))
    assert nachher.innerhalb_der_ordner == vorher.innerhalb_der_ordner
    assert nachher.ausserhalb_der_ordner == vorher.ausserhalb_der_ordner


def test_loeschen_setzt_die_datei_auf_manuell_zurueck(client, config):
    client.put("/api/v1/settings/global/berechtigungsmodus_chat", json={"wert": "restricted"})
    zwischendurch = laden(config.pfad(config.app.berechtigungen_datei))
    assert zwischendurch.innerhalb_der_ordner["chat"] == "fragen"

    antwort = client.put(
        "/api/v1/settings/global/berechtigungsmodus_chat", json={"wert": None}
    )
    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["wert"] is None

    regeln = laden(config.pfad(config.app.berechtigungen_datei))
    assert regeln.innerhalb_der_ordner["chat"] == "ja"
    assert regeln.ausserhalb_der_ordner["chat"] == "fragen"


def test_standard_als_einzelner_text_setzt_beide_herkuenfte(tmp_path):
    """A bare "ja"/"fragen"/"nein", written before this field had a
    chat/agent split, still reads without forcing a rewrite."""
    pfad = tmp_path / "berechtigungen.json"
    pfad.write_text(json.dumps({"standard": "fragen"}), encoding="utf-8")
    regeln = laden(pfad)
    assert regeln.standard == {"chat": "fragen", "agent": "fragen"}


def test_standard_je_herkunft_wird_gelesen(tmp_path):
    pfad = tmp_path / "berechtigungen.json"
    pfad.write_text(
        json.dumps({"standard": {"chat": "fragen", "agent": "nein"}}), encoding="utf-8"
    )
    regeln = laden(pfad)
    assert regeln.standard == {"chat": "fragen", "agent": "nein"}


def test_regeldatei_standard_ist_je_herkunft_ja():
    assert Regeldatei().standard == {"chat": "ja", "agent": "ja"}
    assert Regeldatei().innerhalb_der_ordner == {"chat": "ja", "agent": "ja"}


def test_der_agent_traegt_ein_anderes_wort_fuer_denselben_wert():
    """"Sandboxed" on the agent side, "Manuell" on the chat side — one value.

    For a chat the three modes are a question of how often you are asked.
    An agent has nobody to answer, so `fragen` becomes `nein`
    (`berechtigungen.py`) and the same ladder stops being about frequency
    and becomes about reach: the whole disk, the shared folders, or no files
    at all. "Manuell" promises a question that is never put there.

    The guard that matters is the one below it: the stored VALUE must stay
    `manuell`. A rename that changed the value would quietly reset every
    install that has the mode set, because the cascade would no longer
    recognise what is written in it.

    Source-text, and openly so: it catches the wiring coming apart, not
    every way a label could go wrong.
    """
    liste = (WURZEL / "frontend/src/lib/berechtigungsmodus.svelte.js").read_text(encoding="utf-8")

    # The values are the contract with the cascade and must not move.
    for wert in ("auto", "manuell", "restricted"):
        assert f"'{wert}'" in liste, f"the value {wert} has left the list"
    assert berechtigungswahl.GUELTIGE_MODI == {"auto", "manuell", "restricted"}

    assert "modus_agent_manuell" in liste, "the agent column lost its own word"

    # Only the job dialog asks for the agent's wording; the chat's mode chip
    # in the input bar must not, or both sides would say "Sandboxed".
    auftrag = (WURZEL / "frontend/src/teile/AuftragStarten.svelte").read_text(encoding="utf-8")
    leiste = (WURZEL / "frontend/src/teile/Eingabeleiste.svelte").read_text(encoding="utf-8")
    assert "modusOptionen('agent')" in auftrag
    assert "modusOptionen()" in leiste
    assert "modusOptionen('agent')" not in leiste


def test_beide_kataloge_kennen_das_agentenwort():
    """A missing key would render as the raw key path in the dialog."""
    for datei in ("de.json", "en.json"):
        texte = json.loads((WURZEL / "app/locales" / datei).read_text(encoding="utf-8"))
        assert texte["berechtigungen"]["modus_agent_manuell"] == "Sandboxed"
