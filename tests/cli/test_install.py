"""The command on the path, placed by ``exe install`` — and by the shell on
the app's first start. Both place a link in a folder of the test's own
rather than /usr/local/bin, both say so once, and both are silent the second
time: a link that already points right is not touched.

The shell's placer lives in `fenster-electron/main.js`, which requires
electron; the functions under test are cut out of its source by name and
run in node against the real file system, the way the shell's other tests
do it."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from cli import install
from cli.main import help_text, main
from cli.texts import Texts

ROOT = Path(__file__).resolve().parents[2]
SHELL = ROOT / "fenster-electron" / "main.js"

posix = pytest.mark.skipif(sys.platform == "win32", reason="the link is placed on macOS and Linux")


def _placed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """A folder for the link and a command for it to point at, in place of
    /usr/local/bin and the installed app."""
    link = tmp_path / "bin" / "exe"
    target = tmp_path / "Exe AI.app" / "Contents" / "Resources" / "bin" / "exe"
    target.parent.mkdir(parents=True)
    target.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(install, "LINK", link)
    monkeypatch.setattr(install, "target", lambda: target)
    return link, target


def _run(tmp_path: Path) -> int:
    return main(["install", "--lang", "en"], prefs_path=tmp_path / "cli.json")


@posix
def test_install_places_the_link_and_names_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    link, target = _placed(tmp_path, monkeypatch)
    assert _run(tmp_path) == 0
    assert os.readlink(link) == str(target)
    assert capsys.readouterr().out == Texts("en").t("cli.install_placed", path=link) + "\n"


@posix
def test_a_second_install_keeps_the_link_and_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The silence probe: the link that already points right is the same
    file afterwards, not a new one."""
    link, _target = _placed(tmp_path, monkeypatch)
    _run(tmp_path)
    before = os.lstat(link)
    capsys.readouterr()
    assert _run(tmp_path) == 0
    assert os.lstat(link).st_ino == before.st_ino
    assert capsys.readouterr().out == Texts("en").t("cli.install_kept", path=link) + "\n"


@posix
def test_a_link_pointing_elsewhere_is_replaced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    link, target = _placed(tmp_path, monkeypatch)
    link.parent.mkdir()
    link.symlink_to(tmp_path / "older" / "exe")
    assert _run(tmp_path) == 0
    assert os.readlink(link) == str(target)


@posix
def test_a_file_that_is_no_link_is_left_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    link, _target = _placed(tmp_path, monkeypatch)
    link.parent.mkdir()
    link.write_text("somebody else's", encoding="utf-8")
    assert _run(tmp_path) == 1
    assert link.read_text(encoding="utf-8") == "somebody else's"
    assert str(link) in capsys.readouterr().err


@posix
@pytest.mark.skipif(getattr(os, "geteuid", lambda: 1)() == 0, reason="root is refused nothing")
def test_without_rights_install_names_the_line_to_run_as_administrator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    link, target = _placed(tmp_path, monkeypatch)
    link.parent.mkdir()
    link.parent.chmod(0o500)
    try:
        assert _run(tmp_path) == 1
    finally:
        link.parent.chmod(0o700)
    assert f'sudo "{target}" install' in capsys.readouterr().err
    assert not link.exists()


@posix
def test_a_command_that_is_not_there_gets_no_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A link to nothing would be reported as the command's place."""
    link, target = _placed(tmp_path, monkeypatch)
    target.unlink()
    assert _run(tmp_path) == 1
    assert not link.is_symlink() and not link.parent.exists()
    said = capsys.readouterr()
    assert said.out == "" and str(target) in said.err


@posix
def test_from_source_there_is_nothing_to_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(install, "LINK", tmp_path / "bin" / "exe")
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert _run(tmp_path) == 1
    assert capsys.readouterr().err == Texts("en").t("cli.install_source") + "\n"
    assert not (tmp_path / "bin").exists()


def test_packaged_the_command_lies_beside_the_programs_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Falls over with the one-file layout: the program lies in a folder of
    its own, Resources/exe-ai-terminal/Exe AI, and the command one level
    above that folder, in Resources/bin."""
    resources = (tmp_path / "Exe AI.app" / "Contents" / "Resources").resolve()
    program = resources / "exe-ai-terminal" / "Exe AI"
    program.parent.mkdir(parents=True)
    program.write_text("", encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(program))
    assert install.target() == resources / "bin" / "exe"


def test_on_windows_install_points_at_the_installer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    link, _target = _placed(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "platform", "win32")
    assert _run(tmp_path) == 0
    assert capsys.readouterr().out == Texts("en").t("cli.install_windows") + "\n"
    assert not link.exists()


def test_help_names_install() -> None:
    assert re.search(r"^  install\s", help_text(Texts("en")), re.M)


# --- the shell: the link on the app's first start ---------------------------


def _piece(pattern: str, name: str) -> str:
    match = re.search(pattern, SHELL.read_text(encoding="utf-8"), re.S)
    assert match, f"{name} not found"
    return match.group(0).strip() + "\n"


def _placer_pieces() -> str:
    return "\n".join([
        _piece(r"\nconst CLI_LINK = .*?\n", "CLI_LINK"),
        _piece(r"\nfunction cliLinkRead\(link\) \{\n.*?\n\}\n", "cliLinkRead"),
        _piece(r"\nfunction cliLinkTargetStays\(target\) \{\n.*?\n\}\n", "cliLinkTargetStays"),
        _piece(r"\nconst CLI_LINK_DECLINES = .*?\n", "CLI_LINK_DECLINES"),
        _piece(r"\nconst CLI_LINK_PROMPT = .*?\n", "CLI_LINK_PROMPT"),
        _piece(r"\nconst shellWord = .*?\n", "shellWord"),
        _piece(r"\nconst appleScriptWord = .*?\n", "appleScriptWord"),
        _piece(r"\nfunction cliLinkScript\(link, target\) \{\n.*?\n\}\n", "cliLinkScript"),
        _piece(r"\nfunction cliLinkDeclinesRead\(file\) \{\n.*?\n\}\n", "cliLinkDeclinesRead"),
        _piece(r"\nfunction cliLinkDeclineKeep\(file, declined\) \{\n.*?\n\}\n", "cliLinkDeclineKeep"),
        _piece(r"\nasync function cliLinkPlace\(\{\n.*?\n\}\n", "cliLinkPlace"),
    ])


def _shell_places(
    tmp_path: Path, *, rounds: str, rights: bool = True, elevates: bool = False,
    read_only: bool = False,
) -> dict:
    """Runs the shell's placer in node, ``rounds`` times in a row in the
    same folder (``p`` = place, ``e`` = make the link point elsewhere first,
    ``f`` = put a plain file there first). Without ``rights``, placing the
    link fails the way a folder of the system's fails, and the stand-in for
    the password window answers ``elevates``. With ``read_only``, the app
    sits where a disk image sits."""
    if not shutil.which("node"):
        pytest.skip("node is missing")
    refuse = "" if rights else """
const refused = new Error('EACCES: permission denied'); refused.code = 'EACCES'
fs.symlinkSync = () => { throw refused }
fs.mkdirSync = () => { throw refused }
"""
    script = f"""
const fs = require('fs')
const path = require('path')
const logged = []
console.log = (line) => logged.push(line)
console.error = (...parts) => logged.push(parts.join(' '))
const spawn = () => {{ throw new Error('the password window itself is not opened here') }}
{_placer_pieces()}
const dir = {json.dumps(str(tmp_path))}
const link = path.join(dir, 'bin', 'exe')
const target = path.join(dir, 'app', 'bin', 'exe')
const memoryFile = path.join(dir, 'cli-link.json')
fs.mkdirSync(path.dirname(target), {{ recursive: true }})
fs.writeFileSync(target, '')
const elevateCalls = []
const elevate = async (l, t) => {{ elevateCalls.push([l, t]); return {json.dumps(elevates)} }}
if ({json.dumps(read_only)}) {{
  const readOnly = new Error('EROFS: read-only file system'); readOnly.code = 'EROFS'
  fs.accessSync = () => {{ throw readOnly }}
}}
{refuse}
;(async () => {{
  const outcomes = []
  const inodes = []
  for (const round of {json.dumps(rounds)}) {{
    if (round === 'e') {{ fs.mkdirSync(path.dirname(link), {{ recursive: true }}); fs.symlinkSync(path.join(dir, 'older', 'exe'), link) }}
    if (round === 'f') {{ fs.mkdirSync(path.dirname(link), {{ recursive: true }}); fs.writeFileSync(link, 'not ours') }}
    outcomes.push(await cliLinkPlace({{ link, target, memoryFile, elevate }}))
    let inode = null
    try {{ inode = fs.lstatSync(link).ino }} catch {{}}
    inodes.push(inode)
  }}
  let pointsAt = null
  try {{ pointsAt = fs.readlinkSync(link) }} catch {{}}
  let memory = null
  try {{ memory = JSON.parse(fs.readFileSync(memoryFile, 'utf8')) }} catch {{}}
  process.stdout.write(JSON.stringify({{ outcomes, logged, pointsAt, target, inodes, elevateCalls, memory }}) + "\\n")
}})()
"""
    run = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=30,
    )
    assert run.returncode == 0, (run.stdout + run.stderr)[-3000:]
    return json.loads(run.stdout.strip().splitlines()[-1])


@posix
def test_the_shell_places_the_link_once_and_keeps_it_silently(tmp_path: Path) -> None:
    result = _shell_places(tmp_path, rounds="pp")
    assert result["outcomes"] == ["placed", "kept"]
    assert result["pointsAt"] == result["target"]
    assert result["logged"] == [f"CLI: link placed at {tmp_path / 'bin' / 'exe'}"]
    assert result["inodes"][0] == result["inodes"][1], "the kept link is the same file"


@posix
def test_the_shell_replaces_a_link_that_points_elsewhere(tmp_path: Path) -> None:
    result = _shell_places(tmp_path, rounds="e")
    assert result["outcomes"] == ["placed"]
    assert result["pointsAt"] == result["target"]


@posix
def test_the_shell_leaves_a_file_that_is_no_link_alone(tmp_path: Path) -> None:
    result = _shell_places(tmp_path, rounds="f")
    assert result["outcomes"] == ["failed"]
    assert (tmp_path / "bin" / "exe").read_text(encoding="utf-8") == "not ours"
    assert len(result["logged"]) == 1 and "not placed" in result["logged"][0]


@posix
def test_without_rights_the_shell_asks_twice_and_then_never_again(tmp_path: Path) -> None:
    result = _shell_places(tmp_path, rounds="ppp", rights=False, elevates=False)
    assert result["outcomes"] == ["declined", "declined", "declined"]
    assert len(result["elevateCalls"]) == 2, "the third start asks no more"
    assert result["memory"] == {"declined": 2}
    assert result["logged"] == [
        "CLI: password window declined (1 of 2)",
        "CLI: password window declined (2 of 2)",
    ]


@posix
def test_without_rights_the_password_window_places_the_link(tmp_path: Path) -> None:
    result = _shell_places(tmp_path, rounds="p", rights=False, elevates=True)
    assert result["outcomes"] == ["placed"]
    assert result["elevateCalls"] == [[str(tmp_path / "bin" / "exe"), str(tmp_path / "app" / "bin" / "exe")]]
    assert result["memory"] is None, "nothing was declined"
    assert result["logged"] == [f"CLI: link placed at {tmp_path / 'bin' / 'exe'} with administrator rights"]


def test_the_shell_knows_one_place_for_the_command() -> None:
    """The command comes with the app and lies at one path. No second bin
    folder is looked into for a link some other installer may have left."""
    source = SHELL.read_text(encoding="utf-8")
    assert source.count("const CLI_LINK = '/usr/local/bin/exe'") == 1
    assert "CLI_LINKS_ELSEWHERE" not in source and "/opt/homebrew" not in source


@posix
def test_from_a_disk_image_the_shell_places_nothing(tmp_path: Path) -> None:
    """An app on a read-only volume is gone once it ends, and a link into it
    with it. Nothing is placed, asked or counted — writable or not."""
    for rights in (True, False):
        folder = tmp_path / str(rights)
        folder.mkdir()
        result = _shell_places(folder, rounds="p", rights=rights, read_only=True)
        assert result["outcomes"] == ["skipped"]
        assert result["pointsAt"] is None
        assert result["elevateCalls"] == [] and result["logged"] == [] and result["memory"] is None


def _password_window_script(link: Path, target: Path) -> str:
    """The script the shell hands to the password window, for that link."""
    if not shutil.which("node"):
        pytest.skip("node is missing")
    script = f"""
const path = require('path')
{_placer_pieces()}
process.stdout.write(JSON.stringify(cliLinkScript({json.dumps(str(link))}, {json.dumps(str(target))})) + "\\n")
"""
    run = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=30,
    )
    assert run.returncode == 0, (run.stdout + run.stderr)[-3000:]
    return json.loads(run.stdout.strip().splitlines()[-1])


ADMINISTRATOR = " with administrator privileges"


def test_the_password_window_is_asked_with_the_reason_and_the_right() -> None:
    script = _password_window_script(Path("/usr/local/bin/exe"), Path("/Applications/Exe AI.app/Contents/Resources/bin/exe"))
    assert script.startswith('do shell script "mkdir -p ')
    assert ' with prompt "Exe AI places the command exe at /usr/local/bin."' in script
    assert script.endswith(ADMINISTRATOR)


@pytest.mark.skipif(sys.platform != "darwin" or not shutil.which("osascript"), reason="the password window is the Mac's")
def test_what_the_password_window_runs_places_the_link(tmp_path: Path) -> None:
    """The script itself, run by the system the way the password window runs
    it — only without the right, in a folder that needs none. The paths
    carry what an installed app's path carries and what would end a quoted
    word early: a space, a single and a double quote, a backslash."""
    folder = tmp_path / "it's a \"folder\" with \\ in it"
    link = folder / "bin" / "exe"
    target = folder / "Exe AI.app" / "Contents" / "Resources" / "bin" / "exe"
    target.parent.mkdir(parents=True)
    target.write_text("#!/bin/sh\n", encoding="utf-8")
    script = _password_window_script(link, target)
    assert script.endswith(ADMINISTRATOR)
    as_the_user = script[: -len(ADMINISTRATOR)]

    def run() -> None:
        done = subprocess.run(["osascript", "-e", as_the_user], capture_output=True, text=True, timeout=60)
        assert done.returncode == 0, done.stderr

    run()
    assert os.readlink(link) == str(target)
    # Over a link that points elsewhere — a folder even: replaced, not entered.
    link.unlink()
    (folder / "older").mkdir()
    link.symlink_to(folder / "older")
    run()
    assert os.readlink(link) == str(target)
    assert list((folder / "older").iterdir()) == []


def test_the_shell_places_the_link_only_on_the_installed_mac_app() -> None:
    """Read off the source: the call sits in the start, behind the platform
    and the packaged check — a dev run has no app to point at, and Windows
    has its installer."""
    source = SHELL.read_text(encoding="utf-8")
    assert "if (process.platform === 'darwin' && app.isPackaged) cliLinkPlace()" in source
    assert source.count("cliLinkPlace()") == 1
