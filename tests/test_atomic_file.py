"""The one way to write a file whole (app/atomic_file.py): a side file,
renamed onto the name; on Windows tried again while the target is held;
copied across devices; and no other way left in the program.

The Windows paths are taken with the platform pretended and the rename
faked, the way tests/test_prozessstopp.py does it: shown to be taken,
never run on Windows here.
"""

from __future__ import annotations

import ast
import asyncio
import errno
import os
import stat
import sys
from pathlib import Path

import pytest

from app import atomic_file

APP = Path(__file__).resolve().parent.parent / "app"


def _only(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir())


# --- a plain write, as before --------------------------------------------


def test_a_write_replaces_the_file_whole_and_leaves_no_side_file(tmp_path):
    target = tmp_path / "note.json"
    target.write_text("old", encoding="utf-8")
    atomic_file.write(target, "new")
    assert target.read_text(encoding="utf-8") == "new"
    assert _only(tmp_path) == ["note.json"]


def test_bytes_go_to_the_disk_as_they_are(tmp_path):
    target = tmp_path / "exe.md"
    atomic_file.write(target, b"one\r\ntwo\n")
    assert target.read_bytes() == b"one\r\ntwo\n"


def test_text_keeps_its_own_line_breaks_when_asked(tmp_path):
    target = tmp_path / "config.yaml"
    atomic_file.write(target, "a\r\nb\n", newline="")
    assert target.read_bytes() == b"a\r\nb\n"


@pytest.mark.skipif(sys.platform == "win32", reason="a link needs a privilege Windows does not grant by default")
def test_a_link_stays_a_link_and_the_file_behind_it_is_replaced(tmp_path):
    real = tmp_path / "real.md"
    real.write_text("old", encoding="utf-8")
    link = tmp_path / "link.md"
    link.symlink_to(real)
    atomic_file.write(link, "new")
    assert link.is_symlink()
    assert real.read_text(encoding="utf-8") == "new"


@pytest.mark.skipif(sys.platform == "win32", reason="Windows keeps no mode bits beyond read-only")
def test_the_permission_bits_of_the_file_stay(tmp_path):
    target = tmp_path / "note.json"
    target.write_text("old", encoding="utf-8")
    target.chmod(0o640)
    atomic_file.write(target, "new")
    assert stat.S_IMODE(target.stat().st_mode) == 0o640


@pytest.mark.skipif(getattr(os, "geteuid", lambda: 1)() == 0, reason="root may write anything")
def test_a_read_only_file_stays_refused(tmp_path):
    target = tmp_path / "note.json"
    target.write_text("old", encoding="utf-8")
    target.chmod(0o444)
    try:
        with pytest.raises(PermissionError):
            atomic_file.write(target, "new")
        assert target.read_text(encoding="utf-8") == "old"
        assert _only(tmp_path) == ["note.json"]
    finally:
        target.chmod(0o644)


def test_an_interrupted_write_leaves_the_old_file_whole_and_no_side_file(tmp_path, monkeypatch):
    target = tmp_path / "note.json"
    target.write_text('{"whole": true}', encoding="utf-8")

    def disk_full(fd):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(atomic_file.os, "fsync", disk_full)
    with pytest.raises(OSError):
        atomic_file.write(target, '{"half": ')
    assert target.read_text(encoding="utf-8") == '{"whole": true}'
    assert _only(tmp_path) == ["note.json"]


# --- Windows: a held target is tried again --------------------------------


def _held(times: int, code: int = errno.EACCES):
    """A rename that is refused ``times`` times, then goes through."""
    real = os.replace
    refusals: list[int] = []

    def replace(src, dst):
        if len(refusals) < times:
            refusals.append(code)
            raise PermissionError(code, "Access is denied", str(dst))
        return real(src, dst)

    return replace, refusals


def test_on_windows_a_held_target_is_tried_again_until_the_rename_lands(tmp_path, monkeypatch):
    monkeypatch.setattr(atomic_file, "WINDOWS", True)
    replace, refusals = _held(2)
    monkeypatch.setattr(atomic_file.os, "replace", replace)
    pauses: list[float] = []
    monkeypatch.setattr(atomic_file.time, "sleep", pauses.append)
    target = tmp_path / "record.json"
    target.write_text("old", encoding="utf-8")

    atomic_file.write(target, "new")

    assert len(refusals) == 2
    assert pauses == [pytest.approx(0.01), pytest.approx(0.02)]
    assert target.read_text(encoding="utf-8") == "new"
    assert _only(tmp_path) == ["record.json"]


def test_on_windows_a_busy_or_forbidden_target_counts_as_held_too(tmp_path, monkeypatch):
    monkeypatch.setattr(atomic_file, "WINDOWS", True)
    monkeypatch.setattr(atomic_file.time, "sleep", lambda s: None)
    for code in (errno.EPERM, errno.EBUSY):
        replace, refusals = _held(1, code)
        monkeypatch.setattr(atomic_file.os, "replace", replace)
        target = tmp_path / f"record-{code}.json"
        atomic_file.write(target, "new")
        assert refusals == [code]
        assert target.read_text(encoding="utf-8") == "new"


def test_the_pause_grows_by_a_step_per_attempt_up_to_a_tenth_of_a_second(tmp_path, monkeypatch):
    monkeypatch.setattr(atomic_file, "WINDOWS", True)
    replace, _ = _held(12)
    monkeypatch.setattr(atomic_file.os, "replace", replace)
    pauses: list[float] = []
    monkeypatch.setattr(atomic_file.time, "sleep", pauses.append)
    atomic_file.write(tmp_path / "record.json", "new")
    assert pauses == [pytest.approx(min(0.1, 0.01 * n)) for n in range(1, 13)]


def test_on_windows_a_target_held_past_the_minute_is_raised_and_the_file_stays(tmp_path, monkeypatch):
    monkeypatch.setattr(atomic_file, "WINDOWS", True)
    replace, refusals = _held(10_000)
    monkeypatch.setattr(atomic_file.os, "replace", replace)
    monkeypatch.setattr(atomic_file.time, "sleep", lambda s: None)
    clock = iter(range(0, 100_000, 20))
    monkeypatch.setattr(atomic_file.time, "monotonic", lambda: float(next(clock)))
    target = tmp_path / "record.json"
    target.write_text("old", encoding="utf-8")

    with pytest.raises(PermissionError):
        atomic_file.write(target, "new")

    # The budget, not the count, ends it: the clock above hands out 20 s a
    # read, so the minute is over after a handful of attempts.
    assert 2 <= len(refusals) <= 6
    assert target.read_text(encoding="utf-8") == "old"
    assert _only(tmp_path) == ["record.json"]


def test_on_posix_a_refused_rename_is_raised_at_once(tmp_path, monkeypatch):
    """The silence probe: no retry where the system means the refusal."""
    monkeypatch.setattr(atomic_file, "WINDOWS", False)
    replace, refusals = _held(1)
    monkeypatch.setattr(atomic_file.os, "replace", replace)
    slept: list[float] = []
    monkeypatch.setattr(atomic_file.time, "sleep", slept.append)
    target = tmp_path / "record.json"
    target.write_text("old", encoding="utf-8")
    with pytest.raises(PermissionError):
        atomic_file.write(target, "new")
    assert refusals == [errno.EACCES]
    assert slept == []
    assert target.read_text(encoding="utf-8") == "old"
    assert _only(tmp_path) == ["record.json"]


# --- across devices ---------------------------------------------------------


def _other_device_once():
    """A rename that fails across devices once — the first side file's — and
    goes through for the one made beside the target."""
    real = os.replace
    crossed: list[str] = []

    def replace(src, dst):
        if not crossed:
            crossed.append(str(src))
            raise OSError(errno.EXDEV, "Invalid cross-device link")
        return real(src, dst)

    return replace, crossed


def test_a_rename_across_devices_copies_the_file_and_drops_the_side_file(tmp_path, monkeypatch):
    replace, crossed = _other_device_once()
    monkeypatch.setattr(atomic_file.os, "replace", replace)
    target = tmp_path / "record.json"
    target.write_text("old", encoding="utf-8")
    atomic_file.write(target, "new")
    assert len(crossed) == 1
    assert target.read_text(encoding="utf-8") == "new"
    assert _only(tmp_path) == ["record.json"]


def test_a_copy_across_devices_that_breaks_off_leaves_the_old_file_whole(tmp_path, monkeypatch):
    replace, _ = _other_device_once()

    def disk_full(src, dst, *args, **kwargs):
        Path(dst).write_bytes(b"half")
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(atomic_file.os, "replace", replace)
    monkeypatch.setattr(atomic_file.shutil, "copyfile", disk_full)
    target = tmp_path / "record.json"
    target.write_text("old", encoding="utf-8")
    with pytest.raises(OSError):
        atomic_file.write(target, "new")
    assert target.read_text(encoding="utf-8") == "old"
    assert _only(tmp_path) == ["record.json"]


def test_a_file_already_written_is_moved_onto_its_name_the_same_way(tmp_path, monkeypatch):
    """``rename_onto`` for a side file somebody else wrote (a scaled
    picture, a download): the same retry, the same copy across devices."""
    monkeypatch.setattr(atomic_file, "WINDOWS", True)
    replace, refusals = _held(1)
    monkeypatch.setattr(atomic_file.os, "replace", replace)
    monkeypatch.setattr(atomic_file.time, "sleep", lambda s: None)
    side = tmp_path / "picture-part.jpg"
    side.write_bytes(b"jpg")
    target = tmp_path / "picture.jpg"
    atomic_file.rename_onto(side, target)
    assert refusals == [errno.EACCES]
    assert target.read_bytes() == b"jpg"
    assert not side.exists()


# --- the side file's name ---------------------------------------------------


def test_a_side_file_is_hidden_marked_and_told_apart_from_the_files_it_lies_beside():
    name = atomic_file.side_file_name("agentendock.json")
    assert name.startswith(".agentendock.json.") and name.endswith(".tmp")
    assert atomic_file.is_side_file(name)
    assert atomic_file.is_side_file(name, "agentendock.json")
    assert not atomic_file.is_side_file(name, "other.json")
    assert not atomic_file.is_side_file("agentendock.json")
    assert not atomic_file.is_side_file("report.tmp")
    assert not atomic_file.is_side_file(".hidden-note.md")


# --- the one way ------------------------------------------------------------


def _renames_onto_a_name(call: ast.Call) -> bool:
    """A rename of a path: ``os.replace(a, b)``, or ``x.replace(y)`` with one
    plain argument — a text's ``replace`` takes two, a dataclass's or a
    datetime's takes keywords."""
    function = call.func
    if not isinstance(function, ast.Attribute) or function.attr != "replace":
        return False
    if call.keywords:
        return False
    if isinstance(function.value, ast.Name) and function.value.id == "os":
        return True
    return len(call.args) == 1


def test_no_file_in_the_program_is_renamed_onto_its_name_past_the_one_way():
    """Every side file in ``app/`` reaches its name through this module:
    one place for the Windows retry and the copy across devices, not
    fourteen that each lack them."""
    elsewhere: list[str] = []
    for file in sorted(APP.rglob("*.py")):
        if file.name == "atomic_file.py":
            continue
        tree = ast.parse(file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _renames_onto_a_name(node):
                elsewhere.append(f"{file.relative_to(APP)}:{node.lineno}")
    assert elsewhere == [], f"renames past app/atomic_file.py: {elsewhere}"


# --- the callers that must not wait on the event loop -------------------------
#
# ``rename_onto`` waits on Windows while the target is held (up to a minute).
# A plain function may wait; a coroutine may not, because the whole service
# answers nothing while it does. So every async caller hands the write to a
# thread (``asyncio.to_thread``), and the plain callers keep calling directly.


def _writes_through_the_one_way(call: ast.Call) -> bool:
    func = call.func
    return (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id == "atomic_file"
        and func.attr in {"write", "rename_onto"}
    )


def _blocking_calls_in_coroutines(tree: ast.AST) -> list[int]:
    """Lines inside ``async def`` bodies that call the one way directly — or a
    plain function of the same module that does so (a wrapper like
    ``_atomar_schreiben`` blocks the loop exactly as the write itself)."""
    wrappers = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and any(
            isinstance(inner, ast.Call) and _writes_through_the_one_way(inner)
            for inner in ast.walk(node)
        )
    }
    lines: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        for inner in _own_body(node):
            if not isinstance(inner, ast.Call):
                continue
            if _writes_through_the_one_way(inner) or (
                isinstance(inner.func, ast.Name) and inner.func.id in wrappers
            ):
                lines.add(inner.lineno)
    return sorted(lines)


def _own_body(node: ast.AST):
    """The nodes of one function, not of the functions defined inside it: a
    helper a coroutine defines and hands to a thread is the thread's."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        yield child
        yield from _own_body(child)


def test_no_coroutine_in_the_program_writes_through_the_one_way_on_the_loop():
    """The memory tool, the skill tool and the three provider routes hand the
    write to a thread; nothing async calls it (or a wrapper of it) directly."""
    offenders: list[str] = []
    for file in sorted(APP.rglob("*.py")):
        tree = ast.parse(file.read_text(encoding="utf-8"))
        for line in _blocking_calls_in_coroutines(tree):
            offenders.append(f"{file.relative_to(APP)}:{line}")
    assert offenders == [], f"writes on the event loop: {offenders}"


def test_the_plain_callers_still_write_directly():
    """The silence side: a plain function has no loop to hold, so Config,
    Ordnerwissen, Speicherorte and the dock call the one way as before,
    not through a thread."""
    for name in ("config.py", "ordnerwissen.py", "speicherorte.py", "agentendock.py"):
        tree = ast.parse((APP / name).read_text(encoding="utf-8"))
        direct = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and _writes_through_the_one_way(node)
        ]
        assert direct, f"{name} no longer writes through app/atomic_file.py"
        assert _blocking_calls_in_coroutines(tree) == []


@pytest.fixture
def to_thread_spy(monkeypatch):
    """Records what the program hands to ``asyncio.to_thread`` and lets the
    real thread do the work, so the result is the same as before."""
    seen: list = []
    real = asyncio.to_thread

    async def spy(func, /, *args, **kwargs):
        seen.append(func)
        return await real(func, *args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", spy)
    return seen


async def test_the_memory_tool_writes_in_a_thread_and_the_entry_lands(tmp_path, to_thread_spy):
    from app.tools import memory

    pfad = tmp_path / "memory.md"
    antwort = await memory.ausfuehren({"text": "Mag Tee.", "kind": "fact"}, pfad, zeigen=True)
    assert antwort == "Saved."
    assert to_thread_spy == [atomic_file.write]
    assert "Mag Tee." in pfad.read_text(encoding="utf-8")
    assert _only(tmp_path) == ["memory.md"]


async def test_the_skill_tool_writes_in_a_thread_and_the_skill_lands(tmp_path, to_thread_spy):
    from app import skills
    from app.tools import skill

    mein = tmp_path / "mein"
    mein.mkdir()
    antwort = await skill.schreiben(
        {"name": "release", "description": "Vor dem Ausliefern", "instruction": "Erst Tests."},
        mein,
    )
    assert antwort.startswith("Saved")
    assert to_thread_spy == [atomic_file.write]
    assert "Erst Tests." in (mein / "release" / skills.SKILL_DATEI).read_text(encoding="utf-8")
    assert _only(mein / "release") == [skills.SKILL_DATEI]


def test_the_provider_routes_write_in_a_thread_under_one_lock_and_the_file_follows(
    client, tmp_path, monkeypatch, to_thread_spy
):
    """Adding, capabilities, context, time limit and removal each rewrite
    config.yaml — in a thread, under the one lock (the loop is free while
    the thread writes, and a route reading the file in that gap would lose
    a change), and the file carries what the route was told."""
    import yaml

    from app import paketierung
    from app.api.v1 import anbieter

    echt = anbieter._atomar_schreiben

    def under_the_lock(konfig_datei, rohdaten):
        assert anbieter._schleuse.locked(), "the write runs outside the lock"
        echt(konfig_datei, rohdaten)

    monkeypatch.setattr(anbieter, "_atomar_schreiben", under_the_lock)
    monkeypatch.setattr(paketierung, "daten", lambda: tmp_path)
    datei = tmp_path / "config.yaml"
    datei.write_text("endpoints: []\n", encoding="utf-8")
    monkeypatch.setenv("EIGENE_API_KEY", "vorher")
    client.post(
        "/api/v1/providers",
        json={
            "art": "eigen",
            "kennung": "eigene",
            "url": "http://127.0.0.1:9/v1",
            "schluessel": "sk-test-1234",
        },
    )

    def eintrag():
        for e in yaml.safe_load(datei.read_text(encoding="utf-8"))["endpoints"]:
            if e["id"] == "eigene":
                return e
        return None

    assert eintrag()["id"] == "eigene"
    assert client.put("/api/v1/providers/eigene/capabilities", json={"vision": True}).status_code == 200
    assert eintrag()["capabilities"]["vision"] is True
    assert client.put("/api/v1/providers/eigene/context", json={"context_tokens": 4096}).status_code == 200
    assert eintrag()["context_tokens"] == 4096
    assert client.put("/api/v1/providers/eigene/timeout", json={"timeout_enabled": False}).status_code == 200
    assert eintrag()["timeout_enabled"] is False
    assert client.delete("/api/v1/providers/eigene").status_code == 204
    assert eintrag() is None
    assert to_thread_spy.count(under_the_lock) == 5
    assert not any(atomic_file.is_side_file(p.name) for p in tmp_path.iterdir())
