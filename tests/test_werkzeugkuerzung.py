"""Old tool results cleared from the request before anything is summarized.

The first step against a window that is filling up costs no model and no
waiting: what a tool printed many rounds ago becomes one line in the REQUEST,
and the rows keep every character (``app/werkzeugkuerzung.py``). Only where
the window is still too full afterwards is a summary asked for.

Three things are checked here and nowhere else: that the step happens between
the tool rounds of ONE answer and ONE run, that a call and its result never
come apart, and that the database does not learn about any of it. The fourth
is the chat's half — a later tool round of a chat gets the same lowered ceiling a
job's round has had all along.
"""

from __future__ import annotations

import json

import pytest

from app import kontextdruck, verdichtung, werkzeugbild, werkzeugkuerzung
from app.api.v1.generierung import WERKZEUGERGEBNIS_GRENZE
from app.providers import ChatNachricht, MockProvider, ProviderFehler, mock_endpunkt
from app.providers.base import Stueck, Werkzeugaufruf
from tests.conftest import (
    FENSTER,
    GROSS,
    KLEIN,
    KNAPP_UNTER_DER_SCHWELLE,
    RUNDENTEXT,
    RUNDENTEXT_GROSS,
    UEBER_DER_SCHWELLE,
    UNTER_DER_SCHWELLE,
    GrossesErgebnis,
    chatkette,
    provider_setzen,
    senden,
)
from tests.test_auftraege_api import RegistryDouble, agent_schreiben, auf_ende_warten
from tests.test_auftraege_api import mcp_client as _mcp_client

# The tool-enabled client, borrowed rather than built a second time. pytest
# looks a fixture up by the MODULE attribute it is bound to, so it has to
# carry that name here — bound rather than imported under it, because an
# import of that name and a test parameter of that name read to the linter as
# one name defined twice.
mcp_client = _mcp_client
from tests.test_kontextvoll import VLLM_ZU_GROSS


def _werkzeugzug(nummer: int, ergebnis: str) -> list[ChatNachricht]:
    """One tool round as a provider wants it back: the call on the assistant
    turn, the result in a message of its own, tied to it by id."""
    return [
        ChatNachricht(
            role="assistant",
            content=f"round {nummer}",
            werkzeugaufrufe=[Werkzeugaufruf(id=f"w{nummer}", name="riesig", argumente={})],
        ),
        ChatNachricht(role="tool", content=ergebnis, werkzeugaufruf_id=f"w{nummer}"),
    ]


# --- The module on its own -------------------------------------------------


def test_alte_ergebnisse_werden_ein_platzhalter():
    nachrichten = [
        ChatNachricht(role="system", content="system"),
        ChatNachricht(role="user", content="question"),
        *_werkzeugzug(1, "a" * 500),
        *_werkzeugzug(2, "b" * 500),
    ]

    neu, anzahl = werkzeugkuerzung.kuerzen(nachrichten, len(nachrichten))

    assert anzahl == 2
    assert [n.content for n in neu if n.role == "tool"] == [
        werkzeugkuerzung.PLATZHALTER,
        werkzeugkuerzung.PLATZHALTER,
    ]
    # Nothing else was touched, and nothing was dropped.
    assert len(neu) == len(nachrichten)
    assert [n.role for n in neu] == [n.role for n in nachrichten]
    assert [n.content for n in neu if n.role != "tool"] == [
        "system", "question", "round 1", "round 2",
    ]


def test_das_geschuetzte_ende_bleibt_woertlich():
    """The tail is the model's own working memory — a placeholder there would
    take away what it is working from."""
    nachrichten = [
        ChatNachricht(role="user", content="question"),
        *_werkzeugzug(1, "a" * 500),
        *_werkzeugzug(2, "b" * 500),
    ]

    # Everything from the second round's call on is protected.
    neu, anzahl = werkzeugkuerzung.kuerzen(nachrichten, 3)

    assert anzahl == 1
    assert neu[2].content == werkzeugkuerzung.PLATZHALTER
    assert neu[4].content == "b" * 500


def test_kurze_ergebnisse_bleiben():
    """A short result usually IS the answer; a placeholder would save nothing
    and cost the model the only line it had."""
    knapp_darunter = "a" * (werkzeugkuerzung.MINDESTZEICHEN - 1)
    genau_darauf = "b" * werkzeugkuerzung.MINDESTZEICHEN
    nachrichten = [
        ChatNachricht(role="user", content="question"),
        *_werkzeugzug(1, knapp_darunter),
        *_werkzeugzug(2, genau_darauf),
    ]

    neu, anzahl = werkzeugkuerzung.kuerzen(nachrichten, len(nachrichten))

    assert anzahl == 1
    assert neu[2].content == knapp_darunter
    assert neu[4].content == werkzeugkuerzung.PLATZHALTER


def test_doppelte_ergebnisse_zeigen_auf_das_neueste():
    """Byte-identical results INSIDE the protected end point at the newest
    copy instead of carrying the same bytes twice. Nothing unique is lost,
    which is the reason for this one exception to the protected end."""
    gleich = "a" * 500
    nachrichten = [
        ChatNachricht(role="user", content="question"),
        *_werkzeugzug(1, gleich),
        *_werkzeugzug(2, gleich),
        *_werkzeugzug(3, gleich),
    ]

    # Everything from the second round on is protected.
    neu, anzahl = werkzeugkuerzung.kuerzen(nachrichten, 3)

    assert anzahl == 2
    # Ahead of the boundary the ordinary placeholder, not a pointer.
    assert neu[2].content == werkzeugkuerzung.PLATZHALTER
    # Inside it the older copy points at the newest, the newest stands.
    assert neu[4].content == werkzeugkuerzung.DOPPELT
    assert neu[6].content == gleich


def test_kein_zeiger_auf_ein_geloeschtes_ergebnis():
    """A pointer may never outlive what it points at. The duplicate pass runs
    inside the protected end only, so its referent is protected too — with
    both passes on one list there is no order in which the second could clear
    the copy the first pointed a reader to."""
    gleich = "a" * 500
    nachrichten = [
        ChatNachricht(role="user", content="question"),
        *_werkzeugzug(1, gleich),
        *_werkzeugzug(2, gleich),
        ChatNachricht(role="user", content="tail"),
    ]

    # The boundary falls between the two copies: the older is cleared, the
    # newer is protected.
    neu, _ = werkzeugkuerzung.kuerzen(nachrichten, 3)

    zeiger = [n for n in neu if n.content == werkzeugkuerzung.DOPPELT]
    for _ in zeiger:
        assert gleich in [n.content for n in neu], "the pointer lost its referent"
    assert neu[2].content == werkzeugkuerzung.PLATZHALTER
    assert neu[4].content == gleich


def test_die_grenze_ist_die_des_faltens():
    """The boundary a caller must hand over is ``verdichtung.geschuetztes_ende``
    and never ``schwanz_anfang`` alone: the raw boundary can land INSIDE the
    tool results of the round that just ran, and a result cleared there tells
    the model its own fresh call produced nothing — it would simply make the
    call again."""
    budget = 600
    nachrichten = [
        ChatNachricht(role="system", content="system"),
        ChatNachricht(role="user", content="question"),
        *_werkzeugzug(1, "a" * 5_000),
        ChatNachricht(
            role="assistant",
            content="two calls",
            werkzeugaufrufe=[
                Werkzeugaufruf(id="wa", name="riesig", argumente={}),
                Werkzeugaufruf(id="wb", name="riesig", argumente={}),
            ],
        ),
        ChatNachricht(role="tool", content="A" * 500, werkzeugaufruf_id="wa"),
        ChatNachricht(role="tool", content="B" * 500, werkzeugaufruf_id="wb"),
    ]
    roh = verdichtung.schwanz_anfang(
        [n.content or "" for n in nachrichten], budget
    )
    grenze = verdichtung.geschuetztes_ende(nachrichten, budget)
    assert grenze < roh, "this history is only interesting where the two differ"

    neu, _ = werkzeugkuerzung.kuerzen(nachrichten, grenze)

    # The round that just ran keeps both of its results.
    assert neu[-2].content == "A" * 500
    assert neu[-1].content == "B" * 500
    # The older round is shortened, so the boundary did not simply protect all.
    assert neu[3].content == werkzeugkuerzung.PLATZHALTER


def test_ein_zweiter_durchgang_aendert_nichts():
    """Both lines this writes are shorter than the floor, so an already
    shortened list is recognized by its own length and nothing else."""
    nachrichten = [
        ChatNachricht(role="user", content="question"),
        *_werkzeugzug(1, "a" * 500),
    ]

    einmal, erste = werkzeugkuerzung.kuerzen(nachrichten, len(nachrichten))
    zweimal, zweite = werkzeugkuerzung.kuerzen(einmal, len(einmal))

    assert erste == 1
    assert zweite == 0
    assert zweimal is einmal


def test_nichts_zu_tun_gibt_die_eingabe_zurueck():
    """A caller reads "nothing happened" off the count and never has to
    compare two lists."""
    nachrichten = [ChatNachricht(role="user", content="question")]

    neu, anzahl = werkzeugkuerzung.kuerzen(nachrichten, len(nachrichten))

    assert anzahl == 0
    assert neu is nachrichten
    assert werkzeugkuerzung.kuerzen([], 0) == ([], 0)


@pytest.mark.parametrize("geschuetzt_ab", [-5, 0, 99])
def test_eine_grenze_ausserhalb_der_liste_verrutscht_nicht(geschuetzt_ab):
    nachrichten = [
        ChatNachricht(role="user", content="question"),
        *_werkzeugzug(1, "a" * 500),
    ]

    neu, anzahl = werkzeugkuerzung.kuerzen(nachrichten, geschuetzt_ab)

    assert len(neu) == len(nachrichten)
    assert anzahl == (1 if geschuetzt_ab == 99 else 0)


def test_aufruf_und_ergebnis_bleiben_zusammen():
    """Every call keeps the result that answers it, in the same order and
    under the same id: a tool result whose call is gone is invalid history,
    and Anthropic answers it with a 400."""
    nachrichten = [
        ChatNachricht(role="user", content="question"),
        *_werkzeugzug(1, "a" * 500),
        *_werkzeugzug(2, "b" * 500),
        *_werkzeugzug(3, "c" * 500),
    ]

    neu, _ = werkzeugkuerzung.kuerzen(nachrichten, 3)

    paare = [
        (n.werkzeugaufrufe[0].id if n.werkzeugaufrufe else None, n.werkzeugaufruf_id)
        for n in neu
    ]
    assert paare == [
        (None, None), ("w1", None), (None, "w1"),
        ("w2", None), (None, "w2"), ("w3", None), (None, "w3"),
    ]


def test_zeichen_zaehlt_die_ganze_liste():
    nachrichten = [
        ChatNachricht(role="user", content="abc"),
        ChatNachricht(role="assistant", content=""),
    ]
    assert werkzeugkuerzung.zeichen(nachrichten) == 3


def _bildzug(nummer: int, pfad: str | None = "/ordner/bild.png") -> ChatNachricht:
    """The message a tool's picture rides on (app/werkzeugbild.py)."""
    return werkzeugbild.nachricht(
        [f"bild{nummer}.png"],
        [f"data:image/png;base64,AAA{nummer}"],
        [pfad] if pfad else [""],
    )


def test_ein_bild_wiegt_in_der_kuerzung_mit():
    """A picture is priced at the one house estimate, here as everywhere —
    read by its text alone, a request that had just dropped five pictures
    reported saving nothing."""
    ohne = [ChatNachricht(role="user", content="abc")]
    mit = ohne + [_bildzug(1)]

    assert werkzeugkuerzung.zeichen(mit) - werkzeugkuerzung.zeichen(ohne) == (
        len(mit[1].content or "") + kontextdruck.bild_zeichen(1)
    )


def test_ein_bild_verschiebt_die_grenze_des_schwanzes():
    """The same weight, in the boundary the fold and the pruning share."""
    text = [ChatNachricht(role="user", content="x" * 100) for _ in range(6)]
    budget = 400
    ohne = verdichtung.geschuetztes_ende(text, budget)
    mit_bild = list(text)
    mit_bild[3] = _bildzug(1)

    assert verdichtung.geschuetztes_ende(mit_bild, budget) > ohne


def test_die_drei_neuesten_werkzeugbilder_bleiben():
    """Five pictures a tool read: the newest three keep theirs, the older two
    say where the file is instead. The number comes from the constant."""
    nachrichten = [ChatNachricht(role="user", content="frage")]
    for nr in range(5):
        nachrichten.append(_bildzug(nr, f"/ordner/bild{nr}.png"))

    neu, anzahl = werkzeugkuerzung.kuerzen(nachrichten, geschuetzt_ab=len(nachrichten))

    behalten = werkzeugkuerzung.WERKZEUGBILDER_BEHALTEN
    mit_bild = [n for n in neu if n.alle_bild_urls()]
    assert len(mit_bild) == behalten
    assert anzahl == 5 - behalten
    for n in neu[1 : 1 + 5 - behalten]:
        assert not n.alle_bild_urls()
        assert n.content.startswith(werkzeugkuerzung.BILD_ENTFERNT)
        assert "/ordner/bild" in n.content
        assert "read_file" in n.content


def test_ein_hochgeladenes_bild_bleibt_unberuehrt():
    """"User uploads untouched": a picture somebody attached is part of what
    they asked, however old it is."""
    hochgeladen = ChatNachricht(
        role="user", content="mein Bild", bild_urls=["data:image/png;base64,ZZZ"]
    )
    nachrichten = [hochgeladen] + [_bildzug(nr) for nr in range(4)]

    neu, _ = werkzeugkuerzung.kuerzen(nachrichten, geschuetzt_ab=len(nachrichten))

    assert neu[0].alle_bild_urls() == hochgeladen.alle_bild_urls()
    assert neu[0].content == "mein Bild"


def test_ohne_pfad_steht_der_leitsatz_allein():
    """A picture with no file to read back: the sentence stands on its own,
    with no empty path in it."""
    nachrichten = [_bildzug(nr, pfad=None) for nr in range(4)]

    neu, _ = werkzeugkuerzung.kuerzen(nachrichten, geschuetzt_ab=len(nachrichten))

    assert neu[0].content == werkzeugkuerzung.BILD_ENTFERNT


def test_drei_bilder_werden_nicht_ausgemustert():
    """Silence test: up to the constant nothing is retired at all."""
    nachrichten = [_bildzug(nr) for nr in range(werkzeugkuerzung.WERKZEUGBILDER_BEHALTEN)]

    neu, anzahl = werkzeugkuerzung.kuerzen(nachrichten, geschuetzt_ab=len(nachrichten))

    assert anzahl == 0
    assert neu is nachrichten


def test_fuenf_werkzeugbilder_in_einer_nachricht_werden_je_bild_gezaehlt():
    """One round can read several pictures into a single message
    (``app/werkzeugbild.py``): the cut counts each of them on its own, not
    the one message they all rode in on. ``geschuetzt_ab=0`` protects the
    whole list from the generic shortening passes above, so only the
    picture pass — which never respects that boundary — is exercised here."""
    namen = [f"bild{nr}.png" for nr in range(5)]
    pfade = [f"/ordner/{name}" for name in namen]
    urls = [f"data:image/png;base64,AAA{nr}" for nr in range(5)]
    aufrufe = [Werkzeugaufruf(id=f"w{nr}", name="read_file", argumente={}) for nr in range(5)]
    ergebnisse = [
        ChatNachricht(
            role="tool", content=werkzeugbild.bildsatz(pfad, 1_000), werkzeugaufruf_id=f"w{nr}"
        )
        for nr, pfad in enumerate(pfade)
    ]
    nachrichten = [
        ChatNachricht(role="user", content="frage"),
        ChatNachricht(role="assistant", content="", werkzeugaufrufe=aufrufe),
        *ergebnisse,
        werkzeugbild.nachricht(namen, urls, pfade),
    ]

    neu, anzahl = werkzeugkuerzung.kuerzen(nachrichten, geschuetzt_ab=0)

    behalten = werkzeugkuerzung.WERKZEUGBILDER_BEHALTEN
    ausgemustert = 5 - behalten
    bildnachricht = neu[-1]
    assert anzahl == ausgemustert
    assert bildnachricht.werkzeugbilder == pfade[ausgemustert:]
    assert bildnachricht.bild_urls == urls[ausgemustert:]
    # The introduction keeps naming its pictures by their SHORT name — the
    # one the read announced them under, not the full path a retired one is
    # read back by.
    assert bildnachricht.content.startswith(
        werkzeugbild.EINLEITUNG.format(namen=", ".join(namen[ausgemustert:]))
    )
    for pfad in pfade[:ausgemustert]:
        assert pfad in bildnachricht.content
    # Only the two oldest results lose the promise; the three kept pictures'
    # own results still say the picture is attached this round.
    ergebnisse_neu = neu[2:7]
    for nr, ergebnis in enumerate(ergebnisse_neu[:ausgemustert]):
        assert ergebnis.content == werkzeugbild.NICHT_MEHR_DABEI
    for nr, ergebnis in enumerate(ergebnisse_neu[ausgemustert:], start=ausgemustert):
        assert ergebnis.content == werkzeugbild.bildsatz(pfade[nr], 1_000)


def test_fuenf_werkzeugbilder_bleiben_bei_drei_haengen():
    """Silence test: a round with exactly three pictures in one message
    keeps all of them, whatever else already sits in the request."""
    pfade = [f"/ordner/bild{nr}.png" for nr in range(3)]
    urls = [f"data:image/png;base64,AAA{nr}" for nr in range(3)]
    nachrichten = [
        ChatNachricht(role="user", content="frage"),
        werkzeugbild.nachricht([f"bild{nr}.png" for nr in range(3)], urls, pfade),
    ]

    neu, anzahl = werkzeugkuerzung.kuerzen(nachrichten, geschuetzt_ab=0)

    assert anzahl == 0
    assert neu is nachrichten


def test_dasselbe_bild_zweimal_in_einer_runde_behaelt_das_zweite_versprechen():
    """The same file read twice inside ONE round, into one picture message:
    retiring the older instance must not take the promise from the kept
    one's own result just because the two share a path — only their
    position in the round tells them apart, the path cannot. The sizes
    differ so the two results are not byte-identical — otherwise the
    unrelated duplicate-RESULT pass above would fire first and this test
    would measure that pass instead of this one."""
    dup = "/ordner/dup.png"
    groessen = [1_000, 2_000, 3_000, 4_000]
    pfade = [dup, "/ordner/a.png", dup, "/ordner/b.png"]
    urls = [f"data:image/png;base64,X{nr}" for nr in range(4)]
    aufrufe = [Werkzeugaufruf(id=f"w{nr}", name="read_file", argumente={}) for nr in range(4)]
    ergebnisse = [
        ChatNachricht(
            role="tool",
            content=werkzeugbild.bildsatz(pfad, groessen[nr]),
            werkzeugaufruf_id=f"w{nr}",
        )
        for nr, pfad in enumerate(pfade)
    ]
    nachrichten = [
        ChatNachricht(role="user", content="frage"),
        ChatNachricht(role="assistant", content="", werkzeugaufrufe=aufrufe),
        *ergebnisse,
        werkzeugbild.nachricht(["dup.png", "a.png", "dup.png", "b.png"], urls, pfade),
    ]

    neu, anzahl = werkzeugkuerzung.kuerzen(nachrichten, geschuetzt_ab=0)

    assert anzahl == 1
    ergebnisse_neu = neu[2:6]
    assert ergebnisse_neu[0].content == werkzeugbild.NICHT_MEHR_DABEI
    for nr in range(1, 4):
        assert ergebnisse_neu[nr].content == werkzeugbild.bildsatz(pfade[nr], groessen[nr])


def test_ein_bereits_ausgemustertes_duplikat_verschiebt_das_bildversprechen_nicht():
    """The duplicate-RESULT pass above (``DOPPELT``) can blank an older copy
    of a byte-identical tool result before this pass runs. Counting the
    round's image-announcing results off the list that pass already rewrote
    would silently drop that blanked result from the count and shift every
    later picture's match onto the wrong, still-kept result — read against
    the untouched input list instead, so the position stays right."""
    dup = "/ordner/dup.png"
    pfade = [dup, "/ordner/a.png", dup, "/ordner/b.png"]
    urls = [f"data:image/png;base64,X{nr}" for nr in range(4)]
    aufrufe = [Werkzeugaufruf(id=f"w{nr}", name="read_file", argumente={}) for nr in range(4)]
    # Same size for both `dup.png` reads: the two results are byte-identical,
    # exactly what the duplicate-result pass above looks for.
    ergebnisse = [
        ChatNachricht(
            role="tool", content=werkzeugbild.bildsatz(pfad, 5_000), werkzeugaufruf_id=f"w{nr}"
        )
        for nr, pfad in enumerate(pfade)
    ]
    nachrichten = [
        ChatNachricht(role="user", content="frage"),
        ChatNachricht(role="assistant", content="", werkzeugaufrufe=aufrufe),
        *ergebnisse,
        werkzeugbild.nachricht(["dup.png", "a.png", "dup.png", "b.png"], urls, pfade),
    ]

    neu, anzahl = werkzeugkuerzung.kuerzen(nachrichten, geschuetzt_ab=0)

    assert anzahl == 2  # one DOPPELT result, one retired picture
    ergebnisse_neu = neu[2:6]
    # The retired picture's own result: the duplicate note is superseded by
    # the stronger, final one — the picture is gone from the request either way.
    assert ergebnisse_neu[0].content == werkzeugbild.NICHT_MEHR_DABEI
    # a.png is KEPT and was never a duplicate of anything — its result must
    # keep its own promise untouched, not inherit the retired picture's note.
    assert ergebnisse_neu[1].content == werkzeugbild.bildsatz(pfade[1], 5_000)
    # The second `dup.png` is KEPT too — its result stands as the canonical
    # copy the duplicate pass pointed at, unrelated to the picture pass.
    assert ergebnisse_neu[2].content == werkzeugbild.bildsatz(pfade[2], 5_000)
    assert ergebnisse_neu[3].content == werkzeugbild.bildsatz(pfade[3], 5_000)


# --- Chat -------------------------------------------------------------------



def _chat(client) -> str:
    return client.post("/api/v1/chats", json={"title": "Kuerzung"}).json()["id"]


def _nachrichten(client, chat_id: str) -> list[dict]:
    return client.get(f"/api/v1/chats/{chat_id}/messages").json()["nachrichten"]


def _paare_stimmen(aufzeichnung: list[tuple[str, str]]) -> bool:
    """Every tool result is directly preceded by an assistant turn — the one
    thing a provider refuses the whole history over."""
    return all(
        stelle > 0 and aufzeichnung[stelle - 1][0] == "assistant"
        for stelle, (rolle, _) in enumerate(aufzeichnung)
        if rolle == "tool"
    )


def test_chat_kuerzt_alte_ergebnisse_zwischen_den_runden(mcp_client):
    """The step that needs no model: from the second tool round on, the
    earlier results travel as one line, the newest one travels whole, and no
    summary was ever asked for."""
    provider = chatkette(mcp_client, runden=6, stand=KNAPP_UNTER_DER_SCHWELLE, ergebnis=GROSS)
    chat_id = _chat(mcp_client)

    senden(mcp_client, chat_id)

    assert provider.faltungen == 0, "the first step alone had to be enough"
    letzte = provider.aufzeichnung[-1]
    inhalte = [inhalt for _, inhalt in letzte]
    assert inhalte.count(werkzeugkuerzung.PLATZHALTER) == 3
    # The newest result is what the model is working from — untouched by the
    # clearing and carried the way the tool handed it over: cut at the
    # house's ceiling, as every result is now (``WERKZEUGERGEBNIS_GRENZE``),
    # and certainly not a placeholder.
    assert letzte[-1][0] == "tool"
    assert letzte[-1][1].endswith("y" * 1_000), "no longer the tool's text"
    assert len(letzte[-1][1]) == WERKZEUGERGEBNIS_GRENZE
    assert _paare_stimmen(letzte)


def test_chat_reicht_die_erste_stufe_nicht_wird_im_lauf_gefaltet(mcp_client):
    """The reading alone is over the threshold, so clearing the results
    cannot bring it down: a summary is asked for mid-answer, and the answer
    still comes."""
    provider = chatkette(mcp_client, runden=6, stand=UEBER_DER_SCHWELLE, ergebnis=GROSS,
                          rundentext=RUNDENTEXT_GROSS)
    chat_id = _chat(mcp_client)

    senden(mcp_client, chat_id)

    assert provider.faltungen >= 1
    assert _nachrichten(mcp_client, chat_id)[-1]["content"].endswith("done")
    # The summary went into the request, and the fold kept the pairs.
    letzte = provider.aufzeichnung[-1]
    assert any(
        inhalt.startswith(verdichtung.VORSPANN) for _, inhalt in letzte
    ), "the request has to carry the summary that replaced the middle"
    assert _paare_stimmen(letzte)


def test_die_naechste_nachricht_traegt_das_geraeumte_wie_der_lauf(mcp_client):
    """What a run cleared stays cleared in the next request — result by result.

    The clearing works on the request alone and the rows keep every character
    (app/werkzeugkuerzung.py). Without a note in the row the next request
    sent the cleared results WHOLE again: the request after an answer read
    differently from the request inside it, and the server read everything
    from the first cleared round on anew. Falls today: 3 cleared results in the run, 3 whole ones in
    the request after it.
    """
    provider = chatkette(mcp_client, runden=6, stand=KNAPP_UNTER_DER_SCHWELLE, ergebnis=GROSS)
    chat_id = _chat(mcp_client)

    senden(mcp_client, chat_id)
    im_lauf = [inhalt for rolle, inhalt in provider.aufzeichnung[-1] if rolle == "tool"]
    assert im_lauf.count(werkzeugkuerzung.PLATZHALTER) == 3

    senden(mcp_client, chat_id)
    danach = [inhalt for rolle, inhalt in provider.aufzeichnung[-1] if rolle == "tool"]

    assert danach == im_lauf, "the rebuild does not send what was cleared replaced the same way"
    # And the window keeps every character: the rows still carry the results.
    ergebnisse = [
        eintrag["ergebnis"]
        for zeile in _nachrichten(mcp_client, chat_id)
        for eintrag in ((zeile.get("stats") or {}).get("werkzeuge") or [])
    ]
    assert ergebnisse, "the answers must have logged their tool calls"
    assert all(werkzeugkuerzung.PLATZHALTER not in ergebnis for ergebnis in ergebnisse)


def test_chat_die_zeilen_erfahren_nichts_von_der_kuerzung(mcp_client):
    """The rows are what the reader reads, and they keep every character: the
    shortening happens in the request alone, and no fold is written down."""
    provider = chatkette(mcp_client, runden=6, stand=KNAPP_UNTER_DER_SCHWELLE, ergebnis=GROSS)
    chat_id = _chat(mcp_client)

    senden(mcp_client, chat_id)

    assert werkzeugkuerzung.PLATZHALTER in [
        inhalt for _, inhalt in provider.aufzeichnung[-1]
    ]
    zeilen = _nachrichten(mcp_client, chat_id)
    assert not [z for z in zeilen if z.get("art") == "verdichtung"]
    ergebnisse = [
        eintrag["ergebnis"]
        for zeile in zeilen
        for eintrag in ((zeile.get("stats") or {}).get("werkzeuge") or [])
    ]
    assert ergebnisse, "the answer has to have logged its tool calls"
    # Cut only where every stored result is cut, never by this step.
    assert all(len(ergebnis) == WERKZEUGERGEBNIS_GRENZE for ergebnis in ergebnisse)
    assert all(werkzeugkuerzung.PLATZHALTER not in ergebnis for ergebnis in ergebnisse)


def test_chat_kurze_kette_kuerzt_nichts(mcp_client):
    """The silence test: a couple of rounds with small results stay word for
    word, and nothing is folded either."""
    provider = chatkette(mcp_client, runden=3, stand=UNTER_DER_SCHWELLE, ergebnis=KLEIN)
    chat_id = _chat(mcp_client)

    senden(mcp_client, chat_id)

    assert provider.faltungen == 0
    for aufzeichnung in provider.aufzeichnung:
        inhalte = [inhalt for _, inhalt in aufzeichnung]
        assert werkzeugkuerzung.PLATZHALTER not in inhalte
        assert werkzeugkuerzung.DOPPELT not in inhalte
    assert _nachrichten(mcp_client, chat_id)[-1]["content"].endswith("done")


# --- The context bar reads the total the trigger weighs ---------------------


def _schwellenlesungen(monkeypatch) -> list[int]:
    """Every total the chat's own trigger reads between rounds — the last
    real reading plus what is new — recorded as the trigger is asked."""
    import sys

    gelesen: list[int] = []
    echt = kontextdruck.ueber_der_schwelle

    def mitschreiben(letzter_stand, neu_tokens, fenster, *rest, **benannt):
        if sys._getframe(1).f_code.co_filename.endswith("round_end.py"):
            gelesen.append(round((letzter_stand or 0) + neu_tokens))
        return echt(letzter_stand, neu_tokens, fenster, *rest, **benannt)

    monkeypatch.setattr(kontextdruck, "ueber_der_schwelle", mitschreiben)
    return gelesen


def _kontextstaende(ereignisse: list[dict]) -> list[int]:
    return [e["gesamt_tokens"] for e in ereignisse if e["typ"] == "kontext"]


def test_chat_meldet_den_stand_mit_den_ergebnissen_der_runde(mcp_client, monkeypatch):
    """After a tool round the bar shows what the trigger reads: the round's
    real reading plus its own results. Every reading the round reported was
    taken before those results existed, so without its own event the bar
    stood below the number the fold was decided on."""
    gelesen = _schwellenlesungen(monkeypatch)
    chatkette(mcp_client, runden=1, stand=UNTER_DER_SCHWELLE, ergebnis=GROSS)
    chat_id = _chat(mcp_client)

    staende = _kontextstaende(senden(mcp_client, chat_id))

    assert gelesen, "the trigger between rounds was never asked"
    assert gelesen[0] > UNTER_DER_SCHWELLE, "the round's result has to weigh in"
    assert gelesen[0] in staende, (gelesen, staende)
    # And it arrives after the round's own reading, not before it.
    assert staende.index(gelesen[0]) > staende.index(UNTER_DER_SCHWELLE)


def test_chat_meldet_den_stand_auch_nach_der_kuerzung(mcp_client, monkeypatch):
    """The second place a job reports: once old results were cleared, the
    fold reads the lower total — and so does the bar."""
    gelesen = _schwellenlesungen(monkeypatch)
    provider = chatkette(
        mcp_client, runden=6, stand=KNAPP_UNTER_DER_SCHWELLE, ergebnis=GROSS
    )
    chat_id = _chat(mcp_client)

    staende = _kontextstaende(senden(mcp_client, chat_id))

    assert werkzeugkuerzung.PLATZHALTER in [
        inhalt for _, inhalt in provider.aufzeichnung[-1]
    ], "the clearing has to have run for this test to mean anything"
    # A reading after the clearing is lower than the one right before it —
    # the one only the second report carries.
    assert any(nachher < vorher for vorher, nachher in zip(gelesen[:-1], gelesen[1:], strict=True))
    assert set(gelesen) <= set(staende), (gelesen, staende)


def test_chat_ohne_werkzeugrunde_meldet_nichts_dazu(mcp_client, monkeypatch):
    """Silence probe: an answer without a tool round sends no extra
    reading — only the round's own one."""
    gelesen = _schwellenlesungen(monkeypatch)
    chatkette(mcp_client, runden=0, stand=UNTER_DER_SCHWELLE, ergebnis=GROSS)
    chat_id = _chat(mcp_client)

    staende = _kontextstaende(senden(mcp_client, chat_id))

    assert gelesen == []
    assert staende == [UNTER_DER_SCHWELLE]


# --- A later chat round gets the same cure as the first ---------------------


class _ZuLangInDerZweitenRunde(MockProvider):
    """Answers the first request with a tool call, refuses the round after it
    the way a server refuses an answer ceiling that fills the window, and
    answers that same round once the ceiling comes down."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.grenzen: list[int | None] = []

    async def streamen(self, anfrage):
        self.letzte_anfrage = anfrage
        self.alle_anfragen.append(anfrage)
        self.grenzen.append(anfrage.max_tokens)
        if len(self.grenzen) == 1:
            yield Stueck("content", text="looking")
            yield Stueck(
                "tool_call",
                werkzeugaufrufe=[
                    Werkzeugaufruf(id="w1", name="addieren", argumente={"a": 1, "b": 2})
                ],
            )
            return
        if len(self.grenzen) == 2:
            raise ProviderFehler(
                f"provider answered with 400: {VLLM_ZU_GROSS}",
                status=400,
                rohtext=VLLM_ZU_GROSS,
            )
        yield Stueck("content", text="after the tool")


def test_chat_eine_spaetere_runde_senkt_die_grenze_statt_die_karte_zu_zeigen(mcp_client):
    """Until now only the first round of an answer was ever lowered:
    round one went out with the setting's own number again, was refused at
    once, and the answer ended with the context-full card. It gets the same
    cure the first round gets, and the same one a job's every round has had."""
    provider = provider_setzen(mcp_client, _ZuLangInDerZweitenRunde(mock_endpunkt("test")))
    mcp_client.app.state.werkzeuge = RegistryDouble()
    chat_id = _chat(mcp_client)

    senden(mcp_client, chat_id, max_tokens=8192)

    # The refusal names the window (8192) and the input (1200); the retry
    # takes what is left of it, less the margin.
    assert provider.grenzen == [8192, 8192, 8192 - 1200 - 64]
    antwort = _nachrichten(mcp_client, chat_id)[-1]
    assert antwort["content"] == "looking\n\nafter the tool"
    assert "kontextfenster_voll" not in antwort["stats"]


# --- Job --------------------------------------------------------------------


class _AuftragMitGrossenErgebnissen(MockProvider):
    """``runden`` tool rounds with a large result each, then one last answer.
    Every round reports the same reading, under the threshold on its own."""

    def __init__(self, *args, runden: int = 4, stand: int = UNTER_DER_SCHWELLE,
                 rundentext: str = RUNDENTEXT, **kwargs):
        super().__init__(*args, **kwargs)
        self.runden = runden
        self.stand = stand
        self.rundentext = rundentext
        self.echte_runden = 0
        self.faltungen = 0
        self.aufzeichnung: list[list[tuple[str, str]]] = []

    async def streamen(self, anfrage):
        self.letzte_anfrage = anfrage
        self.alle_anfragen.append(anfrage)
        letzte = anfrage.nachrichten[-1]
        if letzte.role == "user" and (letzte.content or "").startswith(
            verdichtung.ANFRAGE_TEXT
        ):
            self.faltungen += 1
            yield Stueck("content", text="summary")
            return
        self.aufzeichnung.append(
            [(n.role, n.content or "") for n in anfrage.nachrichten]
        )
        self.echte_runden += 1
        if self.echte_runden <= self.runden:
            yield Stueck("content", text=f"step {self.echte_runden} {self.rundentext}")
            yield Stueck("stats", daten={"nutzung": {"total_tokens": self.stand}})
            yield Stueck(
                "tool_call",
                werkzeugaufrufe=[
                    Werkzeugaufruf(
                        id=f"w{self.echte_runden}", name="riesig", argumente={}
                    )
                ],
            )
            return
        yield Stueck("content", text="done")
        yield Stueck("stats", daten={"nutzung": {"total_tokens": self.stand}})


def test_auftrag_kuerzt_vor_der_faltung(config, mcp_client):
    """The same step in a run: the protocol says what was cleared, and the
    run finishes without a summary ever being asked for."""
    agent_schreiben(config, kopf="model: test\nmax_rounds: 30")
    mcp_client.app.state.werkzeuge = GrossesErgebnis(gross=GROSS)
    provider = provider_setzen(
        mcp_client,
        _AuftragMitGrossenErgebnissen(mock_endpunkt("test"), runden=4),
    )
    mcp_client.app.state.discovery.zustaende["test"].context_tokens = FENSTER

    kennung = mcp_client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Go", "endpoint_id": "test"}
    ).json()["id"]
    daten = auf_ende_warten(mcp_client, kennung)

    assert daten["state"] == "fertig"
    assert provider.faltungen == 0
    schritte = [s["inhalt"] for s in daten["schritte"] if s["typ"] == "status"]
    assert any("old tool results" in s for s in schritte), schritte
    letzte = provider.aufzeichnung[-1]
    inhalte = [inhalt for _, inhalt in letzte]
    assert werkzeugkuerzung.PLATZHALTER in inhalte
    assert letzte[-1][0] == "tool"
    assert letzte[-1][1].endswith(GROSS)
    assert _paare_stimmen(letzte)


def test_auftrag_reicht_die_erste_stufe_nicht_wird_gefaltet(config, mcp_client):
    """Over the threshold on the reading alone: the run clears the results
    first and asks for a summary after all."""
    agent_schreiben(config, kopf="model: test\nmax_rounds: 30")
    mcp_client.app.state.werkzeuge = GrossesErgebnis(gross=GROSS)
    provider = provider_setzen(
        mcp_client,
        _AuftragMitGrossenErgebnissen(
            mock_endpunkt("test"), runden=4, stand=UEBER_DER_SCHWELLE
        ),
    )
    mcp_client.app.state.discovery.zustaende["test"].context_tokens = FENSTER

    kennung = mcp_client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Go", "endpoint_id": "test"}
    ).json()["id"]
    daten = auf_ende_warten(mcp_client, kennung)

    assert daten["state"] == "fertig"
    assert provider.faltungen >= 1
    schritte = [s["inhalt"] for s in daten["schritte"] if s["typ"] == "status"]
    assert any("old tool results" in s for s in schritte), schritte
    assert any("Compacted the history" in s for s in schritte), schritte
    assert _paare_stimmen(provider.aufzeichnung[-1])


def test_auftrag_die_kontextleiste_zeigt_die_zahl_des_ausloesers(
    config, mcp_client, monkeypatch
):
    """The context bar reads a job's last ``kontext`` step. When the trigger
    looks at the window, and again when the fold is asked for, that step
    carries the very number read there — not the one written after the
    answer, which cannot count the round's own tool results. Same run as
    above: the reading alone stands at 85 %, each result adds 32.5 points,
    and clearing old results brings the number down before the fold."""
    from app import kontextdruck, verdichtungswahl

    gelesen = []
    echt_prozent = kontextdruck.prozent

    def prozent_mitschreiben(letzter_stand, neu_tokens, fenster):
        wert = echt_prozent(letzter_stand, neu_tokens, fenster)
        if wert is not None:
            gelesen.append(wert)
        return wert

    repositories = mcp_client.app.state.repositories

    def leiste(auftrag_id: str) -> float:
        zeilen = [s for s in repositories.auftraege.schritte(auftrag_id) if s.typ == "kontext"]
        return json.loads(zeilen[-1].inhalt)["prozent"]

    # Every time the trigger is asked: the bar as it stands then, and the
    # share the trigger itself reads (the last total plus what is new,
    # against the whole window).
    am_ausloeser = []
    echt_schwelle = kontextdruck.ueber_der_schwelle
    laufende: list[str] = []

    def schwelle_mitschreiben(letzter_stand, neu_tokens, fenster, *rest, **benannt):
        if laufende and fenster:
            am_ausloeser.append(
                (
                    leiste(laufende[-1]),
                    round(100 * ((letzter_stand or 0) + neu_tokens) / fenster, 1),
                )
            )
        return echt_schwelle(letzter_stand, neu_tokens, fenster, *rest, **benannt)

    echt_lesen = verdichtungswahl.schwelle

    def read_threshold(repos, **kwargs):
        laufende.append(kwargs["chat"])
        return echt_lesen(repos, **kwargs)

    an_der_faltung = []
    echt_verdichten = verdichtung.verdichten

    async def verdichten_mitschreiben(zustand, anfrage, budget, *, schluessel, **kwargs):
        an_der_faltung.append((leiste(schluessel), round(gelesen[-1], 1)))
        return await echt_verdichten(zustand, anfrage, budget, schluessel=schluessel, **kwargs)

    monkeypatch.setattr(kontextdruck, "prozent", prozent_mitschreiben)
    monkeypatch.setattr(verdichtungswahl, "schwelle", read_threshold)
    monkeypatch.setattr(kontextdruck, "ueber_der_schwelle", schwelle_mitschreiben)
    monkeypatch.setattr(verdichtung, "verdichten", verdichten_mitschreiben)

    agent_schreiben(config, kopf="model: test\nmax_rounds: 30")
    mcp_client.app.state.werkzeuge = GrossesErgebnis(gross=GROSS)
    provider = provider_setzen(
        mcp_client,
        _AuftragMitGrossenErgebnissen(
            mock_endpunkt("test"), runden=4, stand=UEBER_DER_SCHWELLE
        ),
    )
    mcp_client.app.state.discovery.zustaende["test"].context_tokens = FENSTER

    kennung = mcp_client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Go", "endpoint_id": "test"}
    ).json()["id"]
    daten = auf_ende_warten(mcp_client, kennung)

    assert daten["state"] == "fertig"
    assert provider.faltungen >= 1
    assert am_ausloeser and an_der_faltung
    # The trigger read more than the answer's own reading, so a bar left on
    # that reading would show a different number here.
    assert max(ausloeser for _, ausloeser in am_ausloeser) > UEBER_DER_SCHWELLE * 100 / FENSTER
    assert all(zeile == ausloeser for zeile, ausloeser in am_ausloeser), am_ausloeser
    # The fold reads the number after old results were cleared, lower than
    # the trigger's, and the bar follows it there too.
    assert all(zeile == faltung for zeile, faltung in an_der_faltung), an_der_faltung
    assert max(f for _, f in an_der_faltung) < max(a for _, a in am_ausloeser)


def test_ein_ausgemustertes_bild_nimmt_das_versprechen_mit():
    """Five pictures read, the two oldest retired: their results drop the
    promise of an attachment and say nothing else — the path already stands
    once, in the message beside them.

    Both sentences used to sit in one request — the message said the
    picture was removed, the result next to it said "is attached below …
    Say what you see in it now", and the promise was the false one. Fixed
    that way, the path ended up doubled: this pass is why it does not.
    """
    nachrichten = [ChatNachricht(role="user", content="frage")]
    for nr in range(5):
        pfad = f"/ordner/bild{nr}.png"
        nachrichten.append(
            ChatNachricht(
                role="assistant",
                content="",
                werkzeugaufrufe=[
                    Werkzeugaufruf(
                        id=f"a{nr}", name="read_file", argumente={"path": pfad}
                    )
                ],
            )
        )
        nachrichten.append(
            ChatNachricht(
                role="tool",
                content=werkzeugbild.bildsatz(pfad, 4711),
                werkzeugaufruf_id=f"a{nr}",
            )
        )
        # The message the picture rides on comes AFTER the round's results —
        # the order both runs build (app/api/v1/generierung.py:2543,
        # app/api/v1/auftraege.py:2480).
        nachrichten.append(_bildzug(nr, pfad))

    # Everything in the protected end: the pictures are retired there all the
    # same, and it is exactly there that the two sentences met.
    neu, _ = werkzeugkuerzung.kuerzen(nachrichten, geschuetzt_ab=0)

    behalten = werkzeugkuerzung.WERKZEUGBILDER_BEHALTEN
    ergebnisse = [n for n in neu if n.role == "tool"]
    assert len(ergebnisse) == 5
    bildzeilen = [n for n in neu if n.content and n.content.startswith(werkzeugkuerzung.BILD_ENTFERNT)]

    for nr, n in enumerate(ergebnisse[: 5 - behalten]):
        assert werkzeugbild.ANHANG_SATZ not in (n.content or "")
        # The bare placeholder alone — the path stands once, in the message.
        assert n.content == werkzeugbild.NICHT_MEHR_DABEI
        assert f"/ordner/bild{nr}.png" in bildzeilen[nr].content
        assert "/ordner/bild" not in (n.content or "")

    for n in ergebnisse[5 - behalten :]:
        assert werkzeugbild.ANHANG_SATZ in (n.content or "")


def test_ein_abgelehntes_bild_behaelt_seinen_text():
    """Silence test: a read that was refused announced no picture at all, so
    its result is not rewritten — its own words stand."""
    pfad = "/ordner/bild0.png"
    nachrichten = [ChatNachricht(role="user", content="frage")]
    for nr in range(4):
        nachrichten.append(
            ChatNachricht(
                role="assistant",
                content="",
                werkzeugaufrufe=[
                    Werkzeugaufruf(
                        id=f"a{nr}", name="read_file", argumente={"path": f"/o/b{nr}.png"}
                    )
                ],
            )
        )
        nachrichten.append(
            ChatNachricht(
                role="tool",
                content=(
                    f"'{pfad}' cannot be shown to this model: it has no eyes."
                    if nr == 0
                    else werkzeugbild.bildsatz(f"/o/b{nr}.png", 4711)
                ),
                werkzeugaufruf_id=f"a{nr}",
            )
        )
        nachrichten.append(_bildzug(nr, f"/o/b{nr}.png"))

    neu, _ = werkzeugkuerzung.kuerzen(nachrichten, geschuetzt_ab=len(nachrichten))

    abgelehnt = [n for n in neu if n.role == "tool" and "no eyes" in (n.content or "")]
    assert len(abgelehnt) == 1
    assert werkzeugbild.NICHT_MEHR_DABEI not in abgelehnt[0].content


def test_dasselbe_bild_zweimal_gelesen_behaelt_das_neueste_versprechen():
    """The same file read twice: only the round whose picture was retired
    loses its promise.

    Pairing by file path instead of by round would rewrite the newest result
    too — it names the same file — and tell the model a picture is not in the
    request while that very picture rides right beside it. Read again in a
    later turn is exactly what ``ANHANG_SATZ`` asks for.
    """
    pfad = "/ordner/schirm.png"
    nachrichten = [ChatNachricht(role="user", content="frage")]
    for nr, name in enumerate([pfad, "/ordner/a.png", "/ordner/b.png", pfad]):
        nachrichten.append(
            ChatNachricht(
                role="assistant",
                content="",
                werkzeugaufrufe=[
                    Werkzeugaufruf(
                        id=f"a{nr}", name="read_file", argumente={"path": name}
                    )
                ],
            )
        )
        nachrichten.append(
            ChatNachricht(
                role="tool",
                content=werkzeugbild.bildsatz(name, 4711 + nr),
                werkzeugaufruf_id=f"a{nr}",
            )
        )
        nachrichten.append(_bildzug(nr, name))

    neu, _ = werkzeugkuerzung.kuerzen(nachrichten, geschuetzt_ab=0)

    ergebnisse = [n for n in neu if n.role == "tool"]
    bildzeilen = [n for n in neu if n.content and n.content.startswith(werkzeugkuerzung.BILD_ENTFERNT)]
    # Round 1's picture went — its result drops the promise, its message
    # says where the file is.
    assert werkzeugbild.ANHANG_SATZ not in (ergebnisse[0].content or "")
    assert ergebnisse[0].content == werkzeugbild.NICHT_MEHR_DABEI
    assert "/ordner/schirm.png" in bildzeilen[0].content
    # Round 4's picture is in the request — its promise stands.
    assert werkzeugbild.ANHANG_SATZ in (ergebnisse[3].content or "")
