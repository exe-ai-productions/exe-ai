"""The approval of a model for runs: "use for agents".

What this has to get right is where the approval counts and where it does
not. It counts where the program looks for a place by itself — a schedule
with nothing chosen, an agent started with no pick — and there it takes out
a local server whose switch is off and lets an approved cloud model in as
the last resort. It does not count where somebody chose: a hand pick, or the
field naming a server or a file, runs whatever the switch says.
"""

from __future__ import annotations

import pytest

from app import agentenmodellwahl as wahl
from app import agentenserver, modellwahl, runnermodellwahl
from app.api.v1.einstellungen import MODEL_SWITCH_KEYS, PRUEFER
from app.db.repositories.einstellungen import GLOBAL
from app.providers.mock import MockProvider, mock_endpunkt

SLOT = agentenserver.ENDPUNKT_ID
HAUPT = wahl.HAUPTMODELL


def _empty_field(client) -> None:
    client.app.state.repositories.einstellungen.setzen(
        GLOBAL, wahl.SCHLUESSEL, {"sorte": "", "wert": ""}
    )


async def _local_server(client, id: str, *, answers: bool = True, tools: bool = True):
    """A local server of ours as the discovery holds it."""
    discovery = client.app.state.discovery
    await discovery.anmelden(mock_endpunkt(id, group="local"))
    state = discovery.zustaende[id]
    state.provider = MockProvider(mock_endpunkt(id, group="local"), ist_erreichbar=answers)
    state.erreichbar = answers
    # A silence is only tolerated for what has answered before: this one never did.
    state.je_geantwortet = answers
    state.endpunkt.capabilities.tool_calls = tools


async def _provider(
    client, id: str, models: list[str], *, tools: bool = True, answers: bool = True
):
    """A cloud provider with a catalogue."""
    discovery = client.app.state.discovery
    await discovery.anmelden(mock_endpunkt(id))
    state = discovery.zustaende[id]
    state.provider = MockProvider(mock_endpunkt(id), modelle=models, ist_erreichbar=answers)
    state.modelle = list(models)
    state.erreichbar = answers
    state.je_geantwortet = answers
    state.endpunkt.capabilities.tool_calls = tools


def _approve(client, *ids: str, picked: bool = True) -> None:
    """The approval of these models — and, as the window does it, their pick
    out of the catalogue (the approval is shown on picked models only)."""
    einstellungen = client.app.state.repositories.einstellungen
    einstellungen.setzen(GLOBAL, modellwahl.KEY_RUNS, list(ids))
    picks: dict[str, list[str]] = {}
    for kennung in ids:
        provider, _, model = kennung.partition(":")
        if picked and model:
            picks.setdefault(provider, []).append(model)
    einstellungen.setzen(GLOBAL, modellwahl.SCHLUESSEL_WAHL, picks)


def _switch(client, *, main: bool | None = None, agent: bool | None = None) -> None:
    einstellungen = client.app.state.repositories.einstellungen
    if main is not None:
        einstellungen.zusammenlegen(GLOBAL, runnermodellwahl.SCHLUESSEL, {"use_for_runs": main})
    if agent is not None:
        einstellungen.zusammenlegen(GLOBAL, wahl.SCHLUESSEL, {"use_for_runs": agent})


def _run(client, *, tools: bool = False, **fields):
    return wahl.lauf_kennung(
        client.app.state.repositories,
        client.app.state.discovery,
        slot_id=SLOT,
        werkzeuge=tools,
        **fields,
    )


# --- What is stored ---------------------------------------------------------


def test_both_local_servers_are_approved_as_shipped(repos):
    assert runnermodellwahl.use_for_runs(repos) is True
    assert wahl.use_for_runs(repos) is True
    assert runnermodellwahl.VORGABE["use_for_runs"] is True
    assert wahl.VORGABE["use_for_runs"] is True


def test_the_switch_is_checked_to_a_plain_boolean():
    for modul in (runnermodellwahl, wahl):
        assert modul.wahl_pruefen({"use_for_runs": 0})["use_for_runs"] is False
        assert modul.wahl_pruefen({"use_for_runs": "ja"})["use_for_runs"] is True
        assert "use_for_runs" not in modul.wahl_pruefen({"kontext": 4096})


def test_a_stored_no_stands(repos):
    repos.einstellungen.zusammenlegen(GLOBAL, runnermodellwahl.SCHLUESSEL, {"use_for_runs": False})
    repos.einstellungen.zusammenlegen(GLOBAL, wahl.SCHLUESSEL, {"use_for_runs": False})
    assert runnermodellwahl.use_for_runs(repos) is False
    assert wahl.use_for_runs(repos) is False


def test_the_approved_cloud_models_have_a_checker_and_announce_their_writes():
    """Without the entry the settings route answers 400 and the tick never
    leaves the window; in the switch keys, a second window hears of it."""
    assert PRUEFER[modellwahl.KEY_RUNS] is modellwahl.runs_check
    assert modellwahl.KEY_RUNS in MODEL_SWITCH_KEYS


def test_the_approved_list_is_cleaned():
    assert modellwahl.runs_check(["a:b", " a:b ", "", 3, "c"]) == ["a:b", "c"]
    assert modellwahl.runs_check("a:b") == []


def test_no_cloud_model_is_approved_as_shipped(client):
    assert client.get("/api/v1/settings/global/models_for_runs").json()["wert"] is None


# --- The cloud as the last resort ------------------------------------------


async def test_without_a_local_server_the_run_takes_the_approved_cloud_model(client):
    _empty_field(client)
    await _provider(client, "cloud", ["model-a", "model-b"])
    _approve(client, "cloud:model-b")

    assert _run(client) == "cloud:model-b"


async def test_without_approval_there_is_still_no_model(client):
    """Silence: nothing approved, nothing different from before."""
    _empty_field(client)
    await _provider(client, "cloud", ["model-a"])

    assert _run(client) is None


async def test_only_the_approved_model_of_a_provider_counts(client):
    _empty_field(client)
    await _provider(client, "cloud", ["model-a", "model-b"])
    _approve(client, "cloud:model-a")

    assert _run(client) == "cloud:model-a"
    _approve(client, "cloud:model-c")
    assert _run(client) is None


async def test_of_several_approved_the_order_of_the_list_decides(client):
    """Not the order the ticks were made in: the one the model list shows."""
    _empty_field(client)
    await _provider(client, "first", ["a", "b"])
    await _provider(client, "second", ["c"])
    _approve(client, "second:c", "first:b", "first:a")

    assert _run(client) == "first:a"


async def test_a_run_with_tools_takes_only_a_model_that_can_call_them(client):
    _empty_field(client)
    await _provider(client, "without", ["a"], tools=False)
    await _provider(client, "with", ["b"], tools=True)
    _approve(client, "without:a", "with:b")

    assert _run(client, tools=True) == "with:b"
    assert _run(client, tools=False) == "without:a"
    _approve(client, "without:a")
    assert _run(client, tools=True) is None


async def test_an_approved_model_that_does_not_answer_is_skipped(client):
    _empty_field(client)
    await _provider(client, "dead", ["a"], answers=False)
    await _provider(client, "alive", ["b"])
    _approve(client, "dead:a", "alive:b")

    assert _run(client) == "alive:b"


async def test_an_approved_model_that_is_not_picked_in_the_catalogue_does_not_count(client):
    """The window shows the approval on picked models only, so a model that
    was unpicked must not keep working out of sight."""
    _empty_field(client)
    await _provider(client, "cloud", ["model-a", "model-b"])
    _approve(client, "cloud:model-a", picked=False)

    assert _run(client) is None
    _approve(client, "cloud:model-a")
    assert _run(client) == "cloud:model-a"


async def test_a_provider_without_a_catalogue_is_approved_by_its_own_id(client):
    _empty_field(client)
    await _provider(client, "single", [])
    _approve(client, "single")

    assert _run(client) == "single"


# --- The two local servers come first, and only while approved --------------


async def test_an_answering_approved_local_server_never_hands_the_run_to_the_cloud(client):
    _empty_field(client)
    await _local_server(client, HAUPT)
    await _provider(client, "cloud", ["a"])
    _approve(client, "cloud:a")

    answer = _run(client)
    assert answer is not None and answer.startswith(HAUPT)

    await _local_server(client, SLOT)
    _switch(client, main=False)
    assert _run(client) == SLOT


async def test_a_local_server_without_approval_is_skipped(client):
    _empty_field(client)
    await _local_server(client, HAUPT)
    await _local_server(client, SLOT)

    _switch(client, main=False, agent=True)
    assert _run(client) == SLOT

    _switch(client, agent=False)
    assert _run(client) is None


async def test_the_agent_server_without_approval_leaves_the_main_model_first(client):
    _empty_field(client)
    await _local_server(client, HAUPT)
    await _local_server(client, SLOT)

    _switch(client, agent=False)
    answer = _run(client)
    assert answer is not None and answer.startswith(HAUPT)


async def test_without_approval_of_the_servers_an_approved_cloud_model_takes_the_run(
    client,
):
    _empty_field(client)
    await _local_server(client, HAUPT)
    await _provider(client, "cloud", ["a"])
    _approve(client, "cloud:a")
    _switch(client, main=False)

    assert _run(client) == "cloud:a"


# --- A choice runs whatever the switch says ----------------------------------


async def test_a_hand_pick_runs_on_a_server_without_approval_too(client):
    _empty_field(client)
    await _local_server(client, HAUPT)
    await _local_server(client, SLOT)
    _switch(client, main=False, agent=False)

    assert _run(client, endpoint_id=SLOT) == SLOT
    answer = _run(client, endpoint_id=HAUPT)
    assert answer is not None and answer.startswith(HAUPT)


async def test_the_field_naming_the_main_model_runs_without_approval_too(client):
    await _local_server(client, HAUPT)
    client.app.state.repositories.einstellungen.setzen(
        GLOBAL, wahl.SCHLUESSEL, {"sorte": wahl.SORTE_KENNUNG, "wert": HAUPT}
    )
    _switch(client, main=False)

    answer = _run(client)
    assert answer is not None and answer.startswith(HAUPT)


async def test_a_slot_file_in_the_field_runs_without_approval_too(client):
    await _local_server(client, SLOT)
    client.app.state.repositories.einstellungen.setzen(
        GLOBAL, wahl.SCHLUESSEL, {"sorte": wahl.SORTE_SLOT, "wert": "small.gguf"}
    )
    _switch(client, agent=False)

    assert _run(client) == SLOT


async def test_a_cloud_model_in_the_field_runs_without_a_tick_in_the_list(client):
    await _provider(client, "cloud", ["a"])
    client.app.state.repositories.einstellungen.setzen(
        GLOBAL, wahl.SCHLUESSEL, {"sorte": wahl.SORTE_KENNUNG, "wert": "cloud:a"}
    )

    assert _run(client) == "cloud:a"


# --- The preload ----------------------------------------------------------------


@pytest.mark.parametrize("cloud_approved", [False, True])
async def test_the_preload_serves_the_main_server_with_a_cloud_approved_too(client, cloud_approved):
    """The cloud that would take the run in the meantime is no reason to
    leave the server unloaded."""
    _empty_field(client)
    await _provider(client, "cloud", ["a"])
    if cloud_approved:
        _approve(client, "cloud:a")

    assert wahl.hauptmodell_ist_das_ziel(
        client.app.state.repositories, client.app.state.discovery, slot_id=SLOT
    ) is True


async def test_nothing_is_preloaded_for_a_main_server_without_approval(client):
    """A run never lands on a server that is not approved, so nothing is
    loaded for one."""
    _empty_field(client)
    _switch(client, main=False)

    assert wahl.hauptmodell_ist_das_ziel(
        client.app.state.repositories, client.app.state.discovery, slot_id=SLOT
    ) is False


async def test_a_main_server_named_in_the_field_is_preloaded_without_approval_too(client):
    client.app.state.repositories.einstellungen.setzen(
        GLOBAL, wahl.SCHLUESSEL, {"sorte": wahl.SORTE_KENNUNG, "wert": HAUPT}
    )
    _switch(client, main=False)

    assert wahl.hauptmodell_ist_das_ziel(
        client.app.state.repositories, client.app.state.discovery, slot_id=SLOT
    ) is True


# --- The route -------------------------------------------------------------------


def test_the_approval_can_be_written_through_the_settings_route(client):
    answer = client.put(
        "/api/v1/settings/global/models_for_runs", json={"wert": ["cloud:a", " cloud:a "]}
    )
    assert answer.status_code == 200, answer.text
    assert client.get("/api/v1/settings/global/models_for_runs").json()["wert"] == ["cloud:a"]
