"""``/mcp``: the servers with whether they answer, a new one entered the way
the mask enters it, the switches of one entry, the sign-in through the
browser, and an entry removed. The service is the stand-in; nothing is
drawn."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from cli import commands, mcp_servers
from cli.interfaces import Asker, Context, Entry
from cli.texts import Texts
from tests.cli.conftest import RecordingRenderer, RecordingScreen
from tests.cli.stub_service import StubService, model


def texts() -> Texts:
    return Texts("en")


class Asking(Asker):
    def __init__(self) -> None:
        self.shown: list[list[Entry]] = []
        self.heads: list[str] = []
        self.picks: list[int | None] = []
        self.typed: list[str | None] = []
        self.questions: list[tuple[str, bool]] = []

    def choose(self, entries: Any, head: str = "") -> int | None:
        self.shown.append(list(entries))
        self.heads.append(head)
        return self.picks.pop(0) if self.picks else None

    def ask_text(
        self, head: str, *, secret: bool = False, default: str | None = None
    ) -> str | None:
        self.questions.append((head, secret))
        return self.typed.pop(0) if self.typed else None

    def rows(self) -> list[list[str]]:
        return [[text for _, text in entry.cells] for entry in self.shown[-1]]


def server(name: str, **fields: Any) -> dict[str, Any]:
    return {
        "name": name, "type": "http", "url": f"https://{name}.example.test/mcp", "enabled": True,
        "laeuft": True, "alle_werkzeuge": [{"name": "search", "beschreibung": ""}, {"name": "fetch", "beschreibung": ""}],
        "allowed_tools": None, "needs_confirmation": [], **fields,
    }


@pytest.fixture
def mcp(
    stub: StubService,
    wire: Callable[[httpx.Client], Context],
    stub_http: httpx.Client,
    monkeypatch: pytest.MonkeyPatch,
) -> Context:
    stub.models = [model("local", "Local Model")]
    monkeypatch.setattr(mcp_servers, "_FIRST_WAIT", 0.0)
    monkeypatch.setattr(mcp_servers, "_NEXT_WAIT", 0.0)
    context = wire(stub_http)
    context.asker = Asking()
    context.renderer = RecordingRenderer()
    context.screen = RecordingScreen(context)
    context.commands = commands.build_commands(context)
    return context


@pytest.fixture
def opened(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    addresses: list[str] = []
    monkeypatch.setattr(mcp_servers.webbrowser, "open", lambda address: addresses.append(address))
    return addresses


def actions(stub: StubService, what: str) -> list[tuple[str, Any]]:
    return [(name, body) for kind, name, body in stub.mcp_actions if kind == what]


# --- The names as the mask makes them ----------------------------------------------------


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("My Server", "my-server"),
        ("  --Docs__v2--  ", "docs-v2"),
        ("a" * 40, "a" * 30),
        ("???", ""),
    ],
)
def test_an_id_is_lower_case_with_single_hyphens_and_at_most_thirty_characters(given, expected):
    assert mcp_servers.server_id(given) == expected


def test_the_key_variable_is_the_id_in_capitals_with_underscores_and_no_leading_digit():
    assert mcp_servers.key_variable("my-docs") == "MY_DOCS_API_KEY"
    assert mcp_servers.key_variable("1password") == "_1PASSWORD_API_KEY"


def test_the_time_limit_is_a_number_above_zero_or_nothing():
    assert mcp_servers.time_limit(" 30 ") == 30.0
    assert mcp_servers.time_limit("0") is None
    assert mcp_servers.time_limit("-5") is None
    assert mcp_servers.time_limit("soon") is None
    assert mcp_servers.time_limit("inf") is None
    assert mcp_servers.time_limit("nan") is None
    assert mcp_servers.time_limit("") is None


def test_a_tool_outside_the_offered_ones_is_off_whatever_the_asking_list_says():
    entry = {"allowed_tools": ["a"], "needs_confirmation": ["b"]}
    assert mcp_servers.state_of("b", entry) == mcp_servers.OFF
    assert mcp_servers.state_of("a", entry) == mcp_servers.ON
    assert mcp_servers.state_of("a", {"allowed_tools": None, "needs_confirmation": ["a"]}) == mcp_servers.ASKS


def test_a_tool_that_asks_stands_in_both_lists_and_one_that_is_off_in_neither():
    assert mcp_servers.lists_of({"a": "an", "b": "fragt", "c": "aus"}) == {
        "allowed_tools": ["a", "b"],
        "needs_confirmation": ["b"],
    }


# --- The selection -----------------------------------------------------------------------------


def test_the_selection_has_add_on_top_and_each_server_with_its_state_and_tool_count(mcp, stub):
    stub.mcp_servers = {"docs": server("docs"), "wiki": server("wiki", laeuft=False, alle_werkzeuge=[])}
    mcp.commands.run("/mcp")
    assert mcp.asker.rows() == [
        [texts().t("verbindungen.hinzufuegen")],
        ["docs", texts().t("verbindungen.stand_verbunden"), texts().t("mcp.tools_zahl", n=2)],
        ["wiki", texts().t("verbindungen.stand_getrennt"), ""],
    ]


def test_without_servers_only_add_stands_there(mcp, stub):
    mcp.commands.run("/mcp")
    assert mcp.asker.rows() == [[texts().t("verbindungen.hinzufuegen")]]


def test_leaving_the_selection_changes_nothing(mcp, stub):
    stub.mcp_servers = {"docs": server("docs")}
    mcp.commands.run("/mcp")
    assert stub.mcp_actions == []
    assert mcp.renderer.notices == [] and mcp.renderer.errors == []


# --- Adding ----------------------------------------------------------------------------------


def test_a_server_that_needs_nothing_is_entered_new_and_its_line_and_time_limit_follow(mcp, stub):
    stub.mcp_probes["https://docs.example.test/mcp"] = {"verlangt": None, "name": "My Docs"}
    mcp.asker.picks = [0]
    mcp.asker.typed = ["https://docs.example.test/mcp", "45"]
    mcp.commands.run("/mcp")
    assert actions(stub, "write") == [
        ("my-docs", {"type": "http", "url": "https://docs.example.test/mcp"}),
        ("my-docs", {"timeout": 45.0}),
    ]
    assert [question for question, _ in mcp.asker.questions] == [
        texts().t("mcp.url"), texts().t("mcp.zeitgrenze")
    ]
    assert mcp.renderer.notices == [
        f"my-docs  {texts().t('verbindungen.stand_verbunden')}  {texts().t('mcp.tools_zahl', n=2)}"
    ]


def test_an_empty_or_invalid_time_limit_leaves_the_default(mcp, stub):
    for answer in ("", "0", "soon"):
        stub.mcp_servers.clear()
        stub.mcp_actions.clear()
        mcp.asker.picks = [0]
        mcp.asker.typed = ["https://docs.example.test/mcp", answer]
        mcp.commands.run("/mcp")
        assert actions(stub, "write") == [
            ("https-docs-example-test-mcp", {"type": "http", "url": "https://docs.example.test/mcp"})
        ]


def test_a_name_that_leaves_nothing_after_the_cleaning_is_refused_and_nothing_is_written(mcp, stub):
    stub.mcp_probes["???"] = {"verlangt": None, "name": "???"}
    mcp.asker.picks = [0]
    mcp.asker.typed = ["???"]
    mcp.commands.run("/mcp")
    assert mcp.renderer.errors == [texts().t("mcp.name_ungueltig")]
    assert actions(stub, "write") == []


def test_an_empty_address_or_esc_asks_nothing_of_the_service(mcp, stub):
    mcp.asker.picks = [0]
    mcp.asker.typed = [""]
    mcp.commands.run("/mcp")
    assert stub.mcp_actions == []


def test_a_server_that_wants_a_key_is_asked_for_it_hidden_and_gets_its_variable(mcp, stub):
    stub.mcp_probes["https://api.docs.test/mcp"] = {"verlangt": "schluessel"}
    mcp.asker.picks = [0]
    mcp.asker.typed = ["https://api.docs.test/mcp", "sk-secret-1", ""]
    mcp.commands.run("/mcp")
    assert (texts().t("mcp.api_key"), True) in mcp.asker.questions
    assert actions(stub, "write")[0] == (
        "api-docs-test",
        {
            "type": "http", "url": "https://api.docs.test/mcp",
            "api_key_env": "API_DOCS_TEST_API_KEY", "api_key": "sk-secret-1",
        },
    )
    assert "sk-secret-1" not in " ".join(mcp.renderer.notices + mcp.renderer.errors)


def test_a_refusal_never_repeats_the_key_that_was_sent(mcp, stub):
    stub.mcp_probes["https://api.docs.test/mcp"] = {"verlangt": "schluessel"}
    stub.refuse_mcp = "The key sk-secret-1 was rejected."
    mcp.asker.picks = [0]
    mcp.asker.typed = ["https://api.docs.test/mcp", "sk-secret-1"]
    mcp.commands.run("/mcp")
    assert mcp.renderer.errors == ["The key … was rejected."]


def test_a_server_with_a_sign_in_opens_the_browser_and_waits_for_it(mcp, stub, opened):
    stub.mcp_probes["https://auth.docs.test/mcp"] = {"verlangt": "anmeldung"}
    mcp.asker.picks = [0]
    mcp.asker.typed = ["https://auth.docs.test/mcp", ""]
    mcp.commands.run("/mcp")
    assert actions(stub, "write")[0] == (
        "auth-docs-test", {"type": "http", "url": "https://auth.docs.test/mcp", "enabled": True}
    )
    assert actions(stub, "oauth") == [("auth-docs-test", {"server": "auth-docs-test"})]
    assert opened == [stub.mcp_sign_in_url]
    assert mcp.renderer.notices[-1].startswith("auth-docs-test  ")


def test_a_server_that_wants_a_client_id_gets_it_and_the_secret_sent_to_the_sign_in(mcp, stub, opened):
    stub.mcp_probes["https://auth.docs.test/mcp"] = {"verlangt": "oauth_kennung"}
    mcp.asker.picks = [0]
    mcp.asker.typed = ["https://auth.docs.test/mcp", "client-7", "shh-secret", ""]
    mcp.commands.run("/mcp")
    assert (texts().t("verbindungen.geheimnis"), True) in mcp.asker.questions
    assert actions(stub, "oauth") == [
        ("auth-docs-test", {"server": "auth-docs-test", "client_id": "client-7", "client_secret": "shh-secret"})
    ]
    assert "shh-secret" not in " ".join(mcp.renderer.notices + mcp.renderer.errors)


def test_a_server_that_never_answers_says_so_and_stays_entered(mcp, stub):
    stub.mcp_connects = False
    mcp.asker.picks = [0]
    mcp.asker.typed = ["https://docs.example.test/mcp"]
    mcp.commands.run("/mcp")
    assert mcp.renderer.errors == [texts().t("mcp.nicht_erreichbar")]
    assert len(stub.mcp_servers) == 1
    assert [question for question, _ in mcp.asker.questions] == [texts().t("mcp.url")]


def test_the_interrupt_key_ends_the_wait_without_a_sentence(mcp, stub, monkeypatch):
    stub.mcp_connects = False
    monkeypatch.setattr(mcp_servers, "_FIRST_WAIT", 0.5)
    monkeypatch.setattr(mcp_servers, "_NEXT_WAIT", 0.5)
    mcp.asker.picks = [0]
    mcp.asker.typed = ["https://docs.example.test/mcp"]
    timer = threading.Timer(0.1, lambda: mcp.session.cancel_wait and mcp.session.cancel_wait())
    timer.start()
    mcp.commands.run("/mcp")
    timer.join()
    assert mcp.renderer.errors == [] and mcp.renderer.notices == []


# --- The menu of one server ------------------------------------------------------------


def test_the_menu_offers_edit_the_browser_sign_in_for_a_server_without_a_key_and_remove(mcp, stub):
    stub.mcp_servers = {"docs": server("docs")}
    mcp.asker.picks = [1]
    mcp.commands.run("/mcp")
    # The second selection is the menu of the server.
    mcp.asker.picks = [None]
    mcp.commands.run("/mcp 2")
    assert mcp.asker.rows() == [
        [texts().t("skills.bearbeiten")],
        [texts().t("mcp.im_browser_anmelden")],
        [texts().t("verbindungen.entfernen")],
    ]


def test_a_server_with_a_key_or_a_command_has_no_browser_sign_in(mcp, stub):
    stub.mcp_servers = {
        "keyed": server("keyed", api_key_env="KEYED_API_KEY"),
        "local": server("local", type="stdio"),
    }
    for number in (2, 3):
        mcp.commands.run(f"/mcp {number}")
        assert [texts().t("mcp.im_browser_anmelden")] not in mcp.asker.rows()


def test_the_browser_sign_in_of_an_entry_starts_the_flow_for_it(mcp, stub, opened):
    stub.mcp_servers = {"docs": server("docs", laeuft=False, alle_werkzeuge=[])}
    mcp.asker.picks = [1, 1]
    mcp.commands.run("/mcp")
    assert actions(stub, "oauth") == [("docs", {"server": "docs"})]
    assert opened == [stub.mcp_sign_in_url]


def test_a_number_counts_into_the_selection_and_one_is_add(mcp, stub):
    stub.mcp_servers = {"docs": server("docs"), "wiki": server("wiki")}
    mcp.commands.run("/mcp 3")
    assert mcp.asker.heads[-1].startswith("wiki")


@pytest.mark.parametrize("line", ["/mcp 9", "/mcp 0", "/mcp docs"])
def test_a_number_that_is_no_server_and_any_other_word_are_unknown(mcp, stub, line):
    stub.mcp_servers = {"docs": server("docs")}
    mcp.commands.run(line)
    assert len(mcp.renderer.errors) == 1
    assert mcp.asker.shown == []


# --- Editing ----------------------------------------------------------------------------------


def test_enter_on_active_switches_the_entry_and_says_its_line(mcp, stub):
    stub.mcp_servers = {"docs": server("docs")}
    mcp.asker.picks = [1, 0, 0]
    mcp.commands.run("/mcp")
    assert actions(stub, "write") == [("docs", {"enabled": False})]
    assert mcp.asker.rows()[0][1] == texts().t("status.inaktiv")
    assert mcp.renderer.notices[0].startswith("docs  ")


def test_the_tools_show_active_asks_and_inactive_and_each_press_goes_one_step_on(mcp, stub):
    stub.mcp_servers = {"docs": server("docs")}
    # server 1 → edit → tool "search" three times.
    mcp.asker.picks = [1, 0, 1, 1, 1]
    mcp.commands.run("/mcp")
    assert actions(stub, "write") == [
        ("docs", {"allowed_tools": ["search", "fetch"], "needs_confirmation": ["search"]}),
        ("docs", {"allowed_tools": ["fetch"], "needs_confirmation": []}),
        ("docs", {"allowed_tools": ["search", "fetch"], "needs_confirmation": []}),
    ]
    assert mcp.asker.rows()[1:] == [
        ["search", texts().t("status.aktiv")],
        ["fetch", texts().t("status.aktiv")],
    ]


@pytest.mark.parametrize(
    ("language", "words"),
    [("en", ("active", "asks", "inactive")), ("de", ("aktiv", "fragt", "inaktiv"))],
)
def test_the_tool_rows_say_active_asks_inactive_in_both_languages(mcp, stub, language, words):
    """One press at a time: the row of the tool reads the three words of the
    catalogue Exe AI reads, and nothing says "on" or "off"."""
    mcp.texts = Texts(language)
    stub.mcp_servers = {"docs": server("docs")}
    shown: list[str] = []
    for presses in range(3):
        mcp.asker = Asking()
        # server 1 → edit → the tool "search" pressed `presses` times.
        mcp.asker.picks = [1, 0] + [1] * presses
        mcp.commands.run("/mcp")
        shown.append(mcp.asker.rows()[1][1])
        stub.mcp_servers = {"docs": server("docs")}
    assert shown == [words[0], words[1], words[2]]


def test_a_server_that_does_not_answer_shows_no_tools_to_switch(mcp, stub):
    stub.mcp_servers = {"docs": server("docs", laeuft=False, alle_werkzeuge=[])}
    mcp.asker.picks = [1, 0]
    mcp.commands.run("/mcp")
    assert len(mcp.asker.shown[-1]) == 1


def test_a_refusal_of_the_service_ends_the_edit_with_its_sentence(mcp, stub):
    stub.mcp_servers = {"docs": server("docs")}
    stub.refuse_mcp = "Not allowed."
    mcp.asker.picks = [1, 0, 0]
    mcp.commands.run("/mcp")
    assert mcp.renderer.errors == ["Not allowed."]


# --- Removing -------------------------------------------------------------------------------------


def test_remove_asks_and_a_yes_deletes_the_entry_with_no_sentence(mcp, stub, monkeypatch):
    stub.mcp_servers = {"docs": server("docs")}
    asked: list[str] = []
    monkeypatch.setattr(
        mcp_servers.servers, "ask", lambda ctx, question: asked.append(question) or True
    )
    mcp.asker.picks = [1, 2]
    mcp.commands.run("/mcp")
    assert asked == [texts().t("verbindungen.entfernen_frage", name="docs")]
    assert actions(stub, "delete") == [("docs", None)]
    assert mcp.renderer.notices == [] and mcp.renderer.errors == []


def test_remove_with_a_no_changes_nothing(mcp, stub, monkeypatch):
    stub.mcp_servers = {"docs": server("docs")}
    monkeypatch.setattr(mcp_servers.servers, "ask", lambda ctx, question: False)
    mcp.asker.picks = [1, 2]
    mcp.commands.run("/mcp")
    assert actions(stub, "delete") == []
    assert "docs" in stub.mcp_servers
