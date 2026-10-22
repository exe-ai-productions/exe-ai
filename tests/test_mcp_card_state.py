"""The state the MCP gallery gives a card, and the words it draws for it.

`zustand`, `stateText` and `stateHead` are the rules of lib/mcpCards.js (one place
for the MCP page and the server overview) and run in node as written: the rules
were otherwise pinned by nothing but a template substring.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parent.parent
VERBINDUNGEN = WURZEL / "frontend" / "src" / "teile" / "Verbindungen.svelte"
MCP_CARDS = WURZEL / "frontend" / "src" / "lib" / "mcpCards.js"
MASKE = WURZEL / "frontend" / "src" / "teile" / "MCPMaske.svelte"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed here")


def _run(body: str) -> object:
    script = f"""
import {{ zustand as stateOf, stateText as textOf, stateHead as headOf }} from '{MCP_CARDS.as_uri()}'
const WORDS = {{
  'verbindungen.stand_schluessel_fehlt': 'Schluessel fehlt:',
  'verbindungen.stand_getrennt': 'Nicht verbunden',
  'verbindungen.stand_wartet': 'Startet ...',
}}
const t = (key) => WORDS[key] ?? key
let status = {{}}
const zustand = (k) => stateOf(k, status)
const stateText = (k, stand) => textOf(k, stand, t)
const stateHead = (stand) => headOf(stand, t)
console.log(JSON.stringify((() => {{ {body} }})()))
"""
    done = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


OWN = "{ katalog: null, eintrag: { name: 'own', type: 'http', url: 'https://x.invalid/mcp', enabled: true, auth: 'oauth', schluessel_gesetzt: null, laeuft: false } }"


def test_an_own_address_that_wants_a_sign_in_stands_disconnected_without_one():
    assert _run(f"return zustand({OWN})") == "getrennt"


def test_silence_the_same_entry_with_a_valid_sign_in_is_not_disconnected():
    assert _run(f"""
      status = {{ own: {{ verbunden: true }} }}
      const k = {OWN}
      const waiting = zustand(k)
      k.eintrag.laeuft = true
      return [waiting, zustand(k)]
    """) == ["wartet", "verbunden"]


def test_silence_an_own_program_server_and_an_own_address_without_a_sign_in_stay_as_they_were():
    assert _run("""
      const program = { katalog: null, eintrag: { name: 'p', type: 'stdio', enabled: true, auth: 'oauth', schluessel_gesetzt: null, laeuft: false } }
      const plain = { katalog: null, eintrag: { name: 'q', type: 'http', url: 'https://x.invalid/mcp', enabled: true, auth: null, schluessel_gesetzt: null, laeuft: false } }
      const running = { katalog: null, eintrag: { name: 'p', type: 'stdio', enabled: true, auth: null, schluessel_gesetzt: null, laeuft: true } }
      return [zustand(program), zustand(plain), zustand(running)]
    """) == ["wartet", "wartet", "verbunden"]


def test_the_card_names_the_missing_keys_behind_the_state_and_the_menu_head_drops_the_colon():
    result = _run("""
      const k = { katalog: null, eintrag: { name: 'g', type: 'http', enabled: true, schluessel_gesetzt: false, missing_keys: ['GITHUB_TOKEN', 'X_KEY'], laeuft: false } }
      const stand = zustand(k)
      return { stand, card: stateText(k, stand), head: stateHead(stand), other: stateHead('wartet') }
    """)
    assert result == {
        "stand": "schluessel_fehlt",
        "card": "Schluessel fehlt: GITHUB_TOKEN, X_KEY",
        "head": "Schluessel fehlt",
        "other": "Startet ...",
    }


def test_no_empty_colon_stands_anywhere():
    result = _run("""
      const k = { katalog: null, eintrag: { name: 'g', type: 'http', enabled: true, schluessel_gesetzt: false, missing_keys: [], laeuft: false } }
      return { card: stateText(k, 'schluessel_fehlt'), head: stateHead('schluessel_fehlt') }
    """)
    # With no name to give, the card says the state alone, and the head too.
    assert result["head"] == "Schluessel fehlt"
    assert result["card"] == "Schluessel fehlt"


def test_no_empty_colon_either_where_the_service_sends_no_names_at_all():
    result = _run("""
      const k = { katalog: null, eintrag: { name: 'g', type: 'http', enabled: true, schluessel_gesetzt: false, laeuft: false } }
      return { card: stateText(k, 'schluessel_fehlt') }
    """)
    assert result["card"] == "Schluessel fehlt"


def test_the_sheet_reads_the_sign_in_of_an_own_entry_from_its_auth_field():
    maske = MASKE.read_text(encoding="utf-8")
    assert "quelle.anmeldung === 'oauth' || quelle.auth === 'oauth' ? 'anmeldung'" in maske


def _groups(cards: str) -> object:
    """Run the split into cards and tiles of lib/mcpCards.js on the given list."""
    script = f"""
import {{ setUpCards, notSetUpCards }} from '{MCP_CARDS.as_uri()}'
const status = {{}}
const alle = {cards}
const names = (list) => list.map((k) => (k.katalog ? k.katalog.name : k.eintrag.name))
console.log(JSON.stringify({{ setUp: names(setUpCards(alle, status)), notSetUp: names(notSetUpCards(alle, status)) }}))
"""
    done = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


def _card(name: str, **entry: object) -> str:
    fields = {"name": name, "type": "http", "enabled": True, "schluessel_gesetzt": None, "laeuft": False, **entry}
    return f"{{ katalog: {{ name: '{name}', anmeldung: 'keine' }}, eintrag: {json.dumps(fields)} }}"


def test_a_server_with_an_entry_is_a_card_and_one_without_is_a_tile():
    free = "{ katalog: { name: 'free', anmeldung: 'oauth' }, eintrag: null }"
    result = _groups(f"[{free}, {_card('on', laeuft=True)}]")
    assert result == {"setUp": ["on"], "notSetUp": ["free"]}


def test_the_connected_and_starting_cards_stand_first_and_the_rest_keep_their_order():
    result = _groups(
        "["
        + ", ".join(
            [
                _card("off", enabled=False),
                _card("running", laeuft=True),
                _card("missing", schluessel_gesetzt=False),
                _card("starting"),
            ]
        )
        + "]"
    )
    assert result["setUp"] == ["running", "starting", "off", "missing"]
    assert result["notSetUp"] == []


def test_silence_an_entry_taken_out_turns_its_card_back_into_a_tile():
    """The same server before and after the entry is gone: the split follows
    the entry alone, so removing it moves the server from one group to the other."""
    on_file = _groups(f"[{_card('x', laeuft=True)}]")
    removed = _groups("[{ katalog: { name: 'x', anmeldung: 'keine' }, eintrag: null }]")
    assert on_file == {"setUp": ["x"], "notSetUp": []}
    assert removed == {"setUp": [], "notSetUp": ["x"]}


def _question_run(function: str, answer: str, card: str) -> object:
    """Run the page's own `entfernen` or `vergessen` with the answer given to the question."""
    source = VERBINDUNGEN.read_text(encoding="utf-8")
    body = re.search(rf"\n  async function {function}\(.*?\n  \}}\n", source, re.S).group(0)
    script = f"""
const asked = []
const called = []
const t = (key, params) => key + ' ' + JSON.stringify(params)
const frage = async (text) => {{ asked.push(text); return {answer} }}
const api = {{
  serverEntfernen: async (name) => called.push(['remove', name]),
  oauthVergessen: async (name) => called.push(['forget', name]),
}}
const schliessen = () => {{}}
const laden = async () => {{}}
const nachziehen = () => {{}}
const melde = () => {{}}
const errorSentence = () => ''
let mcpOffen = true
{body}
const entry = {{ name: 'recraft' }}
await {function}(entry, {card})
console.log(JSON.stringify({{ asked, called, mcpOffen }}))
"""
    done = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("function,key", [("entfernen", "entfernen_frage"), ("vergessen", "vergessen_frage")])
def test_the_question_names_the_server_as_its_card_does_and_the_entry_goes_by_the_key(function, key):
    done = _question_run(function, "true", "'Recraft'")
    assert done["asked"] == [f'verbindungen.{key} {{"name":"Recraft"}}']
    assert done["called"] == [["remove" if function == "entfernen" else "forget", "recraft"]]


@pytest.mark.parametrize("function", ["entfernen", "vergessen"])
def test_silence_a_declined_question_removes_and_forgets_nothing(function):
    done = _question_run(function, "false", "'Recraft'")
    assert done["called"] == [] and done["mcpOffen"] is True
