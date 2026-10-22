"""Reading skills: two places, the user's wins, a broken one drops out alone.

The rules being guarded here are decisions, not implementation details. A
skill carries no model and no tool list — that is what separates it from an
agent, and the separation is the reason both exist. Its name is typed after a
slash, so it has to survive being typed. And its description rides in the
system prompt on every request when the skill is automatic, which is why
there is a limit on it at all.
"""

from __future__ import annotations

import logging
import pathlib

import pytest

from app import skills


def _schreiben(ordner, name, text, *, beilage=None):
    ziel = ordner / name
    ziel.mkdir(parents=True)
    (ziel / skills.SKILL_DATEI).write_text(text, encoding="utf-8")
    if beilage:
        (ziel / beilage).write_text("egal", encoding="utf-8")
    return ziel


GUT = """---
description: Sums this conversation up as a handover
auto: true
---

Go through the whole conversation and collect what matters.
"""


def test_max_tokens_gehoert_zu_den_agentenfeldern():
    """Added alongside app/agenten.py's own max_tokens field — otherwise a
    skill file with this typo would get the generic 'unknown field' warning
    instead of pointing at what it actually belongs to."""
    assert "max_tokens" in skills.AGENTENFELDER


def test_eine_gute_skill_wird_gelesen(tmp_path):
    ordner = _schreiben(tmp_path, "handoff", GUT)
    skill = skills.skill_lesen(ordner)
    assert skill.name == "handoff"
    assert skill.beschreibung == "Sums this conversation up as a handover"
    assert skill.anleitung.startswith("Go through")
    assert skill.auto is True


def test_auto_ist_ohne_angabe_aus(tmp_path):
    """The expensive setting is never the one you get by not deciding."""
    ordner = _schreiben(tmp_path, "still", "---\ndescription: Does a thing\n---\n\nDo it.\n")
    assert skills.skill_lesen(ordner).auto is False


def test_der_ordner_gehoert_zur_skill(tmp_path):
    """An instruction that points at a script beside it needs to know where
    it stands. Two of the three skills this was modelled on carry one."""
    ordner = _schreiben(tmp_path, "vektoren", GUT, beilage="generator.py")
    skill = skills.skill_lesen(ordner)
    assert skill.ordner == ordner
    assert (skill.ordner / "generator.py").is_file()


@pytest.mark.parametrize("name", ["Handoff", "mein skill", "über", "-vorn", "a_b"])
def test_ein_name_der_sich_nicht_tippen_laesst_faellt_durch(tmp_path, name):
    with pytest.raises(skills.SkillKaputt):
        skills.skill_aus_text(name, GUT, ordner=tmp_path)


def test_ohne_beschreibung_faellt_sie_durch(tmp_path):
    """Without it there is nothing to put in the list and nothing the model
    could recognise the skill by."""
    with pytest.raises(skills.SkillKaputt, match="description"):
        skills.skill_aus_text("x", "---\nauto: true\n---\n\nText.\n", ordner=tmp_path)


def test_eine_zu_lange_beschreibung_faellt_durch(tmp_path):
    """Past the budget the skill is refused, not quietly shortened — and the
    refusal names the number that applies."""
    lang = "w " * 600
    with pytest.raises(skills.SkillKaputt) as gefangen:
        skills.skill_aus_text(
            "x", f"---\ndescription: {lang}\n---\n\nText.\n", ordner=tmp_path
        )
    assert gefangen.value.kind == "beschreibung_lang"
    assert gefangen.value.values["grenze"] == skills.MAX_BESCHREIBUNG


def test_ohne_anleitung_faellt_sie_durch(tmp_path):
    with pytest.raises(skills.SkillKaputt):
        skills.skill_aus_text("x", "---\ndescription: Da\n---\n\n   \n", ordner=tmp_path)


def test_agentenfelder_werden_uebergangen_statt_befolgt(tmp_path, caplog):
    """A skill has no model and no tool list. Writing them anyway is a
    misunderstanding worth a word, not a reason to throw the skill away."""
    text = "---\ndescription: Da\nmodel: qwen-mac\ntools:\n  - run_command\n---\n\nText.\n"
    skill = skills.skill_aus_text("x", text, ordner=tmp_path)
    assert skill.beschreibung == "Da"
    assert not hasattr(skill, "modell")
    assert "belongs to an agent" in caplog.text


# --- the two places ----------------------------------------------------------


def test_deine_fassung_schlaegt_die_mitgelieferte(tmp_path):
    haus = tmp_path / "haus"
    mein = tmp_path / "mein"
    _schreiben(haus, "handoff", "---\ndescription: Ab Werk\n---\n\nWerk.\n")
    _schreiben(mein, "handoff", "---\ndescription: Meine\n---\n\nMeins.\n")

    geladen = skills.skills_laden(haus, mein)
    assert len(geladen) == 1
    assert geladen["handoff"].beschreibung == "Meine"
    assert geladen["handoff"].eigen is True


def test_beide_orte_kommen_zusammen(tmp_path):
    haus = tmp_path / "haus"
    mein = tmp_path / "mein"
    _schreiben(haus, "handoff", GUT)
    _schreiben(mein, "eigenes", GUT)

    geladen = skills.skills_laden(haus, mein)
    assert sorted(geladen) == ["eigenes", "handoff"]
    assert geladen["handoff"].eigen is False


def test_fehlende_ordner_sind_kein_fehler(tmp_path):
    """It ships empty — the place exists, the content belongs to the user."""
    assert skills.skills_laden(tmp_path / "weg", tmp_path / "auch-weg") == {}


def test_eine_kaputte_skill_nimmt_die_anderen_nicht_mit(tmp_path):
    mein = tmp_path / "mein"
    _schreiben(mein, "heil", GUT)
    _schreiben(mein, "kaputt", "hier fehlt der Kopfteil")

    geladen = skills.skills_laden(tmp_path / "haus", mein)
    assert sorted(geladen) == ["heil"]


def test_ein_ordner_ohne_skill_datei_wird_uebergangen(tmp_path):
    mein = tmp_path / "mein"
    (mein / "nur-ein-ordner").mkdir(parents=True)
    _schreiben(mein, "heil", GUT)
    assert sorted(skills.skills_laden(tmp_path / "haus", mein)) == ["heil"]


def test_nur_automatische_kosten_platz_im_prompt(tmp_path):
    mein = tmp_path / "mein"
    _schreiben(mein, "selbst", "---\ndescription: Da\nauto: true\n---\n\nText.\n")
    _schreiben(mein, "getippt", "---\ndescription: Da\n---\n\nText.\n")

    geladen = skills.skills_laden(tmp_path / "haus", mein)
    assert [s.name for s in skills.automatische(geladen, ())] == ["selbst"]


def test_der_mitgelieferte_cronjob_skill_widerspricht_der_werkzeugbeschreibung_nicht():
    """The skill said a job without an agent goes to a shipped reminder agent
    with no tools and no folders; the description of the tool says it runs as
    an unattended model run with the approved tools. Two statements that
    disagree: the skill now leaves what happens without an agent to the
    description, which always comes with the tool."""
    ordner = pathlib.Path(__file__).resolve().parent.parent / "skills" / "cronjob"
    skill = skills.skill_lesen(ordner)

    assert skill.name == "cronjob"
    assert "reminder agent" not in skill.anleitung
    assert "shipped" not in skill.anleitung
    assert (
        "Offer to name a specific agent to run it; if the user has no preference, leave "
        "`agent` out." in " ".join(skill.anleitung.split())
    )
    # Silence probe: the head and the table of `time` stay as they were.
    assert skill.auto is True
    assert skill.beschreibung.startswith("Schedules future actions:")
    assert "| every day at 08:00 | `08:00` — a daily time, 24-hour `HH:MM` |" in skill.anleitung
    assert "| every fifteen minutes | `*/15 * * * *` — a five-field cron expression |" in skill.anleitung


def test_every_shipped_skill_header_is_valid_yaml(caplog):
    """A shipped header YAML cannot read is read line by line and warns on
    every listing of the skills and on the first message of every chat. Two
    did: a second unquoted ``: `` in ``description`` (cronjob, help)."""
    ordner = pathlib.Path(__file__).resolve().parent.parent / "skills"
    gelesen = []
    with caplog.at_level(logging.WARNING, logger="app.skills"):
        for skill_ordner in sorted(p for p in ordner.iterdir() if (p / "SKILL.md").is_file()):
            skills.skill_lesen(skill_ordner)
            gelesen.append(skill_ordner.name)

    assert {"cronjob", "help"} <= set(gelesen)
    assert [r.getMessage() for r in caplog.records if "not valid YAML" in r.getMessage()] == []


# --- writing one from the UI -------------------------------------------------


NEU = """---
description: Writes a plan for the next step
auto: true
---

Lay out the next step as a short plan.
"""


def _verwaltung(client, name):
    """The management row for one skill, or None if it is not offered."""
    for zeile in client.get("/api/v1/skills/verwaltung").json():
        if zeile["name"] == name:
            return zeile
    return None


def test_ein_geschriebener_skill_taucht_in_der_verwaltung_auf(client):
    """A written skill lands in the user's folder and reads back with its
    front matter parsed — description and auto taken from the file."""
    antwort = client.post("/api/v1/skills", json={"name": "planer", "inhalt": NEU})
    assert antwort.status_code == 201
    assert antwort.json() == {
        "name": "planer",
        "beschreibung": "Writes a plan for the next step",
        "auto": True,
        "eigen": True,
        "mitgeliefert": False,
    }

    zeile = _verwaltung(client, "planer")
    assert zeile["eigen"] is True
    assert zeile["beschreibung"] == "Writes a plan for the next step"
    assert zeile["auto"] is True


def test_ein_ungueltiger_name_faellt_durch(client):
    antwort = client.post("/api/v1/skills", json={"name": "Gross Raum", "inhalt": NEU})
    assert antwort.status_code == 400
    assert _verwaltung(client, "Gross Raum") is None


def test_ein_leerer_inhalt_faellt_durch(client):
    antwort = client.post("/api/v1/skills", json={"name": "leer", "inhalt": "   \n"})
    assert antwort.status_code == 400
    assert _verwaltung(client, "leer") is None


def test_ein_inhalt_ohne_kopfteil_wird_wieder_entfernt(client):
    """Content that will not load back is answered with 400 and taken off the
    disk again, so a broken skill never lingers in the offered list."""
    _, eigen = client.app.state.config.skillverzeichnisse
    antwort = client.post(
        "/api/v1/skills", json={"name": "kaputt", "inhalt": "no front matter here"}
    )
    assert antwort.status_code == 400
    assert not (eigen / "kaputt").exists()
    assert _verwaltung(client, "kaputt") is None


def test_ein_geschriebener_skill_ueberschattet_einen_mitgelieferten(client):
    """A name that a shipped skill already carries is not an error: the write
    makes the user's copy, exactly the copy-on-write the mask relies on."""
    haus, eigen = client.app.state.config.skillverzeichnisse
    (haus / "handoff").mkdir(parents=True)
    (haus / "handoff" / skills.SKILL_DATEI).write_text(
        "---\ndescription: Shipped one\n---\n\nShipped body.\n", encoding="utf-8"
    )

    antwort = client.post("/api/v1/skills", json={"name": "handoff", "inhalt": NEU})
    assert antwort.status_code == 201
    body = antwort.json()
    assert body["eigen"] is True
    assert body["mitgeliefert"] is True
    assert body["beschreibung"] == "Writes a plan for the next step"

    # The user's copy is on disk and the shipped one is untouched.
    assert (eigen / "handoff" / skills.SKILL_DATEI).is_file()
    assert "Shipped body." in (haus / "handoff" / skills.SKILL_DATEI).read_text()
    assert skills.skills_laden(haus, eigen)["handoff"].eigen is True


# --- Deleting: only what the user owns --------------------------------------


def test_ein_eigener_skill_laesst_sich_loeschen(client):
    """Written, then gone. Until now a mistyped skill could only be switched
    off, never removed."""
    client.post("/api/v1/skills", json={"name": "wegdamit", "inhalt": NEU})
    assert _verwaltung(client, "wegdamit") is not None

    antwort = client.delete("/api/v1/skills/wegdamit")
    assert antwort.status_code == 204
    assert _verwaltung(client, "wegdamit") is None


def test_das_loeschen_holt_den_mitgelieferten_zurueck(client, config):
    """A user's copy shadows a shipped skill. Removing the copy is not a
    deletion but a reset — the shipped one stands there again."""
    mitgeliefert, _ = config.skillverzeichnisse
    _schreiben(
        mitgeliefert,
        "handoff",
        "---\ndescription: The shipped one\nauto: false\n---\n\nShipped instruction.\n",
    )
    client.post("/api/v1/skills", json={"name": "handoff", "inhalt": NEU})
    assert _verwaltung(client, "handoff")["beschreibung"] == "Writes a plan for the next step"

    client.delete("/api/v1/skills/handoff")
    zeile = _verwaltung(client, "handoff")
    assert zeile is not None
    assert zeile["eigen"] is False
    assert zeile["beschreibung"] == "The shipped one"


def test_ein_mitgelieferter_ohne_eigene_fassung_bleibt(client, config):
    """Nothing to delete: the shipped folder is not this route's business,
    and a deletion there would be undone by the next update anyway."""
    mitgeliefert, _ = config.skillverzeichnisse
    _schreiben(
        mitgeliefert,
        "bleibt",
        "---\ndescription: Stays put\nauto: false\n---\n\nShipped instruction.\n",
    )
    antwort = client.delete("/api/v1/skills/bleibt")
    assert antwort.status_code == 404
    assert _verwaltung(client, "bleibt") is not None


def test_ein_name_ist_nie_ein_pfad(client):
    """The name comes out of the URL and is about to become a path. A dotted
    escape does not even reach the handler — the router refuses it — and a
    name that does reach it is turned away by the pattern."""
    assert client.delete("/api/v1/skills/..").status_code in (400, 404, 405)
    assert client.delete("/api/v1/skills/etc%2Fpasswd").status_code in (400, 404, 405)
    assert client.delete("/api/v1/skills/Gross Raum").status_code == 400


def test_skill_datei_lesen_und_bearbeiten(client):
    """The edit button's round trip: read the raw file, save it changed.

    The raw text comes back verbatim — front matter included — so saving
    it unchanged changes nothing. A broken edit is refused and the old
    file stands.
    """
    client.post("/api/v1/skills", json={"name": "planer", "inhalt": NEU})

    datei = client.get("/api/v1/skills/planer")
    assert datei.status_code == 200
    assert datei.json()["inhalt"] == NEU
    assert datei.json()["eigen"] is True

    geaendert = NEU.replace("short plan", "long plan")
    antwort = client.put("/api/v1/skills/planer", json={"inhalt": geaendert})
    assert antwort.status_code == 200
    assert client.get("/api/v1/skills/planer").json()["inhalt"] == geaendert

    # Broken content never reaches the disk.
    kaputt = client.put("/api/v1/skills/planer", json={"inhalt": "no front matter"})
    assert kaputt.status_code == 400
    assert client.get("/api/v1/skills/planer").json()["inhalt"] == geaendert


def test_bearbeiten_eines_mitgelieferten_legt_die_eigene_fassung_an(client, tmp_path):
    """Editing a shipped skill copies it to the user's folder first, so the
    next update walks past the change."""
    mitgeliefert, _ = client.app.state.config.skillverzeichnisse
    ordner = mitgeliefert / "werk"
    ordner.mkdir(parents=True)
    (ordner / "SKILL.md").write_text(NEU, encoding="utf-8")

    geaendert = NEU.replace("short plan", "careful plan")
    antwort = client.put("/api/v1/skills/werk", json={"inhalt": geaendert})
    assert antwort.status_code == 200
    assert antwort.json()["eigen"] is True
    assert antwort.json()["mitgeliefert"] is True
    assert client.get("/api/v1/skills/werk").json()["inhalt"] == geaendert


# --- A header that is not valid YAML is read line by line -------------------

ZWEIZEILIG = """---
description: Sorts the inbox and
files every letter by sender
auto: true
---

Sort the inbox, then file every letter by its sender.
"""


def test_ein_kopf_mit_umbrochener_beschreibung_wird_angenommen(tmp_path):
    """A description over two lines is not valid YAML. The skill is still
    stored, and it is read the way the line-wise reader reads it: the first
    line is the description, the second one carries no colon and falls away
    instead of being glued to it."""
    skill = skills.skill_aus_text("sortieren", ZWEIZEILIG, ordner=tmp_path)
    assert skill.beschreibung == "Sorts the inbox and"
    assert skill.auto is True
    assert skill.anleitung.startswith("Sort the inbox")


def test_der_kaputte_kopf_schreibt_eine_zeile_mit_dem_yaml_fehler(tmp_path, caplog):
    """An unterminated quote makes the header invalid. The value stays text,
    as the line-wise reader hands it over, but the log names the skill and
    the parser's own sentence — a typo no longer passes in silence."""
    text = '---\ndescription: "Zitat\nauto: true\n---\n\nText.\n'
    with caplog.at_level("WARNING", logger="app.skills"):
        skill = skills.skill_aus_text("zitat", text, ordner=tmp_path)
    assert skill.beschreibung == '"Zitat'
    assert skill.auto is True
    zeilen = [r.getMessage() for r in caplog.records if "not valid YAML" in r.getMessage()]
    assert len(zeilen) == 1
    assert "'zitat'" in zeilen[0]
    assert "line" in zeilen[0]  # the parser's sentence carries line and column


def test_ein_gueltiger_kopf_schreibt_keine_yaml_zeile(tmp_path, caplog):
    """Silence probe: a header YAML can read says nothing about YAML."""
    with caplog.at_level("WARNING", logger="app.skills"):
        skills.skill_aus_text("x", GUT, ordner=tmp_path)
    assert "not valid YAML" not in caplog.text


def test_eine_zeile_ohne_doppelpunkt_legt_kein_feld_an_und_klebt_nirgends(tmp_path):
    """A note inside a broken header is dropped. It used to be glued to the
    description and then rode in the system prompt of every request."""
    text = (
        "---\ndescription: Sorts the inbox and\nfiles by sender\n# Notiz\n"
        "auto: true\n---\n\nText.\n"
    )
    skill = skills.skill_aus_text("x", text, ordner=tmp_path)
    assert skill.beschreibung == "Sorts the inbox and"
    assert skill.auto is True


def test_eine_fortsetzung_mit_doppelpunkt_ist_ein_eigenes_unbekanntes_feld(tmp_path, caplog):
    """`12:30 Uhr` or a URL with a port opens a field of its own; the
    description is its first line, and the field is passed over with a log
    line, like any unknown one."""
    text = (
        "---\ndescription: Sorts the inbox and\n12:30 Uhr\nauto: true\n---\n\nText.\n"
    )
    with caplog.at_level("WARNING", logger="app.skills"):
        skill = skills.skill_aus_text("x", text, ordner=tmp_path)
    assert skill.beschreibung == "Sorts the inbox and"
    assert "unknown header fields are ignored: 12" in caplog.text


def test_eine_fortsetzung_nach_auto_trifft_nicht_das_feld_auto(tmp_path):
    """The line after `auto: true` used to be glued to `auto` and the skill
    refused for a line that says plainly `true`."""
    text = "---\ndescription: Eins und\nauto: true\nnoch was\n---\n\nText.\n"
    skill = skills.skill_aus_text("x", text, ordner=tmp_path)
    assert skill.auto is True
    assert skill.beschreibung == "Eins und"


def test_ein_doppelpunkt_in_der_beschreibung_ist_kein_fehler_mehr(tmp_path):
    """How the program's own editor writes such a header: the sentence
    carries a colon, and YAML reads that as a second mapping."""
    text = "---\ndescription: Use when: the user says sort\n---\n\nSort it.\n"
    skill = skills.skill_aus_text("sortieren", text, ordner=tmp_path)
    assert skill.beschreibung == "Use when: the user says sort"


def test_die_beschreibung_darf_tausendvierundzwanzig_zeichen_lang_sein(tmp_path):
    lang = "w" * skills.MAX_BESCHREIBUNG
    skill = skills.skill_aus_text(
        "x", f"---\ndescription: {lang}\n---\n\nText.\n", ordner=tmp_path
    )
    assert skill.beschreibung == lang
    assert skills.MAX_BESCHREIBUNG == 1024


def test_ueber_der_grenze_kommt_die_absage_mit_der_zahl(tmp_path):
    lang = "w" * (skills.MAX_BESCHREIBUNG + 1)
    with pytest.raises(skills.SkillKaputt) as gefangen:
        skills.skill_aus_text(
            "x", f"---\ndescription: {lang}\n---\n\nText.\n", ordner=tmp_path
        )
    assert gefangen.value.kind == "beschreibung_lang"
    assert gefangen.value.values["grenze"] == 1024


def test_zwei_zeilen_die_zusammen_zu_lang_sind_werden_abgelehnt(tmp_path):
    """Joined first, measured after: a description that only grows past the
    budget by being joined is refused, never cut off at the seam."""
    halb = "w" * 600
    text = f"---\ndescription: {halb}\n  {halb}\n---\n\nText.\n"
    with pytest.raises(skills.SkillKaputt) as gefangen:
        skills.skill_aus_text("x", text, ordner=tmp_path)
    assert gefangen.value.kind == "beschreibung_lang"


def test_der_rueckfall_gibt_rohtext_und_kein_yaml(tmp_path):
    """What the line-wise reader hands over is TEXT: no quotes stripped, no
    comment cut off, no word turned into a boolean. `auto` is understood in
    its plain spelling, and anything else stays what it is and is refused —
    silently guessing here would be worse than saying so."""
    schlicht = skills.skill_aus_text(
        "x", "---\ndescription: Eins\nauto: true\n---\n\nText.\n", ordner=tmp_path
    )
    assert schlicht.auto is True
    # The header has to go through the FALLBACK, or the case proves
    # nothing: a second description line makes it unreadable for YAML.
    for krumm in ('"true"', "wahr"):
        with pytest.raises(skills.SkillKaputt, match="auto"):
            skills.skill_aus_text(
                "x",
                f"---\ndescription: Eins und\nnoch was\nauto: {krumm}\n---\n\nText.\n",
                ordner=tmp_path,
            )
    # And every spelling YAML reads as a truth value counts here too.
    for gut in ("yes", "on", "YES", "On", "off", "no", "NO"):
        erwartet = gut.strip().lower() in ("yes", "on", "true")
        skill = skills.skill_aus_text(
            "x",
            f"---\ndescription: Eins und\nnoch was\nauto: {gut}\n---\n\nText.\n",
            ordner=tmp_path,
        )
        assert skill.auto is erwartet, gut
    # In a header YAML cannot read, the comment BEHIND the word stays part of
    # the value (that is what "raw text" means) — the word is then no longer
    # a plain `true`, and the skill is refused rather than guessed at.
    with pytest.raises(skills.SkillKaputt, match="auto"):
        skills.skill_aus_text(
            "x", "---\ndescription: Eins und\nnoch etwas\nauto: true   # on\n---\n\nText.\n",
            ordner=tmp_path,
        )


def test_gueltiges_yaml_wird_weiter_feld_fuer_feld_gelesen(tmp_path):
    """Silence probe: a header YAML can read is read by YAML, exactly as
    before — the fallback is for what YAML cannot read."""
    text = (
        "---\n"
        "description: Sums this conversation up as a handover\n"
        "auto: true   # as written in the file\n"
        "---\n\nText.\n"
    )
    skill = skills.skill_aus_text("x", text, ordner=tmp_path)
    assert skill.beschreibung == "Sums this conversation up as a handover"
    assert skill.auto is True
    # And without `auto` it stays off, as always.
    ohne = skills.skill_aus_text(
        "x", "---\ndescription: Sums it up\n---\n\nText.\n", ordner=tmp_path
    )
    assert ohne.auto is False
    # Two more shapes of a VALID header, unread by the fallback: an indented
    # continuation line (YAML folds it itself) and a quoted value (YAML
    # strips the quotes). Both keep the strict path's behaviour — the
    # fallback is for what YAML cannot read.
    gefaltet = skills.skill_aus_text(
        "x", "---\ndescription: Sorts the inbox and\n  files by sender\n---\n\nText.\n",
        ordner=tmp_path,
    )
    assert gefaltet.beschreibung == "Sorts the inbox and files by sender"
    zitiert = skills.skill_aus_text(
        "x", '---\ndescription: "Eins"\n---\n\nText.\n', ordner=tmp_path
    )
    assert zitiert.beschreibung == "Eins"


def test_eine_kurze_einzeilige_beschreibung_bleibt_wie_sie_war(tmp_path):
    """Silence probe: the ordinary skill of today is read exactly as it was,
    character for character."""
    kurz = "Sums this conversation up as a handover"
    skill = skills.skill_aus_text(
        "x", f"---\ndescription: {kurz}\n---\n\nText.\n", ordner=tmp_path
    )
    assert skill.beschreibung == kurz


def test_die_route_nimmt_die_umbrochene_beschreibung_an(client):
    """Over the same door the editing mask uses: what the reader accepts, a
    person can store. Before this, the header could be neither created nor
    edited — the answer was 400 with the YAML sentence, and the folder was
    removed again."""
    antwort = client.post(
        "/api/v1/skills", json={"name": "sortieren", "inhalt": ZWEIZEILIG}
    )
    assert antwort.status_code == 201, antwort.text
    gelesen = client.get("/api/v1/skills")
    assert gelesen.status_code == 200, gelesen.text
    koerper = gelesen.json()
    eintraege = koerper.get("skills", koerper) if isinstance(koerper, dict) else koerper
    namen = [s["name"] for s in eintraege]
    assert "sortieren" in namen
    einer = [s for s in eintraege if s["name"] == "sortieren"][0]
    assert einer["beschreibung"] == "Sorts the inbox and"


# --- the automatic switch keeps what it does not change -----------------------


def test_the_auto_switch_keeps_a_description_with_a_hash(client):
    """Switching `auto` rewrites the header; the description comes back
    whole — not cut at the `#`, and the skill stays in the list."""
    description = "Sum it up #42 and count the rest"
    content = f'---\ndescription: "{description}"\nauto: false\n---\n\nCount it.\n'
    assert client.post(
        "/api/v1/skills", json={"name": "zaehlen", "inhalt": content}
    ).status_code == 201

    response = client.patch("/api/v1/skills/zaehlen", json={"auto": True})
    assert response.status_code == 200

    listed = next(row for row in client.get("/api/v1/skills").json() if row["name"] == "zaehlen")
    assert listed["beschreibung"] == description
    managed = _verwaltung(client, "zaehlen")
    assert managed["auto"] is True
    assert managed["beschreibung"] == description


# --- the header as the house writes it ----------------------------------------


@pytest.mark.parametrize(
    "description",
    [
        "Use for A---B and a----b",
        "Ctrl\x85 x \x9f y \x7f z",
        "Grüße: #1 yes",
    ],
    ids=["hyphen-runs", "c1-controls", "colon-hash-yes"],
)
def test_the_written_header_gives_back_the_description(tmp_path, description):
    """What JSON leaves raw and YAML or the header split cannot take is
    written as an escape: the description and `auto` read back unchanged,
    and the file can be written as UTF-8."""
    text = skills.skill_file_text(description, True, "Do it.")
    folder = tmp_path / "mein" / "probe"
    folder.mkdir(parents=True)
    (folder / skills.SKILL_DATEI).write_text(text, encoding="utf-8")
    read = skills.skill_lesen(folder)
    assert read.beschreibung == " ".join(description.split())
    assert read.auto is True
    assert read.anleitung == "Do it."


# --- a broken skill takes only itself out -------------------------------------


@pytest.mark.parametrize(
    ("head", "loads"),
    [
        ("description: Da\non: x\n", True),
        ("description: Da\n1: x\n", True),
        ("description: Da\nmodel: x\nyes: x\n", True),
        ("description: Da\nwhen: 2026-13-45\n", True),
        ("description: Da\nx: !!int abc\n", True),
        ("description: Da\nw: !!bool maybe\n", True),
        ("description: Da\nt: !!timestamp x\n", True),
        ("description: Da\nx: " + "[" * 5000 + "]" * 5000 + "\n", True),
        ("description: " + "[" * 5000 + "]" * 5000 + "\n", False),
    ],
    ids=["on-key", "number-key", "boolean-key-beside-agent-field", "bad-date",
         "bad-int-tag", "bad-bool-tag", "bad-timestamp-tag", "deep-nesting-beside",
         "deep-nesting-as-description"],
)
def test_an_odd_header_takes_only_its_own_skill_out(tmp_path, head, loads):
    """A key YAML reads as a boolean or a number, a value it refuses to
    build, a header nested past the parser's stack: the healthy skill beside
    it stays in the list, and the odd one is read or skipped on its own."""
    folder = tmp_path / "mein"
    _schreiben(folder, "heil", GUT)
    _schreiben(folder, "seltsam", f"---\n{head}---\n\nText.\n")

    loaded = skills.skills_laden(tmp_path / "haus", folder)
    assert "heil" in loaded
    assert ("seltsam" in loaded) is loads
    if loads:
        assert loaded["seltsam"].beschreibung == "Da"


def test_a_file_that_is_not_utf8_takes_only_itself_out(tmp_path, caplog):
    folder = tmp_path / "mein"
    _schreiben(folder, "heil", GUT)
    broken = folder / "kaputt"
    broken.mkdir(parents=True)
    (broken / skills.SKILL_DATEI).write_bytes(b"---\ndescription: \xff\n---\n\nText.\n")

    loaded = skills.skills_laden(tmp_path / "haus", folder)
    assert sorted(loaded) == ["heil"]
    assert any("kaputt" in record.getMessage() for record in caplog.records)



# --- the switch changes only `auto`, lands whole and survives an existing folder


KOPF_MIT_FREMDEM = """---
description: "Sums it up"
# a note somebody left in the header
version: 2
auto: false   # the switch
---

Sum the conversation up.
"""


def test_the_switch_changes_only_the_auto_line(client):
    """A field a newer version wrote, a comment in the header, the description
    as written and the instruction stay; only the value of `auto` changes,
    and the comment behind it stays too."""
    assert client.post(
        "/api/v1/skills", json={"name": "kopf", "inhalt": KOPF_MIT_FREMDEM}
    ).status_code == 201

    assert client.patch("/api/v1/skills/kopf", json={"auto": True}).status_code == 200

    gelesen = client.get("/api/v1/skills/kopf").json()["inhalt"]
    assert gelesen == KOPF_MIT_FREMDEM.replace("auto: false   # the switch", "auto: true   # the switch")
    assert _verwaltung(client, "kopf")["auto"] is True


def test_the_switch_writes_through_the_atomic_writer(client, monkeypatch):
    from app import atomic_file

    geschrieben = []
    echt = atomic_file.write
    monkeypatch.setattr(
        atomic_file, "write", lambda pfad, daten, **kw: (geschrieben.append(pfad), echt(pfad, daten, **kw))[1]
    )
    client.post("/api/v1/skills", json={"name": "atomar", "inhalt": NEU})

    assert client.patch("/api/v1/skills/atomar", json={"auto": False}).status_code == 200

    assert [p.name for p in geschrieben] == ["SKILL.md"]
    assert _verwaltung(client, "atomar")["auto"] is False


def test_the_switch_goes_into_an_existing_folder_without_a_skill_file(client):
    """A folder of the user's own by the skill's name, with a file of theirs
    and no SKILL.md: the shipped skill is copied into it, the file stays."""
    mitgeliefert, eigen = client.app.state.config.skillverzeichnisse
    werk = mitgeliefert / "werk2"
    werk.mkdir(parents=True)
    (werk / "SKILL.md").write_text(NEU, encoding="utf-8")
    (werk / "hilfe.md").write_text("shipped help", encoding="utf-8")
    ordner = eigen / "werk2"
    ordner.mkdir(parents=True)
    (ordner / "notes.md").write_text("mine", encoding="utf-8")
    (ordner / "hilfe.md").write_text("my own help", encoding="utf-8")

    antwort = client.patch("/api/v1/skills/werk2", json={"auto": False})

    assert antwort.status_code == 200
    assert (ordner / "notes.md").read_text(encoding="utf-8") == "mine"
    assert (ordner / "hilfe.md").read_text(encoding="utf-8") == "my own help"
    assert "auto: false" in (ordner / "SKILL.md").read_text(encoding="utf-8")


def test_editing_a_shipped_skill_goes_into_an_existing_folder_as_well(client):
    mitgeliefert, eigen = client.app.state.config.skillverzeichnisse
    werk = mitgeliefert / "werk3"
    werk.mkdir(parents=True)
    (werk / "SKILL.md").write_text(NEU, encoding="utf-8")
    ordner = eigen / "werk3"
    ordner.mkdir(parents=True)
    (ordner / "notes.md").write_text("mine", encoding="utf-8")

    geaendert = NEU.replace("short plan", "careful plan")
    antwort = client.put("/api/v1/skills/werk3", json={"inhalt": geaendert})

    assert antwort.status_code == 200
    assert (ordner / "notes.md").read_text(encoding="utf-8") == "mine"
    assert client.get("/api/v1/skills/werk3").json()["inhalt"] == geaendert


def test_a_skill_without_an_auto_line_gets_one_and_reads_as_automatic(client):
    """Silence probe: nothing else in the header moves."""
    inhalt = '---\ndescription: "No auto here"\n---\n\nDo it.\n'
    client.post("/api/v1/skills", json={"name": "ohne-auto", "inhalt": inhalt})
    assert _verwaltung(client, "ohne-auto")["auto"] is False

    assert client.patch("/api/v1/skills/ohne-auto", json={"auto": True}).status_code == 200

    assert client.get("/api/v1/skills/ohne-auto").json()["inhalt"] == (
        '---\ndescription: "No auto here"\nauto: true\n---\n\nDo it.\n'
    )
    assert _verwaltung(client, "ohne-auto")["auto"] is True


def test_a_shipped_skill_is_copied_whole_when_the_switch_is_used(client):
    """Silence probe: the shipped folder with its companion files, as before."""
    mitgeliefert, eigen = client.app.state.config.skillverzeichnisse
    werk = mitgeliefert / "werk4"
    werk.mkdir(parents=True)
    (werk / "SKILL.md").write_text(NEU, encoding="utf-8")
    (werk / "beilage.md").write_text("companion", encoding="utf-8")

    assert client.patch("/api/v1/skills/werk4", json={"auto": False}).status_code == 200

    assert (eigen / "werk4" / "beilage.md").read_text(encoding="utf-8") == "companion"
    assert (werk / "SKILL.md").read_text(encoding="utf-8") == NEU
    assert _verwaltung(client, "werk4")["eigen"] is True


@pytest.mark.parametrize(
    "text, expected",
    [
        ("---\nauto: false\ndescription: x\n---\nbody\n", "---\nauto: true\ndescription: x\n---\nbody\n"),
        ("---\r\ndescription: x\r\nauto: false\r\n---\r\nbody\r\n", "---\r\ndescription: x\r\nauto: true\r\n---\r\nbody\r\n"),
        ("---\ndescription: x\nauto:\n---\nbody\n", "---\ndescription: x\nauto: true\n---\nbody\n"),
        ("---\ndescription: |\n  auto: false\n  more\n---\nbody\n", "---\ndescription: |\n  auto: false\n  more\nauto: true\n---\nbody\n"),
        ("﻿---\ndescription: x\n---\nbody\n", "﻿---\ndescription: x\nauto: true\n---\nbody\n"),
    ],
    ids=["first", "crlf", "empty-value", "indented-line-is-not-the-field", "bom"],
)
def test_with_auto_keeps_every_other_byte(text, expected):
    assert skills.with_auto(text, True) == expected


def test_a_flow_style_header_still_loads_after_the_switch(client):
    """A header written as one flow mapping has no `auto` line to change; the
    switch then writes the file the house way instead of leaving a skill that
    no longer reads."""
    inhalt = '---\n{description: "Flow header", auto: false}\n---\n\nDo it.\n'
    assert client.post("/api/v1/skills", json={"name": "fluss", "inhalt": inhalt}).status_code == 201
    assert _verwaltung(client, "fluss")["auto"] is False

    assert client.patch("/api/v1/skills/fluss", json={"auto": True}).status_code == 200

    zeile = _verwaltung(client, "fluss")
    assert zeile is not None and zeile["auto"] is True
    assert zeile["beschreibung"] == "Flow header"
