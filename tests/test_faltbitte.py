"""What the "summarize this" request carries, and how wide it may get.

The tool calls travel with the words — a summary written without them
cannot say what a tool found, and after the fold that is gone from every
later prompt. Everything here is cut with a visible note, and nothing is
cut that fits.
"""

from __future__ import annotations

import re

from app import antwortgrenze, chatverdichtung, faltbitte, kontextvoll
from app.providers import ChatNachricht

# A window far wider than the ceiling: the request's width is decided by
# BITTE_MAX alone, exactly as before the window had a say.
GROSSES_FENSTER = 200_000


def test_aufruf_und_ergebnis_stehen_in_einer_zeile():
    """One line per call, in the order the calls were made: nobody reading
    the request has to pair a result with a call again."""
    text = faltbitte.werkzeug_fuer_bitte(
        [
            ("read_file", {"path": "a.py"}, "print(1)"),
            ("run_command", {"command": "ls"}, "a.py"),
        ],
        "Erledigt.",
    )
    zeilen = text.splitlines()
    assert zeilen[0] == faltbitte.KOPFZEILE
    assert zeilen[1] == '- read_file {"path": "a.py"} → print(1)'
    assert zeilen[2] == '- run_command {"command": "ls"} → a.py'
    assert text.endswith("Erledigt.")


def test_ohne_aufruf_bleibt_der_text_wie_er_war():
    """A caller may ask for every turn without knowing which used tools."""
    assert faltbitte.werkzeug_fuer_bitte([], "Nur Text.") == "Nur Text."


def test_eine_antwort_ohne_worte_bleibt_nicht_leer():
    """An answer that did nothing but call tools is a normal shape, and an
    empty message is refused by most servers."""
    text = faltbitte.werkzeug_fuer_bitte([("ls", {}, "a.py")], "")
    assert text.startswith(faltbitte.KOPFZEILE)
    assert text.endswith("→ a.py")


def test_ein_ergebnis_ohne_ausgabe_wird_benannt():
    text = faltbitte.werkzeug_fuer_bitte([("run_command", {"command": "true"}, "")], "")
    assert text.endswith(f"→ {faltbitte.OHNE_AUSGABE}")


def test_lange_argumente_werden_hinten_gekappt():
    """Arguments say what was asked for, and the front of them carries the
    path and the command — a write call's kilobytes of content sit behind
    that."""
    argumente = {"path": "a.py", "content": "y" * 5_000}
    text = faltbitte.werkzeug_fuer_bitte([("write_file", argumente, "ok")], "")
    zeile = text.splitlines()[1]
    assert '{"path": "a.py"' in zeile
    assert faltbitte.ARGUMENTE_VERMERK in zeile
    assert "y" * faltbitte.ARGUMENTE_KOPF not in zeile
    assert len(zeile) < faltbitte.ARGUMENTE_MAX + len(faltbitte.OHNE_AUSGABE) + 40


def test_ein_langes_ergebnis_wird_aus_der_mitte_gekappt():
    """The top says what the output is, the end says how it went — the
    middle is what goes, and it says that it went."""
    ergebnis = "A" * 4_000 + "M" * 90_000 + "Z" * 2_000
    text = faltbitte.werkzeug_fuer_bitte([("run_command", {}, ergebnis)], "")
    assert "A" * 1_000 in text
    assert "Z" * 1_000 in text
    assert faltbitte.ERGEBNIS_VERMERK in text
    assert "M" * (faltbitte.ERGEBNIS_MAX + 1) not in text
    assert len(text) < len(ergebnis)


def test_ein_kurzes_ergebnis_bleibt_unberuehrt():
    """The silence test for the per-call ceilings."""
    text = faltbitte.werkzeug_fuer_bitte([("run_command", {"command": "ls"}, "a.py")], "")
    assert faltbitte.ERGEBNIS_VERMERK not in text
    assert faltbitte.ARGUMENTE_VERMERK not in text


def test_eine_berichtszeile_geht_als_nutzerseite_in_die_faltung(client, chat_id):
    """A report is the SERVICE talking, and the fold hands it over exactly
    the way the conversation does — as the user's side of it.

    The row is stored as an assistant row so the window files it with the
    answer, but the model never said it. Read from that stored field it would
    reach the summarising model as its own words, and the summary would carry
    a report of the model's own making."""
    repositories = client.app.state.repositories
    repositories.messages.speichern(
        chat_id=chat_id, role="assistant", content="[report]", art="werkzeugmeldung"
    )
    zeile = repositories.messages.letzte(chat_id=chat_id)

    assert chatverdichtung.als_bitte(zeile, repositories).role == "user"


def test_eine_echte_antwort_bleibt_die_stimme_des_modells(client, chat_id):
    """Silence probe: a row the model really wrote keeps its own role in the
    fold, exactly as it does in the conversation."""
    repositories = client.app.state.repositories
    repositories.messages.speichern(chat_id=chat_id, role="assistant", content="Hallo")
    zeile = repositories.messages.letzte(chat_id=chat_id)

    assert chatverdichtung.als_bitte(zeile, repositories).role == "assistant"


def test_unter_dem_deckel_bleibt_die_bitte_wie_sie_war():
    """The silence test for the whole request: a request that was never too
    large is exactly the request the caller built — the same objects, not a
    rebuilt list."""
    nachrichten = [
        ChatNachricht(role="user", content="x" * 1_000),
        ChatNachricht(role="assistant", content="y" * 1_000),
    ]
    assert faltbitte.deckeln("kurz") == "kurz"
    assert faltbitte.gedeckelt(nachrichten, GROSSES_FENSTER) is nachrichten


def test_ueber_dem_deckel_geht_die_mitte_mit_vermerk():
    text = "A" * 100_000 + "M" * 400_000 + "Z" * 100_000

    gedeckelt = faltbitte.deckeln(text)

    assert len(gedeckelt) <= faltbitte.BITTE_MAX
    assert gedeckelt.startswith("A" * 1_000)
    assert gedeckelt.endswith("Z" * 1_000)
    # What the note claims is what is missing, so the model reads the seam
    # for what it is instead of reading two halves as one history.
    vermerk = re.search(r"\n\n…\[summary input truncated.*?\]…\n\n", gedeckelt, re.S)
    assert vermerk is not None
    genannt = int(
        re.search(r"omitted ([\d,]+) chars", vermerk.group(0)).group(1).replace(",", "")
    )
    assert genannt == len(text) - (len(gedeckelt) - len(vermerk.group(0)))


def test_eine_zu_grosse_bitte_wird_eine_nachricht_vor_der_bitte():
    """Over the ceiling there is no keeping the message borders AND the
    ceiling: what has to go is a stretch in the middle, and it does not
    stop at a border. So the history is written out with its roles into one
    message — and the ask behind it is never touched, whatever happens to
    the history in front of it."""
    frage = ChatNachricht(role="user", content="Summarize the conversation so far.")
    nachrichten = [
        ChatNachricht(role="user", content="A" * faltbitte.BITTE_MAX),
        ChatNachricht(role="assistant", content="M" * faltbitte.BITTE_MAX),
        frage,
    ]

    gedeckelt = faltbitte.gedeckelt(nachrichten, GROSSES_FENSTER)

    assert len(gedeckelt) == 2
    assert gedeckelt[1] is frage
    assert gedeckelt[0].role == "user"
    assert len(gedeckelt[0].content) <= faltbitte.BITTE_MAX
    assert gedeckelt[0].content.startswith("[USER]: A")
    assert "summary input truncated" in gedeckelt[0].content


def test_die_bilder_ueberleben_den_deckel():
    """A picture is not text and survives no collapse into text, so it has
    to be carried over — otherwise the same history reaches the summarizer
    with its pictures below the ceiling and without them above it."""
    nachrichten = [
        ChatNachricht(role="user", content="A" * faltbitte.BITTE_MAX),
        ChatNachricht(role="user", content="", bild_urls=["data:image/png;base64,QUJD"]),
        ChatNachricht(role="user", content="Summarize the conversation so far."),
    ]

    gedeckelt = faltbitte.gedeckelt(nachrichten, GROSSES_FENSTER)

    assert gedeckelt[0].bild_urls == ["data:image/png;base64,QUJD"]


def _langer_verlauf(frage: ChatNachricht) -> list[ChatNachricht]:
    """A history far wider than any window below, and the ask behind it."""
    return [
        ChatNachricht(role="user", content="A" * 150_000),
        ChatNachricht(role="assistant", content="Z" * 150_000),
        frage,
    ]


FRAGE = ChatNachricht(role="user", content="Summarize the conversation so far.")


def test_die_reserve_ist_ein_zwanzigstel_zwischen_boden_und_decke():
    """The summary's own room: 5 % of the window, never below 2,000 and never
    above 10,000 tokens."""
    assert faltbitte.reserve(8_192) == 2_000
    assert faltbitte.reserve(131_072) == 6_553
    assert faltbitte.reserve(262_144) == 10_000


def test_bei_grossem_fenster_bleibt_der_deckel_bitte_max():
    """The silence test for the window: where it holds more than the ceiling,
    the ceiling decides, and the request is cut exactly as before.

    `deckel` answers in TOKENS now and `deckel_zeichen` turns that into a
    length for the text in hand; `BITTE_MAX` is the ceiling on the length,
    so it is the second one that has to stop at it."""
    assert faltbitte.deckel(GROSSES_FENSTER, [FRAGE]) > faltbitte.BITTE_MAX
    assert (
        faltbitte.deckel_zeichen("x" * 10 * faltbitte.BITTE_MAX, 10**9)
        == faltbitte.BITTE_MAX
    )

    gedeckelt = faltbitte.gedeckelt(_langer_verlauf(FRAGE), GROSSES_FENSTER)

    assert gedeckelt is not None
    assert len(gedeckelt[0].content) == faltbitte.BITTE_MAX


def test_ohne_fenster_bleibt_der_deckel_bitte_max():
    """An endpoint that stopped answering has no window: the ceiling stands
    as it always did, and nothing is estimated in its place."""
    assert faltbitte.deckel(None, [FRAGE]) == faltbitte.BITTE_MAX

    gedeckelt = faltbitte.gedeckelt(_langer_verlauf(FRAGE), None)

    assert gedeckelt is not None
    assert len(gedeckelt[0].content) == faltbitte.BITTE_MAX


def test_ein_kleines_fenster_senkt_den_deckel_und_laesst_die_reserve_frei():
    """A window smaller than the ceiling lowers it — and what the request
    leaves of the window is at least the summary's reserve, not one token."""
    fenster = 32_768
    reserve = faltbitte.reserve(fenster)
    assert reserve == 2_000

    gedeckelt = faltbitte.gedeckelt(_langer_verlauf(FRAGE), fenster)

    assert gedeckelt is not None
    assert len(gedeckelt[0].content) < faltbitte.BITTE_MAX
    assert gedeckelt[1] is FRAGE
    eingabe = antwortgrenze.eingabe_schaetzen(gedeckelt)
    assert eingabe <= fenster - reserve - kontextvoll.SICHERHEITSABSTAND
    # Asked on the wire that carries a number: there the reserve is what the
    # summary gets written in. On the OpenAI wire no number goes out, and the
    # reserve is room left in the window.
    assert antwortgrenze.aufloesen(None, None, fenster, eingabe, anthropic=True) >= reserve
    assert antwortgrenze.reicht_nicht(None, None, fenster, eingabe, anthropic=True) is False
    assert antwortgrenze.aufloesen(None, None, fenster, eingabe, anthropic=False) is None


def test_der_vermerk_nennt_die_am_fenster_wirklich_ausgelassene_zahl():
    """The note under a lowered ceiling names what THAT ceiling left out,
    not what BITTE_MAX would have."""
    nachrichten = _langer_verlauf(FRAGE)
    ganz = "\n\n".join(f"[{n.role.upper()}]: {n.content}" for n in nachrichten[:-1])

    inhalt = faltbitte.gedeckelt(nachrichten, 16_384)[0].content

    vermerk = re.search(r"\n\n…\[summary input truncated.*?\]…\n\n", inhalt, re.S)
    assert vermerk is not None
    genannt = int(
        re.search(r"omitted ([\d,]+) chars", vermerk.group(0)).group(1).replace(",", "")
    )
    assert genannt == len(ganz) - (len(inhalt) - len(vermerk.group(0)))
    assert genannt > len(ganz) - faltbitte.BITTE_MAX


def test_was_sonst_mitreist_senkt_den_deckel():
    """The ask and the pictures travel in the same request, so the history
    gets what is left after them. The request offers no tools."""
    fenster = 32_768
    ohne = faltbitte.deckel(fenster, [FRAGE])
    mit_bild = faltbitte.deckel(
        fenster, [FRAGE, ChatNachricht(role="user", content="", bild_urls=["data:x"])]
    )

    assert mit_bild < ohne


def test_passt_kein_zeichen_verlauf_gibt_es_keine_bitte():
    """Where the window leaves the history not one character once the
    reserve is set aside, there is no request to send: the note alone would
    travel, and the model would summarize nothing."""
    assert faltbitte.deckel(2_048, [FRAGE]) == 0
    assert faltbitte.gedeckelt(_langer_verlauf(FRAGE), 2_048) is None

    # A window that leaves some history is asked as usual.
    gedeckelt = faltbitte.gedeckelt(_langer_verlauf(FRAGE), 4_096)
    assert gedeckelt is not None
    assert "A" in gedeckelt[0].content
