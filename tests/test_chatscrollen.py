"""Following along while the answer streams (`frontend/src/App.svelte`).

The whole point of this logic is that a reader who scrolls away is LEFT
where they scrolled to. It has failed that twice, in two different ways,
so both are pinned here by running the real functions rather than reading
them: the source is lifted out of App.svelte and executed in node.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parent.parent
QUELLE = WURZEL / "frontend/src/App.svelte"
FEDER = WURZEL / "frontend/src/lib/glide.js"


def _funktionen() -> str:
    """The real `scrollGeprueft`, `radGedreht` and `runter`, lifted out of
    the component so node can run them against a stand-in element."""
    quelle = QUELLE.read_text()
    stuecke = []
    for name in (
        "scrollGeprueft", "gescrollt", "radGedreht", "tasteHoch",
        "beruehrungBeginnt", "beruehrungZieht", "beruehrungEndet", "runter", "gleiteZumBoden",
    ):
        treffer = re.search(rf"\n  function {name}\(.*?\n  \}}\n", quelle, re.S)
        assert treffer, f"{name}() not found"
        stuecke.append(treffer.group(0))
    treffer = re.search(r"\n  const AM_BODEN = (\d+)\n", quelle)
    assert treffer, "AM_BODEN not found"
    stuecke.insert(0, f"const AM_BODEN = {treffer.group(1)};\n")
    fang = re.search(r"\n  const fangweite = \(\) => verlauf\.clientHeight / 2\n", quelle)
    assert fang, "fangweite not found"
    stuecke.insert(1, "const fangweite = () => verlauf.clientHeight / 2;\n")
    treffer = re.search(r"\n  const FANG_WEG = (\d+)\n", quelle)
    assert treffer, "FANG_WEG not found"
    stuecke.insert(2, f"const FANG_WEG = {treffer.group(1)};\nlet fangSumme = 0;\nlet fangZuletzt = 0;\nlet hochSumme = 0;\nlet runterSumme = 0;\n")
    # The spring itself lives in `lib/glide.js`, shared with the growing text.
    feder = FEDER.read_text()
    treffer = re.search(r"\nexport const GLEIT_HALB_MS = (\d+)\n", feder)
    assert treffer, "GLEIT_HALB_MS not found"
    schritt = re.search(r"\nexport function glideStep\(.*?\n\}\n", feder, re.S)
    assert schritt, "glideStep() not found"
    stuecke.insert(
        2,
        f"const GLEIT_HALB_MS = {treffer.group(1)};\nlet gleitet = false;\n"
        + schritt.group(0).replace("export function", "function"),
    )
    reduziert = re.search(r"\n  const bewegungReduziert = \(\) =>\n[^\n]*\n", quelle)
    assert reduziert, "bewegungReduziert not found"
    stuecke.insert(2, reduziert.group(0).replace("const bewegungReduziert", "const bewegungReduziert"))
    tasten = re.search(r"\n  const TASTEN_HOCH = new Set\(.*?\)\n", quelle)
    assert tasten, "TASTEN_HOCH not found"
    stuecke.insert(1, tasten.group(0))
    return "".join(stuecke)


def _lauf(schritte: str, bilder: str = "sofort") -> dict:
    """Run the lifted functions against a stand-in scroll box.

    `bilder="sofort"`: every animation frame runs straight through, so the
    ordering the tests are about (wheel before scroll) is not blurred by
    frame timing. `bilder="getaktet"`: frames wait in a queue and
    `takt(n)` runs n of them, 16 ms apart on a clock the code reads."""
    skript = f"""
let folgtMit = true, beruehrungY = 0;
const zustand = {{ aktiverChat: 'c1' }};
let selbstGerolltChat = null;
let uhr = 1000;
const performance = {{ now: () => uhr }};
const wartend = [];
const zeitgeber = [];
const takt = (n = 1) => {{
  for (let k = 0; k < n; k += 1) {{
    uhr += 16;
    for (const e of wartend.splice(0)) if (!e.tot) e.f();
    for (const t of zeitgeber) if (!t.tot && !t.lief && t.um <= uhr) {{ t.lief = true; t.f(); }}
  }}
}};
const GETAKTET = {json.dumps(bilder == "getaktet")};
// A real element CLAMPS what is written to scrollTop; a plain object does
// not, and runter() writes scrollHeight into it on purpose. Without the
// clamp this stand-in would answer for a box that does not exist.
const verlauf = {{
  scrollHeight: 3000, clientHeight: 500, _oben: 2500,
  get scrollTop() {{ return this._oben }},
  set scrollTop(v) {{
    this._oben = Math.max(0, Math.min(this.scrollHeight - this.clientHeight, v));
  }},
}};
const abstand = () => verlauf.scrollHeight - verlauf.scrollTop - verlauf.clientHeight;
// The browser fires `scroll` after the position changed; a programmatic
// write that moves nothing fires nothing, which is what runter() relies on.
const stelleMerken = () => {{}};
const scrolleAuf = (oben) => {{
  const vorher = verlauf.scrollTop;
  verlauf.scrollTop = Math.max(0, Math.min(verlauf.scrollHeight - verlauf.clientHeight, oben));
  // Through the REAL handler the wiring uses, not a shortcut to one half.
  if (verlauf.scrollTop !== vorher) gescrollt();
}};
// requestAnimationFrame runs straight through here: the ordering this test
// is about is wheel-before-scroll, not frame timing. `let`, so a test can
// kill the frames and prove the straggler timer still takes the snap.
let requestAnimationFrame = (f) => {{
  if (GETAKTET) {{ const e = {{ f }}; wartend.push(e); return e }}
  f();
  return 1;
}};
let cancelAnimationFrame = (e) => {{ if (e && typeof e === 'object') e.tot = true }};
let setTimeout = (f, ms) => {{
  if (GETAKTET) {{ const t = {{ f, um: uhr + ms }}; zeitgeber.push(t); return t }}
  f();
  return 1;
}};
let clearTimeout = (t) => {{ if (t && typeof t === 'object') t.tot = true }};
{_funktionen()}
{schritte}
console.log(JSON.stringify({{ folgtMit, abstand: abstand(), scrollTop: verlauf.scrollTop, wege: globalThis.wege, bewegt: globalThis.bewegt }}));
"""
    lauf = subprocess.run(["node", "-e", skript], capture_output=True, text=True)
    assert lauf.returncode == 0, f"{lauf.stderr}\n{lauf.stdout}"
    return json.loads(lauf.stdout)


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_ein_kleines_stueck_hoch_beendet_das_mitfolgen():
    """⛔ The regression this exists for. `wheel` fires BEFORE `scroll`, and
    scrollGeprueft() used to assign folgtMit from the position with no
    condition -- so a reader who nudged up a little was still inside the
    band when it ran, and it undid what radGedreht() had just decided. The
    next chunk pulled them straight back down. Only a big scroll ever
    escaped, which is exactly "I cannot scroll along"."""
    stand = _lauf("""
        radGedreht({ deltaY: -30 });     // the wheel says: stop following
        scrolleAuf(verlauf.scrollTop - 30);
        runter();                        // the next chunk arrives
    """)
    assert stand["folgtMit"] is False, "the wheel was overwritten by the position check"
    assert stand["scrollTop"] == 2470, "the reader was pulled back"


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_ein_grosses_stueck_hoch_beendet_es_auch():
    """The case that always worked -- kept so a fix aimed at the small one
    cannot quietly break the big one."""
    stand = _lauf("""
        radGedreht({ deltaY: -400 });
        scrolleAuf(verlauf.scrollTop - 400);
        runter();
    """)
    assert stand["folgtMit"] is False
    assert stand["scrollTop"] == 2100


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_am_boden_folgt_die_ansicht_weiter_mit():
    """The silence half. A reader who never scrolled away must still be
    carried along, or the fix above would have traded one broken half for
    the other: "never follows" is not better than "always follows"."""
    stand = _lauf("""
        verlauf.scrollHeight = 3200;   // the answer grew
        runter();
    """)
    assert stand["folgtMit"] is True
    assert stand["scrollTop"] == 2700, "the view did not follow the text"


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_zurueck_an_den_boden_nimmt_das_mitfolgen_wieder_auf():
    """Scrolling back down to the floor resumes following -- the promise
    the comment in the component makes, and the reason the resume side of
    the band cannot simply be deleted."""
    stand = _lauf("""
        radGedreht({ deltaY: -300 });
        scrolleAuf(verlauf.scrollTop - 300);
        scrolleAuf(verlauf.scrollHeight - verlauf.clientHeight);   // back down
    """)
    assert stand["folgtMit"] is True


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_ein_sprung_der_nichts_bewegt_frisst_den_naechsten_leser_scroll_nicht():
    """The older regression, kept beside its sibling: a programmatic snap
    that moves nothing fires no scroll event. A latch that marked own
    snaps used to stay armed there and swallowed the reader's NEXT real
    scroll instead. The latch is gone; this keeps it gone."""
    stand = _lauf("""
        scrolleAuf(verlauf.scrollHeight - verlauf.clientHeight);   // already at the floor
        runter();                        // snaps nothing, must not arm the latch
        radGedreht({ deltaY: -30 });
        scrolleAuf(verlauf.scrollTop - 30);
        runter();
    """)
    assert stand["folgtMit"] is False, "the latch swallowed the reader's scroll"
    assert stand["scrollTop"] == 2470


def test_die_laufende_antwort_wird_an_ort_und_stelle_gezeichnet():
    """The throw-back the follow-along could never catch: `{@html}` rebuilds
    the whole answer on every chunk, the scroll area collapses for one
    frame, and the browser clamps the position — below every event the
    scroll logic sees. The answer is therefore drawn in place instead
    (lib/lebendhtml.js, checked against a real DOM in test_lebendhtml.py).
    Source-text guard: the answer's text wears the action, and `{@html}`
    is not back."""
    quelle = (WURZEL / "frontend/src/teile/Nachricht.svelte").read_text()
    antwort = re.search(
        r'<div class="antwort" onclick=\{antwortKlick\}>.*?\n        </div>',
        quelle,
        re.S,
    )
    assert antwort, "the answer box was not found"
    assert "use:lebendHtml={{ html: stueck.wert," in antwort.group(0), "the answer is no longer drawn in place"
    assert "{@html stueck.wert}" not in antwort.group(0), "the rebuild is back"


def test_die_antwort_traegt_keinen_hoehen_halter_mehr():
    """The height holder pinned the answer's box to the LARGEST height it
    had ever reached. One wrong large measurement and an empty hole stood
    under the text for the rest of the run. Its reason — the full rebuild
    collapsing the box — is gone since the answer is drawn in place
    (lib/lebendhtml.js), so the holder went with it."""
    quelle = (WURZEL / "frontend/src/teile/Nachricht.svelte").read_text()
    assert "hoeheHalten" not in quelle, "the height holder is back"


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_ein_sprung_des_browsers_beendet_das_mitfolgen_nicht():
    """⛔ The field finding. The browser keeps the content in view anchored
    while something above it shrinks (the "reading context" head giving
    way to the text, a document's reading mark vanishing): scrollTop moves
    up by that height and a scroll event fires — with no wheel, no touch,
    no key. Judged by position that read as "the reader left", and
    following switched itself off mid-answer. Only the reader may stop it;
    the next chunk pulls the view back to the floor."""
    stand = _lauf("""
        scrolleAuf(verlauf.scrollHeight - verlauf.clientHeight);   // following, at the floor
        scrolleAuf(verlauf.scrollTop - 115);                        // the browser, not the reader
        verlauf.scrollHeight = 3100;                                // the next chunk
        runter();
    """)
    assert stand["folgtMit"] is True, "a jump of the browser ended the following"
    assert stand["abstand"] == 0, "the view is not back at the bottom"


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_ein_sprung_des_browsers_wird_im_selben_bild_zurueckgeholt():
    """The same jump with NO chunk following it. The model may take a
    minute over its next word; the reader must not sit that minute a
    head's height above the floor. The scroll event itself is the cue:
    still following and not at the floor means the browser moved the
    view, and the floor is re-taken at once."""
    stand = _lauf("""
        scrolleAuf(verlauf.scrollHeight - verlauf.clientHeight);   // following, at the floor
        scrolleAuf(verlauf.scrollTop - 115);                        // the browser, not the reader
    """)
    assert stand["folgtMit"] is True
    assert stand["abstand"] == 0, "the bottom was not brought back at once"


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_die_pfeiltaste_nach_oben_beendet_das_mitfolgen():
    """The keyboard is a reader too — but not inside a field, where the
    arrow moves the caret and the chat must keep following."""
    stand = _lauf("""
        if (tasteHoch({ key: 'ArrowUp', target: { tagName: 'DIV', closest: () => null } })) folgtMit = false;
    """)
    assert stand["folgtMit"] is False
    stand = _lauf("""
        if (tasteHoch({ key: 'ArrowUp', target: { tagName: 'TEXTAREA' } })) folgtMit = false;
        if (tasteHoch({ key: 'ArrowUp', metaKey: true, target: { tagName: 'DIV' } })) folgtMit = false;
        // Inside a picker the arrow walks the list, not the chat.
        if (tasteHoch({ key: 'ArrowUp', target: { tagName: 'DIV', closest: (s) => ({}) } })) folgtMit = false;
    """)
    assert stand["folgtMit"] is True


def test_der_boden_haelt_wenn_box_oder_inhalt_ihre_groesse_aendern():
    """Following means AT the floor, whenever box or content change size.
    The input field grows with what is typed and the box shrinks; a live
    head gives way to the text and the content shrinks. With nothing
    arriving nothing called runter(), so the view stood a head's height
    above the floor until the next chunk. Source-text guard: one observer,
    both the box and its track, calling runter()."""
    quelle = QUELLE.read_text()
    stelle = re.search(
        r"new ResizeObserver\(\(\) => \{\n\s+stelleNachsetzen\(\)\n\s+runter\(\)\n\s+\}\)\n\s+beobachter\.observe\(verlauf\)\n"
        r"\s+const spur = verlauf\.querySelector\('\.spur'\)\n\s+if \(spur\) beobachter\.observe\(spur\)",
        quelle,
    )
    assert stelle, "box and track are no longer both watched for their size"


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_rad_nach_unten_in_bodennaehe_haengt_wieder_ein():
    """The floor of a streaming answer runs away faster than a wheel can
    chase it, so "resume at the floor" alone never resumed. Turning the
    wheel down near the floor means "take me back", and does."""
    stand = _lauf("""
        radGedreht({ deltaY: -200 });                              // reader leaves
        scrolleAuf(verlauf.scrollTop - 150);
        verlauf.scrollHeight = 3100;                               // the answer keeps growing
        radGedreht({ deltaY: 120 });                               // reader turns back down
        runter();
    """)
    assert stand["folgtMit"] is True, "the wheel downwards did not latch on again"
    assert stand["abstand"] == 0


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_rad_nach_unten_weit_oben_haengt_nicht_ein():
    """Far above the floor a down-tick is reading, not returning."""
    stand = _lauf("""
        radGedreht({ deltaY: -300 });
        scrolleAuf(1000);                                          // far up
        radGedreht({ deltaY: 120 });
    """)
    assert stand["folgtMit"] is False


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_der_ausklang_eines_hochwischens_teleportiert_nicht():
    """The tail of a trackpad flick upward emits a few small positive
    deltas; caught on a single tick they teleported the reader to the
    floor right after they had scrolled up. Below the travel bar nothing
    re-engages — one real notch still does."""
    stand = _lauf("""
        radGedreht({ deltaY: -200 });
        scrolleAuf(verlauf.scrollTop - 150);
        radGedreht({ deltaY: 6 });
        radGedreht({ deltaY: 4 });
    """)
    assert stand["folgtMit"] is False, "the trackpad's coasting latched on again"
    assert stand["abstand"] == 150


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_ohne_animationsbilder_nimmt_der_nachzuegler_den_sprung():
    """A hidden window runs no animation frames; the plain timer beside
    them is what still carries the snap. The frames are killed here and
    the floor must be reached anyway — the branch no earlier harness
    could even execute."""
    stand = _lauf("""
        requestAnimationFrame = () => 0;   // the window is covered
        verlauf.scrollHeight = 3300;
        runter();
    """)
    assert stand["folgtMit"] is True
    assert stand["abstand"] == 0, "the latecomer did not fetch the bottom"


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_ein_fingerzug_nach_unten_haengt_beim_loslassen_wieder_ein():
    """The touch half of re-engaging, through the real three handlers:
    drag down past the travel bar near the floor, lift — following is
    back. Mid-drag nothing snaps."""
    stand = _lauf("""
        radGedreht({ deltaY: -200 });
        scrolleAuf(verlauf.scrollTop - 150);
        beruehrungBeginnt({ touches: [{ clientY: 300 }] });
        beruehrungZieht({ touches: [{ clientY: 250 }] });   // finger up = heading down
        beruehrungEndet();
    """)
    assert stand["folgtMit"] is True
    assert stand["abstand"] == 0


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_ein_fingerzug_nach_oben_parkt_und_bleibt_geparkt():
    stand = _lauf("""
        beruehrungBeginnt({ touches: [{ clientY: 300 }] });
        beruehrungZieht({ touches: [{ clientY: 340 }] });   // finger down = looking up
        scrolleAuf(verlauf.scrollTop - 200);
        beruehrungEndet();
    """)
    assert stand["folgtMit"] is False
    assert stand["abstand"] == 200


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_ein_langsamer_fingerzug_nach_oben_beendet_das_mitfolgen_auch():
    """One move event carries a few pixels. Measured per event, a slow,
    deliberate drag up the page never reached the threshold and the next
    paint pulled the reader back to the floor under their finger. The
    distance is summed until the finger turns."""
    stand = _lauf("""
        beruehrungBeginnt({ touches: [{ clientY: 300 }] });
        for (let y = 303; y <= 315; y += 3) beruehrungZieht({ touches: [{ clientY: y }] });
        scrolleAuf(verlauf.scrollTop - 200);
        beruehrungEndet();
    """)
    assert stand["folgtMit"] is False
    assert stand["abstand"] == 200


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_ein_zug_der_umkehrt_zaehlt_von_vorn():
    """A little towards looking up, then a real turn the other way: the
    sum starts over at the turn, so two small moves apart do not add up to
    a stop."""
    stand = _lauf("""
        beruehrungBeginnt({ touches: [{ clientY: 300 }] });
        beruehrungZieht({ touches: [{ clientY: 305 }] });   // 5 towards looking up
        beruehrungZieht({ touches: [{ clientY: 295 }] });   // 10 back: a real turn, the sum resets
        beruehrungZieht({ touches: [{ clientY: 300 }] });   // 5 again — never 8 in one run
    """)
    assert stand["folgtMit"] is True


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_zittern_im_fangzug_setzt_die_fangsumme_nicht_zurueck():
    """Parked, then dragged back down with a pixel of wobble every other
    event: the catch-up sum has to survive the wobble, or the follow-along
    can never be re-armed by hand."""
    stand = _lauf("""
        beruehrungBeginnt({ touches: [{ clientY: 300 }] });
        beruehrungZieht({ touches: [{ clientY: 340 }] });   // 40 down = looking up, parks
        scrolleAuf(verlauf.scrollTop - 100);
        let y = 340;
        for (let i = 0; i < 20; i++) {
          y -= 5; beruehrungZieht({ touches: [{ clientY: y }] });   // heading down
          y += 1; beruehrungZieht({ touches: [{ clientY: y }] });   // a pixel of wobble
        }
        beruehrungEndet();
    """)
    assert stand["folgtMit"] is True
    assert stand["abstand"] == 0


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_nach_einem_fangzug_beendet_zittriges_hochziehen_das_mitfolgen_noch():
    """Ten pixels towards the floor first (past the wobble threshold), then
    a slow drag up with a pixel of wobble every other event: the turn the
    down sum made must be consumed with it, or every further wobble wiped
    the up sum and the follow-along could not be stopped for the rest of
    the touch."""
    stand = _lauf("""
        beruehrungBeginnt({ touches: [{ clientY: 300 }] });
        beruehrungZieht({ touches: [{ clientY: 290 }] });   // 10 towards the floor
        let y = 290;
        for (let i = 0; i < 20; i++) {
          y += 3; beruehrungZieht({ touches: [{ clientY: y }] });   // looking up
          y -= 1; beruehrungZieht({ touches: [{ clientY: y }] });   // a pixel of wobble
        }
        scrolleAuf(verlauf.scrollTop - 200);
        beruehrungEndet();
    """)
    assert stand["folgtMit"] is False
    assert stand["abstand"] == 200


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_ein_knopf_im_verlauf_nimmt_der_tastatur_den_weg_nach_oben_nicht():
    """Focus rests on whatever button was clicked last — a copy button, a
    tool card — and with every button excluded, PageUp and Home stopped
    working for the chat the moment one had been clicked. Only the pickers
    keep the keys: the combobox and its frame, the drop-down, a listbox."""
    stand = _lauf("""
        const knopf = { tagName: 'BUTTON', closest: (s) => (s.includes('button') ? {} : null) };
        if (tasteHoch({ key: 'PageUp', target: knopf })) folgtMit = false;
    """)
    assert stand["folgtMit"] is False
    stand = _lauf("""
        const feld = { tagName: 'DIV', closest: (s) => (s.includes('[role="combobox"]') ? {} : null) };
        if (tasteHoch({ key: 'ArrowUp', target: feld })) folgtMit = false;
        const klapp = { tagName: 'BUTTON', closest: (s) => (s.includes('.klappwahl') ? {} : null) };
        if (tasteHoch({ key: 'Home', target: klapp })) folgtMit = false;
    """)
    assert stand["folgtMit"] is True


def test_die_verdrahtung_der_leser_hoerer_steht_im_markup():
    """The lifted functions are only half the truth: delete a binding and
    every node test above stays green. The markup is the other half."""
    quelle = QUELLE.read_text()
    for bindung in (
        'onscroll={gescrollt}',
        'onwheel={radGedreht}',
        'ontouchstart={beruehrungBeginnt}',
        'ontouchmove={beruehrungZieht}',
        'ontouchend={beruehrungEndet}',
        '<svelte:window onkeydown={tastatur}',
    ):
        assert bindung in quelle, f"wiring missing: {bindung}"
    assert re.search(r"if \(tasteHoch\(ereignis\)\) \{\s+folgtMit = false", quelle), (
        "the window handler no longer asks tasteHoch"
    )



# --- The place a chat was left, put back on opening it --------------------


def _zurueck_programm(stelle: dict, *, folgt: bool, hoehe: int = 1000, bilder_max: int | None = None) -> str:
    """The real `stelleZurueck` and `stelleNachsetzen`, lifted out of the
    component, against a stand-in list of `hoehe` pixels, 200 of them
    visible, scrolled to its floor, with following as the previous chat left
    it. Ends with the call; what follows is up to the test."""
    quelle = QUELLE.read_text()
    stuecke = []
    for name in ("stelleZurueck", "stelleBild", "stelleNachsetzen"):
        treffer = re.search(rf"\n  function {name}\(.*?\n  \}}\n", quelle, re.S)
        assert treffer, f"{name}() not found"
        stuecke.append(treffer.group(0))
    boden = re.search(r"\n  const AM_BODEN = (\d+)\n", quelle)
    assert boden, "AM_BODEN not found"
    gesetzt = re.search(r"\n  const STELLE_BILDER_MAX = (\d+)\n", quelle)
    assert gesetzt, "STELLE_BILDER_MAX not found"
    bilder_max = bilder_max or int(gesetzt.group(1))
    return (
        f"const AM_BODEN = {boden.group(1)};\n"
        f"let folgtMit = {json.dumps(folgt)};\n"
        "let nachsetzenZiel = null;\nlet selbstGerolltChat = null;\n"
        "// A real element clamps what is written to scrollTop.\n"
        f"const verlauf = {{ scrollHeight: {hoehe}, clientHeight: 200, _oben: {max(0, hoehe - 200)},\n"
        "  get scrollTop() { return this._oben },\n"
        "  set scrollTop(v) { this._oben = Math.max(0, Math.min(this.scrollHeight - this.clientHeight, v)) } };\n"
        "const zustand = { aktiverChat: 'c1' };\n"
        "const STELLE_BILDER_MAX = " + str(bilder_max) + ";\n"
        "const gemerkt = [];\nconst stelleMerken = () => gemerkt.push({ oben: verlauf.scrollTop, folgt: folgtMit });\n"
        "// The frames are a queue the test steps through; the first one runs\n"
        "// at once, as the single frame of the place's setting always did.\n"
        "const bilder = [];\nconst requestAnimationFrame = (f) => { bilder.push(f); return bilder.length };\n"
        "const bild = () => { const f = bilder.shift(); if (f) f() };\n"
        + "".join(stuecke)
        + f"\nstelleZurueck({json.dumps(stelle)}, 'c1');\nbild();\n"
    )


def _ausfuehren(programm: str) -> dict:
    lauf = subprocess.run(["node", "-e", programm], capture_output=True, text=True, timeout=30)
    assert lauf.returncode == 0, f"{lauf.stderr}\n{lauf.stdout}"
    return json.loads(lauf.stdout)


def _zurueck(stelle: dict, *, folgt: bool, hoehe: int = 1000) -> dict:
    """Reports where the place ends up and whether the view follows."""
    return _ausfuehren(
        _zurueck_programm(stelle, folgt=folgt, hoehe=hoehe)
        + "console.log(JSON.stringify({ oben: verlauf.scrollTop, folgt: folgtMit }));\n"
    )


@pytest.mark.skipif(shutil.which("node") is None, reason="no node on this machine")
@pytest.mark.parametrize(
    ("stelle", "folgt", "hoehe", "erwartet"),
    [
        # Left at the very top: saved as not following at offset zero, and
        # that place used to be thrown away as if nothing had been stored.
        ({"am_boden": False, "versatz": 0}, True, 1000, {"oben": 0, "folgt": False}),
        ({"am_boden": False, "versatz": 300}, True, 1000, {"oben": 300, "folgt": False}),
        # The silence probe, from a previous chat left at the top: a chat
        # left following comes back following, whatever came before it.
        ({"am_boden": True, "versatz": 0}, False, 1000, {"oben": 800, "folgt": True}),
        # A place that is the floor now (the chat fits the window) follows.
        ({"am_boden": False, "versatz": 0}, True, 150, {"oben": 0, "folgt": True}),
    ],
)
def test_die_stelle_eines_chats_kommt_zurueck(stelle, folgt, hoehe, erwartet):
    assert _zurueck(stelle, folgt=folgt, hoehe=hoehe) == erwartet


@pytest.mark.skipif(shutil.which("node") is None, reason="no node on this machine")
def test_eine_schmale_spalte_waechst_ueber_drei_bilder_und_die_stelle_kommt_an():
    """The first frame finds a list of 1000 px: the place 2000 is out of
    reach. It is held at what exists WITHOUT following, and set again as the
    list grows, until it is reached at 4461 px."""
    stand = _ausfuehren(
        _zurueck_programm({"am_boden": False, "versatz": 2000}, folgt=False, hoehe=1000)
        + """
        // The scroll event the browser fires after each write: at the floor it
        // switches following on (scrollGeprueft), as the real handler does.
        const gescrollt = () => {
          if (verlauf.scrollHeight - verlauf.scrollTop - verlauf.clientHeight <= AM_BODEN) folgtMit = true;
        };
        gescrollt();
        const nach_erstem = { oben: verlauf.scrollTop, folgt: folgtMit };
        verlauf.scrollHeight = 2500; stelleNachsetzen(); gescrollt();
        const nach_zweitem = { oben: verlauf.scrollTop, folgt: folgtMit };
        verlauf.scrollHeight = 4461; stelleNachsetzen(); gescrollt();
        // a later growth of the list must not move the view any more
        verlauf.scrollHeight = 6000; stelleNachsetzen(); gescrollt();
        console.log(JSON.stringify({ nach_erstem, nach_zweitem, oben: verlauf.scrollTop, folgt: folgtMit }));
        """
    )
    # (after each write the scroll event may switch following on at the floor;
    # the next call says "not following" again before anything can use it)
    assert stand["nach_erstem"]["oben"] == 800
    assert stand["nach_zweitem"] == {"oben": 2000, "folgt": False}
    assert stand["oben"] == 2000 and stand["folgt"] is False


@pytest.mark.skipif(shutil.which("node") is None, reason="no node on this machine")
def test_hat_der_leser_selbst_gerollt_kommt_die_stelle_nicht_mehr():
    """The stored place arrives late, after the reader moved the view
    themselves: it stays where they put it (the mark is per chat)."""
    stand = _ausfuehren(
        _zurueck_programm({"am_boden": False, "versatz": 300}, folgt=False, hoehe=150)
        + """
        // reset to a fresh list and a fresh target, the reader has rolled first
        verlauf.scrollHeight = 1000; verlauf._oben = 500;
        selbstGerolltChat = 'c1';
        nachsetzenZiel = { chatId: 'c1', versatz: 300 };
        stelleNachsetzen();
        const gerollt = verlauf.scrollTop;
        // Silence probe: another chat's mark does not hold this one back
        selbstGerolltChat = 'c2';
        nachsetzenZiel = { chatId: 'c1', versatz: 300 };
        stelleNachsetzen();
        console.log(JSON.stringify({ gerollt, anderer_chat: verlauf.scrollTop }));
        """
    )
    assert stand == {"gerollt": 500, "anderer_chat": 300}


def test_ohne_offenen_chat_wird_die_gesetzte_stelle_vergessen():
    """Chat A, no chat, chat A: the place must come back. The effect forgets
    the chat it put a place back for as soon as none is open; the hand's
    mark is set by the three listeners and reset per chat."""
    quelle = QUELLE.read_text()
    wirkung = quelle.split("let stelleGesetztFuer = null", 1)[1]
    assert re.search(r"if \(!chatId\) \{\s+stelleGesetztFuer = null\s+return\s+\}", wirkung), (
        "the placed chat is not forgotten when no chat is open"
    )
    assert quelle.count("selbstGerolltChat = zustand.aktiverChat") == 3, "a listener no longer marks the hand"
    assert "ResizeObserver(() => {\n      stelleNachsetzen()" in quelle, "the observer no longer sets the place again"


@pytest.mark.skipif(shutil.which("node") is None, reason="no node on this machine")
def test_a_place_behind_the_end_is_given_up_after_thirty_frames():
    """The chat is shorter than the place it was left at. The wait ends after
    the last frame: the view stays at what exists, the remembered place is
    brought to it, following is on again — and a list that grows past the old
    place much later does not set the view back there."""
    stand = _ausfuehren(
        _zurueck_programm({"am_boden": False, "versatz": 2000}, folgt=False, hoehe=1000)
        + """
        const vor = { ziel: nachsetzenZiel !== null, folgt: folgtMit, bilder: bilder.length };
        for (let i = 0; i < 28; i += 1) bild();           // frames 2 .. 29: still waiting
        const nach29 = { ziel: nachsetzenZiel !== null, folgt: folgtMit };
        bild();                                          // frame 30: given up
        const nach30 = { ziel: nachsetzenZiel !== null, folgt: folgtMit, oben: verlauf.scrollTop, gemerkt };
        verlauf.scrollHeight = 4461; stelleNachsetzen(); // a growth in one step, much later
        console.log(JSON.stringify({ vor, nach29, nach30, spaeter: verlauf.scrollTop }));
        """
    )
    assert stand["vor"] == {"ziel": True, "folgt": False, "bilder": 1}
    assert stand["nach29"] == {"ziel": True, "folgt": False}
    assert stand["nach30"]["ziel"] is False and stand["nach30"]["folgt"] is True
    assert stand["nach30"]["oben"] == 800
    assert stand["nach30"]["gemerkt"] == [{"oben": 800, "folgt": True}]
    assert stand["spaeter"] == 800, "the old place was set again after the wait had ended"


@pytest.mark.skipif(shutil.which("node") is None, reason="no node on this machine")
def test_a_place_that_becomes_reachable_in_time_is_set_as_before():
    """Silence probe: the list grows at the fifth frame; the place is set
    there, the wait is over, nothing is given up or remembered anew."""
    stand = _ausfuehren(
        _zurueck_programm({"am_boden": False, "versatz": 2000}, folgt=False, hoehe=1000)
        + """
        for (let i = 0; i < 3; i += 1) bild();           // frames 2 .. 4
        verlauf.scrollHeight = 4461;
        bild();                                          // frame 5
        console.log(JSON.stringify({ ziel: nachsetzenZiel !== null, oben: verlauf.scrollTop,
                                     folgt: folgtMit, gemerkt, uebrig: bilder.length }));
        """
    )
    assert stand == {"ziel": False, "oben": 2000, "folgt": False, "gemerkt": [], "uebrig": 0}


@pytest.mark.skipif(shutil.which("node") is None, reason="no node on this machine")
def test_the_observer_of_the_list_costs_no_frame():
    """Silence probe: `stelleNachsetzen` called by the size observer as often
    as it likes does not count towards the thirty."""
    stand = _ausfuehren(
        _zurueck_programm({"am_boden": False, "versatz": 2000}, folgt=False, hoehe=1000)
        + """
        for (let i = 0; i < 100; i += 1) stelleNachsetzen();
        console.log(JSON.stringify({ ziel: nachsetzenZiel !== null, folgt: folgtMit, bilder: bilder.length }));
        """
    )
    assert stand == {"ziel": True, "folgt": False, "bilder": 1}


@pytest.mark.skipif(shutil.which("node") is None, reason="no node on this machine")
def test_the_hand_ends_the_wait_before_the_frames_run_out():
    stand = _ausfuehren(
        _zurueck_programm({"am_boden": False, "versatz": 2000}, folgt=False, hoehe=1000)
        + """
        selbstGerolltChat = 'c1';
        bild();
        console.log(JSON.stringify({ ziel: nachsetzenZiel !== null, bilder: bilder.length, gemerkt }));
        """
    )
    assert stand == {"ziel": False, "bilder": 0, "gemerkt": []}


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_das_mitlaufen_gleitet_ueber_mehrere_bilder_statt_in_einem_schritt():
    """A line of text arrives: the floor moves by a line's height at once.
    The view reaches it over several frames, each a part of the way, the way
    a spring does, and ends exactly at the floor (before: one write, the
    whole way, in the next frame)."""
    stand = _lauf(
        """
        verlauf.scrollHeight = 3026;   // one line of 26 px came in
        runter();
        const wege = [];
        for (let k = 0; k < 40 && abstand() > 0; k += 1) {
          const vorher = verlauf.scrollTop;
          takt();
          wege.push(verlauf.scrollTop - vorher);
        }
        globalThis.wege = wege;
        """,
        bilder="getaktet",
    )
    # The report line carries the end state; the frames are read below.
    assert stand["abstand"] == 0 and stand["folgtMit"] is True
    assert stand["wege"][0] < 26, "the whole line was taken in one frame"
    assert len([w for w in stand["wege"] if w > 0]) >= 4, stand["wege"]
    # Each frame takes less than the one before: a spring, not a ramp.
    positive = [w for w in stand["wege"] if w > 0]
    assert all(a >= b for a, b in zip(positive, positive[1:])), positive


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_nach_dem_hochscrollen_bewegt_eine_neue_zeile_die_ansicht_nicht():
    """Silence probe: the reader scrolled up; a new line moves nothing, not
    even a part of the way — and a glide that was running stops with the
    wheel."""
    stand = _lauf(
        """
        verlauf.scrollHeight = 3100;
        runter();
        takt();                         // the glide is under way
        radGedreht({ deltaY: -30 });    // the reader turns the wheel up
        const dort = verlauf.scrollTop;
        scrolleAuf(dort - 30);
        const gelesen = verlauf.scrollTop;
        verlauf.scrollHeight = 3200;    // another line
        runter();
        takt(10);
        globalThis.bewegt = verlauf.scrollTop - gelesen;
        """,
        bilder="getaktet",
    )
    assert stand["folgtMit"] is False
    assert stand["bewegt"] == 0, "the view moved under a reader who scrolled away"
