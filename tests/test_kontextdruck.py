"""How full the context is ABOUT TO BE — the last confirmed reading plus an
estimate of what arrived since."""

from __future__ import annotations

from app import kontextdruck


def test_prozent_zaehlt_den_letzten_stand_und_das_neue():
    # 500 tokens confirmed, 500 more new — measured by the caller now, not
    # counted in characters and divided here — against a 1000-token window:
    # 1000 of 1000 is 100%.
    assert kontextdruck.prozent(500, 500, 1000) == 100.0


def test_prozent_ohne_letzten_stand_zaehlt_nur_das_neue():
    """No confirmed reading yet — a chat's very first message — counts as
    zero rather than refusing the reading."""
    assert kontextdruck.prozent(None, 1000, 1000) == 100.0


def test_prozent_ohne_fenster_ist_nichts():
    """A threshold measured against a size nobody confirmed would fold a
    conversation for no reason — the rule the rest of the context display
    follows."""
    assert kontextdruck.prozent(500, 2000, None) is None
    assert kontextdruck.prozent(500, 2000, 0) is None


def test_prozent_ohne_neues_ist_der_alte_stand():
    assert kontextdruck.prozent(250, 0, 1000) == 25.0


def test_stand_ist_dieselbe_zahl_in_der_form_der_kontextzeile():
    """The trigger's reading as a job logs it: the estimated total, the
    window, and the share rounded the way a round's measured step is."""
    stand = kontextdruck.stand(85_000, 32_502, 100_000)
    assert stand is not None
    assert stand.kontextgroesse == 100_000
    assert stand.prozent == round(kontextdruck.prozent(85_000, 32_502, 100_000), 1) == 117.5
    assert stand.tokens == 85_000 + 32_502


def test_stand_ohne_fenster_ist_nichts():
    assert kontextdruck.stand(500, 2000, None) is None
    assert kontextdruck.stand(500, 2000, 0) is None


def test_ein_bild_wiegt_die_eine_hausschaetzung():
    """One price per image, in whichever currency the caller counts in:
    tokens for everything that prices a request, characters for the two
    readers that CUT a history (the verbatim tail, the tool prune)."""
    assert kontextdruck.bild_tokens(1) == kontextdruck.BILD_TOKEN_SCHAETZUNG
    assert kontextdruck.prozent(
        0, kontextdruck.bild_tokens(1), kontextdruck.BILD_TOKEN_SCHAETZUNG
    ) == 100.0
    assert kontextdruck.bild_tokens(3) == 3 * kontextdruck.bild_tokens(1)
    assert kontextdruck.bild_tokens(0) == 0
    # The character form is the same price, at the rough ratio.
    assert kontextdruck.bild_zeichen(1) == kontextdruck.BILD_TOKEN_SCHAETZUNG * 4


# --- The threshold a fold fires at ------------------------------------------


def test_ohne_eingestellte_grenze_ist_der_vergleich_der_alte():
    """Auto: nothing is reserved here, so the threshold is the share of the
    whole window it always was."""
    fenster = 100_000
    schwelle = 80.0
    knapp_darunter = int(fenster * schwelle / 100) - 1

    assert not kontextdruck.ueber_der_schwelle(0, knapp_darunter, fenster, schwelle)
    assert kontextdruck.ueber_der_schwelle(0, knapp_darunter + 2, fenster, schwelle)


def test_eine_eingestellte_grenze_zieht_sich_vom_fenster_ab():
    """A ceiling somebody set is reserved out of the same window: the
    threshold measures against what is left, so the fold fires earlier."""
    fenster = 100_000
    grenze = 40_000
    schwelle = 80.0
    # 80 % of the usable 60,000 is 48,000 tokens; 80 % of the whole window
    # would be 80,000.
    assert kontextdruck.ueber_der_schwelle(48_000, 0, fenster, schwelle, grenze)
    assert not kontextdruck.ueber_der_schwelle(47_999, 0, fenster, schwelle, grenze)
    assert not kontextdruck.ueber_der_schwelle(48_000, 0, fenster, schwelle)


def test_eine_grenze_so_gross_wie_das_fenster_laesst_einen_token():
    """A ceiling that fills the whole window leaves the history nothing —
    and the comparison still answers instead of dividing by zero."""
    assert kontextdruck.ueber_der_schwelle(1, 0, 8_192, 80.0, 8_192) is True


def test_ohne_fenster_faellt_der_vergleich_aus():
    """A window nobody confirmed answers False, exactly as `prozent`
    answers None."""
    assert kontextdruck.ueber_der_schwelle(500, 2_000, None, 80.0) is False
    assert kontextdruck.ueber_der_schwelle(500, 2_000, 0, 80.0, 100) is False


def test_die_leiste_zeigt_dieselbe_zahl_mit_und_ohne_grenze():
    """The bar reads `prozent`, and that is the share of the WHOLE window —
    a ceiling changes when the fold fires, never what the bar shows."""
    ohne = kontextdruck.stand(50_000, 0, 100_000)
    assert ohne is not None
    assert ohne.prozent == 50.0
    assert ohne.kontextgroesse == 100_000
