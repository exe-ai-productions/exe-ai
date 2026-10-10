"""Faults of the schedules, one test each: a broken row does not stop the
pass, and what a person reads comes out of the catalogue in their language (app/cronablauf.py,
app/api/v1/cronjobs.py, app/tools/cronjob.py).
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import textwrap
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from app import cronablauf
from app.i18n import t
from app.providers import MockProvider, mock_endpunkt
from tests.conftest import provider_setzen
from tests.test_auftraege_api import agent_schreiben

MORGEN_13 = datetime.now(timezone.utc).replace(
    hour=13, minute=0, second=0, microsecond=0
) + timedelta(days=1)


def _runs(client, agent: str) -> list[dict]:
    return [a for a in client.get("/api/v1/jobs").json() if a["agent"] == agent]


# --- One unreadable schedule does not stop the pass -------------------------


def _broken_then_healthy(config, client):
    agent_schreiben(config)
    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    repositories = client.app.state.repositories
    broken = repositories.cronjobs.erstellen(
        agent="recherche", task="Broken", zeitplan="12:00", herkunft="chat"
    )
    repositories.cronjobs.verbindung.execute(
        "UPDATE cronjobs SET zeitplan = 'not a schedule' WHERE id = ?", (broken.id,)
    )
    healthy = repositories.cronjobs.erstellen(
        agent="recherche", task="Healthy", zeitplan="12:00", herkunft="chat"
    )
    return broken, healthy


def test_a_healthy_entry_fires_behind_an_unreadable_one(config, client, caplog):
    broken, _ = _broken_then_healthy(config, client)
    cronablauf._unreadable_reported.discard(broken.id)

    asyncio.run(client.app.state.wecker.einmal_pruefen(jetzt=MORGEN_13))

    assert [run["task"] for run in _runs(client, "recherche")] == ["Healthy"]
    assert any("cannot be read" in r.getMessage() for r in caplog.records)
    # Still in the list, where somebody can see it and fix it.
    ids = [row["id"] for row in client.get("/api/v1/cronjobs").json()]
    assert broken.id in ids


def test_the_preload_skips_an_unreadable_entry(config, client):
    _, healthy = _broken_then_healthy(config, client)
    repositories = client.app.state.repositories

    termine = cronablauf._bereitschaftstermine(
        repositories, {"recherche": object()}, MORGEN_13
    )

    assert [cronjob_id for cronjob_id, _ in termine] == [healthy.id]


def test_without_a_broken_row_nothing_changes(config, client, caplog):
    """Silence probe: a healthy entry fires, and nothing is reported."""
    agent_schreiben(config)
    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    client.app.state.repositories.cronjobs.erstellen(
        agent="recherche", task="Healthy", zeitplan="12:00", herkunft="chat"
    )

    asyncio.run(client.app.state.wecker.einmal_pruefen(jetzt=MORGEN_13))

    assert [run["task"] for run in _runs(client, "recherche")] == ["Healthy"]
    assert not any("cannot be read" in r.getMessage() for r in caplog.records)


# --- What a person reads comes from the catalogue ---------------------------


@pytest.mark.parametrize("language", ["de", "en"])
def test_an_unknown_entry_is_answered_in_the_readers_language(client, language):
    headers = {"Accept-Language": language}
    expected = t("fehler.cronjob_not_found", language)
    for answer in (
        client.post("/api/v1/cronjobs/phantom/pause", headers=headers),
        client.post("/api/v1/cronjobs/phantom/resume", headers=headers),
        client.post("/api/v1/cronjobs/phantom/run", headers=headers),
        client.delete("/api/v1/cronjobs/phantom", headers=headers),
    ):
        assert answer.status_code == 404
        assert answer.json()["detail"] == expected


@pytest.mark.parametrize(
    ("body", "key", "values"),
    [
        ({"zeitplan": "08:00", "task": "   "}, "cronjob_refusal.task_empty", {}),
        ({"zeitplan": "whenever", "task": "Los"}, "cronjob_refusal.time_unreadable", {}),
        (
            {"zeitplan": "0 8 * * *", "task": "Los", "einmalig": True, "datum": "2099-01-01"},
            "cronjob_refusal.date_only_daily_time",
            {},
        ),
        (
            {"zeitplan": "08:00", "task": "Los", "einmalig": True, "datum": "2000-01-01"},
            "cronjob_refusal.date_past",
            {},
        ),
        ({"zeitplan": "0 0 30 2 *", "task": "Los"}, "cronjob_refusal.time_never_due", {}),
    ],
)
@pytest.mark.parametrize("language", ["de", "en"])
def test_a_refusal_reaches_the_mask_in_the_readers_language(client, body, key, values, language):
    answer = client.post(
        "/api/v1/cronjobs", json=body, headers={"Accept-Language": language}
    )
    assert answer.status_code == 400, answer.text
    assert answer.json()["detail"] == t(key, language, **values)


def test_an_unknown_agent_names_the_available_ones(config, client):
    agent_schreiben(config)
    answer = client.post(
        "/api/v1/cronjobs",
        json={"zeitplan": "08:00", "task": "Los", "agent": "nobody"},
        headers={"Accept-Language": "de"},
    )
    assert answer.status_code == 400
    assert answer.json()["detail"].startswith("Agent „nobody“ nicht gefunden.")
    assert "recherche" in answer.json()["detail"]


def test_the_model_still_reads_english(client):
    """The tool's own answer stays English prose for the model."""
    from app.tools import cronjob

    with pytest.raises(cronjob.CronjobVerboten) as refusal:
        asyncio.run(
            cronjob.ausfuehren(
                {"action": "create", "time": "08:00", "task": "  "},
                client.app.state.repositories.cronjobs,
                client.app.state.config.agentenverzeichnisse,
                herkunft="chat",
            )
        )
    assert str(refusal.value) == "'task' is empty — nothing to run."
    assert refusal.value.schluessel == "cronjob_refusal.task_empty"


def test_the_service_writes_in_the_language_the_interface_chose(client):
    """A stored choice wins; on "auto" the configured language speaks."""
    from app import sprachwahl

    repositories = client.app.state.repositories
    assert sprachwahl.interface_language(repositories, "en") == "en"
    repositories.einstellungen.setzen("global", "sprache", {"sprache": "de"})
    assert sprachwahl.interface_language(repositories, "en") == "de"
    repositories.einstellungen.setzen("global", "sprache", {"sprache": "auto"})
    assert sprachwahl.interface_language(repositories, "en") == "en"


# --- The window reads the schedules on the service's clock ------------------


def test_meta_names_the_configured_zone(client):
    client.app.state.config.app.timezone = "Asia/Tokyo"
    assert client.get("/api/v1/meta").json()["timezone"] == "Asia/Tokyo"


def test_meta_names_the_machines_zone_when_none_is_set(client, monkeypatch):
    """With no zone set the service reads the machine's clock, and the
    window is told which one — a browser elsewhere would read its own."""
    monkeypatch.setenv("TZ", "America/Chicago")
    client.app.state.config.app.timezone = None
    assert client.get("/api/v1/meta").json()["timezone"] == "America/Chicago"


def test_the_history_stands_newest_first(client):
    """The one route the window reads the runs from lists the newest first."""
    repositories = client.app.state.repositories
    entry = repositories.cronjobs.erstellen(
        agent="recherche", task="Los", zeitplan="08:00", herkunft="chat"
    )
    for task in ("First", "Then"):
        run = repositories.auftraege.erstellen(
            user_id="standard", agent="recherche", auftrag=task, cronjob_id=entry.id
        )
        repositories.auftraege.zustand_setzen(run.id, "fertig")

    runs = client.get("/api/v1/cronjobs/runs/all").json()
    assert [r["task"] for r in runs if r["cronjob_id"] == entry.id] == ["Then", "First"]


FRONTEND = Path(__file__).resolve().parent.parent / "frontend"


@pytest.mark.skipif(
    shutil.which("node") is None or not (FRONTEND / "node_modules").is_dir(),
    reason="no Node or no frontend dependencies on this machine",
)
def _node_environment(browser_zone: str) -> dict[str, str]:
    """The environment node runs in, with the browser's zone as its clock.
    A POSIX system gets nothing of this process's own environment besides
    a plain PATH; Windows needs the system's variables (``SystemRoot``
    above all — without it node dies before the script runs, measured),
    so there the zone is laid over the environment as it is."""
    if sys.platform == "win32":
        return {**os.environ, "TZ": browser_zone}
    return {"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin", "TZ": browser_zone}


@pytest.mark.parametrize(
    ("browser_zone", "config_zone"),
    [("UTC", "Asia/Tokyo"), ("Asia/Tokyo", "Asia/Tokyo"), ("Asia/Tokyo", "")],
)
def test_a_next_run_is_named_on_the_services_clock(browser_zone, config_zone):
    """A daily 08:00 in Tokyo, next due at 08:00 Tokyo time: the card names
    08:00, whether or not the browser's clock is Tokyo's. The last two cases
    are the silence probe: the same zones, and no zone at all, read as
    before. (The day line reads the service's calendar, which is already on
    that clock.)"""
    folder = FRONTEND / "node_modules" / f".check-zone-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        for name in ("zeitpunkt.js", "clock.js"):
            (folder / name).write_text(
                (FRONTEND / "src" / "lib" / name).read_text(encoding="utf-8"), encoding="utf-8"
            )
        (folder / "texte.svelte.js").write_text(
            "export const texte = { sprache: 'de' }\n", encoding="utf-8"
        )
        (folder / "check.mjs").write_text(
            textwrap.dedent(
                f"""
                import {{ zeitpunkt }} from './zeitpunkt.js'
                import {{ dayIn }} from './clock.js'
                const next = '2026-09-28T08:00:00+09:00'
                console.log(JSON.stringify({{
                  shown: zeitpunkt(next, '{config_zone}'),
                  day: dayIn(new Date('2026-09-27T23:30:00Z'), '{config_zone}'),
                }}))
                """
            ),
            encoding="utf-8",
        )
        run = subprocess.run(
            ["node", "check.mjs"], cwd=folder, capture_output=True, text=True,
            timeout=60, env=_node_environment(browser_zone),
        )
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    assert run.returncode == 0, run.stderr
    result = json.loads(run.stdout)
    # 23:30 UTC on the 27th is already the 28th in Tokyo.
    assert result == {"shown": "28.09. 08:00", "day": "2026-09-28"}
