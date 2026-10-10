"""G2: an unknown field on the picture wish is a caller that built the
request wrong, not an optional extra to quietly ignore — see BildWunsch's
own model_config."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_unbekanntes_feld_wird_abgelehnt(client: TestClient):
    antwort = client.post(
        "/api/v1/bild",
        json={"modell": "x.safetensors", "prompt": "x", "erfunden": True},
    )
    assert antwort.status_code == 422
