"""Loading and writing skills.

The rules under test are the ones that were argued for, not the plumbing:
nothing here asks — the one prompt in the program is the shell reaching
outside the shared folders — and writing never lands in the shipped folder,
so a change to a shipped skill survives the next update.
"""

from __future__ import annotations

import pytest

from app import skills
from app.tools import skill


@pytest.fixture
def orte(tmp_path):
    haus = tmp_path / "haus"
    mein = tmp_path / "mein"
    haus.mkdir()
    mein.mkdir()
    return haus, mein


def _anlegen(ordner, name, beschreibung="Da", anleitung="Tu es.", auto=False):
    ziel = ordner / name
    ziel.mkdir(parents=True, exist_ok=True)
    (ziel / skills.SKILL_DATEI).write_text(
        f"---\ndescription: {beschreibung}\nauto: {str(auto).lower()}\n---\n\n{anleitung}\n",
        encoding="utf-8",
    )
    return ziel


# --- loading -----------------------------------------------------------------


async def test_laden_gibt_die_ganze_anleitung(orte):
    haus, mein = orte
    _anlegen(haus, "handoff", anleitung="Erst dies, dann das.")
    assert await skill.laden({"name": "handoff"}, haus, mein) == "Erst dies, dann das."


async def test_laden_nimmt_deine_fassung(orte):
    haus, mein = orte
    _anlegen(haus, "handoff", anleitung="Ab Werk.")
    _anlegen(mein, "handoff", anleitung="Meine.")
    assert await skill.laden({"name": "handoff"}, haus, mein) == "Meine."


async def test_ein_unbekannter_name_nennt_die_vorhandenen(orte):
    """A model that guessed the name is one line away from the right one."""
    haus, mein = orte
    _anlegen(haus, "handoff")
    with pytest.raises(skill.SkillVerboten, match="handoff"):
        await skill.laden({"name": "handof"}, haus, mein)


# --- writing -----------------------------------------------------------------


async def test_schreiben_legt_die_skill_bei_dir_an(orte):
    haus, mein = orte
    antwort = await skill.schreiben(
        {"name": "release", "description": "Vor dem Ausliefern", "instruction": "Erst Tests."},
        mein,
    )
    assert "/release" in antwort
    geladen = skills.skills_laden(haus, mein)
    assert geladen["release"].anleitung == "Erst Tests."
    assert geladen["release"].eigen is True


async def test_ohne_angabe_wird_eine_neue_skill_nicht_von_selbst_geladen(orte):
    """The expensive setting is never the one you get by not deciding."""
    haus, mein = orte
    await skill.schreiben(
        {"name": "neu", "description": "Da", "instruction": "Tu es."}, mein
    )
    assert skills.skills_laden(haus, mein)["neu"].auto is False


async def test_das_modell_darf_eine_skill_selbst_freischalten(orte):
    """It costs a line of every later request — what answers that is the mask,
    where the count stands at the top and each one can be switched off."""
    haus, mein = orte
    await skill.schreiben(
        {"name": "neu", "description": "Da", "instruction": "Tu es.", "auto": True},
        mein,
    )
    assert skills.skills_laden(haus, mein)["neu"].auto is True


async def test_schreiben_geht_nie_in_den_mitgelieferten_ordner(orte):
    """Overwriting a shipped skill IS the copy that keeps the next update
    from quietly taking the change back."""
    haus, mein = orte
    _anlegen(haus, "handoff", anleitung="Ab Werk.")
    await skill.schreiben(
        {"name": "handoff", "description": "Meine", "instruction": "Meins."}, mein
    )
    assert (haus / "handoff" / skills.SKILL_DATEI).read_text().endswith("Ab Werk.\n")
    assert skills.skills_laden(haus, mein)["handoff"].anleitung == "Meins."


async def test_ein_untippbarer_name_wird_abgelehnt(orte):
    _, mein = orte
    with pytest.raises(skill.SkillVerboten):
        await skill.schreiben(
            {"name": "Mein Skill", "description": "Da", "instruction": "Tu es."}, mein
        )
    assert not any(mein.iterdir())


async def test_eine_zu_lange_anleitung_wird_abgelehnt(orte):
    _, mein = orte
    with pytest.raises(skill.SkillVerboten, match="too long"):
        await skill.schreiben(
            {"name": "lang", "description": "Da", "instruction": "x" * (skill.MAX_ANLEITUNG + 1)},
            mein,
        )
    assert not any(mein.iterdir())


async def test_eine_abgelehnte_skill_laesst_keinen_leeren_ordner_zurueck(orte):
    _, mein = orte
    with pytest.raises(skill.SkillVerboten):
        await skill.schreiben({"name": "leer", "description": "", "instruction": "x"}, mein)
    assert not any(mein.iterdir())


async def test_der_zweite_schreibvorgang_ersetzt_statt_zu_stapeln(orte):
    haus, mein = orte
    for text in ("Erst.", "Dann."):
        await skill.schreiben(
            {"name": "wieder", "description": "Da", "instruction": text}, mein
        )
    assert skills.skills_laden(haus, mein)["wieder"].anleitung == "Dann."


# --- the header as it is written ---------------------------------------------


async def test_a_description_with_colon_hash_and_yes_reads_back_unchanged(orte):
    """A colon, a `#` and the words `42` and `yes` in one description: the
    written header is valid YAML and gives back exactly that sentence."""
    import yaml

    _, own = orte
    description = "Use when: the user says #sort 42 yes"
    await skill.schreiben(
        {"name": "sortieren", "description": description, "instruction": "Sort it."}, own
    )
    text = (own / "sortieren" / skills.SKILL_DATEI).read_text(encoding="utf-8")
    head = yaml.safe_load(text.split("---", 2)[1])
    assert head == {"description": description, "auto": False}
    assert skills.skill_lesen(own / "sortieren").beschreibung == description


async def test_a_plain_description_reads_as_before(orte):
    """Silence probe: a plain sentence comes back as it went in."""
    _, own = orte
    await skill.schreiben(
        {"name": "schlicht", "description": "Sums the chat up", "instruction": "Do it."}, own
    )
    read = skills.skill_lesen(own / "schlicht")
    assert (read.beschreibung, read.auto, read.anleitung) == ("Sums the chat up", False, "Do it.")
