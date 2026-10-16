"""The clean-up server's port and the embedding server's file and port are
stored, and the next start uses them.

Both windows held them in the page: after stopping and reopening, or after a
restart, they stood on 8085 / 8081 and the first file of the folder again.
The clean-up port joins the dictation row beside its memory numbers
(`cleanup_port`); the embedding server has a row of its own, `embedding`,
with `model` and `port`.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

DIKTAT = "/api/v1/settings/global/diktat"
EMBEDDING = "/api/v1/settings/global/embedding"
EMBEDDING_RESOLVED = "/api/v1/settings/resolved/embedding"
DIKTAT_RESOLVED = "/api/v1/settings/resolved/diktat"


def _fresh_client(config) -> TestClient:
    from app.main import app_erstellen

    app = app_erstellen(config)
    client = TestClient(app)
    client.__enter__()
    client.headers["X-Sitzungsschluessel"] = app.state.sitzungsschluessel
    return client


def test_the_cleanup_port_is_stored_and_read_from_a_fresh_start(client: TestClient, config):
    assert client.patch(DIKTAT, json={"wert": {"cleanup_port": 8195}}).status_code == 200
    again = _fresh_client(config)
    try:
        assert again.get(DIKTAT_RESOLVED).json()["wert"]["cleanup_port"] == 8195
    finally:
        again.__exit__(None, None, None)


def test_the_cleanup_start_carries_the_stored_port(client: TestClient, monkeypatch):
    client.patch(DIKTAT, json={"wert": {"cleanup_port": 8195}})
    seen: dict = {}
    monkeypatch.setattr(
        client.app.state.sprachputzrunner, "starten", lambda modell, **kw: seen.update(kw)
    )
    client.post("/api/v1/bereinigungsserver/start", json={"modell": "m.gguf"})
    assert seen["port"] == 8195
    # The request's own port still wins.
    client.post("/api/v1/bereinigungsserver/start", json={"modell": "m.gguf", "port": 8300})
    assert seen["port"] == 8300


def test_the_idle_cleanup_answer_shows_the_stored_port(client: TestClient):
    client.patch(DIKTAT, json={"wert": {"cleanup_port": 8195}})
    assert client.get("/api/v1/bereinigungsserver").json()["port"] == 8195


def test_the_embedding_choice_is_stored_in_a_row_of_its_own(client: TestClient, config):
    answer = client.patch(EMBEDDING, json={"wert": {"model": "embed.gguf", "port": 8188}})
    assert answer.status_code == 200, answer.text
    again = _fresh_client(config)
    try:
        stored = again.get(EMBEDDING_RESOLVED).json()["wert"]
        assert stored == {"model": "embed.gguf", "port": 8188}
    finally:
        again.__exit__(None, None, None)


def test_the_embedding_start_carries_the_stored_port(client: TestClient, monkeypatch):
    client.patch(EMBEDDING, json={"wert": {"model": "embed.gguf", "port": 8188}})
    seen: dict = {}
    monkeypatch.setattr(
        client.app.state.einbettungsrunner, "starten", lambda modell, **kw: seen.update(kw)
    )
    client.post("/api/v1/einbettungsserver/start", json={"modell": "embed.gguf"})
    assert seen["port"] == 8188


def test_with_nothing_stored_both_starts_go_by_the_servers_own_port(client: TestClient, monkeypatch):
    """The silence check: no stored value, no change."""
    seen: dict = {}
    monkeypatch.setattr(
        client.app.state.einbettungsrunner, "starten", lambda modell, **kw: seen.update(kw)
    )
    monkeypatch.setattr(
        client.app.state.sprachputzrunner, "starten", lambda modell, **kw: seen.update(putz=kw)
    )
    client.post("/api/v1/einbettungsserver/start", json={"modell": "e.gguf"})
    client.post("/api/v1/bereinigungsserver/start", json={"modell": "m.gguf"})
    assert seen["port"] is None
    assert seen["putz"]["port"] is None


def test_an_embedding_port_outside_the_range_is_not_stored(client: TestClient):
    client.patch(EMBEDDING, json={"wert": {"model": "e.gguf", "port": 80}})
    stored = client.get(EMBEDDING_RESOLVED).json()["wert"]
    assert stored == {"model": "e.gguf"}


def test_the_idle_embedding_answer_shows_the_stored_file_and_port(client: TestClient):
    """What the window opens on after a restart: the stored file while it is
    still in the folder, and the stored port."""
    from pathlib import Path

    folder = Path(client.get("/api/v1/einbettungsserver").json()["ordner"])
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "embed.gguf").write_bytes(b"GGUF")
    client.patch(EMBEDDING, json={"wert": {"model": "embed.gguf", "port": 8188}})
    answer = client.get("/api/v1/einbettungsserver").json()
    assert answer["modell"] == "embed.gguf"
    assert answer["port"] == 8188


def test_a_stored_file_that_has_left_the_folder_is_not_shown(client: TestClient):
    client.patch(EMBEDDING, json={"wert": {"model": "gone.gguf", "port": 8188}})
    answer = client.get("/api/v1/einbettungsserver").json()
    assert answer["modell"] is None
