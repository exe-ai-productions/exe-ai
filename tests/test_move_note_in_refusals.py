"""A refused file call aimed under a moved folder is told where it went.

The sentence in the system message alone was measured not to be enough: a
model calling the old path from its own history read only the refusal of
that call — outside the shared folders, does not exist — and gave up on the
file. Each refusal of the program now carries the same move sentence, in a
chat and in a job run alike. A call the user declined never does: the no
stands as it is. Without a move, for a path that does not lie under the old
place, or in a job whose folders do not hold the new place, the refusals
stay word for word as they were.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import time
from pathlib import Path

import pytest

from app import berechtigungen, dokumentablage
from app.agenten import agenten_laden
from app.api.v1 import generierung
from app.api.v1.auftraege import auftrag_anstossen
from app.i18n import t
from app.providers import MockProvider, mock_endpunkt
from app.providers.base import Werkzeugaufruf
from app.tools import grenzen
from app.tools.mcp_client import MCPWerkzeug
from app.tools.registry import WerkzeugRegistry, WerkzeugVerboten
from tests.conftest import provider_setzen, wakes_settled

END_STATES = {"fertig", "abgebrochen", "gescheitert", "unterbrochen"}


def _move_folder(client, chat_id: str, tmp_path: Path) -> tuple[Path, Path]:
    """Shares ``alt``, moves it on disk and re-chooses it at ``neu`` — the
    way the window does it. Returns both, resolved."""
    old = tmp_path / "alt"
    old.mkdir()
    (old / "notiz.txt").write_text("x", encoding="utf-8")
    client.patch(f"/api/v1/chats/{chat_id}", json={"working_dirs": [str(old)]})
    new = tmp_path / "platte" / "neu"
    new.parent.mkdir()
    shutil.move(str(old), str(new))
    client.patch(
        f"/api/v1/chats/{chat_id}",
        json={
            "working_dirs": [str(new)],
            "ordner_ersatz": {"alt": str(old.resolve()), "neu": str(new)},
        },
    )
    return old.resolve(), new.resolve()


def _share_only(client, chat_id: str, tmp_path: Path) -> tuple[Path, Path]:
    """The same two places without a move: ``neu`` is shared, ``alt`` never
    was re-chosen."""
    old = tmp_path / "alt"
    new = tmp_path / "platte" / "neu"
    new.mkdir(parents=True)
    client.patch(f"/api/v1/chats/{chat_id}", json={"working_dirs": [str(new)]})
    return old.resolve(), new.resolve()


def _sentence(old: Path, new: Path) -> str:
    return (
        f"The shared folder '{old}' has moved to '{new}'. Resolve paths under "
        "the old location against the new location."
    )


# A refusal about the TOOL, not its path: a per-tool rule, a tool not
# enabled, a tool the agent was not given.
TOOL_REFUSAL = "Tool 'read_file' is not enabled."


# --- The chat ----------------------------------------------------------


class _ChatRegistry:
    """``read_file`` that is refused one of three ways."""

    def __init__(self, kind: str, client) -> None:
        self.kind = kind
        self.client = client

    def als_openai_werkzeuge(self, nur=None, shell_zeitgrenze=None, **_options):
        return [{"type": "function", "function": {"name": "read_file", "parameters": {}}}]

    def braucht_bestaetigung(self, name, argumente=None, ordner=None):
        if self.kind != "declined":
            return False
        _decline_later(self.client)
        return True

    def server_von(self, name):
        return ""

    def bestaetigungsgrund(self, name, argumente=None, ordner=None):
        return None

    async def ausfuehren(self, name, argumente, bild_senke=None, ordner=None,
                         chat_id=None, shell_zeitgrenze=None, **_rest):
        path = str(argumente.get("path"))
        if self.kind == "tool":
            raise WerkzeugVerboten(TOOL_REFUSAL)
        if self.kind == "outside":
            raise WerkzeugVerboten(
                berechtigungen._ausserhalb_grund(path, ordner or []), about_path=True
            )
        if self.kind == "missing":
            raise WerkzeugVerboten(
                grenzen.missing(Path(path), ordner or [], None), about_path=True
            )
        if self.kind == "long":
            raise WerkzeugVerboten(
                "x" * (generierung.WERKZEUGERGEBNIS_GRENZE + 500), about_path=True
            )
        raise AssertionError("a declined call must not run")


def _decline_later(client) -> None:
    manager = client.app.state.generierungen

    def tick():
        for running in manager.laufende():
            for call_id in list(running.bestaetigungen):
                manager.bestaetigen(running.id, call_id, False)
                return
        asyncio.get_running_loop().call_later(0.01, tick)

    asyncio.get_running_loop().call_later(0.01, tick)


def _chat_run(client, chat_id: str, kind: str | None, path: Path):
    """One refused ``read_file`` in a chat: the provider and the stream."""
    client.app.state.werkzeuge = _ChatRegistry(kind, client) if kind else None
    client.app.state.config.features.mcp = True
    provider = provider_setzen(
        client,
        MockProvider(
            mock_endpunkt("test"),
            haeppchen=["fertig"],
            werkzeugaufrufe=[
                Werkzeugaufruf(id="a1", name="read_file", argumente={"path": str(path)})
            ],
        ),
    )
    response = client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "lies"},
    )
    return provider, response


def _model_copy(provider, call_id: str) -> str:
    return next(
        n.content for n in provider.letzte_anfrage.nachrichten
        if n.role == "tool" and n.werkzeugaufruf_id == call_id
    )


def _chat_refusal(client, chat_id: str, kind: str | None, path: Path) -> str:
    """What the model read as the result of one refused ``read_file``."""
    provider, _antwort = _chat_run(client, chat_id, kind, path)
    return _model_copy(provider, "a1")


def _unchanged(kind: str, path: Path, new: Path, client=None) -> str:
    """Each refusal word for word as it reads without a move. A chat's
    folders end with the dock and the picture folder, which every run sees."""
    if kind == "outside":
        program = dokumentablage.program_folders(client.app.state.config) if client else []
        return berechtigungen._ausserhalb_grund(str(path), [str(new), *program])
    if kind == "missing":
        return grenzen.missing(path, [str(new)], None)
    return t("fehler.werkzeug_abgelehnt", "en", name="read_file")


@pytest.mark.parametrize("kind", ["outside", "missing"])
def test_chat_refusal_at_the_old_path_names_the_new_place(client, chat_id, tmp_path, kind):
    old, new = _move_folder(client, chat_id, tmp_path)
    path = old / "notiz.txt"

    content_ = _chat_refusal(client, chat_id, kind, path)

    assert content_ == f"{_unchanged(kind, path, new, client)}\n{_sentence(old, new)}"


def test_a_call_the_user_declined_gets_no_move_sentence(client, chat_id, tmp_path):
    """The user's no stands as it is: no hint where the same file lies,
    which would only invite the model around it."""
    old, new = _move_folder(client, chat_id, tmp_path)
    path = old / "notiz.txt"

    content_ = _chat_refusal(client, chat_id, "declined", path)

    assert content_ == _unchanged("declined", path, new, client)


@pytest.mark.parametrize("kind", ["outside", "declined", "missing"])
def test_chat_without_a_move_keeps_the_refusal(client, chat_id, tmp_path, kind):
    """Schweigeprobe: no move, no sentence — the refusal is unchanged."""
    old, new = _share_only(client, chat_id, tmp_path)
    path = old / "notiz.txt"

    assert _chat_refusal(client, chat_id, kind, path) == _unchanged(kind, path, new, client)


@pytest.mark.parametrize("kind", ["outside", "declined", "missing"])
def test_chat_path_outside_the_old_place_gets_no_sentence(
    client, chat_id, tmp_path, kind
):
    """Schweigeprobe: a move is recorded, but this call aims elsewhere."""
    _old, new = _move_folder(client, chat_id, tmp_path)
    path = (tmp_path / "anderswo" / "notiz.txt").resolve()

    assert _chat_refusal(client, chat_id, kind, path) == _unchanged(kind, path, new, client)


def test_chat_window_keeps_its_refusal(client, chat_id, tmp_path):
    """The sentence is the model's: the window's result stays as it was."""
    old, new = _move_folder(client, chat_id, tmp_path)
    path = old / "notiz.txt"

    _provider, response = _chat_run(client, chat_id, "outside", path)
    results = [
        json.loads(z[5:].strip())
        for z in response.text.splitlines()
        if z.startswith("data:")
    ]
    window = next(e for e in results if e["typ"] == "tool_result")

    assert window["text"] == _unchanged("outside", path, new, client)


def test_chat_sentence_is_appended_after_the_cut(client, chat_id, tmp_path):
    """A refusal longer than the ceiling is cut first — the sentence after
    it is never cut off."""
    old, new = _move_folder(client, chat_id, tmp_path)

    content_ = _chat_refusal(client, chat_id, "long", old / "notiz.txt")

    assert content_ == "x" * generierung.WERKZEUGERGEBNIS_GRENZE + f"\n{_sentence(old, new)}"


def test_chat_without_tools_gets_no_sentence(client, chat_id, tmp_path):
    """Schweigeprobe: "tools are turned off" is no matter of a moved folder."""
    old, _neu = _move_folder(client, chat_id, tmp_path)

    content_ = _chat_refusal(client, chat_id, None, old / "notiz.txt")

    assert content_ == t("fehler.werkzeug_verboten", "en", name="read_file")


# --- The job -----------------------------------------------------------


class _JobRegistry(WerkzeugRegistry):
    """``read_file`` only, refused the way the gate or the tool refuses it."""

    def __init__(self, kind: str) -> None:
        super().__init__([])
        self.kind = kind
        entry = (None, MCPWerkzeug(name="read_file", beschreibung="liest"), False)
        self._werkzeuge = {"read_file": entry}  # type: ignore[dict-item]

    async def ausfuehren(self, name, argumente, bild_senke=None, ordner=None,
                         chat_id=None, herkunft="chat", agent=None, **_rest):
        path = str(argumente.get("path"))
        if self.kind == "tool":
            raise WerkzeugVerboten(TOOL_REFUSAL)
        if self.kind == "outside":
            raise WerkzeugVerboten(
                berechtigungen._ausserhalb_grund(path, ordner or []), about_path=True
            )
        raise WerkzeugVerboten(
            grenzen.missing(Path(path), ordner or [], None), about_path=True
        )


async def _job_run(
    client, config, chat_id: str, kind: str | None, path: Path, folders: list[str] | None = None
):
    """One job run with one refused ``read_file``: the provider and the job."""
    agents_dir = Path(config.app.agenten_verzeichnis)
    agents_dir.mkdir(parents=True, exist_ok=True)
    (agents_dir / "recherche.md").write_text(
        "---\nmodel: test\n---\n\nResearch.\n", encoding="utf-8"
    )
    client.app.state.config.features.mcp = True
    client.app.state.discovery.zustaende["test"].endpunkt.capabilities.tool_calls = True
    provider = provider_setzen(
        client,
        MockProvider(
            mock_endpunkt("test"),
            haeppchen=["fertig"],
            werkzeugaufrufe=[
                Werkzeugaufruf(id="w1", name="read_file", argumente={"path": str(path)})
            ],
        ),
    )
    repositories = client.app.state.repositories
    job = auftrag_anstossen(
        config=client.app.state.config,
        repositories=repositories,
        discovery=client.app.state.discovery,
        generierungen=client.app.state.generierungen,
        registry=_JobRegistry(kind) if kind else None,
        agent=agenten_laden(agents_dir)["recherche"],
        task="Los",
        endpoint_id=None,
        user_id="standard",
        sprache="de",
        chat_id=chat_id,
        ordner=folders,
    )
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        current = repositories.auftraege.holen(job.id)
        if current is not None and current.zustand in END_STATES:
            break
        await asyncio.sleep(0.01)
    else:
        raise AssertionError("the job reached no end state")
    await wakes_settled()
    return provider, job


async def _job_refusal(
    client, config, chat_id: str, kind: str | None, path: Path, folders: list[str] | None = None
) -> str:
    """What a job's model read for one refused ``read_file``."""
    provider, _auftrag = await _job_run(client, config, chat_id, kind, path, folders)
    return _model_copy(provider, "w1")


@pytest.mark.parametrize("kind", ["outside", "missing"])
async def test_job_refusal_at_the_old_path_names_the_new_place(
    client, config, chat_id, tmp_path, kind
):
    old, new = _move_folder(client, chat_id, tmp_path)
    path = old / "notiz.txt"

    content_ = await _job_refusal(client, config, chat_id, kind, path, [str(new)])

    assert content_.endswith(f"\n{_sentence(old, new)}")
    assert content_.startswith(f"'{path}'")


@pytest.mark.parametrize("kind", ["outside", "missing"])
async def test_a_job_whose_folders_lack_the_new_place_gets_no_move_sentence(
    client, config, chat_id, tmp_path, kind
):
    """The new place is not among the job's folders: a sentence sending the
    model there would only cost another refused call."""
    old, _neu = _move_folder(client, chat_id, tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    content_ = await _job_refusal(
        client, config, chat_id, kind, old / "notiz.txt", [str(elsewhere)]
    )

    assert "now lives at" not in content_


@pytest.mark.parametrize("kind", ["outside", "missing"])
async def test_job_without_a_move_keeps_the_refusal(
    client, config, chat_id, tmp_path, kind
):
    """Schweigeprobe: the chat of this work recorded no move."""
    old, _neu = _share_only(client, chat_id, tmp_path)
    path = old / "notiz.txt"

    content_ = await _job_refusal(client, config, chat_id, kind, path)

    assert "now lives at" not in content_


@pytest.mark.parametrize("kind", ["outside", "missing"])
async def test_job_path_outside_the_old_place_gets_no_sentence(
    client, config, chat_id, tmp_path, kind
):
    _move_folder(client, chat_id, tmp_path)
    path = (tmp_path / "anderswo" / "notiz.txt").resolve()

    content_ = await _job_refusal(client, config, chat_id, kind, path)

    assert "now lives at" not in content_


async def test_job_transcript_keeps_its_refusal(client, config, chat_id, tmp_path):
    """As in the chat: the model's copy carries the sentence, the job's
    transcript keeps the refusal as the tool gave it."""
    old, new = _move_folder(client, chat_id, tmp_path)

    _provider, job = await _job_run(
        client, config, chat_id, "outside", old / "notiz.txt", [str(new)]
    )
    steps = client.app.state.repositories.auftraege.schritte(job.id)
    results = [s.inhalt for s in steps if s.typ == "tool_result"]

    assert results
    assert all("now lives at" not in content_ for content_ in results)


async def test_job_without_tools_gets_no_sentence(client, config, chat_id, tmp_path):
    """Schweigeprobe: a run without tools is refused for that alone."""
    old, _neu = _move_folder(client, chat_id, tmp_path)

    content_ = await _job_refusal(client, config, chat_id, None, old / "notiz.txt")

    assert content_ == t("fehler.werkzeug_verboten", "en", name="read_file")


# --- The sentence itself -----------------------------------------------


def test_note_only_for_file_tools_with_a_path_under_the_old_place(tmp_path):
    chat = "umzug-einheit"
    old, new = (tmp_path / "Alt").resolve(), (tmp_path / "neu").resolve()
    folders = [str(new)]
    generierung.ordner_umzug_melden(chat, str(old), str(new))
    note = generierung.move_note
    try:
        below = {"path": str(old / "a" / "b.txt")}
        assert note(chat, "read_file", below, folders) == _sentence(old, new)
        assert note(chat, "list_dir", {"path": str(old)}, folders) == _sentence(old, new)
        # Read the way the gate reads it: letter case aside, and a relative
        # path against the first shared folder.
        spelled_otherwise = {"path": str(tmp_path.resolve() / "ALT" / "b.txt")}
        assert note(chat, "read_file", spelled_otherwise, folders) == _sentence(old, new)
        assert note(chat, "read_file", {"path": "../Alt/b.txt"}, folders) == _sentence(old, new)
        # Not a file tool, a relative path inside the new place, a neighbour
        # sharing the prefix, no shared folder, another chat.
        assert note(chat, "run_command", below, folders) == ""
        assert note(chat, "read_file", {"path": "Alt/b.txt"}, folders) == ""
        neighbour = {"path": str(tmp_path / "Alt-zwei" / "b.txt")}
        assert note(chat, "read_file", neighbour, folders) == ""
        assert note(chat, "read_file", below, []) == ""
        assert note("anderer-chat", "read_file", below, folders) == ""
        assert note(None, "read_file", below, folders) == ""
    finally:
        generierung.ordner_umzug_vergessen(chat)


def test_a_path_the_disk_cannot_take_gets_no_sentence(tmp_path):
    """A NUL byte makes the path unresolvable: the refusal stays as it is
    without a sentence, nothing is raised."""
    chat = "move-nul"
    old, new = (tmp_path / "alt").resolve(), (tmp_path / "neu").resolve()
    generierung.ordner_umzug_melden(chat, str(old), str(new))
    try:
        arguments = {"path": str(old / "a\x00b.txt")}
        assert generierung.move_note(chat, "read_file", arguments, [str(new)]) == ""
    finally:
        generierung.ordner_umzug_vergessen(chat)


def test_one_target_per_old_place_and_chains_resolved(tmp_path):
    """A to B, then B to C: A points at C. A to B, then B back to A: A is no
    old place any more, and B points at A."""
    chat = "move-chain"
    a, b, c = (str((tmp_path / n).resolve()) for n in ("a", "b", "c"))
    try:
        generierung.ordner_umzug_melden(chat, a, b)
        generierung.ordner_umzug_melden(chat, b, c)
        assert _pairs(chat) == {(a, c), (b, c)}

        generierung.ordner_umzug_vergessen(chat)
        generierung.ordner_umzug_melden(chat, a, b)
        generierung.ordner_umzug_melden(chat, b, a)
        assert _pairs(chat) == {(b, a)}
        assert generierung._ordner_umzug_satz(chat) == _sentence(Path(b), Path(a))
        # A path under A is no longer told to look at the stale B.
        under_a = {"path": str(Path(a) / "x.txt")}
        assert generierung.move_note(chat, "read_file", under_a, [a]) == ""
    finally:
        generierung.ordner_umzug_vergessen(chat)


def test_a_single_move_is_one_entry(tmp_path):
    """Schweigeprobe: one move, one entry, the sentence as before."""
    chat = "move-single"
    a, b = str((tmp_path / "a").resolve()), str((tmp_path / "b").resolve())
    try:
        generierung.ordner_umzug_melden(chat, a, b)
        assert _pairs(chat) == {(a, b)}
        assert generierung._ordner_umzug_satz(chat) == _sentence(Path(a), Path(b))
    finally:
        generierung.ordner_umzug_vergessen(chat)


def test_chat_a_refusal_about_the_tool_gets_no_sentence(client, chat_id, tmp_path):
    """The tool itself is refused — not the path — so where the folder went
    does not help the call: no sentence."""
    old, _new = _move_folder(client, chat_id, tmp_path)

    content_ = _chat_refusal(client, chat_id, "tool", old / "notiz.txt")

    assert content_ == TOOL_REFUSAL


async def test_job_a_refusal_about_the_tool_gets_no_sentence(client, config, chat_id, tmp_path):
    old, new = _move_folder(client, chat_id, tmp_path)

    content_ = await _job_refusal(client, config, chat_id, "tool", old / "notiz.txt", [str(new)])

    assert content_ == TOOL_REFUSAL


async def test_job_a_tool_the_helper_is_not_offered_gets_no_sentence(
    client, config, chat_id, tmp_path, monkeypatch
):
    """A tool the run is not offered (app/helper.py ``refused_call``) is
    refused for what it is, wherever its path points."""
    from app import helper

    old, new = _move_folder(client, chat_id, tmp_path)
    monkeypatch.setattr(helper, "refused_call", lambda _agent, _name: TOOL_REFUSAL)

    content_ = await _job_refusal(client, config, chat_id, "outside", old / "notiz.txt", [str(new)])

    assert content_ == TOOL_REFUSAL


def test_the_gate_marks_a_refusal_about_the_path(tmp_path):
    """Tor 3 says which of its refusals are about the path: outside the
    shared folders yes, a rule against the tool no."""
    from app import berechtigungen as gate
    from app.berechtigungsregeln import Regeldatei

    shared = tmp_path / "shared"
    shared.mkdir()
    outside = gate.urteil(
        "read_file", {"path": str(tmp_path / "elsewhere" / "a.txt")}, [str(shared)], "agent",
        regeln=Regeldatei(),
    )
    assert outside.antwort == "nein"
    assert outside.about_path is True

    by_rule = gate.urteil(
        "read_file", {"path": str(shared / "a.txt")}, [str(shared)], "agent",
        regeln=Regeldatei(regeln={"read_file": "nein"}),
    )
    assert by_rule.antwort == "nein"
    assert by_rule.about_path is False


def _pairs(chat: str) -> set[tuple[str, str]]:
    return set(generierung._ordner_umzuege.get(chat, {}).values())


def test_another_spelling_of_the_same_place_still_closes_the_chain(tmp_path):
    """A to B, then B — written with a trailing slash, another letter case
    and through a link — back to A: the same chain as written alike."""
    chat = "move-spelling"
    real = tmp_path / "real"
    (real / "b").mkdir(parents=True)
    link = tmp_path / "link"
    link.symlink_to(real)
    a = str((tmp_path / "a").resolve())
    b = str((real / "b").resolve())
    try:
        generierung.ordner_umzug_melden(chat, a, b)
        generierung.ordner_umzug_melden(chat, str(link / "B") + "/", a)
        assert len(_pairs(chat)) == 1
        ((old, new),) = _pairs(chat)
        assert new == a
        assert generierung._place_key(old) == generierung._place_key(b)
    finally:
        generierung.ordner_umzug_vergessen(chat)
