"""What a text weighs before it is sent (app/tokenmass.py).

There is no tokenizer on this side, so the estimate is the only thing four
modules have to price a request with. It used to be `characters / 4`, which
under-counted every script that is not Latin — as measured, a 600-page PDF
the estimate called 183,420 tokens was refused by the server at 308,703.

Measured against the real tokenizer of a 35B model, estimate over truth:
German prose 100 %, Python 76 %, Greek 122 %, Russian 164 %, Chinese 164 %.
The dangerous direction — an estimate BELOW the truth, which sends a request
the server then refuses — is closed for every non-Latin script measured
here. Code lands low now, more than Latin prose did before; both are stated
here, not smoothed over.
"""

from __future__ import annotations

from app.tokenmass import ZEICHEN_JE_TOKEN_ROH, tokens


def test_nichts_wiegt_nichts():
    assert tokens("") == 0
    assert tokens(None) == 0


def test_kurzes_wiegt_nie_null():
    """The ceiling: a text that exists costs at least one token, or a
    hundred short rows would price at nothing at all."""
    assert tokens("a") == 1
    assert tokens("abcd") == 1
    assert tokens("abcde") == 2


def test_ascii_geht_den_schnellen_weg():
    """Plain text is four characters to the token, as it always was — the
    common case must not get slower or different."""
    assert tokens("x" * 4_000) == 1_000
    assert tokens("x" * 733_678) == 183_420


def test_dichte_schrift_zaehlt_je_zeichen():
    """CJK, Hangul and Kana are about one token per character. Counted as
    ASCII they were priced at a quarter of the truth — the single biggest
    under-count the old proxy had."""
    for zeichen in ("中", "한", "カ", "漢"):
        assert tokens(zeichen * 100) == 100, zeichen
    # And the ranges are not guessed: the Hangul syllable block is in.
    assert tokens("가" * 50) == 50


def test_zwei_bytes_je_zeichen_kosten_das_doppelte():
    """Cyrillic, Greek and Arabic take two UTF-8 bytes per character, so
    they cost about two characters per token — the bytes are what carries
    that, and counting characters alone missed it."""
    for text in ("привет" * 100, "καλημέρα" * 100, "مرحبا" * 100):
        zeichen = len(text)
        assert tokens(text) > zeichen // ZEICHEN_JE_TOKEN_ROH, text[:8]
        assert tokens(text) <= zeichen, text[:8]


def test_gemischt_wird_stueckweise_gerechnet():
    """One text, two kinds: the dense characters count one each and the
    rest by its bytes. Neither half is allowed to set the price alone."""
    gemischt = "中文" * 50 + "x" * 400
    assert tokens(gemischt) == 100 + 100


def test_eine_einsame_ersatzstelle_bringt_nichts_zum_platzen():
    """A lone surrogate is routine in tool output and must not turn an
    estimate into a raise."""
    assert tokens("abc\ud800def") > 0


def test_die_gegenrichtung_bleibt_die_pauschale():
    """The other direction is a different question: how many CHARACTERS of
    a text still to be written fit into a token budget. There is nothing to
    measure yet, so it stays a ratio — and it stays exactly one number."""
    assert ZEICHEN_JE_TOKEN_ROH == 4
