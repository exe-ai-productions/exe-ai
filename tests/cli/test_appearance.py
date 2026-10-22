"""Whether the machine is set to dark: asked of the system of a Mac and read
from the registry of a Windows, each stood in for here — and nothing where a
system keeps no word on it or asking fails."""

from __future__ import annotations

import subprocess
import sys
import types

import pytest

from cli import appearance


def a_mac(monkeypatch: pytest.MonkeyPatch, style: str | None) -> None:
    """A Mac whose system answers with that style — ``None`` where it keeps
    no entry, as a Mac set to light does."""
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(appearance, "_mac_style", lambda: style)


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


@pytest.mark.parametrize(("style", "dark"), [("Dark", True), (None, False)])
def test_a_mac_says_dark_while_its_system_carries_the_entry(monkeypatch, style, dark):
    a_mac(monkeypatch, style)
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


def test_a_mac_that_cannot_be_asked_says_nothing(monkeypatch):
    def cannot_be_asked() -> str | None:
        raise OSError("no system to ask")

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(appearance, "_mac_style", cannot_be_asked)
    assert appearance.machine_is_dark() is None


@pytest.mark.skipif(sys.platform != "darwin", reason="only a Mac has a system to ask")
def test_the_system_of_this_mac_answers_as_its_own_tool_does():
    asked = subprocess.run(
        ["defaults", "read", "-g", "AppleInterfaceStyle"], capture_output=True, text=True
    )
    # A Mac set to light keeps no entry, and the tool then fails.
    expected = asked.stdout.strip() if asked.returncode == 0 else None
    assert appearance._mac_style() == expected
    assert appearance.machine_is_dark() is (expected == "Dark")


def test_a_windows_without_the_entry_says_nothing(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setitem(
        sys.modules, "winreg", types.SimpleNamespace(HKEY_CURRENT_USER=object(), OpenKey=no_entry)
    )
    assert appearance.machine_is_dark() is None


def test_a_system_that_keeps_no_such_setting_says_nothing(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert appearance.machine_is_dark() is None
