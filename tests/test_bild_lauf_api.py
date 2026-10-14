"""Images per run: several pictures from one draw, ONE answer for the
whole run (it replaced the earlier shape, which put each
picture in its own message and needed a chain of fixes just to keep a
run's own question and count honest — every one of them rooted in that
one row-per-picture choice).

The window still issues one real request per picture — a client-driven
design, one request, one picture — but this route now writes every
picture of a run into the SAME answer row instead of a new one each
time: ``bilder`` (Wanderung 19), a JSON array indexed by the picture's
own ``nr``, not by arrival order. A single picture (the default,
``von=1``) is entirely unaffected: it never gets a ``lauf_kennung`` at
all (see ``bild.py``'s own von>1 check) and writes byte-identical rows
to before this field existed.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from PIL import Image
from PIL.PngImagePlugin import PngInfo

from app import draw_input, image_switches, model_image, paste_back
from app.bildrunner import BildFehler, Bildrunner
from app.config import Config
from app.speicherorte import ort


@pytest.fixture
def bild_senden(config: Config, client: TestClient, monkeypatch, tmp_path: Path):
    """Prepares a fake model and returns a function that sends one POST
    /bild and returns its JSON body."""
    config.app.bildmodelle_verzeichnis = str(tmp_path / "bildmodelle")
    bildordner = tmp_path / "bildmodelle"
    bildordner.mkdir(parents=True)
    (bildordner / "base.safetensors").write_bytes(b"x")

    monkeypatch.setattr(Bildrunner, "programm", property(lambda self: Path("/fake/sd-cli")))

    zaehler = {"n": 0}

    def _erzeugen(self, auftrag, ziel):
        zaehler["n"] += 1
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_bytes(b"PNG" + str(zaehler["n"]).encode())
        return ziel

    monkeypatch.setattr(Bildrunner, "erzeugen", _erzeugen)

    def _senden(chat_id: str, **felder):
        body = {"prompt": "x", "modell": "base.safetensors", "chat_id": chat_id, **felder}
        antwort = client.post("/api/v1/bild", json=body)
        assert antwort.status_code == 201, antwort.text
        return antwort.json()

    return _senden


def _nachrichten(client: TestClient, chat_id: str) -> list[dict]:
    return client.get(f"/api/v1/chats/{chat_id}/messages").json()["nachrichten"]


def test_a_single_picture_writes_a_question_and_its_own_row(bild_senden, client, chat_id):
    """A2: a single picture (von=1, the default) must write exactly the
    same two rows as before this feature existed — a question, an
    answer, and stats carrying the seed and what the picture was drawn
    with, no lauf/nr/von key, no ``bilder``."""
    antwort = bild_senden(chat_id)
    nachrichten = _nachrichten(client, chat_id)
    assert len(nachrichten) == 2
    frage, bildnachricht = nachrichten
    assert frage["role"] == "user"
    assert bildnachricht["role"] == "assistant"
    assert bildnachricht["bild"] == antwort["bild"]
    assert bildnachricht.get("bilder") is None
    assert set(bildnachricht["stats"]) == {"seed", "drawn_with"}
    assert bildnachricht["stats"]["seed"] == antwort["seed"]


def test_ein_lauf_von_eins_ist_kein_lauf(bild_senden, client, chat_id):
    """A run of one writes exactly
    the same two rows as a single picture — proven here by sending a
    lauf_kennung WITH von=1 anyway, the way a caller could in principle.
    bild.py forces lauf_kennung to None whenever von==1 regardless of
    what was sent, so this must land exactly like the plain single
    picture above, not as a one-picture 'run'."""
    antwort = bild_senden(chat_id, von=1, nr=1, lauf_kennung="lauf-einzeln", frage_erstellen=True)
    nachrichten = _nachrichten(client, chat_id)
    assert len(nachrichten) == 2
    frage, bildnachricht = nachrichten
    assert bildnachricht["bild"] == antwort["bild"]
    assert bildnachricht.get("bilder") is None
    assert set(bildnachricht["stats"]) == {"seed", "drawn_with"}
    assert bildnachricht["stats"]["seed"] == antwort["seed"]


def test_lauf_schreibt_eine_frage_eine_antwort(bild_senden, client, chat_id):
    """A run of several pictures writes ONE question and
    ONE answer — not one answer per picture, the way the old shape did."""
    for nr in range(1, 5):
        bild_senden(
            chat_id, von=4, nr=nr, lauf_kennung="lauf-a",
            frage_erstellen=(nr == 1),
        )
    nachrichten = _nachrichten(client, chat_id)
    fragen = [n for n in nachrichten if n["role"] == "user"]
    antworten = [n for n in nachrichten if n["role"] == "assistant"]
    assert len(fragen) == 1
    assert len(antworten) == 1
    assert antworten[0]["bilder"] is not None
    assert len(antworten[0]["bilder"]) == 4
    assert all(bild is not None for bild in antworten[0]["bilder"])
    # The write path itself must never touch `bild` on a
    # lauf row. Checked against the REPOSITORY, not the API response —
    # `NachrichtAntwort.aus` already masks `bild` whenever `bilder` is
    # set, so a route-level check alone would stay green even if
    # `lauf_bild_speichern` started writing both.
    roh = client.app.state.repositories.messages.holen(antworten[0]["id"])
    assert roh.bild is None


def test_acht_bilder_alle_gelungen_bleiben_eine_zeile(bild_senden, client, chat_id):
    """A run of 8, all successful, is one user row
    and one assistant row with all eight pictures — the SERVER's old
    four-per-chat ceiling (IM_CHAT_ANZAHL) is gone without replacement.

    This used to also claim the window "still caps its
    own display at four" — false on both halves, measured. Nothing in
    the frontend renders `nachricht.bilder` at all yet, so there is no display to cap. And
    BILDLAUF_IM_CHAT (App.svelte) never capped a display to begin with
    — its three uses all sit inside the shortfall CAPTION's own numbers
    ("N of M pictures could not be drawn"), not the tile row. This test
    is the server side only and says nothing about either."""
    antworten = [
        bild_senden(chat_id, von=8, nr=nr, lauf_kennung="lauf-acht", frage_erstellen=(nr == 1))
        for nr in range(1, 9)
    ]
    # Every request answers with the SAME answer row, not one each.
    assert len({a["antwort_id"] for a in antworten}) == 1

    nachrichten = _nachrichten(client, chat_id)
    fragen = [n for n in nachrichten if n["role"] == "user"]
    antwortzeilen = [n for n in nachrichten if n["role"] == "assistant"]
    assert len(fragen) == 1
    assert len(antwortzeilen) == 1
    assert len(antwortzeilen[0]["bilder"]) == 8
    assert all(bild is not None for bild in antwortzeilen[0]["bilder"])


def test_lauf_kennung_nr_von_stehen_in_stats(bild_senden, client, chat_id):
    """The run is named on the row itself and `von` lands in
    its stats, seeds ride alongside indexed like the pictures — a fixed seed
    walks by the picture's own position, so the run is reproducible picture
    by picture, not eight copies of the same image.

    `lauf` moved out of the stats blob into the `lauf_id` column, and the
    row now says `art='bildlauf'` rather than passing for an answer: an
    empty assistant row was indistinguishable from an answer still being
    written, which is what let a reader adopt one of these and overwrite
    it."""
    for nr in range(1, 4):
        bild_senden(
            chat_id, von=3, nr=nr, lauf_kennung="lauf-b",
            frage_erstellen=(nr == 1), seed=100,
        )
    antwort = next(n for n in _nachrichten(client, chat_id) if n["role"] == "assistant")
    assert antwort["lauf_id"] == "lauf-b"
    assert antwort["art"] == "bildlauf"
    assert antwort["stats"]["von"] == 3
    assert antwort["stats"]["seeds"] == [100, 101, 102]
    assert len(antwort["bilder"]) == 3
    assert all(bild is not None for bild in antwort["bilder"])


def test_bild_landet_beim_richtigen_index_auch_ausser_der_reihe(bild_senden, client, chat_id):
    """A picture finishing out of turn
    must land at its OWN place in the list, not wherever arrival order
    would put it."""
    bild_senden(chat_id, von=3, nr=2, lauf_kennung="lauf-d", frage_erstellen=False)
    bild_senden(chat_id, von=3, nr=1, lauf_kennung="lauf-d", frage_erstellen=True)
    bild_senden(chat_id, von=3, nr=3, lauf_kennung="lauf-d", frage_erstellen=False)

    nachrichten = _nachrichten(client, chat_id)
    fragen = [n for n in nachrichten if n["role"] == "user"]
    antworten = [n for n in nachrichten if n["role"] == "assistant"]
    assert len(fragen) == 1
    assert len(antworten) == 1
    bilder = antworten[0]["bilder"]
    assert len(bilder) == 3
    # nr=2 was written first but must sit at index 1, not index 0.
    assert bilder[1] is not None
    assert bilder[0] is not None
    assert bilder[2] is not None
    assert len({b for b in bilder}) == 3  # three distinct files, not overwritten


def test_frage_ueberlebt_wenn_das_erste_bild_scheitert(
    config: Config, client: TestClient, monkeypatch, tmp_path: Path, chat_id: str,
):
    """Still the point for images per run:
    frage_erstellen only ever names a PLAN — "nr==1 is expected to land".
    The window bakes that plan in before any request is sent, so it
    cannot know picture 1 is about to fail. If the question only ever
    rode on that one plan, a run where picture 1 fails would lose the
    prompt entirely, even though pictures 2-4 go on to succeed under it.
    It must survive — and now lands in the SAME one answer row as
    everything else in the run, with index 0 left empty."""
    config.app.bildmodelle_verzeichnis = str(tmp_path / "bildmodelle")
    bildordner = tmp_path / "bildmodelle"
    bildordner.mkdir(parents=True)
    (bildordner / "base.safetensors").write_bytes(b"x")
    monkeypatch.setattr(Bildrunner, "programm", property(lambda self: Path("/fake/sd-cli")))

    zaehler = {"n": 0}

    def _erzeugen(self, auftrag, ziel):
        zaehler["n"] += 1
        if zaehler["n"] == 1:
            raise BildFehler("bild.gescheitert")
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_bytes(b"PNG" + str(zaehler["n"]).encode())
        return ziel

    monkeypatch.setattr(Bildrunner, "erzeugen", _erzeugen)

    antworten = []
    for nr in range(1, 5):
        body = {
            "prompt": "ein rotes fahrrad", "modell": "base.safetensors",
            "chat_id": chat_id, "von": 4, "nr": nr,
            "lauf_kennung": "lauf-scheitert", "frage_erstellen": nr == 1,
        }
        antworten.append(client.post("/api/v1/bild", json=body))

    assert antworten[0].status_code == 503
    assert [a.status_code for a in antworten[1:]] == [201, 201, 201]

    nachrichten = _nachrichten(client, chat_id)
    fragen = [n for n in nachrichten if n["role"] == "user"]
    antwortzeilen = [n for n in nachrichten if n["role"] == "assistant"]
    assert len(fragen) == 1
    assert fragen[0]["content"] == "ein rotes fahrrad"
    assert len(antwortzeilen) == 1
    bilder = antwortzeilen[0]["bilder"]
    assert bilder[0] is None
    assert all(bild is not None for bild in bilder[1:])
    assert sum(1 for b in bilder if b is not None) == 3


def test_frage_bleibt_einmalig_wenn_nr_zwei_vor_nr_eins_ankommt(bild_senden, client, chat_id):
    """No deletion needed to reach the loss this guards. The
    plan's True branch never checked whether a question already existed —
    only the False branch was ever taught to look. Picture 2
    (frage_erstellen=False) landing first writes the question correctly;
    picture 1 (frage_erstellen=True) landing after it must not write a
    second one just because its own plan still says it is first — and
    both must still land in the one shared answer row."""
    bild_senden(chat_id, von=4, nr=2, lauf_kennung="lauf-d2", frage_erstellen=False)
    bild_senden(chat_id, von=4, nr=1, lauf_kennung="lauf-d2", frage_erstellen=True)

    nachrichten = _nachrichten(client, chat_id)
    fragen = [n for n in nachrichten if n["role"] == "user"]
    antworten = [n for n in nachrichten if n["role"] == "assistant"]
    assert len(fragen) == 1
    assert len(antworten) == 1


def test_bilder_gewinnt_wenn_eine_zeile_beides_traegt(client, chat_id):
    """`bild` and `bilder` are
    mutually exclusive by construction — neither writer here ever
    touches the other's column — but nothing in the code or the docs
    said which one a reader should trust if a row somehow carried both
    anyway. `bilder` wins now, enforced in `NachrichtAntwort.aus`, not
    left to whoever reads the row next.

    Built directly against the database, not through the route: the
    real route can never produce this row itself, so this proves what
    the API does with a state it is designed to prevent, not what the
    route does. Named columns throughout (A3) — the very reason this
    stays correct across a fresh database (`bilder` at column index 7)
    and a migrated one (index 9, appended at the end)."""
    from app.db.repositories.base import neue_id

    state = client.app.state
    state.repositories.db.verbindung.execute(
        "INSERT INTO messages (id, chat_id, role, content, bild, bilder, created_at) "
        "VALUES (?, ?, 'assistant', '', 'aeltere-einzeldatei.png', ?, ?)",
        (neue_id(), chat_id, '["a.png", "b.png"]', "2020-01-01T00:00:00"),
    )
    nachrichten = _nachrichten(client, chat_id)
    zeile = next(n for n in nachrichten if n["role"] == "assistant")
    assert zeile["bilder"] == ["a.png", "b.png"]
    assert zeile["bild"] is None


def test_frage_kommt_zurueck_wenn_sie_selbst_geloescht_wird(bild_senden, client, chat_id):
    """Still the same shape for images per run: deleting only the question
    (not the answer row) while its pictures survive must not be read as
    proof the question was written — nothing would ever write it again.
    The self-heal check stays keyed to role='user', unaffected by
    ``bilder`` replacing the old one-row-per-picture answers."""
    bild_senden(chat_id, von=2, nr=1, lauf_kennung="lauf-e", frage_erstellen=True)
    frage = next(n for n in _nachrichten(client, chat_id) if n["role"] == "user")
    antwort = client.delete(f"/api/v1/chats/{chat_id}/messages/{frage['id']}")
    assert antwort.status_code == 204

    bild_senden(chat_id, von=2, nr=2, lauf_kennung="lauf-e", frage_erstellen=False)

    nachrichten = _nachrichten(client, chat_id)
    fragen = [n for n in nachrichten if n["role"] == "user"]
    antworten = [n for n in nachrichten if n["role"] == "assistant"]
    assert len(fragen) == 1
    assert fragen[0]["content"] == "x"
    assert len(antworten) == 1
    assert all(bild is not None for bild in antworten[0]["bilder"])


def test_lauf_findet_nie_eine_alte_weg_b_zeile(client, chat_id):
    """An old single-picture row carries the same
    `stats.lauf` key a run row does — the lookup matched on that key
    alone, so a chat mixing an old row with new run writes (a restart
    mid-run, or simply an old chat) could find the WRONG row and write
    `bilder` onto it, producing one row with both fields set through
    ordinary use, not a constructed edge case. Requiring `bilder IS NOT
    NULL` on the lookup excludes any row that has not been through
    `lauf_bild_speichern` itself, old single-picture rows included."""
    repositories = client.app.state.repositories
    repositories.messages.speichern(
        chat_id=chat_id, role="assistant", content="", bild="alte-weg-b-datei.png",
        stats={"lauf": "geteilter-lauf", "nr": 1, "von": 2},
    )

    repositories.messages.lauf_bild_speichern(
        chat_id=chat_id, lauf_kennung="geteilter-lauf", nr=1,
        von=1, bild="neue-weg-a-datei.png", seed=1,
    )

    nachrichten = _nachrichten(client, chat_id)
    antworten = [n for n in nachrichten if n["role"] == "assistant"]
    assert len(antworten) == 2
    alte = next(n for n in antworten if n["bild"] == "alte-weg-b-datei.png")
    neue = next(n for n in antworten if n["bild"] is None)
    assert alte["bilder"] is None
    assert neue["bilder"] == ["neue-weg-a-datei.png"]


def test_nr_null_bricht_ab_statt_still_in_den_letzten_platz_zu_schreiben(client, chat_id):
    """Python's negative indexing turns `nr=0`
    into `bilder[-1]` — the LAST slot, silently, instead of an error.
    The route already refuses `nr < 1` (Field(ge=1) on BildWunsch), but
    the method itself had nothing stopping a second caller from doing
    the same thing quietly. Still writing the wrong thing is worse than
    stopping — `nr > von` already raises IndexError and stays that way,
    loud by the list itself."""
    with pytest.raises(ValueError):
        client.app.state.repositories.messages.lauf_bild_speichern(
            chat_id=chat_id, lauf_kennung="lauf-null", nr=0, von=2, bild="x.png", seed=1,
        )


def test_kaputtes_json_in_bilder_kostet_nur_seine_eigene_zeile(client, chat_id):
    """A damaged `bilder` value must not turn
    `GET .../messages` into a 500 for the WHOLE chat — one bad row costs
    that row's own picture list, nothing else in the conversation."""
    repositories = client.app.state.repositories
    repositories.messages.speichern(chat_id=chat_id, role="user", content="x")
    repositories.db.verbindung.execute(
        "INSERT INTO messages (id, chat_id, role, content, bilder, created_at) "
        "VALUES ('kaputt', ?, 'assistant', '', 'nicht-valides-json{{{', ?)",
        (chat_id, "2020-01-01T00:00:00"),
    )

    antwort = client.get(f"/api/v1/chats/{chat_id}/messages")
    assert antwort.status_code == 200
    kaputte_zeile = next(n for n in antwort.json()["nachrichten"] if n["id"] == "kaputt")
    assert kaputte_zeile["bilder"] is None


@pytest.mark.parametrize("stats_wert", [
    "nicht json{{{",   # does not parse at all -> JSONDecodeError
    "[1, 2]",          # parses, wrong shape -> `.get` on a list
    "5",               # parses, wrong shape -> `.get` on an int
    '"hallo"',         # parses, wrong shape -> `str.get` does not exist
])
def test_kaputtes_json_in_stats_kostet_nur_seine_eigene_zeile(
    client, chat_id, stats_wert
):
    """The neighbouring column, and the same rule: `GET .../messages` reads
    every row of a chat in one pass, so one damaged `stats_json` used to end
    the request with a 500 for the whole conversation. Two ways in — text
    that does not parse, and text that parses to something that is not a
    mapping and then meets a reader calling `.get` on it."""
    repositories = client.app.state.repositories
    repositories.messages.speichern(chat_id=chat_id, role="user", content="x")
    repositories.db.verbindung.execute(
        "INSERT INTO messages (id, chat_id, role, content, stats_json, created_at) "
        "VALUES ('kaputt', ?, 'assistant', 'Antwort', ?, ?)",
        (chat_id, stats_wert, "2020-01-01T00:00:00"),
    )

    antwort = client.get(f"/api/v1/chats/{chat_id}/messages")
    assert antwort.status_code == 200
    zeilen = antwort.json()["nachrichten"]
    kaputte_zeile = next(n for n in zeilen if n["id"] == "kaputt")
    # The row survives with its text; only the damaged column is dropped —
    # and dropped means empty, not "some other mapping".
    assert kaputte_zeile["content"] == "Antwort"
    assert kaputte_zeile["stats"] == {}
    assert len(zeilen) == 2


def test_gute_stats_kommen_unveraendert_durch(client, chat_id):
    """The silence probe: a mapping is handed on as it is."""
    repositories = client.app.state.repositories
    repositories.db.verbindung.execute(
        "INSERT INTO messages (id, chat_id, role, content, stats_json, created_at) "
        "VALUES ('heil', ?, 'assistant', 'Antwort', ?, ?)",
        (chat_id, '{"tokens": 7}', "2020-01-01T00:00:00"),
    )

    antwort = client.get(f"/api/v1/chats/{chat_id}/messages")
    assert antwort.status_code == 200
    zeile = next(n for n in antwort.json()["nachrichten"] if n["id"] == "heil")
    assert zeile["stats"]["tokens"] == 7


@pytest.mark.parametrize("roh_wert", [
    "nicht json{{{",   # does not parse at all
    '{"a": 1}',        # parses, wrong shape (a dict) — its KEY once leaked
                       # through as a filename before B7a's guard applied
                       # here too; this is the case that proves it still does
])
def test_schreiben_heilt_eine_beschaedigte_zeile_statt_daran_zu_scheitern(
    client, chat_id, caplog, roh_wert,
):
    """The shape guard was proven on the READ
    side — the write side goes through the exact same `Message.aus_zeile`
    (`lauf_bild_speichern` reads its row through it before writing
    anything back), so a damaged existing value must not crash the
    write either, and must not leak through it in some OTHER shape.
    Before B7a covered this path, a dict's own KEY became the next
    filename (`{"a": 1}` → `"a"` written back as if it were a real
    picture) — this is a NEBENEFFEKT of the shared code path, not a
    dedicated assurance, so it is asserted here explicitly: a future
    change that gives `lauf_bild_speichern` a more direct route past
    `Message.aus_zeile` (a bare `SELECT`, its own `json.loads`) would
    reopen this silently, and only a test that runs THROUGH the write
    path, not just `GET`, would notice.

    It is HEALED, not merely rejected: the read side already turns the
    damaged value into `None`, so the write proceeds as if this lauf's
    row had never had a picture yet, and the fresh, valid list this
    call produces replaces the damaged one outright — overwriting it,
    which is exactly why the log entry matters more here than on the
    read side: nothing else records that anything was ever there.

    Written to `nr=2`, deliberately not `nr=1`: index 0 is where a
    leaked dict key would land, and `nr=1` would silently overwrite
    that exact slot with `bild`, hiding the very regression this test
    exists to catch — the first version of this test did precisely
    that and stayed green with the leak still open."""
    repositories = client.app.state.repositories
    repositories.db.verbindung.execute(
        "INSERT INTO messages (id, chat_id, role, content, bilder, stats_json, "
        "created_at, art, lauf_id) "
        "VALUES ('beschaedigt', ?, 'assistant', '', ?, '{\"von\": 2}', ?, "
        "'bildlauf', 'lauf-heilung')",
        (chat_id, roh_wert, "2020-01-01T00:00:00"),
    )

    with caplog.at_level("WARNING"):
        ergebnis = repositories.messages.lauf_bild_speichern(
            chat_id=chat_id, lauf_kennung="lauf-heilung", nr=2, von=2,
            bild="geheilt.png", seed=1,
        )

    assert ergebnis.bilder == [None, "geheilt.png"]
    assert any("beschaedigt" in satz.message for satz in caplog.records), (
        "no log entry while healing the damaged row"
    )

    geholt = repositories.messages.holen("beschaedigt")
    assert geholt.bilder == [None, "geheilt.png"]


# --- A chat deleted while its picture is drawn --------------------------------


def _pictures(config: Config) -> list[Path]:
    """Every file lying in the picture folder."""
    folder = ort(config, "images")
    return sorted(folder.iterdir()) if folder.is_dir() else []


def test_a_chat_deleted_while_its_picture_is_drawn_leaves_no_file(
    bild_senden, config: Config, client, chat_id, monkeypatch,
):
    """The chat goes while the painter is at work: the finished picture is
    removed with it instead of lying in the picture folder without a row,
    and the request ends the way a stopped picture does."""
    repositories = client.app.state.repositories

    def draw(self, job, target):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"PNG")
        assert repositories.chats.loeschen(chat_id)
        return target

    monkeypatch.setattr(Bildrunner, "erzeugen", draw)
    answer = client.post(
        "/api/v1/bild", json={"prompt": "x", "modell": "base.safetensors", "chat_id": chat_id},
    )
    assert answer.status_code == 499, answer.text
    assert "chat" not in answer.json()["detail"].lower()
    assert _pictures(config) == []


def test_a_chat_that_stays_keeps_its_picture(bild_senden, config: Config, client, chat_id):
    """Silence probe: with the chat still there, the picture lies in the
    folder and stands in the chat."""
    body = bild_senden(chat_id)
    assert [path.name for path in _pictures(config)] == [body["bild"]]
    assert _nachrichten(client, chat_id)[-1]["bild"] == body["bild"]


def test_a_chat_that_never_was_is_said_before_anything_is_drawn(
    bild_senden, config: Config, client, monkeypatch,
):
    """A chat that does not exist is no chat deleted meanwhile: the request
    is told so, and no picture is drawn for it."""
    drawn = []
    monkeypatch.setattr(Bildrunner, "erzeugen", lambda self, job, target: drawn.append(target))
    answer = client.post(
        "/api/v1/bild", json={"prompt": "x", "modell": "base.safetensors", "chat_id": "nobody"},
    )
    assert answer.status_code == 404
    assert drawn == []
    assert _pictures(config) == []


# --- Input pictures no larger than the drawing needs them ---------------------


def _png(width: int, height: int) -> bytes:
    """A grey PNG of the given size — large on screen, small on disk."""

    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body)) + kind + body
            + struct.pack(">I", zlib.crc32(kind + body))
        )

    rows = (b"\x00" + b"\x80" * width) * height
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows, 1))
        + chunk(b"IEND", b"")
    )


@pytest.fixture
def drawn_from(bild_senden, config: Config, monkeypatch):
    """Draws one picture from a starting picture of the given size and hands
    back that picture's own file and the file the painter was given."""

    def draw_from(width: int, height: int, **fields) -> tuple[Path, Path]:
        folder = ort(config, "images")
        folder.mkdir(parents=True, exist_ok=True)
        source = folder / f"start-{width}x{height}.png"
        source.write_bytes(_png(width, height))
        given: list[Path] = []

        def draw(self, job, target):
            given.append(job.startbild)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"PNG")
            return target

        monkeypatch.setattr(Bildrunner, "erzeugen", draw)
        bild_senden(None, startbild=source.name, **fields)
        return source, given[0]

    return draw_from


needs_the_system_tool = pytest.mark.skipif(
    not model_image.verfuegbar(), reason="no system tool to scale a picture here",
)


@needs_the_system_tool
def test_a_start_picture_far_larger_than_the_drawing_reaches_the_painter_scaled_down(drawn_from):
    """8000 by 8000 for a drawing of 1024 by 1024: the painter gets a copy
    of 1024 by 1024, and the picture itself is not written to."""
    before = _png(8000, 8000)
    source, given = drawn_from(8000, 8000, breite=1024, hoehe=1024)
    assert given != source
    assert model_image.masse(given) == (1024, 1024)
    assert source.read_bytes() == before


@needs_the_system_tool
def test_a_start_picture_of_another_shape_keeps_what_the_painter_crops_from(drawn_from):
    """The painter crops a starting picture to the drawing's shape and then
    scales it. 3000 by 1000 for 512 by 512 is made smaller only until it
    still covers the drawing, so the painter never enlarges the copy."""
    _, given = drawn_from(3000, 1000, breite=512, hoehe=512)
    assert model_image.masse(given) == (1536, 512)


@needs_the_system_tool
def test_a_start_picture_that_fits_stays_as_it_is(drawn_from):
    """Silence probe: a picture no larger than the drawing — or larger on
    one side only — goes to the painter itself."""
    source, given = drawn_from(512, 512, breite=1024, hoehe=1024)
    assert given == source
    source, given = drawn_from(2000, 512, breite=1024, hoehe=1024)
    assert given == source


@pytest.fixture
def painter_s_job(bild_senden, config: Config, monkeypatch, tmp_path: Path):
    """Draws once with the named pictures of the given sizes lying in the
    picture folder and hands back the job the painter was given. A field's
    value is a (width, height) pair, or a list of them."""
    folder = ort(config, "images")
    folder.mkdir(parents=True, exist_ok=True)
    # An IP-Adapter in its folder, so the picture its switch names acts.
    adapters = tmp_path / "bildmodelle" / image_switches.IP_ADAPTER_FOLDER
    adapters.mkdir(parents=True, exist_ok=True)
    (adapters / "adapter.safetensors").write_bytes(b"x")

    def lay(field: str, size: tuple[int, int], number: int = 0) -> str:
        name = f"{field}-{number}-{size[0]}x{size[1]}.png"
        (folder / name).write_bytes(_png(*size))
        return name

    def draw(switch_picture: tuple[int, int] | None = None, **pictures):
        fields: dict = {}
        for field, size in pictures.items():
            if field in ("breite", "hoehe", "video"):
                fields[field] = size
            elif isinstance(size, list):
                fields[field] = [lay(field, one, number) for number, one in enumerate(size)]
            else:
                fields[field] = lay(field, size)
        if switch_picture is not None:
            fields["switches"] = {
                "ip_adapter": "adapter.safetensors",
                "ip_adapter_image": lay("guide", switch_picture),
            }
        given: list = []

        def paint(self, job, target):
            given.append(job)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"PNG")
            return target

        monkeypatch.setattr(Bildrunner, "erzeugen", paint)
        bild_senden(None, **fields)
        return given[0], folder

    return draw


@needs_the_system_tool
def test_a_large_mask_reaches_the_painter_at_its_start_picture_s_size(painter_s_job):
    """4000 by 4000 for a drawing of 1024 by 1024: the painter gets a copy
    of the mask, at exactly the size the starting picture goes at — also
    where that picture keeps a shape of its own. Neither file is written
    to."""
    job, folder = painter_s_job(startbild=(4000, 4000), maske=(4000, 4000), breite=1024, hoehe=1024)
    mask = folder / "maske-0-4000x4000.png"
    assert job.maske != mask
    assert model_image.masse(job.maske) == model_image.masse(job.startbild) == (1024, 1024)
    assert mask.read_bytes() == _png(4000, 4000)

    job, _ = painter_s_job(startbild=(3000, 1000), maske=(3000, 1000), breite=512, hoehe=512)
    assert model_image.masse(job.maske) == model_image.masse(job.startbild) == (1536, 512)

    # A mask larger than a starting picture that goes itself follows it too.
    job, folder = painter_s_job(startbild=(512, 512), maske=(4000, 4000), breite=1024, hoehe=1024)
    assert job.startbild == folder / "startbild-0-512x512.png"
    assert model_image.masse(job.maske) == (512, 512)


@needs_the_system_tool
def test_a_reference_video_s_frames_and_a_switch_s_picture_reach_the_painter_scaled_down(
    painter_s_job,
):
    """The frames of a reference video and the picture a switch names are
    read whole by the painter like a starting picture: each goes as a copy
    no larger than the drawing needs it."""
    job, folder = painter_s_job(
        ref_video_frames=[(4000, 4000), (4000, 4000)], video=True, breite=1024, hoehe=1024,
    )
    assert len(job.ref_video_frames) == 2
    for number, frame in enumerate(job.ref_video_frames):
        assert frame != folder / f"ref_video_frames-{number}-4000x4000.png"
        assert model_image.masse(frame) == (1024, 1024)

    job, folder = painter_s_job(switch_picture=(4000, 4000), breite=1024, hoehe=1024)
    guide = job.switch_paths["ip_adapter_image"]
    assert guide != folder / "guide-0-4000x4000.png"
    assert model_image.masse(guide) == (1024, 1024)
    # The file the other switch names is no picture and stays where it lies.
    assert job.switch_paths["ip_adapter"].name == "adapter.safetensors"
    assert job.switch_paths["ip_adapter"].parent.name == image_switches.IP_ADAPTER_FOLDER


@needs_the_system_tool
def test_a_mask_a_frame_and_a_switch_s_picture_that_fit_stay_as_they_are(painter_s_job):
    """Silence probe: what is no larger than the drawing goes itself, and a
    mask without a starting picture does not go at all — as before."""
    job, folder = painter_s_job(
        startbild=(512, 512), maske=(512, 512), switch_picture=(512, 512),
        breite=1024, hoehe=1024,
    )
    assert job.startbild == folder / "startbild-0-512x512.png"
    assert job.maske == folder / "maske-0-512x512.png"
    assert job.switch_paths["ip_adapter_image"] == folder / "guide-0-512x512.png"

    job, folder = painter_s_job(ref_video_frames=[(512, 512)], video=True, breite=1024, hoehe=1024)
    assert job.ref_video_frames == (folder / "ref_video_frames-0-512x512.png",)

    job, _ = painter_s_job(maske=(4000, 4000), breite=1024, hoehe=1024)
    assert job.maske is None and job.startbild is None


@needs_the_system_tool
def test_the_frames_of_a_video_that_fits_are_measured_once(painter_s_job, monkeypatch):
    """The frames of one video share one size: where the first goes itself,
    the others are not measured one by one."""
    measured: list[Path] = []
    real = model_image.masse
    monkeypatch.setattr(
        model_image, "masse", lambda picture: measured.append(picture) or real(picture)
    )
    job, _ = painter_s_job(
        ref_video_frames=[(512, 512)] * 5, steuerbilder=[(512, 512)] * 5, video=True,
        breite=1024, hoehe=1024,
    )
    assert len(job.ref_video_frames) == 5 and len(job.control_frames) == 5
    assert len(measured) == 2


def test_without_a_system_tool_the_mask_goes_out_whole(tmp_path: Path, monkeypatch):
    """No tool, a picture that cannot be measured, or a tool that fails: the
    draw gets the mask itself, and no half-written copy is left behind."""
    mask, picture = tmp_path / "mask.png", tmp_path / "start.png"
    mask.write_bytes(_png(64, 64))
    picture.write_bytes(_png(16, 16))
    work = tmp_path / "work"

    monkeypatch.setattr(model_image, "verfuegbar", lambda: False)
    assert draw_input.fitted_like(mask, picture, work) == mask

    monkeypatch.setattr(model_image, "verfuegbar", lambda: True)
    monkeypatch.setattr(model_image, "masse", lambda file: (None, None))
    assert draw_input.fitted_like(mask, picture, work) == mask

    monkeypatch.setattr(
        model_image, "masse", lambda file: (64, 64) if file == mask else (16, 16)
    )
    monkeypatch.setattr(model_image, "scaled_copy", lambda *a: False)
    assert draw_input.fitted_like(mask, picture, work) == mask
    assert not work.exists() or list(work.iterdir()) == []


def test_the_size_a_picture_is_scaled_down_to_still_covers_the_drawing():
    assert draw_input.covering_size(8000, 8000, 1024, 1024) == (1024, 1024)
    assert draw_input.covering_size(3000, 1000, 512, 512) == (1536, 512)
    assert draw_input.covering_size(1000, 3000, 512, 512) == (512, 1536)
    assert draw_input.covering_size(4032, 3024, 1024, 768) == (1024, 768)
    # Not larger on both sides: nothing to make smaller.
    assert draw_input.covering_size(1024, 1024, 1024, 1024) is None
    assert draw_input.covering_size(8000, 512, 1024, 1024) is None
    assert draw_input.covering_size(512, 512, 1024, 1024) is None


def test_without_a_system_tool_the_picture_goes_out_whole(tmp_path: Path, monkeypatch):
    """No tool, or a tool that fails: the draw gets the original, and no
    half-written copy is left behind."""
    source = tmp_path / "start.png"
    source.write_bytes(_png(64, 64))
    work = tmp_path / "work"

    monkeypatch.setattr(model_image, "verfuegbar", lambda: False)
    assert draw_input.fitted(source, 16, 16, work) == source

    monkeypatch.setattr(model_image, "verfuegbar", lambda: True)
    monkeypatch.setattr(model_image, "masse", lambda picture: (64, 64))
    monkeypatch.setattr(model_image, "scaled_copy", lambda *a: False)
    assert draw_input.fitted(source, 16, 16, work) == source
    assert not work.exists() or list(work.iterdir()) == []


def test_scaled_copy_writes_exactly_the_asked_size(tmp_path: Path):
    """The painter gets a PNG of exactly the size asked for, whatever the
    source's ratio — and a name with an apostrophe in it is a name, not the
    end of a string (it broke the script of the tool that stood here
    before)."""
    source = tmp_path / "it's.png"
    source.write_bytes(_png(64, 64))
    target = tmp_path / "it's-1536x512.png"
    assert model_image.scaled_copy(source, target, 1536, 512)
    assert model_image.masse(target) == (1536, 512)


# --- A piece of a picture, drawn and set back --------------------------------

_OLD, _NEW = (10, 60, 200), (240, 180, 20)


@pytest.fixture
def drawn_piece(bild_senden, config: Config, monkeypatch):
    """Draws from a piece of a picture of 200 by 300 that lies in the picture
    folder — the painter writes a picture of 64 by 64 with its settings in
    it — and hands back the run's picture."""
    folder = ort(config, "images")
    folder.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (200, 300), _OLD).save(folder / "whole.png")
    Image.new("RGB", (100, 100), _OLD).save(folder / "piece.png")

    def paint(self, job, target):
        beside = PngInfo()
        beside.add_text("parameters", "a lighthouse")
        target.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (64, 64), _NEW).save(target, "PNG", pnginfo=beside)
        return target

    monkeypatch.setattr(Bildrunner, "erzeugen", paint)

    def draw(**fields) -> Image.Image:
        answer = bild_senden(None, startbild="piece.png", **fields)
        with Image.open(folder / answer["bild"]) as result:
            result.load()
            return result

    return draw


@needs_the_system_tool
def test_a_large_mask_is_set_in_from_the_mask_itself(drawn_piece, config: Config, monkeypatch):
    """The painter gets the mask at its starting picture's size; setting the
    drawn piece back reads the mask as it lies in the folder."""
    folder = ort(config, "images")
    mask = Image.new("L", (400, 400), 0)
    mask.paste(255, (120, 120, 280, 280))
    mask.save(folder / "mask.png")
    read: list[Path] = []
    real = paste_back.into_whole

    def into_whole(drawn, whole, box, cover=None):
        read.append(cover)
        return real(drawn, whole, box, cover)

    monkeypatch.setattr(paste_back, "into_whole", into_whole)
    result = drawn_piece(maske="mask.png", crop_of="whole.png", crop_box=[50, 100, 100, 100])
    assert read == [folder / "mask.png"]
    assert result.convert("RGB").getpixel((100, 150)) == _NEW
    assert result.convert("RGB").getpixel((55, 105)) == _OLD


def test_a_draw_from_a_piece_hands_back_the_whole_picture(drawn_piece, config: Config):
    """With the picture the piece was cut from and the piece's place, the
    run's picture has that picture's size and carries the drawn piece where
    it was cut out; the picture it came from is not written to."""
    whole = ort(config, "images") / "whole.png"
    before = whole.read_bytes()
    result = drawn_piece(crop_of="whole.png", crop_box=[50, 100, 100, 100])
    assert result.size == (200, 300)
    assert result.convert("RGB").getpixel((100, 150)) == _NEW
    assert result.convert("RGB").getpixel((10, 10)) == _OLD
    assert whole.read_bytes() == before
    with Image.open(whole) as untouched:
        assert untouched.convert("RGB").getpixel((100, 150)) == _OLD


@pytest.mark.parametrize("fields", [
    {},
    {"crop_of": "whole.png"},
    {"crop_box": [50, 100, 100, 100]},
    # The place reaches beyond the picture, or has no width.
    {"crop_of": "whole.png", "crop_box": [150, 100, 100, 100]},
    {"crop_of": "whole.png", "crop_box": [50, 100, 0, 100]},
    # The picture is not there, or is named as a path.
    {"crop_of": "gone.png", "crop_box": [50, 100, 100, 100]},
    {"crop_of": "../images/whole.png", "crop_box": [50, 100, 100, 100]},
], ids=["neither", "no-place", "no-picture", "beyond", "no-width", "gone", "a-path"])
def test_without_a_fitting_place_the_painter_s_picture_stays(drawn_piece, fields):
    """The silence check: the run draws all the same, and its picture is the
    piece as the painter wrote it."""
    result = drawn_piece(**fields)
    assert result.size == (64, 64)


def test_the_whole_picture_passes_the_settings_gate_like_any_other(
    drawn_piece, client: TestClient,
):
    """What the painter wrote beside its pixels stands in the whole picture
    too — and is stripped from it where pictures are stored without it."""
    from app.bildschutz import SCHLUESSEL

    place = {"crop_of": "whole.png", "crop_box": [50, 100, 100, 100]}
    assert drawn_piece(**place).text == {}
    client.patch(f"/api/v1/settings/global/{SCHLUESSEL}", json={"wert": {"an": False}})
    kept = drawn_piece(**place)
    assert kept.size == (200, 300)
    assert kept.text == {"parameters": "a lighthouse"}


def test_a_video_is_never_set_into_a_picture(drawn_piece):
    """A run that draws a video keeps the painter's file whatever it names."""
    result = drawn_piece(video=True, crop_of="whole.png", crop_box=[50, 100, 100, 100])
    assert result.size == (64, 64)


def test_with_a_mask_only_the_painted_part_of_the_piece_is_set_in(drawn_piece, config: Config):
    """The run's own mask says what of the piece replaces the picture."""
    mask = Image.new("L", (100, 100), 0)
    mask.paste(255, (30, 30, 70, 70))
    mask.save(ort(config, "images") / "mask.png")
    result = drawn_piece(
        maske="mask.png", crop_of="whole.png", crop_box=[50, 100, 100, 100],
    ).convert("RGB")
    assert result.size == (200, 300)
    assert result.getpixel((100, 150)) == _NEW
    # Inside the piece's place, but not painted over.
    assert result.getpixel((60, 110)) == _OLD


# --- What a picture was drawn with, kept by the program ----------------------


def _info(client: TestClient, name: str) -> dict:
    answer = client.get("/api/v1/bild/info", params={"name": name})
    assert answer.status_code == 200, answer.text
    return answer.json()


def test_the_program_keeps_what_a_picture_was_drawn_with(
    bild_senden, client: TestClient, chat_id, monkeypatch,
):
    """Pictures are stored without their settings (the switch ships on), and
    the program still says what one was drawn with: asked by the picture's
    name, in the names the reading of a file answers with."""

    def paint(self, job, target):
        beside = PngInfo()
        beside.add_text("parameters", "a lighthouse\nSteps: 6, Seed: 7")
        target.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (8, 8)).save(target, "PNG", pnginfo=beside)
        return target

    monkeypatch.setattr(Bildrunner, "erzeugen", paint)
    answer = bild_senden(
        chat_id, prompt="a lighthouse", negativ="fog", breite=768, hoehe=512, schritte=6,
        cfg=1.5, seed=7, sampler="euler", crop_of="whole.png", crop_box=[0, 0, 8, 8],
    )
    assert _info(client, answer["bild"]) == {
        "prompt": "a lighthouse", "negativ": "fog", "modell": "base.safetensors",
        "breite": 768, "hoehe": 512, "schritte": 6, "cfg": 1.5, "seed": 7, "sampler": "euler",
    }
    # The silence checks: the stored file carries nothing beside its pixels,
    # and a name nothing is kept for gets the empty answer.
    stored = client.get(f"/api/v1/images/{answer['bild']}").content
    assert b"tEXt" not in stored and b"lighthouse" not in stored
    assert _info(client, "0123456789abcdef0123456789abcdef.png") == {}
    assert _info(client, "") == {}


def test_each_picture_of_a_run_keeps_its_own_values(bild_senden, client: TestClient, chat_id):
    names = [
        bild_senden(
            chat_id, von=2, nr=nr, lauf_kennung="run-info", frage_erstellen=(nr == 1),
            seed=100, schritte=steps,
        )["bild"]
        for nr, steps in ((2, 9), (1, 4))
    ]
    second, first = (_info(client, name) for name in names)
    assert (first["schritte"], first["seed"]) == (4, 100)
    assert (second["schritte"], second["seed"]) == (9, 101)
    assert first["prompt"] == second["prompt"] == "x"


def test_a_picture_drawn_while_an_answer_is_written_keeps_its_values(
    bild_senden, client: TestClient, chat_id,
):
    """The pictures of the drawing tool stand in the run of the answer they
    were drawn for, a run that grows picture by picture: each one keeps its
    own values there too."""
    messages = client.app.state.repositories.messages
    answer = messages.speichern(chat_id=chat_id, role="assistant", content="Here it is.")
    names = [
        bild_senden(chat_id, lauf_kennung=answer.id, prompt=prompt, seed=5)["bild"]
        for prompt in ("a harbour", "a ship")
    ]
    assert [_info(client, name)["prompt"] for name in names] == ["a harbour", "a ship"]
    assert messages.run_row(chat_id=chat_id, lauf_kennung=answer.id).bilder == names


def test_a_run_stored_before_values_were_kept_answers_empty(client: TestClient, chat_id):
    """The silence check: a row that carries a picture and no values — one
    written before they were kept — gives the empty answer, never an error."""
    messages = client.app.state.repositories.messages
    messages.speichern(
        chat_id=chat_id, role="assistant", content="", bild="old.png", stats={"seed": 3},
        art="bild",
    )
    messages.lauf_bild_speichern(
        chat_id=chat_id, lauf_kennung="old-run", nr=1, von=2, bild="old-run-1.png", seed=4,
    )
    assert _info(client, "old.png") == {}
    assert _info(client, "old-run-1.png") == {}


# --- A picture that was only enlarged has no seed ----------------------------


@pytest.fixture
def mode_run(bild_senden, config: Config, tmp_path: Path):
    """Runs a mode on a finished picture of the picture folder — enlarging
    or repairing faces alone — into a chat, and hands back the route's
    answer. The upscaler and the detector lie in their own folders."""
    folder = ort(config, "images")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "finished.png").write_bytes(_png(64, 64))
    models = tmp_path / "bildmodelle"
    for sub, name in (("upscaler", "big.pth"), ("adetailer", "face.pt")):
        (models / sub).mkdir(parents=True, exist_ok=True)
        (models / sub / name).write_bytes(b"x")

    def run(chat: str, mode: str) -> dict:
        return bild_senden(
            chat, startbild="finished.png", mode=mode, seed=77,
            upscale_model="big.pth", ad_modell="face.pt",
        )

    return run


def test_enlarging_alone_reports_no_seed(mode_run, client: TestClient, chat_id):
    """Enlarging draws nothing and uses no seed: the answer, the chat's row
    and the values kept for the picture name none."""
    answer = mode_run(chat_id, "upscale")
    assert answer["seed"] is None
    row = next(m for m in _nachrichten(client, chat_id) if m.get("bild") == answer["bild"])
    assert "seed" not in row["stats"]
    kept = _info(client, answer["bild"])
    assert "seed" not in kept
    assert kept["modell"] == "base.safetensors"


def test_repairing_faces_alone_keeps_its_seed(mode_run, client: TestClient, chat_id):
    """The silence check: the detailer draws, so its seed is reported as
    for any drawn picture."""
    answer = mode_run(chat_id, "adetailer")
    assert answer["seed"] == 77
    row = next(m for m in _nachrichten(client, chat_id) if m.get("bild") == answer["bild"])
    assert row["stats"]["seed"] == 77
    assert _info(client, answer["bild"])["seed"] == 77


def test_enlarging_without_a_prompt_is_drawn_and_keeps_none(
    mode_run, bild_senden, client: TestClient, chat_id,
):
    """The upscaler reads no prompt: a picture that was uploaded is enlarged
    with none, writes no question into the chat, and its values name none."""
    mode_run(chat_id, "upscale")
    answer = bild_senden(
        chat_id, prompt="", startbild="finished.png", mode="upscale",
        upscale_model="big.pth", frage_erstellen=False,
    )
    assert answer["seed"] is None
    rows = _nachrichten(client, chat_id)
    new = next(m for m in rows if m.get("bild") == answer["bild"])
    assert new["role"] == "assistant"
    # The first run of the fixture wrote its pair; this one wrote only its answer.
    assert [m["role"] for m in rows].count("user") == 1
    assert "prompt" not in _info(client, answer["bild"])


def test_enlarging_with_a_prompt_keeps_it_and_writes_its_question(
    mode_run, bild_senden, client: TestClient, chat_id,
):
    """The silence check: the prompt of an enlarging stands in the chat and
    in the values kept for the new picture, as it did."""
    mode_run(chat_id, "upscale")
    answer = bild_senden(
        chat_id, prompt="a red car", startbild="finished.png", mode="upscale", upscale_model="big.pth",
    )
    asked = [m["content"] for m in _nachrichten(client, chat_id) if m["role"] == "user"]
    assert asked[-1] == "a red car"
    assert _info(client, answer["bild"])["prompt"] == "a red car"


@pytest.mark.parametrize("mode", ["", "adetailer"])
def test_a_drawing_or_a_repair_without_a_prompt_is_still_refused(
    mode_run, client: TestClient, chat_id, mode,
):
    """Only the enlarging goes without a prompt: the other modes and the
    drawing are refused as before, with the length sentence."""
    mode_run(chat_id, "upscale")
    answer = client.post("/api/v1/bild", json={
        "prompt": "", "modell": "base.safetensors", "chat_id": chat_id,
        "startbild": "finished.png", "mode": mode, "ad_modell": "face.pt",
    })
    assert answer.status_code == 422, answer.text
    entry = answer.json()["detail"][0]
    assert entry["type"] == "string_too_short" and entry["ctx"] == {"min_length": 1}


# --- A failed picture's run says why ------------------------------------------


def _runs(client: TestClient, chat_id: str) -> list[dict]:
    answer = client.get(f"/api/v1/laeufe/{chat_id}")
    assert answer.status_code == 200, answer.text
    return answer.json()["laeufe"]


def test_a_failed_picture_s_run_carries_the_answer_s_words(
    bild_senden, client: TestClient, monkeypatch, chat_id: str,
):
    """The red run in the terminal carries the same text the caller got:
    the sentence and the painter's last words below it."""

    def _erzeugen(self, auftrag, ziel):
        raise BildFehler("bild.gescheitert", "[ERROR] load tensors from model loader failed")

    monkeypatch.setattr(Bildrunner, "erzeugen", _erzeugen)
    answer = client.post(
        "/api/v1/bild", json={"prompt": "x", "modell": "base.safetensors", "chat_id": chat_id},
    )
    assert answer.status_code == 503
    said = answer.json()["detail"]
    assert "load tensors from model loader failed" in said

    run = _runs(client, chat_id)[-1]
    assert run["zustand"] == "fehler"
    assert run["ausgabe"] == said


def test_a_stopped_and_a_finished_picture_s_run_stay_without_text(
    bild_senden, client: TestClient, monkeypatch, chat_id: str,
):
    """The silence probe: a picture that was drawn and one that was stopped
    leave a run without any output."""
    bild_senden(chat_id)
    assert [(run["zustand"], run["ausgabe"]) for run in _runs(client, chat_id)] == [("fertig", "")]

    def _erzeugen(self, auftrag, ziel):
        raise BildFehler("bild.abgebrochen", "stopped while drawing")

    monkeypatch.setattr(Bildrunner, "erzeugen", _erzeugen)
    answer = client.post(
        "/api/v1/bild", json={"prompt": "x", "modell": "base.safetensors", "chat_id": chat_id},
    )
    assert answer.status_code == 499
    run = _runs(client, chat_id)[-1]
    assert run["zustand"] == "abgebrochen"
    assert run["ausgabe"] == ""
