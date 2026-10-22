"""The agents dot on the rail, executed rather than read.

One run, two displays. The reports list draws a run that handed its work on
to a continuation quietly — grey, not red — because the work is still
going (``weitergereicht``, frontend/src/teile/ModulAgenten.svelte, since
e959e99). The dot on the rail said the opposite about the very same run:
``unterbrochen`` was worth a red dot whatever its reason, and red there
means "the newest ended job failed, and nobody has looked".

So the two now tell the same two kinds apart by the same field:

* handed on (``kontext_voll``, ``anbieter_ausfall``, anything but a service
  restart) — not an ending at all here. It does not decide the dot, the way
  the failure counter and CRONJOB_AUSGAENGE already skip it.
* cut short by a service restart (``dienst_neustart``) — a real ending with
  nothing behind it, and still red.

The rule is not asserted by searching the file for a substring: the module
is compiled with Svelte's own compiler and run in node against real job
rows, the way tests/test_warteschlange.py runs the queue and
tests/test_chatringe.py runs ``ringfarbe.js``. Only the state container the
module imports is stubbed — the decision itself is the shipped one, and
``weitergereicht`` is the shipped one too: it lives in
frontend/src/lib/laufstand.js, the file both displays of a run import, and
is loaded from there rather than replaced by anything.

This file measures what the DOT does with that distinction.
tests/test_laufstand.py measures that the list has not grown a second
reading of it.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import textwrap
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest

# Borrowed rather than copied: running the reports list is what that file
# already does, on the block lifted out of the component itself.
from tests.test_anzeigefunde import _zeilen as report_rows

WURZEL = Path(__file__).resolve().parent.parent
FRONTEND = WURZEL / "frontend"
MODUL = FRONTEND / "src" / "lib" / "agentenampel.svelte.js"
LAUFSTAND = FRONTEND / "src" / "lib" / "laufstand.js"
REPORTS_PANEL = FRONTEND / "src" / "teile" / "ModulAgenten.svelte"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not (FRONTEND / "node_modules").is_dir(),
    reason="no Node or no frontend dependencies on this machine",
)

# One millisecond apart is enough for "newer": the dot compares parsed
# timestamps, and a test that leaned on whole seconds would be slow for no
# reason. The oldest sits before every `gesehen` any test sets.
FRUEH = "2026-09-01T10:00:00+00:00"
MITTE = "2026-09-01T11:00:00+00:00"
SPAET = "2026-09-01T12:00:00+00:00"


@contextmanager
def _pruefordner():
    """A folder of this run's own for the three files the driver needs.

    Under ``frontend/node_modules`` for two reasons at once. Node resolves
    ``svelte/compiler`` and the ``svelte/internal/client`` the compiled
    module pulls in by walking UP from the importing file, so the driver has
    to sit inside frontend; and node_modules is ignored, so a run killed
    between writing and cleaning up cannot leave anything in the working
    tree.

    The name is this call's own. All three files used to be fixed names in
    ``frontend/`` — two test runs at once, which is the everyday case here,
    wrote over each other's, and an abort left three stray .mjs files in the
    repository that no ignore rule catches.
    """
    ordner = FRONTEND / "node_modules" / f".pruefstand-agentenampel-{uuid4().hex}"
    ordner.mkdir(parents=True)
    try:
        yield ordner
    finally:
        shutil.rmtree(ordner, ignore_errors=True)


def _lauf(
    jobs: list[dict], *, gesehen: str | None = None, gelesen: list[str] | None = None,
    ausdruck: str = "a.punktfarbe()",
) -> str:
    """Compile the dot module, hand it `jobs` as the job list, and return
    the colour it decides on.

    `gesehen` is the floor the rail keeps in memory ("everything that ended
    before this was over before anybody could look"); left out, it is set
    far enough back that every row in `jobs` counts as news. `gelesen` is
    the ids of the runs somebody has opened since. `ausdruck` is what is
    asked of the module once that state stands."""
    with _pruefordner() as ordner:
        treiber = ordner / "pruefung.mjs"
        gebaut = ordner / "gebaut.mjs"
        stumpf = ordner / "zustand.mjs"
        stumpf.write_text(
            # Both of them: the module reads the job list and, when a run is
            # marked read, closes the notice standing for it.
            "export const zustand = { auftraege: [] }\n"
            "export const geschlossen = []\n"
            "export function meldungenZuAuftragSchliessen(id) { geschlossen.push(id) }\n",
            encoding="utf-8",
        )
        treiber.write_text(
            textwrap.dedent(
                """
                import { compileModule } from 'svelte/compiler'
                import { readFileSync, writeFileSync } from 'fs'
                const quelle = readFileSync(%r, 'utf-8')
                const gebaut = compileModule(quelle, {
                  filename: 'agentenampel.svelte.js', generate: 'client',
                })
                // Only the state container is swapped for a stub — the
                // module reads `zustand.auftraege` and nothing else from
                // it, and the real one drags the whole interface in behind
                // it. The shared rule is NOT stubbed: it is the thing under
                // test, and it is pointed at where it really lives, because
                // the built file sits somewhere else than the source does.
                // An import wants a URL, not a path: a Windows path is read
                // as a protocol ('c:') and refused.
                writeFileSync(%r, gebaut.js.code
                  .replace('./zustand.svelte.js', './zustand.mjs')
                  .replace('./laufstand.js', %r))
                const a = await import('./gebaut.mjs')
                const { zustand } = await import('./zustand.mjs')
                zustand.auftraege = %s
                a.agentenampel.seit = %s
                a.agentenampel.gesehene = %s
                const { geschlossen } = await import('./zustand.mjs')
                console.log('---BERICHT---' + JSON.stringify(%s))
                """
            )
            % (
                str(MODUL),
                str(gebaut),
                LAUFSTAND.as_uri(),
                json.dumps(jobs),
                "Date.parse(%s)" % json.dumps(gesehen) if gesehen else "0",
                json.dumps(gelesen or []),
                ausdruck,
            ),
            encoding="utf-8",
        )
        ergebnis = subprocess.run(
            ["node", treiber.name],
            cwd=ordner,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
        )
    assert ergebnis.returncode == 0, (ergebnis.stdout + ergebnis.stderr)[-2000:]
    marke = "---BERICHT---"
    assert marke in ergebnis.stdout, ergebnis.stdout[-2000:]
    return json.loads(ergebnis.stdout.split(marke, 1)[1].strip())


_NAECHSTE = iter(f"job-{n}" for n in range(1, 999))


def _job(zustand, grund=None, wann=SPAET, kennung=None, *, result="Report", schedule=None):
    """One job row. It carries a report unless a test takes it away: whether
    a run has one decides whether the reports list has a row for it, and a
    run without a row colours nothing. So every test about something else
    gets a run that can be opened, and the tests about exactly that say
    ``result=None`` out loud."""
    return {
        "id": kennung or next(_NAECHSTE),
        "state": zustand,
        "end_reason": grund,
        "updated_at": wann,
        "result": result,
        "cronjob_id": schedule,
    }


# --- The one run the two displays disagreed about ---------------------------


def test_ein_weitergereichter_lauf_faerbt_den_punkt_nicht_rot():
    """The whole point. A context overflow or a lost provider that wrote a
    continuation ends 'unterbrochen' with its own reason, and the reports
    list draws it quietly. The dot painted it red — the same run, two
    answers, one glance apart."""
    assert _lauf([_job("unterbrochen", "kontext_voll")]) == "still"
    assert _lauf([_job("unterbrochen", "anbieter_ausfall")]) == "still"


def test_ein_vom_neustart_abgeschnittener_lauf_bleibt_rot():
    """The other writer of 'unterbrochen', and the one this must not touch:
    nothing was handed anywhere, the run was simply cut off, and there is
    something to go and look at."""
    assert _lauf([_job("unterbrochen", "dienst_neustart")]) == "rot"


def test_ohne_grund_gilt_genau_die_regel_der_liste():
    """The boundary, written down so nobody tightens it here alone. The rule
    is "anything but a service restart", so a row with no reason at all
    counts as handed on — and the reports list answers exactly the same,
    because it is the same rule.

    Nothing writes such a row: 'unterbrochen' has two writers, one setting
    'kontext_voll' or 'anbieter_ausfall' and one setting 'dienst_neustart'.
    Guarding the impossible case here and not there would be two rules for
    one thing, which is how the two displays came apart in the first
    place."""
    assert _lauf([_job("unterbrochen", None)]) == "still"


def test_die_uebrigen_ausgaenge_sagen_was_sie_immer_sagten():
    """Nothing else moved: a report is green, a failure and an abort that
    left a report are red, and a state that is not an ending colours
    nothing."""
    assert _lauf([_job("fertig")]) == "gruen"
    assert _lauf([_job("gescheitert", "kontext_voll")]) == "rot"
    assert _lauf([_job("abgebrochen", "benutzer_abbruch")]) == "rot"


def test_laufend_und_wartend_schlagen_jedes_ende():
    """The order of precedence is the feature, and it is untouched."""
    assert _lauf([_job("laeuft"), _job("gescheitert", "fehler: x")]) == "blau"
    assert _lauf([_job("wartet"), _job("gescheitert", "fehler: x")]) == "gelb"


# --- Skipped, not merely recoloured ----------------------------------------


def test_ein_weitergereichtes_glied_verdeckt_keinen_aelteren_fehlschlag():
    """Why the handed-on run is skipped instead of being painted 'still': it
    is not an ending, so it must not be "the newest ended one" either. A
    failure nobody has looked at stays on the dot while a chain carries the
    other job on beside it."""
    farbe = _lauf(
        [
            _job("unterbrochen", "anbieter_ausfall", SPAET),
            _job("gescheitert", "fehler: Kabelbrand", MITTE),
        ]
    )
    assert farbe == "rot"


def test_ein_weitergereichtes_glied_verdeckt_auch_keinen_fertigen_bericht():
    """The same the other way round — a finished report waiting to be read
    does not vanish because a chain link handed its work on afterwards."""
    farbe = _lauf(
        [
            _job("unterbrochen", "kontext_voll", SPAET),
            _job("fertig", None, MITTE),
        ]
    )
    assert farbe == "gruen"


def test_eine_kette_aus_lauter_gliedern_laesst_den_punkt_in_ruhe():
    """A dead provider restarts one job again and again. Every link is a
    handed-on run, and none of them is news — the rail stays quiet until
    something really ends."""
    kette = [
        _job("unterbrochen", "anbieter_ausfall", zeit)
        for zeit in (SPAET, MITTE, FRUEH)
    ]
    assert _lauf(kette) == "still"


def test_das_ende_der_kette_meldet_sich_wieder():
    """And when the chain finally gives up — the restart ceiling, a handoff
    that came back empty — that run is 'gescheitert' and the dot says so."""
    farbe = _lauf(
        [
            _job("gescheitert", "anbieter_ausfall", SPAET),
            _job("unterbrochen", "anbieter_ausfall", MITTE),
            _job("unterbrochen", "anbieter_ausfall", FRUEH),
        ]
    )
    assert farbe == "rot"


# --- The watermark still counts --------------------------------------------


def test_was_vor_dem_hinsehen_endete_ist_keine_neuigkeit():
    """The floor is untouched by any of this: an ending older than the mark
    is not news, handed on or not."""
    assert _lauf([_job("gescheitert", "fehler: x", FRUEH)], gesehen=MITTE) == "still"
    assert _lauf([_job("gescheitert", "fehler: x", SPAET)], gesehen=MITTE) == "rot"


def test_ein_neustart_bleibt_rot_neben_einem_weitergereichten_glied():
    """Both kinds of 'unterbrochen' in one list, which is the everyday case
    after a restart caught a chain mid-flight: the cut-off run is still the
    one that decides."""
    farbe = _lauf(
        [
            _job("unterbrochen", "kontext_voll", SPAET),
            _job("unterbrochen", "dienst_neustart", MITTE),
        ]
    )
    assert farbe == "rot"


# --- Read is asked per run, not per window ---------------------------------


def test_ein_gelesener_bericht_nimmt_dem_punkt_seine_farbe():
    assert _lauf([_job("fertig", kennung="a")]) == "gruen"
    assert _lauf([_job("fertig", kennung="a")], gelesen=["a"]) == "still"


def test_ein_gelesener_bericht_verdeckt_keinen_ungelesenen():
    """The reason this is not a watermark anymore. Reading the newest report
    used to clear every older one with it; now the older failure nobody has
    opened keeps the dot."""
    farbe = _lauf(
        [
            _job("fertig", None, SPAET, kennung="neu"),
            _job("gescheitert", "fehler: Kabelbrand", MITTE, kennung="alt"),
        ],
        gelesen=["neu"],
    )
    assert farbe == "rot"


def test_drei_enden_und_eines_gelesen_lassen_die_anderen_stehen():
    """Three runs end, one is opened: the dot still has something to say."""
    jobs = [
        _job("fertig", None, SPAET, kennung="a"),
        _job("fertig", None, MITTE, kennung="b"),
        _job("fertig", None, FRUEH, kennung="c"),
    ]
    assert _lauf(jobs, gelesen=["a"]) == "gruen"
    assert _lauf(jobs, gelesen=["a", "b"]) == "gruen"
    assert _lauf(jobs, gelesen=["a", "b", "c"]) == "still"


# --- The dot follows the reports list ---------------------------------------
#
# The dot loses a colour in one way only: the run is opened, and a run is
# opened from its row in the reports list. So a run the list has no row for
# must not colour the dot — it would hold that colour until the page is
# loaded again. The list is run as it stands (tests/test_anzeigefunde.py
# lifts its block out of the component), the dot is run as it stands, and
# both are asked about the same rows.


def test_a_run_stopped_by_hand_colours_nothing_and_has_no_row():
    """The one run the two displays disagreed about this time: a run stopped
    under the running ones ends 'abgebrochen' with no report. The dot went
    red for it, and the list offered nothing to open."""
    stopped = _job("abgebrochen", "benutzer_abbruch", result=None)

    assert _lauf([stopped]) == "still"
    assert report_rows([stopped]) == []


def test_a_finished_run_with_nothing_to_say_colours_nothing_either():
    """The same gap in green: nothing was written, so there is no row, and a
    green dot would have nothing behind it to read."""
    silent = _job("fertig", "fertig", result=None)

    assert _lauf([silent]) == "still"
    assert report_rows([silent]) == []


def test_a_run_stopped_by_hand_hides_no_older_report():
    """Skipped, not painted 'still': the stop a minute ago is not "the
    newest ended one", so the report nobody has opened keeps the dot — and
    keeps it green, which is what tells the three possible answers apart."""
    farbe = _lauf(
        [
            _job("abgebrochen", "benutzer_abbruch", SPAET, result=None),
            _job("fertig", "fertig", MITTE),
        ]
    )
    assert farbe == "gruen"


def test_a_failure_stays_red_until_it_is_opened():
    """Silence probe. A failure needs no report to have a row — the reason
    is its news — so it is red, listed, and quiet once somebody opened it."""
    failed = _job("gescheitert", "zeitgrenze", kennung="failed", result=None)

    assert report_rows([failed]) == ["failed"]
    assert _lauf([failed]) == "rot"
    assert _lauf([failed], gelesen=["failed"]) == "still"


def test_a_run_cut_off_by_a_restart_stays_red_until_it_is_opened():
    """Silence probe. The sweep at service start writes no result either."""
    cut_off = _job("unterbrochen", "dienst_neustart", kennung="cut", result=None)

    assert report_rows([cut_off]) == ["cut"]
    assert _lauf([cut_off]) == "rot"
    assert _lauf([cut_off], gelesen=["cut"]) == "still"


def test_a_stopped_run_of_a_schedule_stays_in_list_and_dot():
    """Silence probe. The same state as the run stopped by hand above, and
    the one thing telling them apart is the schedule behind it: its row is
    the only place that run can still be seen."""
    stopped = _job(
        "abgebrochen", "benutzer_abbruch", kennung="planned", result=None, schedule="plan-1"
    )

    assert report_rows([stopped]) == ["planned"]
    assert _lauf([stopped]) == "rot"
    assert _lauf([stopped], gelesen=["planned"]) == "still"


def test_a_finished_run_with_a_report_stays_green():
    """Silence probe."""
    done = _job("fertig", "fertig", kennung="done")

    assert report_rows([done]) == ["done"]
    assert _lauf([done]) == "gruen"


ENDINGS = [
    (state, reason, result, schedule)
    for state, reason in (
        ("fertig", "fertig"),
        ("gescheitert", "zeitgrenze"),
        ("abgebrochen", "benutzer_abbruch"),
        ("unterbrochen", "dienst_neustart"),
        ("unterbrochen", "kontext_voll"),
    )
    for result in (None, "Report")
    for schedule in (None, "plan-1")
]


@pytest.mark.parametrize("state,reason,result,schedule", ENDINGS)
def test_no_run_without_a_row_colours_the_dot(state, reason, result, schedule):
    """The rule itself, over every ending a run can have, with and without a
    report, with and without a schedule: whatever the list leaves out, the
    dot leaves alone. Before the two read one function, the run stopped by
    hand and the finished run with nothing to say broke this.

    And the other way round, so no row here passes by saying nothing: a run
    with a row colours the dot — except the one that handed its work on,
    which the list keeps as the last link of its chain and the dot skips on
    purpose (tests/test_laufstand.py)."""
    row = _job(state, reason, result=result, schedule=schedule)
    handed_on = state == "unterbrochen" and reason != "dienst_neustart"

    listed = bool(report_rows([row]))
    coloured = _lauf([row]) != "still"

    assert coloured == (listed and not handed_on)


def test_dot_and_list_take_the_rule_from_one_function():
    """The claim that has to be read rather than run: there is one copy.

    The list imports ``worthReading`` from the dot's module and calls it;
    the dot calls it too; and the block that builds the list names no ending
    of its own any more. A second copy in the component would keep every
    test above green on the day the two start to differ — each side would
    be measured against itself."""
    dot = MODUL.read_text(encoding="utf-8")
    panel = REPORTS_PANEL.read_text(encoding="utf-8")

    assert dot.count("function worthReading(") == 1
    # The dot and the mark in a row ask one predicate, and that predicate
    # asks `worthReading`.
    assert dot.count("function countsForDot(") == 1
    predicate = dot.split("function countsForDot(job) {", 1)[1].split("\n}", 1)[0]
    assert "worthReading(job)" in predicate
    assert "if (!countsForDot(job)) continue" in dot.split("export function punktfarbe() {", 1)[1]
    assert "return countsForDot(job) &&" in dot.split("export function isRedRun(job) {", 1)[1]

    assert "function worthReading(" not in panel
    # Whatever else the panel takes from that module, this name is in it.
    assert re.search(
        r"import \{[^}]*\bworthReading\b[^}]*\} from '\.\./lib/agentenampel\.svelte\.js'", panel
    )
    start = panel.index("  const berichte = $derived.by(() => {")
    block = panel[start : panel.index("\n  })", start)]
    assert "worthReading(auftrag)" in block
    for own_reading in ("auftrag.result", "'gescheitert'", "'abgebrochen'", "cronjob_id"):
        assert own_reading not in block, f"the list decides {own_reading} for itself again"


# --- The row that carries the red bar of an unseen failure ------------------


def _red_rows(jobs: list[dict], gelesen: list[str] | None = None) -> list[bool]:
    """Which rows of the reports list carry the red bar: `isRedRun` of
    each run, in order."""
    return _lauf(jobs, gelesen=gelesen, ausdruck="zustand.auftraege.map((j) => a.isRedRun(j))")


def test_every_unseen_failed_row_carries_the_red_bar():
    jobs = [_job("gescheitert", "fehler: x", kennung="a"), _job("gescheitert", "fehler: y", kennung="b")]
    assert _red_rows(jobs) == [True, True]


def test_a_seen_run_loses_its_dot_the_other_keeps_it_and_the_sign_stays_red():
    """The schweigeprobe of the order: two failed runs, one of them looked
    at — by opening its report or by the cross of its notice, which is the
    same call — and the sign stays red because of the other, whose row
    still carries the dot."""
    jobs = [_job("gescheitert", "fehler: x", kennung="a"), _job("gescheitert", "fehler: y", kennung="b")]
    assert _red_rows(jobs, gelesen=["a"]) == [False, True]
    assert _lauf(jobs, gelesen=["a"]) == "rot"
    assert _red_rows(jobs, gelesen=["a", "b"]) == [False, False]
    assert _lauf(jobs, gelesen=["a", "b"]) == "still"


def test_a_single_run_has_a_row_dot_exactly_when_the_sign_is_red():
    """With one run the row and the sign agree: the dot is red exactly when
    that run is an unseen failure the list can show."""
    faelle = [
        [_job("gescheitert", "fehler: x", kennung="a")],
        [_job("fertig", kennung="a")],
        [_job("unterbrochen", "kontext_voll", kennung="a")],
        [_job("unterbrochen", "dienst_neustart", kennung="a")],
        [_job("abgebrochen", "benutzer_abbruch", kennung="a", result=None)],
        [_job("abgebrochen", "benutzer_abbruch", kennung="a", result=None, schedule="c1")],
    ]
    for jobs in faelle:
        assert any(_red_rows(jobs)) == (_lauf(jobs) == "rot"), jobs


def test_every_unseen_failure_keeps_its_dot_whatever_the_sign_shows():
    """The rows mark each unseen failure; the sign shows the newest unseen
    run, or yellow or blue while something runs or waits. So an older failure
    keeps its dot beside a newer success — the dot is cleared by looking at
    that run, not by something else happening."""
    aelter_fehler_neuer_erfolg = [
        _job("fertig", None, SPAET, kennung="neu"),
        _job("gescheitert", "fehler: x", MITTE, kennung="alt"),
    ]
    assert _lauf(aelter_fehler_neuer_erfolg) == "gruen"
    assert _red_rows(aelter_fehler_neuer_erfolg) == [False, True]
    mit_laufendem = [_job("laeuft", None, kennung="l"), _job("gescheitert", "fehler: x", kennung="f")]
    assert _lauf(mit_laufendem) == "blau"
    assert _red_rows(mit_laufendem) == [False, True]


def test_what_ended_before_the_start_carries_no_dot():
    assert _lauf(
        [_job("gescheitert", "fehler: x", FRUEH, kennung="a")],
        gesehen=MITTE,
        ausdruck="zustand.auftraege.map((j) => a.isRedRun(j))",
    ) == [False]


def test_the_cross_of_a_notice_marks_a_run_as_opening_its_report_does():
    """`markSeenIfOver` marks the run and closes the notices standing for
    it, the way opening its report does; the cross of a notice goes through
    it."""
    ergebnis = _lauf(
        [_job("gescheitert", "fehler: x", kennung="a")],
        ausdruck="(a.markSeenIfOver('a'), { rot: a.isRedRun(zustand.auftraege[0]), zu: geschlossen })",
    )
    assert ergebnis == {"rot": False, "zu": ["a"]}


def test_the_cross_of_a_notice_about_a_run_still_going_marks_nothing():
    """A run standing on a question is not over: closing its notice must not
    hide the failure it may still end in."""
    jobs = [_job("wartet", None, kennung="a")]
    ergebnis = _lauf(jobs, ausdruck="(a.markSeenIfOver('a'), { gesehen: a.agentenampel.gesehene.length, zu: geschlossen })")
    assert ergebnis == {"gesehen": 0, "zu": []}
    # Later it fails, and the dot still turns red.
    spaeter = [_job("gescheitert", "fehler: x", kennung="a")]
    assert _lauf(spaeter) == "rot"


def test_the_cross_of_a_notice_about_an_unknown_run_marks_nothing():
    ergebnis = _lauf([], ausdruck="(a.markSeenIfOver('gone'), a.agentenampel.gesehene.length)")
    assert ergebnis == 0


def test_the_cross_and_the_row_are_wired():
    meldungen = (FRONTEND / "src" / "teile" / "Meldungen.svelte").read_text(encoding="utf-8")
    assert "markSeenIfOver(meldung.auftragId)" in meldungen
    assert "onclick={() => closeByHand(meldung)}" in meldungen
    agenten = REPORTS_PANEL.read_text(encoding="utf-8")
    assert "{@const unseen = isRedRun(auftrag)}" in agenten
    assert "{#if unseen}" in agenten and 'class="unseen-bar"' in agenten
