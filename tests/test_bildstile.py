"""Picture styles: a named template the prompt is drawn through.

The draw route takes the style's text and negative beside the prompt and
hands the generator the merged pair; the chat's history keeps the prompt as
it was typed. Same shape as test_bild_verfeinerung_api.py: the generator is
mocked, the test reads the job that would have reached it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import bildstile
from app.bildrunner import Bildrunner
from app.config import Config


@pytest.fixture
def bild_senden(config: Config, client: TestClient, monkeypatch, tmp_path: Path):
    config.app.bildmodelle_verzeichnis = str(tmp_path / "bildmodelle")
    ordner = tmp_path / "bildmodelle"
    ordner.mkdir(parents=True)
    (ordner / "base.safetensors").write_bytes(b"x")
    monkeypatch.setattr(Bildrunner, "programm", property(lambda self: Path("/fake/sd-cli")))
    aufgerufen: dict = {}

    def _erzeugen(self, auftrag, ziel):
        aufgerufen["auftrag"] = auftrag
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_bytes(b"PNG")
        return ziel

    monkeypatch.setattr(Bildrunner, "erzeugen", _erzeugen)

    def _senden(**felder):
        body = {"modell": "base.safetensors", **felder}
        antwort = client.post("/api/v1/bild", json=body)
        assert antwort.status_code == 201, antwort.text
        return aufgerufen["auftrag"]

    return _senden


def test_der_stil_setzt_den_prompt_an_seine_stelle(bild_senden):
    auftrag = bild_senden(prompt="Apfel", negativ="unscharf",
                          stil_text="Foto, {prompt}, scharf", stil_negativ="Zeichnung")
    assert auftrag.prompt == "Foto, Apfel, scharf"
    assert auftrag.negativ == "unscharf, Zeichnung"


def test_ohne_stil_geht_der_prompt_unveraendert_hinaus(bild_senden):
    auftrag = bild_senden(prompt="Apfel", negativ="unscharf")
    assert auftrag.prompt == "Apfel"
    assert auftrag.negativ == "unscharf"


def test_ein_text_ohne_platzhalter_folgt_dem_prompt():
    assert bildstile.anwenden("Apfel", "", "Ölgemälde", "") == ("Apfel, Ölgemälde", "")


def test_der_platzhalter_gilt_an_jeder_stelle():
    assert bildstile.anwenden("Apfel", "", "{prompt} und {prompt}", "")[0] == "Apfel und Apfel"


def test_das_negativ_des_stils_steht_auch_ohne_eigenes():
    assert bildstile.anwenden("Apfel", "", "{prompt}", "Text") == ("Apfel", "Text")


def test_die_liste_behaelt_jeden_namen_einmal():
    sauber = bildstile.wahl_pruefen([
        {"name": "Foto", "text": "{prompt}, photo", "negativ": "cartoon"},
        {"name": " Foto ", "text": "doppelt"},
        {"name": "", "text": "ohne Namen"},
        "kein Eintrag",
        {"name": "Anime", "text": 3},
    ])
    assert [{k: v for k, v in style.items() if k != "id"} for style in sauber] == [
        {"name": "Foto", "text": "{prompt}, photo", "negativ": "cartoon"},
        {"name": "Anime", "text": "", "negativ": ""},
    ]
    assert bildstile.wahl_pruefen("keine Liste") is None


def test_every_style_leaves_with_an_id_of_its_own():
    """A style is kept under an id that never changes: its own where it
    brings one, else one grown from its name — the same one whoever writes
    the old list, so two windows cannot hand one style two ids."""
    first = bildstile.wahl_pruefen([{"name": "Foto"}, {"name": "Anime"}])
    again = bildstile.wahl_pruefen([{"name": "Foto"}, {"name": "Anime"}])
    assert [style["id"] for style in first] == [style["id"] for style in again]
    assert len({style["id"] for style in first}) == 2
    assert all(len(style["id"]) == 32 for style in first)
    # Its own id stays, whatever the style is called now.
    renamed = bildstile.wahl_pruefen([{**first[0], "name": "Bild"}, first[1]])
    assert [style["id"] for style in renamed] == [style["id"] for style in first]
    assert renamed[0]["name"] == "Bild"
    # A style without an id never takes the id another style of the list
    # carries — not even standing in front of it, called what that one was
    # called when its id grew.
    in_front = bildstile.wahl_pruefen([{"name": "Foto"}, {**first[0], "name": "Bild"}])
    assert in_front[1]["id"] == first[0]["id"] and in_front[1]["name"] == "Bild"
    assert in_front[0]["id"] != first[0]["id"] and len(in_front[0]["id"]) == 32
    # An id of another shape, or one a style before it carries, is not kept;
    # a new style called what the renamed one was called gets a fresh one.
    odd = bildstile.wahl_pruefen([
        {"id": "not an id", "name": "A"},
        {"id": first[0]["id"], "name": "B"},
        {"id": first[0]["id"], "name": "C"},
        {**first[0], "name": "Bild"},
        {"name": "Foto"},
    ])
    ids = [style["id"] for style in odd]
    assert len(set(ids)) == len(ids) == 5
    assert ids[1] == first[0]["id"] and all(len(i) == 32 for i in ids)


def test_a_renamed_style_stays_the_style_of_every_chat(client: TestClient):
    """Chosen in two chats, then given a new name: both chats still draw
    through it and are told the new name. Kept by its name, the style fell
    out of every chat but the open one."""
    put = client.put("/api/v1/settings/global/bildstile",
                     json={"wert": [{"name": "Foto", "text": "{prompt}, photo", "negativ": ""}]})
    style = put.json()["wert"][0]
    for chat in ("a", "b"):
        assert client.put(f"/api/v1/settings/chat:{chat}/bildfenster",
                          json={"wert": {"stil": style["id"]}}).status_code == 200
    assert client.put("/api/v1/settings/global/bildstile",
                      json={"wert": [{**style, "name": "Lichtbild"}]}).status_code == 200
    styles = client.get("/api/v1/settings/resolved/bildstile").json()["wert"]
    assert [s["id"] for s in styles] == [style["id"]]
    for chat in ("a", "b"):
        chosen = client.get(f"/api/v1/settings/resolved/bildfenster?chat={chat}").json()["wert"]["stil"]
        assert bildstile.name_of(styles, chosen) == "Lichtbild"
    # A chat that chose before styles had ids names its style by the name it
    # had: it finds the style while it is called that, and no longer after.
    assert bildstile.name_of(styles, "Lichtbild") == "Lichtbild"
    assert bildstile.name_of(styles, "Foto") == ""
    # The silence check: no choice, a style that is gone, a list of no use.
    assert bildstile.name_of(styles, "") == ""
    assert bildstile.name_of(styles, "0" * 32) == ""
    assert bildstile.name_of(None, style["id"]) == ""


def test_die_stile_gelten_fuer_alle_chats(client: TestClient):
    stile = [{"name": "Foto", "text": "{prompt}, photo", "negativ": ""}]
    assert client.put("/api/v1/settings/global/bildstile", json={"wert": stile}).status_code == 200
    gelesen = client.get("/api/v1/settings/resolved/bildstile").json()
    assert [{k: v for k, v in style.items() if k != "id"} for style in gelesen["wert"]] == stile


def test_die_wahl_des_stils_gehoert_dem_chat(client: TestClient):
    antwort = client.put("/api/v1/settings/chat:abc/bildfenster", json={"wert": {"stil": "Foto"}})
    assert antwort.status_code == 200
    assert client.get("/api/v1/settings/resolved/bildfenster?chat=abc").json()["wert"]["stil"] == "Foto"
