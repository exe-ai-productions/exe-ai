"""The four shipped sounds.

Nothing here judges how they sound. What it checks is that they are there,
that they are readable audio, and that they are short — a notification that
plays for three seconds is not a notification, and a missing file would only
show up as silence on a user's machine, where nobody can tell it from a
switch that is off.
"""

from __future__ import annotations

import wave
from pathlib import Path

import pytest

KLANG_VERZEICHNIS = Path(__file__).resolve().parent.parent / "static" / "klaenge"
NAMEN = ("fertig", "wartet", "fehler", "agent-cronjob")

# Long enough to be a sound, short enough not to become one you wait out.
MAX_SEKUNDEN = 2.0


@pytest.mark.parametrize("name", NAMEN)
def test_der_klang_ist_da_und_lesbar(name):
    pfad = KLANG_VERZEICHNIS / f"{name}.wav"
    assert pfad.exists(), f"{pfad} is missing"
    with wave.open(str(pfad), "rb") as datei:
        rahmen = datei.getnframes()
        rate = datei.getframerate()
        assert datei.getnchannels() == 1
        assert rate == 48_000
        assert 0 < rahmen / rate <= MAX_SEKUNDEN


def test_die_herkunft_steht_dabei():
    """A shipped file whose licence nobody can look up is a file that has to
    be removed later."""
    herkunft = KLANG_VERZEICHNIS / "HERKUNFT.md"
    assert herkunft.exists()
    text = " ".join(herkunft.read_text(encoding="utf-8").split())
    # Made by the program's own script: no recording, no outside library.
    assert "script of our own" in text
    assert "licence of a third party" in text


def test_the_old_sound_is_gone():
    """`cron-fertig.wav` is the agent / cronjob sound under its new name; a
    file nobody plays is a file shipped for nothing."""
    assert not (KLANG_VERZEICHNIS / "cron-fertig.wav").exists()
    assert sorted(p.name for p in KLANG_VERZEICHNIS.glob("*.wav")) == sorted(
        f"{name}.wav" for name in NAMEN
    )


def test_no_outside_source_in_the_notices():
    """The sounds are the program's own, so the notices of third parties
    name no sound library."""
    hinweise = (KLANG_VERZEICHNIS.parent.parent / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    assert "Versilian" not in hinweise
    assert "Notification sounds" not in hinweise
