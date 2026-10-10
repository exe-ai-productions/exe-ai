"""The exe.md of a shared folder: reading, creating, protecting, warning.

What is checked here is the behaviour the decisions actually rest on — a
folder without the file costing nothing, an existing file never being
touched, the write tool refusing to replace one, and the 4 KB warning
firing once rather than on every message.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from app import grundprompt, ordnerwissen
from app.events import Ereignisse, bus
from app.tools import datei_schreiben, grenzen


@pytest.fixture(autouse=True)
def sauber():
    ordnerwissen.vergessen()
    yield
    ordnerwissen.vergessen()


# --- Reading ------------------------------------------------------------------


def test_ein_ordner_ohne_datei_erzeugt_gar_nichts(tmp_path):
    """Not even a line saying there is none — that is the whole principle."""
    assert ordnerwissen.lesen([str(tmp_path)]) == []


def test_ein_ordner_mit_leerer_datei_erzeugt_gar_nichts(tmp_path):
    (tmp_path / ordnerwissen.DATEINAME).write_text("   \n\n", encoding="utf-8")
    assert ordnerwissen.lesen([str(tmp_path)]) == []


def test_die_reihenfolge_ist_die_der_freigabe(tmp_path):
    erst, dann = tmp_path / "a", tmp_path / "b"
    for ordner, text in ((erst, "A"), (dann, "B")):
        ordner.mkdir()
        (ordner / ordnerwissen.DATEINAME).write_text(text, encoding="utf-8")
    notizen = ordnerwissen.lesen([str(dann), str(erst)])
    assert [n.text for n in notizen] == ["B", "A"]


def test_nur_die_oberste_ebene_zaehlt(tmp_path):
    tief = tmp_path / "unterordner"
    tief.mkdir()
    (tief / ordnerwissen.DATEINAME).write_text("nicht diese", encoding="utf-8")
    assert ordnerwissen.lesen([str(tmp_path)]) == []


def test_eine_unlesbare_datei_nimmt_den_ordner_nicht_mit(tmp_path):
    (tmp_path / ordnerwissen.DATEINAME).write_bytes(b"\xff\xfe\x00kaputt")
    assert ordnerwissen.lesen([str(tmp_path)]) == []


# --- Creating -----------------------------------------------------------------


def test_freigeben_legt_das_geruest_an(tmp_path):
    ordnerwissen.anlegen([str(tmp_path)], tmp_path / "daten")
    assert (tmp_path / ordnerwissen.DATEINAME).read_text(encoding="utf-8") == (
        ordnerwissen.GERUEST
    )


def test_eine_vorhandene_datei_bleibt_unangetastet(tmp_path):
    datei = tmp_path / ordnerwissen.DATEINAME
    datei.write_text("meine eigene", encoding="utf-8")
    ordnerwissen.anlegen([str(tmp_path)], tmp_path / "daten")
    assert datei.read_text(encoding="utf-8") == "meine eigene"


def test_das_register_merkt_sich_woher_die_datei_kam(tmp_path):
    eigen, fremd = tmp_path / "eigen", tmp_path / "fremd"
    eigen.mkdir()
    fremd.mkdir()
    (fremd / ordnerwissen.DATEINAME).write_text("lag schon da", encoding="utf-8")
    daten = tmp_path / "daten"
    ordnerwissen.anlegen([str(eigen), str(fremd)], daten)
    assert ordnerwissen.herkunft(str(eigen), daten) == ordnerwissen.ANGELEGT
    assert ordnerwissen.herkunft(str(fremd), daten) == ordnerwissen.VORGEFUNDEN


def test_das_register_liegt_ausserhalb_des_freigegebenen_ordners(tmp_path):
    """Otherwise dropping a file in could rewrite the answer about it."""
    ordner = tmp_path / "geteilt"
    ordner.mkdir()
    daten = tmp_path / "daten"
    ordnerwissen.anlegen([str(ordner)], daten)
    assert (daten / ordnerwissen.REGISTER).is_file()
    assert not (ordner / ordnerwissen.REGISTER).exists()


def test_die_erste_antwort_ueber_die_herkunft_gilt(tmp_path):
    ordner = tmp_path / "geteilt"
    ordner.mkdir()
    daten = tmp_path / "daten"
    ordnerwissen.anlegen([str(ordner)], daten)
    ordnerwissen.anlegen([str(ordner)], daten)
    assert ordnerwissen.herkunft(str(ordner), daten) == ordnerwissen.ANGELEGT


@pytest.mark.platforms("posix", reason="a folder closed by its rights")
def test_ein_nicht_beschreibbarer_ordner_wirft_nicht(tmp_path):
    """The share succeeds either way — there is simply no exe.md."""
    ordner = tmp_path / "schreibgeschuetzt"
    ordner.mkdir()
    ordner.chmod(0o500)
    try:
        ordnerwissen.anlegen([str(ordner)], tmp_path / "daten")
        assert not (ordner / ordnerwissen.DATEINAME).exists()
    finally:
        ordner.chmod(0o700)


# --- The backup copy ----------------------------------------------------------


def test_die_sicherung_ueberlebt_das_loeschen_der_datei(tmp_path):
    ordner = tmp_path / "geteilt"
    ordner.mkdir()
    datei = ordner / ordnerwissen.DATEINAME
    datei.write_text("was drinstand", encoding="utf-8")
    daten = tmp_path / "daten"
    ordnerwissen.sichern(ordnerwissen.lesen([str(ordner)]), daten)
    datei.unlink()
    assert ordnerwissen.sicherung(str(ordner), daten) == "was drinstand"


def test_die_sicherung_wird_nur_bei_aenderung_geschrieben(tmp_path):
    ordner = tmp_path / "geteilt"
    ordner.mkdir()
    (ordner / ordnerwissen.DATEINAME).write_text("gleich", encoding="utf-8")
    daten = tmp_path / "daten"
    notizen = ordnerwissen.lesen([str(ordner)])
    ordnerwissen.sichern(notizen, daten)
    kopie = daten / ordnerwissen.SICHERUNGEN
    zuerst = next(kopie.iterdir()).stat().st_mtime_ns
    ordnerwissen.sichern(notizen, daten)
    assert next(kopie.iterdir()).stat().st_mtime_ns == zuerst


# --- The delete protection ----------------------------------------------------


def test_write_file_ersetzt_eine_bestehende_exemd_nicht(tmp_path):
    datei = tmp_path / ordnerwissen.DATEINAME
    datei.write_text("zweihundert Zeilen", encoding="utf-8")
    with pytest.raises(grenzen.GrenzeVerletzt) as fehler:
        asyncio.run(
            datei_schreiben.ausfuehren(
                {"path": ordnerwissen.DATEINAME, "content": "drei"}, [str(tmp_path)]
            )
        )
    assert "edit_file" in str(fehler.value)
    assert datei.read_text(encoding="utf-8") == "zweihundert Zeilen"


def test_write_file_legt_eine_fehlende_exemd_ganz_normal_an(tmp_path):
    antwort = asyncio.run(
        datei_schreiben.ausfuehren(
            {"path": ordnerwissen.DATEINAME, "content": "neu"}, [str(tmp_path)]
        )
    )
    assert "Created" in antwort
    assert (tmp_path / ordnerwissen.DATEINAME).read_text(encoding="utf-8") == "neu"


def test_der_schutz_gilt_nur_der_obersten_ebene(tmp_path):
    tief = tmp_path / "unterordner"
    tief.mkdir()
    (tief / ordnerwissen.DATEINAME).write_text("alt", encoding="utf-8")
    antwort = asyncio.run(
        datei_schreiben.ausfuehren(
            {"path": f"unterordner/{ordnerwissen.DATEINAME}", "content": "neu"},
            [str(tmp_path)],
        )
    )
    assert "Overwrote" in antwort


def test_eine_andere_datei_bleibt_ueberschreibbar(tmp_path):
    (tmp_path / "notiz.md").write_text("alt", encoding="utf-8")
    antwort = asyncio.run(
        datei_schreiben.ausfuehren(
            {"path": "notiz.md", "content": "neu"}, [str(tmp_path)]
        )
    )
    assert "Overwrote" in antwort


# --- The 4 KB threshold -------------------------------------------------------


def test_die_schwelle_meldet_einmal_je_chat_und_ordner(tmp_path):
    (tmp_path / ordnerwissen.DATEINAME).write_text(
        "x" * (ordnerwissen.SCHWELLE + 1), encoding="utf-8"
    )
    notizen = ordnerwissen.lesen([str(tmp_path)])
    gesehen: list[dict] = []
    handler = lambda **daten: gesehen.append(daten)  # noqa: E731
    bus.abonnieren(Ereignisse.EXEMD_ZU_GROSS, handler)
    try:
        assert len(ordnerwissen.melden("chat-1", notizen)) == 1
        ordnerwissen.melden("chat-1", notizen)
        ordnerwissen.melden("chat-1", notizen)
        # A second conversation is warned in its own right.
        ordnerwissen.melden("chat-2", notizen)
    finally:
        bus.abbestellen(Ereignisse.EXEMD_ZU_GROSS, handler)
    assert [d["chat_id"] for d in gesehen] == ["chat-1", "chat-2"]
    assert gesehen[0]["meldung"] == ordnerwissen.MELDUNG == "exe.md > 4 KB"


def test_eine_datei_unter_der_schwelle_meldet_nichts(tmp_path):
    (tmp_path / ordnerwissen.DATEINAME).write_text("kurz", encoding="utf-8")
    assert ordnerwissen.melden("chat", ordnerwissen.lesen([str(tmp_path)])) == []


def test_es_gibt_keinen_harten_deckel(tmp_path):
    """Whatever the size, the file travels whole — decided, and checked."""
    riesig = "y" * (ordnerwissen.SCHWELLE * 10)
    (tmp_path / ordnerwissen.DATEINAME).write_text(riesig, encoding="utf-8")
    notizen = ordnerwissen.lesen([str(tmp_path)])
    assert notizen[0].text == riesig
    text = grundprompt.bauen(
        ordner=[str(tmp_path)], ordnerwissen=ordnerwissen.fuer_prompt(notizen)
    )
    assert riesig in text


# --- The prompt ---------------------------------------------------------------


def test_jede_notiz_traegt_ihren_ordner(tmp_path):
    text = grundprompt.bauen(
        ordner=["/eins", "/zwei"],
        ordnerwissen=[("/eins", "erstes"), ("/zwei", "zweites")],
    )
    assert "--- exe.md for /eins ---\nerstes" in text
    assert "--- exe.md for /zwei ---\nzweites" in text


def test_ohne_notizen_steht_nichts_im_prompt():
    text = grundprompt.bauen(ordner=["/eins"])
    assert "exe.md" not in text


def test_die_pflege_pflicht_haengt_am_eigenen_tor():
    ohne = grundprompt.bauen(ordner=["/eins"], ordnerwissen=[("/eins", "was")])
    mit = grundprompt.bauen(
        ordner=["/eins"], ordnerwissen=[("/eins", "was")], ordnerwissen_pflegen=True
    )
    assert "Keeping each `exe.md` current" not in ohne
    assert "Keeping each `exe.md` current" in mit


def _flach(text: str) -> str:
    """One line, single spaces — the blocks are wrapped at different columns,
    and the model reads the words, not the line breaks."""
    return " ".join(text.split())


def test_die_ausnahme_zitiert_die_beiden_regeln_die_sie_aufhebt():
    """Word for word, so the exception points at the very sentences it lifts —
    a paraphrase would leave the contradiction standing."""
    text = _flach(
        grundprompt.bauen(werkzeuge=True, ordner=["/eins"], ordnerwissen_pflegen=True)
    )
    ausnahme = _flach(grundprompt.EXEMD_PFLEGEN)
    for satz in (
        "Do not write or change files, and do not produce code, unless the "
        "user asked for it",
        "being allowed to change something without a prompt is not a reason "
        "to change it unasked",
    ):
        # Once where the rule stands, once where the exception names it.
        assert text.count(satz) == 2
        assert satz in ausnahme


def test_die_entscheidungsfrage_braucht_beide_seiten():
    frage = "would this still be true in a different folder"
    nur_gedaechtnis = grundprompt.bauen(gedaechtnis_schreiben=True)
    nur_ordner = grundprompt.bauen(ordner=["/eins"], ordnerwissen_pflegen=True)
    beide = grundprompt.bauen(
        ordner=["/eins"], ordnerwissen_pflegen=True, gedaechtnis_schreiben=True
    )
    assert frage not in _flach(nur_gedaechtnis).lower()
    assert frage not in _flach(nur_ordner).lower()
    assert frage in _flach(beide).lower()


def test_die_notizen_stehen_hinter_den_ordnern():
    """N6's order: the notes right after the folder list they belong to. The
    memory itself is appended behind the whole prompt with its own
    introduction (app/gedaechtnis.py), so inside this text the notes only
    need to follow the folders."""
    text = grundprompt.bauen(
        ordner=["/eins"],
        ordnerwissen=[("/eins", "was")],
    )
    assert (
        text.index("The user has shared these working folders")
        < text.index("Each shared folder can carry notes about itself")
    )


def test_die_notizen_stehen_unter_dem_benutzerprompt():
    """Rank, stated in the text itself: never above a machine rule."""
    assert "It ranks below these instructions" in grundprompt.EXEMD


# --- The wiring ---------------------------------------------------------------


def test_das_geruest_ist_englisch_und_ohne_beispielinhalt():
    zeilen = [z for z in ordnerwissen.GERUEST.splitlines() if z.startswith("## ")]
    assert zeilen == [
        "## Rules you cannot guess",
        "## How things are done here",
        "## Where things belong",
        "## Why it is built this way",
    ]
    assert "- " not in ordnerwissen.GERUEST


def test_das_register_uebersteht_eine_kaputte_datei(tmp_path):
    daten = tmp_path / "daten"
    daten.mkdir()
    (daten / ordnerwissen.REGISTER).write_text("{kein json", encoding="utf-8")
    ordner = tmp_path / "geteilt"
    ordner.mkdir()
    ordnerwissen.anlegen([str(ordner)], daten)
    assert (ordner / ordnerwissen.DATEINAME).is_file()
    assert json.loads((daten / ordnerwissen.REGISTER).read_text(encoding="utf-8"))


def test_schon_gewarnt_antwortet_vor_der_meldung(tmp_path):
    """Which folders are NEW is a question only answerable before ``melden``.

    Afterwards every file over the line is marked and the answer is always
    yes — which is why the caller that shows the warning once has to ask
    first. ``melden``'s own return is the state and repeats at every
    sentence, and a warning at every sentence is not a warning.
    """
    (tmp_path / ordnerwissen.DATEINAME).write_text("x" * 5000, encoding="utf-8")
    notizen = ordnerwissen.lesen([str(tmp_path)])
    ordner = notizen[0].ordner

    assert not ordnerwissen.schon_gewarnt("chat-neu", ordner)
    ordnerwissen.melden("chat-neu", notizen)
    assert ordnerwissen.schon_gewarnt("chat-neu", ordner)
    # Another conversation has not been told anything yet.
    assert not ordnerwissen.schon_gewarnt("chat-zwei", ordner)
