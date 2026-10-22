"""The window's address rule, run for real.

This is JavaScript and the suite is Python, so node runs it — the same detour
tests/test_vorschauschutz.py takes, and for the same reason: the rule decides
whether a foreign page may be shown INSIDE a program window, which is how a
page that asks for a password gets believed. It used to live in
fenster-electron/main.js, which requires electron and therefore cannot run
outside a packaged window; it could have broken without a test going red.

See fenster-electron/adressregel.js.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parents[1]
MODUL = WURZEL / "fenster-electron" / "adressregel.js"
PAKET = WURZEL / "fenster-electron" / "package.json"

SKRIPT = """
const rules = require(%(modul)s)
const PDF = 'chrome-extension://mhjfbmdgcfjbbpaeojofohoefgiehjai/34b3c741'
const own = (a) => rules.istEigeneSeite(a, 8090)
console.log(JSON.stringify({
  eigene_seite: {
    loopback: own('http://127.0.0.1:8090/app/'),
    localhost: own('http://localhost:8090/app/'),
    handbuch: own('http://127.0.0.1:8090/help/start'),
    anderer_port: own('http://127.0.0.1:8091/app/'),
    https: own('https://127.0.0.1:8090/app/'),
    fremder_wirt: own('http://exe-hq.net:8090/app/'),
    fremder_wirt_im_pfad: own('http://boese.example/127.0.0.1:8090/app/'),
    host_as_username: own('http://127.0.0.1:8090@boese.example/'),
    no_port: own('http://127.0.0.1/app/'),
    datei: own('file:///etc/passwd'),
    empty_text: own(''),
    nothing: own(null),
    unfug: own('not even an address'),
  },
  standardport: {
    unspecified: rules.istEigeneSeite('http://127.0.0.1/app/', 80),
    ausgeschrieben: rules.istEigeneSeite('http://127.0.0.1:80/app/', 80),
    localhost: rules.istEigeneSeite('http://localhost/app/', 80),
    anderer_port: rules.istEigeneSeite('http://127.0.0.1:8090/app/', 80),
    https_unspecified: rules.istEigeneSeite('https://127.0.0.1/app/', 443),
  },
  to_outside: {
    http: rules.darfNachDraussen('http://exe-hq.net/'),
    https: rules.darfNachDraussen('https://exe-hq.net/'),
    datei: rules.darfNachDraussen('file:///etc/passwd'),
    javascript: rules.darfNachDraussen('javascript:alert(1)'),
    daten: rules.darfNachDraussen('data:text/html,<h1>hi'),
    unbekannt: rules.darfNachDraussen('someprotocol:run-it'),
    leer: rules.darfNachDraussen(''),
    nothing: rules.darfNachDraussen(null),
  },
  navigation: (() => {
    const verdict = (address, kind) => rules.navigationVerdict(address, 8090, kind)
    return {
      main_foreign_https: verdict('https://exe-hq.net/hilfe', { mainFrame: true }),
      main_file: verdict('file:///etc/passwd', { mainFrame: true }),
      main_javascript: verdict('javascript:alert(1)', { mainFrame: true }),
      main_own: verdict('http://127.0.0.1:8090/app/', { mainFrame: true }),
      sub_foreign: verdict('https://exe-hq.net/', { mainFrame: false }),
      sub_srcdoc: verdict('about:srcdoc', { mainFrame: false }),
      sub_blank: verdict('about:blank', { mainFrame: false }),
      sub_own: verdict('http://localhost:8090/help/', { mainFrame: false }),
      sub_pdf_viewer: verdict('chrome-extension://mhjfbmdgcfjbbpaeojofohoefgiehjai/34b3c741', { mainFrame: false }),
      sub_other_extension: verdict('chrome-extension://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/x', { mainFrame: false }),
      main_pdf_viewer: verdict('chrome-extension://mhjfbmdgcfjbbpaeojofohoefgiehjai/34b3c741', { mainFrame: true }),
      sub_devtools: verdict('devtools://devtools/bundled/panel.html', { mainFrame: false }),
      main_devtools: verdict('devtools://devtools/bundled/panel.html', { mainFrame: true }),
      redirect_devtools: verdict('devtools://devtools/bundled/x.html', { mainFrame: true, redirect: true }),
      tools_sub_data: verdict('data:text/html,<p>x', { mainFrame: false, tools: true }),
      tools_main_devtools: verdict('devtools://devtools/bundled/devtools_app.html', { mainFrame: true, tools: true }),
      tools_main_foreign: verdict('https://exe-hq.net/', { mainFrame: true, tools: true }),
      tools_main_file: verdict('file:///etc/passwd', { mainFrame: true, tools: true }),
      tools_main_remote_frontend: verdict('devtools://devtools/remote/serve_rev/@1/inspector.html', { mainFrame: true, tools: true }),
      tools_sub_devtools: verdict('devtools://devtools/bundled/panel.html', { mainFrame: false, tools: true }),
      tools_sub_foreign: verdict('https://exe-hq.net/', { mainFrame: false, tools: true }),
      tools_sub_file: verdict('file:///etc/passwd', { mainFrame: false, tools: true }),
      tools_sub_redirect_foreign: verdict('https://exe-hq.net/', { mainFrame: false, redirect: true, tools: true }),
      tools_main_own: verdict('http://127.0.0.1:8090/app/', { mainFrame: true, tools: true }),
      tools_main_other_host: verdict('devtools://evil/bundled/x.html', { mainFrame: true, tools: true }),
      tools_main_lookalike: verdict('devtools://devtools/bundledX/x.html', { mainFrame: true, tools: true }),
      tools_main_dotdot: verdict('devtools://devtools/bundled/../remote/x', { mainFrame: true, tools: true }),
      tools_sub_remote_frontend: verdict('devtools://devtools/remote/serve_rev/@1/inspector.html', { mainFrame: false, tools: true }),
      tools_sub_extension: verdict('chrome-extension://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/panel.html', { mainFrame: false, tools: true }),
      tools_sub_own: verdict('http://127.0.0.1:8090/help/', { mainFrame: false, tools: true }),
      tools_sub_blob: verdict('blob:devtools://devtools/0f1e2d3c', { mainFrame: false, tools: true }),
      tools_sub_srcdoc: verdict('about:srcdoc', { mainFrame: false, tools: true }),
      tools_main_blank: verdict('about:blank', { mainFrame: true, tools: true }),
      tools_sub_other_host: verdict('devtools://evil/bundled/x.html', { mainFrame: false, tools: true }),
      tools_sub_dotdot: verdict('devtools://devtools/bundled/../remote/x', { mainFrame: false, tools: true }),
      tools_main_encoded_dotdot: verdict('devtools://devtools/bundled/..%%2fremote/x', { mainFrame: true, tools: true }),
      tools_sub_encoded_dotdot: verdict('devtools://devtools/bundled/x%%2f..%%2fremote', { mainFrame: false, tools: true }),
      tools_main_backslash: verdict('devtools://devtools/bundled/..\\\\remote\\\\x', { mainFrame: true, tools: true }),
      tools_main_userinfo: verdict('devtools://u:p@devtools/bundled/devtools_app.html', { mainFrame: true, tools: true }),
      tools_sub_dots_in_name: verdict('devtools://devtools/bundled/third_party/foo..min.js', { mainFrame: false, tools: true }),
      tools_main_query: verdict('devtools://devtools/bundled/devtools_app.html?panel=elements', { mainFrame: true, tools: true }),
      tools_sub_blank: verdict('about:blank', { mainFrame: false, tools: true }),
      tools_sub_about_other: verdict('about:version', { mainFrame: false, tools: true }),
      main_srcdoc: verdict('about:srcdoc', { mainFrame: true }),
      sub_blank_query: verdict('about:blank?x', { mainFrame: false }),
      sub_blob: verdict('blob:http://127.0.0.1:8090/0f1e', { mainFrame: false }),
      sub_data: verdict('data:text/html,<p>x', { mainFrame: false }),
      sub_blank_fragment: verdict('about:blank#x', { mainFrame: false }),
      sub_about_other: verdict('about:version', { mainFrame: false }),
      main_blank: verdict('about:blank', { mainFrame: true }),
      redirect_foreign: verdict('https://exe-hq.net/', { mainFrame: true, redirect: true }),
      redirect_own: verdict('http://127.0.0.1:8090/app/', { mainFrame: true, redirect: true }),
      no_options: verdict('https://exe-hq.net/'),
      pdf_sub_foreign: verdict('https://exe-hq.net/', { mainFrame: false, initiator: PDF }),
      pdf_main_foreign: verdict('https://exe-hq.net/', { mainFrame: true, initiator: PDF }),
      pdf_http: verdict('http://exe-hq.net/', { mainFrame: false, initiator: PDF }),
      pdf_javascript: verdict('javascript:alert(1)', { mainFrame: false, initiator: PDF }),
      pdf_file: verdict('file:///etc/passwd', { mainFrame: true, initiator: PDF }),
      pdf_redirect: verdict('https://exe-hq.net/', { mainFrame: true, redirect: true, initiator: PDF }),
      pdf_own: verdict('http://127.0.0.1:8090/app/', { mainFrame: false, initiator: PDF }),
      srcdoc_foreign: verdict('https://exe-hq.net/', { mainFrame: false, initiator: 'about:srcdoc' }),
      extension_foreign: verdict(
        'https://exe-hq.net/', { mainFrame: false, initiator: 'chrome-extension://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/x' },
      ),
      own_page_foreign: verdict(
        'https://exe-hq.net/', { mainFrame: true, initiator: 'http://127.0.0.1:8090/app/' },
      ),
      pdf_tools_foreign: verdict('https://exe-hq.net/', { mainFrame: false, tools: true, initiator: PDF }),
      browser_main_foreign: verdict('https://exe-hq.net/', { mainFrame: true, byBrowser: true }),
      browser_sub_foreign: verdict('https://exe-hq.net/', { mainFrame: false, byBrowser: true }),
      browser_file: verdict('file:///etc/passwd', { mainFrame: true, byBrowser: true }),
      browser_javascript: verdict('javascript:alert(1)', { mainFrame: true, byBrowser: true }),
      browser_redirect: verdict('https://exe-hq.net/', { mainFrame: true, redirect: true, byBrowser: true }),
      browser_tools: verdict('https://exe-hq.net/', { mainFrame: true, tools: true, byBrowser: true }),
    }
  })(),
  link: (() => {
    const verdict = (address, kind) => rules.linkVerdict(address, 8090, kind)
    return {
      https: verdict('https://exe-hq.net/hilfe'),
      http: verdict('http://exe-hq.net/'),
      own: verdict('http://127.0.0.1:8090/app/'),
      own_localhost: verdict('http://localhost:8090/help/'),
      other_port_on_loopback: verdict('http://127.0.0.1:8091/app/'),
      javascript: verdict('javascript:alert(1)'),
      file: verdict('file:///etc/passwd'),
      data: verdict('data:text/html,<h1>hi'),
      unknown_scheme: verdict('someprotocol:run-it'),
      empty: verdict(''),
      nothing: verdict(null),
      tools_foreign: verdict('https://exe-hq.net/', { tools: true }),
      tools_own: verdict('http://127.0.0.1:8090/app/', { tools: true }),
    }
  })(),
  log: {
    https: rules.addressForLog('https://user:pw@service.example/reset/9f3c?code=SECRET'),
    own: rules.addressForLog('http://127.0.0.1:8090/app/?x=1'),
    file: rules.addressForLog('file:///Users/someone/secret.txt'),
    garbage: rules.addressForLog('not an address'),
  },
  handbuch: {
    genau: rules.istHandbuch('http://127.0.0.1:8090/help/'),
    darunter: rules.istHandbuch('http://127.0.0.1:8090/help/tasten'),
    app: rules.istHandbuch('http://127.0.0.1:8090/app/'),
    aehnlich: rules.istHandbuch('http://127.0.0.1:8090/helpdesk'),
    unfug: rules.istHandbuch('no address at all'),
  },
}))
"""


@pytest.fixture(scope="module")
def antwort():
    if not shutil.which("node"):
        pytest.skip("node is missing")
    ausdruck = SKRIPT % {"modul": json.dumps(str(MODUL))}
    lauf = subprocess.run(
        ["node", "-e", ausdruck], capture_output=True, text=True, timeout=60
    )
    assert lauf.returncode == 0, (lauf.stdout + lauf.stderr)[-2000:]
    return json.loads(lauf.stdout)


def test_nur_die_eigene_seite_darf_ins_fenster(antwort):
    """Own page means: plain http, loopback, and THIS port."""
    fall = antwort["eigene_seite"]
    assert fall["loopback"] is True
    assert fall["localhost"] is True
    assert fall["handbuch"] is True
    for name in (
        "anderer_port",
        "https",
        "fremder_wirt",
        "fremder_wirt_im_pfad",
        "host_as_username",
        "no_port",
        "datei",
        "empty_text",
        "nothing",
        "unfug",
    ):
        assert fall[name] is False, name


def test_nur_http_und_https_verlassen_das_programm(antwort):
    """Everything else would hand the address to whatever program claims the
    scheme — the guard would become a way of starting programs from a page."""
    fall = antwort["to_outside"]
    assert fall["http"] is True
    assert fall["https"] is True
    for name in ("datei", "javascript", "daten", "unbekannt", "leer", "nothing"):
        assert fall[name] is False, name


def test_das_handbuch_ist_ein_pfad_und_kein_wortanfang(antwort):
    """The manual gets the one window it is allowed. Everything else of ours
    is a plain window — `/helpdesk` is not the manual."""
    fall = antwort["handbuch"]
    assert fall["genau"] is True
    assert fall["darunter"] is True
    for name in ("app", "aehnlich", "unfug"):
        assert fall[name] is False, name


def test_das_modul_wird_mitgepackt():
    """A rule in a file the packer leaves out dies on the first require —
    and the packer's list is a positive one: what is not written there is
    not in the bundle, so the shell starts and dies before a window opens.

    Read off the shell itself rather than listed here: every ``require`` of
    a file next to it has to stand in the list. A second module added later
    is covered the moment it is required, instead of waiting for someone to
    remember this test."""
    paket = json.loads(PAKET.read_text(encoding="utf-8"))
    dateien = paket["build"]["files"]
    assert "adressregel.js" in dateien
    haupt = (WURZEL / "fenster-electron" / "main.js").read_text(encoding="utf-8")
    eigene = re.findall(r"require\('\./([\w.-]+)'\)", haupt)
    assert eigene, "no require of our own found in main.js"
    for name in eigene:
        assert f"{name}.js" in dateien, (
            f"{name}.js is needed by main.js but is not in build.files"
        )


def test_ein_weggelassener_standardport_ist_der_eigene(antwort):
    """The URL parser drops `:80`; a shell on port 80 still knows its own
    page — and one on another port or https still does not."""
    assert antwort["standardport"] == {
        "unspecified": True,
        "ausgeschrieben": True,
        "localhost": True,
        "anderer_port": False,
        "https_unspecified": False,
    }


def test_beide_filter_des_fensters_fragen_dieselbe_regel():
    """Which pages may open in a window and which may be navigated to used
    to be two lists — `127.0.0.1` only in one, `localhost` as well in the
    other. Both now ask the one module, adressregel.js (`istEigeneSeite` for
    a new window, `navigationVerdict` for a navigation), and both are
    attached to every page the program creates."""
    quelle = (WURZEL / "fenster-electron" / "main.js").read_text()
    # Navigation: every frame and every redirect goes through the one
    # decision, which stops what is not allowed and sends out what may go.
    guard = re.search(r"function navigationSperren\(inhalt\) \{.*?\n\}", quelle, re.S)
    assert guard, "navigationSperren not found"
    for event, redirect in (("will-frame-navigate", "false"), ("will-redirect", "true")):
        assert f"inhalt.on('{event}', (details) => navigationDecide(inhalt, details, {redirect}))" in (
            guard.group(0)
        ), f"{event} does not go through navigationDecide"
    decide = re.search(r"function navigationDecide\(contents, details, redirect\) \{.*?\n\}", quelle, re.S)
    assert decide, "navigationDecide not found"
    body = decide.group(0)
    assert "regel.navigationVerdict(details.url, PORT" in body
    assert re.search(r"if \(verdict === 'allow'\) return\s*details\.preventDefault\(\)", body), (
        "a navigation that is not allowed is not stopped"
    )
    assert "if (verdict === 'outside') nachDraussen(details.url)" in body
    # One listener decides: will-navigate would open a second browser tab.
    assert "on('will-navigate'" not in quelle
    # A new window: a foreign address is sent out and denied.
    assert re.search(
        r"function fensterweiche\(\{ url \}, inhalt\) \{\s*if \(!istEigeneSeite\(url\)\) \{"
        r"(?:\s*//[^\n]*)*\s*const haupt = istHauptfenster\(inhalt\)"
        r"\s*console\.log\([^\n]*\)\s*if \(haupt\) nachDraussen\(url\)"
        r"\s*return \{ action: 'deny' \}",
        quelle,
    ), "fensterweiche does not deny foreign addresses through istEigeneSeite"
    # Both, for every page at any depth.
    haken = re.search(r"app\.on\(['\"]web-contents-created['\"].*?\n\}\)", quelle, re.S)
    assert haken, "web-contents-created hook not found"
    assert "setWindowOpenHandler((angaben) => fensterweiche(angaben, inhalt))" in haken.group(0)
    assert "navigationSperren(inhalt)" in haken.group(0)
    assert "tools: toolsPages.has(contents)" in body
    # No second spelling of the own address beside the rule — in code, that
    # is; comments may name an example address.
    code = "\n".join(
        zeile for zeile in quelle.splitlines() if not zeile.lstrip().startswith("//")
    ).replace("const ZIEL = `http://127.0.0.1:${PORT}/app/`", "")
    assert not re.search(r"['\"`]http://(127\.0\.0\.1|localhost)[:'\"`/]", code), (
        "a second spelling of the own address"
    )


def test_a_navigation_stays_goes_out_or_is_stopped(antwort):
    """In a program window a navigation to a foreign page is stopped and
    opens nothing: a script that sets `location`, a form posting out or a
    redirect cannot start a browser tab. The one navigation that goes to the
    browser is the one no frame started — the PDF viewer's, for a link inside
    a PDF — or one the viewer's own frames started, and only over http(s). In the developer tools (`tools`) nothing goes to the
    browser: their main frame stays on the frontend shipped with the
    program, their frames keep their own kinds of documents, and a foreign
    page is stopped."""
    assert antwort["navigation"] == {
        "main_foreign_https": "block",
        "main_file": "block",
        "main_javascript": "block",
        "main_own": "allow",
        "sub_foreign": "block",
        "sub_srcdoc": "allow",
        "sub_blank": "allow",
        "sub_own": "allow",
        "sub_pdf_viewer": "allow",
        "sub_other_extension": "block",
        "main_pdf_viewer": "block",
        "sub_devtools": "block",
        "main_devtools": "block",
        "redirect_devtools": "block",
        "tools_sub_data": "allow",
        "tools_main_devtools": "allow",
        "tools_main_foreign": "block",
        "tools_main_file": "block",
        "tools_main_remote_frontend": "block",
        "tools_sub_devtools": "allow",
        "tools_sub_foreign": "block",
        "tools_sub_file": "block",
        "tools_sub_redirect_foreign": "block",
        "tools_main_own": "block",
        "tools_main_other_host": "block",
        "tools_main_lookalike": "block",
        "tools_main_dotdot": "block",
        "tools_sub_remote_frontend": "block",
        "tools_sub_extension": "block",
        "tools_sub_own": "block",
        "tools_sub_blob": "allow",
        "tools_sub_srcdoc": "allow",
        "tools_main_blank": "block",
        "tools_sub_other_host": "block",
        "tools_sub_dotdot": "block",
        "tools_main_encoded_dotdot": "block",
        "tools_sub_encoded_dotdot": "block",
        "tools_main_backslash": "block",
        "tools_main_userinfo": "block",
        "tools_sub_dots_in_name": "allow",
        "tools_main_query": "allow",
        "tools_sub_blank": "allow",
        "tools_sub_about_other": "block",
        "main_srcdoc": "block",
        "sub_blank_query": "allow",
        "sub_blob": "block",
        "sub_data": "block",
        "sub_blank_fragment": "allow",
        "sub_about_other": "block",
        "main_blank": "block",
        "redirect_foreign": "block",
        "redirect_own": "allow",
        "no_options": "block",
        "pdf_sub_foreign": "outside",
        "pdf_main_foreign": "outside",
        "pdf_http": "outside",
        "pdf_javascript": "block",
        "pdf_file": "block",
        "pdf_redirect": "block",
        "pdf_own": "allow",
        "srcdoc_foreign": "block",
        "extension_foreign": "block",
        "own_page_foreign": "block",
        "pdf_tools_foreign": "block",
        "browser_main_foreign": "outside",
        "browser_sub_foreign": "outside",
        "browser_file": "block",
        "browser_javascript": "block",
        "browser_redirect": "block",
        "browser_tools": "block",
    }


def test_the_log_names_the_place_and_nothing_more(antwort):
    """A path or a query can carry a token; the log keeps only the origin,
    and of anything that is not http(s) only the scheme."""
    assert antwort["log"] == {
        "https": "https://service.example",
        "own": "http://127.0.0.1:8090",
        "file": "file:",
        "garbage": "(not an address)",
    }


def test_a_clicked_link_leaves_only_as_a_foreign_http_address(antwort):
    """What the shell does with a click linkclicks.js reported: a foreign
    http(s) address opens the browser, one of our own pages is left alone,
    and anything else — or anything the developer tools ask for — opens
    nothing."""
    assert antwort["link"] == {
        "https": "outside",
        "http": "outside",
        "own": "allow",
        "own_localhost": "allow",
        "other_port_on_loopback": "outside",
        "javascript": "block",
        "file": "block",
        "data": "block",
        "unknown_scheme": "block",
        "empty": "block",
        "nothing": "block",
        "tools_foreign": "block",
        "tools_own": "block",
    }


def test_the_shell_asks_the_link_rule_for_a_click_and_hands_the_starter_to_the_navigation_rule():
    """The wiring main.js cannot be run for here: the click request is read
    by the one rule, from a sender that is not a developer-tools page, and
    the navigation rule is given the frame that started the navigation."""
    quelle = (WURZEL / "fenster-electron" / "main.js").read_text(encoding="utf-8")
    anfrage = re.search(r"ipcMain\.on\('open-link', .*?\n\}\)", quelle, re.S)
    assert anfrage, "the click request is not heard"
    assert "regel.linkVerdict(address, PORT, { tools: toolsPages.has(event.sender) })" in anfrage.group(0)
    assert "if (verdict === 'outside') nachDraussen(address)" in anfrage.group(0)
    decide = re.search(r"function navigationDecide\(contents, details, redirect\) \{.*?\n\}", quelle, re.S)
    assert decide and "...starterOf(details)" in decide.group(0)
    starter = re.search(r"function starterOf\(details\) \{.*?\n\}", quelle, re.S)
    assert starter and "byBrowser: true" in starter.group(0)
    # The catcher goes into the session before the window is built.
    assert re.search(
        r"session\.defaultSession\.registerPreloadScript\(\{\s*type: 'frame', id: 'linkclicks',"
        r"\s*filePath: path\.join\(__dirname, 'linkclicks\.js'\),\s*\}\)"
        r"\s*menueSetzen\(\)\s*fensterBauen\(\)",
        quelle,
    ), "linkclicks.js is not set as a preload before the window is built"


def test_the_click_catcher_is_packed_and_its_channel_is_the_one_the_shell_hears():
    """registerPreloadScript names the file by path, not by `require`, so the test
    above for required modules does not see it."""
    paket = json.loads(PAKET.read_text(encoding="utf-8"))
    assert "linkclicks.js" in paket["build"]["files"]
    fenger = (WURZEL / "fenster-electron" / "linkclicks.js").read_text(encoding="utf-8")
    haupt = (WURZEL / "fenster-electron" / "main.js").read_text(encoding="utf-8")
    assert "const CHANNEL = 'open-link'" in fenger
    assert "ipcMain.on('open-link'," in haupt
