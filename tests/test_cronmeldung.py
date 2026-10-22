"""Playing a sound and showing a cron entry's task text once its run has
ended (app/cronmeldung.py).

``melden()`` itself is only ever exercised with ``subprocess.run`` swapped
out — nothing here actually plays a sound or pops up a notification on
whatever machine runs the tests. What is testable, and what breaks
silently, is the built command text (a wrong quote does not crash, it just
shows the wrong thing, and a wrong path just plays nothing) and the
handling around the real call: a missing tool, and a command that ran but
failed.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app import cronmeldung
from app.cronmeldung import (
    TITEL,
    _klang_befehl_macos,
    _klang_befehl_windows,
    _klang_pfad,
    _mitteilung_befehl_macos,
    _mitteilung_befehl_windows,
)


def _mit_titel(titel: str) -> SimpleNamespace:
    return SimpleNamespace(app=SimpleNamespace(meldetitel=titel))


@pytest.fixture(autouse=True)
def shipped_switches(monkeypatch):
    """The shipped switches, whatever an earlier test's service stored."""
    monkeypatch.setattr(cronmeldung, "_repositories", None)


@pytest.fixture(autouse=True)
def hausname(monkeypatch):
    """Every test in this file builds its command against the shipped name.

    Without this the command builders read the real configuration of
    whoever runs the suite — a test service with a name of its own in
    EXE_AI_CONFIG turned four of these red — and loading that config from
    a test also lets the migration write into the developer's own file.
    """
    monkeypatch.setattr(cronmeldung, "get_config", lambda: _mit_titel(""))


# --- verfuegbar() ----------------------------------------------------------


def test_verfuegbar_auf_macos_braucht_nur_osascript(monkeypatch):
    monkeypatch.setattr(cronmeldung.sys, "platform", "darwin")
    monkeypatch.setattr(
        cronmeldung.shutil, "which", lambda name: "/usr/bin/osascript" if name == "osascript" else None
    )
    assert cronmeldung.verfuegbar() is True


def test_nicht_verfuegbar_auf_macos_ohne_osascript(monkeypatch):
    monkeypatch.setattr(cronmeldung.sys, "platform", "darwin")
    monkeypatch.setattr(cronmeldung.shutil, "which", lambda name: None)
    assert cronmeldung.verfuegbar() is False


def test_verfuegbar_auf_windows_mit_powershell(monkeypatch):
    monkeypatch.setattr(cronmeldung.sys, "platform", "win32")
    monkeypatch.setattr(cronmeldung.shutil, "which", lambda name: f"C:\\{name}")
    assert cronmeldung.verfuegbar() is True


def test_nicht_verfuegbar_auf_windows_ohne_powershell(monkeypatch):
    monkeypatch.setattr(cronmeldung.sys, "platform", "win32")
    monkeypatch.setattr(cronmeldung.shutil, "which", lambda name: None)
    assert cronmeldung.verfuegbar() is False


# --- Which sound is picked --------------------------------------------


def test_sound_path_of_a_good_ending_is_the_agent_cronjob_sound():
    pfad = _klang_pfad(True)
    assert pfad.name == "agent-cronjob.wav"
    assert pfad.is_file()
    assert pfad.is_absolute()
    assert pfad.parent.parent == cronmeldung.paketierung.ressourcen() / "static"


def test_klang_pfad_fehler_zeigt_auf_fehler_wav():
    pfad = _klang_pfad(False)
    assert pfad.name == "fehler.wav"
    assert pfad.is_file()
    assert pfad.is_absolute()
    assert pfad.parent.parent == cronmeldung.paketierung.ressourcen() / "static"


# --- macOS command text -------------------------------------------------


def test_macos_klang_befehl_nennt_afplay_und_pfad():
    befehl = _klang_befehl_macos(Path("/irgendwo/agent-cronjob.wav"))
    assert befehl[0] == "afplay"
    assert befehl[-1] == str(Path("/irgendwo/agent-cronjob.wav"))


def test_macos_sound_command_carries_the_volume_as_a_factor():
    assert _klang_befehl_macos(Path("/a.wav"), 70)[:3] == ["afplay", "-v", "0.7"]
    assert _klang_befehl_macos(Path("/a.wav"), 100)[:3] == ["afplay", "-v", "1"]
    assert _klang_befehl_macos(Path("/a.wav"), 5)[:3] == ["afplay", "-v", "0.05"]


def test_macos_mitteilung_traegt_titel_und_text():
    schrift = _mitteilung_befehl_macos("Plant reminder")[-1]
    assert "Plant reminder" in schrift
    assert TITEL in schrift


def test_macos_mitteilung_entschaerft_anfuehrungszeichen():
    schrift = _mitteilung_befehl_macos('Sag "Hallo"')[-1]
    assert '\\"Hallo\\"' in schrift


# --- Which name the notification carries -----------------------------------


def test_ohne_eigenen_titel_meldet_sich_der_hausname(monkeypatch):
    """Nothing about a shipped install changes: an empty field is the
    program's own name."""
    monkeypatch.setattr(cronmeldung, "get_config", lambda: _mit_titel(""))
    assert TITEL in _mitteilung_befehl_macos("Plant reminder")[-1]
    assert TITEL in _mitteilung_befehl_windows("Plant reminder")[-1]


def test_ein_pruefstand_meldet_sich_unter_seinem_eigenen_namen(monkeypatch):
    """Two installs on one machine: a schedule fired by the test service
    used to announce itself under the shipped program's name, and the
    notification said nothing about which of the two had spoken."""
    monkeypatch.setattr(cronmeldung, "get_config", lambda: _mit_titel("Test service 8095"))
    schrift = _mitteilung_befehl_macos("Plant reminder")[-1]
    assert "Test service 8095" in schrift
    assert TITEL not in schrift
    assert "Test service 8095" in _mitteilung_befehl_windows("Plant reminder")[-1]


def test_ein_titel_mit_anfuehrungszeichen_wird_entschaerft(monkeypatch):
    """The same care the text gets: a quote in the name would end the
    AppleScript string early and show something else entirely."""
    monkeypatch.setattr(cronmeldung, "get_config", lambda: _mit_titel('Exe "8095"'))
    assert '\\"8095\\"' in _mitteilung_befehl_macos("egal")[-1]
    monkeypatch.setattr(cronmeldung, "get_config", lambda: _mit_titel("Max's Exe"))
    assert "Max''s Exe" in _mitteilung_befehl_windows("egal")[-1]


def test_eine_unlesbare_konfiguration_nimmt_den_hausnamen(monkeypatch):
    """A notification must not need a config to be shown at all."""

    def platzt():
        raise RuntimeError("keine Konfiguration")

    monkeypatch.setattr(cronmeldung, "get_config", platzt)
    assert TITEL in _mitteilung_befehl_macos("Plant reminder")[-1]


# --- Windows command text -----------------------------------------------


def test_windows_klang_befehl_nennt_soundplayer_und_pfad():
    schrift = _klang_befehl_windows(Path(r"C:\irgendwo\fehler.wav"))[-1]
    assert "SoundPlayer" in schrift
    assert r"C:\irgendwo\fehler.wav" in schrift
    assert "PlaySync" in schrift


def test_windows_klang_befehl_verdoppelt_apostrophe():
    schrift = _klang_befehl_windows(Path("C:\\Max's Sounds\\fehler.wav"))[-1]
    assert "Max''s Sounds" in schrift


def test_windows_mitteilung_zeigt_text_und_haelt_die_blase_offen():
    schrift = _mitteilung_befehl_windows("Plant reminder")[-1]
    assert "Plant reminder" in schrift
    assert "ShowBalloonTip" in schrift
    assert "Start-Sleep" in schrift


def test_windows_mitteilung_verdoppelt_apostrophe():
    schrift = _mitteilung_befehl_windows("Max's Auftrag")[-1]
    assert "Max''s Auftrag" in schrift


# --- melden() end to end, subprocess replaced ---------------------------


def test_macos_erfolg_spielt_klang_und_zeigt_unveraenderten_text(monkeypatch):
    monkeypatch.setattr(cronmeldung.sys, "platform", "darwin")
    monkeypatch.setattr(cronmeldung.shutil, "which", lambda name: f"/usr/bin/{name}")
    aufrufe = []
    monkeypatch.setattr(
        cronmeldung.subprocess, "run",
        lambda befehl, **k: aufrufe.append(befehl) or SimpleNamespace(returncode=0),
    )

    cronmeldung.melden("Plant reminder", erfolgreich=True)

    assert len(aufrufe) == 2
    assert aufrufe[0][0] == "afplay"
    assert aufrufe[0][:3] == ["afplay", "-v", "0.7"]
    assert "agent-cronjob.wav" in aufrufe[0][-1]
    assert aufrufe[1][0] == "osascript"
    assert "Plant reminder" in aufrufe[1][-1]
    assert not any("say" in befehl for befehl in aufrufe)


def test_macos_fehlschlag_spielt_fehler_klang_und_nennt_ihn_in_der_mitteilung(monkeypatch):
    monkeypatch.setattr(cronmeldung.sys, "platform", "darwin")
    monkeypatch.setattr(cronmeldung.shutil, "which", lambda name: f"/usr/bin/{name}")
    aufrufe = []
    monkeypatch.setattr(
        cronmeldung.subprocess, "run",
        lambda befehl, **k: aufrufe.append(befehl) or SimpleNamespace(returncode=0),
    )

    cronmeldung.melden("Plant reminder", erfolgreich=False)

    assert "fehler.wav" in aufrufe[0][-1]
    assert "Plant reminder" in aufrufe[1][-1]
    assert "Failed" in aufrufe[1][-1]


def test_macos_ohne_afplay_zeigt_wenigstens_die_mitteilung(monkeypatch):
    """A missing playback tool must not silence the
    notification too — only ``osascript`` is essential."""
    monkeypatch.setattr(cronmeldung.sys, "platform", "darwin")
    monkeypatch.setattr(
        cronmeldung.shutil, "which", lambda name: "/usr/bin/osascript" if name == "osascript" else None
    )
    aufrufe = []
    monkeypatch.setattr(
        cronmeldung.subprocess, "run",
        lambda befehl, **k: aufrufe.append(befehl) or SimpleNamespace(returncode=0),
    )

    cronmeldung.melden("Plant reminder", erfolgreich=True)

    assert len(aufrufe) == 1
    assert aufrufe[0][0] == "osascript"


def test_macos_ohne_osascript_meldet_sich_gar_nichts(monkeypatch):
    monkeypatch.setattr(cronmeldung.sys, "platform", "darwin")
    monkeypatch.setattr(cronmeldung.shutil, "which", lambda name: None)
    aufrufe = []
    monkeypatch.setattr(
        cronmeldung.subprocess, "run",
        lambda befehl, **k: aufrufe.append(befehl) or SimpleNamespace(returncode=0),
    )

    cronmeldung.melden("Plant reminder", erfolgreich=True)

    assert aufrufe == []


def test_windows_spielt_klang_und_zeigt_mitteilung(monkeypatch):
    monkeypatch.setattr(cronmeldung.sys, "platform", "win32")
    monkeypatch.setattr(cronmeldung.shutil, "which", lambda name: f"C:\\{name}")
    aufrufe = []
    monkeypatch.setattr(
        cronmeldung.subprocess, "run",
        lambda befehl, **k: aufrufe.append(befehl) or SimpleNamespace(returncode=0),
    )

    cronmeldung.melden("Plant reminder", erfolgreich=True)

    assert len(aufrufe) == 2
    assert "SoundPlayer" in aufrufe[0][-1]
    assert "ShowBalloonTip" in aufrufe[1][-1]
    assert not any("System.Speech" in befehl[-1] for befehl in aufrufe)


# --- A command that ran but failed leaves a trace -----------


def test_ein_fehlercode_hinterlaesst_eine_protokollzeile(monkeypatch, caplog):
    monkeypatch.setattr(cronmeldung.sys, "platform", "darwin")
    monkeypatch.setattr(cronmeldung.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        cronmeldung.subprocess, "run", lambda befehl, **k: SimpleNamespace(returncode=1)
    )

    with caplog.at_level("WARNING", logger="app.cronmeldung"):
        cronmeldung.melden("Plant reminder", erfolgreich=True)

    assert len(caplog.records) == 2  # both commands failed the same way
    klang, mitteilung = caplog.records
    assert "afplay" in klang.message
    assert "osascript" in mitteilung.message
    for eintrag in caplog.records:
        assert "1" in eintrag.message


def test_ein_abgestuerzter_befehl_haelt_die_mitteilung_nicht_auf(monkeypatch, caplog):
    """The new returncode check must not run against a
    result that was never assigned because the command itself raised —
    the notification is the second, still-essential command in the list."""
    monkeypatch.setattr(cronmeldung.sys, "platform", "darwin")
    monkeypatch.setattr(cronmeldung.shutil, "which", lambda name: f"/usr/bin/{name}")
    aufrufe = []

    def _lauf(befehl, **k):
        if befehl[0] == "afplay":
            raise OSError("afplay weg")
        aufrufe.append(befehl)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(cronmeldung.subprocess, "run", _lauf)

    with caplog.at_level("WARNING", logger="app.cronmeldung"):
        cronmeldung.melden("Plant reminder", erfolgreich=True)

    assert aufrufe == [cronmeldung._mitteilung_befehl_macos("Plant reminder")]
    assert len(caplog.records) == 1
    assert "afplay" in caplog.records[0].message


def test_ein_geglueckter_aufruf_hinterlaesst_nichts(monkeypatch, caplog):
    monkeypatch.setattr(cronmeldung.sys, "platform", "darwin")
    monkeypatch.setattr(cronmeldung.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        cronmeldung.subprocess, "run", lambda befehl, **k: SimpleNamespace(returncode=0)
    )

    with caplog.at_level("WARNING", logger="app.cronmeldung"):
        cronmeldung.melden("Plant reminder", erfolgreich=True)

    assert caplog.records == []


# --- The switches of the settings page ------------------------------------


class _Stored:
    """The settings table as far as this module reads it: one stored object
    per key, nothing for a key that was never set."""

    def __init__(self, **werte):
        self.werte = werte
        self.einstellungen = self

    def zusammengefuehrt(self, schluessel, vorgabe=None, **_):
        return self.werte.get(schluessel, vorgabe)


def _calls(monkeypatch, plattform="darwin"):
    monkeypatch.setattr(cronmeldung.sys, "platform", plattform)
    monkeypatch.setattr(cronmeldung.shutil, "which", lambda name: f"/usr/bin/{name}")
    aufrufe = []
    monkeypatch.setattr(
        cronmeldung.subprocess, "run",
        lambda befehl, **k: aufrufe.append(befehl) or SimpleNamespace(returncode=0),
    )
    return aufrufe


def _sounds(**klaenge):
    return _Stored(klaenge=klaenge)


@pytest.mark.parametrize(
    "klaenge",
    [
        {"an": False},
        {"pegel": 0},
        {"ton_agent_cronjob": False},
    ],
)
def test_without_sound_no_sound_command_runs_and_the_notification_stays(monkeypatch, klaenge):
    """The main switch, a volume of zero and the sound switch of the
    occurrence each keep the sound away on their own."""
    aufrufe = _calls(monkeypatch)
    cronmeldung.connect_settings(_sounds(**klaenge))

    cronmeldung.melden("Plant reminder", erfolgreich=True)

    assert [befehl[0] for befehl in aufrufe] == ["osascript"]


def test_the_sound_of_a_failure_has_its_own_switch(monkeypatch):
    aufrufe = _calls(monkeypatch)
    cronmeldung.connect_settings(_sounds(ton_agent_cronjob=False))

    cronmeldung.melden("Plant reminder", erfolgreich=False)

    # Failure is not the occurrence that was switched off: it still sounds.
    assert [befehl[0] for befehl in aufrufe] == ["afplay", "osascript"]
    assert "fehler.wav" in aufrufe[0][-1]


def test_without_popup_no_notification_but_the_sound(monkeypatch):
    aufrufe = _calls(monkeypatch)
    cronmeldung.connect_settings(_Stored(meldewesen={"melde_agent_cronjob": False}))

    cronmeldung.melden("Plant reminder", erfolgreich=True)

    assert [befehl[0] for befehl in aufrufe] == ["afplay"]


def test_the_popup_switch_of_a_failure_holds_for_a_failure_only(monkeypatch):
    aufrufe = _calls(monkeypatch)
    cronmeldung.connect_settings(_Stored(meldewesen={"melde_fehler": False}))

    cronmeldung.melden("Plant reminder", erfolgreich=False)
    assert [befehl[0] for befehl in aufrufe] == ["afplay"]
    aufrufe.clear()
    cronmeldung.melden("Plant reminder", erfolgreich=True)
    assert [befehl[0] for befehl in aufrufe] == ["afplay", "osascript"]


def test_the_volume_comes_from_the_settings(monkeypatch):
    aufrufe = _calls(monkeypatch)
    cronmeldung.connect_settings(_sounds(pegel=30))

    cronmeldung.melden("Plant reminder", erfolgreich=True)

    assert aufrufe[0][:3] == ["afplay", "-v", "0.3"]


def test_nothing_stored_is_the_shipped_state(monkeypatch):
    """Schweigeprobe: a store with nothing in it is the shipped state —
    everything on, at the shipped volume."""
    aufrufe = _calls(monkeypatch)
    cronmeldung.connect_settings(_Stored())

    cronmeldung.melden("Plant reminder", erfolgreich=True)

    assert [befehl[0] for befehl in aufrufe] == ["afplay", "osascript"]
    assert aufrufe[0][:3] == ["afplay", "-v", "0.7"]


def test_an_unreadable_store_gives_the_shipped_state_not_silence(monkeypatch):
    aufrufe = _calls(monkeypatch)

    class Kaputt:
        @property
        def einstellungen(self):
            raise RuntimeError("closed")

    cronmeldung.connect_settings(Kaputt())

    cronmeldung.melden("Plant reminder", erfolgreich=True)

    assert [befehl[0] for befehl in aufrufe] == ["afplay", "osascript"]


def test_windows_knows_no_volume_only_on_or_off(monkeypatch):
    aufrufe = _calls(monkeypatch, plattform="win32")
    cronmeldung.connect_settings(_sounds(pegel=30))
    cronmeldung.melden("Plant reminder", erfolgreich=True)
    assert len(aufrufe) == 2 and "SoundPlayer" in aufrufe[0][-1]

    aufrufe.clear()
    cronmeldung.connect_settings(_sounds(ton_agent_cronjob=False))
    cronmeldung.melden("Plant reminder", erfolgreich=True)
    assert len(aufrufe) == 1 and "ShowBalloonTip" in aufrufe[0][-1]


def test_the_real_route_and_the_service_read_the_same_switches(client):
    """What the settings page stores through the route is what the service
    reads when a run ends — the same key, the same field names."""
    antwort = client.put(
        "/api/v1/settings/global/klaenge",
        json={"wert": {"ton_agent_cronjob": False, "pegel": 40}},
    )
    assert antwort.status_code == 200, antwort.text
    antwort = client.put(
        "/api/v1/settings/global/meldewesen", json={"wert": {"melde_fehler": False}}
    )
    assert antwort.status_code == 200, antwort.text

    klaenge, melden_wahl = cronmeldung._switches()

    assert klaenge["ton_agent_cronjob"] is False and klaenge["pegel"] == 40
    assert klaenge["ton_fehler"] is True
    assert melden_wahl["melde_fehler"] is False and melden_wahl["melde_agent_cronjob"] is True
