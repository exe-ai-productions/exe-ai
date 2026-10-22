"""The state of the web app page (frontend/src/lib/webapp.svelte.js): what it
takes from the service's answers, how it reads a refusal, and when it hands
the Tailscale sign-in address to the browser.

The shipped module is compiled and run in node with only what it talks to
replaced: the API calls and the browser's `window.open`.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest

WURZEL = Path(__file__).resolve().parents[1]
FRONTEND = WURZEL / "frontend"
MODUL = FRONTEND / "src" / "lib" / "webapp.svelte.js"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not (FRONTEND / "node_modules").is_dir(),
    reason="no Node or no frontend dependencies on this machine",
)


@contextmanager
def _scratch_dir():
    folder = FRONTEND / "node_modules" / f".scratch-webapp-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        yield folder
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def _snapshot(*, running=False, address="", connected=False, login_url="", password=True, qr=""):
    return {
        "tailscale": {"connected": connected, "kind": "own", "login_url": login_url},
        "service": {"running": running, "address": address, "qr": qr},
        "password": password,
        "password_min": 8,
    }


def _run(js: str, answers: dict) -> dict:
    """Run `js` against the shipped module. `answers` maps each call to a
    list of answers handed out in order: a dict is an answer, a string is a
    refusal with that message. The script sees `m` (the module) and
    `opened` (the addresses given to the browser)."""
    with _scratch_dir() as folder:
        built = folder / "built.mjs"
        (folder / "api.mjs").write_text(
            textwrap.dedent(
                """
                const answers = %s
                const take_next = (name) => async () => {
                  if (name === 'state') globalThis.__reads = (globalThis.__reads || 0) + 1
                  const answer = answers[name].length > 1 ? answers[name].shift() : answers[name][0]
                  if (answer && answer._delay) await new Promise((done) => setTimeout(done, answer._delay))
                  if (typeof answer === 'string') throw new Error(answer)
                  return answer
                }
                export const api = {
                  webApp: {
                    state: take_next('state'),
                    setPassword: take_next('setPassword'),
                    start: take_next('start'),
                    stop: take_next('stop'),
                    startTailscale: take_next('startTailscale'),
                  },
                }
                """
            )
            % json.dumps(answers),
            encoding="utf-8",
        )
        driver = folder / "check.mjs"
        driver.write_text(
            textwrap.dedent(
                """
                import { compileModule } from 'svelte/compiler'
                import { readFileSync, writeFileSync } from 'fs'
                const opened = []
                globalThis.window = { open: (address) => opened.push(address) }
                const built = compileModule(readFileSync(%r, 'utf-8'), {
                  filename: 'webapp.svelte.js', generate: 'client',
                })
                writeFileSync(%r, built.js.code.replace('./api.js', './api.mjs'))
                const m = await import('./built.mjs')
                let report = {}
                %s
                console.log('---REPORT---' + JSON.stringify({ ...report, opened }))
                """
            )
            % (str(MODUL), str(built), js),
            encoding="utf-8",
        )
        result = subprocess.run(
            ["node", driver.name], cwd=folder, capture_output=True, text=True, encoding="utf-8", timeout=120
        )
    assert result.returncode == 0, (result.stdout + result.stderr)[-2000:]
    return json.loads(result.stdout.split("---REPORT---", 1)[1].strip())


def _with_state(js: str) -> str:
    return js + "\nreport = { ...report, state: JSON.parse(JSON.stringify(m.webapp)) }"


def test_the_answer_is_taken_in_as_it_comes():
    report = _run(
        _with_state("await m.webappLoad()"),
        {
            "state": [
                _snapshot(
                    running=True, address="https://exe.tailnet-name.ts.net", connected=True, qr="<svg></svg>"
                )
            ]
        },
    )
    state = report["state"]
    assert state["loaded"] is True
    assert state["passwordMin"] == 8
    assert state["running"] is True
    assert state["address"] == "https://exe.tailnet-name.ts.net"
    assert state["qr"] == "<svg></svg>"
    assert state["tailscale"] == {"connected": True, "kind": "own", "loginUrl": ""}


def test_a_missed_read_leaves_the_rows_standing():
    """The page asks again and again; one answer that does not come must not
    blank what it shows — nor show an error where nothing was done."""
    report = _run(
        _with_state("await m.webappLoad()\nawait m.webappLoad()"),
        {"state": [_snapshot(password=True), "not_answering"]},
    )
    assert report["state"]["password"] is True
    assert report["state"]["error"] == {"reason": "", "detail": ""}


def test_a_read_that_fails_first_shows_its_reason():
    report = _run(_with_state("await m.webappLoad()"), {"state": ["from_this_machine_only"]})
    assert report["state"]["loaded"] is False
    assert report["state"]["error"]["reason"] == "from_this_machine_only"


def test_a_refusal_is_split_into_its_reason_and_what_tailscale_said():
    report = _run(
        _with_state("await m.webappStartService()"),
        {"start": ["serve_failed: HTTPS is not enabled: https://login.example/enable"]},
    )
    assert report["state"]["error"] == {
        "reason": "serve_failed",
        "detail": "HTTPS is not enabled: https://login.example/enable",
    }


def test_a_refusal_without_detail_has_none():
    report = _run(_with_state("await m.webappStartService()"), {"start": ["no_password"]})
    assert report["state"]["error"] == {"reason": "no_password", "detail": ""}


def test_the_next_action_clears_the_error_of_the_one_before():
    report = _run(
        _with_state("await m.webappStartService()\nawait m.webappSetPassword('x')"),
        {"start": ["no_password"], "setPassword": [_snapshot(password=True)]},
    )
    assert report["state"]["error"] == {"reason": "", "detail": ""}
    assert report["state"]["password"] is True


def test_the_sign_in_address_goes_to_the_browser_once():
    """Starting hands it over; the polls that still see the same address do
    not open it a second time, and the button opens it on purpose."""
    waiting = _snapshot(login_url="https://login.example/a")
    report = _run(
        _with_state(
            "await m.webappStartService()\n"
            "await m.webappLoad()\n"
            "await m.webappStartTailscale()\n"
            "m.openSignIn(true)"
        ),
        {"start": [waiting], "state": [waiting], "startTailscale": [waiting]},
    )
    assert report["opened"] == ["https://login.example/a", "https://login.example/a"]


def test_a_connected_tailscale_opens_nothing_and_a_new_sign_in_may_open_again():
    connected_state = _snapshot(connected=True, running=True, address="https://exe.tailnet-name.ts.net")
    report = _run(
        _with_state(
            "await m.webappStartService()\n"
            "await m.webappStartTailscale()\n"
            "await m.webappLoad()\n"
            "m.openSignIn(true)"
        ),
        {
            "start": [_snapshot(login_url="https://login.example/a")],
            "startTailscale": [connected_state],
            "state": [_snapshot(login_url="https://login.example/b")],
        },
    )
    assert report["opened"] == ["https://login.example/a", "https://login.example/b"]
    assert report["state"]["tailscale"]["connected"] is False


def test_only_one_action_runs_at_a_time():
    report = _run(
        _with_state(
            "const first = m.webappSetPassword('x')\n"
            "const second = await m.webappStartService()\n"
            "report.second = second\n"
            "await first"
        ),
        {"setPassword": [_snapshot()], "start": [_snapshot(running=True)]},
    )
    assert report["second"] is False
    assert report["state"]["running"] is False
    assert report["state"]["busy"] == ""


def test_a_first_read_that_failed_is_forgiven_by_the_next_one_that_works():
    report = _run(
        _with_state("await m.webappLoad()\nawait m.webappLoad()"),
        {"state": ["not_answering", _snapshot(password=True)]},
    )
    assert report["state"]["loaded"] is True
    assert report["state"]["error"] == {"reason": "", "detail": ""}


def test_a_read_sent_before_an_action_does_not_put_the_older_state_back():
    """The poll's answer comes in late: what the action answered is newer."""
    report = _run(
        _with_state(
            "const slow = m.webappLoad()\n"
            "await m.webappStopService()\n"
            "await slow"
        ),
        {
            "state": [{**_snapshot(running=True, address="https://x.example"), "_delay": 60}],
            "stop": [_snapshot(running=False)],
        },
    )
    assert report["state"]["running"] is False
    assert report["state"]["address"] == ""


def test_a_read_is_not_started_while_another_is_on_its_way():
    report = _run(
        _with_state(
            "const slow = m.webappLoad()\n"
            "await m.webappLoad()\n"
            "await slow\n"
            "report.reads = globalThis.__reads"
        ),
        {"state": [{**_snapshot(password=True), "_delay": 60}]},
    )
    assert report["reads"] == 1


def test_a_second_visit_starts_without_what_the_first_one_left():
    report = _run(
        _with_state("await m.webappStartService()\nm.webappReset()"),
        {"start": ["port_taken"]},
    )
    assert report["state"]["loaded"] is False
    assert report["state"]["error"] == {"reason": "", "detail": ""}


def test_an_address_the_browser_refused_is_tried_again():
    waiting = _snapshot(login_url="https://login.example/a")
    report = _run(
        _with_state(
            "let refused = true\n"
            "globalThis.window.open = (address) => { if (refused) { refused = false; return null } "
            "opened.push(address); return {} }\n"
            "await m.webappStartService()\n"
            "await m.webappStartTailscale()"
        ),
        {"start": [waiting], "startTailscale": [waiting]},
    )
    assert report["opened"] == ["https://login.example/a"]
