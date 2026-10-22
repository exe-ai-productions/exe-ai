"""The agent as a file: read the header, survive broken files."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import config_file
from app.agenten import (
    STANDARD_MINUTEN,
    STANDARD_RUNDEN,
    AgentDateiKaputt,
    agent_lesen,
    agenten_laden,
)


def schreiben(ordner: Path, name: str, inhalt: str) -> Path:
    ordner.mkdir(parents=True, exist_ok=True)
    datei = ordner / f"{name}.md"
    datei.write_text(inhalt, encoding="utf-8")
    return datei


VOLLSTAENDIG = """---
model: mana
tools:
  - web_search
  - read_webpage
max_rounds: 10
max_minutes: 5
---

You are a research agent.
"""


def test_vollstaendige_datei_wird_gelesen(tmp_path):
    agent = agent_lesen(schreiben(tmp_path, "recherche", VOLLSTAENDIG))
    assert agent.name == "recherche"
    # No ``modell`` any more — the key is read, logged about and
    # dropped, exactly like the retired schedule keys.
    assert not hasattr(agent, "modell")
    assert agent.werkzeuge == ["web_search", "read_webpage"]
    assert agent.runden == 10
    assert agent.minuten == 5.0
    assert agent.prompt == "You are a research agent."


def test_vorgaben_greifen_bei_schweigsamem_kopfteil(tmp_path):
    """If a limit is missing from the header, the default applies — never none at all."""
    agent = agent_lesen(
        schreiben(tmp_path, "still", "---\nmodel: mana\n---\nTu was.\n")
    )
    assert agent.runden == STANDARD_RUNDEN
    assert agent.minuten == STANDARD_MINUTEN
    # tools: left out entirely, not an empty list — every approved
    # tool runs for this agent.
    assert agent.werkzeuge is None


def test_ohne_folders_bleibt_die_liste_leer(tmp_path):
    """No field means no shared folders — the permission is a deliberate act."""
    agent = agent_lesen(schreiben(tmp_path, "still", "---\nmodel: mana\n---\nTu was.\n"))
    assert agent.ordner == []


def test_folders_absolut_werden_uebernommen_und_entdoppelt(tmp_path):
    # Full paths of this system: a POSIX path is not one on Windows.
    code = str(Path(Path.cwd().anchor, "Users", "you", "code"))
    data = str(Path(Path.cwd().anchor, "data", "x"))
    kopf = f"---\nfolders:\n  - {code}\n  - {code}\n  - {data}\n---\nTu was.\n"
    agent = agent_lesen(schreiben(tmp_path, "leser", kopf))
    assert agent.ordner == [code, data]


def test_folders_mit_tilde_ist_kaputt(tmp_path):
    """~/code is not a complete path — refuse loudly, do not stay silent."""
    kopf = "---\nfolders:\n  - ~/code\n---\nTu was.\n"
    with pytest.raises(AgentDateiKaputt):
        agent_lesen(schreiben(tmp_path, "tilde", kopf))


def test_folders_relativ_ist_kaputt(tmp_path):
    kopf = "---\nfolders:\n  - code/sub\n---\nTu was.\n"
    with pytest.raises(AgentDateiKaputt):
        agent_lesen(schreiben(tmp_path, "relativ", kopf))


def test_folders_muss_eine_liste_sein(tmp_path):
    kopf = "---\nfolders: /Users/you/code\n---\nTu was.\n"
    with pytest.raises(AgentDateiKaputt):
        agent_lesen(schreiben(tmp_path, "kein_list", kopf))


def test_ohne_kopfteil_ist_die_datei_kaputt(tmp_path):
    with pytest.raises(AgentDateiKaputt, match="front matter"):
        agent_lesen(schreiben(tmp_path, "roh", "Nur Prompt, kein Kopf.\n"))


def test_ohne_schliessende_striche_ist_die_datei_kaputt(tmp_path):
    with pytest.raises(AgentDateiKaputt, match="closing"):
        agent_lesen(schreiben(tmp_path, "offen", "---\nmodel: mana\nTu was.\n"))


def test_kaputtes_yaml_ist_kaputt(tmp_path):
    with pytest.raises(AgentDateiKaputt, match="YAML"):
        agent_lesen(schreiben(tmp_path, "yaml", "---\nmodel: [ohne ende\n---\nx\n"))


def test_tools_muss_eine_liste_sein(tmp_path):
    with pytest.raises(AgentDateiKaputt, match="tools"):
        agent_lesen(schreiben(tmp_path, "t", "---\ntools: web_search\n---\nx\n"))


def test_weggelassenes_tools_ist_none_nicht_leer(tmp_path):
    agent = agent_lesen(schreiben(tmp_path, "t", "---\nmodel: mana\n---\nx\n"))
    assert agent.werkzeuge is None


def test_leeres_tools_bleibt_eine_leere_liste(tmp_path):
    """The field present but empty is a deliberate 'none of them' — not
    the same as leaving it out."""
    agent = agent_lesen(schreiben(tmp_path, "t", "---\ntools: []\n---\nx\n"))
    assert agent.werkzeuge == []


def test_tools_ohne_eintraege_zaehlt_auch_als_leer(tmp_path):
    """`tools:` with nothing written under it is YAML null, not a missing
    key — still a deliberate empty list, not "all tools"."""
    agent = agent_lesen(schreiben(tmp_path, "t", "---\ntools:\n---\nx\n"))
    assert agent.werkzeuge == []


def test_runden_muessen_eine_zahl_ab_1_sein(tmp_path):
    with pytest.raises(AgentDateiKaputt, match="max_rounds"):
        agent_lesen(schreiben(tmp_path, "r", "---\nmax_rounds: 0\n---\nx\n"))


def test_minuten_muessen_ueber_0_liegen(tmp_path):
    with pytest.raises(AgentDateiKaputt, match="max_minutes"):
        agent_lesen(schreiben(tmp_path, "m", "---\nmax_minutes: -3\n---\nx\n"))


def test_ohne_max_tokens_bleibt_es_leer(tmp_path):
    """Missing entirely means the agent has no opinion — the settings
    cascade decides, not a silently invented number."""
    agent = agent_lesen(schreiben(tmp_path, "still", "---\nmodel: mana\n---\nTu was.\n"))
    assert agent.max_tokens is None


def test_max_tokens_wird_uebernommen(tmp_path):
    agent = agent_lesen(schreiben(tmp_path, "budget", "---\nmax_tokens: 16000\n---\nx\n"))
    assert agent.max_tokens == 16000


def test_max_tokens_muss_eine_zahl_ab_1_sein(tmp_path):
    with pytest.raises(AgentDateiKaputt, match="max_tokens"):
        agent_lesen(schreiben(tmp_path, "t", "---\nmax_tokens: 0\n---\nx\n"))


def test_ohne_max_command_seconds_bleibt_es_leer(tmp_path):
    """Missing entirely means the agent has no opinion — the settings
    cascade decides (app/befehlszeitwahl.py), not a silently invented
    number."""
    agent = agent_lesen(schreiben(tmp_path, "still2", "---\nmodel: mana\n---\nTu was.\n"))
    assert agent.befehlssekunden is None


def test_max_command_seconds_wird_uebernommen(tmp_path):
    agent = agent_lesen(
        schreiben(tmp_path, "zeit", "---\nmax_command_seconds: 600\n---\nx\n")
    )
    assert agent.befehlssekunden == 600


def test_max_command_seconds_muss_eine_zahl_ab_1_sein(tmp_path):
    for wert in ("0", "-5", "true", "'600'"):
        with pytest.raises(AgentDateiKaputt, match="max_command_seconds"):
            agent_lesen(
                schreiben(tmp_path, "z", f"---\nmax_command_seconds: {wert}\n---\nx\n")
            )


def test_max_tokens_hat_eine_obergrenze(tmp_path):
    """Same ceiling as the chat request schema — a typo with an extra digit
    must not silently become the job's actual budget."""
    with pytest.raises(AgentDateiKaputt, match="max_tokens"):
        agent_lesen(schreiben(tmp_path, "t", "---\nmax_tokens: 1000001\n---\nx\n"))


def test_max_tokens_an_der_obergrenze_ist_gueltig(tmp_path):
    agent = agent_lesen(schreiben(tmp_path, "t", "---\nmax_tokens: 1000000\n---\nx\n"))
    assert agent.max_tokens == 1_000_000


def test_max_tokens_bool_wird_abgewiesen(tmp_path):
    """True/False pass isinstance(_, int) in Python — refuse explicitly,
    the same trap max_rounds already guards against."""
    with pytest.raises(AgentDateiKaputt, match="max_tokens"):
        agent_lesen(schreiben(tmp_path, "t", "---\nmax_tokens: true\n---\nx\n"))


def test_ohne_prompt_ist_die_datei_kaputt(tmp_path):
    with pytest.raises(AgentDateiKaputt, match="no prompt"):
        agent_lesen(schreiben(tmp_path, "leer", "---\nmodel: mana\n---\n\n"))


def test_unbekannte_felder_stoeren_nicht(tmp_path):
    """A file from a newer program version stays readable."""
    agent = agent_lesen(
        schreiben(tmp_path, "neu", "---\nmodel: mana\nzukunft: ja\n---\nx\n")
    )
    assert agent.prompt == "x"


def test_kaputte_datei_nimmt_nur_diesen_agenten_aus_dem_spiel(tmp_path):
    """Decision from 6.3: no service outage because of one agent file."""
    schreiben(tmp_path, "gesund", VOLLSTAENDIG)
    schreiben(tmp_path, "krank", "kein kopfteil")
    agenten = agenten_laden(tmp_path)
    assert sorted(agenten) == ["gesund"]


def test_fehlender_ordner_heisst_keine_agenten(tmp_path):
    assert agenten_laden(tmp_path / "gibtsnicht") == {}


def test_ungueltige_bytes_nehmen_nur_diesen_agenten_aus_dem_spiel(tmp_path):
    """Bytes that are no UTF-8 take out exactly this one agent, not the load
    — they come back from the one read place as a broken agent file."""
    schreiben(tmp_path, "gesund", VOLLSTAENDIG)
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "krank.md").write_bytes(b"---\nmodel: x\n---\nHallo \xff\xfe kaputt")
    agenten = agenten_laden(tmp_path)
    assert sorted(agenten) == ["gesund"]


# --- permissions: per-agent overrides for Tor 3 ----------------------------


def test_permissions_werden_gelesen(tmp_path):
    agent = agent_lesen(schreiben(
        tmp_path, "streng",
        "---\nmodel: mana\npermissions:\n  run_command: nein\n---\nx\n",
    ))
    assert agent.berechtigungen == {"run_command": "nein"}


def test_ohne_permissions_bleibt_die_liste_leer(tmp_path):
    agent = agent_lesen(schreiben(tmp_path, "ohne", "---\nmodel: mana\n---\nx\n"))
    assert agent.berechtigungen == {}


def test_permissions_muss_eine_feldliste_sein(tmp_path):
    with pytest.raises(AgentDateiKaputt, match="permissions"):
        agent_lesen(schreiben(tmp_path, "p", "---\npermissions: nein\n---\nx\n"))


def test_permissions_wert_muss_ja_fragen_oder_nein_sein(tmp_path):
    with pytest.raises(AgentDateiKaputt, match="permissions"):
        agent_lesen(schreiben(
            tmp_path, "p", "---\npermissions:\n  run_command: vielleicht\n---\nx\n",
        ))


def test_permissions_mit_unhashbarem_wert_ist_kaputt_nicht_abgestuerzt(tmp_path):
    """A nested list where a plain answer belongs is a broken file, not a
    crash — the check itself must not choke on the very value it rejects."""
    with pytest.raises(AgentDateiKaputt, match="permissions"):
        agent_lesen(schreiben(
            tmp_path, "p",
            "---\npermissions:\n  run_command:\n    - ja\n    - nein\n---\nx\n",
        ))


def test_farbe_wird_gelesen(tmp_path):
    """Which colour an agent's name is written in stands in its file, like
    every other field it carries."""
    agent = agent_lesen(schreiben(
        tmp_path, "bunt", '---\ncolor: "#2f8f84"\n---\nx\n',
    ))
    assert agent.farbe == "#2f8f84"


def test_ohne_farbe_bleibt_die_farbe_ungesagt(tmp_path):
    """The silence test: an agent that picked none must look exactly as
    every agent looked before the field existed."""
    agent = agent_lesen(schreiben(tmp_path, "schlicht", "---\n---\nx\n"))
    assert agent.farbe is None


def test_eine_farbe_muss_ein_farbwert_sein(tmp_path):
    with pytest.raises(AgentDateiKaputt, match="color"):
        agent_lesen(schreiben(tmp_path, "f", "---\ncolor: tuerkis\n---\nx\n"))


def test_kurzschreibweise_der_farbe_wird_abgelehnt(tmp_path):
    """One spelling, so the file and the picker always say the same thing."""
    with pytest.raises(AgentDateiKaputt, match="color"):
        agent_lesen(schreiben(tmp_path, "f", '---\ncolor: "#2f8"\n---\nx\n'))


# --- A broken file is explained in the language of the page -------------------


@pytest.mark.parametrize(
    ("language", "budget_text", "front_text"),
    [
        ("en", "'reasoning_budget' must be a number between", "the closing '---' line is missing"),
        ("de", "'reasoning_budget' muss eine Zahl zwischen", "die schließende '---'-Zeile fehlt"),
    ],
)
def test_a_broken_agent_file_speaks_the_language_of_the_page(client, language, budget_text, front_text):
    from pathlib import Path as _Path

    folder = _Path(client.app.state.config.app.agenten_verzeichnis)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "thinker.md").write_text(
        "---\nreasoning_budget: 99999999\n---\n\nThink.\n", encoding="utf-8"
    )
    (folder / "unclosed.md").write_text("---\ndescription: x\nGo.\n", encoding="utf-8")
    header = {"Accept-Language": language}

    listed = {
        e["name"]: e["kaputt"]
        for e in client.get("/api/v1/agent-files", headers=header).json()
    }
    assert budget_text in listed["thinker"]
    assert front_text in listed["unclosed"]

    answer = client.put(
        "/api/v1/agents/thinker/fields", json={"reasoning_budget": 99999999},
        headers=header,
    )
    assert answer.status_code == 422
    assert budget_text in answer.json()["detail"]


def test_a_valid_agent_file_is_not_broken(client):
    from pathlib import Path as _Path

    folder = _Path(client.app.state.config.app.agenten_verzeichnis)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "good.md").write_text("---\ndescription: x\n---\n\nGo.\n", encoding="utf-8")
    listed = {e["name"]: e["kaputt"] for e in client.get("/api/v1/agent-files").json()}
    assert listed["good"] is None


def test_a_broken_file_error_survives_copy_and_pickle():
    import copy
    import pickle

    from app.agentenfelder import KopfteilKaputt

    error = AgentDateiKaputt("a.md", "folders_full", path="rel")
    again = pickle.loads(pickle.dumps(error))
    assert again.text("de") == error.text("de")
    assert str(copy.copy(error)) == str(error)
    assert copy.copy(KopfteilKaputt("front_missing")).text("en") == KopfteilKaputt(
        "front_missing"
    ).text("en")


# --- A file that is not UTF-8 ------------------------------------------------


def _agentenordner(client):
    """The folder the routes read the user's own agent files from."""
    from pathlib import Path as _Path

    folder = _Path(client.app.state.config.app.agenten_verzeichnis)
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _kranke_datei(client):
    """A file with bytes that are not UTF-8."""
    datei = _agentenordner(client) / "krank.md"
    datei.write_bytes(b"---\nmodel: x\n---\nHallo \xff\xfe kaputt")
    return datei


@pytest.mark.parametrize(
    ("language", "text"),
    [
        ("en", "The file is not saved as UTF-8."),
        ("de", "Die Datei ist nicht als UTF-8 gespeichert."),
    ],
)
def test_eine_datei_die_kein_utf8_ist_wird_gemeldet(client, language, text):
    """The list names it as broken instead of falling over; the view and the
    save refuse it with the same sentence; the file keeps its bytes.

    The sentence carries the file's name in front, like every other reason a
    broken agent file has (`AgentDateiKaputt.text`): the decode error is one
    breakage among the others, not a second kind of answer."""
    datei = _kranke_datei(client)
    vorher = datei.read_bytes()
    header = {"Accept-Language": language}
    satz = f"'krank.md': {text}"

    liste = client.get("/api/v1/agent-files", headers=header)
    assert liste.status_code == 200
    gemeldet = {e["name"]: e["kaputt"] for e in liste.json()}["krank"]
    assert gemeldet == satz

    ansicht = client.get("/api/v1/agents/krank", headers=header)
    assert ansicht.status_code == 422
    assert ansicht.json()["detail"] == satz

    speichern = client.put(
        "/api/v1/agents/krank/fields",
        json={"description": "Anders."},
        headers=header,
    )
    assert speichern.status_code == 422
    assert speichern.json()["detail"] == satz

    assert datei.read_bytes() == vorher


def test_eine_datei_mit_byte_order_mark_ist_gesund(client):
    """A byte order mark is how a Windows editor writes UTF-8 — that file is
    read, listed without a fault and opened; only the BOM itself is gone.

    And it is a healthy agent everywhere else too: through the loader the
    runs, the schedules and the chat's tool use read, and in the list they
    offer."""
    order = _agentenordner(client)
    datei = order / "bom.md"
    datei.write_bytes("---\ndescription: x\n---\n\nMach.\n".encode("utf-8-sig"))

    liste = client.get("/api/v1/agent-files").json()
    assert {e["name"]: e["kaputt"] for e in liste}["bom"] is None
    gelesen = client.get("/api/v1/agents/bom")
    assert gelesen.status_code == 200
    assert not gelesen.json()["content"].startswith("﻿")

    assert agenten_laden(order)["bom"].prompt == "Mach."
    assert "bom" in {a["name"] for a in client.get("/api/v1/agents").json()}


def test_eine_kaputte_notizdatei_reisst_die_liste_nicht_mit(client):
    """``geloescht.json`` with bytes that are no UTF-8 costs the note and
    nothing else: an unusable note is an empty note, and both lists answer."""
    from app.agenten import GELOESCHT_DATEI

    (_agentenordner(client) / GELOESCHT_DATEI).write_bytes(b'{"a": "\xff\xfe"}')

    assert client.get("/api/v1/agent-files").status_code == 200
    assert client.get("/api/v1/agents").status_code == 200


def test_eine_gueltige_notizdatei_bleibt_gueltig(client):
    """Silence probe for the note file: a readable one is READ, and only the
    entries of this build's version count.

    The stale entry beside the fresh one is the measurement: with the version
    filter gone both names would come back, with the note never read neither
    — a note carrying only a stale version would hold in both cases."""
    import json

    from app.agenten import GELOESCHT_DATEI, __version__, geloeschte_agenten

    order = _agentenordner(client)
    (order / GELOESCHT_DATEI).write_text(
        json.dumps({"irgendein-agent": __version__, "veraltet": "0.0.0"}),
        encoding="utf-8",
    )
    assert client.get("/api/v1/agent-files").status_code == 200
    assert geloeschte_agenten(order) == {"irgendein-agent"}


def test_eine_notizdatei_mit_byte_order_mark_zaehlt(client):
    """A note a Windows editor saved as "UTF-8 with BOM" is read like every
    other text of this program: the mark falls away when decoding, and the
    entry counts."""
    import json

    from app.agenten import GELOESCHT_DATEI, __version__, geloeschte_agenten

    order = _agentenordner(client)
    (order / GELOESCHT_DATEI).write_bytes(
        json.dumps({"irgendein-agent": __version__}).encode("utf-8-sig")
    )
    assert geloeschte_agenten(order) == {"irgendein-agent"}


def test_eine_notizdatei_ohne_json_kostet_nur_die_notiz(client):
    """Text that is valid UTF-8 and no JSON at all: the note is unusable, the
    agents are not — the branch the JSON error stands for."""
    from app.agenten import GELOESCHT_DATEI, geloeschte_agenten

    order = _agentenordner(client)
    (order / GELOESCHT_DATEI).write_text("kein json", encoding="utf-8")
    assert geloeschte_agenten(order) == set()
    assert client.get("/api/v1/agent-files").status_code == 200


@pytest.mark.platforms("posix", reason="a folder closed by its rights")
def test_ein_ordner_ohne_recht_kostet_die_notiz_nicht_die_liste(client):
    """The note is looked for inside a folder nobody may walk into: the look
    alone is an error, and it is the note's own bad luck — not the agents'.

    The probe in front is the premise of the whole test: if this
    interpreter's ``is_file()`` answered False here instead of raising, the
    test would hold without the catch it is meant to prove.

    The routes are deliberately not asked here. They answer, but with an
    empty list — a folder nobody may walk into hides its agents from ``glob``
    as well, and that is a separate matter of its own."""
    import json

    from app.agenten import GELOESCHT_DATEI, geloeschte_agenten

    order = _agentenordner(client)
    (order / GELOESCHT_DATEI).write_text(json.dumps({"geist": "1.0"}), encoding="utf-8")
    vorher = order.stat().st_mode
    order.chmod(0o000)  # a folder nobody may enter: only POSIX rights do that
    try:
        with pytest.raises(PermissionError):
            (order / GELOESCHT_DATEI).is_file()
        assert geloeschte_agenten(order) == set()
    finally:
        order.chmod(vorher)


@pytest.mark.parametrize(
    ("language", "text"),
    [
        ("en", "The file cannot be read."),
        ("de", "Die Datei lässt sich nicht lesen."),
    ],
)
@pytest.mark.platforms("posix", reason="a file closed by its rights")
def test_eine_datei_die_niemand_lesen_kann_wird_gemeldet(client, language, text):
    """A file the process may not read is that one file's own breakage, named
    like every other: the file's name in front, the sentence of the page's
    language behind it — not the system's English line with the private path.
    The view and the save answer 422 with the same sentence; the full line
    goes to the log."""
    datei = _kranke_datei(client)
    datei.chmod(0o000)
    header = {"Accept-Language": language}
    satz = f"'krank.md': {text}"
    try:
        liste = client.get("/api/v1/agent-files", headers=header)
        assert liste.status_code == 200
        gemeldet = {e["name"]: e["kaputt"] for e in liste.json()}["krank"]
        assert gemeldet == satz
        assert "Errno" not in gemeldet
        assert str(datei) not in gemeldet

        ansicht = client.get("/api/v1/agents/krank", headers=header)
        assert ansicht.status_code == 422
        assert ansicht.json()["detail"] == satz

        speichern = client.put(
            "/api/v1/agents/krank/fields",
            json={"description": "Anders."},
            headers=header,
        )
        assert speichern.status_code == 422
        assert speichern.json()["detail"] == satz
    finally:
        datei.chmod(0o600)


def test_ein_ordner_statt_einer_datei_wird_gemeldet(client):
    """A directory named ``ordner.md`` is the same kind of unreadable: the
    list names it in the page's language, with the file in front like every
    broken entry beside it, and without the system's line."""
    (_agentenordner(client) / "ordner.md").mkdir()

    liste = client.get("/api/v1/agent-files", headers={"Accept-Language": "de"})
    assert liste.status_code == 200
    gemeldet = {e["name"]: e["kaputt"] for e in liste.json()}["ordner"]
    assert gemeldet == "'ordner.md': Die Datei lässt sich nicht lesen."
    assert "Errno" not in gemeldet


def test_eine_gesunde_datei_oeffnet_und_speichert_wie_bisher(client):
    """Silence probe for the whole change: a readable file opens and takes
    the saved fields — read back off the disk, not off the answer."""
    datei = _agentenordner(client) / "gesund.md"
    datei.write_text("---\ndescription: x\n---\n\nMach.\n", encoding="utf-8")

    assert client.get("/api/v1/agents/gesund").status_code == 200
    geschrieben = client.put("/api/v1/agents/gesund/fields", json={"description": "Anders."})
    assert geschrieben.status_code == 200
    assert "Anders." in datei.read_text(encoding="utf-8")


# --- Saving an agent file -----------------------------------------------------

_ALT = "---\ndescription: alt\n---\n\nAlt.\n"
# The sentences are asserted in English; a page without a language is German.
_EN = {"Accept-Language": "en"}


@pytest.mark.parametrize(
    ("language", "text"),
    [
        ("en", "The file cannot be saved."),
        ("de", "Die Datei lässt sich nicht speichern."),
    ],
)
@pytest.mark.platforms("posix", reason="a folder closed by its rights")
def test_ein_ordner_ohne_schreibrecht_ist_ein_satz_kein_serverfehler(client, language, text):
    """Both saving routes answer 422 with the file's name and the sentence of
    the page's language — not a 500 — and the old file stays byte for byte."""
    import os

    if os.geteuid() == 0:
        pytest.skip("root may write into any folder")
    order = _agentenordner(client)
    datei = order / "alt.md"
    datei.write_text(_ALT, encoding="utf-8")
    vorher = datei.read_bytes()
    header = {"Accept-Language": language}
    satz = f"'alt.md': {text}"
    mode = order.stat().st_mode
    order.chmod(0o500)
    try:
        roh = client.put("/api/v1/agents/alt", json={"content": "neu"}, headers=header)
        felder = client.put(
            "/api/v1/agents/alt/fields", json={"description": "Anders."}, headers=header
        )
    finally:
        order.chmod(mode)

    assert (roh.status_code, roh.json()["detail"]) == (422, satz)
    assert (felder.status_code, felder.json()["detail"]) == (422, satz)
    assert datei.read_bytes() == vorher


@pytest.mark.parametrize("route", ["/api/v1/agents/alt", "/api/v1/agents/alt/fields"])
def test_ein_abbruch_beim_schreiben_laesst_die_alte_datei_stehen(client, monkeypatch, route):
    """The write ends in the step that takes the name — a full disk, a
    process ending: the old file is the whole old file and no side file is
    left in the folder."""
    import errno

    from app import atomic_file

    order = _agentenordner(client)
    datei = order / "alt.md"
    datei.write_text(_ALT, encoding="utf-8")
    vorher = datei.read_bytes()

    rename = atomic_file.rename_onto

    def voll(side, target):
        # The copy beside the file takes its name the same way and succeeds;
        # the file itself is the step that fails.
        if target.name.endswith(".vorher"):
            return rename(side, target)
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(atomic_file, "rename_onto", voll)
    body = {"content": "neu"} if route.endswith("alt") else {"description": "Anders."}
    antwort = client.put(route, json=body, headers=_EN)

    assert antwort.status_code == 422
    assert antwort.json()["detail"] == "'alt.md': The file cannot be saved."
    assert datei.read_bytes() == vorher
    # The previous version was set beside the file; no side file is left.
    assert sorted(p.name for p in order.iterdir()) == ["alt.md", "alt.md.vorher"]


def test_ein_gewoehnliches_speichern_schreibt_wie_bisher(client):
    """Silence probe for both routes: the file on the disk is what was sent."""
    order = _agentenordner(client)
    datei = order / "gewoehnlich.md"
    datei.write_text(_ALT, encoding="utf-8")

    roh = client.put(
        "/api/v1/agents/gewoehnlich",
        json={"content": "---\ndescription: roh\n---\n\nRoh.\n"},
    )
    assert roh.status_code == 200
    assert datei.read_text(encoding="utf-8") == "---\ndescription: roh\n---\n\nRoh.\n"

    felder = client.put("/api/v1/agents/gewoehnlich/fields", json={"description": "Form."})
    assert felder.status_code == 200
    assert 'description: "Form."' in datei.read_text(encoding="utf-8")
    assert sorted(p.name for p in order.iterdir()) == ["gewoehnlich.md", "gewoehnlich.md.vorher"]


# --- What lies under an agent's name ------------------------------------------

_KEINE_DATEI = "'{name}': There is no regular file under this name in the agents folder."


@pytest.mark.platforms("posix", reason="symbolic links need no rights there")
def test_ein_link_aus_dem_agentenordner_heraus_wird_in_keiner_route_angefasst(
    client, tmp_path_factory
):
    """A link in the folder that points at a file outside it is no agent
    file: view, both saves and the deletion refuse with the sentence, the
    file outside keeps its bytes and the link stays a link."""
    draussen = tmp_path_factory.mktemp("draussen") / "fremd.txt"
    draussen.write_text("fremd", encoding="utf-8")
    link = _agentenordner(client) / "link.md"
    link.symlink_to(draussen)
    satz = _KEINE_DATEI.format(name="link.md")

    antworten = [
        client.get("/api/v1/agents/link", headers=_EN),
        client.put("/api/v1/agents/link", json={"content": "---\ndescription: x\n---\n\nHi.\n"}, headers=_EN),
        client.put("/api/v1/agents/link/fields", json={"description": "x", "prompt": "Hi."}, headers=_EN),
        client.delete("/api/v1/agents/link", headers=_EN),
    ]

    for antwort in antworten:
        assert antwort.status_code == 422
        assert antwort.json()["detail"] == satz
    assert draussen.read_text(encoding="utf-8") == "fremd"
    assert link.is_symlink()


@pytest.mark.platforms("posix", reason="symbolic links need no rights there")
def test_ein_toter_link_legt_ausserhalb_keine_datei_an(client, tmp_path_factory):
    """A link whose target does not exist yet: the save would create the file
    behind the link, outside the folder. It refuses, and nothing appears."""
    ziel = tmp_path_factory.mktemp("draussen") / "neu.md"
    link = _agentenordner(client) / "tot.md"
    link.symlink_to(ziel)

    antwort = client.put(
        "/api/v1/agents/tot", json={"content": "---\ndescription: x\n---\n\nHi.\n"}, headers=_EN
    )

    assert antwort.status_code == 422
    assert antwort.json()["detail"] == _KEINE_DATEI.format(name="tot.md")
    assert not ziel.exists()


@pytest.mark.platforms("posix", reason="symbolic links need no rights there")
def test_ein_link_innerhalb_des_ordners_und_ein_ordner_als_link_arbeiten_wie_bisher(
    client, tmp_path_factory
):
    """Silence probe: what the barrier lets through still works. A link to
    a file of the same folder is read and saved through, and stays a link.
    An agents folder that is itself a link takes a new agent."""
    order = _agentenordner(client)
    echt = order / "echt.md"
    echt.write_text(_ALT, encoding="utf-8")
    (order / "kurz.md").symlink_to(echt)

    assert client.get("/api/v1/agents/kurz").status_code == 200
    gespeichert = client.put(
        "/api/v1/agents/kurz", json={"content": "---\ndescription: neu\n---\n\nNeu.\n"}
    )
    assert gespeichert.status_code == 200
    assert (order / "kurz.md").is_symlink()
    assert "description: neu" in echt.read_text(encoding="utf-8")

    anderswo = tmp_path_factory.mktemp("anderswo")
    for rest in order.iterdir():
        rest.unlink()
    order.rmdir()
    order.symlink_to(anderswo, target_is_directory=True)
    angelegt = client.put(
        "/api/v1/agents/frisch/fields", json={"description": "x", "prompt": "Hi."}
    )
    assert angelegt.status_code == 200
    assert (anderswo / "frisch.md").is_file()


def test_ein_ordner_unter_dem_namen_ist_ein_satz_kein_serverfehler(client):
    """A folder called ``ordner.md`` is no agent file: every route that
    reaches the name says so, and the folder is left as it was."""
    ordner = _agentenordner(client) / "ordner.md"
    ordner.mkdir()
    satz = _KEINE_DATEI.format(name="ordner.md")

    antworten = [
        client.get("/api/v1/agents/ordner", headers=_EN),
        client.put("/api/v1/agents/ordner", json={"content": "---\ndescription: x\n---\n\nHi.\n"}, headers=_EN),
        client.put("/api/v1/agents/ordner/fields", json={"description": "x", "prompt": "Hi."}, headers=_EN),
        client.delete("/api/v1/agents/ordner", headers=_EN),
    ]

    for antwort in antworten:
        assert antwort.status_code == 422
        assert antwort.json()["detail"] == satz
    assert ordner.is_dir()
    assert list(ordner.iterdir()) == []


def test_ein_freier_name_legt_den_agenten_an_wie_bisher(client):
    """Silence probe: nothing under the name — the agent is created."""
    angelegt = client.put(
        "/api/v1/agents/frei/fields", json={"description": "x", "prompt": "Hi."}
    )

    assert angelegt.status_code == 200
    assert (_agentenordner(client) / "frei.md").is_file()


# --- The previous version beside the file ------------------------------------

_NEBEN = ".vorher"


def test_vor_dem_speichern_liegt_die_vorige_fassung_daneben(client):
    """An agent file whose bytes are no text is replaced by what the page
    then sends — empty. The bytes it had stand beside it afterwards, whole."""
    datei = _kranke_datei(client)
    vorher = datei.read_bytes()

    antwort = client.put("/api/v1/agents/krank", json={"content": ""})

    assert antwort.status_code == 200
    assert datei.read_bytes() == b""
    assert (datei.parent / f"krank.md{_NEBEN}").read_bytes() == vorher


def test_das_formular_legt_die_vorige_fassung_daneben(client):
    datei = _agentenordner(client) / "gesund.md"
    datei.write_text("---\ndescription: vorher\n---\n\nMach.\n", encoding="utf-8")
    vorher = datei.read_bytes()

    antwort = client.put("/api/v1/agents/gesund/fields", json={"description": "nachher"})

    assert antwort.status_code == 200
    assert datei.read_bytes() != vorher
    assert (datei.parent / f"gesund.md{_NEBEN}").read_bytes() == vorher


def test_jedes_sichern_ersetzt_die_eine_fassung_daneben(client):
    """Two saves: the copy beside is the file as it was before the second."""
    datei = _agentenordner(client) / "zweimal.md"
    datei.write_text("---\ndescription: eins\n---\n\nMach.\n", encoding="utf-8")
    zwei = "---\ndescription: zwei\n---\n\nMach.\n"
    drei = "---\ndescription: drei\n---\n\nMach.\n"

    assert client.put("/api/v1/agents/zweimal", json={"content": zwei}).status_code == 200
    assert client.put("/api/v1/agents/zweimal", json={"content": drei}).status_code == 200

    assert (datei.parent / f"zweimal.md{_NEBEN}").read_text(encoding="utf-8") == zwei
    assert datei.read_text(encoding="utf-8") == drei


def test_die_datei_daneben_ist_kein_agent_in_keiner_liste(client):
    """Silence probe: the lists name what they named before the save."""
    datei = _agentenordner(client) / "liste.md"
    datei.write_text("---\ndescription: a\n---\n\nMach.\n", encoding="utf-8")
    vorher_dateien = {e["name"] for e in client.get("/api/v1/agent-files").json()}
    vorher_agenten = {a["name"] for a in client.get("/api/v1/agents").json()}

    assert client.put("/api/v1/agents/liste/fields", json={"description": "b"}).status_code == 200

    assert (datei.parent / f"liste.md{_NEBEN}").is_file()
    assert {e["name"] for e in client.get("/api/v1/agent-files").json()} == vorher_dateien
    assert {a["name"] for a in client.get("/api/v1/agents").json()} == vorher_agenten


def test_ein_erstes_sichern_legt_nichts_daneben(client):
    """A new agent and the first save over a shipped one have no previous
    version in the user's folder: nothing is set beside, the save is as it was."""
    from app.config import Config

    config: Config = client.app.state.config
    mitgeliefert = config.mitgeliefert(config.app.agenten_mitgeliefert)
    mitgeliefert.mkdir(parents=True, exist_ok=True)
    (mitgeliefert / "ausgeliefert.md").write_text(
        "---\ndescription: a\n---\n\nMach.\n", encoding="utf-8"
    )
    order = _agentenordner(client)

    neu = client.put("/api/v1/agents/neu/fields", json={"description": "x", "prompt": "Hi."})
    erstes = client.put("/api/v1/agents/ausgeliefert/fields", json={"description": "b"})

    assert (neu.status_code, erstes.status_code) == (200, 200)
    assert sorted(p.name for p in order.iterdir()) == ["ausgeliefert.md", "neu.md"]


def test_die_dateirouten_legen_die_vorige_fassung_weiter_daneben(client):
    """The one way is shared: the configuration file still has its copy."""
    config = client.app.state.config
    datei = config_file(config)
    vorher = datei.read_bytes() if datei.exists() else None
    datei.write_text("app:\n  language: en\n", encoding="utf-8")
    try:
        antwort = client.put("/api/v1/dateien/konfiguration", json={"inhalt": "app:\n  language: de\n"})

        assert antwort.status_code == 200
        beside = datei.with_name("config.yaml.vorher")
        assert beside.read_text(encoding="utf-8") == "app:\n  language: en\n"
    finally:
        if vorher is None:
            datei.unlink()
        else:
            datei.write_bytes(vorher)
        datei.with_name("config.yaml.vorher").unlink(missing_ok=True)


@pytest.mark.parametrize("route", ["/api/v1/agents/alt", "/api/v1/agents/alt/fields"])
def test_laesst_sich_die_vorige_fassung_nicht_danebenlegen_wird_nicht_geschrieben(
    client, monkeypatch, route
):
    """Partial failure: the copy cannot be made. The agent file stays byte
    for byte and the answer is the sentence of a save that failed."""
    import errno

    from app import previous_version

    datei = _agentenordner(client) / "alt.md"
    datei.write_text(_ALT, encoding="utf-8")
    vorher = datei.read_bytes()

    def voll(quelle, ziel):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(previous_version.shutil, "copy2", voll)
    body = {"content": "neu"} if route.endswith("alt") else {"description": "Anders."}
    antwort = client.put(route, json=body, headers=_EN)

    assert antwort.status_code == 422
    assert antwort.json()["detail"] == "'alt.md': The file cannot be saved."
    assert datei.read_bytes() == vorher
    assert [p.name for p in datei.parent.iterdir()] == ["alt.md"]


@pytest.mark.platforms("posix", reason="a copy closed by its rights")
def test_eine_schreibgeschuetzte_vorige_fassung_wird_trotzdem_ersetzt(client):
    """The copy beside keeps the rights of the file it was taken from. One
    that is read-only must not block every later save: it is replaced by the
    next copy, as a rename does not ask the file."""
    order = _agentenordner(client)
    datei = order / "alt.md"
    datei.write_text(_ALT, encoding="utf-8")
    daneben = order / f"alt.md{_NEBEN}"
    daneben.write_text("aelter", encoding="utf-8")
    daneben.chmod(0o444)

    antwort = client.put("/api/v1/agents/alt", json={"content": "---\ndescription: neu\n---\n\nNeu.\n"})

    assert antwort.status_code == 200
    assert daneben.read_text(encoding="utf-8") == _ALT
    assert sorted(p.name for p in order.iterdir()) == ["alt.md", f"alt.md{_NEBEN}"]
