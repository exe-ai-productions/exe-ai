"""Creating an entry from the mask, through the tool's own door.

Until now an entry could only come into being in a chat, because the model
turns "every two hours" into an expression. Whoever did not want to open a
chat could not get a schedule at all — and the panel that shows them is the
only place to switch one off again.

What matters as much as the creating: the route is NOT a second way in. Every
rule the tool states has to hold here too, or the mask would be a door beside
all of them.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def agentdatei(ordner: Path, name: str, kopf: str = "model: test") -> None:
    ordner.mkdir(parents=True, exist_ok=True)
    (ordner / f"{name}.md").write_text(f"---\n{kopf}\n---\n\nPrompt.\n", encoding="utf-8")


def test_die_maske_legt_einen_termin_an(client):
    antwort = client.post(
        "/api/v1/cronjobs",
        json={"zeitplan": "08:00", "task": "Kaffee kochen"},
    )
    assert antwort.status_code == 201, antwort.text
    zeile = antwort.json()
    assert zeile["task"] == "Kaffee kochen"
    assert zeile["zeitplan"] == "08:00"
    # From the mask, so from a person — the same origin a chat call carries.
    assert zeile["herkunft"] == "chat"
    # And it is really in the table the panel reads.
    alle = client.get("/api/v1/cronjobs").json()
    assert [e["id"] for e in alle] == [zeile["id"]]


def test_ein_leerer_zeitplan_kommt_nicht_durch(client):
    antwort = client.post("/api/v1/cronjobs", json={"zeitplan": "", "task": "x"})
    assert antwort.status_code == 422


def test_die_absage_des_werkzeugs_kommt_woertlich_durch(client):
    """The tool's sentence names what is wrong and often what would be right.
    Rewording it here would cost exactly that."""
    antwort = client.post(
        "/api/v1/cronjobs", json={"zeitplan": "kein zeitplan", "task": "x"}
    )
    assert antwort.status_code == 400
    assert antwort.json()["detail"].strip()


def test_ein_unbekannter_agent_wird_abgelehnt_und_nennt_die_echten(client, tmp_path):
    """The same refusal the tool gives, with the available names in it — in
    the reader's language."""
    antwort = client.post(
        "/api/v1/cronjobs",
        json={"zeitplan": "08:00", "task": "x", "agent": "gibt-es-nicht"},
        headers={"Accept-Language": "en"},
    )
    assert antwort.status_code == 400
    assert "Available" in antwort.json()["detail"]


def test_eine_leere_aufgabe_wird_abgelehnt(client):
    """An agent entry with nothing to do is nothing to run — the tool says so
    and the route must not slip past it."""
    antwort = client.post("/api/v1/cronjobs", json={"zeitplan": "08:00", "task": "   "})
    assert antwort.status_code == 400


def test_unsichtbare_zeichen_werden_geputzt(client):
    """The scrub on the task text is the tool's first security point, and it
    has to hold for the mask exactly as for a chat."""
    antwort = client.post(
        "/api/v1/cronjobs",
        json={"zeitplan": "08:00", "task": "Kaffee​ kochen"},
    )
    assert antwort.status_code == 201, antwort.text
    assert "​" not in antwort.json()["task"]
