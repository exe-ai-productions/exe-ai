"""The chat's event log, and why it has an end.

``Laufverwaltung._ereignisse`` is the SECOND copy of every line a command
writes: the run keeps its own, capped buffer (``MAX_PUFFER_ZEICHEN``), and
this one is what a watcher reattaches to after a dropped connection. It had
no cap at all and was released only when the chat was deleted — a nightly
run writing a hundred lines a second fills it with 180,000 entries in half
an hour, and fifty such runs a night is the shape this program was built for.

What is checked here is the cap and the two things it must not break: the
number carried on each event, which is how a reconnecting window tells
"already applied" from "new", and the resume position a fresh fetch hands
over.
"""

from __future__ import annotations

import pytest

from app.tools.hintergrund import MAX_EREIGNISSE, Laufverwaltung


@pytest.fixture
def verwaltung() -> Laufverwaltung:
    return Laufverwaltung()


def _melden(verwaltung: Laufverwaltung, anzahl: int, chat: str = "chat") -> None:
    for _ in range(anzahl):
        verwaltung.melden(chat, typ="lauf_zeile", lauf=1, text="x" * 100)


def test_der_speicher_hat_ein_ende(verwaltung):
    """Measured before the cap: 220 bytes an event, so a run writing at a
    hundred lines a second cost 130 MB in half an hour and never gave any of
    it back until the chat was deleted."""
    _melden(verwaltung, MAX_EREIGNISSE * 2)

    assert len(verwaltung._ereignisse["chat"]) == MAX_EREIGNISSE


def test_die_nummer_zaehlt_weiter_wenn_der_speicher_vergisst(verwaltung):
    """`n` is what a reconnecting window skips by — it remembers the highest
    it has seen and drops anything at or below it. Handed out from the
    LENGTH of the buffer, as it was, a full buffer would give the same
    number to every event that followed and the window would show one line
    and then nothing."""
    _melden(verwaltung, MAX_EREIGNISSE + 5)

    nummern = [e["n"] for e in verwaltung._ereignisse["chat"]]
    assert nummern == sorted(nummern), "the numbers no longer run upwards"
    assert len(set(nummern)) == len(nummern), "a number was handed out twice"
    assert nummern[-1] == MAX_EREIGNISSE + 4


def test_der_stand_bleibt_die_zahl_aller_ereignisse(verwaltung):
    """``GET /laeufe/{chat}`` hands this over as the ``ab`` the stream
    resumes from. The length of the buffer would name a position that passed
    long ago, and everything since would be replayed on top of the fetch
    that just drew it."""
    _melden(verwaltung, MAX_EREIGNISSE + 300)

    assert verwaltung.ereignisstand("chat") == MAX_EREIGNISSE + 300


async def test_wer_frisch_fetcht_bekommt_nichts_doppelt(verwaltung):
    """The ordinary case, and the one that must not change: a window fetches
    the runs, is told where it stands, and the stream starts after that."""
    _melden(verwaltung, MAX_EREIGNISSE + 10)
    ab = verwaltung.ereignisstand("chat")

    strom = verwaltung.zuschauen("chat", ab=ab, herzschlag_sekunden=0.01)
    verwaltung.melden("chat", typ="lauf_ende", lauf=1, code=0)
    erstes = await strom.__anext__()
    await strom.aclose()

    assert erstes["typ"] == "lauf_ende"
    assert erstes["n"] == ab


async def test_wer_zu_lange_weg_war_bekommt_den_rest_und_keinen_fehler(verwaltung):
    """The cost of the cap, said out loud: a watcher away for longer than
    the buffer holds gets what is left, not the events in between — and not
    an exception, and not the whole history a second time. The hole closes
    on the next run-list fetch, which carries every run's full output."""
    _melden(verwaltung, MAX_EREIGNISSE + 50)

    strom = verwaltung.zuschauen("chat", ab=0, herzschlag_sekunden=0.01)
    rueckblick = []
    async for ereignis in strom:
        if ereignis is None:  # the heartbeat: the backlog is through
            break
        rueckblick.append(ereignis)
    await strom.aclose()

    assert len(rueckblick) == MAX_EREIGNISSE
    # It resumes at the oldest one still kept, not at zero.
    assert rueckblick[0]["n"] == 50
    assert rueckblick[-1]["n"] == MAX_EREIGNISSE + 49


def test_ein_geloeschter_chat_nimmt_auch_seinen_stand_mit(verwaltung):
    """Otherwise the counter of a chat nobody can open any more is kept for
    the life of the process — and a chat id is never reused, so it would
    only ever grow."""
    _melden(verwaltung, 5)
    verwaltung.vergessen("chat")

    assert verwaltung.ereignisstand("chat") == 0
    assert "chat" not in verwaltung._ereignisse
