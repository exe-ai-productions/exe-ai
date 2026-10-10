"""A stream that ends without `done` is a torn one, not a finished answer.

Every complete stream the service sends ends with the `done` event — that is
the event the window hangs the closing state on, the green finished dot and
the release of the queue. A body that simply stops (a proxy that reaped the
connection, a service that died mid-answer, a connection closed cleanly by
some box in between) used to run through `sseLesen` as an ordinary end: the
answer looked finished, the dot went green, and whatever was queued behind
it was sent on top of half an answer.

Driven the way tests/test_sitzung_neu_laden.py drives api.js: the module as
a plain script, a stubbed `window` and a `fetch` that answers the body the
scenario hands it.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from tests.conftest import node_script

from tests import test_openai_provider

# The stub OpenAI-compatible server, borrowed as a fixture.
modellserver = test_openai_provider.modellserver

WURZEL = Path(__file__).resolve().parents[1]
API = WURZEL / "frontend/src/lib/api.js"

# The browser api.js expects, plus a fetch whose body the scenario sets: one
# chunk per entry, delivered as the reader asks for it.
UMGEBUNG = """
globalThis.window = { __SITZUNGSSCHLUESSEL__: 'schluessel', location: { reload() {} } }
globalThis.__stuecke = []
globalThis.__status = 200
globalThis.fetch = async () => {
  let i = 0
  return {
    ok: globalThis.__status === 200,
    status: globalThis.__status,
    json: async () => ({ detail: 'abgelehnt' }),
    body: {
      getReader: () => ({
        read: async () =>
          i < globalThis.__stuecke.length
            ? { done: false, value: new TextEncoder().encode(globalThis.__stuecke[i++]) }
            : { done: true, value: undefined },
      }),
    },
  }
}
"""


def _modul() -> str:
    """api.js as a plain script: the exports become declarations."""
    quelle = API.read_text(encoding="utf-8")
    return re.sub(
        r"^export (?=(?:async )?(?:function\*?|const|let|class) )", "", quelle, flags=re.M
    )


def _strom(stuecke: list[str], status: int = 200) -> dict:
    """Reads one stream to its end and reports what the reader saw."""
    skript = f"""
{UMGEBUNG}
{_modul()}
;(async () => {{
  globalThis.__stuecke = {json.dumps(stuecke)}
  globalThis.__status = {status}
  const gesehen = []
  let fehler = null
  try {{
    for await (const ereignis of antwortStrom({{}}, undefined)) gesehen.push(ereignis.typ)
  }} catch (e) {{
    fehler = {{ name: e.name, text: String(e.message || e), status: e.status ?? null }}
  }}
  console.log(JSON.stringify({{ gesehen, fehler }}))
}})()
"""
    lauf = node_script(skript)
    assert lauf.returncode == 0, f"{lauf.stderr}\n{lauf.stdout}"
    return json.loads(lauf.stdout.strip().splitlines()[-1])


ohne_node = pytest.mark.skipif(shutil.which("node") is None, reason="no node on this machine")


@ohne_node
def test_ein_strom_ohne_done_gilt_als_gerissen():
    """Two events, then the body stops — the reader is told, and the error
    carries no status: exactly the shape of a broken line, which is what
    sends the window looking for the run again instead of writing the
    answer off."""
    ergebnis = _strom([
        "data: {\"typ\": \"start\", \"generation_id\": \"g1\"}\n\n"
        "data: {\"typ\": \"content\", \"text\": \"hallo\"}\n\n",
    ])
    assert ergebnis["gesehen"] == ["start", "content"]
    assert ergebnis["fehler"] is not None, "the silent end got through"
    assert ergebnis["fehler"]["status"] is None, "a cut-off carries no status"


@ohne_node
def test_ein_strom_mit_done_endet_still():
    """Silence probe: the ordinary case — every complete stream carries
    `done`, and that end stays a normal end."""
    ergebnis = _strom([
        "data: {\"typ\": \"start\", \"generation_id\": \"g1\"}\n\n"
        "data: {\"typ\": \"content\", \"text\": \"hallo\"}\n\n"
        "data: {\"typ\": \"done\", \"zustand\": \"fertig\"}\n\n",
    ])
    assert ergebnis["gesehen"] == ["start", "content", "done"]
    assert ergebnis["fehler"] is None


@ohne_node
def test_ein_kaputtes_stueck_reisst_den_strom_nicht_ab():
    """Partial failure: the middle piece is not valid JSON. The other two
    still arrive, and the body that then stops without `done` is still a
    tear — a broken packet is not an excuse for a silent end."""
    ergebnis = _strom([
        "data: {\"typ\": \"start\", \"generation_id\": \"g1\"}\n\n",
        "data: {kaputt\n\n",
        "data: {\"typ\": \"content\", \"text\": \"hallo\"}\n\n",
    ])
    assert ergebnis["gesehen"] == ["start", "content"]
    assert ergebnis["fehler"] is not None


@ohne_node
def test_eine_absage_behaelt_ihren_status():
    """Silence probe: a refusal is not a tear — it keeps the number it came
    with, and the window tells the two apart by exactly that."""
    ergebnis = _strom(["data: {\"typ\": \"start\"}\n\n"], status=404)
    assert ergebnis["gesehen"] == []
    assert ergebnis["fehler"] is not None
    assert ergebnis["fehler"]["status"] == 404



# --- The providers' side: no model stream ends unnamed ----------------------
#
# The same rule one level down: a model stream that closes without naming
# why it stopped is a provider that broke off mid-answer. Both providers
# read the reason in their own protocol and hand it to one shared check, so
# the rule, its key and its sentence cannot drift apart between them.

PROVIDERS = WURZEL / "app/providers"


def test_the_rule_stands_once():
    """The key is raised in one place only — the shared check — and both
    providers use that very check."""
    from app.providers import anthropic, base, openai_kompatibel

    raised_in = sorted(
        source.name
        for source in PROVIDERS.glob("*.py")
        if "fehler.anbieter_ende_fehlt" in source.read_text(encoding="utf-8")
    )
    assert raised_in == ["base.py"]
    for module in (openai_kompatibel, anthropic):
        assert module.require_stream_end is base.require_stream_end


def test_no_end_reason_raises_the_one_key():
    from app.providers.base import ProviderFehler, require_stream_end

    with pytest.raises(ProviderFehler) as error:
        require_stream_end(None, "Test lab")
    assert error.value.key == "fehler.anbieter_ende_fehlt"
    assert "Test lab" in str(error.value)


@pytest.mark.parametrize("reason", ["stop", "length", "tool_calls", "end_turn", "max_tokens"])
def test_a_named_end_reason_lets_the_stream_through(reason):
    """Silence probe: every named reason — OpenAI's and Anthropic's words
    alike — is an end, and the check stays quiet."""
    from app.providers.base import require_stream_end

    assert require_stream_end(reason, "Test lab") is None


@pytest.mark.asyncio
async def test_both_providers_raise_the_same_key_through_the_shared_check(
    monkeypatch, modellserver
):
    """A stream without its end, once per provider, through the real stream
    readers: both fail with the same key, and both through the shared
    check."""
    from app.providers import anthropic as anthropic_module
    from app.providers import base
    from app.providers import openai_kompatibel as openai_module
    from tests.test_anthropic_provider import bauen, strom
    from tests.test_anthropic_provider import stuecke as anthropic_chunks
    from tests.test_openai_provider import _einsammeln, _provider

    calls: list[tuple[str, object]] = []
    real_check = base.require_stream_end

    def recorded(provider: str):
        def check(reason, name):
            calls.append((provider, reason))
            return real_check(reason, name)
        return check

    monkeypatch.setattr(openai_module, "require_stream_end", recorded("openai"))
    monkeypatch.setattr(anthropic_module, "require_stream_end", recorded("anthropic"))

    # The OpenAI wire: text, then `[DONE]`, and no packet naming a reason.
    modellserver.rohzeilen = [
        'data: {"choices": [{"delta": {"content": "Half"}, "index": 0}]}\n\n',
    ]
    with pytest.raises(base.ProviderFehler) as openai_error:
        await _einsammeln(_provider(modellserver.basis))

    # The Anthropic wire: text, and the body closes without a reason.
    with pytest.raises(base.ProviderFehler) as anthropic_error:
        await anthropic_chunks(bauen(), strom(
            {"type": "message_start", "message": {"usage": {"input_tokens": 5}}},
            {"type": "content_block_delta", "index": 0,
             "delta": {"type": "text_delta", "text": "Half"}},
            mit_ende=False,
        ))

    assert openai_error.value.key == anthropic_error.value.key == "fehler.anbieter_ende_fehlt"
    assert calls == [("openai", None), ("anthropic", None)]
