"""The goal report and the one gate (02.09.).

``deliver = 'log'`` means silent — decided for the schedule's own six
notifications and built as a single gate (``app/cronablauf.mitteilen``). The
goal tool was the seventh notification the program makes and passed none of
it: a quiet entry still rang, and played a sound, the moment its run reported
a goal.

Three things are pinned down here, and the third is the one the whole shape
hangs on.

**A quiet entry is quiet here too.** Sound and notification, both gone.

**A loud entry is unchanged.** Once, with its sound — the report was never
the noise anybody complained about.

**A goal reported in a CHAT still announces.** There is no entry there to
ask, and the gate reads "no entry" as "silent" — right for a schedule, wrong
for a conversation. This is why the branch sits in the tool and not in the
gate, and it is the assertion that would break first if somebody ever moved
it.

Silent is not invisible: the log line is written either way, before any of
this is reached.
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from app import cronablauf
from app.tools import ziel_werkzeug
from app.tools.registry import WerkzeugRegistry


def eintrag_bauen(repos, **felder):
    return repos.cronjobs.erstellen(
        agent=felder.pop("agent", "beobachter"),
        task=felder.pop("task", "Ins Postfach sehen"),
        zeitplan=felder.pop("zeitplan", "*/15 * * * *"),
        herkunft="chat",
        ziel=felder.pop("ziel", "Eine Mail von M. liegt im Postfach"),
        **felder,
    )


@pytest.fixture
def gemeldet(monkeypatch):
    """Every announcement that would have reached the notification module,
    as (text, erfolgreich) — trapped in the one place both paths end in."""
    aufrufe: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        ziel_werkzeug.cronmeldung,
        "melden",
        lambda text, *, erfolgreich: aufrufe.append((text, erfolgreich)),
    )
    monkeypatch.setattr(
        cronablauf.cronmeldung,
        "melden",
        lambda text, *, erfolgreich: aufrufe.append((text, erfolgreich)),
    )
    return aufrufe


# --- Through the registry, the way a real run gets here ---------------------


def test_ein_log_termin_meldet_beim_ziel_gar_nichts(repos, gemeldet):
    """The whole finding. The entry asked to be quiet, and until now the
    goal report was the one sentence that ignored it."""
    eintrag = eintrag_bauen(repos, deliver="log")
    registry = WerkzeugRegistry([], cronjobs_repo=repos.cronjobs)
    antwort = asyncio.run(
        registry.ausfuehren(
            ziel_werkzeug.WERKZEUG_NAME,
            {"report": "Mail von M. da, Betreff: Angebot"},
            cronjob_id=eintrag.id,
        )
    )
    assert antwort == ziel_werkzeug.GEMELDET
    assert gemeldet == []


def test_ein_announce_termin_meldet_genau_einmal(repos, gemeldet):
    """Unchanged, and exactly once: the report was never the noise."""
    eintrag = eintrag_bauen(repos, deliver="announce")
    registry = WerkzeugRegistry([], cronjobs_repo=repos.cronjobs)
    asyncio.run(
        registry.ausfuehren(
            ziel_werkzeug.WERKZEUG_NAME,
            {"report": "Mail von M. da, Betreff: Angebot"},
            cronjob_id=eintrag.id,
        )
    )
    assert gemeldet == [("Mail von M. da, Betreff: Angebot", True)]


def test_ein_ziel_im_chat_meldet_weiter(repos, gemeldet):
    """The proof the whole shape hangs on. A goal can be handed out in a
    conversation, and a conversation has no entry — the gate would read that
    as "silent" and swallow a report nobody asked to be quiet."""
    registry = WerkzeugRegistry([], cronjobs_repo=repos.cronjobs)
    asyncio.run(
        registry.ausfuehren(
            ziel_werkzeug.WERKZEUG_NAME, {"report": "Mail von M. da"}
        )
    )
    assert gemeldet == [("Mail von M. da", True)]


def test_ohne_cron_tabelle_meldet_es_auch(gemeldet):
    """A registry with no schedule table at all — the tool works everywhere,
    and "no equipment" must not turn into "no report"."""
    registry = WerkzeugRegistry([])
    asyncio.run(
        registry.ausfuehren(
            ziel_werkzeug.WERKZEUG_NAME, {"report": "Mail von M. da"}
        )
    )
    assert gemeldet == [("Mail von M. da", True)]


def test_ein_geloeschter_eintrag_meldet_nicht(repos, gemeldet):
    """Same answer the gate already gives for a row that is gone: there is
    nothing left to speak for. The model is still told it reported."""
    eintrag = eintrag_bauen(repos, deliver="announce")
    repos.cronjobs.loeschen(eintrag.id)
    registry = WerkzeugRegistry([], cronjobs_repo=repos.cronjobs)
    antwort = asyncio.run(
        registry.ausfuehren(
            ziel_werkzeug.WERKZEUG_NAME,
            {"report": "Mail von M. da"},
            cronjob_id=eintrag.id,
        )
    )
    assert antwort == ziel_werkzeug.GEMELDET
    assert gemeldet == []


# --- Silent is not invisible ------------------------------------------------


def test_der_stille_lauf_schreibt_seine_zeile_trotzdem(repos, gemeldet, caplog):
    eintrag = eintrag_bauen(repos, deliver="log")
    registry = WerkzeugRegistry([], cronjobs_repo=repos.cronjobs)
    with caplog.at_level(logging.INFO, logger="app.tools.ziel_werkzeug"):
        asyncio.run(
            registry.ausfuehren(
                ziel_werkzeug.WERKZEUG_NAME,
                {"report": "Mail von M. da"},
                cronjob_id=eintrag.id,
            )
        )
    ereignisse = [
        satz.bericht
        for satz in caplog.records
        if getattr(satz, "ereignis", None) == "ziel_gemeldet"
    ]
    assert ereignisse == ["Mail von M. da"]
    assert gemeldet == []


# --- The rule stays in one place --------------------------------------------


def test_das_werkzeug_vergleicht_deliver_nicht_selbst():
    """The point of a gate is that nobody else asks the question. A second
    ``deliver`` comparison here would be the copy dc9d2c4 removed, growing
    back in a new place."""
    quelle = ziel_werkzeug.__file__
    with open(quelle, encoding="utf-8") as datei:
        zeilen = [
            zeile
            for zeile in datei.read().splitlines()
            if "deliver" in zeile and not zeile.lstrip().startswith("#")
        ]
    assert not [z for z in zeilen if "==" in z or "!=" in z], zeilen
