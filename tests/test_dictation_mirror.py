"""The mirror over the field while somebody dictates (frontend/src/lib/dictationMirror.js).

Run in node, like tests/test_diktatabgleich.py: what is asserted is what the
real module answers. The cases walk one spoken sentence through the three
states the mirror takes — the beginning settled with the rest still grey,
settled further in, then the whole sentence in the field once the pass after
the stop has answered.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="no node on this machine")

MODULE = Path(__file__).resolve().parent.parent / "frontend/src/lib/dictationMirror.js"
READINGS = Path(__file__).resolve().parent.parent / "frontend/src/lib/diktatabgleich.js"

# What was spoken, and the two states of it the mirror showed before the stop.
SENTENCE = (
    "Kannst du mir bitte erklären, wie das Wetter morgen in Berlin wird und ob "
    "ich einen Regenschirm mitnehmen sollte, weil ich den ganzen Tag unterwegs "
    "bin und am Abend noch ins Kino gehe?"
)
BEGINNING = ("Kannst du", "mir bitte erklären")
FURTHER = ("Kannst du mir bitte erklären, wie das Wetter morgen in Berlin", "wird und ich einen Regen.")


def _node(script: str, *sources: Path):
    code = "\n".join(
        re.sub(r"^export ", "", pfad.read_text(encoding="utf-8"), flags=re.M) for pfad in (MODULE, *sources)
    )
    run = subprocess.run(["node", "-e", f"{code}\n{script}"], capture_output=True, text=True, encoding="utf-8")
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def _shown(field_text: str, settled: str, unsure: str, spot: tuple[int, int]) -> dict:
    """The mirror over a field holding `field_text`, one reading in: what it
    lays over the field, ready to be shown."""
    script = (
        "const m = mirrorReading(startMirror(%s, %d, %d).mirror, %s, %s)\n"
        "console.log(JSON.stringify(mirrorParts(m)))"
    ) % (json.dumps(field_text), spot[0], spot[1], json.dumps(settled), json.dumps(unsure))
    return _node(script)


def test_a_dictation_begins_at_the_spot_the_words_will_take():
    # The field was in hand, the cursor stood between two words.
    assert _node("console.log(JSON.stringify(startMirror('Hallo Welt', 5, 5)))") == {
        "mirror": {"davor": "Hallo", "danach": " Welt", "fest": "", "unsicher": ""},
        "range": {"basis": "Hallo Welt", "von": 5, "bis": 5},
    }
    # A marked piece is the spot: the words take its place, nothing of it
    # stands behind them twice.
    assert _node("console.log(JSON.stringify(startMirror('Hallo Welt', 0, 5).mirror))") == {
        "davor": "",
        "danach": " Welt",
        "fest": "",
        "unsicher": "",
    }


def test_the_settled_words_and_the_grey_rest_are_shown_over_the_field():
    # The first readings: the beginning settled, the rest still grey.
    assert _shown("", *BEGINNING, (0, 0)) == {
        "davor": "",
        "fest": "Kannst du ",
        "unsicher": "mir bitte erklären",
        "danach": "",
    }
    # Further in: the settled text reaches the middle of the sentence, the
    # grey rest behind it.
    assert _shown("", *FURTHER, (0, 0)) == {
        "davor": "",
        "fest": "Kannst du mir bitte erklären, wie das Wetter morgen in Berlin ",
        "unsicher": "wird und ich einen Regen.",
        "danach": "",
    }


def test_the_mirror_carries_the_fields_own_text_around_the_words():
    # Dictated into a draft: what stood before and behind the spot is shown
    # with it, and a word gap only where the text in front does not end in
    # one of its own.
    assert _shown("Bitte sehr: ", *BEGINNING, (12, 12)) == {
        "davor": "Bitte sehr: ",
        "fest": "Kannst du ",
        "unsicher": "mir bitte erklären",
        "danach": "",
    }
    # The text before ends in a letter — the gap between it and the words is
    # the mirror's, not the text's.
    assert _shown("Notiz", *BEGINNING, (5, 5)) == {
        "davor": "Notiz ",
        "fest": "Kannst du ",
        "unsicher": "mir bitte erklären",
        "danach": "",
    }
    # Behind the words the field's own text follows, unchanged.
    assert _shown(" — so war das", *BEGINNING, (0, 0)) == {
        "davor": "",
        "fest": "Kannst du ",
        "unsicher": "mir bitte erklären",
        "danach": " — so war das",
    }
    # The field's own text on both sides at once: the gap stands only on the
    # side the words are spoken into.
    assert _shown("Hallo Welt", *BEGINNING, (5, 5)) == {
        "davor": "Hallo ",
        "fest": "Kannst du ",
        "unsicher": "mir bitte erklären",
        "danach": " Welt",
    }


def test_the_first_readings_keep_the_mirrors_spacing_the_same_as_the_fields():
    """One reading into a dictation at the end of a draft: nothing settled
    yet, only the grey end. No word stands there yet, so no gap stands there
    either — the field later holds exactly this text."""
    assert _shown("Notiz", "", "Kannst du mir", (5, 5)) == {
        "davor": "Notiz ",
        "fest": "",
        "unsicher": "Kannst du mir",
        "danach": "",
    }
    # Nothing spoken at all: the draft keeps exactly its own text.
    assert _shown("Notiz", "", "", (5, 5)) == {
        "davor": "Notiz",
        "fest": "",
        "unsicher": "",
        "danach": "",
    }


def test_silence_probe_an_empty_mirror_grows_no_word_gap():
    # Nothing in front, nothing settled, nothing grey: the mirror is empty
    # rather than a run of gaps.
    assert _shown("", "", "", (0, 0)) == {"davor": "", "fest": "", "unsicher": "", "danach": ""}
    # A settled word with no grey rest behind it carries no gap of its own.
    assert _shown("", "Kannst du", "", (0, 0))["fest"] == "Kannst du"
    # A mirror that carries no field text at all shows none, not the word
    # "undefined" — the field around the words is not always filled in.
    assert _node(
        "console.log(JSON.stringify(mirrorParts({ fest: 'Kannst du', unsicher: 'mir' })))"
    ) == {"davor": "", "fest": "Kannst du ", "unsicher": "mir", "danach": ""}
    # Nor with no mirror at all, and nor one that carries a null where a text
    # belongs: the draft must never show the word "null" in its own colour.
    assert _node("console.log(JSON.stringify(mirrorParts()))") == {
        "davor": "",
        "fest": "",
        "unsicher": "",
        "danach": "",
    }
    assert _node(
        "console.log(JSON.stringify(mirrorParts({ davor: null, fest: 'Kannst du', unsicher: null })))"
    ) == {"davor": "", "fest": "Kannst du", "unsicher": "", "danach": ""}


def test_a_reading_settles_more_words_in_the_mirror():
    """The mirror takes what the readings settle (lib/diktatabgleich.js) —
    three readings that agree on a word make it settled, and the mirror stops
    showing it grey."""
    gezeigt = _node(
        """
let stand = neuerStand()
let m = startMirror('', 0, 0).mirror
for (const text of ['Kannst du', 'Kannst du mir', 'Kannst du mir bitte']) {
  const r = abgleichen(stand, text)
  stand = r.stand
  m = mirrorReading(m, r.fest, r.unsicher)
}
console.log(JSON.stringify(mirrorParts(m)))
""",
        READINGS,
    )
    assert gezeigt == {
        "davor": "",
        "fest": "Kannst du ",
        "unsicher": "mir bitte",
        "danach": "",
    }


def test_the_words_land_where_the_mirror_stood_and_the_cursor_behind_them():
    # The stop's pass over the whole recording: the sentence goes where the
    # words were shown, in place of them.
    assert _node(
        "console.log(JSON.stringify(placeWords('', { range: { basis: '', von: 0, bis: 0 },"
        f" spoken: {json.dumps(SENTENCE)} }})))"
    ) == {"text": SENTENCE, "caret": len(SENTENCE)}


def test_the_words_land_in_the_range_the_mirror_stood_at():
    """The field still holds what it held when the dictation began: then the
    spot the mirror was shown at decides the placement, not the cursor, which
    stands somewhere else."""
    assert _node(
        "console.log(JSON.stringify(placeWords('Hallo Welt',"
        " { range: { basis: 'Hallo Welt', von: 6, bis: 10 },"
        " cursor: { start: 0, end: 0 }, spoken: 'Erde' })))"
    ) == {"text": "Hallo Erde", "caret": 10}


def test_a_word_gap_is_set_only_where_the_text_needs_one():
    place = (
        "console.log(JSON.stringify(placeWords(%s, { range: %s, spoken: 'Kannst du' })))"
    )
    # In front of a letter: one gap, so dictating twice in a row reads as one
    # thought.
    assert _node(place % (json.dumps("Notiz"), "null")) == {"text": "Notiz Kannst du", "caret": 15}
    # In front of a space or an empty field: none.
    assert _node(place % (json.dumps("Notiz "), "null")) == {
        "text": "Notiz Kannst du",
        "caret": 15,
    }
    assert _node(place % (json.dumps(""), "null")) == {"text": "Kannst du", "caret": 9}


def test_dictating_in_front_of_a_draft_leaves_a_gap_behind_the_words():
    """Dictated with the cursor at the start of a draft: the words and the
    draft are two words, not one, in the field and in the mirror alike."""
    place = (
        "console.log(JSON.stringify(placeWords(%s,"
        " { range: { basis: %s, von: 0, bis: 0 }, spoken: 'Hallo' })))"
    )
    assert _node(place % (json.dumps("Welt"), json.dumps("Welt"))) == {
        "text": "Hallo Welt",
        "caret": 5,
    }
    assert _shown("Welt", "Hallo", "", (0, 0)) == {
        "davor": "",
        "fest": "Hallo",
        "unsicher": "",
        "danach": " Welt",
    }
    assert _shown("Welt", "", "Hallo", (0, 0))["danach"] == " Welt"
    # Silence probe: a draft that already begins with a gap gets no second
    # one, and neither does a mirror with no words in it yet.
    assert _node(place % (json.dumps(" Welt"), json.dumps(" Welt"))) == {
        "text": "Hallo Welt",
        "caret": 5,
    }
    assert _shown(" Welt", "Hallo", "", (0, 0))["danach"] == " Welt"
    assert _shown("Welt", "", "", (0, 0))["danach"] == "Welt"
    # Nor in front of a mark that closes the sentence: a word dictated over
    # the last one keeps its full stop right behind it.
    assert _node(
        "console.log(JSON.stringify(placeWords('Ich gehe heim.',"
        " { range: { basis: 'Ich gehe heim.', von: 9, bis: 13 }, spoken: 'nach Hause' })))"
    ) == {"text": "Ich gehe nach Hause.", "caret": 19}
    assert _shown("Hallo Welt!", "Erde", "", (6, 10))["danach"] == "!"


def test_a_german_opening_guillemet_gets_a_gap_and_a_closing_one_does_not():
    """In German text \u00bb opens a quotation and \u00ab closes it: a word
    dictated in front of a quotation stands apart from it, a word dictated
    at the end of one keeps the closing mark right behind it."""
    place = (
        "console.log(JSON.stringify(placeWords(%s,"
        " { range: { basis: %s, von: 0, bis: 0 }, spoken: 'Hallo' })))"
    )
    quoted = "\u00bbZitat\u00ab in Guillemets"
    assert _node(place % (json.dumps(quoted), json.dumps(quoted))) == {
        "text": "Hallo \u00bbZitat\u00ab in Guillemets",
        "caret": 5,
    }
    assert _shown(quoted, "Hallo", "", (0, 0))["danach"] == " " + quoted
    # Silence probe: no gap in front of a full stop, a comma or a closing
    # guillemet.
    for mark in (".", ",", "\u00ab"):
        text = "\u00bbEin Zitat" + mark
        assert _node(
            "console.log(JSON.stringify(placeWords(%s,"
            " { range: { basis: %s, von: 5, bis: 10 }, spoken: 'Wort' })))"
            % (json.dumps(text), json.dumps(text))
        ) == {"text": "\u00bbEin Wort" + mark, "caret": 9}
        assert _shown(text, "Wort", "", (5, 10))["danach"] == mark


def test_a_word_dictated_right_behind_an_opening_guillemet_follows_it_directly():
    """\u00bb opens a German quotation: the word dictated behind it belongs
    to the quotation and follows the mark without a gap."""
    place = "console.log(JSON.stringify(placeWords(%s, { range: null, spoken: 'Wort' })))"
    assert _node(place % json.dumps("Er sagt \u00bb")) == {
        "text": "Er sagt \u00bbWort",
        "caret": 13,
    }
    assert _shown("Er sagt \u00bb", "Wort", "", (13, 13))["davor"] == "Er sagt \u00bb"
    # Silence probe: behind a closing \u00ab and behind a plain word the gap
    # stays, as in front of any other word.
    assert _node(place % json.dumps("\u00bbZitat\u00ab")) == {
        "text": "\u00bbZitat\u00ab Wort",
        "caret": 12,
    }
    assert _shown("\u00bbZitat\u00ab", "Wort", "", (7, 7))["davor"] == "\u00bbZitat\u00ab "
    assert _node(place % json.dumps("Notiz")) == {"text": "Notiz Wort", "caret": 10}
    assert _shown("Notiz", "Wort", "", (5, 5))["davor"] == "Notiz "


def test_the_words_go_to_the_cursor_when_the_field_changed_under_the_dictation():
    """Another chat opened while the words were still coming in: the spot the
    mirror was shown at is gone, so the field's cursor decides."""
    assert _node(
        "console.log(JSON.stringify(placeWords('Ein Text',"
        " { range: { basis: '', von: 0, bis: 0 }, cursor: { start: 3, end: 3 },"
        " spoken: 'Kannst du' })))"
    ) == {"text": "Ein Kannst du Text", "caret": 13}
    # The field was not in hand at all: the end of what stands there.
    assert _node(
        "console.log(JSON.stringify(placeWords('Ein Text',"
        " { range: { basis: '', von: 0, bis: 0 }, spoken: 'Kannst du' })))"
    ) == {"text": "Ein Text Kannst du", "caret": 18}
    # A marked piece is replaced rather than spoken into.
    assert _node(
        "console.log(JSON.stringify(placeWords('Hallo Welt',"
        " { range: null, cursor: { start: 6, end: 10 }, spoken: 'Erde' })))"
    ) == {"text": "Hallo Erde", "caret": 10}
    # A spot counts only with both of its two positions. Half a range — or a
    # bare number where an object belongs — would put the whole field's text
    # behind the words instead of placing them somewhere.
    assert _node(
        "console.log(JSON.stringify(["
        "placeWords('abc', { range: { basis: 'abc' }, spoken: 'X' }),"
        "placeWords('Hallo Welt', { cursor: 3, spoken: 'X' }),"
        "placeWords('abc')]))"
    ) == [
        {"text": "abc X", "caret": 5},
        {"text": "Hallo Welt X", "caret": 12},
        {"text": "abc", "caret": 3},
    ]


def test_the_mirror_follows_the_field_when_its_text_changes_under_it():
    bewegt = _node(
        "const m = mirrorReading(startMirror('', 0, 0).mirror, 'Kannst du', 'mir bitte')\n"
        "const range = { basis: '', von: 0, bis: 0 }\n"
        "console.log(JSON.stringify(mirrorAfterFieldChange(m, range, 'Ein anderer Text')))"
    )
    assert bewegt == {
        "mirror": {
            "davor": "Ein anderer Text",
            "danach": "",
            "fest": "Kannst du",
            "unsicher": "mir bitte",
        },
        "range": {"basis": "Ein anderer Text", "von": 16, "bis": 16},
    }
    # The silent cases: nothing changes while the field holds what it held,
    # and nothing is moved when there is no mirror or range at all.
    assert _node(
        "const m = { davor: '', danach: '', fest: '', unsicher: '' }\n"
        "console.log(JSON.stringify(["
        "mirrorAfterFieldChange(m, { basis: 'gleich', von: 0, bis: 0 }, 'gleich'),"
        "mirrorAfterFieldChange(null, { basis: '', von: 0, bis: 0 }, 'neu'),"
        "mirrorAfterFieldChange(m, null, 'neu')]))"
    ) == [None, None, None]
    # Another chat whose draft is exactly as long as the one being dictated
    # into: the field's text decides, never its length alone.
    assert _node(
        "console.log(JSON.stringify(mirrorAfterFieldChange("
        "{ davor: 'Chat A', danach: '', fest: 'Kannst du', unsicher: 'mir' },"
        " { basis: 'Chat A', von: 6, bis: 6 }, 'Chat B')))"
    ) == {
        "mirror": {"davor": "Chat B", "danach": "", "fest": "Kannst du", "unsicher": "mir"},
        "range": {"basis": "Chat B", "von": 6, "bis": 6},
    }


def test_the_field_grows_with_the_mirror_and_stops_at_two_fifths_of_the_window():
    def size(field: int, window: int, mirror: int | None = None) -> dict:
        teil = "" if mirror is None else f", mirrorHeight: {mirror}"
        return _node(
            f"console.log(JSON.stringify(fieldSize({{ fieldHeight: {field}{teil},"
            f" windowHeight: {window} }})))"
        )

    # The taller of the two wins: the mirror can be longer than the field's
    # own text.
    assert size(120, 800, 300) == {"height": "300px", "overflowY": "hidden"}
    # Past 40 percent of the window it scrolls instead of growing on, and
    # right at the line it still does not.
    assert size(100, 800, 900) == {"height": "320px", "overflowY": "auto"}
    assert size(320, 800) == {"height": "320px", "overflowY": "hidden"}
    # Silence probe, the other way round: with no mirror the field's own text
    # is the only measure.
    assert size(200, 800) == {"height": "200px", "overflowY": "hidden"}
    # And the limit is the window's own, not a number that happens to fit one
    # window size: a taller window carries a taller field.
    assert size(900, 1000) == {"height": "400px", "overflowY": "auto"}
    # A mirror that is still being laid out answers with no height at all —
    # that must measure as nothing, not swallow the field's own text.
    assert _node(
        "console.log(JSON.stringify(fieldSize({ fieldHeight: 200, mirrorHeight: undefined,"
        " windowHeight: 800 })))"
    ) == {"height": "200px", "overflowY": "hidden"}


def test_the_field_does_not_shrink_below_the_height_it_had_in_this_dictation():
    """A reading that needs three lines, the next one two: the field stays at
    three. The grey end changes its length with every pass, and a field that
    follows it down makes the history above it jump."""

    def size(field: int, window: int, mirror: int, floor: int | None = None) -> dict:
        boden = "" if floor is None else f", floorHeight: {floor}"
        return _node(
            f"console.log(JSON.stringify(fieldSize({{ fieldHeight: {field},"
            f" mirrorHeight: {mirror}, windowHeight: {window}{boden} }})))"
        )

    three_lines, two_lines = 84, 56
    first = size(28, 800, three_lines)
    assert first == {"height": "84px", "overflowY": "hidden"}
    # The next reading is shorter; the floor is what the field had.
    assert size(28, 800, two_lines, floor=84) == {"height": "84px", "overflowY": "hidden"}
    # A longer one still grows it.
    assert size(28, 800, 120, floor=84) == {"height": "120px", "overflowY": "hidden"}
    # The cap of two fifths of the window wins over the floor: a smaller
    # window takes the field with it.
    assert size(28, 200, two_lines, floor=300) == {"height": "80px", "overflowY": "auto"}
    assert size(28, 800, 900, floor=84) == {"height": "320px", "overflowY": "auto"}


def test_without_a_floor_the_field_measures_as_it_always_did():
    """Silence: no mirror, no floor — the field shrinks when text is deleted,
    exactly as before; a floor of nothing changes nothing."""
    for floor in ("", ", floorHeight: 0", ", floorHeight: undefined"):
        assert _node(
            "console.log(JSON.stringify(fieldSize({ fieldHeight: 56, mirrorHeight: 0,"
            f" windowHeight: 800{floor} }})))"
        ) == {"height": "56px", "overflowY": "hidden"}


def test_the_bar_hands_the_floor_only_while_a_mirror_stands():
    """The wiring: the height of this dictation is carried while the mirror
    stands and is forgotten with it, so the field measures itself on its own
    text again once the words are in."""
    bar = (
        Path(__file__).resolve().parent.parent / "frontend/src/teile/Eingabeleiste.svelte"
    ).read_text(encoding="utf-8")
    assert "floorHeight: spiegel ? diktatHoehe : 0," in bar
    assert "diktatHoehe = spiegel ? parseInt(groesse.height, 10) : 0" in bar


def test_a_missing_mirror_and_read_back_positions_are_taken_as_they_come():
    """The field's own state is `null` whenever nobody dictates, and the two
    positions of a spot can come back as text. Both count as they are: the
    draft must never show the word "null", and the words must not fall to the
    end of the field over the spelling of a position."""
    assert _node("console.log(JSON.stringify(mirrorParts(null)))") == {
        "davor": "",
        "fest": "",
        "unsicher": "",
        "danach": "",
    }
    assert _node("console.log(JSON.stringify(placeWords('Hallo Welt', null)))") == {
        "text": "Hallo Welt",
        "caret": 10,
    }
    assert _node(
        "console.log(JSON.stringify(placeWords('Hallo Welt',"
        " { range: { basis: 'Hallo Welt', von: '6', bis: '10' }, spoken: 'Erde' })))"
    ) == {"text": "Hallo Erde", "caret": 10}


FRONTEND = Path(__file__).resolve().parent.parent / "frontend/src"


def test_escape_throws_away_a_transcription_that_never_answers():
    """A source guard, the frontend has no runner: the dictation's pass after
    the stop carries an abort signal, and Escape aborts it. Without both, a
    speech service that never answers leaves the mirror over a locked field
    until a reload."""
    api = (FRONTEND / "lib/api.js").read_text(encoding="utf-8")
    call = api[api.index("spracheTranskribieren: (") :]
    call = call[: call.index("}),") + 3]
    assert "signal" in call.split("=>", 1)[0] and "signal," in call, call

    bar = (FRONTEND / "teile/Eingabeleiste.svelte").read_text(encoding="utf-8")
    fetch = bar[bar.index("async function diktatHolen(") :]
    fetch = fetch[: fetch.index("\n  }\n")]
    assert "api.spracheTranskribieren(blob, { signal: controller.signal })" in fetch
    assert "if (fehler?.name === 'AbortError') return" in fetch
    assert "export function transcribing()" in bar
    assert "export function cancelTranscription()" in bar
    assert "transcriptionAbort?.abort()" in bar

    app = (FRONTEND / "App.svelte").read_text(encoding="utf-8")
    escape = app[app.index("ereignis.key === 'Escape'") :]
    escape = escape[: escape.index("else if (laufVon(zustand.aktiverChat) || anspruchWarten.has(")]
    assert "else if (eingabe?.transcribing?.()) eingabe.cancelTranscription()" in escape
