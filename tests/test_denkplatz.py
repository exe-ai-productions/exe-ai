"""The live "reading context" clock (`frontend/src/App.svelte`, the waiting mark).

"Reading context" stands beside the waiting mark on the line while the
model works the grown context through — right after sending and again
after every tool result. It used to be hidden as soon as the answer had any
text, because text chunks set no activity of their own and the reading had
to guess "text exists, so it is writing". That guess also hid the clock
after a tool call in the middle of an answer, the very stretch it was built
for. Now writing is an activity of its own, and the reading alone decides.

The last section is a different matter that lives in this file all the
same: the answer that stood only in the thinking block.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import AsyncIterator

from app.providers import MockProvider, mock_endpunkt
from app.providers.base import Generierungsanfrage, Stueck, Werkzeugaufruf
from tests.conftest import provider_setzen


WURZEL = Path(__file__).resolve().parent.parent
FENSTER = (WURZEL / "frontend/src/App.svelte").read_text()


def test_ein_textstueck_setzt_die_taetigkeit_schreibt():
    zweig = re.search(
        r"else if \(ereignis\.typ === 'content'\) \{(.*?)\n        \} else if", FENSTER, re.S
    )
    assert zweig, "the content branch was not found"
    assert "taetigkeitSetzen(platzhalter, 'schreibt'" in zweig.group(1), (
        "a text chunk leaves the activity standing on the previous reading"
    )


def test_die_kontextuhr_haengt_nur_an_der_taetigkeit():
    # The behaviour — the context face with its own start, also once text
    # has been written — is run in node: tests/test_laufmarke.py. Here only
    # that the mark reads the activity at all.
    assert re.search(r"if \(zeile\.taetigkeit === 'kontext'[^\n]*kontext: true", FENSTER), (
        "the waiting mark no longer reads the context activity"
    )


def test_ein_werkzeugergebnis_stellt_die_uhr_neu():
    """After a tool result the model reads the grown context back through;
    the reading goes back to 'kontext' with a fresh start time — with the
    guard above gone, that is what puts the clock under the tool block of
    an answer that already has text."""
    # A fresh start even straight after another context read (`neu`); the
    # helper itself (lib/taetigkeit.js) is run in node: tests/test_laufmarke.py.
    stelle = FENSTER.find("taetigkeitSetzen(platzhalter, 'kontext', ereignis.zeitpunkt_ms, true)")
    assert stelle > 0, "a tool result no longer sets 'kontext' with its own start time"


# --- The answer that stood only in the thinking block ------------------------


def test_der_denktext_wird_die_antwort_wenn_das_modell_selbst_endet():
    """An answer that was thought but never written out.

    Measured on the installed program (1.9.1): a table over nine tool steps
    stood entirely in the thinking block, the answer text was empty. Whether
    the model, the server or the split in this module put it there is not
    measured — but whatever does it, the chat must not stay empty while the
    model produced an answer. It ended the answer itself ("stop"), so what it
    thought at the end is what it wanted to say.
    """
    from app.reasoning import denktext_als_antwort

    tabelle = "| Schritt | Werkzeug | Ergebnis |\n|---|---|---|\n| 1 | list_dir | drei Dateien |"

    antwort, gedanke = denktext_als_antwort(
        "", "", tabelle, schlusstext="", ende_grund="stop", zustand="fertig"
    )

    assert antwort == tabelle
    assert gedanke == ""


def test_nur_der_schlussgedanke_wechselt_die_seite():
    """Only the thought the answer ENDED on changes sides.

    ``gedanke`` is the whole run's thinking, ``schlussgedanke`` its tail.
    The deliberation of the rounds before ("erst in den Ordner schauen") was
    about work that had already been done; it stays in the thinking block
    and must not be shown as the answer, while the table thought last is
    exactly that.
    """
    from app.reasoning import denktext_als_antwort

    ueberlegung = "Erst schaue ich in den Ordner."
    tabelle = "| Schritt | 1 |"

    assert denktext_als_antwort(
        "",
        ueberlegung + tabelle,
        tabelle,
        schlusstext="",
        ende_grund="stop",
        zustand="fertig",
    ) == (tabelle, ueberlegung)


def test_das_ende_wird_wie_ueberall_im_haus_verglichen():
    """Anthropic's word and a server's capitals count as well.

    The end word is compared where the house compares it
    (app/antwortende.py): ``end_turn`` beside ``stop``, quietly lowercased
    and stripped — a Claude endpoint must not be left with the empty bubble
    this fixes.
    """
    from app.reasoning import denktext_als_antwort

    for wort in ("stop", "end_turn", "STOP", " end_turn "):
        assert denktext_als_antwort(
            "", "", "gedacht", schlusstext="", ende_grund=wort, zustand="fertig"
        ) == ("gedacht", "")


def test_jedes_andere_ende_laesst_alles_wie_es_war():
    """Silence probe: every other ending keeps the two apart.

    "length" or a full window means the model was cut off mid-thought — the
    half sentence must not be dressed up as an answer, and the run says in
    words where the length went (app/antwortende.py, `denken_aufgebraucht`).
    A run that was stopped or that failed is no finished answer whatever
    word its last reporting round left behind. And an answer with its own
    text has both halves in their place.
    """
    from app.reasoning import denktext_als_antwort

    for grund in ("length", "tool_calls", "model_context_window_exceeded", None, ""):
        assert denktext_als_antwort(
            "", "gedacht", "gedacht", schlusstext="", ende_grund=grund, zustand="fertig"
        ) == ("", "gedacht")
    for zustand in ("abgebrochen", "fehler"):
        assert denktext_als_antwort(
            "", "gedacht", "gedacht", schlusstext="", ende_grund="stop", zustand=zustand
        ) == ("", "gedacht")
    assert denktext_als_antwort(
        "Fertig.", "erst gedacht", "erst gedacht", schlusstext="Fertig.", ende_grund="stop",
        zustand="fertig",
    ) == ("Fertig.", "erst gedacht")
    assert denktext_als_antwort(
        "", "", "", schlusstext="", ende_grund="stop", zustand="fertig"
    ) == ("", "")


def test_die_schlussrunde_entscheidet_nicht_die_ganze_antwort():
    """A sentence an earlier round wrote before its tool call is no answer.

    Round one wrote "Ich schaue nach." and called a tool; the closing round
    thought the table and ended. The closing round wrote nothing, so its
    thought is the answer — one blank line behind the sentence, which stays
    where it stood. A closing round that WROTE something keeps everything
    as it was, whatever the earlier rounds wrote.
    """
    from app.reasoning import denktext_als_antwort

    vorspann = "Ich schaue nach.\n"
    ueberlegung = "Erst in den Ordner."
    tabelle = "| Tabelle |"

    assert denktext_als_antwort(
        vorspann,
        ueberlegung + tabelle,
        tabelle,
        schlusstext="",
        ende_grund="stop",
        zustand="fertig",
    ) == (vorspann + "\n" + tabelle, ueberlegung)
    assert denktext_als_antwort(
        vorspann + "Fertig.",
        ueberlegung + tabelle,
        tabelle,
        schlusstext="Fertig.",
        ende_grund="stop",
        zustand="fertig",
    ) == (vorspann + "Fertig.", ueberlegung + tabelle)
    assert denktext_als_antwort(
        vorspann,
        ueberlegung + tabelle,
        tabelle,
        schlusstext="",
        ende_grund="length",
        zustand="fertig",
    ) == (vorspann, ueberlegung + tabelle)


def test_the_lifted_answer_stands_a_blank_line_below_the_opening():
    """A table lifted behind "Ich schaue nach." stood on that sentence's
    line and was not drawn as a table: Markdown starts a new block only
    after a blank line. The lifted thought now starts one blank line below.
    """
    from app.reasoning import denktext_als_antwort

    tabelle = "| Schritt | 1 |\n|---|---|"
    assert denktext_als_antwort(
        "Ich schaue nach.", tabelle, tabelle, schlusstext="", ende_grund="stop",
        zustand="fertig",
    ) == ("Ich schaue nach.\n\n" + tabelle, "")


def test_an_opening_that_already_ends_with_a_blank_line_gets_no_second():
    """Silence probe: line breaks already there count towards the one blank
    line — on either side — and nothing is added before a first text."""
    from app.reasoning import denktext_als_antwort, paragraph_break

    assert denktext_als_antwort(
        "Ich schaue nach.\n\n", "| a |", "| a |", schlusstext="", ende_grund="stop",
        zustand="fertig",
    ) == ("Ich schaue nach.\n\n| a |", "")
    assert paragraph_break("Ich schaue nach.\n \n  ", "| a |") == ""
    assert paragraph_break("Ich schaue nach.", "\n| a |") == "\n"
    assert paragraph_break("Ich schaue nach.", "\n\n| a |") == ""
    assert paragraph_break("", "| a |") == ""
    assert paragraph_break("  \n", "| a |") == ""
    assert paragraph_break("Ich schaue nach.", "   ") == ""


class _Denker(MockProvider):
    """A model that thinks its answer and ends without writing one.

    The measured shape of the case: the stream carries `reasoning` chunks
    and no `content` at all, and the end reason is the model's own — it was
    DONE, it just never wrote the answer out. Every round is a tuple of
    (thinking, visible text, tool calls); the last one is the run's.
    """

    def __init__(self, *runden: tuple[str, str, list[Werkzeugaufruf]]) -> None:
        super().__init__(mock_endpunkt("test"))
        self.runden = list(runden)
        self.ende = "stop"
        self.aufrufe = 0

    async def streamen(self, anfrage: Generierungsanfrage) -> AsyncIterator[Stueck]:
        gedanke, text, aufrufe = self.runden[min(self.aufrufe, len(self.runden) - 1)]
        self.aufrufe += 1
        if gedanke:
            yield Stueck("reasoning", text=gedanke)
        if text:
            yield Stueck("content", text=text)
        if aufrufe:
            yield Stueck("tool_call", werkzeugaufrufe=aufrufe)
        yield Stueck(
            "stats",
            daten={
                "dauer_sekunden": 0.0,
                "haeppchen": 1,
                "ende_grund": self.ende,
                "endpunkt": self.id,
            },
        )


class _Werk:
    """The one tool the two-round script calls — answers at once, asks nothing."""

    def als_openai_werkzeuge(self, nur=None, shell_zeitgrenze=None, bild_fenster=None, **_options):
        return [{"type": "function", "function": {"name": "zaehlen", "parameters": {}}}]

    def braucht_bestaetigung(self, name, argumente=None, ordner=None):
        return False

    def server_von(self, name):
        return ""

    def bestaetigungsgrund(self, name, argumente=None, ordner=None):
        return ""

    async def ausfuehren(
        self, name, argumente, bild_senke=None, ordner=None, chat_id=None,
        shell_zeitgrenze=None, **_rest,
    ):
        return f"gezaehlt bis {argumente.get('n', 0)}"


def _eine_antwort(client, chat_id, modell) -> list[dict]:
    """One turn against the model double, and the events it announced.

    The double takes the place of the test endpoint's provider (the pattern
    the other generation tests use); the request names its endpoint, so
    nothing else has to be pointed anywhere.
    """
    provider_setzen(client, modell)
    antwort = client.post(
        "/api/v1/chat/completions",
        json={
            "chat_id": chat_id,
            "endpoint_id": "test",
            "content": "Wie viele Schritte waren es?",
        },
    )
    assert antwort.status_code == 200
    return [
        json.loads(z[5:].strip())
        for z in antwort.text.splitlines()
        if z.startswith("data:")
    ]


def _zeile(client, chat_id):
    return client.app.state.repositories.messages.auflisten(chat_id=chat_id)[-1]


def _closing_event(ereignisse: list[dict]) -> dict:
    """The one closing event of the stream — the `done`.

    It is what a window that is OPEN on this chat gets: the row below is
    read when the chat is opened, this one while it stands open
    (frontend/src/App.svelte).
    """
    schluss = [e for e in ereignisse if e.get("typ") == "done"]
    assert len(schluss) == 1, f"not one closing event, but {len(schluss)}: {schluss}"
    return schluss[0]


def test_der_chat_zeigt_den_denktext_als_antwort(client, chat_id):
    """The whole way, on the chat's own row and in the closing event.

    Nothing visible ever came over the stream — only `reasoning` — so the
    chat kept an empty answer while the model had produced the table. The row
    is what a window reads when it opens the chat; the closing event is what
    the window that stands open on it reads, and it carries the finished
    pair so that window can lift the answer out of the thinking block it
    drew, instead of showing it there until the chat is opened again.
    """
    tabelle = "| Schritt | Werkzeug | Ergebnis |\n| 1 | list_dir | drei Dateien |"
    ereignisse = _eine_antwort(client, chat_id, _Denker((tabelle, "", [])))

    assert any(e.get("typ") == "reasoning" for e in ereignisse), (
        "the thinking pieces are missing from the stream"
    )
    assert _zeile(client, chat_id).content == tabelle
    assert not _zeile(client, chat_id).reasoning
    fertig = _closing_event(ereignisse)
    assert fertig["content"] == tabelle, "the closing event lacks the lifted answer"
    assert not fertig.get("reasoning"), "the lifted thought still rides along as thinking"


def test_the_closing_event_stays_thin_for_a_written_answer(client, chat_id):
    """Silence probe on the same event: an answer that was written.

    Nothing changes hands there — the pieces already said it, and the
    closing line stands in the run's replay buffer and in the last fifty
    finished runs — so the event carries neither half, and the window has
    nothing to replace. A second thinking stretch after a paragraph stays
    where it happened.
    """
    gedanke = "Erst kurz überlegen."
    antwort = "Die Antwort steht sichtbar."
    ereignisse = _eine_antwort(client, chat_id, _Denker((gedanke, antwort, [])))

    gestreamt = "".join(e.get("text", "") for e in ereignisse if e.get("typ") == "content")
    assert gestreamt == antwort, "the pieces carry another answer than expected"
    fertig = _closing_event(ereignisse)
    assert "content" not in fertig
    assert "reasoning" not in fertig


def test_the_closing_branch_lifts_the_bubble_it_drew():
    """The wiring, where the rule itself runs in node.

    What `liftAnswer` does to the drawn stretches is pinned by
    `tests/test_answer_lift.py`; what nothing else holds is that THIS branch
    hands the pair to it — and that it hangs on the pair being there at all,
    because every written answer sends a closing event without one.
    """
    zweig = re.search(
        r"else if \(ereignis\.typ === 'done'\) \{(.*?)\n        \}\n      \}\n", FENSTER, re.S
    )
    assert zweig, "the done branch was not found in App.svelte"
    assert "typeof ereignis.content === 'string'" in zweig.group(1), (
        "the closing branch no longer asks whether the pair came along"
    )
    assert "platzhalter.abschnitte = " in zweig.group(1), (
        "the closing branch no longer replaces the stretches it drew"
    )
    assert "liftAnswer(" in zweig.group(1), (
        "the closing branch no longer lifts the answer out of the thinking"
    )


def test_die_ueberlegung_der_werkzeugrunde_bleibt_im_denkblock(client, chat_id):
    """Two rounds: only the thought the answer ENDED on changes sides.

    Round one deliberates and calls a tool; round two thinks the answer and
    ends. The deliberation is about work that had already been done — it
    stays the thinking block's, and the answer is the table alone.
    """
    ueberlegung = "Erst schaue ich in den Ordner."
    tabelle = "| Schritt | 1 |"
    client.app.state.werkzeuge = _Werk()
    client.app.state.config.features.mcp = True
    # tool_calls is undetermined until a real /props probe answers it — the
    # test endpoint never gets one, so the capability is pinned by hand.
    client.app.state.discovery.zustaende["test"].endpunkt.capabilities.tool_calls = True
    modell = _Denker(
        (ueberlegung, "", [Werkzeugaufruf(id="a1", name="zaehlen", argumente={"n": 1})]),
        (tabelle, "", []),
    )
    _eine_antwort(client, chat_id, modell)

    assert modell.aufrufe == 2, "there were not two rounds"
    assert _zeile(client, chat_id).content == tabelle
    assert _zeile(client, chat_id).reasoning == ueberlegung


def test_nach_einem_vorspann_kommt_die_gedachte_antwort_in_den_chat(client, chat_id):
    """Round one writes a sentence and calls a tool; round two only thinks.

    The closing round decides: it wrote nothing and ended itself, so the
    thought it ended on is the answer — one blank line behind the sentence,
    once. The
    deliberation of round one stays the thinking block's, and the closing
    event carries the pair the row was written with.
    """
    vorspann = "Ich schaue nach.\n"
    ueberlegung = "Erst schaue ich in den Ordner."
    tabelle = "| Schritt | 1 |"
    client.app.state.werkzeuge = _Werk()
    client.app.state.config.features.mcp = True
    client.app.state.discovery.zustaende["test"].endpunkt.capabilities.tool_calls = True
    modell = _Denker(
        (ueberlegung, vorspann, [Werkzeugaufruf(id="a1", name="zaehlen", argumente={"n": 1})]),
        (tabelle, "", []),
    )
    ereignisse = _eine_antwort(client, chat_id, modell)

    assert modell.aufrufe == 2, "there were not two rounds"
    assert _zeile(client, chat_id).content == vorspann + "\n" + tabelle
    assert _zeile(client, chat_id).reasoning == ueberlegung
    fertig = _closing_event(ereignisse)
    assert fertig["content"] == vorspann + "\n" + tabelle
    assert fertig["reasoning"] == ueberlegung


def test_ein_abgeschnittener_lauf_bleibt_wie_er_war(client, chat_id):
    """Silence probe on the same way: `length` with an empty answer changes
    nothing — the run was cut off mid-thought, the window says so in words,
    and the thinking stays where it is."""
    modell = _Denker(("angefangen zu denken", "", []))
    modell.ende = "length"
    _eine_antwort(client, chat_id, modell)

    assert _zeile(client, chat_id).content == ""
    assert _zeile(client, chat_id).reasoning == "angefangen zu denken"
