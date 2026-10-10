"""The embedding server's own start line."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_die_auskunft_traegt_den_belegten_speicher(client: TestClient, monkeypatch):
    """The machine head's sum needs this server's share while it runs — the
    runner already measures it for itself."""
    runner = client.app.state.einbettungsrunner
    monkeypatch.setattr(runner, "laeuft", lambda: True)
    monkeypatch.setattr(runner, "belegt_gb", lambda: 0.6)
    daten = client.get("/api/v1/einbettungsserver").json()
    assert daten["belegt_gb"] == 0.6


def test_ein_stehender_server_meldet_keinen_speicher(client: TestClient):
    """Schweigeprobe: nothing running, nothing to add."""
    daten = client.get("/api/v1/einbettungsserver").json()
    assert daten["belegt_gb"] is None


def test_das_fenster_steht_nur_einmal_in_der_zeile():
    """The runner writes `--ctx-size` itself. A second one from the flag list
    made a command line that carried it twice — it worked by accident, because
    llama.cpp takes the last one.

    Same guard as the Extended-Workflow server's, and for the same reason:
    what a command line says has to be what somebody meant to say.
    """
    from pathlib import Path

    from app import einbettungsserver

    assert "--ctx-size" not in einbettungsserver.FLAGS
    runner = einbettungsserver.runner_bauen(Path("/tmp"), "llama-server", 8081)
    zeile = " ".join(runner.befehl("m.gguf", einbettungsserver.STAPEL, 99, 8081))
    assert zeile.count("--ctx-size") == 1
    assert f"--ctx-size {einbettungsserver.STAPEL}" in zeile
