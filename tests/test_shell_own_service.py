"""A command that speaks to this program's own service over the loopback
address is stopped. The service hands out its session key on its page, and
with the key everything behind it — chats, memory, the prompt, the tool
settings — answers a plain ``curl``. The stop follows the port the service
listens on; another port and the port without a host stay free."""

from __future__ import annotations

import pytest

from app.tools import WerkzeugRegistry, WerkzeugVerboten, shell

PORT = 8399
OTHER_PORT = 8391


@pytest.mark.parametrize(
    "line",
    [
        f"curl -s http://127.0.0.1:{PORT}/app/",
        f"curl localhost:{PORT}/api/v1/chats",
        f"curl http://[::1]:{PORT}/",
        f"wget 0.0.0.0:{PORT}",
        f"curl 127.1:{PORT}",
        f"curl -s HTTP://LOCALHOST:{PORT}/app/",
        f"cd work && curl 127.0.0.1:{PORT}/api/v1/memory | head",
        f"python3 -c \"import urllib.request as u; u.urlopen('http://127.0.0.1:{PORT}/app/')\"",
    ],
)
def test_a_command_to_the_loopback_address_and_the_port_of_the_service_is_stopped(line):
    assert shell.blockiert(line, PORT) == shell.OWN_SERVICE


@pytest.mark.parametrize(
    "line",
    [
        f"curl 127.0.0.1:{OTHER_PORT}/",
        f"curl localhost:{PORT}0/",
        f"echo {PORT}",
        f"curl http://example.com:{PORT}/",
        "curl https://example.com",
        f"ls 10.0.0.127:{PORT}",
        "curl 127.0.0.1/",
    ],
)
def test_another_port_another_host_and_the_port_alone_are_free(line):
    assert shell.blockiert(line, PORT) is None


def test_without_a_port_nothing_is_stopped_that_was_not_before():
    assert shell.blockiert(f"curl 127.0.0.1:{PORT}/app/") is None
    assert shell.blockiert(f"curl 127.0.0.1:{PORT}/app/", None) is None


def test_the_old_patterns_stand_beside_it():
    assert shell.blockiert("sudo ls", PORT) == "sudo"


async def test_the_tool_refuses_with_the_name_of_the_reason(tmp_path):
    folder = tmp_path / "work"
    folder.mkdir()
    with pytest.raises(shell.ShellVerboten) as refused:
        await shell.ausfuehren(
            {"command": f"curl -s http://127.0.0.1:{PORT}/app/"}, [str(folder)],
            data_dir=tmp_path / "data", service_port=PORT,
        )
    assert shell.OWN_SERVICE in str(refused.value)
    assert "regardless of permissions" in str(refused.value)


async def test_the_registry_hands_the_port_of_the_service_to_the_tool(tmp_path):
    folder = tmp_path / "work"
    folder.mkdir()
    registry = WerkzeugRegistry([], shell_an=True, service_port=PORT)
    with pytest.raises(WerkzeugVerboten) as refused:
        await registry.ausfuehren(
            shell.WERKZEUG_NAME, {"command": f"curl 127.0.0.1:{PORT}/app/"}, ordner=[str(folder)]
        )
    assert shell.OWN_SERVICE in str(refused.value)


async def test_the_silence_probe_a_command_to_another_port_runs(tmp_path):
    """The command is run, not stopped: nothing listens there, so curl fails —
    and that is the shell's answer, not a refusal."""
    folder = tmp_path / "work"
    folder.mkdir()
    registry = WerkzeugRegistry([], shell_an=True, service_port=PORT)
    shown = await registry.ausfuehren(
        shell.WERKZEUG_NAME, {"command": f"echo {PORT}"}, ordner=[str(folder)]
    )
    assert str(PORT) in shown
