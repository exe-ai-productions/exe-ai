"""The watchdog: a run a chat sent off that gives no sign of life for 450
seconds ends as failed, with the reason that says so, and its report comes
into the chat.

What counts as a sign (every piece of the model's stream, the start and the
end of a tool) and what never wakes the watchdog (a tool at work, a run that
waits for the user, a run nobody sent off from a chat) is read off real runs
registered in the service, with the clock handed in by the test — nothing
waits 450 real seconds here.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from app import job_watchdog
from app.agenten import agenten_laden
from app.api.v1.auftraege import auftrag_anstossen
from app.providers import MockProvider, Stueck, mock_endpunkt
from app.providers.base import Werkzeugaufruf
from app.tools.mcp_client import MCPWerkzeug
from app.tools.registry import WerkzeugRegistry
from tests.conftest import provider_setzen

ENDED = {"fertig", "abgebrochen", "gescheitert", "unterbrochen"}


class SilentAfterStart(MockProvider):
    """The first request of the service is taken and never answered — the
    second helper of two started together did exactly this. Every later
    request answers, so a woken chat answer after the ending does not hang."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.anfragen = 0

    async def streamen(self, anfrage):
        self.anfragen += 1
        if self.anfragen == 1:
            await asyncio.sleep(3600)
        yield Stueck("content", text="Zusammengefasst.")


class OnePieceThenSilent(MockProvider):
    """One piece, then nothing: the model began and fell silent."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.anfragen = 0

    async def streamen(self, anfrage):
        self.anfragen += 1
        if self.anfragen == 1:
            # Late enough that the piece is told apart from the start of the run.
            await asyncio.sleep(0.4)
            yield Stueck("content", text="Angefangen.")
            await asyncio.sleep(3600)
        yield Stueck("content", text="Zusammengefasst.")


def _agent(config, name: str = "bote"):
    ordner = Path(config.app.agenten_verzeichnis)
    ordner.mkdir(parents=True, exist_ok=True)
    (ordner / f"{name}.md").write_text(
        "---\nmodel: test\nmax_rounds: 3\ntools: []\n---\n\nDo it.\n", encoding="utf-8"
    )
    return agenten_laden(ordner)[name]


def _start(client, config, chat_id, agent=None, **besonderes):
    """A run the way the chat's ``start_job`` makes it."""
    auftrag = auftrag_anstossen(
        config=client.app.state.config,
        repositories=client.app.state.repositories,
        discovery=client.app.state.discovery,
        generierungen=client.app.state.generierungen,
        registry=getattr(client.app.state, "werkzeuge", None),
        agent=agent or _agent(config),
        task="Write the file.",
        endpoint_id=None,
        user_id="standard",
        sprache="en",
        chat_id=chat_id,
        **{"ask_in_chat": chat_id is not None, **besonderes},
    )
    lauf = client.app.state.generierungen.holen(auftrag.generation_id)
    assert lauf is not None
    return auftrag, lauf


async def _until_ended(client, auftrag_id: str, timeout: float = 8.0):
    frist = time.monotonic() + timeout
    while time.monotonic() < frist:
        auftrag = client.app.state.repositories.auftraege.holen(auftrag_id)
        if auftrag is not None and auftrag.zustand in ENDED:
            return auftrag
        await asyncio.sleep(0.05)
    raise AssertionError("the job reached no end state")


async def _cancel_and_wait(client, auftrag, lauf):
    client.app.state.generierungen.abbrechen(lauf.id)
    await _until_ended(client, auftrag.id)


def _check(client, lauf, nach: float):
    return job_watchdog.check(
        client.app.state.repositories,
        client.app.state.generierungen,
        now=lauf.last_sign + nach,
    )


async def test_a_run_silent_past_the_limit_ends_failed_and_the_chat_hears_of_it(
    client, config, chat_id
):
    provider_setzen(client, SilentAfterStart(mock_endpunkt("test")))
    auftrag, lauf = _start(client, config, chat_id)

    assert _check(client, lauf, job_watchdog.SILENCE_LIMIT_SECONDS + 1) == [auftrag.id]

    beendet = await _until_ended(client, auftrag.id)
    assert beendet.zustand == "gescheitert"
    assert beendet.ende_grund == job_watchdog.REASON == "kein_fortschritt"
    # The report reaches the chat like after any ending, and says why.
    frist = time.monotonic() + 5
    meldung = None
    while time.monotonic() < frist and meldung is None:
        meldung = next(
            (
                n for n in client.app.state.repositories.messages.auflisten(chat_id=chat_id)
                if n.art == "werkzeugmeldung"
            ),
            None,
        )
        await asyncio.sleep(0.05)
    assert meldung is not None
    assert "failed" in meldung.content
    assert "made no further progress" in meldung.content


async def test_silence_a_run_that_spoke_a_moment_ago_stays(client, config, chat_id):
    provider_setzen(client, SilentAfterStart(mock_endpunkt("test")))
    auftrag, lauf = _start(client, config, chat_id)

    assert _check(client, lauf, 100) == []
    assert _check(client, lauf, job_watchdog.SILENCE_LIMIT_SECONDS - 1) == []
    assert client.app.state.repositories.auftraege.holen(auftrag.id).zustand == "laeuft"
    await _cancel_and_wait(client, auftrag, lauf)


async def test_a_piece_of_the_stream_is_a_sign_of_life(client, config, chat_id):
    provider = OnePieceThenSilent(mock_endpunkt("test"))
    provider_setzen(client, provider)
    auftrag, lauf = _start(client, config, chat_id)
    beginn = lauf.last_sign
    # The first piece arrives after 0.4 s, then the model is silent.
    await asyncio.sleep(1.0)
    assert provider.anfragen == 1
    assert lauf.last_sign - beginn >= 0.3
    gelesen = lauf.last_sign

    # The silence is counted from that piece, not from the start of the run.
    assert _check(client, lauf, job_watchdog.SILENCE_LIMIT_SECONDS - 1) == []
    assert lauf.last_sign == gelesen
    assert _check(client, lauf, job_watchdog.SILENCE_LIMIT_SECONDS + 1) == [auftrag.id]
    await _until_ended(client, auftrag.id)


async def test_silence_a_tool_at_work_is_not_waited_out(client, config, chat_id):
    provider_setzen(client, SilentAfterStart(mock_endpunkt("test")))
    auftrag, lauf = _start(client, config, chat_id)

    lauf.tool_begins()
    jetzt = lauf.last_sign + 2000
    assert job_watchdog.check(
        client.app.state.repositories, client.app.state.generierungen, now=jetzt
    ) == []
    # The clock was held while the tool ran: counted from now on, not from before.
    assert lauf.last_sign == jetzt
    lauf.tool_ends()
    assert _check(client, lauf, job_watchdog.SILENCE_LIMIT_SECONDS - 1) == []
    assert _check(client, lauf, job_watchdog.SILENCE_LIMIT_SECONDS + 1) == [auftrag.id]
    await _until_ended(client, auftrag.id)


async def test_silence_a_run_that_waits_for_the_user_stays(client, config, chat_id):
    provider_setzen(client, SilentAfterStart(mock_endpunkt("test")))
    auftrag, lauf = _start(client, config, chat_id)
    repositories = client.app.state.repositories

    repositories.auftraege.zustand_setzen(auftrag.id, "wartet")
    jetzt = lauf.last_sign + 5000
    assert job_watchdog.check(
        client.app.state.repositories, client.app.state.generierungen, now=jetzt
    ) == []
    assert repositories.auftraege.holen(auftrag.id).zustand == "wartet"
    assert lauf.last_sign == jetzt

    # Back to running after the answer: the wait is not counted as silence.
    repositories.auftraege.zustand_setzen(auftrag.id, "laeuft")
    assert _check(client, lauf, job_watchdog.SILENCE_LIMIT_SECONDS - 1) == []
    await _cancel_and_wait(client, auftrag, lauf)


async def test_silence_a_call_waiting_for_the_users_yes_stays(client, config, chat_id):
    provider_setzen(client, SilentAfterStart(mock_endpunkt("test")))
    auftrag, lauf = _start(client, config, chat_id)

    lauf.bestaetigung_erwarten("a1", "run_command")
    assert _check(client, lauf, 5000) == []
    lauf.bestaetigung_ablegen("a1")
    await _cancel_and_wait(client, auftrag, lauf)


async def test_silence_a_scheduled_run_and_a_hand_started_run_are_left_alone(
    client, config, chat_id
):
    provider_setzen(client, SilentAfterStart(mock_endpunkt("test")))
    repositories = client.app.state.repositories
    eintrag = repositories.cronjobs.erstellen(
        agent="bote", task="Water the plants", zeitplan="08:00", herkunft="agent"
    )
    _agent(config)
    # One run per kind of run the watchdog is not for, each with a live run
    # behind it that has been silent for far longer than the limit.
    gestartet = []
    for chat, besonderes in ((chat_id, {"cronjob_id": eintrag.id}), (None, {})):
        auftrag, lauf = _start(client, config, chat, **besonderes)
        gestartet.append((auftrag, lauf))

    for auftrag, lauf in gestartet:
        assert _check(client, lauf, 5000) == []
        assert repositories.auftraege.holen(auftrag.id).zustand == "laeuft"
    for auftrag, lauf in gestartet:
        await _cancel_and_wait(client, auftrag, lauf)


async def test_the_limit_is_fixed_at_450_seconds():
    assert job_watchdog.SILENCE_LIMIT_SECONDS == 450.0


# --- The continuation of a run that handed its work on ------------------------


def _handed_on(client, chat_id, agent_name="bote"):
    """A run that handed its work on, and the entry its continuation fires from."""
    repositories = client.app.state.repositories
    head = repositories.auftraege.erstellen(
        user_id="standard", agent=agent_name, auftrag="Write the file.", chat_id=chat_id,
    )
    repositories.auftraege.zustand_setzen(head.id, "unterbrochen", ende_grund="kontext_voll")
    entry = repositories.cronjobs.erstellen(
        agent=agent_name, task="Write the file.", zeitplan="08:00", herkunft="agent",
        basisaufgabe="Write the file.", ursprung_id=head.id,
    )
    return head, entry


async def test_a_continuation_silent_past_the_limit_ends_failed_like_the_first_run(
    client, config, chat_id
):
    provider_setzen(client, SilentAfterStart(mock_endpunkt("test")))
    head, entry = _handed_on(client, chat_id)
    _agent(config)
    job, run = _start(client, config, None, cronjob_id=entry.id)
    # The continuation is the chat's work: it carries the chat of its origin.
    assert job.chat_id == chat_id

    assert _check(client, run, 100) == []
    assert _check(client, run, job_watchdog.SILENCE_LIMIT_SECONDS + 1) == [job.id]

    ended = await _until_ended(client, job.id)
    assert (ended.zustand, ended.ende_grund) == ("gescheitert", "kein_fortschritt")


async def test_silence_a_continuation_of_a_hand_started_run_and_of_a_schedule_is_left_alone(
    client, config, chat_id
):
    provider_setzen(client, SilentAfterStart(mock_endpunkt("test")))
    repositories = client.app.state.repositories
    _agent(config)
    by_hand_head, by_hand_entry = _handed_on(client, None)
    plan = repositories.cronjobs.erstellen(
        agent="bote", task="Water", zeitplan="08:00", herkunft="agent"
    )
    plan_entry = repositories.cronjobs.erstellen(
        agent="bote", task="Water", zeitplan="08:00", herkunft="agent",
        basisaufgabe="Water", ursprung_id=plan.id,
    )
    started = []
    for entry in (by_hand_entry, plan_entry):
        started.append(_start(client, config, None, cronjob_id=entry.id))

    for job, run in started:
        assert _check(client, run, 5000) == []
        assert repositories.auftraege.holen(job.id).zustand == "laeuft"
    for job, run in started:
        await _cancel_and_wait(client, job, run)


# --- A real tool at work ----------------------------------------------------


class SlowTool(WerkzeugRegistry):
    """One tool that works until the test lets it go."""

    def __init__(self) -> None:
        super().__init__([])
        self._werkzeuge = {
            "langsam": (None, MCPWerkzeug(name="langsam", beschreibung="slow"), False),
        }
        self.laeuft = asyncio.Event()
        self.frei = asyncio.Event()

    async def ausfuehren(
        self, name, argumente, bild_senke=None, ordner=None, chat_id=None,
        herkunft="chat", agent=None, shell_zeitgrenze=None, **_rest,
    ):
        self.laeuft.set()
        await self.frei.wait()
        return "fertig"


async def test_a_real_run_counts_its_tool_at_work_and_a_sign_at_its_end(client, config, chat_id):
    registry = SlowTool()
    client.app.state.werkzeuge = registry
    client.app.state.config.features.mcp = True
    client.app.state.discovery.zustaende["test"].endpunkt.capabilities.tool_calls = True
    ordner = Path(config.app.agenten_verzeichnis)
    ordner.mkdir(parents=True, exist_ok=True)
    (ordner / "bote.md").write_text(
        "---\nmodel: test\nmax_rounds: 3\ntools: [langsam]\n---\n\nDo it.\n", encoding="utf-8"
    )
    provider_setzen(
        client,
        MockProvider(
            mock_endpunkt("test"),
            haeppchen=["Erledigt."],
            werkzeugaufrufe=[Werkzeugaufruf(id="t1", name="langsam", argumente={})],
        ),
    )
    auftrag, lauf = _start(client, config, chat_id)

    await asyncio.wait_for(registry.laeuft.wait(), 5)
    assert lauf.tools_running == 1
    jetzt = lauf.last_sign + 5000
    assert job_watchdog.check(
        client.app.state.repositories, client.app.state.generierungen, now=jetzt
    ) == []

    registry.frei.set()
    beendet = await _until_ended(client, auftrag.id)
    assert beendet.zustand == "fertig"
    assert lauf.tools_running == 0
