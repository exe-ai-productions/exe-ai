"""The model the client starts with: the one chosen last stays chosen while
it is not reachable, and nothing is taken in its place.

``_pick_model`` used to fall back to the first model of the list whenever
the one chosen last was missing from the list of reachable models. Now the
first of the list is taken only where none was chosen yet or where the
service no longer carries the server of the chosen one — the same order the
window keeps.

A model is named by its server, and a server that does not answer names
nothing. So the name is stored with the choice, and a client that starts
while the server is away shows the model under that name. The stored name
follows the list: a start that finds the chosen model listed under another
name stores the choice again under that one.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from cli import commands, main, render
from cli.client import ServiceError
from cli.interfaces import Context
from cli.texts import Texts
from tests.cli.stub_service import StubService, eventually, model
from tests.cli.test_app_scaffold import ENTER, FRESH_TITLE, Service, recorded
from tests.cli.test_one_local_time import Written

Line = Callable[..., str]
Wire = Callable[[httpx.Client], Context]

MODELS = "GET /api/v1/models"


def words(key: str) -> str:
    return Texts("en").t(key)


def gone(endpoint: str, name: str) -> dict[str, Any]:
    """An entry as the service lists a server it cannot reach: the name from
    its configuration, no window, and the word ``offline``."""
    return model(endpoint, name, window=None, server_state="offline") | {
        "erreichbar": False,
        "name_gemeldet": False,
    }


def choose(stub: StubService, model_id: str, name: str | None = None) -> None:
    """The model chosen last, as the window or an earlier client stored it:
    without a name the way a choice was stored before names were kept."""
    choice = {"id": model_id} | ({"name": name} if name else {})
    stub.settings.setdefault("global", {})[commands.LAST_MODEL_KEY] = choice


def catalogue_model(endpoint: str, name: str) -> dict[str, Any]:
    """A model of a catalogue: many models on one server, each named
    ``server:model``."""
    return model(endpoint, name) | {"anbieter": endpoint.partition(":")[0]}


def started(wire: Wire, http: httpx.Client) -> Context:
    """A client up to the point where it picks its model, the way
    ``cli/main.py`` gets there: the reachable models loaded, none in use."""
    ctx = wire(http)
    ctx.session.endpoint_id = None
    main._pick_model(ctx)
    return ctx


def stored(stub: StubService) -> Any:
    return stub.settings.get("global", {}).get(commands.LAST_MODEL_KEY)


def test_an_unreachable_choice_stays_chosen_and_the_line_names_it_offline(
    wire: Wire, stub: StubService, stub_http: httpx.Client, status_line: Line
) -> None:
    """Falls over without the fix: the first of the list was taken."""
    stub.models = [gone("alpha", "alpha"), model("beta", "Beta 9B")]
    choose(stub, "alpha")

    ctx = started(wire, stub_http)

    assert ctx.session.endpoint_id == "alpha"
    # The choice in the service is what it was; the start writes nothing.
    assert stored(stub) == {"id": "alpha"}
    assert not [request for request in stub.requests if request.startswith("PUT ")]
    # Asked twice: the reachable models, then the full list for the choice.
    assert stub.requests.count(MODELS) == 2
    # The picker's list is the reachable models, as before.
    assert [listed["id"] for listed in ctx.session.models] == ["beta"]
    ctx.events.start()
    eventually(lambda: words("kopf.server_aus") in status_line(ctx))
    line = status_line(ctx)
    assert "alpha" in line and "Beta 9B" not in line


def test_silence_probe_without_a_choice_the_first_of_the_list_is_taken(
    wire: Wire, stub: StubService, stub_http: httpx.Client, status_line: Line
) -> None:
    stub.models = [model("alpha", "Alpha 35B"), model("beta", "Beta 9B")]

    ctx = started(wire, stub_http)

    assert ctx.session.endpoint_id == "alpha"
    assert "Alpha 35B" in status_line(ctx)
    # The model list is asked for once: the full list is only worth a second
    # request where the choice is not among the reachable ones.
    assert stub.requests.count(MODELS) == 1


def test_a_server_the_service_no_longer_carries_gives_way_to_the_first_of_the_list(
    wire: Wire, stub: StubService, stub_http: httpx.Client, status_line: Line
) -> None:
    stub.models = [model("beta", "Beta 9B")]
    choose(stub, "alpha")

    ctx = started(wire, stub_http)

    assert ctx.session.endpoint_id == "beta"
    assert "Beta 9B" in status_line(ctx)


def test_a_reachable_choice_is_taken_as_before(
    wire: Wire, stub: StubService, stub_http: httpx.Client, status_line: Line
) -> None:
    stub.models = [model("alpha", "Alpha 35B"), model("beta", "Beta 9B", window=4096)]
    choose(stub, "beta")

    ctx = started(wire, stub_http)

    assert ctx.session.endpoint_id == "beta"
    assert "Beta 9B" in status_line(ctx)


def test_a_model_of_a_catalogue_stays_chosen_while_its_server_is_carried(
    wire: Wire, stub: StubService, stub_http: httpx.Client, status_line: Line
) -> None:
    """A model named ``provider:model``: the service lists an unreachable
    provider once, under its bare id. The choice stands, and no name is
    shown that the service did not give for it."""
    stub.models = [gone("cloud", "cloud"), model("beta", "Beta 9B")]
    choose(stub, "cloud:large-1")

    ctx = started(wire, stub_http)

    assert ctx.session.endpoint_id == "cloud:large-1"
    assert stored(stub) == {"id": "cloud:large-1"}
    ctx.events.start()
    eventually(lambda: words("kopf.server_aus") in status_line(ctx))
    assert "Beta 9B" not in status_line(ctx)


def test_with_no_model_reachable_the_choice_still_stands(
    wire: Wire, stub: StubService, stub_http: httpx.Client
) -> None:
    stub.models = [gone("alpha", "alpha")]
    choose(stub, "alpha")

    ctx = started(wire, stub_http)

    assert ctx.session.models == []
    assert ctx.session.endpoint_id == "alpha"


def test_with_nothing_reachable_and_nothing_chosen_no_model_is_picked(
    wire: Wire, stub: StubService, stub_http: httpx.Client
) -> None:
    stub.models = [gone("alpha", "alpha")]

    ctx = started(wire, stub_http)

    assert ctx.session.endpoint_id is None


# --- the name stored with the choice --------------------------------------------

# A model that is its server's only one, and a model of a catalogue: the
# entry while it is reachable, and the one entry the service still lists for
# its server while that is away.
AWAY_AT_THE_START = [
    pytest.param(model("alpha", "Alpha 35B"), gone("alpha", "alpha"), id="a server's only model"),
    pytest.param(
        catalogue_model("cloud:large-1", "Large 1"), gone("cloud", "cloud"), id="a model of a catalogue"
    ),
]


@pytest.mark.parametrize(("reachable", "away"), AWAY_AT_THE_START)
def test_a_client_that_starts_while_the_server_is_away_shows_the_name_stored_with_the_choice(
    reachable: dict[str, Any],
    away: dict[str, Any],
    wire: Wire,
    stub: StubService,
    stub_http: httpx.Client,
    status_line: Line,
) -> None:
    """Falls over without the name in the stored choice: the service names
    a server it cannot ask by its configured name, and a model of a
    catalogue not at all. Two clients, one after the other: the first
    chooses, the second starts on what the first wrote."""
    stub.models = [model("beta", "Beta 9B"), reachable]
    first = started(wire, stub_http)
    first.commands = commands.build_commands(first)
    first.commands.run(f"/model {reachable['name']}")
    assert stored(stub) == {"id": reachable["id"], "name": reachable["name"]}

    stub.models = [model("beta", "Beta 9B"), away]
    second = started(wire, stub_http)

    assert second.session.endpoint_id == reachable["id"]
    assert stored(stub) == {"id": reachable["id"], "name": reachable["name"]}
    second.events.start()
    eventually(lambda: words("kopf.server_aus") in status_line(second))
    line = status_line(second)
    assert reachable["name"] in line and "Beta 9B" not in line


def test_where_the_full_list_does_not_answer_the_choice_stands_under_its_stored_name(
    wire: Wire,
    stub: StubService,
    stub_http: httpx.Client,
    status_line: Line,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nothing is known against the choice then, and the name stored with
    it is all there is to show."""
    stub.models = [gone("alpha", "alpha"), model("beta", "Beta 9B")]
    choose(stub, "alpha", "Alpha 35B")
    ctx = wire(stub_http)
    ctx.session.endpoint_id = None
    ask = ctx.client.get

    def no_full_list(path: str, **options: Any) -> Any:
        if path == "/models" and options.get("params"):
            raise ServiceError(503, "no answer")
        return ask(path, **options)

    monkeypatch.setattr(ctx.client, "get", no_full_list)
    main._pick_model(ctx)

    assert ctx.session.endpoint_id == "alpha"
    line = status_line(ctx)
    assert "Alpha 35B" in line and "Beta 9B" not in line


def test_silence_probe_a_reachable_choice_goes_by_the_name_the_service_gives(
    wire: Wire, stub: StubService, stub_http: httpx.Client, status_line: Line
) -> None:
    """The stored name is for the time the server is away."""
    stub.models = [model("alpha", "Alpha 35B"), model("beta", "Beta 9B")]
    choose(stub, "beta", "An older name")

    ctx = started(wire, stub_http)

    line = status_line(ctx)
    assert "Beta 9B" in line and "An older name" not in line


# --- the stored name follows the list --------------------------------------------

WRITTEN = f"PUT /api/v1/settings/global/{commands.LAST_MODEL_KEY}"


def writes(stub: StubService) -> list[str]:
    """Everything the client wrote to the service's settings."""
    settings = ("PUT /api/v1/settings/", "PATCH /api/v1/settings/")
    return [request for request in stub.requests if request.startswith(settings)]


def test_a_start_that_finds_the_choice_listed_under_another_name_stores_it_under_that_one(
    wire: Wire, stub: StubService, stub_http: httpx.Client, status_line: Line
) -> None:
    """Falls over without the fix: the name was shown and never stored, so
    the start with the server away went back to the older one. Three
    starts, no choosing in between."""
    stub.models = [model("alpha", "Alpha 35B"), model("beta", "Beta 9B")]
    choose(stub, "beta", "An older name")

    first = started(wire, stub_http)

    # The same choice under the new name, written once.
    assert first.session.endpoint_id == "beta"
    assert stored(stub) == {"id": "beta", "name": "Beta 9B"}
    assert writes(stub) == [WRITTEN]

    # The server goes away: the name the list gave last is what is shown.
    stub.models = [model("alpha", "Alpha 35B"), gone("beta", "beta")]
    second = started(wire, stub_http)
    assert second.session.endpoint_id == "beta"
    line = status_line(second)
    assert "Beta 9B" in line and "An older name" not in line and "Alpha 35B" not in line

    # And back again under the same name: nothing more is written.
    stub.models = [model("alpha", "Alpha 35B"), model("beta", "Beta 9B")]
    started(wire, stub_http)
    assert writes(stub) == [WRITTEN]


def test_a_choice_stored_without_a_name_is_given_the_one_the_list_has(
    wire: Wire, stub: StubService, stub_http: httpx.Client
) -> None:
    """The way a choice was stored before names were kept."""
    stub.models = [model("alpha", "Alpha 35B"), model("beta", "Beta 9B")]
    choose(stub, "beta")

    started(wire, stub_http)

    assert stored(stub) == {"id": "beta", "name": "Beta 9B"}
    assert writes(stub) == [WRITTEN]


def test_silence_probe_a_choice_listed_under_its_stored_name_is_not_written(
    wire: Wire, stub: StubService, stub_http: httpx.Client, status_line: Line
) -> None:
    stub.models = [model("alpha", "Alpha 35B"), model("beta", "Beta 9B")]
    choose(stub, "beta", "Beta 9B")

    ctx = started(wire, stub_http)

    assert ctx.session.endpoint_id == "beta" and "Beta 9B" in status_line(ctx)
    assert stored(stub) == {"id": "beta", "name": "Beta 9B"}
    assert writes(stub) == []


def test_a_listed_name_is_stored_without_the_blanks_around_it(
    wire: Wire, stub: StubService, stub_http: httpx.Client
) -> None:
    """The service keeps a name without them. Stored as it stands in the
    list, it would never equal what the list says, and every start would
    write it again."""
    stub.models = [model("alpha", "Alpha 35B"), model("beta", "  Beta 9B ")]
    choose(stub, "beta", "An older name")

    started(wire, stub_http)
    assert stored(stub) == {"id": "beta", "name": "Beta 9B"}
    assert writes(stub) == [WRITTEN]

    started(wire, stub_http)
    assert writes(stub) == [WRITTEN]


@pytest.mark.parametrize("nameless", ["", "   ", None])
def test_silence_probe_an_entry_without_a_name_leaves_the_stored_one(
    nameless: str | None, wire: Wire, stub: StubService, stub_http: httpx.Client
) -> None:
    """An entry that names nothing says nothing about the name — one of
    blanks only included."""
    stub.models = [model("alpha", "Alpha 35B"), model("beta", "Beta 9B") | {"name": nameless}]
    choose(stub, "beta", "An older name")

    ctx = started(wire, stub_http)

    assert ctx.session.endpoint_id == "beta"
    assert stored(stub) == {"id": "beta", "name": "An older name"}
    assert writes(stub) == []


@pytest.mark.parametrize("reported", [False, None])
def test_a_name_the_configuration_gives_the_server_is_not_stored_as_the_models(
    reported: bool | None, wire: Wire, stub: StubService, stub_http: httpx.Client, status_line: Line
) -> None:
    """Falls over without the fix: a reachable server that reports no model
    name is listed under the name the configuration gives it, and the stored
    name followed that — an older service that does not say which kind of
    name an entry carries is read the same way. The model is in use under
    the name the list gives, as before."""
    unreported = model("alpha", "my server") | {"name_gemeldet": reported}
    stub.models = [unreported, model("beta", "Beta 9B")]
    choose(stub, "alpha", "Alpha 35B")

    ctx = started(wire, stub_http)

    assert ctx.session.endpoint_id == "alpha"
    assert "my server" in status_line(ctx)
    assert stored(stub) == {"id": "alpha", "name": "Alpha 35B"}
    assert writes(stub) == []


def test_silence_probe_a_name_the_server_reports_is_followed(
    wire: Wire, stub: StubService, stub_http: httpx.Client
) -> None:
    stub.models = [model("alpha", "Alpha 70B"), model("beta", "Beta 9B")]
    choose(stub, "alpha", "Alpha 35B")

    started(wire, stub_http)

    assert stored(stub) == {"id": "alpha", "name": "Alpha 70B"}
    assert writes(stub) == [WRITTEN]


def test_silence_probe_a_choice_that_is_not_listed_is_not_written(
    wire: Wire, stub: StubService, stub_http: httpx.Client
) -> None:
    """Its server is away: the full list names the server by its
    configured name, and that is no name of the model."""
    stub.models = [gone("alpha", "alpha"), model("beta", "Beta 9B")]
    choose(stub, "alpha", "Alpha 35B")

    ctx = started(wire, stub_http)

    assert ctx.session.endpoint_id == "alpha"
    assert stored(stub) == {"id": "alpha", "name": "Alpha 35B"}
    assert writes(stub) == []


def test_silence_probe_a_choice_that_gives_way_to_the_first_of_the_list_is_not_written_over(
    wire: Wire, stub: StubService, stub_http: httpx.Client
) -> None:
    """The service no longer carries the server of the choice: the first of
    the list is taken for this start, and the choice stands as stored."""
    stub.models = [model("beta", "Beta 9B")]
    choose(stub, "alpha", "Alpha 35B")

    ctx = started(wire, stub_http)

    assert ctx.session.endpoint_id == "beta"
    assert stored(stub) == {"id": "alpha", "name": "Alpha 35B"}
    assert writes(stub) == []


def test_silence_probe_without_a_choice_nothing_is_written(
    wire: Wire, stub: StubService, stub_http: httpx.Client
) -> None:
    stub.models = [model("alpha", "Alpha 35B"), model("beta", "Beta 9B")]

    ctx = started(wire, stub_http)

    assert ctx.session.endpoint_id == "alpha"
    assert stored(stub) is None
    assert writes(stub) == []


def test_a_refused_write_of_the_name_does_not_hold_the_start(
    wire: Wire,
    stub: StubService,
    stub_http: httpx.Client,
    status_line: Line,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub.models = [model("alpha", "Alpha 35B"), model("beta", "Beta 9B")]
    choose(stub, "beta", "An older name")
    ctx = wire(stub_http)
    ctx.session.endpoint_id = None
    asked: list[tuple[str, Any]] = []

    def refused(path: str, **options: Any) -> Any:
        asked.append((path, options.get("json")))
        raise ServiceError(400, "not now")

    monkeypatch.setattr(ctx.client, "put", refused)
    main._pick_model(ctx)

    # Asked once, with the choice of this start and the name of the list.
    assert asked == [
        (f"/settings/global/{commands.LAST_MODEL_KEY}", {"wert": {"id": "beta", "name": "Beta 9B"}})
    ]
    # The start went on: the model is in use under the name the list gives.
    assert ctx.session.endpoint_id == "beta"
    assert "Beta 9B" in status_line(ctx)
    assert stored(stub) == {"id": "beta", "name": "An older name"}


# --- the mark on a model whose server is reported as gone ------------------------


def test_a_model_of_a_catalogue_is_marked_when_its_server_is_reported_as_gone(
    wire: Wire, stub: StubService, stub_http: httpx.Client, status_line: Line
) -> None:
    """Falls over without the fix: the service reports servers, and the id
    of the model in use was looked up among them — which a model named
    ``server:model`` never is."""
    stub.models = [catalogue_model("cloud:large-1", "Large 1"), model("beta", "Beta 9B")]
    choose(stub, "cloud:large-1", "Large 1")
    ctx = started(wire, stub_http)
    marked = f"Large 1 {words('status.nicht_erreichbar')}"
    assert marked not in status_line(ctx)

    ctx.events.handle({"typ": "endpunkt_status", "endpoint_id": "cloud", "erreichbar": False})
    assert marked in status_line(ctx)

    ctx.events.handle({"typ": "endpunkt_status", "endpoint_id": "cloud", "erreichbar": True})
    assert marked not in status_line(ctx)


def test_silence_probe_another_server_gone_marks_neither_kind_of_model(
    wire: Wire, stub: StubService, stub_http: httpx.Client, status_line: Line
) -> None:
    stub.models = [catalogue_model("cloud:large-1", "Large 1"), model("beta", "Beta 9B")]
    gone_word = words("status.nicht_erreichbar")

    choose(stub, "cloud:large-1", "Large 1")
    in_a_catalogue = started(wire, stub_http)
    in_a_catalogue.events.handle({"typ": "endpunkt_status", "endpoint_id": "beta", "erreichbar": False})
    assert "Large 1" in status_line(in_a_catalogue)
    assert gone_word not in status_line(in_a_catalogue)

    choose(stub, "beta", "Beta 9B")
    alone = started(wire, stub_http)
    alone.events.handle({"typ": "endpunkt_status", "endpoint_id": "cloud", "erreichbar": False})
    assert gone_word not in status_line(alone)
    # A server's only model is marked by the same id as before.
    alone.events.handle({"typ": "endpunkt_status", "endpoint_id": "beta", "erreichbar": False})
    assert f"Beta 9B {gone_word}" in status_line(alone)


# --- the head names the chosen model like the status line ------------------------

VERSION = "9.8.7"


def standing(ctx: Context) -> str:
    """The line of the head that says where the client stands, as the real
    renderer writes it for this client."""
    screen = Written()
    ctx.screen = screen
    ctx.renderer = render.build_renderer(ctx)
    ctx.renderer.header(VERSION, "http://stub.test")
    return next(line for line in screen.text().splitlines() if f" {VERSION} " in line)


@pytest.mark.parametrize(
    ("away", "chosen", "name"),
    [
        pytest.param(gone("alpha", "alpha"), "alpha", "Alpha 35B", id="a server's only model"),
        pytest.param(gone("cloud", "cloud"), "cloud:large-1", "Large 1", id="a model of a catalogue"),
    ],
)
def test_the_head_names_a_chosen_model_whose_server_is_away_like_the_status_line(
    away: dict[str, Any],
    chosen: str,
    name: str,
    wire: Wire,
    stub: StubService,
    stub_http: httpx.Client,
    status_line: Line,
) -> None:
    """Falls over without the fix: the head looked the name up among the
    reachable models, where a model whose server is away is not."""
    stub.models = [away, model("beta", "Beta 9B")]
    choose(stub, chosen, name)

    ctx = started(wire, stub_http)

    head = standing(ctx)
    assert name in head and "Beta 9B" not in head
    assert name in status_line(ctx)
    # The name and nothing about the server: that word is the status line's.
    assert words("kopf.server_aus") not in head
    assert words("status.nicht_erreichbar") not in head


def test_the_head_takes_the_name_the_status_line_falls_back_to(
    wire: Wire, stub: StubService, stub_http: httpx.Client, status_line: Line
) -> None:
    """A choice stored without a name: the status line shows what the
    service still calls the server, and the head shows the same."""
    stub.models = [gone("alpha", "Configured Alpha"), model("beta", "Beta 9B")]
    choose(stub, "alpha")

    ctx = started(wire, stub_http)

    assert "Configured Alpha" in status_line(ctx)
    assert "Configured Alpha" in standing(ctx)


def test_silence_probe_the_head_names_a_reachable_model_as_the_service_does(
    wire: Wire, stub: StubService, stub_http: httpx.Client
) -> None:
    stub.models = [model("alpha", "Alpha 35B"), model("beta", "Beta 9B")]
    choose(stub, "beta", "An older name")

    head = standing(started(wire, stub_http))

    assert "Beta 9B" in head
    assert "An older name" not in head and "Alpha 35B" not in head


def test_silence_probe_without_a_model_the_head_names_none(
    wire: Wire, stub: StubService, stub_http: httpx.Client, status_line: Line
) -> None:
    """Nothing chosen and nothing reachable, and a model of a catalogue that
    was stored without a name: the status line names no model, and neither
    does the head."""
    stub.models = [gone("cloud", "cloud")]
    nothing_chosen = started(wire, stub_http)
    assert nothing_chosen.session.endpoint_id is None
    assert "cloud" not in standing(nothing_chosen).replace("http://stub.test", "")

    choose(stub, "cloud:large-1")
    nameless = started(wire, stub_http)
    assert nameless.session.endpoint_id == "cloud:large-1"
    head = standing(nameless).replace("http://stub.test", "")
    assert "cloud" not in head and "large-1" not in head
    assert "large-1" not in status_line(nameless)


class ServiceWithAServerAway(Service):
    """The whole client's stand-in service, listing reachable models only
    unless the full list is asked for — as the service does."""

    def __call__(self, request: httpx.Request) -> httpx.Response:
        answer = super().__call__(request)
        listing = request.url.path == "/api/v1/models" and answer.status_code == 200
        if listing and request.url.params.get("alle") != "true":
            return httpx.Response(200, json=[entry for entry in self.models if entry["erreichbar"]])
        return answer


def test_the_whole_client_started_while_the_server_is_away_names_the_model_in_head_and_status_line(
    tmp_path: Any,
) -> None:
    """The client's own start, not the two steps called by hand: the head
    is written after the model is picked, and reads what the status line
    was given."""
    service = ServiceWithAServerAway(
        models=[
            {"id": "local", "name": "Local Model", "erreichbar": True, "context_tokens": 8192},
            {"id": "away", "name": "Away Model", "erreichbar": False, "context_tokens": None},
        ],
        last_model="away",
    )
    lines = recorded("/quit" + ENTER, service=service, tmp_path=tmp_path).splitlines()
    head = next(line for line in lines if line.startswith(f"CLI {VERSION}"))
    status = next(line for line in lines if FRESH_TITLE in line)
    assert "Away Model" in head and "Local Model" not in head
    assert "Away Model" in status and "Local Model" not in status


def test_the_whole_client_stores_the_name_at_its_start_and_starts_where_that_is_refused(
    tmp_path: Any,
) -> None:
    """The client's own start: the choice is stored without a name, the
    list names the model, and the stand-in knows no address to write to —
    it refuses, and the client runs all the same."""
    service = Service(
        models=[
            {
                "id": "local", "name": "Local Model", "name_gemeldet": True,
                "erreichbar": True, "context_tokens": 8192,
            }
        ],
        last_model="local",
    )

    lines = recorded("/quit" + ENTER, service=service, tmp_path=tmp_path).splitlines()

    written = [request for request in service.seen if request.method == "PUT"]
    assert [(request.url.path, json.loads(request.content)) for request in written] == [
        (
            f"/api/v1/settings/global/{commands.LAST_MODEL_KEY}",
            {"wert": {"id": "local", "name": "Local Model"}},
        )
    ]
    status = next(line for line in lines if FRESH_TITLE in line)
    assert "Local Model" in status
