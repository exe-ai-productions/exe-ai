"""macOS and Windows side by side: nothing in the terminal client may need
what only one of them has.

A module that only a POSIX system ships imports fine on the machine it was
written on and fails on the first start elsewhere. So the client's source is
read here, file by file, for the handful of things that do not exist on
Windows — and the few places where the system does show through are run on
whichever system the suite runs on.
"""

from __future__ import annotations

import ast
import sys
from collections.abc import Callable, Iterator
from pathlib import Path

import httpx
import pytest
from prompt_toolkit.application import create_app_session
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from cli import prefs, status
from cli.interfaces import Context
from cli.main import main
from tests.cli.stub_service import StubService

CLIENT = Path(__file__).resolve().parent.parent.parent / "cli"

# Modules only a POSIX system ships.
POSIX_ONLY_MODULES = {"fcntl", "termios", "tty", "pwd", "grp"}

# What the two modules that exist everywhere offer on a POSIX system only:
# the name of the module, then the name in it.
POSIX_ONLY_NAMES = {("os", "fork"), ("signal", "SIGHUP")}

# The one of them that may be used behind a check for its existence.
MAY_BE_ASKED_FOR = ("signal", "SIGHUP")

Stack = list[tuple[ast.AST, str, int]]


def _walk(node: ast.AST, stack: Stack) -> Iterator[tuple[ast.AST, Stack]]:
    """Every node below ``node`` with the way down to it: each ancestor, the
    field of it the way leads through and the position in that field."""
    yield node, stack
    for field, value in ast.iter_fields(node):
        children = value if isinstance(value, list) else [value]
        for position, child in enumerate(children):
            if isinstance(child, ast.AST):
                yield from _walk(child, [*stack, (node, field, position)])


def _module_names(tree: ast.AST) -> dict[str, str]:
    """The names a file knows a module by: ``import signal as s`` makes
    ``s`` a name for ``signal``."""
    names: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names[alias.asname or alias.name.split(".")[0]] = alias.name.split(".")[0]
    return names


def _asks_whether_it_exists(test: ast.AST, names: dict[str, str]) -> bool:
    """Whether a condition holds only where the name exists: it is
    ``hasattr(signal, "SIGHUP")`` itself, or several conditions that all
    have to hold with that one among them. A check that is negated, or one
    of several of which any may hold, promises nothing."""
    if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.And):
        return any(_asks_whether_it_exists(value, names) for value in test.values)
    if not (isinstance(test, ast.Call) and isinstance(test.func, ast.Name)):
        return False
    if test.func.id != "hasattr" or len(test.args) != 2:
        return False
    module, name = test.args
    return (
        isinstance(module, ast.Name)
        and names.get(module.id) == MAY_BE_ASKED_FOR[0]
        and isinstance(name, ast.Constant)
        and name.value == MAY_BE_ASKED_FOR[1]
    )


def _behind_a_check(stack: Stack, names: dict[str, str]) -> bool:
    """Whether the way down to a node leads through the true side of a
    check for the name's existence."""
    for parent, field, position in stack:
        if isinstance(parent, (ast.If, ast.IfExp)) and field == "body":
            if _asks_whether_it_exists(parent.test, names):
                return True
        if isinstance(parent, ast.BoolOp) and isinstance(parent.op, ast.And):
            if any(_asks_whether_it_exists(value, names) for value in parent.values[:position]):
                return True
    return False


def _imported_by_name(node: ast.Call) -> str | None:
    """The module a call imports by a name written out in it, as in
    ``__import__("fcntl")``."""
    function = node.func
    called = function.id if isinstance(function, ast.Name) else getattr(function, "attr", "")
    if called not in ("__import__", "import_module") or not node.args:
        return None
    first = node.args[0]
    return first.value.split(".")[0] if isinstance(first, ast.Constant) and isinstance(first.value, str) else None


def posix_only_uses(folder: Path) -> list[str]:
    """Every place below ``folder`` that needs a POSIX system, as
    ``file:line  what``."""
    found: list[str] = []
    for path in sorted(folder.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        names = _module_names(tree)

        def report(node: ast.AST, what: str, path: Path = path) -> None:
            found.append(f"{path.relative_to(folder).as_posix()}:{getattr(node, 'lineno', 0)}  {what}")

        for node, stack in _walk(tree, []):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in POSIX_ONLY_MODULES:
                        report(node, f"import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                module = (node.module or "").split(".")[0]
                if module in POSIX_ONLY_MODULES:
                    report(node, f"from {node.module} import …")
                for alias in node.names:
                    if (module, alias.name) in POSIX_ONLY_NAMES:
                        report(node, f"from {module} import {alias.name}")
            elif isinstance(node, ast.Call) and _imported_by_name(node) in POSIX_ONLY_MODULES:
                report(node, f"import of {_imported_by_name(node)} by name")
            elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                use = (names.get(node.value.id, ""), node.attr)
                if use not in POSIX_ONLY_NAMES:
                    continue
                if use == MAY_BE_ASKED_FOR and _behind_a_check(stack, names):
                    continue
                report(node, ".".join(use))
    return found


# --- The client's source ---------------------------------------------------------


def test_nothing_in_the_client_needs_a_posix_system() -> None:
    assert list(CLIENT.rglob("*.py")), "the client's source was not found"
    assert posix_only_uses(CLIENT) == []


@pytest.mark.parametrize(
    ("source", "what"),
    [
        ("import fcntl\n", "import fcntl"),
        ("import os\nimport termios as terminal\n", "import termios"),
        ("from tty import setraw\n", "from tty import …"),
        ("import os, pwd\n", "import pwd"),
        ("def owner():\n    import grp\n    return grp\n", "import grp"),
        ("import os\npid = os.fork()\n", "os.fork"),
        ("import os as system\npid = system.fork()\n", "os.fork"),
        ("from os import fork\n", "from os import fork"),
        ("import signal\nsignal.signal(signal.SIGHUP, print)\n", "signal.SIGHUP"),
        ("import signal as signals\nhangup = signals.SIGHUP\n", "signal.SIGHUP"),
        ("from signal import SIGHUP\n", "from signal import SIGHUP"),
        ('lock = __import__("fcntl")\n', "import of fcntl by name"),
        ('import importlib\nt = importlib.import_module("termios")\n', "import of termios by name"),
        # Asked for, and then used on the side where it does not exist.
        (
            'import signal\nif hasattr(signal, "SIGHUP"):\n    pass\nelse:\n    signal.SIGHUP\n',
            "signal.SIGHUP",
        ),
        # A check for another name guards nothing.
        (
            'import signal\nif hasattr(signal, "SIGTERM"):\n    signal.SIGHUP\n',
            "signal.SIGHUP",
        ),
        # Nor does a check turned round, or one that need not hold.
        (
            'import signal\nif not hasattr(signal, "SIGHUP"):\n    signal.SIGHUP\n',
            "signal.SIGHUP",
        ),
        (
            'import signal\nforce = True\nif hasattr(signal, "SIGHUP") or force:\n    signal.SIGHUP\n',
            "signal.SIGHUP",
        ),
        (
            'import signal\nnot hasattr(signal, "SIGHUP") and signal.SIGHUP\n',
            "signal.SIGHUP",
        ),
    ],
)
def test_the_search_reports_what_only_a_posix_system_has(
    tmp_path: Path, source: str, what: str
) -> None:
    (tmp_path / "deep").mkdir()
    (tmp_path / "deep" / "module.py").write_text(source, encoding="utf-8")
    found = posix_only_uses(tmp_path)
    assert len(found) == 1, found
    assert found[0].startswith("deep/module.py:") and found[0].endswith(f"  {what}")


@pytest.mark.parametrize(
    "source",
    [
        # Behind a check for its existence the name may be used.
        'import signal\nif hasattr(signal, "SIGHUP"):\n    signal.signal(signal.SIGHUP, print)\n',
        'import signal\nhasattr(signal, "SIGHUP") and signal.signal(signal.SIGHUP, print)\n',
        'import signal\nhangup = signal.SIGHUP if hasattr(signal, "SIGHUP") else None\n',
        'import signal as signals\nif hasattr(signals, "SIGHUP"):\n    signals.SIGHUP\n',
        'import signal\nwanted = True\nif wanted and hasattr(signal, "SIGHUP"):\n    signal.SIGHUP\n',
        'import signal\nhangup = getattr(signal, "SIGHUP", None)\n',
        # What exists on both systems.
        "import os\nimport signal\nsignal.signal(signal.SIGINT, print)\nos.getpid()\n",
        "import os.path\nfrom pathlib import Path\n",
        # A name that only looks alike.
        "class Road:\n    fork = 1\n\nroad = Road()\nroad.fork\n",
        # Said, not done.
        '"""Never import fcntl here."""\n# no termios either\nword = "pwd"\n',
    ],
)
def test_the_search_stays_silent_about_what_runs_everywhere(tmp_path: Path, source: str) -> None:
    (tmp_path / "module.py").write_text(source, encoding="utf-8")
    assert posix_only_uses(tmp_path) == []


# --- Where the system shows through -----------------------------------------------


def test_the_remembered_choices_lie_in_the_users_home_on_this_system(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # One of the two names the home is read from on either system.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert Path.home() == tmp_path
    assert prefs.default_path() == tmp_path / ".exe-ai" / "cli.json"
    # The folder does not exist yet; remembering something creates it.
    prefs.remember(None, look="exe")
    assert prefs.load(None)["look"] == "exe"
    assert (tmp_path / ".exe-ai").is_dir()


def test_a_pipe_stands_in_for_the_keyboard_on_this_system(
    stub: StubService, stub_http: httpx.Client, tmp_path: Path
) -> None:
    expected = "Win32PipeInput" if sys.platform == "win32" else "PosixPipeInput"
    with create_pipe_input() as pipe:
        assert type(pipe).__name__ == expected
        # And what is typed into it reaches a running client.
        pipe.send_text("/quit\r")
        with create_app_session(input=pipe, output=DummyOutput()):
            code = main(
                ["--url", "http://stub.test", "--lang", "en"],
                http=stub_http,
                prefs_path=tmp_path / "cli.json",
            )
    assert code == 0
    assert "GET /api/v1/models" in stub.requests


# --- A console that cannot show every character ----------------------------------


@pytest.mark.parametrize(
    ("encoding", "shown"),
    [
        ("utf-8", "–"),
        ("UTF-8", "–"),
        (None, "–"),
        # A Windows code page that has the character.
        ("cp1252", "–"),
        # The console's classic code page, and plain ASCII: neither has it.
        ("cp437", "-"),
        ("ascii", "-"),
        # A name no codec answers to.
        ("no-such-encoding", "-"),
    ],
)
def test_a_sign_the_console_cannot_show_gives_way_to_its_plain_form(
    encoding: str | None, shown: str
) -> None:
    assert status.showable("–", "-", encoding) == shown


class _Console:
    """A standard output that names the encoding it writes in."""

    def __init__(self, encoding: str | None) -> None:
        self.encoding = encoding


def test_the_status_line_reads_the_consoles_encoding_once_at_start(
    ctx: Context, status_line: Callable[..., str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def started_on(encoding: str | None) -> str:
        with monkeypatch.context() as patch:
            patch.setattr(sys, "stdout", _Console(encoding))
            ctx.status = status.build_status(ctx)
        # Built; whatever the output is later no longer matters.
        ctx.status.update(
            chat_title="A long conversation about the plans for the garden in spring",
            model_name="Local Model",
            context_window=131072,
        )
        return status_line(ctx, 60)

    plain = started_on("cp437")
    assert "-/131072" in plain and "... " in plain
    assert "–" not in plain and "…" not in plain

    full = started_on("utf-8")
    assert "–/131072" in full and "… " in full
    assert "..." not in full


def test_a_standard_output_without_an_encoding_is_no_error(
    ctx: Context, status_line: Callable[..., str], monkeypatch: pytest.MonkeyPatch
) -> None:
    with monkeypatch.context() as patch:
        patch.setattr(sys, "stdout", None)
        ctx.status = status.build_status(ctx)
    ctx.status.update(model_name="Local Model", context_window=131072)
    assert "–/131072" in status_line(ctx)
