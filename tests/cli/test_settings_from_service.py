"""``/settings`` and ``/set`` against the service itself, not a stand-in:
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
from test_commands import Lines, Shown, Silent

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


def test_a_setting_that_stands_only_in_the_services_table_shows_in_settings(
    ctx, client, monkeypatch
):
    monkeypatch.setitem(einstellungen.PRUEFER, "only_in_the_table", lambda value: value)
    client.put("/api/v1/settings/global/only_in_the_table", json={"wert": "here"})

    ctx.commands.run("/settings")
    assert "only_in_the_table here global" in ctx.screen.lines()


def test_every_single_value_stands_with_the_scope_it_comes_from(ctx, client):
    client.put("/api/v1/settings/global/verdichtung_schwelle", json={"wert": 70})
    client.put("/api/v1/settings/global/weck_runden", json={"wert": 3})
    client.put(f"/api/v1/settings/modell:{MODEL}/weck_runden", json={"wert": 4})
    client.put("/api/v1/settings/global/werkzeug_runden", json={"wert": 30})
    client.put(f"/api/v1/settings/chat:{CHAT}/werkzeug_runden", json={"wert": 20})
    client.put("/api/v1/settings/global/berechtigungsmodus_chat", json={"wert": "auto"})

    ctx.commands.run("/settings")
    lines = ctx.screen.lines()
    # The service keeps this share as a decimal number.
    assert "verdichtung_schwelle 70.0 global" in lines
    assert "berechtigungsmodus_chat auto global" in lines
    assert "weck_runden 4 model" in lines
    assert "werkzeug_runden 20 chat" in lines
    # In the order of the scopes: everywhere, then the model, then the chat.
    order = [line.split()[0] for line in lines]
    assert order.index("verdichtung_schwelle") < order.index("weck_runden")
    assert order.index("weck_runden") < order.index("werkzeug_runden")
    # No value a scope has set stands without that scope.
    held = {"verdichtung_schwelle", "weck_runden", "werkzeug_runden", "berechtigungsmodus_chat"}
    for line in lines:
        name, *_, scope = line.split()
        if name in held:
            assert scope in ("global", "model", "chat"), line


def test_a_value_no_scope_has_set_stands_with_the_word_for_the_default(ctx, client):
    client.put("/api/v1/settings/global/weck_runden", json={"wert": 3})

    ctx.commands.run("/settings")
    lines = ctx.screen.lines()
    # The service answers with two values nobody has set, and these say so.
    assert "scrollstelle.am_boden true default" in lines
    assert "scrollstelle.versatz 0 default" in lines
    # Every line says where its value comes from: none ends in the value.
    origins = [line.split()[-1] for line in lines]
    assert set(origins) <= {"global", "model", "chat", "default"}
    # Silence probe: a value a scope has set names that scope as before,
    # and stands above the ones no scope has set.
    assert "weck_runden 3 global" in lines
    assert origins.index("global") < origins.index("default")


@pytest.mark.parametrize("scope", ["chat", "model"])
def test_set_of_a_permission_mode_outside_the_global_scope_shows_the_services_sentence(
    ctx, client, scope
):
    with pytest.raises(ServiceError) as refused:
        ctx.commands.run(f"/set {scope}.berechtigungsmodus_chat manuell")
    assert refused.value.status == 400
    assert refused.value.detail == t(
        "fehler.setting_only_global", "en", name="berechtigungsmodus_chat"
    )
    settings = client.app.state.repositories.einstellungen
    assert settings.holen(f"chat:{CHAT}", "berechtigungsmodus_chat") is None
    assert settings.holen(f"modell:{MODEL}", "berechtigungsmodus_chat") is None


def test_set_of_a_permission_mode_in_the_global_scope_is_taken(ctx, client):
    """The quiet case."""
    ctx.commands.run("/set global.berechtigungsmodus_chat restricted")
    settings = client.app.state.repositories.einstellungen
    assert settings.holen("global", "berechtigungsmodus_chat") == "restricted"
    assert ctx.screen.lines()[-1].startswith("global.berechtigungsmodus_chat null")
