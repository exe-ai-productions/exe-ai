"""Helpers, and what each fixed agent is for.

The chat's model hands work to a helper with a goal and its context, with
no agent file behind it. A helper has the chat's tools minus asking the
user, the memory, schedules and further runs; its two limits stand in the
settings. A fixed agent keeps its own file, and the chat's model reads what
it is for beside its name.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from app import agentenfelder, agentenname, dokumentablage, grundprompt, helper
from app.agenten import Agentenverzeichnis, agent_aus_text
from app.api.v1 import auftraege
from app.api.v1.auftraege import _kind_starten, auftrag_anstossen
from app.i18n import t
from app.providers import MockProvider, Stueck, mock_endpunkt
from app.providers.base import Werkzeugaufruf
from app.tools import auftrag_werkzeug
from app.tools.registry import WerkzeugRegistry
from tests.conftest import provider_setzen
from tests.test_auftrag_werkzeug import StartRegistry, _antworten, _ereignisse

ENDINGS = {"fertig", "abgebrochen", "gescheitert", "unterbrochen"}


class NamedRegistry(StartRegistry):
    """The start_job registry of the chat tests, plus the names a helper's
    tool list is made from."""

    NAMES = ["ask_user", "cron_note", "cronjob", "list_dir", "memory_save",
             "read_file", "run_command", "start_job"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # The allowlists a job's run asked its offer for.
        self.job_lists = []

    def namen(self):
        return list(self.NAMES)

    def known_names(self):
        """What this stand could resolve: the names a helper's list is made
        from, plus the tools a job always gets."""
        from app.tools.registry import EVER_OFFERED

        return {*self.NAMES, *(e.tool.WERKZEUG_NAME for e in EVER_OFFERED)}

    def als_openai_werkzeuge(self, nur=None, **_options):
        if nur is not None:
            self.job_lists.append(set(nur))
        return [{"type": "function", "function": {"name": "start_job", "parameters": {}}}]


def _chat_starts(client, chat_id, arguments):
    client.app.state.werkzeuge = NamedRegistry(client, True, None)
    client.app.state.config.features.mcp = True
    # A helper runs with tools, so its model has to take them.
    client.app.state.discovery.zustaende["test"].endpunkt.capabilities.tool_calls = True
    provider_setzen(
        client,
        MockProvider(
            mock_endpunkt("test"),
            haeppchen=["Good."],
            werkzeugaufrufe=[Werkzeugaufruf(id="h1", name="start_job", argumente=arguments)],
        ),
    )
    answer = client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "hand it off"},
    )
    return _ereignisse(answer)


def _result(events):
    return next(e for e in events if e["typ"] == "tool_result")


def test_a_helper_starts_without_an_agent_file_with_goal_and_context(client, chat_id, caplog):
    with caplog.at_level("INFO", logger="app.api.v1.generierung"):
        events = _chat_starts(
            client, chat_id,
            {"task": "Collect the notes.", "context": "They lie in the notes folder."},
        )

    result = _result(events)
    assert not result["fehlgeschlagen"], result["text"]
    assert "agent 'helper'" in result["text"]
    jobs = client.get("/api/v1/jobs").json()
    assert [job["agent"] for job in jobs] == ["helper"]
    assert jobs[0]["chat_id"] == chat_id
    assert jobs[0]["task"] == "Collect the notes.\n\nContext:\nThey lie in the notes folder."
    assert any("Helper " in r.getMessage() and "started from chat" in r.getMessage()
               for r in caplog.records)


def test_a_helper_lacks_questions_memory_schedules_and_further_runs(client):
    repos = client.app.state.repositories

    agent = helper.helper_agent(repos, NamedRegistry())

    assert agent.name == helper.HELPER_NAME
    assert agent.werkzeuge == ["list_dir", "read_file", "run_command"]
    assert agent.runden == helper.STEPS_DEFAULT == 250
    assert helper.at_once(repos) == helper.AT_ONCE_DEFAULT == 10


def test_the_limits_stand_in_the_settings(client):
    repos = client.app.state.repositories
    for key, value in ((helper.AT_ONCE_KEY, 2), (helper.STEPS_KEY, 40)):
        answer = client.put(f"/api/v1/settings/global/{key}", json={"wert": value})
        assert answer.status_code == 200, answer.text

    assert helper.at_once(repos) == 2
    assert helper.helper_agent(repos, NamedRegistry()).runden == 40


def test_a_helper_over_the_limit_is_refused(client, chat_id):
    repos = client.app.state.repositories
    repos.einstellungen.setzen("global", helper.AT_ONCE_KEY, 1)
    repos.auftraege.erstellen(
        user_id="standard", agent=helper.HELPER_NAME, auftrag="A", zustand="laeuft"
    )

    result = _result(_chat_starts(client, chat_id, {"task": "Collect the notes."}))

    assert result["fehlgeschlagen"]
    # The window's copy, in the language the test service is set to.
    language = client.app.state.config.app.language
    assert t("jobs.helper_limit", language, running=1, limit=1) in result["text"]
    assert len(client.get("/api/v1/jobs").json()) == 1


def test_the_chat_model_reads_what_each_agent_is_for():
    agents = Agentenverzeichnis({
        "bote": agent_aus_text(
            "bote", '---\ndescription: "Delivers parcels, letters and notes."\n---\n\nGo.\n'
        ),
        "leser": agent_aus_text("leser", "---\ntools: []\n---\n\nRead.\n"),
    })

    chat = auftrag_werkzeug.werkzeug_beschreibung(agents, helpers=True)
    job = auftrag_werkzeug.werkzeug_beschreibung(agents)

    field = chat.schema["properties"]["agent"]["description"]
    assert "\n- bote: Delivers parcels, letters and notes.\n- leser (answers only, no tools)." in field
    assert "Omit it to start a helper." in field
    assert chat.schema["required"] == ["task"]
    assert "Leave out agent to start a helper" in chat.beschreibung
    # A job may not start a helper, and is not told it could.
    assert job.schema["required"] == ["agent", "task"]
    assert "helper" not in job.beschreibung
    assert "helper" not in job.schema["properties"]["agent"]["description"]


def test_a_wrapped_description_stays_one_line():
    agents = Agentenverzeichnis({
        "bote": agent_aus_text("bote", '---\ndescription: |\n  Delivers parcels;\n  and notes.\n---\n\nGo.\n'),
    })

    assert agentenname.auswahl_satz(agents) == "\n- bote: Delivers parcels; and notes."


def test_without_descriptions_the_names_stay_one_list():
    """The silence probe for the separator: no description, no change."""
    agents = Agentenverzeichnis({
        "bote": agent_aus_text("bote", "---\n---\n\nGo.\n"),
        "leser": agent_aus_text("leser", "---\n---\n\nRead.\n"),
    })

    assert agentenname.auswahl_satz(agents) == "bote, leser"


def test_a_fixed_agent_keeps_its_own_tools(client):
    """The silence probe: a name that is not the helpers' is a file's agent,
    with the tools its file names."""
    repos = client.app.state.repositories
    agents = Agentenverzeichnis({
        "bote": agent_aus_text("bote", "---\ntools:\n  - read_file\n---\n\nGo.\n"),
    })

    agent = helper.agent_named("bote", agents, repos, NamedRegistry())

    assert agent.werkzeuge == ["read_file"]
    assert helper.agent_named("helper", agents, repos, NamedRegistry()).name == "helper"
    assert helper.agent_named("nobody", agents, repos, NamedRegistry()) is None


@pytest.mark.parametrize("text", ["yes", "42", "Reads mail, sorts it: urgent first."])
def test_the_form_writes_a_description_that_reads_back_as_written(text):
    file_text = agentenfelder.neu_bauen({"description": text}, "Go.")

    assert agent_aus_text("bote", file_text).description == text


def test_no_agent_file_may_take_the_helpers_name(client):
    folder = Path(client.app.state.config.app.agenten_verzeichnis)

    answer = client.put(
        "/api/v1/agents/helper/fields", json={"prompt": "Go.", "description": "x"}
    )

    assert answer.status_code == 422
    assert not (folder / "helper.md").exists()
    # A file put there by hand is out of play, and the editor says why.
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "helper.md").write_text("---\n---\n\nGo.\n", encoding="utf-8")
    assert "helper" not in [a["name"] for a in client.get("/api/v1/agents").json()]
    listed = {e["name"]: e["kaputt"] for e in client.get("/api/v1/agent-files").json()}
    assert "kann nicht als Agentenname verwendet werden" in listed["helper"]


def test_a_helper_starts_nothing_and_a_run_starts_no_helper(client):
    repos = client.app.state.repositories
    state = client.app.state
    helper_run = repos.auftraege.erstellen(
        user_id="standard", agent=helper.HELPER_NAME, auftrag="A", zustand="laeuft"
    )
    fixed_run = repos.auftraege.erstellen(
        user_id="standard", agent="bote", auftrag="B", zustand="laeuft"
    )
    common = dict(
        config=state.config, repositories=repos, discovery=state.discovery,
        generierungen=state.generierungen, registry=None, user_id="standard",
        sprache="en", protokoll=lambda *_: None,
    )

    under_helper = _kind_starten(
        aufruf=Werkzeugaufruf(id="k1", name="start_job",
                              argumente={"agent": "bote", "task": "Go."}),
        eltern_id=helper_run.id, **common,
    )
    helper_under_run = _kind_starten(
        aufruf=Werkzeugaufruf(id="k2", name="start_job", argumente={"task": "Go."}),
        eltern_id=fixed_run.id, **common,
    )

    assert under_helper == (helper.NO_FURTHER_RUNS, True)
    assert helper_under_run == (helper.CHAT_ONLY, True)


class HelperAsks(MockProvider):
    """The chat hands work to a helper; the helper tries to ask the user and
    then reports whatever it was told instead."""

    async def streamen(self, anfrage):
        self.letzte_anfrage = anfrage
        self.alle_anfragen.append(anfrage)
        is_helper_run = any(
            n.role == "system" and helper.PROMPT[:30] in (n.content or "")
            for n in anfrage.nachrichten
        )
        told = [n for n in anfrage.nachrichten if n.role == "tool"]
        if is_helper_run and not told:
            yield Stueck("tool_call", werkzeugaufrufe=[Werkzeugaufruf(
                id="q1", name="ask_user",
                argumente={"question": "Which file?", "options": [{"label": "A"}]},
            )])
            return
        if is_helper_run:
            yield Stueck("content", text=f"Told: {told[-1].content}")
            return
        if not told:
            yield Stueck("tool_call", werkzeugaufrufe=[Werkzeugaufruf(
                id="s1", name="start_job", argumente={"task": "Pick the file."},
            )])
            return
        yield Stueck("content", text="Noted.")


class ChatRegistry(WerkzeugRegistry):
    """A real registry — so a job's list is built for real — that says yes
    to the start window on its own, as the window tests do."""

    def __init__(self, client, agent_places):
        super().__init__([], shell_an=True, agenten_orte=agent_places)
        self._client = client
        self._armed = False

    def braucht_bestaetigung(self, name, argumente=None, ordner=None):
        if name == auftrag_werkzeug.WERKZEUG_NAME:
            if not self._armed:
                _antworten(self._client, True)
                self._armed = True
            return False
        return super().braucht_bestaetigung(name, argumente, ordner)


def test_a_helper_that_asks_is_told_to_report_instead(config, client, chat_id):
    client.app.state.werkzeuge = ChatRegistry(client, config.agentenverzeichnisse)
    client.app.state.config.features.mcp = True
    client.app.state.discovery.zustaende["test"].endpunkt.capabilities.tool_calls = True
    provider_setzen(client, HelperAsks(mock_endpunkt("test")))

    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "hand it off"},
    )

    deadline = time.time() + 8
    job = None
    while time.time() < deadline:
        jobs = client.get("/api/v1/jobs").json()
        job = jobs[0] if jobs else None
        if job and job["state"] in ENDINGS:
            break
        time.sleep(0.05)
    assert job is not None and job["agent"] == "helper"
    assert job["state"] == "fertig", job
    assert job["question"] is None
    assert job["result"].startswith("Told: A helper cannot ask the user questions.")


def test_a_chat_is_offered_helpers_and_a_job_is_not(config):
    registry = WerkzeugRegistry([], shell_an=True, agenten_orte=config.agentenverzeichnisse)

    def start_job_schema(**options):
        offer = registry.als_openai_werkzeuge(**options)
        return next(w for w in offer if w["function"]["name"] == "start_job")["function"]

    assert start_job_schema()["parameters"]["required"] == ["task"]
    assert start_job_schema(for_job=True, helpers=False)["parameters"]["required"] == [
        "agent", "task"
    ]


def test_a_helpers_continuation_fires_while_another_helper_works(client):
    """Handed-on work carries the helpers' shared name; it waits for its
    own run, not for every helper at work."""
    from tests.test_cronablauf import MORGEN_13, auftraege_von, pruefen

    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    repos = client.app.state.repositories
    repos.auftraege.erstellen(
        user_id="standard", agent=helper.HELPER_NAME, auftrag="another", zustand="laeuft"
    )
    repos.cronjobs.erstellen(
        agent=helper.HELPER_NAME, task="carry on", zeitplan="12:00", herkunft="agent"
    )

    pruefen(client, MORGEN_13)

    assert len(auftraege_von(client, helper.HELPER_NAME)) == 2


def test_a_helper_leaves_out_what_its_chat_switched_off(client, chat_id):
    repos = client.app.state.repositories
    repos.einstellungen.setzen(
        f"chat:{chat_id}", "werkzeuge_aus", ["run_command", "deliver_file"]
    )

    _chat_starts(client, chat_id, {"task": "Collect the notes."})

    registry = client.app.state.werkzeuge
    deadline = time.time() + 8
    while time.time() < deadline and not registry.job_lists:
        time.sleep(0.05)
    assert registry.job_lists, "the helper's run never built its offer"
    # The shelf and the clock are added to every run's list, and the shelf
    # still goes where the chat switched it off: the narrowing comes last.
    assert registry.job_lists[0] == {
        "list_dir", "read_file", "get_current_time",
    }


def test_the_limit_holds_where_the_run_is_made(client):
    """Two windows open at once both passed the check before them; the
    second confirmation must still be refused."""
    from fastapi import HTTPException

    from app.api.v1.auftraege import auftrag_anstossen

    repos = client.app.state.repositories
    state = client.app.state
    repos.einstellungen.setzen("global", helper.AT_ONCE_KEY, 1)
    repos.auftraege.erstellen(
        user_id="standard", agent=helper.HELPER_NAME, auftrag="A", zustand="laeuft"
    )

    with pytest.raises(HTTPException) as refused:
        auftrag_anstossen(
            config=state.config, repositories=repos, discovery=state.discovery,
            generierungen=state.generierungen, registry=None,
            agent=helper.helper_agent(repos, None), task="Go.", endpoint_id=None,
            user_id="standard", sprache="en",
        )

    assert refused.value.status_code == 409
    assert len(repos.auftraege.auflisten(user_id="standard")) == 1


def test_a_helper_is_refused_what_it_is_not_offered_and_a_fixed_agent_is_not():
    """The bolt at execution: a call the model makes anyway does not run,
    whatever the rule file says."""
    for tool in ("memory_save", "cronjob", "cron_note"):
        assert helper.refused_call("helper", tool) == helper.NOT_FOR_HELPERS
    assert helper.refused_call("helper", "ask_user") == helper.NO_QUESTIONS
    assert helper.refused_call("helper", "start_job") == helper.NO_FURTHER_RUNS
    assert helper.refused_call("helper", "read_file") is None
    assert helper.refused_call("bote", "memory_save") is None


@pytest.mark.parametrize(
    ("line", "expected"),
    [("description: 42", "42"), ("description: [a, b]", None), ("description:", None)],
)
def test_an_odd_description_keeps_the_agent_in_play(line, expected):
    agent = agent_aus_text("bote", f"---\n{line}\n---\n\nGo.\n")

    assert agent.description == expected


# --- a run a chat sent off works in that chat's folders ----------------------


class PromptSeen:
    """Stands in front of the prompt builder as the jobs module sees it, and
    keeps what each run's prompt was built from beside the text it became."""

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        return getattr(grundprompt, name)

    def bauen(self, **parts):
        text = grundprompt.bauen(**parts)
        self.calls.append({**parts, "text": text})
        return text


@pytest.fixture
def run_prompts(monkeypatch):
    seen = PromptSeen()
    monkeypatch.setattr(auftraege, "grundprompt", seen)
    return seen.calls


def _run_system_message(client) -> str:
    """The system message of the run the chat sent off: the request whose
    message carries the run's own section, not the chat's."""
    head = grundprompt.AGENTENLAUF.split("{")[0].strip()
    provider = client.app.state.discovery.zustaende["test"].provider
    texts = [
        m.content
        for request in provider.alle_anfragen
        for m in request.nachrichten
        if m.role == "system" and head in m.content
    ]
    assert texts, "no request of the run reached the model"
    return texts[-1]


def _places(client, chat_id):
    """The chat's own folder, the dock and the picture folder."""
    config = client.app.state.config
    own = str(dokumentablage.chatordner(config.datenverzeichnis, chat_id))
    dock, pictures = dokumentablage.program_folders(config)
    return own, dock, pictures


async def _runs_at_rest(client):
    """Lets a run started outside a request come to rest before the test
    ends and the service under it shuts down."""
    for _ in range(160):
        if not client.app.state.generierungen.laufende():
            return
        await asyncio.sleep(0.05)


def _fixed_agent_with_folder(config, folder):
    agents = Path(config.app.agenten_verzeichnis)
    agents.mkdir(parents=True, exist_ok=True)
    (agents / "bote.md").write_text(
        f"---\nmodel: test\nmax_rounds: 1\ntools: []\nfolders:\n  - {folder}\n---\n\nGo.\n",
        encoding="utf-8",
    )


async def test_a_helper_of_a_chat_that_shares_nothing_works_in_the_chats_own_folder(
    client, chat_id, run_prompts,
):
    """The chat's own folder first, the dock behind it — so a relative path
    lands where it lands in the chat. The start itself makes no folder and
    writes no folder notes into it."""
    own, dock, pictures = _places(client, chat_id)

    result = _result(_chat_starts(client, chat_id, {"task": "Write the note."}))
    await _runs_at_rest(client)

    assert not result["fehlgeschlagen"], result["text"]
    (prompt,) = run_prompts
    assert prompt["ordner"] == [own, dock, pictures]
    assert prompt["own_folder"] == own
    assert prompt["dock"] == dock
    # The base prompt leaves the paragraph out; the run's system message ends
    # on it, behind everything that is the same for every run.
    assert "has a folder of its own" not in prompt["text"]
    system = _run_system_message(client)
    assert system.endswith(
        f"This conversation has a folder of its own, where its uploads are kept and \
where you work while nothing is shared:\n\n- {own}\n\n"
        "Relative paths resolve against this folder."
    )
    assert "shared these folders" not in system
    assert not Path(own).exists()
    assert prompt["ordnerwissen_pflegen"] is False


async def test_a_helper_of_a_chat_with_shared_folders_gets_them_first(
    client, chat_id, run_prompts, tmp_path,
):
    """The shared folders, then the chat's own once it exists, the dock
    last; the own one is named as the chat's own, not as a share, and gets
    no folder notes."""
    shared = tmp_path / "shared"
    shared.mkdir()
    client.patch(f"/api/v1/chats/{chat_id}", json={"working_dirs": [str(shared)]})
    own, dock, pictures = _places(client, chat_id)
    Path(own).mkdir(parents=True)

    result = _result(_chat_starts(client, chat_id, {"task": "Write the note."}))
    await _runs_at_rest(client)

    assert not result["fehlgeschlagen"], result["text"]
    (prompt,) = run_prompts
    assert prompt["ordner"] == [str(shared.resolve()), own, dock, pictures]
    assert prompt["own_folder"] == own
    assert "also has a folder of its own" not in prompt["text"]
    assert _run_system_message(client).endswith(
        f"This conversation also has a folder of its own, where its uploads are kept:\
\n\n- {own}"
    )
    assert not (Path(own) / "exe.md").exists()
    assert (shared / "exe.md").exists()


def test_a_shared_folder_alone_stays_alone_while_the_chat_has_no_own_folder_yet(
    client, chat_id, run_prompts, tmp_path,
):
    shared = tmp_path / "shared"
    shared.mkdir()
    client.patch(f"/api/v1/chats/{chat_id}", json={"working_dirs": [str(shared)]})
    _, dock, pictures = _places(client, chat_id)

    _chat_starts(client, chat_id, {"task": "Write the note."})

    (prompt,) = run_prompts
    assert prompt["ordner"] == [str(shared.resolve()), dock, pictures]
    assert prompt.get("own_folder") is None


def test_a_fixed_agent_with_folders_of_its_own_keeps_them(
    client, chat_id, config, run_prompts, tmp_path,
):
    """The silence probe: a chat that shares nothing leaves an agent the
    folders its file names — the chat's own folder is not put in front."""
    agents_folder = tmp_path / "agents-work"
    agents_folder.mkdir()
    _fixed_agent_with_folder(config, agents_folder)
    own, dock, pictures = _places(client, chat_id)

    result = _result(
        _chat_starts(client, chat_id, {"agent": "bote", "task": "Collect the notes."})
    )

    assert not result["fehlgeschlagen"], result["text"]
    (prompt,) = run_prompts
    assert prompt["ordner"] == [str(agents_folder), dock, pictures]
    assert prompt.get("own_folder") is None
    assert own not in prompt["text"]


async def test_a_run_under_a_run_keeps_the_agents_folders(
    client, chat_id, config, run_prompts, tmp_path,
):
    """The silence probe: only the run the chat sent off takes the chat's
    folders; a run it starts itself works in its agent's own."""
    agents_folder = tmp_path / "agents-work"
    agents_folder.mkdir()
    _fixed_agent_with_folder(config, agents_folder)
    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    repos, state = client.app.state.repositories, client.app.state
    parent = repos.auftraege.erstellen(
        user_id="standard", agent="bote", auftrag="A", zustand="laeuft", chat_id=chat_id,
    )
    own, dock, pictures = _places(client, chat_id)

    _, failed = _kind_starten(
        aufruf=Werkzeugaufruf(id="k1", name="start_job",
                              argumente={"agent": "bote", "task": "Go."}),
        eltern_id=parent.id, config=state.config, repositories=repos,
        discovery=state.discovery, generierungen=state.generierungen, registry=None,
        user_id="standard", sprache="en", protokoll=lambda *_: None,
    )

    await _runs_at_rest(client)
    assert not failed
    (prompt,) = run_prompts
    assert prompt["ordner"] == [str(agents_folder), dock, pictures]
    assert prompt.get("own_folder") is None


async def test_a_helpers_continuation_goes_on_in_the_chats_own_folder(client, chat_id, run_prompts):
    """Handed-on work gets its folders the way a new start would: the chat's
    own folder first, where the chat shares nothing."""
    from app.zwischenstand import kettenfelder

    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    client.app.state.discovery.zustaende["test"].endpunkt.capabilities.tool_calls = True
    repos, state = client.app.state.repositories, client.app.state
    first = repos.auftraege.erstellen(
        user_id="standard", agent=helper.HELPER_NAME, auftrag="A", zustand="fertig",
        chat_id=chat_id,
    )
    entry = repos.cronjobs.erstellen(
        agent=helper.HELPER_NAME, task="carry on", zeitplan="* * * * *", herkunft="agent",
        **kettenfelder(None, first.id),
    )
    own, dock, pictures = _places(client, chat_id)

    auftrag_anstossen(
        config=state.config, repositories=repos, discovery=state.discovery,
        generierungen=state.generierungen, registry=NamedRegistry(),
        agent=helper.helper_agent(repos, NamedRegistry()), task="carry on",
        endpoint_id=None, user_id="standard", sprache="en", cronjob_id=entry.id,
    )

    await _runs_at_rest(client)
    (prompt,) = run_prompts
    assert prompt["ordner"] == [own, dock, pictures]
    assert prompt["own_folder"] == own


class HelperWrites(MockProvider):
    """The chat hands work to a helper; the helper writes a file by a
    relative path and reports what the tool told it."""

    async def streamen(self, anfrage):
        self.letzte_anfrage = anfrage
        self.alle_anfragen.append(anfrage)
        is_helper_run = any(
            n.role == "system" and helper.PROMPT[:30] in (n.content or "")
            for n in anfrage.nachrichten
        )
        told = [n for n in anfrage.nachrichten if n.role == "tool"]
        if is_helper_run and not told:
            yield Stueck("tool_call", werkzeugaufrufe=[Werkzeugaufruf(
                id="w1", name="write_file",
                argumente={"path": "note.txt", "content": "written by the helper\n"},
            )])
            return
        if is_helper_run:
            yield Stueck("content", text=f"Told: {told[-1].content}")
            return
        if not told:
            yield Stueck("tool_call", werkzeugaufrufe=[Werkzeugaufruf(
                id="s1", name="start_job", argumente={"task": "Write the note."},
            )])
            return
        yield Stueck("content", text="Noted.")


def test_a_relative_path_of_the_helper_lands_in_the_chats_own_folder(config, client, chat_id):
    """End to end, with the real tools: the file is written into the chat's
    own folder, which the call that runs makes, and nothing lands on the
    dock."""
    from app.tools import create_folder

    registry = ChatRegistry(client, config.agentenverzeichnisse)
    # What tells the file tools where the data folder is, as the service's
    # own registry carries it: without it no chat folder is made.
    registry.folder_share = create_folder.ChatFolderShare(
        client.app.state.repositories, config.datenverzeichnis
    )
    client.app.state.werkzeuge = registry
    client.app.state.config.features.mcp = True
    client.app.state.discovery.zustaende["test"].endpunkt.capabilities.tool_calls = True
    provider_setzen(client, HelperWrites(mock_endpunkt("test")))
    own, dock, _ = _places(client, chat_id)

    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "hand it off"},
    )

    deadline = time.time() + 8
    job = None
    while time.time() < deadline:
        jobs = client.get("/api/v1/jobs").json()
        job = jobs[0] if jobs else None
        if job and job["state"] in ENDINGS:
            break
        time.sleep(0.05)
    assert job is not None and job["state"] == "fertig", job
    assert job["result"].startswith(f"Told: Created {Path(own).resolve() / 'note.txt'}"), job["result"]
    assert (Path(own) / "note.txt").read_text(encoding="utf-8") == "written by the helper\n"
    assert not (Path(dock) / "note.txt").exists()
