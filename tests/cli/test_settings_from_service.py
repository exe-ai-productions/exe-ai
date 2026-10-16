"""``/settings`` and ``/settings`` against the service itself, not a stand-in:
the client carries no list of settings, every value shown names its scope,
and a permission mode outside the global scope is refused in the service's
words."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.v1 import einstellungen
from app.i18n import t
from cli import commands
from cli.client import ServiceClient, ServiceError
from cli.interfaces import Context
from cli.texts import Texts
from test_commands import Lines, Shown, Silent, Walking

CHAT = "chat-of-this-test"
MODEL = "model-of-this-test"


@pytest.fixture
def ctx(client: TestClient, tmp_path: Path) -> Context:
    """The commands, talking to the service of this test through its own
    test client."""
    service = ServiceClient("http://testserver", "en", http=client)
    service.connect()
    ctx = Context(client=service, texts=Texts("en"), prefs_path=tmp_path / "cli.json")
    ctx.screen = Shown(ctx)
    ctx.renderer = Lines(ctx)
    ctx.asker = Silent()
    ctx.commands = commands.build_commands(ctx)
    ctx.session.endpoint_id = MODEL
    ctx.session.chat = {"id": CHAT, "title": "A chat"}
    return ctx


def scope_rows(ctx: Context, area: int) -> dict[str, tuple[str, str]]:
    """Opens ``/settings`` and then the scope at ``area``: each setting
    shown with its origin and its value, by name."""
    ctx.asker = Walking(area)
    ctx.commands.run("/settings")
    rows = ctx.asker.rows()
    return {
        row[0]: (row[1], note) for row, note in zip(rows, ctx.asker.remarks(), strict=True)
    }


def test_a_setting_that_stands_only_in_the_services_table_shows_in_settings(
    ctx, client, monkeypatch
):
    monkeypatch.setitem(einstellungen.PRUEFER, "only_in_the_table", lambda value: value)
    client.put("/api/v1/settings/global/only_in_the_table", json={"wert": "here"})

    assert scope_rows(ctx, 0)["only_in_the_table"] == ("global", "here")


def test_every_single_value_stands_with_the_scope_it_comes_from(ctx, client):
    client.put("/api/v1/settings/global/verdichtung_schwelle", json={"wert": 70})
    client.put("/api/v1/settings/global/weck_runden", json={"wert": 3})
    client.put(f"/api/v1/settings/modell:{MODEL}/weck_runden", json={"wert": 4})
    client.put("/api/v1/settings/global/werkzeug_runden", json={"wert": 30})
    client.put(f"/api/v1/settings/chat:{CHAT}/werkzeug_runden", json={"wert": 20})
    client.put("/api/v1/settings/global/berechtigungsmodus_chat", json={"wert": "auto"})

    rows = scope_rows(ctx, 2)
    # The service keeps this share as a decimal number.
    assert rows["verdichtung_schwelle"] == ("global", "70.0")
    assert rows["berechtigungsmodus_chat"] == ("global", "auto")
    assert rows["weck_runden"] == ("model", "4")
    assert rows["werkzeug_runden"] == ("chat", "20")
    # In the order of the scopes: everywhere, then the model, then the chat.
    order = list(rows)
    assert order.index("verdichtung_schwelle") < order.index("weck_runden")
    assert order.index("weck_runden") < order.index("werkzeug_runden")
    # No value a scope has set stands without that scope.
    held = {"verdichtung_schwelle", "weck_runden", "werkzeug_runden", "berechtigungsmodus_chat"}
    for name, (scope, _) in rows.items():
        if name in held:
            assert scope in ("global", "model", "chat"), name


def test_a_value_no_scope_has_set_stands_with_the_word_for_the_default(ctx, client):
    client.put("/api/v1/settings/global/weck_runden", json={"wert": 3})

    rows = scope_rows(ctx, 0)
    # The service answers with two values nobody has set, and these say so.
    assert rows["scrollstelle.am_boden"] == ("default", "true")
    assert rows["scrollstelle.versatz"] == ("default", "0")
    # Every row says where its value comes from.
    origins = [origin for origin, _ in rows.values()]
    assert set(origins) <= {"global", "model", "chat", "default"}
    # Silence probe: a value a scope has set names that scope as before,
    # and stands above the ones no scope has set.
    assert rows["weck_runden"] == ("global", "3")
    assert origins.index("global") < origins.index("default")


@pytest.mark.parametrize("scope", ["chat", "model"])
def test_set_of_a_permission_mode_outside_the_global_scope_shows_the_services_sentence(
    ctx, client, scope
):
    with pytest.raises(ServiceError) as refused:
        ctx.commands.run(f"/settings {scope}.berechtigungsmodus_chat manuell")
    assert refused.value.status == 400
    assert refused.value.detail == t(
        "fehler.setting_only_global", "en", name="berechtigungsmodus_chat"
    )
    settings = client.app.state.repositories.einstellungen
    assert settings.holen(f"chat:{CHAT}", "berechtigungsmodus_chat") is None
    assert settings.holen(f"modell:{MODEL}", "berechtigungsmodus_chat") is None


def test_set_of_a_permission_mode_in_the_global_scope_is_taken(ctx, client):
    """The quiet case."""
    ctx.commands.run("/settings global.berechtigungsmodus_chat restricted")
    settings = client.app.state.repositories.einstellungen
    assert settings.holen("global", "berechtigungsmodus_chat") == "restricted"
    assert ctx.screen.lines()[-1].startswith("global.berechtigungsmodus_chat null")
