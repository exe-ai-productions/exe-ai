"""Whether the machine is set to dark: read from the preferences of a Mac
and from the registry of a Windows, each stood in for here — and nothing
where a system keeps no word on it or looking fails."""

from __future__ import annotations

import plistlib
import sys
import types
from pathlib import Path

import pytest

from cli import appearance


def preferences_of_a_mac(home: Path, entries: dict[str, object]) -> Path:
    file = home / "Library" / "Preferences" / ".GlobalPreferences.plist"
    file.parent.mkdir(parents=True)
    with file.open("wb") as written_to:
        plistlib.dump(entries, written_to, fmt=plistlib.FMT_BINARY)
    return file


def a_mac(monkeypatch: pytest.MonkeyPatch, home: Path) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(Path, "home", lambda: home)


def registry(light: int) -> types.SimpleNamespace:
    """Stands in for the registry of a Windows whose programs are to be
    light (1) or dark (0), and keeps what it was asked."""
    asked: list[tuple[object, ...]] = []

    class Key:
        def __enter__(self) -> Key:
            return self

        def __exit__(self, *_: object) -> None:
            return None

    def open_key(*where: object) -> Key:
        asked.append(where)
        return Key()

    def query(_: Key, entry: str) -> tuple[int, int]:
        asked.append((entry,))
        return (light, 4)

    return types.SimpleNamespace(
        HKEY_CURRENT_USER="the user's part", OpenKey=open_key, QueryValueEx=query, asked=asked
    )


def no_entry(*_: object) -> object:
    raise FileNotFoundError("no such key")


@pytest.mark.parametrize(
    ("entries", "dark"),
    [
        ({"AppleInterfaceStyle": "Dark", "AppleLanguages": ["en"]}, True),
        # Set to light, a Mac keeps no entry at all.
        ({"AppleLanguages": ["en"]}, False),
    ],
)
def test_a_mac_says_dark_while_its_preferences_carry_the_entry(tmp_path, monkeypatch, entries, dark):
    preferences_of_a_mac(tmp_path, entries)
    a_mac(monkeypatch, tmp_path)
    assert appearance.machine_is_dark() is dark


@pytest.mark.parametrize(("light", "dark"), [(0, True), (1, False)])
def test_windows_says_dark_where_its_programs_are_not_to_be_light(monkeypatch, light, dark):
    windows = registry(light)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "winreg", windows)
    assert appearance.machine_is_dark() is dark
    assert windows.asked == [
        ("the user's part", r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"),
        ("AppsUseLightTheme",),
    ]


def test_a_mac_whose_preferences_cannot_be_read_says_nothing(tmp_path, monkeypatch):
    a_mac(monkeypatch, tmp_path)
    # No file at all.
    assert appearance.machine_is_dark() is None
    # A file that is no list of preferences, in three ways.
    file = preferences_of_a_mac(tmp_path, {})
    for content in (b"", b"not a list of preferences", b"bplist00\xff\xff"):
        file.write_bytes(content)
        assert appearance.machine_is_dark() is None
    # Preferences that are a list and no table of entries.
    with file.open("wb") as written_to:
        plistlib.dump(["a list"], written_to)
    assert appearance.machine_is_dark() is None


def test_a_mac_that_does_not_say_where_the_home_is_says_nothing(monkeypatch):
    def no_home() -> Path:
        raise RuntimeError("no home")

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(Path, "home", no_home)
    assert appearance.machine_is_dark() is None


def test_a_windows_without_the_entry_says_nothing(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setitem(
        sys.modules, "winreg", types.SimpleNamespace(HKEY_CURRENT_USER=object(), OpenKey=no_entry)
    )
    assert appearance.machine_is_dark() is None


def test_a_system_that_keeps_no_such_setting_says_nothing(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert appearance.machine_is_dark() is None
