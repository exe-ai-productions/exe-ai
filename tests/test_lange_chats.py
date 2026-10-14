"""A chat past its five hundredth row — read by the window and by the model.

Both readings were capped at five hundred rows and both took the cap off the
WRONG END: `ORDER BY created_at ASC LIMIT 500` hands over the OLDEST five
hundred. The window therefore showed a long chat its beginning and silently
dropped its end, and the model answered the newest question out of a history
that stopped several hundred messages earlier.

Nothing in the program paged, so nothing ever fetched the rest — and the
features that grew fastest drove chats towards the cap hardest: compaction
deletes nothing and adds a summary row per fold, a finished background
command adds its report, a wake adds an answer.

The two readings are fixed differently on purpose, and the tests are in two
halves for that reason. The window gets the newest page and a count that says
how much of the chat it is. The model gets the newest stretch AND the pinned
opening `chatverdichtung._mitte_suchen` identifies by position, with a notice
standing in the gap between them — a history that starts mid-conversation
without saying so is one the model reasons over as if it were whole.
"""

from __future__ import annotations

from pathlib import Path

from app import chatverdichtung, verdichtung

WURZEL = Path(__file__).resolve().parent.parent


def _chat(client):
    return client.post("/api/v1/chats", json={"title": "Lang"}).json()["id"]


def _lange(repositories, chat_id, anzahl=600, fuellung=0):
    """A chat longer than one page — every row numbered, so a missing
    stretch can be named rather than merely counted.

    ``fuellung`` pads each row. The verbatim tail is a TOKEN budget
    (`verdichtung.LETZTE_ZEICHEN`), so six hundred rows of nine characters
    fit inside it whole and leave no middle at all — which says something
    about the budget and nothing about the question a test asking for a
    middle is asking.
    """
    return [
        repositories.messages.speichern(
            chat_id=chat_id,
            role="user" if nr % 2 == 0 else "assistant",
            content=f"Zeile {nr}" + ("." * fuellung),
        )
        for nr in range(anzahl)
    ]


# --- What the window reads -----------------------------------------------


def test_die_seite_bringt_das_ende_des_chats(client):
    """The page the window asks for is the one it is looking at.

    Before: no `limit`, no `offset`, so the route's own defaults applied and
    the answer was rows 0 to 499 of 600 — after a reload the hundred newest
    messages, the ones just typed, were the missing ones.
    """
    repositories = client.app.state.repositories
    chat_id = _chat(client)
    _lange(repositories, chat_id)

    seite = client.get(
        f"/api/v1/chats/{chat_id}/messages", params={"neueste": "true"}
    ).json()["nachrichten"]

    assert len(seite) == 500
    assert seite[-1]["content"] == "Zeile 599"
    assert seite[0]["content"] == "Zeile 100"


def test_die_seite_sagt_wie_lang_der_chat_ist(client):
    """A full page and a chat that is exactly one page long look identical
    from the body alone. That is how this stayed invisible for as long as it
    did, so the count travels beside the rows."""
    repositories = client.app.state.repositories
    chat_id = _chat(client)
    _lange(repositories, chat_id)

    antwort = client.get(
        f"/api/v1/chats/{chat_id}/messages", params={"neueste": "true"}
    )

    assert antwort.headers["X-Nachrichten-Gesamt"] == "600"
    assert len(antwort.json()["nachrichten"]) == 500


def test_eine_kurze_seite_wird_nicht_extra_gezaehlt(client):
    """A page with room left in it is the end of the chat, so the length is
    what was served — no second query for it. Every ordinary chat open paid
    that query for a number nobody read; only a full page leaves the
    question open, and only a full page asks it."""
    repositories = client.app.state.repositories
    chat_id = _chat(client)
    _lange(repositories, chat_id, anzahl=7)
    zaehlungen = []
    echt = repositories.messages.anzahl
    repositories.messages.anzahl = lambda **k: (zaehlungen.append(k), echt(**k))[1]

    antwort = client.get(f"/api/v1/chats/{chat_id}/messages", params={"neueste": "true"})

    assert antwort.headers["X-Nachrichten-Gesamt"] == "7"
    assert zaehlungen == [], "the short page was counted anyway"

    # And the page before a full one still reports the whole length.
    _lange(repositories, chat_id, anzahl=600)
    antwort = client.get(
        f"/api/v1/chats/{chat_id}/messages", params={"neueste": "true", "limit": 500}
    )
    assert antwort.headers["X-Nachrichten-Gesamt"] == "607"
    assert len(zaehlungen) == 1


def test_rueckwaerts_blaettern_bringt_die_seite_davor(client):
    """`offset` counts from the newest end when the page does — the handle a
    scroll-up pager needs, so growing one stays a change in the window."""
    repositories = client.app.state.repositories
    chat_id = _chat(client)
    _lange(repositories, chat_id)

    seite = client.get(
        f"/api/v1/chats/{chat_id}/messages",
        params={"neueste": "true", "limit": 100, "offset": 100},
    ).json()["nachrichten"]

    assert [z["content"] for z in seite] == [f"Zeile {nr}" for nr in range(400, 500)]


def test_die_alte_richtung_bleibt_die_alte(client):
    """Off by default. A caller that asks for nothing gets exactly what it
    got before — the flag is the window's choice, not a new house rule."""
    repositories = client.app.state.repositories
    chat_id = _chat(client)
    _lange(repositories, chat_id)

    seite = client.get(f"/api/v1/chats/{chat_id}/messages").json()["nachrichten"]

    assert seite[0]["content"] == "Zeile 0"
    assert seite[-1]["content"] == "Zeile 499"


def test_nichts_geht_verloren_beim_blaettern(client):
    """Two pages, and between them the whole chat — the cut is a reading,
    never a deletion."""
    repositories = client.app.state.repositories
    chat_id = _chat(client)
    _lange(repositories, chat_id)

    neu = client.get(
        f"/api/v1/chats/{chat_id}/messages", params={"neueste": "true"}
    ).json()["nachrichten"]
    alt = client.get(
        f"/api/v1/chats/{chat_id}/messages",
        params={"neueste": "true", "offset": 500},
    ).json()["nachrichten"]

    assert [z["content"] for z in alt + neu] == [f"Zeile {nr}" for nr in range(600)]


def test_die_antwort_eines_langen_chats_steht_auf_der_seite(client):
    """The row a run writes is the NEWEST row of the chat, and the window
    adopts a run by that row's id (`zustand.svelte.js`). Off the page, the
    id names nothing the window holds, the reattach finds no row to adopt
    and hangs a fresh placeholder beside the real answer — the one thing the
    id-based reattach was built to stop. So the page has to reach that far,
    and in a chat past five hundred rows it did not."""
    from app.providers import MockProvider
    from tests.conftest import provider_setzen

    repositories = client.app.state.repositories
    chat_id = _chat(client)
    _lange(repositories, chat_id)

    provider_setzen(client, MockProvider(haeppchen=["Antwort"]))
    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "Und nun?"},
    )

    seite = client.get(
        f"/api/v1/chats/{chat_id}/messages", params={"neueste": "true"}
    ).json()["nachrichten"]
    letzte = repositories.messages.letzte(chat_id=chat_id, role="assistant")
    assert any(z["id"] == letzte.id for z in seite)


def test_das_fenster_fragt_nach_der_neuesten_seite():
    """Source-text guard, like `test_der_verlauf_fuers_modell_liest_die
    _richtige_seite`: the route can only answer what it is asked, and the
    whole defect was a caller that asked for nothing and got the defaults.
    Nothing on either side looks wrong when it comes back."""
    quelle = (WURZEL / "frontend" / "src" / "lib" / "api.js").read_text()
    assert "neueste=true" in quelle, "the window fetches the oldest page again"
    assert "X-Nachrichten-Gesamt" in quelle, "the truncation is invisible again"


# --- What the model reads ------------------------------------------------


def test_das_modell_bekommt_das_ende_des_chats(client):
    """The newest rows are the ones the next answer is about.

    Before: rows 0 to 499 of 600 unfolded ones, so the question just asked
    was answered out of a history that ended a hundred messages earlier.
    """
    repositories = client.app.state.repositories
    chat_id = _chat(client)
    _lange(repositories, chat_id)

    zeilen = repositories.messages.fuer_das_modell(chat_id=chat_id)

    assert len(zeilen) == 500
    assert zeilen[-1].content == "Zeile 599"


def test_der_angeheftete_anfang_bleibt_der_anfang(client):
    """The other half of the same answer, and the reason it is not simply
    "the newest five hundred".

    `_mitte_suchen` never folds the first `ERSTE_FEST` rows, and it finds
    them BY POSITION in whatever this method returns. Handing back the newest
    N alone would put three arbitrary mid-conversation rows in that slot: the
    real opening would leave the model's view at row 501 for good, and
    compaction would pin a stretch it was never meant to pin.
    """
    repositories = client.app.state.repositories
    chat_id = _chat(client)
    _lange(repositories, chat_id)

    zeilen = repositories.messages.fuer_das_modell(chat_id=chat_id)

    assert [z.content for z in zeilen[: verdichtung.ERSTE_FEST]] == [
        f"Zeile {nr}" for nr in range(verdichtung.ERSTE_FEST)
    ]
    assert zeilen[-1].content == "Zeile 599"


def test_die_verdichtung_faltet_den_angehefteten_anfang_nicht(client):
    """The same fact asked of the function that depends on it: whatever
    `fuer_das_modell` puts in front, the middle must not reach it."""
    repositories = client.app.state.repositories
    chat_id = _chat(client)
    # Padded past the tail budget, or the boundary sits at zero and there is
    # no middle to ask the question about.
    _lange(repositories, chat_id, fuellung=300)

    zeilen = repositories.messages.fuer_das_modell(chat_id=chat_id)
    mitte = chatverdichtung._mitte_suchen(zeilen, [len(z.content) for z in zeilen])

    assert mitte, "there has to be a middle here, or the rest checks nothing"
    gefaltet = {z.id for z in mitte}
    for zeile in zeilen[: verdichtung.ERSTE_FEST]:
        assert zeile.id not in gefaltet
        assert zeile.content.startswith("Zeile ")
    # And the rows it pins really are the chat's own first ones.
    assert zeilen[0].content.startswith("Zeile 0.")


def test_die_luecke_sagt_sich_an(client):
    """A history that starts mid-conversation and does not admit it is a
    history the model reasons over as if it were whole."""
    repositories = client.app.state.repositories
    chat_id = _chat(client)
    _lange(repositories, chat_id)

    zeilen = repositories.messages.fuer_das_modell(chat_id=chat_id)
    hinweis = zeilen[verdichtung.ERSTE_FEST]

    assert hinweis.art == "verdichtung"
    # 600 rows, three pinned at the front, 496 at the back, one slot for the
    # notice itself — 101 are left out, and the notice says so.
    assert "101" in hinweis.content
    assert hinweis.created_at > zeilen[verdichtung.ERSTE_FEST - 1].created_at
    assert hinweis.created_at < zeilen[verdichtung.ERSTE_FEST + 1].created_at


def test_die_luecke_ist_keine_zeile_der_datenbank(client):
    """Built for one reading, never stored. Nothing about a chat being long
    may write to it."""
    repositories = client.app.state.repositories
    chat_id = _chat(client)
    _lange(repositories, chat_id)

    hinweis = repositories.messages.fuer_das_modell(chat_id=chat_id)[
        verdichtung.ERSTE_FEST
    ]

    assert repositories.messages.holen(hinweis.id) is None
    assert repositories.messages.anzahl(chat_id=chat_id) == 600
    alle = repositories.messages.auflisten(chat_id=chat_id, limit=2000)
    assert [z.content for z in alle] == [f"Zeile {nr}" for nr in range(600)]


def test_die_luecke_schliesst_sich_wieder(client):
    """The cap is a backstop, not the mechanism. Fold the chat down and the
    notice is simply not there any more — nobody has to clear it."""
    repositories = client.app.state.repositories
    chat_id = _chat(client)
    zeilen = _lange(repositories, chat_id)

    repositories.messages.verdichten(
        chat_id=chat_id,
        text="Zusammengefasst: die Mitte.",
        ersetzte_ids=[z.id for z in zeilen[3:400]],
    )

    fuers_modell = repositories.messages.fuer_das_modell(chat_id=chat_id)
    assert not any(z.id.startswith("luecke-") for z in fuers_modell)
    assert fuers_modell[0].content == "Zeile 0"
    assert fuers_modell[-1].content == "Zeile 599"


def test_eine_faltung_ueber_die_luecke_hinweg_beschaedigt_nichts(client):
    """The notice reaches `verdichten` whenever the middle spans the gap —
    it stands at exactly the position a middle starts at. There it names no
    row, so it folds nothing and stores nothing, and the summary's own count
    stays the count of the rows it really speaks for."""
    repositories = client.app.state.repositories
    chat_id = _chat(client)
    zeilen = _lange(repositories, chat_id)

    fuers_modell = repositories.messages.fuer_das_modell(chat_id=chat_id)
    hinweis = fuers_modell[verdichtung.ERSTE_FEST]
    echte = fuers_modell[verdichtung.ERSTE_FEST + 1 : verdichtung.ERSTE_FEST + 21]

    zusammenfassung = repositories.messages.verdichten(
        chat_id=chat_id,
        text="Zusammengefasst: zwanzig Zeilen.",
        ersetzte_ids=[hinweis.id, *(z.id for z in echte)],
    )

    assert zusammenfassung is not None
    assert repositories.messages.holen(hinweis.id) is None
    # 601 rows now: the 600 originals plus the summary. The notice added none.
    assert repositories.messages.anzahl(chat_id=chat_id) == 601
    gespeichert = [
        z
        for z in repositories.messages.auflisten(chat_id=chat_id, limit=2000)
        if z.id == zusammenfassung.id
    ][0]
    assert gespeichert.verdichtete_anzahl == len(echte)
    # And every folded row is still readable, which is the whole point.
    for zeile in zeilen:
        assert repositories.messages.holen(zeile.id) is not None


def test_die_zaehlung_der_gefalteten_zeilen_bleibt_im_chat(client):
    """The count of folded rows under a summary walked the WHOLE table:
    the subquery named the summary and not the chat. The statements the
    planner explains here are captured from the SHIPPED reader as it runs
    — a hand-typed copy once drifted from the product and explained SQL
    nobody ships."""
    repositories = client.app.state.repositories
    verbindung = repositories.messages.verbindung
    mitgeschnitten: list[tuple[str, tuple]] = []

    class _Mitschnitt:
        """The connection, with every SELECT written down as it passes."""

        def execute(self, sql, parameter=(), *rest):
            if isinstance(sql, str) and sql.lstrip().upper().startswith("SELECT"):
                mitgeschnitten.append((sql, tuple(parameter)))
            return verbindung.execute(sql, parameter, *rest)

        def __getattr__(self, name):
            return getattr(verbindung, name)

    import types

    echtes_db = repositories.messages.db
    repositories.messages.db = types.SimpleNamespace(verbindung=_Mitschnitt())
    try:
        repositories.messages.auflisten(chat_id="c", limit=5, neueste=True)
        repositories.messages.auflisten(chat_id="c")
    finally:
        repositories.messages.db = echtes_db

    zaehlungen = [
        (sql, parameter)
        for sql, parameter in mitgeschnitten
        if "verdichtet_in = m.id" in sql
    ]
    assert len(zaehlungen) >= 2, "the reader no longer asks the counted query"
    for sql, parameter in zaehlungen:
        plan = " ".join(
            zeile["detail"]
            for zeile in verbindung.execute(f"EXPLAIN QUERY PLAN {sql}", parameter)
        )
        assert "SEARCH g USING" in plan, plan
        assert "SCAN g" not in plan, plan
