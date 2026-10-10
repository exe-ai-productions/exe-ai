"""The Hugging Face token: set once, never handed back out."""

from __future__ import annotations

import os

import pytest

from app import paketierung


@pytest.fixture
def eigener_ordner(tmp_path, monkeypatch):
    monkeypatch.setattr(paketierung, "daten", lambda: tmp_path)
    monkeypatch.setenv("HF_TOKEN", "")
    return tmp_path


def test_ohne_token_sagt_der_stand_nein(client, eigener_ordner):
    assert client.get("/api/v1/models/token").json() == {"gesetzt": False, "ende": None}


def test_ein_token_landet_in_env_und_umgebung(client, eigener_ordner):
    antwort = client.post("/api/v1/models/token", json={"token": "hf_beispiel_1234"})
    assert antwort.status_code == 200
    assert antwort.json() == {"gesetzt": True, "ende": "1234"}
    assert os.environ["HF_TOKEN"] == "hf_beispiel_1234"
    assert "HF_TOKEN=hf_beispiel_1234" in (eigener_ordner / ".env").read_text()
    # And the window never gets it back — only that one is there and how
    # it ends.
    assert client.get("/api/v1/models/token").json() == {"gesetzt": True, "ende": "1234"}


def test_ein_token_laesst_sich_entfernen(client, eigener_ordner):
    (eigener_ordner / ".env").write_text("# mine\nOTHER=1\n", encoding="utf-8")
    client.post("/api/v1/models/token", json={"token": "hf_beispiel_1234"})
    antwort = client.delete("/api/v1/models/token")
    assert antwort.status_code == 200
    assert antwort.json() == {"gesetzt": False, "ende": None}
    assert "HF_TOKEN" not in os.environ
    inhalt = (eigener_ordner / ".env").read_text()
    assert "HF_TOKEN" not in inhalt
    # The user's own lines stay.
    assert "# mine" in inhalt and "OTHER=1" in inhalt
    assert client.get("/api/v1/models/token").json() == {"gesetzt": False, "ende": None}


def test_ein_zu_kurzes_token_wird_abgelehnt(client, eigener_ordner):
    assert client.post("/api/v1/models/token", json={"token": "kurz"}).status_code == 422
