"""The pause after a failed fold, and the block after two emergency folds.

Every one of these waits minutes without waiting: the module reads its clock
through one attribute, and the tests hand in their own.
"""

from __future__ import annotations

import pytest

from app import faltpause

SCHLUESSEL = "chat-1"


class _Uhr:
    def __init__(self):
        self.jetzt = 0.0

    def __call__(self) -> float:
        return self.jetzt

    def weiter(self, sekunden: float) -> None:
        self.jetzt += sekunden


@pytest.fixture(autouse=True)
def uhr(monkeypatch):
    faltpause.freigeben(SCHLUESSEL)
    gestellt = _Uhr()
    monkeypatch.setattr(faltpause, "uhr", gestellt)
    yield gestellt
    faltpause.freigeben(SCHLUESSEL)


def test_ohne_fehlschlag_ist_nichts_gebremst():
    assert faltpause.pausiert(SCHLUESSEL) is False
    assert faltpause.automatik_gesperrt(SCHLUESSEL) is False


def test_eine_leere_antwort_pausiert_kurz(uhr):
    faltpause.notfall(SCHLUESSEL, faltpause.KURZ)

    assert faltpause.pausiert(SCHLUESSEL) is True
    uhr.weiter(faltpause.PAUSE_KURZ - 1)
    assert faltpause.pausiert(SCHLUESSEL) is True
    uhr.weiter(1)
    assert faltpause.pausiert(SCHLUESSEL) is False


def test_jeder_andere_fehler_pausiert_lang(uhr):
    faltpause.notfall(SCHLUESSEL, faltpause.LANG)

    uhr.weiter(faltpause.PAUSE_KURZ)
    assert faltpause.pausiert(SCHLUESSEL) is True
    uhr.weiter(faltpause.PAUSE_LANG - faltpause.PAUSE_KURZ)
    assert faltpause.pausiert(SCHLUESSEL) is False


def test_zweimal_derselbe_fehler_ergibt_zweimal_dieselbe_pause(uhr):
    """The silence test for the ladder that is deliberately not there: a
    second failure of the same kind waits exactly as long as the first,
    never longer."""
    faltpause.notfall(SCHLUESSEL, faltpause.LANG)
    uhr.weiter(faltpause.PAUSE_LANG)
    assert faltpause.pausiert(SCHLUESSEL) is False

    faltpause.notfall(SCHLUESSEL, faltpause.LANG)
    uhr.weiter(faltpause.PAUSE_LANG - 1)
    assert faltpause.pausiert(SCHLUESSEL) is True
    uhr.weiter(1)
    assert faltpause.pausiert(SCHLUESSEL) is False


def test_ein_erfolg_hebt_die_pause_auf():
    faltpause.notfall(SCHLUESSEL, faltpause.LANG)
    faltpause.erfolg(SCHLUESSEL)

    assert faltpause.pausiert(SCHLUESSEL) is False
    assert faltpause.automatik_gesperrt(SCHLUESSEL) is False


def test_zwei_notfaelle_sperren_die_automatik(uhr):
    assert faltpause.notfall(SCHLUESSEL, faltpause.KURZ) is False
    uhr.weiter(faltpause.PAUSE_KURZ)
    assert faltpause.notfall(SCHLUESSEL, faltpause.KURZ) is True
    uhr.weiter(faltpause.PAUSE_KURZ)

    assert faltpause.automatik_gesperrt(SCHLUESSEL) is True


def test_ein_erfolg_dazwischen_setzt_die_reihe_zurueck(uhr):
    faltpause.notfall(SCHLUESSEL, faltpause.KURZ)
    faltpause.erfolg(SCHLUESSEL)
    assert faltpause.notfall(SCHLUESSEL, faltpause.KURZ) is False

    uhr.weiter(faltpause.PAUSE_KURZ)
    assert faltpause.automatik_gesperrt(SCHLUESSEL) is False


def test_nach_der_sperrzeit_geht_genau_ein_versuch_durch(uhr):
    faltpause.notfall(SCHLUESSEL, faltpause.KURZ)
    uhr.weiter(faltpause.PAUSE_KURZ)
    faltpause.notfall(SCHLUESSEL, faltpause.KURZ)
    uhr.weiter(faltpause.PAUSE_KURZ)

    # The window is armed by the first check the block itself holds up.
    assert faltpause.automatik_gesperrt(SCHLUESSEL) is True
    uhr.weiter(faltpause.WIEDERAUFNAHME_SEKUNDEN - 1)
    assert faltpause.automatik_gesperrt(SCHLUESSEL) is True
    uhr.weiter(1)
    assert faltpause.automatik_gesperrt(SCHLUESSEL) is False
    # Asking again says the same thing: the attempt is spent by a request,
    # not by the question whether one may go out.
    assert faltpause.automatik_gesperrt(SCHLUESSEL) is False

    # And the emergency that request comes back as puts the block straight
    # back.
    faltpause.versuch_verbraucht(SCHLUESSEL)
    assert faltpause.notfall(SCHLUESSEL, faltpause.KURZ) is True
    uhr.weiter(faltpause.PAUSE_KURZ)
    assert faltpause.automatik_gesperrt(SCHLUESSEL) is True


def test_der_eine_versuch_wird_erst_von_einer_anfrage_verbraucht(uhr):
    """The block lifts for one attempt, and that attempt is spent by a fold
    request that really goes to a model.

    A turn that checks and then folds nothing — no middle, or a middle too
    small to be worth replacing — never found out whether the model can
    summarize again, so the attempt has to be there still: the check
    deliberately never spends it."""
    faltpause.notfall(SCHLUESSEL, faltpause.KURZ)
    uhr.weiter(faltpause.PAUSE_KURZ)
    faltpause.notfall(SCHLUESSEL, faltpause.KURZ)
    uhr.weiter(faltpause.PAUSE_KURZ)
    assert faltpause.automatik_gesperrt(SCHLUESSEL) is True
    uhr.weiter(faltpause.WIEDERAUFNAHME_SEKUNDEN)

    # Checked three times over three turns that folded nothing: still one
    # attempt, never used up.
    for _ in range(3):
        assert faltpause.automatik_gesperrt(SCHLUESSEL) is False

    faltpause.versuch_verbraucht(SCHLUESSEL)

    # Spent — and the block holds again until the request that spent it says
    # otherwise.
    assert faltpause.automatik_gesperrt(SCHLUESSEL) is False, "the row did not come out at one"
    assert faltpause.notfall(SCHLUESSEL, faltpause.KURZ) is True
    uhr.weiter(faltpause.PAUSE_KURZ)
    assert faltpause.automatik_gesperrt(SCHLUESSEL) is True


def test_verbrauchen_ohne_offenen_versuch_aendert_nichts(uhr):
    """The forced path sends fold requests inside a running block; it never
    asked whether it may, and it must not shorten a block it was never
    subject to."""
    faltpause.notfall(SCHLUESSEL, faltpause.KURZ)
    faltpause.notfall(SCHLUESSEL, faltpause.KURZ)
    uhr.weiter(faltpause.PAUSE_KURZ)
    assert faltpause.automatik_gesperrt(SCHLUESSEL) is True

    faltpause.versuch_verbraucht(SCHLUESSEL)

    assert faltpause.automatik_gesperrt(SCHLUESSEL) is True
    uhr.weiter(faltpause.WIEDERAUFNAHME_SEKUNDEN)
    assert faltpause.automatik_gesperrt(SCHLUESSEL) is False


def test_ein_notfall_nimmt_den_offenen_versuch_mit(uhr):
    """An emergency written without a request — the forced path inside a
    block — is the fresh evidence the attempt was standing for. The block
    starts over rather than keeping an attempt that is now answered."""
    faltpause.notfall(SCHLUESSEL, faltpause.KURZ)
    uhr.weiter(faltpause.PAUSE_KURZ)
    faltpause.notfall(SCHLUESSEL, faltpause.KURZ)
    uhr.weiter(faltpause.PAUSE_KURZ)
    assert faltpause.automatik_gesperrt(SCHLUESSEL) is True
    uhr.weiter(faltpause.WIEDERAUFNAHME_SEKUNDEN)
    assert faltpause.automatik_gesperrt(SCHLUESSEL) is False

    faltpause.notfall(SCHLUESSEL, None)

    assert faltpause.automatik_gesperrt(SCHLUESSEL) is True


def test_ein_erfolg_nach_dem_versuch_raeumt_alles_ab(uhr):
    faltpause.notfall(SCHLUESSEL, faltpause.KURZ)
    uhr.weiter(faltpause.PAUSE_KURZ)
    faltpause.notfall(SCHLUESSEL, faltpause.KURZ)
    uhr.weiter(faltpause.PAUSE_KURZ)
    assert faltpause.automatik_gesperrt(SCHLUESSEL) is True
    uhr.weiter(faltpause.WIEDERAUFNAHME_SEKUNDEN)
    assert faltpause.automatik_gesperrt(SCHLUESSEL) is False

    faltpause.erfolg(SCHLUESSEL)

    assert faltpause.automatik_gesperrt(SCHLUESSEL) is False
    assert faltpause.notfall(SCHLUESSEL, faltpause.KURZ) is False


def test_freigeben_hebt_sperre_und_pause_sofort_auf(uhr):
    faltpause.notfall(SCHLUESSEL, faltpause.LANG)
    faltpause.notfall(SCHLUESSEL, faltpause.LANG)
    assert faltpause.pausiert(SCHLUESSEL) is True
    assert faltpause.automatik_gesperrt(SCHLUESSEL) is True

    faltpause.freigeben(SCHLUESSEL)

    assert faltpause.pausiert(SCHLUESSEL) is False
    assert faltpause.automatik_gesperrt(SCHLUESSEL) is False


def test_ein_notfall_ohne_anfrage_verlaengert_die_pause_nicht(uhr):
    """An emergency fold inside a running pause never asked a model, so it
    learned nothing about it — the pause keeps the length it had."""
    faltpause.notfall(SCHLUESSEL, faltpause.KURZ)
    uhr.weiter(faltpause.PAUSE_KURZ / 2)

    faltpause.notfall(SCHLUESSEL, None)

    uhr.weiter(faltpause.PAUSE_KURZ / 2)
    assert faltpause.pausiert(SCHLUESSEL) is False


def test_der_hinweis_kommt_je_sperre_genau_einmal(uhr):
    faltpause.notfall(SCHLUESSEL, faltpause.KURZ)
    assert faltpause.hinweis_faellig(SCHLUESSEL) is False

    faltpause.notfall(SCHLUESSEL, faltpause.KURZ)
    assert faltpause.hinweis_faellig(SCHLUESSEL) is True
    assert faltpause.hinweis_faellig(SCHLUESSEL) is False

    # The block engages again after its one attempt: the notice stands again.
    # The attempt is the request that goes out after the check, so that is
    # what drops the row — and the emergency it comes back as lifts the row
    # to the block again.
    uhr.weiter(faltpause.PAUSE_KURZ)
    assert faltpause.automatik_gesperrt(SCHLUESSEL) is True
    uhr.weiter(faltpause.WIEDERAUFNAHME_SEKUNDEN)
    assert faltpause.automatik_gesperrt(SCHLUESSEL) is False
    faltpause.versuch_verbraucht(SCHLUESSEL)
    assert faltpause.notfall(SCHLUESSEL, faltpause.KURZ) is True
    assert faltpause.hinweis_faellig(SCHLUESSEL) is True


def test_der_hinweis_kommt_nicht_bei_jedem_weiteren_notfall(uhr):
    """Once per block, not once per emergency: while the block already
    holds, a forced fold's emergency must not stamp the notice under every
    answer that follows."""
    faltpause.notfall(SCHLUESSEL, faltpause.KURZ)
    assert faltpause.notfall(SCHLUESSEL, faltpause.KURZ) is True
    assert faltpause.hinweis_faellig(SCHLUESSEL) is True

    faltpause.notfall(SCHLUESSEL, faltpause.KURZ)
    faltpause.notfall(SCHLUESSEL, faltpause.KURZ)

    assert faltpause.hinweis_faellig(SCHLUESSEL) is False
