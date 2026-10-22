"""The MCP tool switch: three states a click cycles through, two lists the
registry actually reads (app/tools/registry.py).

A tool that "asks first" has to land in BOTH `allowed_tools` and
`needs_confirmation` — offered, but not run without a yes. Landing in only
one of them either hides the tool entirely or lets it run silently, and
that mistake is exactly what this test is built to catch.

The decision lives in its own import-free module for the same reason
test_chatringe.py already gives: it can be executed here as it ships,
without the Svelte build around it.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path
from typing import Any

import pytest

WURZEL = Path(__file__).resolve().parent.parent
FRONTEND = WURZEL / "frontend"
MODUL = FRONTEND / "src" / "lib" / "mcpWerkzeuge.js"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="no Node on this machine"
)


def _lauf(quelltext: str) -> Any:
    treiber = FRONTEND / "mcp_werkzeuge.pruefung.mjs"
    treiber.write_text(
        textwrap.dedent(
            f"""
            import {{
              apiKeyUmgebungsname, grundfelder, headerFields, headersWithoutKey, keyVariableOf,
              listenAusZustaenden,
              naechsterZustand, serverKennung, stateWordKey, zustandAusEintrag,
            }} from {("./" + str(MODUL.relative_to(FRONTEND)))!r}
            {quelltext}
            """
        ),
        encoding="utf-8",
    )
    try:
        lauf = subprocess.run(
            ["node", treiber.name], cwd=FRONTEND, capture_output=True, text=True, timeout=60
        )
    finally:
        treiber.unlink(missing_ok=True)
    assert lauf.returncode == 0, (lauf.stdout + lauf.stderr)[-2000:]
    return json.loads(lauf.stdout.strip().splitlines()[-1])


def test_drei_zustaende_ergeben_zwei_listen():
    """The exact case the order asks for: one tool of each state, and the
    tool that asks first must show up in both lists, not just one."""
    ergebnis = _lauf(
        """
        const werkzeuge = [
          { name: 'lesen', zustand: 'an' },
          { name: 'schreiben', zustand: 'fragt' },
          { name: 'loeschen', zustand: 'aus' },
        ]
        console.log(JSON.stringify(listenAusZustaenden(werkzeuge)))
        """
    )
    assert ergebnis["allowed_tools"] == ["lesen", "schreiben"]
    assert ergebnis["needs_confirmation"] == ["schreiben"]
    # The failure this test is built to catch: "schreiben" only in one list.
    assert "schreiben" in ergebnis["allowed_tools"]
    assert "schreiben" in ergebnis["needs_confirmation"]


def test_aus_faellt_aus_beiden_listen():
    ergebnis = _lauf(
        """
        console.log(JSON.stringify(listenAusZustaenden([{ name: 'x', zustand: 'aus' }])))
        """
    )
    assert ergebnis == {"allowed_tools": [], "needs_confirmation": []}


def test_naechster_zustand_dreht_im_kreis():
    ergebnis = _lauf(
        """
        console.log(JSON.stringify([
          naechsterZustand('an'), naechsterZustand('fragt'), naechsterZustand('aus'),
        ]))
        """
    )
    assert ergebnis == ["fragt", "aus", "an"]


def test_zustand_aus_eintrag_liest_beide_listen():
    ergebnis = _lauf(
        """
        const eintrag = { allowed_tools: ['a', 'b'], needs_confirmation: ['b'] }
        console.log(JSON.stringify([
          zustandAusEintrag('a', eintrag),
          zustandAusEintrag('b', eintrag),
          zustandAusEintrag('c', eintrag),
        ]))
        """
    )
    assert ergebnis == ["an", "fragt", "aus"]


def test_zustand_aus_eintrag_ausschluss_schlaegt_bestaetigung():
    """A name that stands in both lists at once — reachable only by editing
    the raw file by hand — is truly excluded: the registry drops it before
    it ever looks at needs_confirmation (app/tools/registry.py:377-395), so
    the switch must show 'aus', never 'fragt'."""
    ergebnis = _lauf(
        """
        const eintrag = { allowed_tools: ['a'], needs_confirmation: ['b'] }
        console.log(JSON.stringify(zustandAusEintrag('b', eintrag)))
        """
    )
    assert ergebnis == "aus"


def test_zustand_aus_eintrag_ohne_liste_heisst_alles_an():
    """`allowed_tools: null` is the registry's "offer everything" — every
    tool the server reports starts on, not off (app/tools/registry.py)."""
    ergebnis = _lauf(
        """
        const eintrag = { allowed_tools: null, needs_confirmation: [] }
        console.log(JSON.stringify(zustandAusEintrag('irgendwas', eintrag)))
        """
    )
    assert ergebnis == "an"


def test_serverkennung_macht_einen_dateinamen_aus_dem_titel():
    ergebnis = _lauf(
        """
        console.log(JSON.stringify([
          serverKennung('WordPress'), serverKennung('  Meine Seite! '),
        ]))
        """
    )
    assert ergebnis == ["wordpress", "meine-seite"]


def test_api_key_umgebungsname_folgt_der_anbieter_konvention():
    """The same alphabet and the same suffix app/api/v1/anbieter.py already
    uses for a custom cloud provider's key — one convention, not two."""
    ergebnis = _lauf("console.log(JSON.stringify(apiKeyUmgebungsname('meine-seite')))")
    assert ergebnis == "MEINE_SEITE_API_KEY"


def test_ein_name_aus_einer_adresse_wird_ein_gueltiger_umgebungsname():
    """A name typed as an address starts with a digit; the server refuses
    such a variable name, so the sheet must never build one."""
    from app.tools.registry import _UMGEBUNGSNAME

    ergebnis = _lauf("console.log(JSON.stringify(apiKeyUmgebungsname('127-0-0-1')))")
    assert ergebnis == "_127_0_0_1_API_KEY"
    assert _UMGEBUNGSNAME.fullmatch(ergebnis)


def test_ein_eingetragener_schluessel_schaltet_den_server_ein():
    """A switched-off server whose key is typed in and sent with "connect"
    is switched on — otherwise it never starts and the sheet reports it
    unreachable though the key was taken."""
    ergebnis = _lauf(
        """
        const quelle = { url: 'https://x.invalid/mcp' }
        console.log(JSON.stringify({
          mit: grundfelder(quelle, { enabled: false }, { mitSchluessel: true }).enabled,
          ohne: grundfelder(quelle, { enabled: false }).enabled,
          an: grundfelder(quelle, { enabled: true }, { mitSchluessel: true }).enabled,
          neu: grundfelder(quelle, null).enabled,
        }))
        """
    )
    assert ergebnis["mit"] is True
    # Silent cases: without a key the switch stays where it was, and a
    # server that was on stays on.
    assert ergebnis["ohne"] is False
    assert ergebnis["an"] is True
    assert ergebnis["neu"] is True


def test_a_card_without_an_address_writes_neither_kind_nor_address():
    """A server that starts a program here has no address. Written as `http`
    it became an address-less server the file check refuses ("requires a
    'url'"); without the two fields it keeps the kind it has — the shipped
    entry's, or the stdio entry whose key is missing."""
    ergebnis = _lauf(
        """
        const felder = grundfelder({ name: 'websuche', url: null, vorauswahl: null }, null)
        const stdio = grundfelder({ name: 'eigener', command: 'x' }, { enabled: false },
                                  { mitSchluessel: true })
        console.log(JSON.stringify({ felder, stdio }))
        """
    )
    assert ergebnis["felder"] == {"enabled": True}
    assert ergebnis["stdio"] == {"enabled": True}


def test_silence_a_card_with_an_address_writes_kind_and_address_as_before():
    ergebnis = _lauf(
        """
        const quelle = { url: 'https://x.invalid/mcp', vorauswahl: ['a', 'b'] }
        console.log(JSON.stringify(grundfelder(quelle, null)))
        """
    )
    assert ergebnis == {
        "enabled": True,
        "type": "http",
        "url": "https://x.invalid/mcp",
        "allowed_tools": ["a", "b"],
    }


def test_a_key_in_authorization_goes_as_a_bearer_and_in_any_other_header_as_it_is():
    ergebnis = _lauf(
        """
        console.log(JSON.stringify({
          bearer: headerFields('MAPS_API_KEY', 'Authorization'),
          lower: headerFields('MAPS_API_KEY', ' authorization '),
          google: headerFields('MAPS_API_KEY', 'X-Goog-Api-Key'),
          empty: headerFields('MAPS_API_KEY', '  '),
        }))
        """
    )
    assert ergebnis["bearer"] == {
        "headers": {"Authorization": "Bearer ${MAPS_API_KEY}"}, "api_key_env": None, "auth": None,
    }
    assert ergebnis["lower"]["headers"] == {"authorization": "Bearer ${MAPS_API_KEY}"}
    assert ergebnis["google"] == {
        "headers": {"X-Goog-Api-Key": "${MAPS_API_KEY}"}, "api_key_env": None, "auth": None,
    }
    # No name given: the usual one, with a Bearer.
    assert ergebnis["empty"]["headers"] == {"Authorization": "Bearer ${MAPS_API_KEY}"}


def test_a_typed_key_keeps_the_headers_without_a_key_and_replaces_the_ones_with_one():
    ergebnis = _lauf(
        """
        console.log(JSON.stringify(headerFields(
          'NEW_KEY', 'X-Goog-Api-Key',
          { 'X-Org': 'acme', 'Authorization': 'Bearer ${OLD_KEY}', 'x-goog-api-key': '${OLD2}' },
        )))
        """
    )
    assert ergebnis["headers"] == {"X-Org": "acme", "X-Goog-Api-Key": "${NEW_KEY}"}


def test_the_headers_that_carry_a_key_are_told_from_the_ones_that_do_not():
    ergebnis = _lauf(
        """
        console.log(JSON.stringify({
          name: keyVariableOf({ 'X-Org': 'acme', 'X-Goog-Api-Key': '${MAPS}' }),
          none: keyVariableOf({ 'X-Org': 'acme' }) ?? null,
          empty: keyVariableOf(undefined) ?? null,
          kept: headersWithoutKey({ 'X-Org': 'acme', Authorization: 'Bearer ${OLD}' }),
          nothing: headersWithoutKey({ Authorization: 'Bearer ${OLD}' }),
          absent: headersWithoutKey(undefined),
        }))
        """
    )
    assert ergebnis == {
        "name": "MAPS", "none": None, "empty": None,
        "kept": {"X-Org": "acme"}, "nothing": None, "absent": None,
    }


def _catalogue(sprache: str) -> dict:
    return json.loads((WURZEL / "app" / "locales" / f"{sprache}.json").read_text(encoding="utf-8"))


def _word(katalog: dict, schluessel: str) -> str | None:
    gefunden = katalog
    for teil in schluessel.split("."):
        if not isinstance(gefunden, dict) or teil not in gefunden:
            return None
        gefunden = gefunden[teil]
    return gefunden if isinstance(gefunden, str) else None


def test_each_state_beside_a_tool_has_a_word_in_both_catalogues():
    """The word beside a tool is the one the terminal client writes: active,
    asks, inactive. A key the catalogue does not hold comes back as the key
    itself and would stand on the screen as ``werkzeuge.an``."""
    keys = _lauf(
        """
        console.log(JSON.stringify(['an', 'fragt', 'aus'].map(stateWordKey)))
        """
    )
    assert keys == ["status.aktiv", "werkzeuge.fragt", "status.inaktiv"]
    english = [_word(_catalogue("en"), key) for key in keys]
    assert english == ["active", "asks", "inactive"]
    assert [_word(_catalogue("de"), key) for key in keys] == ["aktiv", "fragt", "inaktiv"]


def test_silence_asks_first_keeps_its_word_and_an_unknown_state_reads_as_on():
    assert _lauf("console.log(JSON.stringify(stateWordKey('fragt')))") == "werkzeuge.fragt"
    assert _lauf("console.log(JSON.stringify(stateWordKey('other')))") == "status.aktiv"


def test_the_mask_writes_the_word_through_that_mapping_and_not_a_built_key():
    source = (FRONTEND / "src" / "teile" / "MCPMaske.svelte").read_text(encoding="utf-8")
    assert "t(stateWordKey(werkzeug.zustand))" in source
    assert "werkzeuge.${werkzeug.zustand}" not in source
