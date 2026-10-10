"""The chat's one mark slot decides its face (`frontend/src/App.svelte`).

`laufMarke` is lifted out of the component and run in node, the same way
tests/test_chatscrollen.py runs the follow-along: its branches were
otherwise pinned by nothing but a template substring.
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
RINGE = WURZEL / "frontend/src/lib/chatringe.svelte.js"


def _laufmarke() -> str:
    quelle = QUELLE.read_text()
    treffer = re.search(
        r"const laufMarke = \$derived\.by\((\(\) => \{.*?\n  \})\)\n", quelle, re.S
    )
    assert treffer, "laufMarke not found"
    # The question check it asks is the ring's own (lib/chatringe.svelte.js),
    # lifted the same way so the real one runs.
    frage = re.search(r"export function fragtNach\(chatId\) \{.*?\n\}", RINGE.read_text(), re.S)
    assert frage, "fragtNach not found"
    return frage.group(0).removeprefix("export ") + f"\nconst laufMarke = {treffer.group(1)};\n"


def _lauf(nachrichten: list, laufender_id: str | None = None, fragen: dict | None = None) -> dict | None:
    skript = f"""
const t = (pfad) => pfad;
const zustand = {{
  nachrichten: {json.dumps(nachrichten)}, aktiverChat: 'c1',
  werkzeugfrage: {{}}, benutzerfrage: {{}}, jobfrage: {{}}, ...{json.dumps(fragen or {})},
}};
const nachrichtenAnzeige = () => zustand.nachrichten;
const laufenderId = {json.dumps(laufender_id)};
{_laufmarke()}
console.log(JSON.stringify(laufMarke()));
"""
    lauf = subprocess.run(["node", "-e", skript], capture_output=True, text=True)
    assert lauf.returncode == 0, f"{lauf.stderr}\n{lauf.stdout}"
    return json.loads(lauf.stdout)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed here")
def test_ohne_lauf_steht_keine_marke():
    assert _lauf([{"role": "user", "content": "hallo"}]) is None


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed here")
def test_ein_laufendes_bild_ohne_text_traegt_keine_zweite_marke():
    marke = _lauf([
        {"role": "assistant", "zustand": "laeuft", "content": "", "bildLaeuft": True},
    ])
    assert marke is None


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed here")
def test_die_verdichtung_traegt_stapel_und_eigenes_wort():
    marke = _lauf([
        {"role": "assistant", "zustand": "laeuft", "content": "", "taetigkeit": "verdichtung"},
    ])
    assert marke == {"art": "verdichtung", "text": "status.komprimiert"}


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed here")
def test_the_mark_stays_under_written_text_until_the_run_ends():
    """A server may hold a tool call back until it is whole and send nothing
    for minutes after the first sentence; the mark is then the only sign
    on the line that the run still goes."""
    row = {"role": "assistant", "zustand": "laeuft", "content": "text already"}
    assert _lauf([dict(row, taetigkeit="schreibt")]) == {"art": "antwort", "text": ""}
    # The same after a tool call mid-answer, with text in the last stretch.
    sections = [
        {"art": "content", "text": "text already", "seit": 1},
        {"art": "werkzeug", "aufruf_id": "a", "seit": 2},
        {"art": "content", "text": "more text", "seit": 3},
    ]
    tools = [{"aufruf_id": "a", "name": "x", "ergebnis": "done"}]
    mark = _lauf([dict(row, abschnitte=sections, werkzeuge=tools, taetigkeit="schreibt")])
    assert mark == {"art": "antwort", "text": ""}


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed here")
def test_a_finished_run_carries_no_mark():
    """Silence probe: the window still holds its placeholder while the end
    of the run fetches a fresh history, and the row already carries its
    closing word — every one the service writes takes the mark away."""
    for closing in ("fertig", "abgebrochen", "fehler"):
        row = {"id": "p1", "role": "assistant", "zustand": closing, "content": "done",
               "taetigkeit": "schreibt"}
        assert _lauf([row], laufender_id="p1") is None, closing


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed here")
def test_the_mark_stays_under_a_running_tool():
    """A tool row has no clock of its own; the mark keeps the stretch's
    clock on the line until the result is in — on a row from the service
    and on this window's own placeholder, which has no closing word yet."""
    row = {"content": "text already", "taetigkeit": "werkzeug", "taetigkeitSeit": 9,
           "role": "assistant",
           "abschnitte": [{"art": "content", "text": "text already", "seit": 1},
                          {"art": "werkzeug", "aufruf_id": "a", "seit": 2}],
           "werkzeuge": [{"aufruf_id": "a", "name": "x", "ergebnis": None}]}
    assert _lauf([dict(row, zustand="laeuft")]) == {"art": "antwort", "text": "", "seit": 9}
    own = dict(row, id="p1")
    assert _lauf([own], laufender_id="p1") == {"id": "p1", "art": "antwort", "text": "", "seit": 9}


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed here")
def test_auge_nur_solange_kein_text_und_kein_werkzeug():
    zeile = {"role": "assistant", "zustand": "laeuft", "content": "", "vision": True}
    assert _lauf([dict(zeile)]) == {"art": "vision", "text": ""}
    assert _lauf([dict(zeile, content="schon Text")])["art"] == "antwort"
    assert _lauf([dict(zeile, werkzeuge=[{"name": "x"}])])["art"] == "antwort"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed here")
def test_der_platzhalter_dieses_fensters_zaehlt_ueber_seine_kennung():
    marke = _lauf(
        [{"id": "platzhalter-c1", "role": "assistant", "content": ""}],
        laufender_id="platzhalter-c1",
    )
    assert marke == {"id": "platzhalter-c1", "art": "antwort", "text": ""}


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed here")
def test_der_kontext_traegt_seine_eigene_uhr():
    marke = _lauf([
        {"role": "assistant", "zustand": "laeuft", "content": "", "taetigkeit": "kontext",
         "taetigkeitSeit": 5},
    ])
    assert marke == {"art": "antwort", "text": "", "kontext": True, "seit": 5}
    # Text already written does not hide it: after a tool result the model
    # reads the grown context back through, mid-answer.
    marke = _lauf([
        {"role": "assistant", "zustand": "laeuft", "content": "text already",
         "taetigkeit": "kontext", "taetigkeitSeit": 7},
    ])
    assert marke == {"art": "antwort", "text": "", "kontext": True, "seit": 7}


HILFE = WURZEL / "frontend/src/lib/taetigkeit.js"


def _taetigkeit(schritte: list) -> list:
    """Runs lib/taetigkeit.js's `taetigkeitSetzen` in node over
    (art, seit, neu) steps and returns the placeholder after each one."""
    skript = f"""
const {{ taetigkeitSetzen }} = await import({json.dumps(HILFE.as_uri())});
const zeile = {{ taetigkeit: 'kontext', taetigkeitSeit: 1 }};
const stand = [];
for (const [art, seit, neu] of {json.dumps(schritte)}) {{
  taetigkeitSetzen(zeile, art, seit, neu);
  stand.push({{ ...zeile }});
}}
console.log(JSON.stringify(stand));
"""
    lauf = subprocess.run(
        ["node", "--input-type=module", "-e", skript], capture_output=True, text=True
    )
    assert lauf.returncode == 0, f"{lauf.stderr}\n{lauf.stdout}"
    return json.loads(lauf.stdout)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed here")
def test_eine_neue_taetigkeit_stellt_die_uhr_neu_dieselbe_nicht():
    stand = _taetigkeit([
        ["denkt", 10, False],      # change: new start
        ["denkt", 20, False],      # the same activity again: the clock runs on
        ["werkzeug", 30, False],   # change: new start
        ["kontext", 40, True],     # a tool result: new start
        ["kontext", 50, True],     # another one straight after: new start again
        ["kontext", 60, False],    # the same activity without `neu`: runs on
        ["denkt", None, False],    # no time from the service: the moment of reading
    ])
    assert [s["taetigkeitSeit"] for s in stand[:6]] == [10, 10, 30, 40, 50, 50]
    assert [s["taetigkeit"] for s in stand] == [
        "denkt", "denkt", "werkzeug", "kontext", "kontext", "kontext", "denkt",
    ]
    # Date.now() in milliseconds — not null, not the epoch.
    assert stand[6]["taetigkeitSeit"] > 1_600_000_000_000


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed here")
def test_waehrend_eine_frage_steht_tritt_die_marke_zur_seite():
    zeile = {"role": "assistant", "zustand": "laeuft", "content": "", "taetigkeit": "werkzeug",
             "taetigkeitSeit": 3}
    # Read off the boxes themselves: whichever of the three questions stands
    # for this chat, the yellow entry speaks and the mark steps aside.
    for kasten in ("werkzeugfrage", "benutzerfrage", "jobfrage"):
        assert _lauf([zeile], fragen={kasten: {"c1": {"aufrufId": "a"}}}) is None, kasten
    # A question standing in ANOTHER chat does not touch this one.
    assert _lauf([zeile], fragen={"werkzeugfrage": {"c2": {"aufrufId": "a"}}})["art"] == "antwort"


# --- The eye mark survives a reattach ---------------------------------------


def _frage_trug_bild(quelle: str) -> str:
    """`frageTrugBild` as it stands in App.svelte."""
    hilfe = re.search(r"  function frageTrugBild\(zeile\) \{.*?\n  \}", quelle, re.S)
    assert hilfe, "frageTrugBild not found"
    return hilfe.group(0)


def _uebernahme(nachrichten: list, wiederanhang: str) -> dict:
    """The adoption block out of App.svelte, over the list a scenario sets.

    A reattach adopts a row that came from the service. The service does not
    store `vision` on a row — the QUESTION does, and the block has to read it
    there, or the eye mark of image recognition turns into an ordinary
    waiting mark the moment the page is reloaded.
    """
    quelle = QUELLE.read_text()
    block = re.search(
        r"    const uebernehmen = wiederanhang\?\.messageId\n.*?"
        r"\n      uebernehmen\.gesamt_tokens = null\n    \}",
        quelle,
        re.S,
    )
    assert block, "the adoption block was not found"
    hilfe = _frage_trug_bild(quelle)
    skript = f"""
const zustand = {{ nachrichten: {json.dumps(nachrichten)} }}
const taetigkeitSetzen = () => {{}}
const wiederanhang = {wiederanhang}
const bilder = undefined
{hilfe}
{block.group(0)}
console.log(JSON.stringify(zustand.nachrichten))
"""
    lauf = subprocess.run(["node", "-e", skript], capture_output=True, text=True)
    assert lauf.returncode == 0, f"{lauf.stderr}\n{lauf.stdout}"
    return json.loads(lauf.stdout)[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed here")
def test_die_uebernommene_zeile_behaelt_ihre_augenmarke():
    """Silence probe: a row that already showed the eye keeps showing it."""
    zeile = {"id": "a1", "role": "assistant", "content": "alt", "vision": True}
    danach = _uebernahme(
        [{"id": "u1", "role": "user", "content": "was ist das", "bild": "foto.png"}, zeile],
        '{"chatId": "c1", "generationId": "g1", "messageId": "a1"}',
    )
    assert danach["vision"] is True


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed here")
def test_die_augenmarke_kommt_aus_der_frage_die_die_zeile_beantwortet():
    """The service does not store `vision`; the question above the row is
    what says whether the eye belongs here. Without that reading the field
    was written `false` on every reattach, and the eye mark vanished."""
    zeile = {"id": "a1", "role": "assistant", "content": "alt"}
    danach = _uebernahme(
        [{"id": "u1", "role": "user", "content": "was ist das", "bild": "foto.png"}, zeile],
        '{"chatId": "c1", "generationId": "g1", "messageId": "a1"}',
    )
    assert danach["vision"] is True


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed here")
def test_eine_frage_mit_mehreren_bildern_zaehlt_ebenso():
    """A question may carry a list of pictures instead of one (`anhaenge`) —
    the same reading Nachricht.svelte uses decides here."""
    zeile = {"id": "a1", "role": "assistant", "content": "alt"}
    danach = _uebernahme(
        [{"id": "u1", "role": "user", "content": "beides", "anhaenge": ["a.png", "b.png"]}, zeile],
        '{"chatId": "c1", "generationId": "g1", "messageId": "a1"}',
    )
    assert danach["vision"] is True


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed here")
def test_ohne_bild_in_der_frage_bleibt_die_marke_weg():
    """Silence probe: nothing turns into an eye mark that was not one."""
    zeile = {"id": "a1", "role": "assistant", "content": "alt"}
    danach = _uebernahme(
        [{"id": "u1", "role": "user", "content": "nur text"}, zeile],
        '{"chatId": "c1", "generationId": "g1", "messageId": "a1"}',
    )
    assert danach["vision"] is False


def _pushed_row_vision(nachrichten: list) -> bool:
    """`frageTrugBild(null)` — what the row a reattach PUSHES (nothing to
    adopt) reads for its eye mark: the question the last row answers."""
    skript = f"""
const zustand = {{ nachrichten: {json.dumps(nachrichten)} }}
{_frage_trug_bild(QUELLE.read_text(encoding="utf-8"))}
console.log(JSON.stringify(frageTrugBild(null)))
"""
    lauf = subprocess.run(["node", "-e", skript], capture_output=True, text=True, timeout=60)
    assert lauf.returncode == 0, f"{lauf.stderr}\n{lauf.stdout}"
    return json.loads(lauf.stdout)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed here")
def test_a_pushed_row_reads_the_eye_off_the_last_question():
    """A reattach with no row to adopt pushes one at the end; its eye mark
    comes from the last question in the list — past a picture run's prompt
    and a fold's summary, which carry the role `user` too."""
    assert _pushed_row_vision([
        {"id": "u1", "role": "user", "content": "what is this", "bild": "foto.png"},
        {"id": "b1", "role": "user", "art": "bildlauf", "content": "a prompt"},
        {"id": "s1", "role": "user", "art": "verdichtung", "content": "summary"},
    ]) is True


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed here")
def test_a_pushed_row_after_a_plain_question_has_no_eye():
    """Silence probe: the last question carried no picture — an older one
    that did does not count."""
    assert _pushed_row_vision([
        {"id": "u0", "role": "user", "content": "old", "bild": "foto.png"},
        {"id": "a0", "role": "assistant", "content": "answer"},
        {"id": "u1", "role": "user", "content": "text only"},
    ]) is False
    assert _pushed_row_vision([]) is False
