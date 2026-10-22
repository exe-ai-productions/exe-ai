"""Every page this service hands out carries a content rule, and carries it sharp.

Three ways this could look right and be worthless, so three ways it is pinned:

* Shipped in the reporting mode it would look identical from outside -- the
  header is there, the browser writes complaints nobody reads, and nothing is
  ever refused. So the header NAME is checked, not only its presence.
* Set on the interface alone it would be walked around in one line. A page on
  the same origin without a rule is a borrowed context: a script can open one
  and act from inside it, where no rule applies. Measured, not assumed -- a
  foreign host received the session key that way. So every page is checked.
* Set on everything it would be aimed at nothing. So the last test is the
  other half of the pair.

See app/inhaltssicherheit.py.
"""

from __future__ import annotations

import pytest

from app.inhaltssicherheit import KOPFZEILE

# Every HTML page the service serves on its own origin. The interface comes
# from a route, the rest from the static mount, and the double slash is a
# third way to the same file that used to slip past the route.
SEITEN = ("/app/", "/app/index.html", "/app//index.html", "/", "/help/")


def test_die_regel_ist_scharf_und_nicht_nur_meldend():
    assert KOPFZEILE == "Content-Security-Policy"


@pytest.mark.parametrize("weg", SEITEN)
def test_jede_seite_traegt_eine_regel(weg, client):
    antwort = client.get(weg)
    assert antwort.status_code == 200
    assert "content-security-policy" in antwort.headers, weg


@pytest.mark.parametrize("weg", SEITEN)
def test_der_weg_nach_draussen_ist_auf_jeder_seite_zu(weg, client):
    """The one line the whole rule exists for, on every page that has one."""
    regel = client.get(weg).headers["content-security-policy"]
    assert "connect-src 'self'" in regel, weg
    # Nothing on this origin may be pulled into a frame, which is how a page
    # without a rule would have been borrowed in the first place.
    assert "frame-ancestors 'none'" in regel, weg
    # No wildcard may sneak into any fetching directive; one standing open
    # makes the rest decoration.
    for teil in regel.split(";"):
        assert " *" not in teil, (weg, teil)


@pytest.mark.parametrize("weg", ("/docs", "/redoc", "/docs/oauth2-redirect"))
def test_die_generierte_dokumentation_ist_aus(weg, client):
    """Its viewer used to come from a foreign address -- now
    there is no viewer to load one, on any of its three addresses."""
    assert client.get(weg).status_code == 404


def test_was_die_regel_braucht_steht_drin(client):
    """The three widenings that were measured against the built interface."""
    regel = client.get("/app/").headers["content-security-policy"]
    # The key script the service stitches in is written fresh every start.
    assert "'unsafe-inline'" in regel
    # The recording worklet arrives as a blob URL.
    assert "script-src" in regel and "blob:" in regel
    # A picture just attached is shown from a blob URL.
    assert "img-src 'self' data: blob:" in regel


def test_the_page_rule_lets_the_preview_frame_run_eval_and_webassembly(client):
    """The frame inherits this rule and the stricter of the two wins, so a
    document could run neither while the page lacked them."""
    rule = client.get("/app/").headers["content-security-policy"]
    script = next(part for part in rule.split(";") if "script-src" in part)
    assert "'unsafe-eval'" in script
    assert "'wasm-unsafe-eval'" in script
    assert "worker-src 'self' blob:" in rule


def test_silence_the_page_rule_keeps_the_way_out_shut_beside_eval(client):
    rule = client.get("/app/").headers["content-security-policy"]
    assert "connect-src 'self'" in rule
    assert "default-src 'self'" in rule
    assert "form-action 'self'" in rule
    assert "object-src 'none'" in rule


def test_was_keine_seite_ist_bleibt_ohne(client):
    """A rule aimed at everything is not aimed at anything."""
    antwort = client.get("/health")
    assert antwort.status_code == 200
    assert antwort.headers["content-type"].startswith("application/json")
    assert "content-security-policy" not in antwort.headers
