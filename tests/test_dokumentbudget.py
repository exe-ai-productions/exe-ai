"""How much of a document one request carries is the model's window, not a
number in the code (app/dokumentbudget.py).

A model with eight thousand tokens and one with a million used to get the
same eight pages. Now the budget is read off the window: the whole text
goes where it fits, and where it does not, nothing does — the model is told
what it holds.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from app import dokumentbudget, fenstergroesse
from app.db import Database, repositories_erstellen
from app.dokumentbudget import Anteil
from app.providers import MockProvider, ProviderFehler, mock_endpunkt
from app.verlaufsbau import zeilentext
from tests.conftest import provider_setzen


@dataclass
class _Dokument:
    id: str
    extracted_text: str


# --- The budget -----------------------------------------------------------


def test_das_budget_ist_das_fenster_minus_antwort_reserve_und_belegtem():
    # 8k window, 1k answer: 80 % of 8192 is 6553 tokens, minus 1000 for the
    # answer — 5553 tokens. Tokens all the way now: the old form multiplied
    # by four here and compared the answer against a character count.
    # Half the window (4096) is the smaller ceiling here, so THAT is
    # what actually applies — see the next test for
    # a case where the 80 % reckoning is still the smaller of the two.
    assert dokumentbudget.budget_tokens(8192, 1000) == 4_096
    assert dokumentbudget.budget_tokens(8192, 1000, belegt_tokens=553) == 4_096
    # A million-token window still carries at most half of it.
    assert dokumentbudget.budget_tokens(1_000_000, 4096) == 500_000
    assert dokumentbudget.budget_tokens(8192, 1000, belegt_tokens=10**9) == 0
    assert dokumentbudget.budget_tokens(8192, None) == 4_096


def test_der_antwortdeckel_frisst_nicht_das_ganze_fenster():
    """A ceiling somebody set by hand can be the whole window of a small
    model. Held back in full, nothing was left and every document — a
    500-character note included — travelled as a name. At most a quarter is
    held back."""
    assert dokumentbudget.budget_tokens(8192, 8192) == 4_096
    # Half of the window (4096) still binds here even after the answer
    # reserve and what is already held cut the 80 %-based number lower —
    # 6553 - 2048 - 750 = 3755, the smaller of the two ceilings.
    assert dokumentbudget.budget_tokens(8192, 9000, belegt_tokens=750) == 6553 - 2048 - 750
    # A ceiling below the quarter is held back as it is — still capped by
    # the half-window ceiling (50,000), the smaller of the two here too.
    assert dokumentbudget.budget_tokens(100_000, 4096) == 50_000


def test_die_haelfte_des_fensters_gilt_nur_wenn_sie_die_kleinere_ist():
    """The half-window ceiling is a SECOND limit, not a
    replacement — where the 80 %-based reckoning is already smaller (a
    request that already holds a lot of the window), that number still
    wins — whichever of the two numbers is smaller applies."""
    # 80 % of 100,000 minus the answer minus what is already held: 80,000 -
    # 4,096 - 70,000 = 5,904 — well under half the window (50,000).
    assert dokumentbudget.budget_tokens(100_000, 4096, belegt_tokens=70_000) == 5_904


# --- The plan -------------------------------------------------------------


def test_was_passt_geht_ganz():
    # 10,000 ASCII characters are 2,500 tokens — measured, not divided.
    plan = dokumentbudget.verteilen([_Dokument("a", "x" * 10_000)], 5_000)
    assert plan == {"a": Anteil(ganz=True)}
    assert plan["a"].tokens(2_500) == 2_500


def test_ein_kleines_dokument_geht_immer_ganz():
    """Naming it would cost about as much as sending it."""
    plan = dokumentbudget.verteilen([_Dokument("a", "x" * 500)], 0)
    assert plan == {"a": Anteil(ganz=True)}
    plan = dokumentbudget.verteilen(
        [_Dokument("a", "x" * (dokumentbudget.IMMER_GANZ_TOKENS * 4))], 0
    )
    assert plan == {"a": Anteil(ganz=True)}


def test_unter_dem_boden_wird_nur_benannt():
    plan = dokumentbudget.verteilen([_Dokument("a", "x" * 300_000)], 500)
    assert plan["a"] == Anteil(ganz=False)
    assert plan["a"].tokens(75_000) == 0


def test_das_neueste_dokument_kommt_zuerst_dran():
    """The caller hands the newest first, and the first takes the budget."""
    neu = _Dokument("neu", "x" * 15_000)
    alt = _Dokument("alt", "x" * 15_000)
    # 3,750 tokens each: the first fits, the second does not.
    plan = dokumentbudget.verteilen([neu, alt], 5_000)
    assert plan["neu"] == Anteil(ganz=True)
    assert plan["alt"] == Anteil(ganz=False)
    assert plan["alt"].tokens(3_750) == 0


def test_ein_leeres_dokument_kostet_nichts():
    assert dokumentbudget.verteilen([_Dokument("a", "")], 0) == {"a": Anteil(ganz=True)}


# --- The weight -----------------------------------------------------------


def test_der_beitrag_folgt_dem_plan():
    dokument = _Dokument("a", "x" * 300_000)
    # No plan at all — a caller with no documents in hand — costs nothing,
    # same as a plan that simply does not mention this document.
    assert dokumentbudget.beitrag(dokument, None) == 0
    assert dokumentbudget.beitrag(dokument, {"a": Anteil(ganz=True)}) == 75_000
    assert dokumentbudget.beitrag(dokument, {}) == 0
    assert dokumentbudget.beitrag(dokument, {"a": Anteil(ganz=False)}) == 0


# --- What the model is handed ---------------------------------------------


def _repos(tmp_path):
    db = Database(tmp_path / "d.db")
    db.schema_einrichten()
    return repositories_erstellen(db)


def _zeile_mit_dokument(repos, text):
    chat = repos.chats.erstellen(user_id="u1", title="c")
    dokument = repos.documents.speichern(
        chat_id=chat.id,
        filename="bericht.pdf",
        mime_type="application/pdf",
        size_bytes=len(text),
        extracted_text=text,
        pages=120,
    )
    repos.messages.speichern(
        chat_id=chat.id, role="user", content="Fasse zusammen.", dokumente=[dokument.id]
    )
    return repos.messages.auflisten(chat_id=chat.id)[-1], dokument


def test_mit_plan_geht_der_ganze_text(tmp_path):
    repos = _repos(tmp_path)
    zeile, dokument = _zeile_mit_dokument(repos, "A" * 300_000)
    text = zeilentext(zeile, repos, dokumentplan={dokument.id: Anteil(ganz=True)})
    assert text.startswith('[Attached document "bericht.pdf"]')
    assert "A" * 300_000 in text
    assert "TRUNCATED" not in text


def test_ohne_fassung_und_ohne_passagen_wird_das_dokument_benannt(tmp_path):
    repos = _repos(tmp_path)
    zeile, dokument = _zeile_mit_dokument(repos, "A" * 300_000)
    plan = {dokument.id: Anteil(ganz=False)}
    text = zeilentext(zeile, repos, dokumentplan=plan)
    assert (
        'contains 300000 characters, is too large to be sent with this request, and is not included here'
        in text
    )
    assert "Explain this rather than answering as though you had read it" in text
    assert "A" * 100 not in text
    assert text.endswith("Fasse zusammen.")


def test_ein_dokument_ohne_eintrag_im_plan_wird_benannt(tmp_path):
    """A plan made for other documents says nothing about this one — read
    the same safe way as one the plan explicitly says is too large."""
    repos = _repos(tmp_path)
    zeile, dokument = _zeile_mit_dokument(repos, "A" * 300_000)
    text = zeilentext(zeile, repos, dokumentplan={})
    assert (
        'contains 300000 characters, is too large to be sent with this request, and is not included here'
        in text
    )
    assert "A" * 100 not in text


# --- The answer path, end to end ------------------------------------------


def _hochladen(client, chat_id, name, text) -> str:
    antwort = client.post(
        f"/api/v1/documents?chat_id={chat_id}&name={name}", content=text.encode()
    )
    assert antwort.status_code == 201, antwort.text
    return antwort.json()["dokument"]["id"]


def _fragen(client, chat_id, kennung, frage="Fasse zusammen."):
    antwort = client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": frage, "dokumente": [kennung]},
    )
    assert antwort.status_code == 200, antwort.text
    return antwort


def _nutzertext(provider) -> str:
    nutzer = [n for n in provider.letzte_anfrage.nachrichten if n.role == "user"]
    inhalt = nutzer[-1].content
    return inhalt if isinstance(inhalt, str) else str(inhalt)


def test_im_antwortpfad_reist_ein_kleines_dokument_ganz(client, chat_id):
    """An 8k window with the shipped 8192-token answer ceiling: the note
    still travels whole, not as a name."""
    provider = provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["ok"]))
    client.app.state.discovery.zustaende["test"].context_tokens = 8192
    kennung = _hochladen(client, chat_id, "notiz.md", " ".join(["Kurze Notiz."] * 40))

    _fragen(client, chat_id, kennung)

    text = _nutzertext(provider)
    # The date block sits in front of the turn
    # (app/grundprompt.environment_block) — the document itself is what this
    # test is about.
    assert text.startswith("<environment_context>")
    assert '[Attached document "notiz.md"]' in text
    assert " ".join(["Kurze Notiz."] * 40) in text
    assert "TRUNCATED" not in text


# --- What the card says the answer carried ---------------------------------


def _karte(client, chat_id) -> dict:
    """The card of the first question that carries a document, as the
    message list hands it to the window."""
    antwort = client.get(f"/api/v1/chats/{chat_id}/messages")
    assert antwort.status_code == 200, antwort.text
    return next(
        n["dokument"]
        for n in antwort.json()["nachrichten"]
        if n["role"] == "user" and n["dokument"]
    )


def _done(antwort) -> dict:
    ereignisse = [
        json.loads(zeile[len("data: "):])
        for zeile in antwort.text.splitlines()
        if zeile.startswith("data: ")
    ]
    return next(e for e in ereignisse if e["typ"] == "done")


def _getragen(antwort) -> list[dict]:
    """What `done` reports each row it wrote about carried.

    The words without the row ids, which are made fresh for every chat — so
    the length of this list is also how many rows the answer wrote onto.
    """
    return list(_done(antwort)["dokumente"].values())


def test_die_karte_sagt_kein_platz_wenn_es_zu_gross_ist(client, chat_id):
    """A window above the line and 320 000 characters: too big for the
    budget, so the card of the question says the document did not travel —
    in the list and in `done`."""
    provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["ok"]))
    client.app.state.discovery.zustaende["test"].context_tokens = 65_536
    hochgeladen = client.post(
        f"/api/v1/documents?chat_id={chat_id}&name=buch.md", content=("x" * 320_000).encode()
    )
    assert hochgeladen.json()["dokument"]["getragen"] is None
    kennung = hochgeladen.json()["dokument"]["id"]

    antwort = _fragen(client, chat_id, kennung)

    assert _karte(client, chat_id)["getragen"] == "kein_platz"
    assert _getragen(antwort) == [{kennung: "kein_platz"}]


def test_zu_grosses_dokument_traegt_keinen_text_in_den_prompt(client, chat_id):
    """The prompt for a document too big for the window carries neither its
    text nor a passage of it — only the sentence that says it is missing."""
    provider = provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["ok"]))
    client.app.state.discovery.zustaende["test"].context_tokens = 65_536
    kennung = _hochladen(client, chat_id, "buch.md", "x" * 320_000)

    antwort = _fragen(client, chat_id, kennung)

    text = _nutzertext(provider)
    assert "x" * 100 not in text
    assert "not included here" in text
    assert "Explain this rather than answering as though you had read it" in text
    assert provider.durchlaeufe == 1
    assert _getragen(antwort) == [{kennung: "kein_platz"}]


def test_hochladen_loest_keine_einbettung_mehr_aus(client, chat_id):
    """Uploading extracts the text and nothing else — no section search is
    triggered, and the card carries no section count."""
    antwort = client.post(
        f"/api/v1/documents?chat_id={chat_id}&name=buch.md", content=b"x" * 5_000
    )
    assert antwort.status_code == 201, antwort.text
    karte = antwort.json()["dokument"]
    assert "abschnitte" not in karte
    assert not hasattr(client.app.state.repositories, "abschnitte")


def test_die_karte_sagt_ganz(client, chat_id):
    provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["ok"]))
    client.app.state.discovery.zustaende["test"].context_tokens = 8192
    kennung = _hochladen(client, chat_id, "notiz.md", "n" * 500)

    antwort = _fragen(client, chat_id, kennung)

    assert _karte(client, chat_id)["getragen"] == "ganz"
    assert _getragen(antwort) == [{kennung: "ganz"}]


def test_60_prozent_des_fensters_geht_nicht_mehr_ganz_40_prozent_schon(client):
    """The half-window ceiling: a document at 60 % of
    the window used to travel whole — the 80 %-based budget alone had room
    — and now does not; one at 40 % still does. Two separate chats, the
    same way every other single-document test in this file works."""
    provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["ok"]))
    client.app.state.discovery.zustaende["test"].context_tokens = 100_000

    zu_gross_chat = client.post("/api/v1/chats", json={"title": "60%"}).json()["id"]
    zu_gross = _hochladen(client, zu_gross_chat, "sechzig.md", "x" * (4 * 60_000))
    antwort = _fragen(client, zu_gross_chat, zu_gross)
    assert _karte(client, zu_gross_chat)["getragen"] == "kein_platz"
    assert _getragen(antwort) == [{zu_gross: "kein_platz"}]

    passt_chat = client.post("/api/v1/chats", json={"title": "40%"}).json()["id"]
    passt = _hochladen(client, passt_chat, "vierzig.md", "y" * (4 * 40_000))
    antwort = _fragen(client, passt_chat, passt)
    assert _karte(client, passt_chat)["getragen"] == "ganz"
    assert _getragen(antwort) == [{passt: "ganz"}]


def test_die_karte_sagt_kein_platz_wenn_der_verlauf_das_fenster_fuellt(client, chat_id):
    """A conversation that already fills the 8k window leaves no room at
    all: the document is only named."""
    provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["ok"]))
    client.app.state.discovery.zustaende["test"].context_tokens = 8192
    repos = client.app.state.repositories
    repos.messages.speichern(chat_id=chat_id, role="user", content="v" * 30_000)
    repos.messages.speichern(chat_id=chat_id, role="assistant", content="ok")
    kennung = _hochladen(client, chat_id, "buch.md", "x" * 320_000)

    _fragen(client, chat_id, kennung)

    assert _karte(client, chat_id)["getragen"] == "kein_platz"


def test_die_karte_sagt_kein_platz_wenn_das_verdichten_scheitert(client, chat_id):
    """A document too big for the window costs the answer exactly one
    request — nothing tries to make a condensed version of it any more, so
    there is nothing left that could fail at that."""
    provider = provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["ok"]))
    client.app.state.discovery.zustaende["test"].context_tokens = 65_536
    kennung = _hochladen(client, chat_id, "buch.md", "x" * 320_000)

    _fragen(client, chat_id, kennung)

    assert provider.durchlaeufe == 1
    assert _karte(client, chat_id)["getragen"] == "kein_platz"


def test_ein_anderes_fenster_aendert_das_wort(client, chat_id):
    """The card follows the latest answer: the same question row says
    "too large" after a 64k answer and "whole" after a 256k one."""
    provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["ok"]))
    zustand = client.app.state.discovery.zustaende["test"]
    zustand.context_tokens = 65_536
    kennung = _hochladen(client, chat_id, "buch.md", "x" * 320_000)
    _fragen(client, chat_id, kennung)
    assert _karte(client, chat_id)["getragen"] == "kein_platz"

    zustand.context_tokens = 262_144
    antwort = client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "Und jetzt?"},
    )
    assert antwort.status_code == 200, antwort.text

    assert _karte(client, chat_id)["getragen"] == "ganz"


def test_done_nennt_nur_die_zeile_die_diese_antwort_beschrieben_hat(client, chat_id):
    """`done` says which ROW each word belongs to, and names only the rows
    this request actually sent.

    A folded row is left out of the request (`fuer_das_modell`), so no word
    is written onto it and it keeps the one the last answer that DID carry
    the document left there. Reported flat, by document id alone, the map
    said a word without saying whose row it was — and the window laid it
    over every card of the chat carrying that document, the folded one
    included. Its card then said what the NEW answer carried, until the
    next reload put the stored word back.
    """
    provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["ok"]))
    zustand = client.app.state.discovery.zustaende["test"]
    zustand.context_tokens = fenstergroesse.ERSATZ
    kennung = _hochladen(client, chat_id, "buch.md", "x" * 100_000)

    _fragen(client, chat_id, kennung, frage="Erste Frage.")

    repos = client.app.state.repositories
    alt = next(
        z
        for z in repos.messages.auflisten(chat_id=chat_id)
        if z.role == "user" and kennung in z.dokument_ids()
    )
    assert repos.messages.holen(alt.id).stats["dokumente"] == {kennung: "ganz"}
    repos.messages.verdichten(
        chat_id=chat_id, text="Was bisher geschah.", ersetzte_ids=[alt.id]
    )

    # The same document again, in a window that cannot carry it whole any
    # more: the new row's word differs from the folded row's.
    zustand.context_tokens = 16_384
    antwort = _fragen(client, chat_id, kennung, frage="Zweite Frage.")

    neu = next(
        z
        for z in reversed(repos.messages.auflisten(chat_id=chat_id))
        if z.role == "user" and kennung in z.dokument_ids()
    )
    assert neu.id != alt.id
    dokumente = _done(antwort)["dokumente"]
    assert set(dokumente) == {neu.id}
    assert dokumente[neu.id] == {kennung: "kein_platz"}
    # Untouched in the table, and so the card must stay untouched too.
    assert repos.messages.holen(alt.id).stats["dokumente"] == {kennung: "ganz"}


def test_der_dokumentstand_laesst_die_anderen_messwerte_stehen(tmp_path):
    repos = _repos(tmp_path)
    chat = repos.chats.erstellen(user_id="u1", title="c")
    werkzeuge = [{"name": "shell", "lauf_nummer": 3}]
    zeile = repos.messages.speichern(
        chat_id=chat.id, role="user", content="q", stats={"werkzeuge": werkzeuge, "ziel": "x"}
    )

    repos.messages.dokumentstand_setzen(zeile.id, {"d1": "ganz", "d2": "kein_platz"})
    repos.messages.dokumentstand_setzen(zeile.id, {"d1": "kein_platz"})

    assert repos.messages.holen(zeile.id).stats == {
        "werkzeuge": werkzeuge,
        "ziel": "x",
        "dokumente": {"d1": "kein_platz"},
    }


def test_unlesbare_messwerte_bleiben_wie_sie_sind(tmp_path):
    """A blob that is not JSON is skipped and left alone, not repaired."""
    repos = _repos(tmp_path)
    chat = repos.chats.erstellen(user_id="u1", title="c")
    zeile = repos.messages.speichern(chat_id=chat.id, role="user", content="q")
    repos.messages.verbindung.execute(
        "UPDATE messages SET stats_json = ? WHERE id = ?", ("{kaputt", zeile.id)
    )

    repos.messages.dokumentstand_setzen(zeile.id, {"d1": "ganz"})

    roh = repos.messages.verbindung.execute(
        "SELECT stats_json FROM messages WHERE id = ?", (zeile.id,)
    ).fetchone()["stats_json"]
    assert roh == "{kaputt"


# --- Below the line: no window, still no condensing -------------------------


def test_im_kleinmodus_wird_nicht_verdichtet(client, chat_id):
    """A small window gets no special treatment: the document is simply
    named, in one request, exactly like a large window that does not fit it
    either."""
    provider = provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["ok"]))
    client.app.state.discovery.zustaende["test"].context_tokens = 8192
    kennung = _hochladen(client, chat_id, "buch.md", "x" * 320_000)

    antwort = _fragen(client, chat_id, kennung)

    assert provider.durchlaeufe == 1, "only the answer itself"
    assert _karte(client, chat_id)["getragen"] == "kein_platz"
    assert _getragen(antwort) == [{kennung: "kein_platz"}]


def test_der_ersatzwert_traegt_ein_dokument_ganz_bis_es_gelernt_wird(client, chat_id):
    """A cloud model that never reports a window is no longer 'small' —
    the fallback (app/fenstergroesse.py, 128,000) gives it as much room as
    any other model with a number nobody confirmed. Learning a smaller,
    real window later (a 'too long' refusal) shrinks that room, and the
    very same document that went in whole now does not fit."""
    provider = provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["ok"]))
    zustand = client.app.state.discovery.zustaende["test"]
    zustand.context_tokens = fenstergroesse.ERSATZ
    zustand.kontext_quelle = fenstergroesse.QUELLE_ERSATZ
    kennung = _hochladen(client, chat_id, "buch.md", "x" * 100_000)

    _fragen(client, chat_id, kennung)

    assert provider.durchlaeufe == 1
    assert _karte(client, chat_id)["getragen"] == "ganz"

    zustand.context_tokens = 16_384
    zustand.kontext_quelle = fenstergroesse.QUELLE_GELERNT
    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "Und jetzt?"},
    )

    assert _karte(client, chat_id)["getragen"] == "kein_platz"


def test_bei_auto_haelt_die_tuer_nichts_extra_frei():
    """"Auto" IS what is left over (app/antwortgrenze.py) — holding a share
    back for it would spend the same room twice. A ceiling somebody named is
    held back as before, up to a quarter of the window. Both land on
    the half-window ceiling (50,000) here, the smaller of the two."""
    # Nothing set: only the reserve comes off, then the half-window ceiling.
    assert dokumentbudget.budget_tokens(100_000, None) == 50_000
    # Set to 4,000: still capped the same way.
    assert dokumentbudget.budget_tokens(100_000, 4_000) == 50_000


def test_ohne_abschnitte_bleibt_es_kein_platz(client, chat_id):
    """Too large for the window: the model knows only the name, and the
    card says so."""
    provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["ok"]))
    client.app.state.discovery.zustaende["test"].context_tokens = 8192
    kennung = _hochladen(client, chat_id, "buch.md", "x" * 320_000)

    _fragen(client, chat_id, kennung)

    assert _karte(client, chat_id)["getragen"] == "kein_platz"


# --- The card does not lie ------------------------------------------------


class _LehntImmerAb(MockProvider):
    """Refuses every request the way a server refuses one that is too long
    for its window — the measured sentence, word for word."""

    ROHTEXT = (
        '{"detail":"Prompt too long: 308703 tokens exceeds max context '
        'window of 262144 tokens"}'
    )

    async def streamen(self, anfrage):
        raise ProviderFehler(
            f"provider answered with 400: {self.ROHTEXT}",
            status=400,
            rohtext=self.ROHTEXT,
        )
        yield  # pragma: no cover - never reached, keeps this a generator


def test_die_karte_nimmt_zurueck_was_der_anbieter_ablehnt(client, chat_id):
    """As measured: the turn said "the answer failed" and "context
    window is full", and the card above it said "whole in the context". The
    state is written BEFORE the request goes out, so it is a plan — and
    nothing took it back when the plan turned out to be wrong."""
    provider_setzen(client, _LehntImmerAb(mock_endpunkt("test")))
    kennung = _hochladen(client, chat_id, "bericht.md", "x" * 2_000)

    _fragen(client, chat_id, kennung)

    assert _karte(client, chat_id)["getragen"] == "abgelehnt"


def test_ohne_ablehnung_bleibt_die_karte_stehen(client, chat_id):
    """The silence probe: an answer that came back leaves the card saying
    what the request really carried."""
    provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["ok"]))
    kennung = _hochladen(client, chat_id, "bericht.md", "x" * 2_000)

    _fragen(client, chat_id, kennung)

    assert _karte(client, chat_id)["getragen"] == "ganz"


def test_eine_html_datei_geht_den_gleichen_weg_wie_md(client, chat_id):
    """An uploaded .html carries its text into the request where it fits —
    and where it does not, the card says "too large" and nothing of its
    text travels, exactly like every other document."""
    provider = provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["ok"]))
    client.app.state.discovery.zustaende["test"].context_tokens = 8192
    seite = "<html><body>Das Buch steht im Regal Nummer sieben.</body></html>"
    kennung = _hochladen(client, chat_id, "seite.html", seite)

    _fragen(client, chat_id, kennung)

    text = _nutzertext(provider)
    assert '[Attached document "seite.html"]' in text
    assert "Das Buch steht im Regal Nummer sieben." in text
    assert _karte(client, chat_id)["getragen"] == "ganz"

    gross_chat = client.post("/api/v1/chats", json={"title": "gross"}).json()["id"]
    client.app.state.discovery.zustaende["test"].context_tokens = 65_536
    gross = _hochladen(client, gross_chat, "riesig.html", "x" * 320_000)

    antwort = _fragen(client, gross_chat, gross)

    assert _karte(client, gross_chat)["getragen"] == "kein_platz"
    assert _getragen(antwort) == [{gross: "kein_platz"}]
    assert "x" * 100 not in _nutzertext(provider)
