"""Where the speed in the window comes from — and where it does not.

Three sources, and one of them is not a source at all. A server that counts
tokens and times them is the truth; our own division of its numbers is the
same truth rounded twice; counted CHUNKS are neither, because a chunk is not
a token and with speculative decoding one carries several.

Measured on an mlx server with MTP: two
answers stored 8.06 and 8.05 tok/s out of 156 and 169 chunks, while the same
answers reported 1310 and 1376 `completion_tokens` and 64.42 / 63.99 tok/s of
their own — a factor of eight. Measured against a 35B model on
llama.cpp (b819): 50 tokens, 1144.515 ms and
`predicted_per_second: 42.81289454485088` in one and the same `timings` block.
"""

from __future__ import annotations

from app.providers.openai_kompatibel import tempo_ermitteln

# The chunk count and the seconds of the answer from the measurement above.
MTP_HAEPPCHEN = 156
MTP_DAUER = 19.3
MTP_TOKENS = 1310
# What the same answer's own numbers said.
MTP_TEMPO = 64.42


def test_haeppchen_werden_nicht_als_tempo_ausgegeben():
    """The measured bug: thinking behind a silent server drops the token
    tier, and the chunk tier below it reported chunks per second as if they
    were tokens per second — 8.06 where the answer itself said 64.42.

    The count and the span still go out: they are true whatever a chunk
    holds, and the window shows the duration from them.
    """
    werte = tempo_ermitteln(
        zeitmessung={},
        nutzung={"completion_tokens": MTP_TOKENS},
        haeppchen=MTP_HAEPPCHEN,
        dauer=MTP_DAUER + 5.0,
        erstes_token_nach=5.0,
        denken_gesehen=True,
    )

    assert werte["tempo_quelle"] == "geschaetzt"
    assert werte["erzeugte_tokens"] == MTP_HAEPPCHEN
    assert werte["erzeugungs_sekunden"] == MTP_DAUER
    # 156 / 19.3 = 8.08 — the number this test exists to keep out.
    assert werte["tokens_pro_sekunde"] is None


def test_eine_vom_server_genannte_zahl_wird_genommen():
    """A server that states its own speed and sends no pair to divide: the
    stated number is the reading, and it is a SERVER reading — it was counted
    and timed where it happened."""
    werte = tempo_ermitteln(
        zeitmessung={},
        nutzung={"generation_tokens_per_second": MTP_TEMPO},
        haeppchen=MTP_HAEPPCHEN,
        dauer=MTP_DAUER + 5.0,
        erstes_token_nach=5.0,
        denken_gesehen=True,
    )

    assert werte["tokens_pro_sekunde"] == MTP_TEMPO
    assert werte["tempo_quelle"] == "server"
    # And the count beside it is CHUNKS, whatever the reading is called: the
    # name travels with the number, the summable pair travels with the tier
    # that counted. Measured with the two mixed up: two such rounds merged
    # to 8.42 tok/s, the eightfold error above rebuilt.
    assert werte["erzeugte_tokens"] == MTP_HAEPPCHEN
    assert werte["tempo_tokens"] is None
    assert werte["tempo_sekunden"] is None


def test_die_genannte_zahl_schlaegt_die_eigene_division():
    """Measured against a 35B model on llama.cpp: dividing the server's own pair gives
    43.69, the server reports 42.81 for the same answer and writes that into
    its journal. The window has to be able to say what the log says."""
    werte = tempo_ermitteln(
        zeitmessung={
            "predicted_n": 50,
            "predicted_ms": 1144.515,
            "predicted_per_second": 42.81289454485088,
        },
        nutzung={"completion_tokens": 50},
        haeppchen=40,
        dauer=1.2,
        erstes_token_nach=0.5,
    )

    assert werte["tokens_pro_sekunde"] == 42.81
    assert werte["tempo_quelle"] == "server"
    # The pair still names what was counted and how long it took.
    assert werte["erzeugte_tokens"] == 50
    assert werte["erzeugungs_sekunden"] == 1.145


def test_die_genannte_zahl_ersetzt_die_eigene_messung_nicht():
    """Same number, different stretch of time.

    Where this side has the ANSWER's own tokens against its own clock, the
    rate the server states covers the whole generation, the chain of thought
    included. Substituting the one for the other put a whole-generation
    figure under "measured over the writing of the answer" — and
    left the merge recomputing a different quantity for any answer of more
    than one round. Measured with the substitution in place: 64.42 tok/s
    labelled `gemessen` beside 1000 tokens of its own.
    """
    werte = tempo_ermitteln(
        zeitmessung={},
        nutzung={
            "completion_tokens": 1000,
            "generation_tokens_per_second": MTP_TEMPO,
        },
        haeppchen=200,
        dauer=11.0,
        erstes_token_nach=1.0,
    )

    # 1000 tokens over the ten seconds of the answer, and it says so.
    assert werte["tokens_pro_sekunde"] == 100.0
    assert werte["tempo_quelle"] == "gemessen"
    assert werte["tempo_tokens"] == 1000
    assert werte["tempo_sekunden"] == 10.0


def test_unbrauchbare_zahlen_des_servers_kosten_nur_sich_selbst():
    """The field is the server's, so it can hold anything JSON allows. A
    NaN, an infinity, a zero or a negative rate is not a speed — and must not
    take the rest of the reading with it."""
    for kaputt in (float("nan"), float("inf"), 0, -12.5, "schnell", True, None):
        werte = tempo_ermitteln(
            zeitmessung={},
            nutzung={"generation_tokens_per_second": kaputt, "completion_tokens": 100},
            haeppchen=40,
            dauer=3.0,
            erstes_token_nach=1.0,
        )
        # Falls through to the tier that really measured: 100 tokens in 2 s.
        assert werte["tokens_pro_sekunde"] == 50.0, kaputt
        assert werte["tempo_quelle"] == "gemessen", kaputt


# --- What the window shows -------------------------------------------------
#
# The frontend has no test runner, so the source text is read instead — the
# same way tests/test_verdichtung_im_chat.py does it. What is checked is the
# claim, not the spelling: that nothing is estimated, and that a reading made
# of chunks never reaches the display.

def test_ein_gleicher_uhrstand_macht_die_erzeugungszeit_nicht_zum_ganzen_lauf():
    """Measured on windows-latest: the clock there counts in steps of about
    16 ms, so a one-chunk answer stamped the same moment for its first token
    and for the end of the run. The generation time then fell back to the
    whole run — 0.7 s for an answer written in no measurable time — and the
    speed beside it read as if the thinking had been counted in again."""
    werte = tempo_ermitteln(
        zeitmessung={},
        nutzung={},
        haeppchen=1,
        dauer=0.703,
        erstes_token_nach=0.703,
        denken_gesehen=True,
    )

    assert werte["erzeugungs_sekunden"] is None


def test_die_erzeugungszeit_bleibt_der_rest_nach_dem_ersten_token():
    """The silence probe for the fix above: with a real gap between the
    first token and the end, the span is still that gap and nothing else."""
    werte = tempo_ermitteln(
        zeitmessung={},
        nutzung={},
        haeppchen=3,
        dauer=1.2,
        erstes_token_nach=0.5,
        denken_gesehen=True,
    )

    assert werte["erzeugungs_sekunden"] == 0.7


from pathlib import Path  # noqa: E402 - the guard half belongs at the bottom

APP = Path(__file__).resolve().parents[1] / "frontend" / "src" / "App.svelte"
ANSWER = Path(__file__).resolve().parents[1] / "frontend" / "src" / "teile" / "Nachricht.svelte"
# The rule the answer's foot follows, live and finished alike.
QUELLENREGEL = Path(__file__).resolve().parents[1] / "frontend" / "src" / "lib" / "tempoquelle.js"


def test_das_fenster_schaetzt_kein_tempo_mehr():
    """The browser has no tokenizer, so it no longer divides characters by a
    guessed four. Measured before the removal: live median 78
    tok/s against the server's own 63.99 for the same answer, 4.73 characters
    per token where the code assumed 4.
    """
    quelle = APP.read_text(encoding="utf-8")

    assert "ZEICHEN_JE_TOKEN" not in quelle
    # And no ticker left that would have to invent a reading between chunks.
    assert "setInterval(() => {\n      if (inhaltAngekommen)" not in quelle


def test_only_measured_readings_reach_the_answer_foot():
    """The foot under an answer shows the live reading while it runs and the
    measured figure once it is done — both only when the service MEASURED
    them (`server` or `gemessen`). A reading built from chunks would be the
    eightfold error back in the window."""
    foot = ANSWER.read_text(encoding="utf-8")
    app = APP.read_text(encoding="utf-8")

    # A running answer reads the live reading and nothing else; the row's
    # own `stats` are the finished answer's.
    assert "      ? nachricht.liveSpeed?.wert\n        ? nachricht.liveSpeed" in foot
    assert "tempoGemessen(speedReading.quelle)" in foot
    # The live reading is the server's own, straight from the stream.
    assert "platzhalter.liveSpeed = {" in app
    assert "wert: ereignis.tokens_pro_sekunde" in app


def test_the_answer_foot_says_where_the_figure_comes_from():
    """The `server` tier measures the whole generation, the rest measures
    the writing of the answer. The foot says which, instead of letting one
    number stand for two different things."""
    foot = ANSWER.read_text(encoding="utf-8")
    regel = QUELLENREGEL.read_text(encoding="utf-8")

    assert "tempoTitelSchluessel(speedReading.quelle)" in foot
    assert "'eingabe.tps_titel_server'" in regel
    assert "'eingabe.tps_titel_antwort'" in regel


# --- Across the rounds of one answer ---------------------------------------


def test_zwei_haeppchen_runden_ergeben_kein_tempo():
    """The same rule one layer up: the merge of an answer's rounds must not
    put chunks into a numerator either. Measured before the fix: two rounds
    that each reported no speed added up to 8.08 tok/s.
    """
    from app.api.v1.generierung import _messwerte_mergen

    runde = {
        "dauer_sekunden": 19.3,
        "haeppchen": MTP_HAEPPCHEN,
        "erzeugte_tokens": MTP_HAEPPCHEN,
        "tempo_tokens": None,
        "erzeugungs_sekunden": 19.3,
        "tokens_pro_sekunde": None,
        "tempo_quelle": "geschaetzt",
    }

    zusammen = _messwerte_mergen(dict(runde), dict(runde))

    assert zusammen["tokens_pro_sekunde"] is None
    assert zusammen["tempo_tokens"] is None


def test_eine_genannte_zahl_ohne_token_hebt_die_grenzen_nicht_auf():
    """A round whose server only STATED a rate has nothing in the sum's
    numerator, so its name must not free the sum from the floors. Measured
    before the fix: such a round beside a one-token round reported 1000
    tok/s — the very number the floors exist for.
    """
    from app.api.v1.generierung import _messwerte_mergen

    genannt = {
        "dauer_sekunden": 2.0,
        "haeppchen": 30,
        "erzeugte_tokens": 30,
        "tempo_tokens": None,
        "erzeugungs_sekunden": 2.0,
        "tokens_pro_sekunde": 70.0,
        "tempo_quelle": "server",
    }
    winzig = {
        "dauer_sekunden": 0.002,
        "haeppchen": 1,
        "erzeugte_tokens": 1,
        "tempo_tokens": 1,
        "erzeugungs_sekunden": 0.001,
        "tokens_pro_sekunde": None,
        "tempo_quelle": "gemessen",
    }

    zusammen = _messwerte_mergen(genannt, winzig)

    assert zusammen["tokens_pro_sekunde"] is None


def test_eine_genannte_zahl_ueberlebt_den_zusammenzug():
    """Nothing to sum, but the last round's server said a number: it stays.
    Dropping it lost the server's own reading on every answer that had more
    than one round."""
    from app.api.v1.generierung import _messwerte_mergen

    leer = {
        "dauer_sekunden": 1.0,
        "haeppchen": 5,
        "erzeugte_tokens": 5,
        "tempo_tokens": None,
        "erzeugungs_sekunden": 1.0,
        "tokens_pro_sekunde": None,
        "tempo_quelle": "geschaetzt",
    }
    genannt = {
        "dauer_sekunden": 2.0,
        "haeppchen": 30,
        "erzeugte_tokens": 30,
        "tempo_tokens": None,
        "erzeugungs_sekunden": 2.0,
        "tokens_pro_sekunde": MTP_TEMPO,
        "tempo_quelle": "server",
    }

    zusammen = _messwerte_mergen(leer, genannt)

    assert zusammen["tokens_pro_sekunde"] == MTP_TEMPO
    assert zusammen["tempo_quelle"] == "server"


def test_die_haeppchen_stufe_liefert_keine_zaehlbare_tokenzahl():
    """`tempo_tokens` is the field a sum may use. The chunk tier leaves it
    empty while `erzeugte_tokens` still names what it counted."""
    werte = tempo_ermitteln(
        zeitmessung={}, nutzung={}, haeppchen=40, dauer=5.0, erstes_token_nach=1.0
    )

    assert werte["erzeugte_tokens"] == 40
    assert werte["tempo_tokens"] is None


def test_die_sekunden_einer_verworfenen_runde_bleiben_draussen():
    """The pairing holds at both ends.

    A round whose chunks are dropped keeps its seconds out of the divisor
    too. Measured with them left in: a silent chunk round of 19.3 s beside a
    server round of 51 tokens in 634 ms reported 2.56 tok/s for an answer
    that ran at 78.85 — the same defect as the numerator, mirrored.
    """
    from app.api.v1.generierung import _messwerte_mergen

    haeppchenrunde = {
        "dauer_sekunden": 19.3,
        "haeppchen": MTP_HAEPPCHEN,
        "erzeugte_tokens": MTP_HAEPPCHEN,
        "tempo_tokens": None,
        "tempo_sekunden": None,
        "erzeugungs_sekunden": 19.3,
        "tokens_pro_sekunde": None,
        "tempo_quelle": "geschaetzt",
    }
    serverrunde = {
        "dauer_sekunden": 1.2,
        "haeppchen": 40,
        "erzeugte_tokens": 51,
        "tempo_tokens": 51,
        "tempo_sekunden": 0.634,
        "erzeugungs_sekunden": 0.634,
        "tokens_pro_sekunde": 78.85,
        "tempo_quelle": "server",
    }

    zusammen = _messwerte_mergen(haeppchenrunde, serverrunde)

    # 51 tokens over 0.634 s, and not a second of the dropped round.
    assert zusammen["tempo_tokens"] == 51
    assert zusammen["tempo_sekunden"] == 0.634
    assert zusammen["tokens_pro_sekunde"] == 80.44
    # The name belongs to the rounds that are IN the sum. The dropped round
    # has no say in what the figure counts — and "geschaetzt" on it would
    # have the display throw the whole reading away.
    assert zusammen["tempo_quelle"] == "server"
    # The duration of the ANSWER is still both rounds together.
    assert zusammen["erzeugungs_sekunden"] == 19.934


def test_nur_gemessene_quellen_erreichen_die_anzeige():
    """The display takes `server` and `gemessen`, and checks rather than
    trusts: a name is cheaper to test than a number is to believe."""
    quelle = ANSWER.read_text(encoding="utf-8")
    regel = QUELLENREGEL.read_text(encoding="utf-8")

    assert "TEMPO_QUELLEN = ['server', 'gemessen']" in regel
    assert "TEMPO_QUELLEN.includes(quelle)" in regel
    assert "tempoGemessen(speedReading.quelle)" in quelle
