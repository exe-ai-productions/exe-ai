"""Snapshots before the model changes files, and putting them back.

The store is a real dulwich repository in a temporary folder; only the
settings table is a stand-in. Every test that matters fails without the
behaviour it names: the switch off, a second call in the same turn, a file too
big, a computer without any git.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app import checkpoint_hooks, checkpoints
from app.api.v1.generierung import _werkzeug_ausfuehren
from app.checkpoint_choice import check_switch
from app.providers.base import Werkzeugaufruf
from app.tools import datei_aendern, datei_schreiben


class _Switch:
    def __init__(self, on: bool) -> None:
        self.on = on

    def zusammengefuehrt(self, key: str, **_: Any) -> dict[str, bool]:
        return {"enabled": self.on}


def _repositories(on: bool = True) -> Any:
    return SimpleNamespace(einstellungen=_Switch(on))


@pytest.fixture(autouse=True)
def _fresh_turns():
    checkpoints.forget_turns()
    yield
    checkpoints.forget_turns()


@pytest.fixture
def env(tmp_path: Path) -> SimpleNamespace:
    work = tmp_path / "work"
    work.mkdir()
    (work / "keep.txt").write_text("kept", encoding="utf-8")
    data = tmp_path / "data"
    data.mkdir()
    return SimpleNamespace(
        work=work, data=data, folders=[str(work)], base=checkpoint_hooks.store_folder(data),
        repos=_repositories(True),
    )


def _run(coro):
    return asyncio.run(coro)


async def _tool(env: SimpleNamespace, module, arguments: dict[str, str], turn: str, repos=None) -> str:
    """One call of a file tool, wrapped in the hook the way the chat wraps it."""
    pending = await checkpoint_hooks.before(
        repos or env.repos, env.data, module.WERKZEUG_NAME, arguments, env.folders, "chat-1", turn
    )
    out = await module.ausfuehren(arguments, env.folders, env.data)
    await checkpoint_hooks.after(pending, ran=True)
    return out


def _write(env: SimpleNamespace, name: str, text: str, turn: str, repos=None) -> None:
    _run(_tool(env, datei_schreiben, {"path": name, "content": text}, turn, repos))


def _edit(env: SimpleNamespace, name: str, old: str, new: str, turn: str) -> None:
    _run(_tool(env, datei_aendern, {"path": name, "old_text": old, "new_text": new}, turn))


def _read(env: SimpleNamespace, name: str) -> str | None:
    path = env.work / name
    return path.read_text(encoding="utf-8") if path.exists() else None


def _in_snapshot(env: SimpleNamespace, number: int = 1) -> set[str]:
    snap = checkpoints.snapshots(env.base, env.work)[number - 1]["id"]
    project = checkpoints._project(env.base, env.work)
    with checkpoints._repo(project) as repo:
        return set(checkpoints._flat(repo, repo[snap.encode()].tree))


# --- When a snapshot is taken ------------------------------------------------------------------


def test_two_writes_in_one_turn_make_one_snapshot_and_a_new_turn_a_new_one(env):
    _write(env, "a.txt", "first", "turn-1")
    _write(env, "b.txt", "second", "turn-1")
    assert len(checkpoints.snapshots(env.base, env.work)) == 1
    _write(env, "c.txt", "third", "turn-2")
    assert len(checkpoints.snapshots(env.base, env.work)) == 2


def test_a_shell_command_that_removes_files_makes_a_snapshot_before_it_runs(env):
    pending = _run(
        checkpoint_hooks.before(
            env.repos, env.data, "run_command", {"command": "rm keep.txt"}, env.folders, "chat-1", "turn-1"
        )
    )
    assert pending is not None and pending.file is None
    (env.work / "keep.txt").unlink()
    _run(checkpoint_hooks.after(pending, ran=True))
    listed = checkpoints.snapshots(env.base, env.work)
    assert len(listed) == 1
    assert listed[0]["reason"] == "run_command: rm keep.txt"
    assert listed[0]["files"] == ["keep.txt"]
    assert checkpoints.restore(env.base, env.work, listed[0]["id"])["restored"] == ["keep.txt"]
    assert _read(env, "keep.txt") == "kept"


def test_what_a_command_changed_is_the_models_even_beside_other_notes(env):
    """The careful restore must not read a removed or rewritten file as the
    person's just because the folder's notes hold other entries."""
    (env.work / "other.txt").write_text("other", encoding="utf-8")
    _write(env, "written.txt", "by a tool", "turn-1")
    pending = _run(
        checkpoint_hooks.before(
            env.repos, env.data, "run_command", {"command": "rm keep.txt && sed -i x other.txt"},
            env.folders, "chat-1", "turn-2",
        )
    )
    (env.work / "keep.txt").unlink()
    (env.work / "other.txt").write_text("rewritten by the command", encoding="utf-8")
    _run(checkpoint_hooks.after(pending, ran=True))
    snap = checkpoints.snapshots(env.base, env.work)[0]["id"]
    done = checkpoints.restore(env.base, env.work, snap)
    assert done["restored"] == ["keep.txt", "other.txt"] and done["skipped"] == []
    assert _read(env, "keep.txt") == "kept" and _read(env, "other.txt") == "other"
    # A file the person brought back by hand afterwards is theirs again.
    (env.work / "keep.txt").unlink()
    _run(checkpoint_hooks.after(pending, ran=True))
    (env.work / "keep.txt").write_text("typed by hand", encoding="utf-8")
    assert "keep.txt" in checkpoints.restore(env.base, env.work, snap)["skipped"]


def test_a_shell_command_that_only_reads_makes_no_snapshot(env):
    for command in ("ls -la", "cat keep.txt", "echo hi >> keep.txt", "make 2>&1", "git status"):
        _run(
            checkpoint_hooks.before(
                env.repos, env.data, "run_command", {"command": command}, env.folders, "chat-1", "t"
            )
        )
    assert not env.base.exists()


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf build", "ls && rm x", "mv a b", "cp a b", "sed -i 's/a/b/' f", "sed -n -i.bak p f",
        "echo x > f", "git reset --hard", "git checkout -- f", "git clean -fd", "truncate -s 0 f",
    ],
)
def test_destructive_commands_are_told_apart(command):
    assert checkpoint_hooks.is_destructive(command)


@pytest.mark.parametrize("command", ["ls", "cat f", "echo x >> f", "make 2>&1", "git status", "grep -r word .", ""])
def test_other_commands_are_not_destructive(command):
    assert not checkpoint_hooks.is_destructive(command)


@pytest.mark.parametrize(
    "command",
    [
        "find . -name '*.tmp' -delete", "rsync -a --delete src/ dst/", "rsync -a --del src/ dst/",
        "rsync -a --delete-after src/ dst/", "rsync -a --remove-source-files a/ b/",
        "echo x | tee notes.txt", "echo x | tee -a notes.txt",
        "python3 -c \"import os; os.remove('a')\"", "bash cleanup.sh", "node -e \"require('fs').rmSync('a')\"",
        "cd d && python script.py", "/bin/sh run.sh", "perl -e 'unlink q(a)'", "ruby clean.rb", "zsh tidy.sh",
    ],
)
def test_find_delete_rsync_delete_tee_and_scripts_take_a_snapshot_first(command):
    assert checkpoint_hooks.is_destructive(command)


@pytest.mark.parametrize(
    "command",
    [
        "ls -la", "grep -rn foo .", "git status", "cat a >> b", "rsync -a src/ dst/",
        "find . -name '*.py'", "ssh host ls", "pythonic things", "nodes list", "teeth",
    ],
)
def test_silence_reading_and_look_alikes_take_no_snapshot(command):
    assert not checkpoint_hooks.is_destructive(command)


def test_with_the_switch_off_nothing_is_snapshotted_and_the_tool_runs(env):
    _write(env, "a.txt", "text", "turn-1", repos=_repositories(False))
    assert _read(env, "a.txt") == "text"
    assert not env.base.exists()


def test_with_no_git_on_the_computer_the_snapshot_is_made_and_no_git_program_is_started(env, monkeypatch, tmp_path):
    empty = tmp_path / "empty-path"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    started: list[Any] = []

    def refuse(*args: Any, **kwargs: Any) -> Any:
        started.append(args)
        raise AssertionError("a program was started")

    for name in ("run", "Popen", "check_output", "check_call", "call"):
        monkeypatch.setattr(subprocess, name, refuse)
    monkeypatch.setattr(os, "system", refuse)
    _write(env, "a.txt", "text", "turn-1")
    [only] = checkpoints.snapshots(env.base, env.work)
    assert "keep.txt" in _in_snapshot(env)
    assert only["files"] == ["a.txt"]
    assert checkpoints.restore(env.base, env.work, only["id"])["restored"] == ["a.txt"]
    assert _read(env, "a.txt") is None
    assert started == []


def test_a_folder_outside_the_shares_is_not_snapshotted(env, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    pending = _run(
        checkpoint_hooks.before(
            env.repos, env.data, "write_file", {"path": str(other / "x.txt")}, env.folders, "chat-1", "t"
        )
    )
    assert pending is None
    assert not env.base.exists()


def test_the_root_and_the_home_folder_are_never_snapshotted(env, monkeypatch):
    read: list[Path] = []

    def watch(directory: Path) -> Any:
        read.append(directory)
        return False, []

    monkeypatch.setattr(checkpoints, "_scan", watch)
    assert checkpoints.snapshot(env.base, Path(Path.cwd().anchor), "t", "x") is False
    assert checkpoints.snapshot(env.base, Path.home(), "t", "x") is False
    assert read == []
    assert not env.base.exists()


def test_a_turn_that_changed_nothing_leaves_no_second_snapshot(env):
    assert checkpoints.snapshot(env.base, env.work, "turn-1", "first") is True
    assert checkpoints.snapshot(env.base, env.work, "turn-2", "second") is False
    assert len(checkpoints.snapshots(env.base, env.work)) == 1


@pytest.mark.skipif(os.name == "nt", reason="windows has no executable bit")
def test_a_script_comes_back_executable(env):
    script = env.work / "run.sh"
    script.write_text("#!/bin/sh\n", encoding="utf-8")
    script.chmod(0o755)
    assert checkpoints.snapshot(env.base, env.work, "turn-1", "x") is True
    script.unlink()
    snap = checkpoints.snapshots(env.base, env.work)[0]["id"]
    assert checkpoints.restore(env.base, env.work, snap, everything=True)["restored"] == ["run.sh"]
    assert script.stat().st_mode & 0o111


def test_a_folder_with_too_many_files_gets_no_snapshot(env, monkeypatch):
    monkeypatch.setattr(checkpoints, "MAX_FILES", 2)
    for name in ("one.txt", "two.txt"):
        (env.work / name).write_text(name, encoding="utf-8")
    assert checkpoints.snapshot(env.base, env.work, "t", "x") is False
    assert checkpoints.snapshots(env.base, env.work) == []


def test_files_the_folder_ignores_do_not_count_against_the_limit(env, monkeypatch):
    monkeypatch.setattr(checkpoints, "MAX_FILES", 3)
    (env.work / ".gitignore").write_text("deps/\n", encoding="utf-8")
    (env.work / "deps").mkdir()
    for number in range(10):
        (env.work / "deps" / f"{number}.js").write_text("x", encoding="utf-8")
    assert checkpoints.snapshot(env.base, env.work, "t", "x") is True
    assert _in_snapshot(env) == {".gitignore", "keep.txt"}


def test_a_big_file_and_a_nested_repository_stay_out_of_every_snapshot(env, monkeypatch):
    monkeypatch.setattr(checkpoints, "MAX_FILE_BYTES", 10)
    (env.work / "big.bin").write_bytes(b"x" * 50)
    nested = env.work / "inner"
    nested.mkdir()
    (nested / "inside.txt").write_text("inside", encoding="utf-8")
    (nested / ".git").mkdir()
    (nested / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    _write(env, "small.txt", "tiny", "turn-1")
    assert _in_snapshot(env) == {"keep.txt"}


def test_a_first_snapshot_of_an_empty_folder_is_what_a_new_file_goes_back_to(env):
    (env.work / "keep.txt").unlink()
    _write(env, "made.txt", "by the model", "turn-1")
    listed = checkpoints.snapshots(env.base, env.work)
    assert len(listed) == 1
    assert checkpoints.restore(env.base, env.work, listed[0]["id"])["restored"] == ["made.txt"]
    assert _read(env, "made.txt") is None


def test_a_file_that_cannot_be_read_does_not_stop_the_snapshot(env):
    secret = env.work / "locked.txt"
    secret.write_text("x", encoding="utf-8")
    secret.chmod(0)
    try:
        if os.access(secret, os.R_OK):
            pytest.skip("this account can read any file")
        assert checkpoints.snapshot(env.base, env.work, "t", "x") is True
        assert "keep.txt" in _in_snapshot(env)
    finally:
        secret.chmod(0o600)


def test_names_with_pattern_characters_are_taken_literally(env):
    (env.work / "report[1].md").write_text("old one", encoding="utf-8")
    (env.work / "report1.md").write_text("old two", encoding="utf-8")
    _write(env, "report[1].md", "new one", "turn-1")
    (env.work / "report1.md").write_text("changed by hand", encoding="utf-8")
    snap = checkpoints.snapshots(env.base, env.work)[0]["id"]
    assert checkpoints.restore(env.base, env.work, snap)["restored"] == ["report[1].md"]
    assert _read(env, "report[1].md") == "old one"
    assert _read(env, "report1.md") == "changed by hand"


def test_a_folder_that_is_gone_can_be_listed_and_comes_back(env):
    _write(env, "a.txt", "one", "turn-1")
    _write(env, "b.txt", "two", "turn-2")
    snap = checkpoints.snapshots(env.base, env.work)[0]["id"]
    for name in ("keep.txt", "a.txt", "b.txt"):
        (env.work / name).unlink()
    env.work.rmdir()
    assert checkpoints.snapshots(env.base, env.work)[0]["files"] == ["a.txt", "keep.txt"]
    done = checkpoints.restore(env.base, env.work, snap, everything=True)
    assert done["restored"] == ["a.txt", "keep.txt"]
    assert _read(env, "a.txt") == "one"


def test_a_command_snapshots_every_shared_folder_not_only_the_one_it_starts_in(env, tmp_path):
    second = tmp_path / "second"
    second.mkdir()
    (second / "other.txt").write_text("other", encoding="utf-8")
    folders = [str(env.work), str(second)]
    _run(
        checkpoint_hooks.before(
            env.repos, env.data, "run_command", {"command": "rm /somewhere/else.txt"}, folders, "chat-1", "t"
        )
    )
    assert len(checkpoints.snapshots(env.base, env.work)) == 1
    assert len(checkpoints.snapshots(env.base, second)) == 1


def test_the_chats_own_folder_in_the_data_folder_is_not_snapshotted(env):
    own = env.data / "chats" / "c1"
    own.mkdir(parents=True)
    pending = _run(
        checkpoint_hooks.before(
            env.repos, env.data, "write_file", {"path": "note.txt"}, [str(own)], "chat-1", "t"
        )
    )
    assert pending is None
    assert not env.base.exists()


def test_a_command_in_the_background_is_snapshotted_but_not_noted(env):
    pending = _run(
        checkpoint_hooks.before(
            env.repos, env.data, "run_command", {"command": "rm keep.txt", "background": True},
            env.folders, "chat-1", "t",
        )
    )
    assert pending is None
    assert len(checkpoints.snapshots(env.base, env.work)) == 1


def test_a_failed_write_is_not_noted_and_a_failed_command_is(env):
    write = _run(
        checkpoint_hooks.before(
            env.repos, env.data, "write_file", {"path": "keep.txt"}, env.folders, "chat-1", "turn-1"
        )
    )
    _run(checkpoint_hooks.after(write, ran=False))
    project = checkpoints._project(env.base, env.work)
    assert checkpoints._read_ledger(project) == {}
    command = _run(
        checkpoint_hooks.before(
            env.repos, env.data, "run_command", {"command": "rm keep.txt"}, env.folders, "chat-1", "turn-2"
        )
    )
    (env.work / "keep.txt").unlink()
    _run(checkpoint_hooks.after(command, ran=False))
    assert checkpoints._read_ledger(project) == {str(env.work / "keep.txt"): ""}


def test_a_snapshot_that_failed_on_the_way_is_tried_again_in_the_same_turn(env, monkeypatch):
    real = checkpoints._take
    calls = []

    def flaky(project, reason):
        calls.append(reason)
        if len(calls) == 1:
            raise RuntimeError("the store went wrong")
        return real(project, reason)

    monkeypatch.setattr(checkpoints, "_take", flaky)
    assert checkpoints.snapshot(env.base, env.work, "turn-1", "first call") is False
    assert checkpoints.snapshot(env.base, env.work, "turn-1", "second call") is True
    assert len(calls) == 2


def test_a_restore_can_itself_be_taken_back(env):
    snap = _scene(env)
    checkpoints.restore(env.base, env.work, snap)
    assert _read(env, "made.txt") is None
    newest = checkpoints.snapshots(env.base, env.work)[0]
    assert newest["reason"] == "before restore"
    checkpoints.restore(env.base, env.work, newest["id"], everything=True)
    assert _read(env, "old.txt") == "model text"


def test_a_single_file_no_snapshot_could_hold_is_not_removed(env):
    (env.work / ".gitignore").write_text(".env\n", encoding="utf-8")
    (env.work / ".env").write_text("SECRET=1", encoding="utf-8")
    _write(env, "a.txt", "one", "turn-1")
    snap = checkpoints.snapshots(env.base, env.work)[0]["id"]
    done = checkpoints.restore(env.base, env.work, snap, file=".env")
    assert done["restored"] == [] and done["skipped"] == [".env"]
    assert _read(env, ".env") == "SECRET=1"


# --- What a snapshot lists --------------------------------------------------------------------------


def test_the_list_names_each_snapshot_with_the_files_changed_after_it(env):
    _write(env, "a.txt", "one", "turn-1")
    _write(env, "b.txt", "two", "turn-2")
    listed = checkpoints.snapshots(env.base, env.work)
    assert [snap["nr"] for snap in listed] == [1, 2]
    assert listed[0]["reason"] == "write_file b.txt"
    assert listed[0]["files"] == ["b.txt"]
    assert listed[1]["reason"] == "write_file a.txt"
    assert listed[1]["files"] == ["a.txt"]


# --- Reading only what changed -------------------------------------------------------------------


def _aged(env: SimpleNamespace, name: str, text: str, seconds_ago: int = 3600) -> None:
    """Writes a file and gives it a modification time well before any snapshot
    taken now, the way a file that has lain in a folder for a while looks."""
    path = env.work / name
    path.write_text(text, encoding="utf-8")
    stamp = time.time_ns() - seconds_ago * 1_000_000_000
    os.utime(path, ns=(stamp, stamp))


def _settled_folder(env: SimpleNamespace) -> None:
    for name in ("a.txt", "b.txt", "c.txt", "d.txt", "keep.txt"):
        _aged(env, name, name[0] * 4)


@pytest.fixture
def reads(env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The names of the files of the folder that are read from here on."""
    names: list[str] = []
    original = Path.open
    folder = env.work.resolve()

    def counting(self: Path, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        if mode.startswith("r") and folder in self.parents:
            names.append(self.name)
        return original(self, mode, *args, **kwargs)

    # read_bytes and read_text both go through open.
    monkeypatch.setattr(Path, "open", counting)
    return names


def test_the_next_snapshot_reads_only_the_file_that_changed(env, reads):
    _settled_folder(env)
    assert checkpoints.snapshot(env.base, env.work, "turn-1", "first")
    assert sorted(reads) == ["a.txt", "b.txt", "c.txt", "d.txt", "keep.txt"]
    reads.clear()
    _aged(env, "b.txt", "xxxx", seconds_ago=1800)
    assert checkpoints.snapshot(env.base, env.work, "turn-2", "second")
    assert reads == ["b.txt"]


def test_the_list_reads_only_the_file_that_changed_and_leaves_the_index_as_it_was(env, reads):
    _settled_folder(env)
    checkpoints.snapshot(env.base, env.work, "turn-1", "first")
    _aged(env, "c.txt", "xxxx", seconds_ago=1800)
    index = checkpoints._project(env.base, env.work).index_file
    held = index.read_bytes()
    reads.clear()
    listed = checkpoints.snapshots(env.base, env.work)
    # Same size, new time: the change is seen, and only that file is read.
    assert listed[0]["files"] == ["c.txt"]
    assert reads == ["c.txt"]
    assert index.read_bytes() == held


def test_a_removed_and_a_new_file_are_listed_without_reading_the_rest(env, reads):
    _settled_folder(env)
    checkpoints.snapshot(env.base, env.work, "turn-1", "first")
    (env.work / "c.txt").unlink()
    _aged(env, "e.txt", "eeee")
    reads.clear()
    assert checkpoints.snapshots(env.base, env.work)[0]["files"] == ["c.txt", "e.txt"]
    assert reads == ["e.txt"]


def test_a_file_that_stays_as_it_was_is_not_listed(env):
    _settled_folder(env)
    checkpoints.snapshot(env.base, env.work, "turn-1", "first")
    assert checkpoints.snapshots(env.base, env.work)[0]["files"] == []


@pytest.mark.xfail(
    os.name == "nt",
    strict=True,
    reason="Windows reports the creation time as the change time, so a rewrite that keeps size and time is not seen",
)
def test_a_file_replaced_by_one_of_the_same_size_and_time_is_still_seen(env, reads):
    _settled_folder(env)
    checkpoints.snapshot(env.base, env.work, "turn-1", "first")
    path = env.work / "a.txt"
    before = path.stat().st_mtime_ns
    path.write_text("zzzz", encoding="utf-8")
    # A copy that keeps the time, as cp -p and tar do.
    os.utime(path, ns=(before, before))
    reads.clear()
    assert checkpoints.snapshots(env.base, env.work)[0]["files"] == ["a.txt"]
    assert reads == ["a.txt"]


def _stat(size: int, mtime: int, ctime: int, mode: int = 0o100644) -> Any:
    return SimpleNamespace(st_size=size, st_mtime_ns=mtime, st_ctime_ns=ctime, st_mode=mode)


def test_the_index_vouches_for_a_file_only_while_all_it_knows_of_it_holds():
    second = 1_000_000_000
    seen = checkpoints._Seen(4, 10 * second, 12 * second, b"0" * 40, 0o100644)
    taken = 20 * second
    assert checkpoints._unchanged(seen, _stat(4, 10 * second, 12 * second), taken)
    assert not checkpoints._unchanged(seen, _stat(5, 10 * second, 12 * second), taken)
    assert not checkpoints._unchanged(seen, _stat(4, 11 * second, 12 * second), taken)
    assert not checkpoints._unchanged(seen, _stat(4, 10 * second, 13 * second), taken)
    if os.name != "nt":
        assert not checkpoints._unchanged(seen, _stat(4, 10 * second, 12 * second, mode=0o100755), taken)
    # Its time lies in the second of the pass that wrote the index, or after it.
    late = checkpoints._Seen(4, 20 * second + 5, 12 * second, b"0" * 40, 0o100644)
    assert not checkpoints._unchanged(late, _stat(4, 20 * second + 5, 12 * second), taken)
    later = checkpoints._Seen(4, 30 * second, 12 * second, b"0" * 40, 0o100644)
    assert not checkpoints._unchanged(later, _stat(4, 30 * second, 12 * second), taken)


@pytest.mark.parametrize(
    "damage",
    [
        None,
        "",
        "not json",
        "[]",
        '{"taken": "x", "files": {}}',
        '{"taken": 1, "files": {"a.txt": [1, 2]}}',
        '{"taken": Infinity, "files": {}}',
        "[" * 100_000,
    ],
    # Short ids: pytest puts the id of the running test in an environment
    # variable, and Windows takes none longer than 32767 characters.
    ids=["none", "empty", "not-json", "list", "wrong-taken", "wrong-entry", "infinity", "deep-brackets"],
)
def test_a_missing_or_damaged_index_is_built_again(env, reads, damage):
    _settled_folder(env)
    checkpoints.snapshot(env.base, env.work, "turn-1", "first")
    index = checkpoints._project(env.base, env.work).index_file
    if damage is None:
        index.unlink()
    else:
        index.write_text(damage, encoding="utf-8")
    _aged(env, "b.txt", "xxxx", seconds_ago=1800)
    reads.clear()
    assert checkpoints.snapshots(env.base, env.work)[0]["files"] == ["b.txt"]
    assert sorted(reads) == ["a.txt", "b.txt", "c.txt", "d.txt", "keep.txt"]
    reads.clear()
    assert checkpoints.snapshot(env.base, env.work, "turn-2", "second")
    assert sorted(reads) == ["a.txt", "b.txt", "c.txt", "d.txt", "keep.txt"]
    # The pass wrote an index again: the next one reads nothing but what changed.
    reads.clear()
    _aged(env, "d.txt", "yyyy", seconds_ago=900)
    assert checkpoints.snapshot(env.base, env.work, "turn-3", "third")
    assert reads == ["d.txt"]


def test_an_index_entry_with_a_broken_id_is_not_trusted(env, reads):
    _settled_folder(env)
    checkpoints.snapshot(env.base, env.work, "turn-1", "first")
    index = checkpoints._project(env.base, env.work).index_file
    held = json.loads(index.read_text(encoding="utf-8"))
    held["files"]["a.txt"][3] = "zz"
    index.write_text(json.dumps(held), encoding="utf-8")
    _aged(env, "b.txt", "xxxx", seconds_ago=1800)
    reads.clear()
    assert checkpoints.snapshot(env.base, env.work, "turn-2", "second")
    # The index is dropped as a whole, not entry by entry.
    assert sorted(reads) == ["a.txt", "b.txt", "c.txt", "d.txt", "keep.txt"]
    assert "a.txt" in _in_snapshot(env)


@pytest.mark.skipif(os.name == "nt", reason="the executable bit does not exist there")
def test_a_change_of_the_mode_alone_is_seen_and_snapshotted(env):
    _settled_folder(env)
    checkpoints.snapshot(env.base, env.work, "turn-1", "first")
    (env.work / "a.txt").chmod(0o755)
    assert checkpoints.snapshot(env.base, env.work, "turn-2", "second")
    assert checkpoints.snapshots(env.base, env.work)[0]["reason"] == "second"


def test_a_folder_that_cannot_keep_its_index_still_gets_its_snapshot(env, monkeypatch):
    _settled_folder(env)

    def refuse(*_: Any, **__: Any) -> None:
        raise OSError("no room")

    monkeypatch.setattr(checkpoints.atomic_file, "write", refuse)
    assert checkpoints.snapshot(env.base, env.work, "turn-1", "first")
    assert len(checkpoints.snapshots(env.base, env.work)) == 1


def test_putting_a_snapshot_back_gives_the_same_with_the_index_as_without_it(env):
    _settled_folder(env)
    checkpoints.snapshot(env.base, env.work, "turn-1", "first")
    snap = checkpoints.snapshots(env.base, env.work)[0]["id"]
    index = checkpoints._project(env.base, env.work).index_file

    def run(drop_index: bool) -> tuple[dict[str, list[str]], dict[str, str | None]]:
        _aged(env, "b.txt", "xxxx", seconds_ago=1800)
        _aged(env, "made.txt", "made")
        if drop_index:
            index.unlink()
        done = checkpoints.restore(env.base, env.work, snap, everything=True)
        return done, {name: _read(env, name) for name in ("a.txt", "b.txt", "made.txt")}

    with_index = run(drop_index=False)
    without_index = run(drop_index=True)
    assert with_index == without_index
    assert with_index[0]["restored"] == ["b.txt"]
    assert with_index[1] == {"a.txt": "aaaa", "b.txt": "bbbb", "made.txt": "made"}


# --- Putting files back ---------------------------------------------------------------------------


def _scene(env: SimpleNamespace) -> str:
    """A model turn over a folder the person has files in; returns the id of
    the one snap it left."""
    (env.work / "old.txt").write_text("old", encoding="utf-8")
    (env.work / "hand.txt").write_text("h0", encoding="utf-8")
    _write(env, "old.txt", "model text", "turn-1")
    _write(env, "made.txt", "created by the model", "turn-1")
    _write(env, "later.txt", "also the model", "turn-1")
    (env.work / "hand.txt").write_text("h1", encoding="utf-8")
    (env.work / "later.txt").write_text("changed by hand", encoding="utf-8")
    return checkpoints.snapshots(env.base, env.work)[0]["id"]


def test_the_careful_restore_keeps_what_was_changed_by_hand(env):
    snap = _scene(env)
    done = checkpoints.restore(env.base, env.work, snap)
    assert done["restored"] == ["made.txt", "old.txt"]
    assert done["skipped"] == ["hand.txt", "later.txt"]
    assert _read(env, "old.txt") == "old"
    assert _read(env, "made.txt") is None
    assert _read(env, "hand.txt") == "h1"
    assert _read(env, "later.txt") == "changed by hand"


def test_restoring_everything_puts_back_the_hand_made_change_as_well(env):
    snap = _scene(env)
    done = checkpoints.restore(env.base, env.work, snap, everything=True)
    assert "hand.txt" in done["restored"] and "old.txt" in done["restored"]
    assert _read(env, "hand.txt") == "h0"
    assert _read(env, "old.txt") == "old"
    # A file the snap never had is not touched by putting the snap back.
    assert _read(env, "made.txt") == "created by the model"


def test_one_file_alone(env):
    snap = _scene(env)
    assert checkpoints.restore(env.base, env.work, snap, file="old.txt")["restored"] == ["old.txt"]
    assert _read(env, "old.txt") == "old"
    assert _read(env, "hand.txt") == "h1"
    # A file the snap does not have goes away.
    assert checkpoints.restore(env.base, env.work, snap, file="made.txt")["restored"] == ["made.txt"]
    assert _read(env, "made.txt") is None


def test_an_edit_goes_into_the_ledger_like_a_write(env):
    _write(env, "a.txt", "alpha beta", "turn-1")
    _edit(env, "a.txt", "beta", "gamma", "turn-2")
    snap = checkpoints.snapshots(env.base, env.work)[0]["id"]
    assert checkpoints.restore(env.base, env.work, snap)["restored"] == ["a.txt"]
    assert _read(env, "a.txt") == "alpha beta"


def test_a_request_the_store_cannot_serve_says_why(env):
    snap = _scene(env)

    def kind(**given: Any) -> str:
        arguments = {"base": env.base, "directory": env.work, "snap": snap, **given}
        with pytest.raises(checkpoints.CheckpointError) as refused:
            checkpoints.restore(
                arguments["base"], arguments["directory"], arguments["snap"], file=arguments.get("file")
            )
        return refused.value.kind

    assert kind(file="../outside.txt") == "bad_file"
    assert kind(file=str(env.work / "old.txt")) == "bad_file"
    assert kind(snap="f" * 40) == "unknown_snapshot"
    assert kind(snap="not-an-id") == "unknown_snapshot"
    assert kind(directory=env.data) == "unknown_folder"


def test_a_snapshot_of_another_folder_is_not_taken_for_this_ones(env, tmp_path):
    snap = _scene(env)
    other = tmp_path / "other"
    other.mkdir()
    (other / "x.txt").write_text("x", encoding="utf-8")
    checkpoints.snapshot(env.base, other, "turn-9", "x")
    with pytest.raises(checkpoints.CheckpointError) as refused:
        checkpoints.restore(env.base, other, snap)
    assert refused.value.kind == "unknown_snapshot"


# --- The switch -----------------------------------------------------------------------------------


def test_the_switch_keeps_only_its_one_flag_as_a_boolean():
    assert check_switch({"enabled": 1, "other": True}) == {"enabled": True}
    assert check_switch({"enabled": False}) == {"enabled": False}
    assert check_switch("on") == {}


def test_the_switch_ships_inactive_and_is_global_only(client):
    resolved = client.get("/api/v1/settings/resolved/checkpoints").json()
    assert resolved["wert"] == {"enabled": False}
    assert resolved["herkunft"] == {}
    assert client.put("/api/v1/settings/global/checkpoints", json={"wert": {"enabled": True}}).status_code == 200
    assert client.get("/api/v1/settings/resolved/checkpoints").json()["wert"] == {"enabled": True}
    assert client.put("/api/v1/settings/chat:c1/checkpoints", json={"wert": {"enabled": False}}).status_code == 400
    listed = client.get("/api/v1/settings/resolved").json()
    assert "checkpoints" in listed


# --- The route ------------------------------------------------------------------------------------


def test_the_route_lists_and_restores(client, tmp_path):
    work = tmp_path / "routework"
    work.mkdir()
    (work / "a.txt").write_text("one", encoding="utf-8")
    base = checkpoint_hooks.store_folder(client.app.state.config.datenverzeichnis)
    assert checkpoints.snapshot(base, work, "turn-1", "write_file a.txt")
    (work / "a.txt").write_text("two", encoding="utf-8")
    answer = client.get("/api/v1/checkpoints", params={"directory": str(work)}).json()
    assert answer["enabled"] is False and "git" not in answer
    assert [snap["files"] for snap in answer["snapshots"]] == [["a.txt"]]
    body = {"directory": str(work), "snapshot": answer["snapshots"][0]["id"], "all": True}
    restored = client.post("/api/v1/checkpoints/restore", json=body)
    assert restored.status_code == 200 and restored.json()["restored"] == ["a.txt"]
    assert (work / "a.txt").read_text(encoding="utf-8") == "one"
    unknown = client.post("/api/v1/checkpoints/restore", json={**body, "directory": str(tmp_path)})
    assert unknown.status_code == 404
    bad = client.post("/api/v1/checkpoints/restore", json={**body, "all": False, "file": "../x"})
    assert bad.status_code == 400
    assert client.get("/api/v1/checkpoints", params={"directory": str(tmp_path)}).json()["snapshots"] == []


# --- The call in the chat -------------------------------------------------------------------------


class _Registry:
    """Stands in for the tool registry: runs the real file tool, and first
    looks whether the snapshot is already there."""

    folder_share = None

    def __init__(self, env: SimpleNamespace) -> None:
        self.env = env
        self.snapshots_when_called = -1

    async def ausfuehren(self, name, argumente, bild_senke=None, **kw):
        self.snapshots_when_called = len(checkpoints.snapshots(self.env.base, self.env.work))
        return await datei_schreiben.ausfuehren(argumente, kw["ordner"], self.env.data)


def test_the_chat_takes_the_snapshot_before_the_tool_and_notes_the_write_after(env):
    registry = _Registry(env)
    registry.folder_share = SimpleNamespace(data_dir=env.data)
    call = Werkzeugaufruf(id="c1", name="write_file", argumente={"path": "keep.txt", "content": "changed"})
    _, failed, _, _ = _run(
        _werkzeug_ausfuehren(
            registry, call, "en", ordner=env.folders, chat_id="chat-1",
            repositories=env.repos, turn="answer-1",
        )
    )
    assert failed is False
    assert registry.snapshots_when_called == 1
    snap = checkpoints.snapshots(env.base, env.work)[0]["id"]
    # The write is in the ledger, so the careful restore takes it back.
    assert checkpoints.restore(env.base, env.work, snap)["restored"] == ["keep.txt"]
    assert _read(env, "keep.txt") == "kept"
    assert os.path.isfile(env.base / "store" / "HEAD")


# --- Where a restore must not reach ---------------------------------------------------------------


@pytest.mark.skipif(os.name == "nt", reason="links need a privilege on windows")
def test_a_restore_replaces_a_link_and_never_writes_through_it(env, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("not the folder's", encoding="utf-8")
    assert checkpoints.snapshot(env.base, env.work, "turn-1", "x") is True
    (env.work / "keep.txt").unlink()
    (env.work / "keep.txt").symlink_to(outside)
    snap = checkpoints.snapshots(env.base, env.work)[0]["id"]
    done = checkpoints.restore(env.base, env.work, snap, everything=True)
    assert done["restored"] == ["keep.txt"]
    assert outside.read_text(encoding="utf-8") == "not the folder's"
    assert not (env.work / "keep.txt").is_symlink()
    assert _read(env, "keep.txt") == "kept"


@pytest.mark.skipif(os.name == "nt", reason="links need a privilege on windows")
def test_a_restore_does_not_follow_a_folder_that_became_a_link(env, tmp_path):
    (env.work / "sub").mkdir()
    (env.work / "sub" / "a.txt").write_text("orig", encoding="utf-8")
    assert checkpoints.snapshot(env.base, env.work, "turn-1", "x") is True
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (env.work / "sub" / "a.txt").unlink()
    (env.work / "sub").rmdir()
    (env.work / "sub").symlink_to(elsewhere)
    snap = checkpoints.snapshots(env.base, env.work)[0]["id"]
    done = checkpoints.restore(env.base, env.work, snap, everything=True)
    assert done["failed"] == ["sub/a.txt"]
    assert list(elsewhere.iterdir()) == []


def test_a_file_nothing_noted_is_never_put_back_by_the_default_restore(env):
    (env.work / "script.out").write_text("before", encoding="utf-8")
    assert checkpoints.snapshot(env.base, env.work, "turn-1", "x") is True
    # Changed by something that left no note: the ledger is empty.
    (env.work / "script.out").write_text("after", encoding="utf-8")
    snap = checkpoints.snapshots(env.base, env.work)[0]["id"]
    done = checkpoints.restore(env.base, env.work, snap)
    assert done["restored"] == [] and done["skipped"] == ["script.out"]
    assert _read(env, "script.out") == "after"
    _write(env, "other.txt", "by the model", "turn-2")
    (env.work / "script.out").write_text("after again", encoding="utf-8")
    snap = checkpoints.snapshots(env.base, env.work)[-1]["id"]
    done = checkpoints.restore(env.base, env.work, snap)
    assert "script.out" in done["skipped"] and _read(env, "script.out") == "after again"


def test_a_folder_that_outgrew_the_limit_is_still_listed_but_nothing_is_restored_unrecoverably(env, monkeypatch):
    assert checkpoints.snapshot(env.base, env.work, "turn-1", "x") is True
    (env.work / "keep.txt").write_text("changed", encoding="utf-8")
    monkeypatch.setattr(checkpoints, "MAX_FILES", 0)
    [listed] = checkpoints.snapshots(env.base, env.work)
    assert listed["files"] == []
    # No snapshot of what the restore would overwrite can be taken, so it does not run.
    for options in ({"file": "keep.txt"}, {"everything": True}, {}):
        with pytest.raises(checkpoints.CheckpointError) as refused:
            checkpoints.restore(env.base, env.work, listed["id"], **options)
        assert refused.value.kind == "too_many"
    assert _read(env, "keep.txt") == "changed"


@pytest.mark.skipif(os.name == "nt", reason="links need a privilege on windows")
def test_a_single_file_restore_names_the_link_not_what_it_points_to(env):
    (env.work / "other.txt").write_text("other", encoding="utf-8")
    assert checkpoints.snapshot(env.base, env.work, "turn-1", "x") is True
    (env.work / "keep.txt").unlink()
    (env.work / "keep.txt").symlink_to(env.work / "other.txt")
    snap = checkpoints.snapshots(env.base, env.work)[0]["id"]
    assert checkpoints.restore(env.base, env.work, snap, file="keep.txt")["restored"] == ["keep.txt"]
    assert _read(env, "other.txt") == "other"
    assert _read(env, "keep.txt") == "kept"
    assert not (env.work / "keep.txt").is_symlink()


def test_a_file_a_restore_put_back_still_goes_back_further(env):
    (env.work / "x.txt").write_text("base", encoding="utf-8")
    _write(env, "x.txt", "m1", "turn-1")
    first = checkpoints.snapshots(env.base, env.work)[0]["id"]
    _write(env, "x.txt", "m2", "turn-2")
    second = checkpoints.snapshots(env.base, env.work)[0]["id"]
    assert checkpoints.restore(env.base, env.work, second)["restored"] == ["x.txt"]
    assert _read(env, "x.txt") == "m1"
    done = checkpoints.restore(env.base, env.work, first)
    assert done["restored"] == ["x.txt"] and done["skipped"] == []
    assert _read(env, "x.txt") == "base"


def test_a_folder_that_holds_the_data_folder_is_not_snapshotted(env):
    assert checkpoint_hooks.shared_folders([str(env.work)], env.data) == [env.work.resolve()]
    assert checkpoint_hooks.shared_folders([str(env.data.parent)], env.data) == []
    assert checkpoint_hooks.shared_folders([str(env.data / "chat-folder")], env.data) == []


def test_the_reason_names_the_file_even_when_the_folder_was_matched_in_another_spelling():
    if os.name != "nt":
        # Windows compares the spellings without regard to case, so there the
        # folder is the same one and the file is named relative to it.
        assert checkpoint_hooks._shown(Path("/a/B/x.txt"), Path("/a/b"), "/a/B/x.txt") == "/a/B/x.txt"
    assert checkpoint_hooks._shown(Path("/a/b/x.txt"), Path("/a/b"), "x.txt") == "x.txt"


def test_a_stopped_command_is_still_noted(env):
    class Stopped(_Registry):
        async def ausfuehren(self, name, argumente, bild_senke=None, **kw):
            (self.env.work / "keep.txt").unlink()
            raise asyncio.CancelledError

    registry = Stopped(env)
    registry.folder_share = SimpleNamespace(data_dir=env.data)
    call = Werkzeugaufruf(id="c1", name="run_command", argumente={"command": "rm keep.txt"})
    with pytest.raises(asyncio.CancelledError):
        _run(
            _werkzeug_ausfuehren(
                registry, call, "en", ordner=env.folders, chat_id="chat-1",
                repositories=env.repos, turn="answer-1",
            )
        )
    project = checkpoints._project(env.base, env.work)
    assert checkpoints._read_ledger(project) == {str(env.work / "keep.txt"): ""}
