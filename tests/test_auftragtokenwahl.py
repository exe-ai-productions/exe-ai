"""The job token budget: cascade first, agent head overrides it outright."""

from __future__ import annotations

from app import auftragtokenwahl as atw


def test_ganze_zahl_ab_eins_wird_genommen():
    assert atw.wahl_pruefen(1) == 1
    assert atw.wahl_pruefen(16_000) == 16_000


def test_alles_unbrauchbare_zaehlt_als_ungesetzt():
    for wert in (0, -3, 2.5, "8192", None, [], {}):
        assert atw.wahl_pruefen(wert) is None


def test_ueber_der_obergrenze_zaehlt_als_ungesetzt():
    assert atw.wahl_pruefen(atw.OBERGRENZE) == atw.OBERGRENZE
    assert atw.wahl_pruefen(atw.OBERGRENZE + 1) is None


def test_bool_ist_keine_tokenzahl():
    assert atw.wahl_pruefen(True) is None
    assert atw.wahl_pruefen(False) is None


class _FakeEinstellungen:
    """The cascade as the real repository answers it: ``kette`` names the
    scopes general to specific, ``holen`` reads one scope's value. ``wert``
    is the global scope; ``modellwert`` the model's own, where a test sets
    one."""

    def __init__(self, wert, modellwert=None):
        self._wert = wert or {}
        self._modellwert = modellwert or {}

    def kette(self, schluessel, *, modell=None, chat=None):
        bereiche = ["global"]
        if modell:
            bereiche.append(f"modell:{modell}")
        if chat:
            bereiche.append(f"chat:{chat}")
        return bereiche

    def holen(self, bereich, schluessel):
        # The token number lives inside the `parameter` set of a scope, the
        # way the real repository stores it.
        assert schluessel == "parameter"
        if bereich == "global":
            return self._wert or None
        if bereich.startswith("modell:"):
            return self._modellwert or None
        return None

    def zusammengefuehrt(self, schluessel, *, modell=None, chat=None, vorgabe=None):
        return {**self._wert, **self._modellwert} or (vorgabe or {})


class _FakeRepos:
    def __init__(self, wert, modellwert=None):
        self.einstellungen = _FakeEinstellungen(wert, modellwert)


def test_nichts_gesetzt_heisst_auto():
    """Nothing anywhere answers ``None``: "Auto". What that comes to is
    worked out per request (app/antwortgrenze.py), never here — there is no
    shipped number left to fall back to.

    `zusammengefuehrt()` returns an empty dict here — the trap is treating
    that as a value instead of checking the key it does not have."""
    repos = _FakeRepos({})
    assert atw.aufgeloest(repos, modell="test", agent_wert=None) is None


def test_nimmt_den_kaskadenwert_wenn_gesetzt():
    repos = _FakeRepos({"max_tokens": 32_000, "temperature": 0.5})
    assert atw.aufgeloest(repos, modell="test", agent_wert=None) == 32_000


def test_agentenkopf_ueberschreibt_die_kaskade():
    repos = _FakeRepos({"max_tokens": 32_000})
    assert atw.aufgeloest(repos, modell="test", agent_wert=4096) == 4096


def test_unbrauchbarer_kaskadenwert_faellt_auf_die_vorgabe_zurueck():
    repos = _FakeRepos({"max_tokens": 0})
    assert atw.aufgeloest(repos, modell="test", agent_wert=None) is None


def test_unbrauchbarer_agentenwert_faellt_auf_die_kaskade_zurueck():
    repos = _FakeRepos({"max_tokens": 32_000})
    assert atw.aufgeloest(repos, modell="test", agent_wert=0) == 32_000


def test_ein_unbrauchbarer_modellwert_weicht_auf_den_globalen_aus():
    """Scope by scope, like every other reader of the cascade: a model value
    the check refuses (a string somebody typed into the file) steps aside
    for the global number, not past it to the shipped default."""
    repos = _FakeRepos({"max_tokens": 32_000}, modellwert={"max_tokens": "4096"})
    assert atw.aufgeloest(repos, modell="test", agent_wert=None) == 32_000


def test_ein_brauchbarer_modellwert_schlaegt_den_globalen():
    repos = _FakeRepos({"max_tokens": 32_000}, modellwert={"max_tokens": 4096})
    assert atw.aufgeloest(repos, modell="test", agent_wert=None) == 4096
