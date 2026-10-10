"""Adding a cloud provider from the window, end to end.

The window's whole promise is "key in, models appear". What the endpoint
must leave behind is checked here: the entry in config.yaml, the key in
.env and in the running environment, and — without any restart — the
candidate in discovery. The last one is the difference between a window
and a dead end.
"""

from __future__ import annotations

import os

import pytest
import yaml

from app import paketierung


@pytest.fixture
def eigener_ordner(tmp_path, monkeypatch):
    """Redirects the user folder, so no test writes the project's own
    config.yaml or .env."""
    monkeypatch.setattr(paketierung, "daten", lambda: tmp_path)
    (tmp_path / "config.yaml").write_text("endpoints: []\n", encoding="utf-8")
    # Whatever the endpoint puts into the environment is rolled back by
    # monkeypatch, because the name is registered here first.
    monkeypatch.setenv("EIGENE_API_KEY", "vorher")
    return tmp_path


def test_ein_anbieter_erscheint_ohne_neustart(client, eigener_ordner):
    antwort = client.post(
        "/api/v1/providers",
        json={
            "art": "eigen",
            "kennung": "eigene",
            "url": "http://127.0.0.1:9/v1",
            "schluessel": "sk-test-1234",
        },
    )
    assert antwort.status_code == 200
    # Nothing listens on this port, so the one-time reachability check that
    # `anmelden()` runs right away comes back negative.
    assert antwort.json() == {
        "id": "eigene",
        "api_key_env": "EIGENE_API_KEY",
        "erreichbar": False,
    }

    # The candidate is there while the window is still open.
    zustand = client.app.state.discovery.zustaende.get("eigene")
    assert zustand is not None
    assert zustand.endpunkt.group == "cloud"

    # The running service can use the key at once; the file serves the next
    # start.
    assert os.environ["EIGENE_API_KEY"] == "sk-test-1234"
    assert "EIGENE_API_KEY=sk-test-1234" in (eigener_ordner / ".env").read_text()

    gespeichert = yaml.safe_load((eigener_ordner / "config.yaml").read_text())
    assert gespeichert["endpoints"][0]["id"] == "eigene"


def test_dieselbe_kennung_gibt_es_nur_einmal(client, eigener_ordner):
    daten = {
        "art": "eigen",
        "kennung": "doppelt",
        "url": "http://127.0.0.1:9/v1",
        "schluessel": "sk-test-1234",
    }
    assert client.post("/api/v1/providers", json=daten).status_code == 200
    assert client.post("/api/v1/providers", json=daten).status_code == 409


def test_ein_bekannter_anbieter_braucht_keine_adresse(client, eigener_ordner, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "vorher")
    antwort = client.post(
        "/api/v1/providers",
        json={"art": "anthropic", "schluessel": "sk-ant-test-1234"},
    )
    assert antwort.status_code == 200
    zustand = client.app.state.discovery.zustaende.get("anthropic")
    assert zustand is not None
    assert zustand.endpunkt.base_url == "https://api.anthropic.com/v1"


# --- Hand-set capabilities ---------------------------------------------------


def test_vision_laesst_sich_von_hand_setzen(client, eigener_ordner):
    """Cloud model lists say nothing about modalities — whoever knows their
    model sees images must be able to say so, and the word must hold."""
    client.post(
        "/api/v1/providers",
        json={
            "art": "eigen",
            "kennung": "eigene",
            "url": "http://127.0.0.1:9/v1",
            "schluessel": "sk-test-1234",
        },
    )
    zustand = client.app.state.discovery.zustaende["eigene"]
    assert zustand.kann("vision") is False

    antwort = client.put(
        "/api/v1/providers/eigene/capabilities", json={"vision": True}
    )
    assert antwort.status_code == 200
    assert antwort.json()["capabilities"]["vision"] is True
    # The running service answers with the new word at once …
    assert zustand.kann("vision") is True
    # … and the file carries it to the next start.
    gespeichert = yaml.safe_load((eigener_ordner / "config.yaml").read_text())
    eintrag = next(e for e in gespeichert["endpoints"] if e["id"] == "eigene")
    assert eintrag["capabilities"]["vision"] is True


def test_vision_wort_laesst_sich_zuruecknehmen(client, eigener_ordner):
    client.post(
        "/api/v1/providers",
        json={
            "art": "eigen",
            "kennung": "eigene",
            "url": "http://127.0.0.1:9/v1",
            "schluessel": "sk-test-1234",
        },
    )
    client.put("/api/v1/providers/eigene/capabilities", json={"vision": True})
    antwort = client.put(
        "/api/v1/providers/eigene/capabilities", json={"vision": None}
    )
    assert antwort.status_code == 200
    gespeichert = yaml.safe_load((eigener_ordner / "config.yaml").read_text())
    eintrag = next(e for e in gespeichert["endpoints"] if e["id"] == "eigene")
    assert "vision" not in (eintrag.get("capabilities") or {})
    assert client.app.state.discovery.zustaende["eigene"].kann("vision") is False


def test_faehigkeit_nur_genannte_felder(client, eigener_ordner):
    """A request naming only vision must not wipe an explicit tool_calls."""
    client.post(
        "/api/v1/providers",
        json={"art": "anthropic", "schluessel": "sk-test-1234"},
    )
    client.put("/api/v1/providers/anthropic/capabilities", json={"vision": False})
    gespeichert = yaml.safe_load((eigener_ordner / "config.yaml").read_text())
    eintrag = next(e for e in gespeichert["endpoints"] if e["id"] == "anthropic")
    assert eintrag["capabilities"] == {"tool_calls": True, "vision": False}


def test_denken_laesst_sich_von_hand_setzen(client, eigener_ordner):
    """An unknown host is offered the plain OpenAI field's stages; the
    switch in the window says otherwise either way, and the hand wins."""
    client.post(
        "/api/v1/providers",
        json={
            "art": "eigen",
            "kennung": "eigene",
            "url": "http://127.0.0.1:9/v1",
            "schluessel": "sk-test-1234",
        },
    )
    zustand = client.app.state.discovery.zustaende["eigene"]
    assert zustand.kann("thinking") is True

    antwort = client.put(
        "/api/v1/providers/eigene/capabilities", json={"thinking": False}
    )
    assert antwort.status_code == 200
    assert zustand.kann("thinking") is False

    antwort = client.put(
        "/api/v1/providers/eigene/capabilities", json={"thinking": True}
    )
    assert antwort.status_code == 200
    assert antwort.json()["capabilities"]["thinking"] is True
    assert zustand.kann("thinking") is True

    gespeichert = yaml.safe_load((eigener_ordner / "config.yaml").read_text())
    eintrag = next(e for e in gespeichert["endpoints"] if e["id"] == "eigene")
    assert eintrag["capabilities"]["thinking"] is True


def test_werkzeuge_lassen_sich_von_hand_setzen(client, eigener_ordner):
    """A new custom provider takes tool calls from the start, like the
    presets: a cloud entry has no /props to sniff, and without tools a model
    that could call one writes its call into the chat as text. A hand-set
    "no" stays."""
    client.post(
        "/api/v1/providers",
        json={
            "art": "eigen",
            "kennung": "eigene",
            "url": "http://127.0.0.1:9/v1",
            "schluessel": "sk-test-1234",
        },
    )
    zustand = client.app.state.discovery.zustaende["eigene"]
    assert zustand.kann("tool_calls") is True

    client.put("/api/v1/providers/eigene/capabilities", json={"tool_calls": False})
    assert zustand.kann("tool_calls") is False
    gespeichert = yaml.safe_load((eigener_ordner / "config.yaml").read_text())
    eintrag = next(e for e in gespeichert["endpoints"] if e["id"] == "eigene")
    assert eintrag["capabilities"]["tool_calls"] is False

    antwort = client.put(
        "/api/v1/providers/eigene/capabilities", json={"tool_calls": True}
    )
    assert antwort.status_code == 200
    assert antwort.json()["capabilities"]["tool_calls"] is True
    assert zustand.kann("tool_calls") is True

    gespeichert = yaml.safe_load((eigener_ordner / "config.yaml").read_text())
    eintrag = next(e for e in gespeichert["endpoints"] if e["id"] == "eigene")
    assert eintrag["capabilities"]["tool_calls"] is True


def test_faehigkeit_unbekannter_endpunkt_gibt_404(client, eigener_ordner):
    assert (
        client.put(
            "/api/v1/providers/phantom/capabilities", json={"vision": True}
        ).status_code
        == 404
    )


# --- The "Zeitgrenze" switch -------------------------------------------------


def test_zeitgrenze_laesst_sich_von_hand_ausschalten(client, eigener_ordner):
    """A server this window's user trusts to eventually answer switches the
    600 s cutoff off — the word must hold in the running service AND the
    file, the same as the three capability switches above."""
    client.post(
        "/api/v1/providers",
        json={
            "art": "eigen",
            "kennung": "eigene",
            "url": "http://127.0.0.1:9/v1",
            "schluessel": "sk-test-1234",
        },
    )
    zustand = client.app.state.discovery.zustaende["eigene"]
    assert zustand.endpunkt.timeout_enabled is True

    antwort = client.put(
        "/api/v1/providers/eigene/timeout", json={"timeout_enabled": False}
    )
    assert antwort.status_code == 200
    assert antwort.json()["timeout_enabled"] is False
    assert zustand.endpunkt.timeout_enabled is False

    gespeichert = yaml.safe_load((eigener_ordner / "config.yaml").read_text())
    eintrag = next(e for e in gespeichert["endpoints"] if e["id"] == "eigene")
    assert eintrag["timeout_enabled"] is False


def test_zeitgrenze_zurueck_auf_an_raeumt_das_feld_wieder_weg(client, eigener_ordner):
    """Schweigeprobe: switched back on, the file carries no line at all —
    on is what an absent entry has always meant."""
    client.post(
        "/api/v1/providers",
        json={
            "art": "eigen",
            "kennung": "eigene",
            "url": "http://127.0.0.1:9/v1",
            "schluessel": "sk-test-1234",
        },
    )
    client.put("/api/v1/providers/eigene/timeout", json={"timeout_enabled": False})
    client.put("/api/v1/providers/eigene/timeout", json={"timeout_enabled": True})

    zustand = client.app.state.discovery.zustaende["eigene"]
    assert zustand.endpunkt.timeout_enabled is True
    gespeichert = yaml.safe_load((eigener_ordner / "config.yaml").read_text())
    eintrag = next(e for e in gespeichert["endpoints"] if e["id"] == "eigene")
    assert "timeout_enabled" not in eintrag


def test_zeitgrenze_unbekannter_endpunkt_gibt_404(client, eigener_ordner):
    assert (
        client.put(
            "/api/v1/providers/phantom/timeout", json={"timeout_enabled": False}
        ).status_code
        == 404
    )


# --- Removing a provider ------------------------------------------------------


def test_ein_anbieter_laesst_sich_entfernen(client, eigener_ordner):
    """The counterpart of adding one: gone from the file, gone from
    discovery, gone from the running config — but the key stays in .env."""
    client.post(
        "/api/v1/providers",
        json={
            "art": "eigen",
            "kennung": "eigene",
            "url": "http://127.0.0.1:9/v1",
            "schluessel": "sk-test-1234",
        },
    )
    assert os.environ["EIGENE_API_KEY"] == "sk-test-1234"

    antwort = client.delete("/api/v1/providers/eigene")
    assert antwort.status_code == 204

    gespeichert = yaml.safe_load((eigener_ordner / "config.yaml").read_text())
    assert all(e["id"] != "eigene" for e in gespeichert["endpoints"])
    assert client.app.state.discovery.zustaende.get("eigene") is None
    assert not any(e.id == "eigene" for e in client.app.state.config.endpoints)
    # The key was never the route's to remove — only the entry.
    assert os.environ["EIGENE_API_KEY"] == "sk-test-1234"
    assert "EIGENE_API_KEY=sk-test-1234" in (eigener_ordner / ".env").read_text()


def test_entfernter_anbieter_laesst_sich_erneut_anlegen(client, eigener_ordner):
    """The case from the field: a dead entry blocked every future add under
    the same name — removing it has to open that name up again."""
    daten = {
        "art": "eigen",
        "kennung": "eigene",
        "url": "http://127.0.0.1:9/v1",
        "schluessel": "sk-test-1234",
    }
    client.post("/api/v1/providers", json=daten)
    client.delete("/api/v1/providers/eigene")

    antwort = client.post("/api/v1/providers", json=daten)
    assert antwort.status_code == 200
    gespeichert = yaml.safe_load((eigener_ordner / "config.yaml").read_text())
    assert sum(1 for e in gespeichert["endpoints"] if e["id"] == "eigene") == 1


def test_andere_anbieter_bleiben_beim_entfernen_unberuehrt(client, eigener_ordner):
    client.post(
        "/api/v1/providers",
        json={
            "art": "eigen",
            "kennung": "eins",
            "url": "http://127.0.0.1:9/v1",
            "schluessel": "sk-test-1111",
        },
    )
    client.post(
        "/api/v1/providers",
        json={
            "art": "eigen",
            "kennung": "zwei",
            "url": "http://127.0.0.1:9/v1",
            "schluessel": "sk-test-2222",
        },
    )

    client.delete("/api/v1/providers/eins")

    gespeichert = yaml.safe_load((eigener_ordner / "config.yaml").read_text())
    assert [e["id"] for e in gespeichert["endpoints"]] == ["zwei"]
    zustand = client.app.state.discovery.zustaende.get("zwei")
    assert zustand is not None
    assert zustand.endpunkt.base_url == "http://127.0.0.1:9/v1"


def test_anbieter_loeschen_unbekannt_gibt_404(client, eigener_ordner):
    assert client.delete("/api/v1/providers/phantom").status_code == 404
