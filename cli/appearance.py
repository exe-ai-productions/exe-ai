"""Whether the machine is set to dark or to light.

The look that follows the machine asks this. The answer is read from what
the system keeps on this machine: a file of preferences on macOS, an entry
of the registry on Windows. No program is started and nothing is waited
for, so asking never holds anything up. A system that keeps no word on it
and a look that failed both answer with nothing.
"""

from __future__ import annotations

import plistlib
import sys
from pathlib import Path

# Where macOS keeps what the user set for every program, inside the user's
# home, and the entry that is there for as long as the machine is set to
# dark. Set to light, the entry is missing.
_MAC_PREFERENCES = Path("Library") / "Preferences" / ".GlobalPreferences.plist"
_MAC_ENTRY = "AppleInterfaceStyle"
_MAC_DARK = "Dark"

# Where Windows keeps it: a number that is 0 where programs are to be dark.
_WINDOWS_KEY = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
_WINDOWS_ENTRY = "AppsUseLightTheme"


def _mac_is_dark(preferences: Path) -> bool:
    """Whether those preferences of a Mac say dark. A file that is not
    there or cannot be read raises."""
    with preferences.open("rb") as file:
        return bool(plistlib.load(file).get(_MAC_ENTRY) == _MAC_DARK)


def _windows_is_dark() -> bool:
    """Whether Windows says dark. A machine that keeps no such entry
    raises, and so does one that is no Windows."""
    if sys.platform != "win32":
        raise OSError("no registry on this system")
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _WINDOWS_KEY) as key:
        light, _ = winreg.QueryValueEx(key, _WINDOWS_ENTRY)
    return bool(light == 0)


def machine_is_dark() -> bool | None:
    """Whether the machine is set to dark, as it stands at this moment —
    ``None`` where the system keeps no word on it, or where looking failed."""
    try:
        if sys.platform == "darwin":
            return _mac_is_dark(Path.home() / _MAC_PREFERENCES)
        if sys.platform == "win32":
            return _windows_is_dark()
    except Exception:  # noqa: BLE001
        # Whatever went wrong while looking: nothing is known.
        return None
    return None
