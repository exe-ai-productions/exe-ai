"""The switch "Suspend instructions for this chat" works before the first message.

In a new chat there is no chat row to hold the switch. The value is held in
`zustand.pendingPromptOff`; the first message creates the chat, hands the value
to it (`haltendenWertSetzen`) and only then sends, so the first answer already
runs without the person's own instructions (`app/api/v1/generierung.py` reads
`prompt_aus` on every request). Leaving for another chat, or starting anew,
lets the held value go.

The three functions of `frontend/src/lib/zustand.svelte.js` are lifted out and
run in node against a stand-in for the chat list and the service; the wiring
in the send is read as source.
"""

from __future__ import annotations

import functools
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "frontend/src/lib/zustand.svelte.js"
RUN = ROOT / "frontend/src/lib/chatlauf.svelte.js"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="no node on this machine")


@functools.cache
def _functions() -> str:
    source = STATE.read_text(encoding="utf-8")
    parts = []
    for name in ("promptAusgesetzt", "promptAusUmschalten", "haltendenWertSetzen"):
        match = re.search(rf"\nexport (?:async )?function {name}\(\) \{{\n.*?\n\}}\n", source, re.S)
        assert match, f"{name} not found in {STATE.name}"
        parts.append(match.group(0).strip().replace("export ", "", 1) + "\n")
    return "\n".join(parts)


def _run(script: str, *, chats=None, active=None, held=False, refuse=False):
    state = {"chats": chats or [], "aktiverChat": active, "pendingPromptOff": held}
    program = f"""
const zustand = {json.dumps(state)}
const calls = []
const told = []
const t = (key) => key
const melde = (text, art) => told.push([text, art])
const aktuellerChat = () => zustand.chats.find((c) => c.id === zustand.aktiverChat) || null
const chatAendern = async (id, daten) => {{
  if ({json.dumps(refuse)}) throw new Error('refused')
  calls.push([id, daten])
  const chat = zustand.chats.find((c) => c.id === id)
  Object.assign(chat, daten)
}}
{_functions()}
(async () => {{
  const out = {{}}
  {script}
  out.calls = calls; out.told = told; out.held = zustand.pendingPromptOff
  console.log(JSON.stringify(out))
}})()
"""
    run = subprocess.run(["node", "-e", program], capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, f"{run.stderr}\n{run.stdout}"
    return json.loads(run.stdout)


@needs_node
def test_without_a_chat_the_switch_only_holds_its_value_and_flips_back():
    out = _run("out.first = await promptAusUmschalten(); out.shown = promptAusgesetzt(); await promptAusUmschalten(); out.second = promptAusgesetzt()")
    assert out["first"] is True and out["shown"] is True and out["second"] is False
    assert out["calls"] == [] and out["held"] is False


@needs_node
def test_with_a_chat_open_a_flip_goes_to_the_service_and_settles_what_was_held():
    out = _run(
        "out.before = promptAusgesetzt(); await promptAusUmschalten(); out.after = promptAusgesetzt()",
        chats=[{"id": "c", "prompt_aus": False}], active="c",
    )
    assert out["before"] is False and out["after"] is True
    assert out["calls"] == [["c", {"prompt_aus": True}]]
    # A value still held for the chat counts as set; a flip turns it off for good.
    held = _run(
        "out.before = promptAusgesetzt(); await promptAusUmschalten(); out.after = promptAusgesetzt()",
        chats=[{"id": "c", "prompt_aus": False}], active="c", held=True,
    )
    assert held["before"] is True and held["after"] is False
    assert held["calls"] == [["c", {"prompt_aus": False}]] and held["held"] is False


@needs_node
def test_a_refusal_is_told_and_leaves_the_switch_as_it_was():
    out = _run(
        "out.ok = await promptAusUmschalten(); out.shown = promptAusgesetzt()",
        chats=[{"id": "c", "prompt_aus": False}], active="c", refuse=True,
    )
    assert out["ok"] is False and out["shown"] is False
    assert out["told"] == [["systemprompt.schalter_fehler", "fehler"]]


@needs_node
def test_the_held_value_goes_to_the_chat_the_first_message_made_and_is_spent():
    out = _run(
        "out.ok = await haltendenWertSetzen()",
        chats=[{"id": "c", "prompt_aus": False}], active="c", held=True,
    )
    assert out["ok"] is True and out["calls"] == [["c", {"prompt_aus": True}]] and out["held"] is False


@needs_node
def test_a_refused_hand_over_stops_the_send_and_keeps_the_value_for_the_next_try():
    out = _run(
        "out.ok = await haltendenWertSetzen()",
        chats=[{"id": "c", "prompt_aus": False}], active="c", held=True, refuse=True,
    )
    assert out["ok"] is False and out["held"] is True
    assert out["told"] == [["systemprompt.schalter_fehler", "fehler"]]


@needs_node
def test_silence_nothing_held_means_nothing_sent_and_no_chat_means_nothing_to_hand_to():
    quiet = _run("out.ok = await haltendenWertSetzen()", chats=[{"id": "c", "prompt_aus": False}], active="c")
    assert quiet["ok"] is True and quiet["calls"] == []
    no_chat = _run("out.ok = await haltendenWertSetzen()", held=True)
    assert no_chat["ok"] is True and no_chat["calls"] == [] and no_chat["held"] is True


def test_leaving_the_chat_or_starting_anew_lets_the_held_value_go():
    source = STATE.read_text(encoding="utf-8")
    new_chat = source.split("export function neuerChat() {", 1)[1].split("\n}\n", 1)[0]
    assert "zustand.pendingPromptOff = false" in new_chat
    opening = source.split("export async function chatOeffnen(id) {", 1)[1]
    assert opening.index("zustand.pendingPromptOff = false") < opening.index("if (!id) {")


def test_the_first_message_hands_the_value_over_after_the_chat_exists_and_before_the_run():
    source = RUN.read_text(encoding="utf-8")
    sending = source.split("async function senden(", 1)[1]
    creation = sending.index("await openNewChat(")
    hand_over = sending.index("await haltendenWertSetzen()")
    run = sending.index("const sendeChat = zustand.aktiverChat")
    assert creation < hand_over < run
    block = sending[hand_over - 20 : hand_over + 120]
    assert "giveBack()" in block and "return" in block, "a refusal gives back what was typed and ends the send"
