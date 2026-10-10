"""Plays a sound and shows a cron entry's task text once its run has ended
(app/cronablauf.py) — an entry with ``deliver = 'announce'`` asks for this;
``'log'`` (the default) never reaches this module at all.

Two ways, both platforms: a short sound (macOS ``afplay``, Windows
PowerShell's ``System.Media.SoundPlayer``) and a system notification that
stays on screen until dismissed (macOS ``osascript``, Windows a balloon tip
via ``System.Windows.Forms`` — no third-party module, same reasoning as the
Windows folder dialog in app/ordner_dialog.py). Which sound plays depends on
how the run ended — a scheduled job fires while nobody is watching, and a
failure needs to sound different from success to be noticed at all.

Missing notification tool (macOS ``osascript``, Windows PowerShell): nothing
happens, same as an entry on 'log'. Missing sound tool alone: the
notification still shows — a fired schedule should not go silent just
because one of the two ways to notice it is gone.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from pathlib import Path

from app import i18n, paketierung
from app.config import get_config
from app.no_console import no_window

log = logging.getLogger(__name__)

# The shipped name. A test service running beside the shipped install sets
# `app.meldetitel` and speaks under its own name instead — see app/config.py.
TITEL = "Exe AI"
ZEITGRENZE_SEKUNDEN = 15
_KLANG_ERFOLG = "static/klaenge/cron-fertig.wav"
_KLANG_FEHLER = "static/klaenge/fehler.wav"


def verfuegbar() -> bool:
    """Whether this platform has the tools to notify at all."""
    if sys.platform == "darwin":
        return bool(shutil.which("osascript"))
    if sys.platform == "win32":
        return bool(_windows_powershell())
    return False


def _windows_powershell() -> str | None:
    return shutil.which("powershell.exe") or shutil.which("pwsh.exe")


def _titel() -> str:
    """The name this install's notifications carry.

    Read per notification rather than once at import: the config is loaded
    after this module, and a schedule fires long after both.
    """
    try:
        eigener = get_config().app.meldetitel.strip()
    except Exception:  # noqa: BLE001 - a notification must not need a config
        log.debug("Announcement title cannot be read, the house name is used", exc_info=True)
        return TITEL
    return eigener or TITEL


def _klang_pfad(erfolgreich: bool) -> Path:
    return paketierung.aufloesen(_KLANG_ERFOLG if erfolgreich else _KLANG_FEHLER)


def _klang_befehl_macos(pfad: Path) -> list[str]:
    return ["afplay", str(pfad)]


def _klang_befehl_windows(pfad: Path) -> list[str]:
    # System.Media ships with PowerShell itself — unlike the notification's
    # NotifyIcon (System.Windows.Forms), SoundPlayer needs no Add-Type.
    sicher = str(pfad).replace("'", "''")
    schrift = f"(New-Object Media.SoundPlayer '{sicher}').PlaySync()"
    return [_windows_powershell() or "powershell.exe", "-NoProfile", "-Command", schrift]


def _mitteilung_befehl_macos(text: str) -> list[str]:
    sicher = text.replace("\\", "\\\\").replace('"', '\\"')
    titel_sicher = _titel().replace("\\", "\\\\").replace('"', '\\"')
    schrift = f'display notification "{sicher}" with title "{titel_sicher}"'
    return ["osascript", "-e", schrift]


def _mitteilung_befehl_windows(text: str) -> list[str]:
    sicher = text.replace("'", "''")
    titel_sicher = _titel().replace("'", "''")
    schrift = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "Add-Type -AssemblyName System.Drawing; "
        "$symbol = New-Object System.Windows.Forms.NotifyIcon; "
        "$symbol.Icon = [System.Drawing.SystemIcons]::Information; "
        "$symbol.Visible = $true; "
        f"$symbol.ShowBalloonTip(10000, '{titel_sicher}', '{sicher}', "
        "[System.Windows.Forms.ToolTipIcon]::Info); "
        # The balloon dies with the process — without a wait it would never
        # be seen at all in a one-shot PowerShell call.
        "Start-Sleep -Seconds 6; "
        "$symbol.Dispose()"
    )
    return [_windows_powershell() or "powershell.exe", "-NoProfile", "-Command", schrift]


def mit_grund(aufgabentext: str, grund: str | None) -> str:
    """``aufgabentext`` with the ending's reason behind it — the notification
    an entry on ``deliver = 'announce'`` gets, and the reason travelling IN
    it rather than in one of its own.

    Why this exists at all: a failing schedule announced "Failed — <task>"
    and nothing else. The reason WAS written — as the run's ``ende`` step —
    but the step log only opens for a run that is waiting or running, and the
    ending is the very moment a run leaves that list. So the one line that
    said what went wrong appeared on screen never. A red schedule, and no way
    to find out why.

    The words come out of the catalogue block that already holds every
    reason (``jobs.grund.*``), never a second wording invented here. In
    English, which is this module's language throughout ("Failed — ",
    "stopped after N failed runs", "waiting for a model"): a sentence that
    switched languages halfway would read worse than one that does not
    translate at all, and asking the catalogue means the words are already
    there the day this module learns whose language to speak.

    An ending with nothing to explain is left exactly as it was — no reason
    at all (a script that simply exited 0), or ``fertig``, whose notification
    is the good news itself and would otherwise read "… — finished". That is
    also what keeps a clean run's announcement byte for byte what it was.

    A reason with no entry shows ITSELF. A run that died on an error carries
    the message inline (``fehler: connection reset``,
    app/api/v1/auftraege.py) and can have no entry — and ``t`` answers a
    missing key with the key, which would put ``jobs.grund.fehler: connection
    reset`` in front of somebody. The warning ``t`` logs on the way past is
    wanted: a NEW ending with no catalogue entry is exactly the silence this
    line exists to end.
    """
    if not grund or grund == "fertig":
        return aufgabentext
    schluessel = f"jobs.grund.{grund}"
    satz = i18n.t(schluessel)
    return f"{aufgabentext} — {grund if satz == schluessel else satz}"


def melden(aufgabentext: str, *, erfolgreich: bool) -> None:
    """Plays a sound and shows ``aufgabentext``. Blocking — call via
    ``asyncio.to_thread`` from async code, the same way the folder dialog
    is kept off the event loop.

    Takes the text ready-made, on purpose: a caller that has something to add
    — the failure limit's "stopped after N failed runs", the ending's reason
    (``mit_grund`` above) — puts it into THIS notification instead of asking
    for a second one. One piece of work says its piece once.
    """
    if not verfuegbar():
        return
    mitteilungstext = aufgabentext if erfolgreich else f"Failed — {aufgabentext}"
    klangpfad = _klang_pfad(erfolgreich)
    if sys.platform == "darwin":
        befehle = []
        if shutil.which("afplay"):
            befehle.append(_klang_befehl_macos(klangpfad))
        befehle.append(_mitteilung_befehl_macos(mitteilungstext))
    else:
        befehle = [_klang_befehl_windows(klangpfad), _mitteilung_befehl_windows(mitteilungstext)]
    for befehl in befehle:
        try:
            ergebnis = subprocess.run(befehl, capture_output=True, timeout=ZEITGRENZE_SEKUNDEN, **no_window())
        except (subprocess.TimeoutExpired, OSError) as fehler:
            log.warning("Cron announcement (%s) failed: %s", befehl[0], fehler)
            continue
        if ergebnis.returncode != 0:
            log.warning(
                "Cron announcement (%s) exited with code %d", befehl[0], ergebnis.returncode
            )
