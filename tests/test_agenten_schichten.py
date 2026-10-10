"""The two agent layers (shipped + the user's), mirroring the skills.

The shipped folder ``agenten/`` sits next to the program and is replaced by
every update; the user's ``prompts/agenten/`` is never touched. On a name
clash the user's file wins — which is exactly what lets a shipped agent
survive an update AND lets the user override it wholesale.
"""

from __future__ import annotations

from pathlib import Path

from app.agenten import (
    GELOESCHT_DATEI,
    agenten_laden,
    loeschung_merken,
)

WURZEL = Path(__file__).resolve().parent.parent


def _schreiben(ordner: Path, name: str, prompt: str) -> Path:
    ordner.mkdir(parents=True, exist_ok=True)
    datei = ordner / f"{name}.md"
    datei.write_text(f"---\nmodel: test\n---\n\n{prompt}\n", encoding="utf-8")
    return datei


def test_mitgelieferter_agent_wird_geladen(tmp_path):
    mitgeliefert = tmp_path / "agenten"
    eigen = tmp_path / "prompts" / "agenten"
    _schreiben(mitgeliefert, "recherche", "Shipped prompt.")

    agenten = agenten_laden(mitgeliefert, eigen)
    assert agenten["recherche"].prompt == "Shipped prompt."


def test_gleichnamiger_eigener_agent_gewinnt(tmp_path):
    mitgeliefert = tmp_path / "agenten"
    eigen = tmp_path / "prompts" / "agenten"
    _schreiben(mitgeliefert, "recherche", "Shipped prompt.")
    _schreiben(eigen, "recherche", "The user's own prompt.")

    agenten = agenten_laden(mitgeliefert, eigen)
    assert agenten["recherche"].prompt == "The user's own prompt."


def test_kaputte_eigene_datei_laesst_den_mitgelieferten_stehen(tmp_path):
    """A broken override takes only itself out of play — the shipped agent
    then stays in force rather than the name vanishing entirely."""
    mitgeliefert = tmp_path / "agenten"
    eigen = tmp_path / "prompts" / "agenten"
    _schreiben(mitgeliefert, "recherche", "Shipped prompt.")
    eigen.mkdir(parents=True, exist_ok=True)
    (eigen / "recherche.md").write_text("kein Kopfteil", encoding="utf-8")

    agenten = agenten_laden(mitgeliefert, eigen)
    assert agenten["recherche"].prompt == "Shipped prompt."


def test_das_paket_bringt_keinen_agenten_mit():
    """No agent ships with the program: every agent is one a person created.
    The shipped layer stays, empty, for an agent that is chosen to ship."""
    assert not list((WURZEL / "agenten").glob("*.md"))


# --- Through the API ---------------------------------------------------------


def _mitgeliefert_ordner(client) -> Path:
    config = client.app.state.config
    return config.mitgeliefert(config.app.agenten_mitgeliefert)


def test_agentenliste_zeigt_den_mitgelieferten(client):
    _schreiben(_mitgeliefert_ordner(client), "recherche", "Shipped prompt.")
    namen = {a["name"] for a in client.get("/api/v1/agents").json()}
    assert "recherche" in namen


def test_speichern_beschattet_den_mitgelieferten_statt_ihn_zu_aendern(client):
    """Editing a shipped agent must write the user's copy and leave the
    shipped file exactly as the update delivered it."""
    datei = _schreiben(_mitgeliefert_ordner(client), "recherche", "Shipped prompt.")
    vorher = datei.read_text(encoding="utf-8")

    gelesen = client.get("/api/v1/agents/recherche")
    assert gelesen.status_code == 200
    assert "Shipped prompt." in gelesen.json()["content"]

    neu = "---\nmodel: test\n---\n\nThe user's own prompt.\n"
    antwort = client.put("/api/v1/agents/recherche", json={"content": neu})
    assert antwort.status_code == 200

    assert datei.read_text(encoding="utf-8") == vorher
    config = client.app.state.config
    eigene = Path(config.app.agenten_verzeichnis) / "recherche.md"
    assert eigene.read_text(encoding="utf-8") == neu
    assert "The user's own" in client.get("/api/v1/agents/recherche").json()["content"]


def test_dateiliste_zeigt_beide_schichten_einmal(client):
    _schreiben(_mitgeliefert_ordner(client), "recherche", "Shipped prompt.")
    config = client.app.state.config
    _schreiben(Path(config.app.agenten_verzeichnis), "recherche", "Own prompt.")
    _schreiben(Path(config.app.agenten_verzeichnis), "eigener", "Own prompt.")

    namen = [e["name"] for e in client.get("/api/v1/agent-files").json()]
    assert namen.count("recherche") == 1
    assert "eigener" in namen


# --- Deleted is deleted (until the next update) ------------------------------


def test_geloeschter_mitgelieferter_bleibt_weg(tmp_path):
    """The note in the user's folder silences the shipped file."""
    mitgeliefert = tmp_path / "agenten"
    eigen = tmp_path / "prompts" / "agenten"
    _schreiben(mitgeliefert, "recherche", "Shipped prompt.")
    _schreiben(mitgeliefert, "zweiter", "Also shipped.")
    loeschung_merken(eigen, "recherche")

    agenten = agenten_laden(mitgeliefert, eigen)
    assert "recherche" not in agenten
    # The silent half: an undeleted neighbour must not vanish with it.
    assert "zweiter" in agenten


def test_eigene_datei_gewinnt_ueber_eine_alte_loeschung(tmp_path):
    """A file the user put there is the user's word — it stands, note or no
    note."""
    mitgeliefert = tmp_path / "agenten"
    eigen = tmp_path / "prompts" / "agenten"
    _schreiben(mitgeliefert, "recherche", "Shipped prompt.")
    loeschung_merken(eigen, "recherche")
    _schreiben(eigen, "recherche", "The user's own prompt.")

    agenten = agenten_laden(mitgeliefert, eigen)
    assert agenten["recherche"].prompt == "The user's own prompt."


def test_loeschung_verfaellt_mit_dem_update(tmp_path):
    """The house rule: a deleted shipped agent returns with the next update —
    the note carries the version, and a different version means the shipped
    folder was replaced."""
    import json

    mitgeliefert = tmp_path / "agenten"
    eigen = tmp_path / "prompts" / "agenten"
    _schreiben(mitgeliefert, "recherche", "Shipped prompt.")
    eigen.mkdir(parents=True, exist_ok=True)
    (eigen / GELOESCHT_DATEI).write_text(
        json.dumps({"recherche": "0.0.1"}), encoding="utf-8"
    )

    agenten = agenten_laden(mitgeliefert, eigen)
    assert "recherche" in agenten


def test_loeschen_eines_mitgelieferten_ist_kein_404(client):
    """The editor's delete used to answer 404 for a shipped agent, because
    only the user's folder was ever checked. Deleted is deleted: the call
    succeeds, and every list stops naming the agent."""
    _schreiben(_mitgeliefert_ordner(client), "recherche", "Shipped prompt.")

    antwort = client.delete("/api/v1/agents/recherche")
    assert antwort.status_code == 204

    assert "recherche" not in {a["name"] for a in client.get("/api/v1/agents").json()}
    assert "recherche" not in [
        e["name"] for e in client.get("/api/v1/agent-files").json()
    ]
    assert client.get("/api/v1/agents/recherche").status_code == 404
    # Deleting what is already gone is the plain 404 it always was.
    assert client.delete("/api/v1/agents/recherche").status_code == 404


def test_loeschen_nimmt_beschattung_und_mitgelieferten_zusammen(client):
    """One delete, one result: the user's override goes, and the shipped
    file underneath does not quietly step back in."""
    _schreiben(_mitgeliefert_ordner(client), "recherche", "Shipped prompt.")
    config = client.app.state.config
    _schreiben(Path(config.app.agenten_verzeichnis), "recherche", "Own prompt.")

    assert client.delete("/api/v1/agents/recherche").status_code == 204
    assert "recherche" not in {a["name"] for a in client.get("/api/v1/agents").json()}


def test_neu_speichern_hebt_die_loeschung_auf(client):
    """Saving under the deleted name is creating it anew — the note falls,
    the file counts."""
    _schreiben(_mitgeliefert_ordner(client), "recherche", "Shipped prompt.")
    assert client.delete("/api/v1/agents/recherche").status_code == 204

    neu = "---\nmodel: test\n---\n\nBorn again.\n"
    assert client.put("/api/v1/agents/recherche", json={"content": neu}).status_code == 200
    assert "recherche" in {a["name"] for a in client.get("/api/v1/agents").json()}
    assert "Born again." in client.get("/api/v1/agents/recherche").json()["content"]
