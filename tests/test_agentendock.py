"""The dock (app/agentendock.py), its tool and its API.

The one shelf for files without a chat: what the person drops on the start
page and what a job without a chat delivers.
"""

from __future__ import annotations

import pytest

from app import zwischenstand
from app.agenten import Agent
from app import atomic_file
from app.agentendock import DATEI, MAX_BYTES, AgentenDock, dock_fuer
from app.providers import MockProvider
from app.tools import agentendock as werkzeug
from app.tools.agentendock import AblageVerboten
from app.tools.registry import WerkzeugRegistry

AGENT = Agent(name="recherche", prompt="Prompt.")


# --- The shelf itself --------------------------------------------------------


def test_ablegen_holen_entfernen(tmp_path):
    dock = AgentenDock(tmp_path)
    eintrag = dock.ablegen("bericht.md", b"# Report", typ="text/markdown", agent="recherche")

    assert eintrag["agent"] == "recherche"
    assert [e["id"] for e in dock.alle()] == [eintrag["id"]]

    gefunden = dock.holen(eintrag["id"])
    assert gefunden is not None
    daten, pfad = gefunden
    assert pfad.read_bytes() == b"# Report"
    assert daten["name"] == "bericht.md"

    assert dock.entfernen(eintrag["id"]) is True
    assert dock.alle() == []
    assert not pfad.exists()


def test_der_typ_kommt_aus_dem_namen(tmp_path):
    """Without a type every file leaves the shelf as octet-stream, and a
    delivered picture is then refused by the chat and shown without a
    thumbnail. The name carries the only hint both ways in have."""
    dock = AgentenDock(tmp_path)
    assert dock.ablegen("bild.png", b"\x89PNG")["typ"] == "image/png"
    assert dock.ablegen("quelle.txt", b"x")["typ"] == "text/plain"
    assert dock.ablegen("bericht.md", b"# Report")["typ"] == "text/markdown"
    # No extension, nothing to read off — and a given type still wins.
    assert dock.ablegen("ohne", b"x")["typ"] == ""
    assert dock.ablegen("a.txt", b"x", typ="text/csv")["typ"] == "text/csv"
    # A packed name describes what is inside the archive, not the bytes here.
    assert dock.ablegen("bericht.md.gz", b"x")["typ"] == ""


def test_pfadtricks_bleiben_im_ordner(tmp_path):
    dock = AgentenDock(tmp_path)
    eintrag = dock.ablegen("../../evil.md", b"x")
    _, pfad = dock.holen(eintrag["id"])
    assert pfad.parent.resolve() == dock.ordner.resolve()


def test_die_zahl_der_dateien_hat_keine_decke(tmp_path):
    """The ceiling at 50 is gone, and it is gone in the only way that can be
    shown: past it, well past it, without a single refusal.

    It was a wall with no door — nothing in the program ever cleared a place,
    the refused delivery was lost, and the run still reported "fertig". What
    it was there for is answered elsewhere now: the per-file ceiling below,
    and a folder the user owns, sees and can empty.
    """
    dock = AgentenDock(tmp_path)
    for nummer in range(120):
        dock.ablegen(f"bericht-{nummer}.md", f"Nummer {nummer}".encode())
    liste = dock.alle()
    assert len(liste) == 120
    # Not just counted: the hundredth is really there, with its own file.
    _, pfad = dock.holen(liste[99]["id"])
    assert pfad.read_text(encoding="utf-8") == "Nummer 99"


# --- The record survives two hands at once and a damaged file ---------------


def test_zwei_gleichzeitige_ablagen_verlieren_keinen_eintrag(tmp_path):
    """Two deliveries at the same moment, provoked rather than argued.

    Every delivery read the whole record, appended one entry and wrote the
    whole thing back. Two of them at the same moment — two due schedules, a
    firing beside a hand-started job, or the panel's own delete in the
    threadpool FastAPI gives a synchronous endpoint — both read the same
    list and both wrote their own version of it: one entry simply gone, its
    file left in the folder as a nameless ``<uuid>.md``.

    Threads and not tasks on purpose: that is the shape the race really has
    here, and it is the shape the lock has to answer.
    """
    import threading

    dock = AgentenDock(tmp_path)
    barriere = threading.Barrier(8)
    fehler: list[BaseException] = []

    def legen(nummer: int) -> None:
        try:
            barriere.wait()
            for lauf in range(15):
                dock.ablegen(f"bericht-{nummer}-{lauf}.md", b"x")
        except BaseException as ausnahme:  # noqa: BLE001 - reported below
            fehler.append(ausnahme)

    faeden = [threading.Thread(target=legen, args=(n,)) for n in range(8)]
    for faden in faeden:
        faden.start()
    for faden in faeden:
        faden.join()

    assert fehler == []
    namen = {e["name"] for e in dock.alle()}
    assert len(namen) == 8 * 15
    # And every entry still points at a file that is really there — a record
    # is only worth anything as long as it names what exists.
    for eintrag in dock.alle():
        assert dock.holen(eintrag["id"]) is not None


@pytest.mark.platforms("posix", reason="a reader holding the file blocks the rename on Windows (WinError 5)")
def test_das_verzeichnis_wird_nie_halb_gelesen(tmp_path):
    """``write_text`` truncates first and writes after, so a reader in
    between got half a file — read as an empty shelf, and written back as
    one by the next delivery. With 89 entries at 23 KB that window is not a
    theoretical instant any more; it grows with the shelf.

    Side file plus rename closes it: a reader sees the whole old record or
    the whole new one, never something between the two.
    """
    import threading

    dock = AgentenDock(tmp_path)
    dock.ablegen("erst.md", b"x")
    laeuft = True
    gelesen: list[int] = []

    def lesen() -> None:
        while laeuft:
            gelesen.append(len(dock.alle()))

    leser = threading.Thread(target=lesen)
    leser.start()
    try:
        for nummer in range(200):
            dock.ablegen(f"bericht-{nummer}.md", b"x")
    finally:
        laeuft = False
        leser.join()

    assert len(dock.alle()) == 201
    # Never empty, and never going backwards: both would mean the reader saw
    # a file that was not a whole record.
    assert gelesen
    assert min(gelesen) >= 1
    assert gelesen == sorted(gelesen)


def test_the_record_s_side_file_is_never_taken_in_as_a_delivery(tmp_path):
    """A write's side file (app/atomic_file.py) lies in the folder for a
    moment; a listing that catches it there must not show it as a file —
    the count went 2, 3, 2 in the reader test above."""
    dock = AgentenDock(tmp_path)
    dock.ablegen("erst.md", b"x")
    (tmp_path / atomic_file.side_file_name(DATEI)).write_text("[]", encoding="utf-8")
    assert [e["name"] for e in dock.alle()] == ["erst.md"]


def test_ein_kaputtes_verzeichnis_wird_nicht_ueberschrieben(tmp_path):
    """A read error must not become a silent loss.

    ``except … return []`` said "unreadable means empty shelf", and the very
    next delivery wrote that emptiness over the file for good. The record is
    the only thing that maps ``<uuid>.md`` back to ``bericht.md``, so losing
    it turns every file on the shelf into an unnamed blob.

    So the write refuses instead — through the road a refused delivery
    already takes, which ends the run on ``ablage_gescheitert`` rather than
    on silence — and the damaged bytes stay exactly where they are.
    """
    dock = AgentenDock(tmp_path)
    dock.ablegen("bericht.md", b"# Report")
    kaputt = "[{halb geschrieben"
    dock.pfad.write_text(kaputt, encoding="utf-8")

    with pytest.raises(ValueError, match="could not be read"):
        dock.ablegen("neu.md", b"x")
    with pytest.raises(ValueError, match="could not be read"):
        dock.entfernen("egal")

    assert dock.pfad.read_text(encoding="utf-8") == kaputt
    # And the panel still opens: a broken record shows an empty wall rather
    # than taking the whole agents view down with it.
    assert dock.alle() == []


def test_ein_verzeichnis_das_keine_liste_ist_ebenso(tmp_path):
    """Readable JSON of the wrong shape is the same case — a hand-edited
    file, or someone else's ``agentendock.json`` in a folder the shelf was
    pointed at."""
    dock = AgentenDock(tmp_path)
    dock.pfad.parent.mkdir(parents=True, exist_ok=True)
    dock.pfad.write_text('{"fremd": true}', encoding="utf-8")

    with pytest.raises(ValueError, match="not a list"):
        dock.ablegen("neu.md", b"x")
    assert dock.pfad.read_text(encoding="utf-8") == '{"fremd": true}'


async def test_the_size_ceiling_holds_on_the_tool_path_only(tmp_path):
    """Ten megabytes and one byte: the delivery tool refuses them, the
    person's own drop onto the same shelf takes them."""
    dock = AgentenDock(tmp_path)
    too_large = "x" * (MAX_BYTES + 1)

    with pytest.raises(AblageVerboten, match="large"):
        await werkzeug.ausfuehren(
            {"name": "gross.txt", "content": too_large}, dock, [],
            herkunft="agent", agent=AGENT, job="j1",
        )
    assert dock.alle() == []

    eintrag = dock.ablegen("gross.txt", too_large.encode())
    assert eintrag["groesse"] == MAX_BYTES + 1
    assert [e["name"] for e in dock.alle()] == ["gross.txt"]


def test_die_dateigrenze_bleibt_und_ist_grosszuegig():
    """Not the same wood as the count ceiling that stood beside it.

    That one was global, silent and had no way out. This one is per call,
    names the size and the ceiling, and the model can answer it by writing
    less. It stays.
    """
    assert MAX_BYTES >= 1024 * 1024


# --- The folder is the user's ------------------------------------------------


def test_das_verzeichnis_liegt_im_ordner(tmp_path):
    """Folder and record are one thing. A record left in the data folder
    would name files a moved folder does not hold."""
    dock = AgentenDock(tmp_path / "regal")
    dock.ablegen("bericht.md", b"x")
    assert (tmp_path / "regal" / DATEI).is_file()
    assert not (tmp_path / DATEI).exists()


def test_der_ordner_wird_bei_jedem_griff_neu_gefragt(tmp_path):
    """The registry holds one shelf from startup to the next settings save.
    A folder bound back then would go on writing into the old place for the
    rest of the session — so the shelf asks, every time."""
    wohin = {"pfad": tmp_path / "erst"}
    dock = AgentenDock(lambda: wohin["pfad"])
    dock.ablegen("erst.md", b"a")
    wohin["pfad"] = tmp_path / "dann"
    assert dock.alle() == []
    dock.ablegen("dann.md", b"b")
    assert [e["name"] for e in dock.alle()] == ["dann.md"]
    # And the first shelf is untouched over there — nothing was lost, it is
    # simply somewhere else, and pointing back brings all of it home.
    wohin["pfad"] = tmp_path / "erst"
    assert [e["name"] for e in dock.alle()] == ["erst.md"]


def test_dock_fuer_folgt_dem_speicherort(tmp_path, config):
    """The one place a shelf is built reads the storage location, so moving
    the folder in the panel is felt by the very next delivery."""
    from app import speicherorte

    vorgabe = dock_fuer(config)
    vorgabe.ablegen("alt.md", b"a")
    assert vorgabe.ordner == speicherorte.standard(config, "agent_dock")

    anderswo = tmp_path / "woanders"
    speicherorte.setzen(config, "agent_dock", anderswo)
    jetzt = dock_fuer(config)
    assert jetzt.ordner == anderswo.resolve()
    assert jetzt.alle() == []
    jetzt.ablegen("neu.md", b"b")
    assert (anderswo / DATEI).is_file()

    speicherorte.loeschen(config, "agent_dock")
    assert [e["name"] for e in dock_fuer(config).alle()] == ["alt.md"]


def test_ein_altes_verzeichnis_wird_einmal_uebernommen(tmp_path, config):
    """Before the shelf had a folder of its own, its record sat one level up
    in the data folder. Left there, an installation with deliveries would
    open an empty shelf while its files lay right beside it — a silent loss,
    which is the very thing this step is about."""
    from app import speicherorte

    ordner = speicherorte.standard(config, "agent_dock")
    ordner.mkdir(parents=True, exist_ok=True)
    (ordner / "abc.md").write_bytes(b"# Alt")
    config.datenverzeichnis.mkdir(parents=True, exist_ok=True)
    (config.datenverzeichnis / DATEI).write_text(
        '[{"id": "abc", "name": "alt.md", "datei": "abc.md", "typ": "text/markdown",'
        ' "groesse": 5, "agent": "recherche", "abgelegt": "2026-09-01T00:00:00+00:00"}]',
        encoding="utf-8",
    )

    dock = dock_fuer(config)
    assert [e["name"] for e in dock.alle()] == ["alt.md"]
    assert (ordner / DATEI).is_file()
    assert not (config.datenverzeichnis / DATEI).exists()


def test_ein_altes_verzeichnis_folgt_keinem_umzug(tmp_path, config):
    """Once the folder was moved, the old record must stay where it is: the
    files it names are in the old folder, and carrying the list after them
    would fill the new shelf with tiles that open nothing."""
    from app import speicherorte

    config.datenverzeichnis.mkdir(parents=True, exist_ok=True)
    (config.datenverzeichnis / DATEI).write_text(
        '[{"id": "abc", "name": "alt.md", "datei": "abc.md"}]', encoding="utf-8"
    )
    anderswo = tmp_path / "woanders"
    speicherorte.setzen(config, "agent_dock", anderswo)

    assert dock_fuer(config).alle() == []
    assert not (anderswo / DATEI).exists()
    assert (config.datenverzeichnis / DATEI).is_file()


# --- The tool ---------------------------------------------------------------


async def test_werkzeug_liefert_text_ab(tmp_path):
    dock = AgentenDock(tmp_path)
    antwort = await werkzeug.ausfuehren(
        {"name": "bericht.md", "content": "# Report"},
        dock, [], herkunft="agent", agent=AGENT,
    )
    assert "bericht.md" in antwort
    (eintrag,) = dock.alle()
    assert eintrag["agent"] == "recherche"
    _, pfad = dock.holen(eintrag["id"])
    assert pfad.read_text(encoding="utf-8") == "# Report"


_KEIN_TEXT = (
    "'{name}' is not a text format, but 'content' is always stored as plain text, so the "
    "file would not open. Write the file first, for example a PDF with write_file, then "
    "call deliver_file again with its 'path' instead of 'content'."
)


@pytest.mark.parametrize("name", ["bericht.pdf", "bild.png", "Tabelle.XLSX"])
async def test_content_under_a_name_that_is_no_text_format_is_refused(tmp_path, name):
    """`content` is stored as plain text whatever the name says: under a
    .pdf or a .png it would open as nonsense. The call is refused with the
    way that works and nothing is written."""
    dock = AgentenDock(tmp_path)
    with pytest.raises(AblageVerboten) as fehler:
        await werkzeug.ausfuehren(
            {"name": name, "content": "plain words"},
            dock, [], herkunft="agent", agent=AGENT,
        )
    assert str(fehler.value) == _KEIN_TEXT.format(name=name)
    assert dock.alle() == []


async def test_a_chat_call_with_content_under_such_a_name_stores_nothing(tmp_path):
    gespeichert = []

    def ablage(**felder):
        gespeichert.append(felder)

    with pytest.raises(AblageVerboten, match="not a text format"):
        await werkzeug.ausfuehren(
            {"name": "bericht.pdf", "content": "plain words"},
            AgentenDock(tmp_path), [], herkunft="chat", chat_delivery=ablage, chat="c1", answer="a1",
        )
    assert gespeichert == []


@pytest.mark.parametrize("name", ["bericht.md", "daten.csv", "README"])
async def test_silence_content_under_a_text_name_or_none_goes_through(tmp_path, name):
    dock = AgentenDock(tmp_path)
    await werkzeug.ausfuehren(
        {"name": name, "content": "plain words"}, dock, [], herkunft="agent", agent=AGENT,
    )
    (eintrag,) = dock.alle()
    _, pfad = dock.holen(eintrag["id"])
    assert pfad.read_text(encoding="utf-8") == "plain words"


async def test_silence_a_path_to_a_real_pdf_goes_through(tmp_path):
    dock = AgentenDock(tmp_path / "daten")
    freigabe = tmp_path / "arbeit"
    freigabe.mkdir()
    (freigabe / "bericht.pdf").write_bytes(b"%PDF-1.4 ...")

    await werkzeug.ausfuehren(
        {"name": "bericht.pdf", "path": "bericht.pdf"},
        dock, [str(freigabe)], herkunft="agent", agent=AGENT,
    )
    (eintrag,) = dock.alle()
    _, pfad = dock.holen(eintrag["id"])
    assert pfad.read_bytes() == b"%PDF-1.4 ..."


def test_the_tool_list_names_both_places_the_file_lands():
    import json
    from pathlib import Path

    katalog = Path(__file__).resolve().parents[1] / "app" / "locales"
    satz = {
        sprache: json.loads((katalog / f"{sprache}.json").read_text(encoding="utf-8"))
        ["werkzeuge"]["eingebaut_satz"]["deliver_file"]
        for sprache in ("en", "de")
    }
    assert satz["en"] == (
        "Hands you a finished file: in a chat it appears in the response, from a task it "
        "lands in the doc folder."
    )
    assert satz["de"] == (
        "Übergibt dir eine fertige Datei: im Chat erscheint sie in der Antwort, aus einer "
        "Aufgabe landet sie im Doc-Ordner."
    )


async def test_werkzeug_kopiert_datei_aus_der_freigabe(tmp_path):
    dock = AgentenDock(tmp_path / "daten")
    freigabe = tmp_path / "arbeit"
    freigabe.mkdir()
    (freigabe / "bild.png").write_bytes(b"\x89PNG...")

    await werkzeug.ausfuehren(
        {"name": "bild.png", "path": "bild.png"},
        dock, [str(freigabe)], herkunft="agent", agent=AGENT,
    )
    (eintrag,) = dock.alle()
    _, pfad = dock.holen(eintrag["id"])
    assert pfad.read_bytes() == b"\x89PNG..."


async def test_beide_wege_legen_den_typ_ab(tmp_path):
    """``content`` and ``path`` both land with a usable type — the picture
    path is the one the chat's image check depends on."""
    dock = AgentenDock(tmp_path / "daten")
    freigabe = tmp_path / "arbeit"
    freigabe.mkdir()
    (freigabe / "bild.png").write_bytes(b"\x89PNG...")

    await werkzeug.ausfuehren(
        {"name": "bericht.md", "content": "# Report"},
        dock, [str(freigabe)], herkunft="agent", agent=AGENT,
    )
    await werkzeug.ausfuehren(
        {"name": "bild.png", "path": "bild.png"},
        dock, [str(freigabe)], herkunft="agent", agent=AGENT,
    )
    assert [e["typ"] for e in dock.alle()] == ["text/markdown", "image/png"]


async def test_werkzeug_verweigert_pfad_ausserhalb_der_freigabe(tmp_path):
    dock = AgentenDock(tmp_path / "daten")
    freigabe = tmp_path / "arbeit"
    freigabe.mkdir()
    draussen = tmp_path / "geheim.txt"
    draussen.write_text("x", encoding="utf-8")

    with pytest.raises(AblageVerboten, match="outside"):
        await werkzeug.ausfuehren(
            {"name": "geheim.txt", "path": str(draussen)},
            dock, [str(freigabe)], herkunft="agent", agent=AGENT,
        )
    assert dock.alle() == []


async def test_a_chat_call_with_no_chat_to_keep_the_file_in_is_refused(tmp_path):
    """A chat delivers into itself. Where nothing can keep the file there —
    no chat named, or no way to store it — the call is refused in words
    and the shelf, which is the jobs', stays empty."""
    dock = AgentenDock(tmp_path)
    with pytest.raises(AblageVerboten, match="no conversation to deliver to"):
        await werkzeug.ausfuehren(
            {"name": "x.md", "content": "x"}, dock, [], herkunft="chat", agent=None,
        )
    with pytest.raises(AblageVerboten, match="no conversation to deliver to"):
        await werkzeug.ausfuehren(
            {"name": "x.md", "content": "x"}, dock, [], herkunft="chat", agent=None,
            chat_delivery=lambda **_given: None,
        )
    assert dock.alle() == []


async def test_a_call_with_neither_a_job_nor_a_chat_behind_it_is_refused(tmp_path):
    dock = AgentenDock(tmp_path)
    with pytest.raises(AblageVerboten, match="neither"):
        await werkzeug.ausfuehren(
            {"name": "x.md", "content": "x"}, dock, [], herkunft="agent", agent=None,
        )
    assert dock.alle() == []


async def test_werkzeug_will_genau_eine_quelle(tmp_path):
    dock = AgentenDock(tmp_path)
    with pytest.raises(AblageVerboten, match="exactly one"):
        await werkzeug.ausfuehren(
            {"name": "x.md"}, dock, [], herkunft="agent", agent=AGENT,
        )
    with pytest.raises(AblageVerboten, match="exactly one"):
        await werkzeug.ausfuehren(
            {"name": "x.md", "content": "x", "path": "y"},
            dock, [], herkunft="agent", agent=AGENT,
        )


# --- The registry gate -------------------------------------------------------


def test_ohne_dock_gibt_es_das_werkzeug_nicht(tmp_path):
    ohne = WerkzeugRegistry([])
    assert werkzeug.WERKZEUG_NAME not in ohne.namen()
    assert ohne._merkmal_abgeschaltet(werkzeug.WERKZEUG_NAME) is True

    mit = WerkzeugRegistry([], agentendock=AgentenDock(tmp_path))
    assert werkzeug.WERKZEUG_NAME in mit.namen()
    assert mit._merkmal_abgeschaltet(werkzeug.WERKZEUG_NAME) is False
    angeboten = {
        w["function"]["name"] for w in mit.als_openai_werkzeuge(for_job=True)
    }
    assert werkzeug.WERKZEUG_NAME in angeboten


def _namen(registry, **kwargs):
    return [w["function"]["name"] for w in registry.als_openai_werkzeuge(**kwargs)]


def test_a_chat_is_offered_it_where_the_chat_can_keep_the_file(tmp_path):
    """A chat's list carries it as soon as there is a way to keep a file in
    a chat — and not before: offered without one, the user would be asked
    to allow a call that is refused the moment they say yes.

    The lists are checked EXACTLY, the way test_shell_werkzeug.py does it: a
    bare "in" would stay green if the offering fell apart around it.
    """
    without = WerkzeugRegistry([], agentendock=AgentenDock(tmp_path))
    assert _namen(without) == ["goal", "get_current_time"]

    registry = WerkzeugRegistry(
        [], agentendock=AgentenDock(tmp_path), chat_delivery=lambda **_given: None
    )
    assert _namen(registry) == ["goal", "get_current_time", werkzeug.WERKZEUG_NAME]
    # The note of a schedule stays what it was: a chat has no entry for it.
    assert "cron_note" not in _namen(
        WerkzeugRegistry([], agentendock=AgentenDock(tmp_path), cronjobs_repo=object(),
                         chat_delivery=lambda **_given: None)
    )


def _description(registry, **kwargs):
    offer = registry.als_openai_werkzeuge(**kwargs)
    return next(w for w in offer if w["function"]["name"] == werkzeug.WERKZEUG_NAME)["function"]


def test_each_list_is_told_where_its_file_lands(tmp_path):
    """A chat is told the file shows as a card in its answer, a job that it
    goes to the doc folder — neither hears the other's place."""
    registry = WerkzeugRegistry(
        [], agentendock=AgentenDock(tmp_path), chat_delivery=lambda **_given: None
    )
    in_chat = _description(registry)
    in_job = _description(registry, for_job=True)

    assert "card in your answer" in in_chat["description"]
    assert "doc folder" not in in_chat["description"]
    assert "card" in in_chat["parameters"]["properties"]["name"]["description"]
    assert "this job" not in str(in_chat)

    assert "doc folder" in in_job["description"]
    assert "card" not in str(in_job)
    assert in_chat["parameters"]["required"] == in_job["parameters"]["required"] == ["name"]


def test_im_auftragslauf_wird_es_angeboten(tmp_path):
    registry = WerkzeugRegistry([], agentendock=AgentenDock(tmp_path))
    assert _namen(registry, for_job=True) == [
        "goal", "get_current_time", werkzeug.WERKZEUG_NAME,
    ]


def test_ohne_dock_gibt_es_es_auch_im_lauf_nicht():
    """Same convention as every other equipped tool: no shelf, no tool —
    even in a run that would otherwise be offered it."""
    registry = WerkzeugRegistry([])
    assert werkzeug.WERKZEUG_NAME not in _namen(registry, for_job=True)
    assert werkzeug.WERKZEUG_NAME not in registry.namen()


def test_abgeschaltet_verschwindet_es_aus_dem_angebot(tmp_path):
    registry = WerkzeugRegistry([], agentendock=AgentenDock(tmp_path))
    registry.abgeschaltet = {werkzeug.WERKZEUG_NAME}
    assert werkzeug.WERKZEUG_NAME not in _namen(registry, for_job=True)


def test_ein_agent_der_es_nicht_nennt_bekommt_es_nicht(tmp_path):
    """The per-run allowlist (6.3) reaches it like every other tool."""
    registry = WerkzeugRegistry([], agentendock=AgentenDock(tmp_path))
    assert werkzeug.WERKZEUG_NAME not in _namen(
        registry, nur={"goal"}, for_job=True
    )
    assert werkzeug.WERKZEUG_NAME in _namen(
        registry, nur={werkzeug.WERKZEUG_NAME}, for_job=True
    )


def test_es_steht_weiter_in_der_werkzeugliste_der_maske(tmp_path):
    """Not offered is not the same as not switchable: the settings window
    lists it, or it would be the one tool nobody can switch off."""
    registry = WerkzeugRegistry([], agentendock=AgentenDock(tmp_path))
    assert werkzeug.WERKZEUG_NAME in registry.namen()
    assert werkzeug.WERKZEUG_NAME in [e["name"] for e in registry.uebersicht()]


# --- A chat's own delivery ---------------------------------------------------


def _chat_registry(client):
    """The registry as the service builds it (app/tools/aufbau.py), so the
    line that hands it the way into a chat is part of what is tested."""
    from pathlib import Path

    from app.tools.aufbau import registry_bauen

    config = client.app.state.config
    config.mcp.servers_file = str(Path(config.app.data_dir) / "no_servers.json")
    return registry_bauen(client.app, config)


def _answer_row(client, chat_id):
    return client.app.state.repositories.messages.speichern(
        chat_id=chat_id, role="assistant", content="", zustand="laeuft"
    )


async def test_a_chat_call_keeps_the_file_in_the_chat_on_its_answer(client, chat_id):
    """The chat's model hands a file over: it becomes a document of this
    chat, kept in the chat's own folder, and hangs on the answer being
    written — where the message list shows it as a card and the file route
    serves it. Nothing goes onto the shelf."""
    from pathlib import Path

    from app import dokumentablage

    repositories = client.app.state.repositories
    config = client.app.state.config
    answer = _answer_row(client, chat_id)

    result = await _chat_registry(client).ausfuehren(
        werkzeug.WERKZEUG_NAME,
        {"name": "notes.md", "content": "# Notes"},
        chat_id=chat_id,
        antwort_id=answer.id,
    )

    [document_id] = repositories.messages.holen(answer.id).dokument_ids()
    document = repositories.documents.holen(document_id)
    assert document.chat_id == chat_id
    assert document.filename == "notes.md"
    assert document.mime_type == "text/markdown"
    assert document.agent is None and document.job is None
    folder = dokumentablage.chatordner(config.datenverzeichnis, chat_id)
    assert Path(document.pfad).parent == folder.resolve()
    assert Path(document.pfad).read_bytes() == b"# Notes"
    assert "Delivered 'notes.md' to the user in this conversation" in result
    assert document.pfad in result
    assert dock_fuer(config).alle() == []

    page = client.get(f"/api/v1/chats/{chat_id}/messages").json()
    row = next(m for m in page["nachrichten"] if m["id"] == answer.id)
    assert row["dokument"]["id"] == document_id
    assert row["dokument"]["name"] == "notes.md"
    assert row["dokument"]["typ"] == "md"

    served = client.get(f"/api/v1/documents/{document_id}/file")
    assert served.status_code == 200
    assert served.content == b"# Notes"
    assert served.headers["content-type"].startswith("text/markdown")


async def test_a_second_delivery_joins_the_first_on_the_same_answer(client, chat_id):
    """Two files in one answer are two cards on it, in the order they came,
    and the row tells both of its readers the same: the first in the scalar,
    all of them in the list."""
    repositories = client.app.state.repositories
    answer = _answer_row(client, chat_id)
    registry = _chat_registry(client)

    for name in ("first.md", "second.csv"):
        await registry.ausfuehren(
            werkzeug.WERKZEUG_NAME,
            {"name": name, "content": name},
            chat_id=chat_id,
            antwort_id=answer.id,
        )

    row = repositories.messages.holen(answer.id)
    names = [repositories.documents.holen(d).filename for d in row.dokument_ids()]
    assert names == ["first.md", "second.csv"]
    assert row.dokument == row.dokument_ids()[0]
    page = client.get(f"/api/v1/chats/{chat_id}/messages").json()
    listed = next(m for m in page["nachrichten"] if m["id"] == answer.id)
    assert [card["name"] for card in listed["dokumente"]] == names


async def test_the_same_file_twice_in_one_answer_is_one_card(client, chat_id):
    """A model that repeats its call after its own result gets the document
    it already delivered. Other bytes under the same name are another file."""
    repositories = client.app.state.repositories
    answer = _answer_row(client, chat_id)
    registry = _chat_registry(client)

    async def deliver(text):
        return await registry.ausfuehren(
            werkzeug.WERKZEUG_NAME,
            {"name": "notes.md", "content": text},
            chat_id=chat_id,
            antwort_id=answer.id,
        )

    first = await deliver("# Notes")
    assert await deliver("# Notes") == first
    assert len(repositories.messages.holen(answer.id).dokument_ids()) == 1
    assert len(repositories.documents.auflisten(chat_id=chat_id)) == 1

    await deliver("# Other notes")
    assert len(repositories.messages.holen(answer.id).dokument_ids()) == 2


async def test_a_delivery_whose_answer_is_gone_still_keeps_the_file(client, chat_id):
    """The row can vanish while the run still calls — the user deleted the
    answer. The file is kept in the chat all the same, and nothing fails."""
    repositories = client.app.state.repositories

    result = await _chat_registry(client).ausfuehren(
        werkzeug.WERKZEUG_NAME,
        {"name": "notes.md", "content": "# Notes"},
        chat_id=chat_id,
        antwort_id="no-such-row",
    )

    [document] = repositories.documents.auflisten(chat_id=chat_id)
    assert document.filename == "notes.md"
    assert "Delivered 'notes.md'" in result


async def test_a_chat_delivers_a_file_of_its_folders_and_none_from_outside(
    client, chat_id, tmp_path
):
    """``path`` copies a file the chat may read; a path outside its folders
    is refused as it is in a job, and nothing is kept."""
    from app.tools.registry import WerkzeugVerboten

    repositories = client.app.state.repositories
    shared = tmp_path / "work"
    shared.mkdir()
    (shared / "table.csv").write_bytes(b"a;b")
    outside = tmp_path / "secret.txt"
    outside.write_text("x", encoding="utf-8")
    answer = _answer_row(client, chat_id)
    registry = _chat_registry(client)

    await registry.ausfuehren(
        werkzeug.WERKZEUG_NAME,
        {"name": "table.csv", "path": "table.csv"},
        ordner=[str(shared)],
        chat_id=chat_id,
        antwort_id=answer.id,
    )
    with pytest.raises(WerkzeugVerboten, match="outside"):
        await registry.ausfuehren(
            werkzeug.WERKZEUG_NAME,
            {"name": "secret.txt", "path": str(outside)},
            ordner=[str(shared)],
            chat_id=chat_id,
            antwort_id=answer.id,
        )

    [document] = repositories.documents.auflisten(chat_id=chat_id)
    assert document.filename == "table.csv"
    # A copy in the chat's own folder: the file in the user's folder is theirs.
    assert document.pfad != str((shared / "table.csv").resolve())
    assert (shared / "table.csv").read_bytes() == b"a;b"
    assert repositories.messages.holen(answer.id).dokument_ids() == [document.id]


def _file_in_chat_folder(client, chat_id, relative, data=b"\xff\xd8\xff"):
    """A file the model wrote into the chat's own folder — in a subfolder
    where ``relative`` has one — the way ``run_command`` leaves it."""
    from app import dokumentablage

    folder = dokumentablage.chatordner(client.app.state.config.datenverzeichnis, chat_id)
    file = folder / relative
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(data)
    return folder, file


def _files_below(folder):
    return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file())


async def test_a_file_that_lies_in_the_chat_folder_is_delivered_where_it_lies(client, chat_id):
    """No copy into the folder's root: the row points at the file, the folder
    holds one file and the wall shows one tile for it."""
    repositories = client.app.state.repositories
    folder, file = _file_in_chat_folder(client, chat_id, "dogs/dog-1.jpg")
    answer = _answer_row(client, chat_id)

    result = await _chat_registry(client).ausfuehren(
        werkzeug.WERKZEUG_NAME,
        {"name": "dog-1.jpg", "path": "dogs/dog-1.jpg"},
        ordner=[str(folder)],
        chat_id=chat_id,
        antwort_id=answer.id,
    )

    [document] = repositories.documents.auflisten(chat_id=chat_id)
    assert document.pfad == str(file.resolve())
    assert document.mime_type == "image/jpeg"
    assert _files_below(folder) == ["dogs/dog-1.jpg"]
    assert repositories.messages.holen(answer.id).dokument_ids() == [document.id]
    assert document.pfad in result
    wall = client.get("/api/v1/doc-folder", params={"chat": chat_id}).json()
    assert len(wall) == 1


async def test_a_job_started_from_a_chat_delivers_a_file_of_its_folder_where_it_lies(
    client, chat_id
):
    repositories = client.app.state.repositories
    folder, file = _file_in_chat_folder(client, chat_id, "dogs/dog-2.jpg")
    job = repositories.auftraege.erstellen(
        user_id="lokal", agent=AGENT.name, auftrag="deliver", chat_id=chat_id
    )

    await _chat_registry(client).ausfuehren(
        werkzeug.WERKZEUG_NAME,
        {"name": "dog-2.jpg", "path": "dogs/dog-2.jpg"},
        herkunft="agent",
        agent=AGENT,
        ordner=[str(folder)],
        chat_id=job.id,
    )

    [document] = repositories.documents.auflisten(chat_id=chat_id)
    assert document.pfad == str(file.resolve())
    assert document.job == job.id
    assert _files_below(folder) == ["dogs/dog-2.jpg"]
    assert len(client.get("/api/v1/doc-folder", params={"chat": chat_id}).json()) == 1


async def test_a_file_from_another_folder_is_still_copied_into_the_chat_folder(
    client, chat_id, tmp_path
):
    """The silence check: only what already lies in the chat's own folder is
    kept in place. A file of a shared folder of the user's is copied, and
    the original is left as it is."""
    repositories = client.app.state.repositories
    folder, _ = _file_in_chat_folder(client, chat_id, "dogs/dog-3.jpg")
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "dog-4.jpg").write_bytes(b"\xff\xd8\xfe")
    answer = _answer_row(client, chat_id)

    await _chat_registry(client).ausfuehren(
        werkzeug.WERKZEUG_NAME,
        {"name": "dog-4.jpg", "path": "dog-4.jpg"},
        ordner=[str(shared), str(folder)],
        chat_id=chat_id,
        antwort_id=answer.id,
    )

    [document] = repositories.documents.auflisten(chat_id=chat_id)
    assert document.pfad == str((folder / "dog-4.jpg").resolve())
    assert _files_below(folder) == ["dog-4.jpg", "dogs/dog-3.jpg"]
    assert (shared / "dog-4.jpg").read_bytes() == b"\xff\xd8\xfe"


async def test_content_is_still_written_into_the_chat_folder(client, chat_id):
    repositories = client.app.state.repositories
    folder, _ = _file_in_chat_folder(client, chat_id, "dogs/dog-5.jpg")
    answer = _answer_row(client, chat_id)

    await _chat_registry(client).ausfuehren(
        werkzeug.WERKZEUG_NAME,
        {"name": "notes.md", "content": "# Notes"},
        ordner=[str(folder)],
        chat_id=chat_id,
        antwort_id=answer.id,
    )

    [document] = repositories.documents.auflisten(chat_id=chat_id)
    assert document.pfad == str((folder / "notes.md").resolve())
    assert _files_below(folder) == ["dogs/dog-5.jpg", "notes.md"]


async def test_the_same_file_of_the_chat_folder_twice_in_one_answer_is_one_card(client, chat_id):
    repositories = client.app.state.repositories
    folder, _ = _file_in_chat_folder(client, chat_id, "dogs/dog-6.jpg")
    answer = _answer_row(client, chat_id)
    registry = _chat_registry(client)

    for _ in range(2):
        await registry.ausfuehren(
            werkzeug.WERKZEUG_NAME,
            {"name": "dog-6.jpg", "path": "dogs/dog-6.jpg"},
            ordner=[str(folder)],
            chat_id=chat_id,
            antwort_id=answer.id,
        )

    assert len(repositories.messages.holen(answer.id).dokument_ids()) == 1
    assert len(repositories.documents.auflisten(chat_id=chat_id)) == 1
    assert _files_below(folder) == ["dogs/dog-6.jpg"]


async def test_a_job_without_a_chat_still_delivers_onto_the_dock(client):
    """The silence check for the jobs' side: nothing about a job's delivery
    moved. Without a chat behind it the file lands on the shelf, with the
    agent's name, and no document row is written."""
    repositories = client.app.state.repositories
    config = client.app.state.config
    job = repositories.auftraege.erstellen(
        user_id="lokal", agent=AGENT.name, auftrag="deliver", chat_id=None
    )

    result = await _chat_registry(client).ausfuehren(
        werkzeug.WERKZEUG_NAME,
        {"name": "report.md", "content": "# Report"},
        herkunft="agent",
        agent=AGENT,
        chat_id=job.id,
    )

    [entry] = dock_fuer(config).alle()
    assert entry["name"] == "report.md" and entry["agent"] == AGENT.name
    assert "to the agent dock" in result
    assert repositories.documents.for_folder() == []


def test_a_chats_delivery_goes_through_the_gate_like_every_other_tool(client):
    """No way of its own through the gate: the mode the user set decides. As
    shipped a chat's call runs; where the chat asks first, this one is asked
    about too, and the same rule file can refuse it by name."""
    import json as json_module
    from pathlib import Path

    config = client.app.state.config
    registry = _chat_registry(client)
    call = {"name": "notes.md", "content": "# Notes"}
    assert registry.urteil(werkzeug.WERKZEUG_NAME, call).antwort == "ja"

    rules = Path(config.pfad(config.app.berechtigungen_datei))
    rules.write_text(
        json_module.dumps({"standard": {"chat": "fragen", "agent": "ja"}}), encoding="utf-8"
    )
    assert registry.urteil(werkzeug.WERKZEUG_NAME, call).antwort == "fragen"
    assert registry.braucht_bestaetigung(werkzeug.WERKZEUG_NAME, call) is True

    rules.write_text(
        json_module.dumps({"regeln": {werkzeug.WERKZEUG_NAME: "nein"}}), encoding="utf-8"
    )
    assert registry.urteil(werkzeug.WERKZEUG_NAME, call).antwort == "nein"


def _chat_run_that_delivers(client, chat_id, call):
    """One answer of the chat whose model makes this one call, through the
    whole run (app/api/v1/generierung.py); returns the stream's events and
    the provider, which keeps the request it was sent."""
    import json as json_module
    from pathlib import Path

    from app.providers import mock_endpunkt
    from app.providers.base import Werkzeugaufruf
    from tests.conftest import provider_setzen

    config = client.app.state.config
    # A chat that may call without being asked: the prompt is the gate's own
    # test above, and a run waiting for a yes would never end here.
    Path(config.pfad(config.app.berechtigungen_datei)).write_text(
        json_module.dumps({"standard": {"chat": "ja", "agent": "ja"}}), encoding="utf-8"
    )
    config.features.mcp = True
    client.app.state.werkzeuge = _chat_registry(client)
    client.app.state.discovery.zustaende["test"].endpunkt.capabilities.tool_calls = True
    provider = provider_setzen(
        client,
        MockProvider(
            mock_endpunkt("test"),
            haeppchen=["Here it is."],
            werkzeugaufrufe=[
                Werkzeugaufruf(id="d1", name=werkzeug.WERKZEUG_NAME, argumente=call)
            ],
        ),
    )
    answer = client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "Write it down for me."},
    )
    events = [
        json_module.loads(line[5:].strip())
        for line in answer.text.splitlines()
        if line.startswith("data:")
    ]
    return events, provider


def test_a_chats_answer_carries_the_file_its_model_delivered(client, chat_id):
    """The whole way: the chat's model is offered the tool with the chat's
    own words, calls it, and the answer it writes carries the file — in the
    stream at once, on the row for every later read."""
    events, provider = _chat_run_that_delivers(
        client, chat_id, {"name": "notes.md", "content": "# Notes"}
    )

    offered = {
        w["function"]["name"]: w["function"] for w in provider.alle_anfragen[0].werkzeuge
    }
    assert "card in your answer" in offered[werkzeug.WERKZEUG_NAME]["description"]
    # And the prompt's overview names the same place, not the jobs' folder.
    system = " ".join(str(provider.alle_anfragen[0].nachrichten[0].content).split())
    assert "deliver completed files to the user as cards in the response" in system
    assert "into the Doc folder" not in system

    result = next(e for e in events if e["typ"] == "tool_result")
    assert result["name"] == werkzeug.WERKZEUG_NAME and not result["fehlgeschlagen"]
    [card] = result["dokumente"]
    assert card["name"] == "notes.md" and card["typ"] == "md"

    repositories = client.app.state.repositories
    rows = repositories.messages.auflisten(chat_id=chat_id)
    answer = next(r for r in rows if r.role == "assistant")
    assert answer.zustand == "fertig"
    assert answer.dokument_ids() == [card["id"]]
    assert client.get(f"/api/v1/documents/{card['id']}/file").content == b"# Notes"


def test_a_delivered_file_is_in_no_later_request_and_its_card_claims_none(client, chat_id):
    """The file hangs on the answer as a file. The next request carries no
    text of it — the model knows what it wrote from its own call — and the
    card is told nothing about the context, which it is not in."""
    from app.providers import mock_endpunkt
    from tests.conftest import provider_setzen

    _chat_run_that_delivers(client, chat_id, {"name": "notes.md", "content": "# Notes"})
    provider = provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["Yes."]))
    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "And now."},
    )

    sent = "\n".join(str(n.content or "") for n in provider.letzte_anfrage.nachrichten)
    assert "Attached document" not in sent
    page = client.get(f"/api/v1/chats/{chat_id}/messages").json()
    [card] = [m["dokument"] for m in page["nachrichten"] if m.get("dokument")]
    assert card["name"] == "notes.md" and card["getragen"] is None


# --- The API ----------------------------------------------------------------


def test_api_liste_datei_und_entfernen(client):
    dock = dock_fuer(client.app.state.config)
    eintrag = dock.ablegen("bericht.md", b"# Report", typ="text/markdown", agent="recherche")

    liste = client.get("/api/v1/agentendock/alle").json()
    assert [e["id"] for e in liste] == [eintrag["id"]]
    assert liste[0]["agent"] == "recherche"

    antwort = client.get(f"/api/v1/agentendock/{eintrag['id']}")
    assert antwort.status_code == 200
    assert antwort.content == b"# Report"

    assert client.delete(f"/api/v1/agentendock/{eintrag['id']}").status_code == 204
    assert client.get("/api/v1/agentendock/alle").json() == []
    assert client.get(f"/api/v1/agentendock/{eintrag['id']}").status_code == 404


def test_ein_pdf_vom_dock_wird_an_ort_und_stelle_gezeigt_alles_andere_gespeichert(client):
    """The reader's frame draws a PDF's pages only for an answer that says
    "inline", the way the routes of a chat's documents say it. Every other
    type stays "attachment": a page of the shelf is never served in place."""
    dock = dock_fuer(client.app.state.config)
    offered = {
        "scan.pdf": ("application/pdf", b"%PDF-1.4"),
        "seite.html": ("text/html", b"<p>x</p>"),
        "bild.png": ("image/png", b"\x89PNG"),
        "notiz.md": ("text/markdown", b"# x"),
    }
    ids = {name: dock.ablegen(name, daten, typ=typ)["id"] for name, (typ, daten) in offered.items()}

    heads = {
        name: client.get(f"/api/v1/agentendock/{kennung}").headers["content-disposition"]
        for name, kennung in ids.items()
    }

    assert heads["scan.pdf"].startswith("inline")
    for name in ("seite.html", "bild.png", "notiz.md"):
        assert heads[name].startswith("attachment"), name


def _abgelegt(client, name, typ, chat=""):
    """A file dropped through the route, with the type header as given."""
    abfrage = f"name={name}" + (f"&chat={chat}" if chat else "")
    kopf = {"Content-Type": typ} if typ else {}
    antwort = client.post(f"/api/v1/agentendock?{abfrage}", content=b"\xff\xd8\xff", headers=kopf)
    assert antwort.status_code == 201, antwort.text
    return antwort.json()


def test_eine_abgelegte_datei_ohne_brauchbaren_typ_bekommt_ihn_aus_dem_namen(client):
    """The browser leaves the type empty where it does not know the ending,
    and the page then sends octet-stream. A picture dropped that way has to
    stand as a picture: the name decides, as for every delivery."""
    assert _abgelegt(client, "foto.jpg", "application/octet-stream")["typ"] == "image/jpeg"
    # A header with parameters is the same word; the name still decides.
    assert (
        _abgelegt(client, "foto.png", "application/octet-stream; charset=binary")["typ"]
        == "image/png"
    )
    # A drop into a chat is a document of the chat, under the same type.
    chat = client.post("/api/v1/chats", json={"title": "Drop"}).json()["id"]
    in_chat = _abgelegt(client, "foto.jpg", "application/octet-stream", chat)
    assert in_chat["typ"] == "image/jpeg"


def test_ein_mitgegebener_typ_und_ein_unbekannter_name_bleiben_wie_sie_waren(client):
    # A type that came with the file stays, whatever the name says.
    assert _abgelegt(client, "foto.jpg", "image/png")["typ"] == "image/png"
    assert _abgelegt(client, "notiz.txt", "text/plain; charset=utf-8")["typ"].startswith("text/plain")
    # No ending, nothing to read off: no picture type, as before.
    assert _abgelegt(client, "ohne", "application/octet-stream")["typ"] == ""
    assert _abgelegt(client, "archiv.jpg.gz", "application/octet-stream")["typ"] == ""


def test_alter_eintrag_ohne_typ_bleibt_bedienbar(client):
    """Files delivered before the shelf knew about types keep an empty
    ``typ`` in agentendock.json. They must still list and download — just
    as octet-stream, exactly as they did before."""
    dock = dock_fuer(client.app.state.config)
    eintrag = dock.ablegen("alt.png", b"\x89PNG", agent="recherche")
    liste = dock.alle()
    liste[0]["typ"] = ""
    dock._schreiben(liste)

    gelistet = client.get("/api/v1/agentendock/alle").json()
    assert gelistet[0]["typ"] == ""
    antwort = client.get(f"/api/v1/agentendock/{eintrag['id']}")
    assert antwort.status_code == 200
    assert antwort.content == b"\x89PNG"
    assert antwort.headers["content-type"] == "application/octet-stream"
    assert client.delete(f"/api/v1/agentendock/{eintrag['id']}").status_code == 204


# --- The one call site: a job's own tool list -------------------------------


def test_der_auftragslauf_bietet_es_wirklich_an(config):
    """The gate above only holds if somebody switches it on.

    A job's list is built in one place (app/api/v1/auftraege.py), and the
    tests above call the registry themselves. A run that never reached the
    tool would leave every one of them green — which is what this one is
    here to catch. Measured the same way live: the run's own log names what
    it was offered.
    """
    import time
    from pathlib import Path

    from fastapi.testclient import TestClient

    from app.main import app_erstellen
    from app.providers import MockProvider, mock_endpunkt
    from tests.conftest import provider_setzen

    config.features.mcp = True
    config.mcp.servers_file = str(Path(config.app.data_dir) / "keine_server.json")
    ordner = Path(config.app.agenten_verzeichnis)
    ordner.mkdir(parents=True, exist_ok=True)
    (ordner / "ableger.md").write_text(
        f"---\ntools: [{werkzeug.WERKZEUG_NAME}]\n---\n\nLegt ab.\n", encoding="utf-8"
    )

    with TestClient(app_erstellen(config)) as client:
        client.headers["X-Sitzungsschluessel"] = client.app.state.sitzungsschluessel
        client.app.state.discovery.zustaende["test"].endpunkt.capabilities.tool_calls = True
        provider_setzen(client, MockProvider(mock_endpunkt("test")))

        kennung = client.post(
            "/api/v1/jobs", json={"agent": "ableger", "task": "Los"}
        ).json()["id"]
        frist = time.time() + 8
        while time.time() < frist:
            daten = client.get(f"/api/v1/jobs/{kennung}").json()
            if daten.get("state") in {"fertig", "abgebrochen", "gescheitert", "unterbrochen"}:
                break
            time.sleep(0.05)

    angeboten = [
        s["inhalt"] for s in daten["schritte"]
        if s["typ"] == "status" and s["inhalt"].startswith("Werkzeuge angeboten:")
    ]
    # The clock rides along in every run that has tools (app/api/v1/auftraege.py,
    # the same widening the shelf itself gets) — the shelf is what this test
    # is about, and it is there.
    assert angeboten == [
        f"Werkzeuge angeboten: {werkzeug.WERKZEUG_NAME}, get_current_time"
    ]


# --- A delivery that never arrived is not a finished run ---------------------


def _lauf_mit_ablage(config, aufrufe, task="Los"):
    """Runs one job whose model makes exactly these ``deliver_file`` calls,
    and hands back the finished job. The harness of the offering test above,
    with the model actually calling instead of only being offered."""
    import time
    from pathlib import Path

    from fastapi.testclient import TestClient

    from app.main import app_erstellen
    from app.providers import MockProvider, mock_endpunkt
    from tests.conftest import provider_setzen

    config.features.mcp = True
    config.mcp.servers_file = str(Path(config.app.data_dir) / "keine_server.json")
    ordner = Path(config.app.agenten_verzeichnis)
    ordner.mkdir(parents=True, exist_ok=True)
    (ordner / "ableger.md").write_text(
        f"---\ntools: [{werkzeug.WERKZEUG_NAME}]\n---\n\nLegt ab.\n", encoding="utf-8"
    )

    with TestClient(app_erstellen(config)) as client:
        client.headers["X-Sitzungsschluessel"] = client.app.state.sitzungsschluessel
        client.app.state.discovery.zustaende["test"].endpunkt.capabilities.tool_calls = True
        provider_setzen(client, MockProvider(mock_endpunkt("test"), werkzeugaufrufe=aufrufe))

        kennung = client.post(
            "/api/v1/jobs", json={"agent": "ableger", "task": task}
        ).json()["id"]
        frist = time.time() + 8
        while time.time() < frist:
            daten = client.get(f"/api/v1/jobs/{kennung}").json()
            if daten.get("state") in {"fertig", "abgebrochen", "gescheitert", "unterbrochen"}:
                break
            time.sleep(0.05)
    return daten


def _ende(daten):
    return [s["inhalt"] for s in daten["schritte"] if s["typ"] == "ende"]


def _ablage_ruf(kennung, groesse, name=None):
    from app.providers.base import Werkzeugaufruf

    return Werkzeugaufruf(
        id=kennung,
        name=werkzeug.WERKZEUG_NAME,
        argumente={"name": name or f"{kennung}.md", "content": "x" * groesse},
    )


def test_ein_lauf_dessen_ablage_nicht_ankam_meldet_keinen_erfolg(config, monkeypatch):
    """Without this check the shelf refused the delivery,
    the refusal stood at one step of the log, and the run ended "fertig" —
    with `deliver: 'log'` on a schedule the user was never told the report
    was gone. Nothing else about the run stopped, so nothing else could have
    said so."""
    import app.agentendock as modul

    monkeypatch.setattr(modul, "MAX_BYTES", 8)
    daten = _lauf_mit_ablage(config, [_ablage_ruf("zugross", 40)])

    assert daten["state"] == "gescheitert"
    assert _ende(daten) == [werkzeug.GRUND_NICHT_ABGELEGT]


def test_eine_angekommene_ablage_bleibt_ein_fertiger_lauf(config):
    """The other half, and the one that would break every normal run if the
    rule above were written as "a delivery was attempted"."""
    daten = _lauf_mit_ablage(config, [_ablage_ruf("klein", 8)])

    assert daten["state"] == "fertig"
    assert _ende(daten) == ["fertig"]


def test_eine_nachgeholte_ablage_zaehlt(config, monkeypatch):
    """Making good means the SAME file, and only that.

    The rule was written as the last call's verdict, whatever file it was
    about — so this test used to prove something else entirely: a refused
    ``zugross.md`` followed by a successful ``dann.md`` counted as "made
    good", and the run finished. That is not a model correcting itself, it
    is one file's success wiping out another file's loss.

    Kept as one test with both halves, because the two only mean anything
    beside each other: the same name after a refusal is a corrected call and
    must not cost the run its ending, and a different name is a second file
    that says nothing about the first.
    """
    import app.agentendock as modul

    monkeypatch.setattr(modul, "MAX_BYTES", 8)

    nachgeholt = _lauf_mit_ablage(
        config,
        [
            _ablage_ruf("zuerst", 40, name="bericht.md"),
            _ablage_ruf("dann", 4, name="bericht.md"),
        ],
    )
    assert nachgeholt["state"] == "fertig"
    assert _ende(nachgeholt) == ["fertig"]

    fremd = _lauf_mit_ablage(
        config,
        [
            _ablage_ruf("zuerst", 40, name="daten.csv"),
            _ablage_ruf("dann", 4, name="anderes.md"),
        ],
    )
    assert fremd["state"] == "gescheitert"
    assert _ende(fremd) == [werkzeug.GRUND_NICHT_ABGELEGT]


def test_von_drei_ablagen_reicht_die_mittlere(config, monkeypatch):
    """The whole case: a report that lands, a table that
    is refused, a note that lands. The flag read the note's success as
    the run's verdict and the run ended "fertig" — with the table gone and
    one line of the step log the only place saying so.

    The ending has to be about the FILE, so one name still open is enough."""
    import app.agentendock as modul

    monkeypatch.setattr(modul, "MAX_BYTES", 8)
    daten = _lauf_mit_ablage(
        config,
        [
            _ablage_ruf("a", 4, name="bericht.md"),
            _ablage_ruf("b", 40, name="daten.csv"),
            _ablage_ruf("c", 4, name="notiz.txt"),
        ],
    )

    assert daten["state"] == "gescheitert"
    assert _ende(daten) == [werkzeug.GRUND_NICHT_ABGELEGT]
    # And the two that did arrive really are on the shelf — the ending says
    # a file is missing, not that the run delivered nothing.
    dock = dock_fuer(config)
    assert {e["name"] for e in dock.alle()} == {"bericht.md", "notiz.txt"}


# --- And the loss survives a handoff -----------------------------------------


def test_der_block_geht_hin_und_zurueck():
    """The debt is written into the continuation's task and read back out of
    it — one text doing both jobs, so the memory and the instruction can
    never say different things."""
    aufgabe = zwischenstand.naechste_aufgabe(
        "Los", "## Done\n- eins", ["daten.csv", "bild.png"]
    )

    assert zwischenstand.offene_ablagen_lesen(aufgabe) == {"daten.csv", "bild.png"}
    # A run that owes nothing gets no block at all, and reading a plain task
    # finds nothing to owe.
    schlicht = zwischenstand.naechste_aufgabe("Los", "## Done\n- eins")
    assert zwischenstand.OFFENE_ABLAGE_KOPF not in schlicht
    assert zwischenstand.offene_ablagen_lesen(schlicht) == set()
    # The "Done" bullets right above it are not deliveries — the reader stops
    # at the next heading, exactly as ``erledigt_zaehlen`` does.
    assert zwischenstand.erledigt_zaehlen(aufgabe) == 1


class _AblageDannUeberlauf(MockProvider):
    """Delivers in the first round — refused — and only then reports a
    near-full context, which turns the run toward a handoff.

    The order matters and is the real one: a round crossing the threshold
    has its own tool calls DROPPED (app/api/v1/auftraege.py), so a provider
    that reports "full" in the same breath as its delivery never delivers at
    all. The loss this test is about needs the delivery to have really
    happened and really been refused.
    """

    def __init__(self, *args, dateiname: str, **kwargs):
        super().__init__(*args, **kwargs)
        self.dateiname = dateiname

    async def streamen(self, anfrage):
        from app.providers import Stueck
        from app.providers.base import Werkzeugaufruf

        self.letzte_anfrage = anfrage
        self.alle_anfragen.append(anfrage)
        self.durchlaeufe += 1
        letzte = anfrage.nachrichten[-1]
        if letzte.role == "user" and letzte.content == zwischenstand.ANFRAGE_TEXT:
            yield Stueck("content", text="## Task\nLos\n\n## Done\n- eins\n\n## Next\nweiter")
            return
        yield Stueck(
            "stats",
            daten={"nutzung": {"total_tokens": 100 if self.durchlaeufe == 1 else 950}},
        )
        yield Stueck(
            "tool_call",
            werkzeugaufrufe=[
                Werkzeugaufruf(
                    id=f"w{self.durchlaeufe}",
                    name=werkzeug.WERKZEUG_NAME,
                    argumente={"name": self.dateiname, "content": "x" * 40},
                )
            ],
        )


def test_der_fehlschlag_ueberlebt_den_kontextueberlauf(config, monkeypatch):
    """A refused delivery survives the context overflow, end to end.

    ``ablage_offen`` was a local in the run. Run 1 delivered, was refused,
    worked on, ran out of context and handed over — and run 2 opened knowing
    nothing about it: delivered nothing, ended "fertig", and the schedule
    booked a success for a file that never arrived. Nobody was ever told.

    Both halves are measured here: the continuation's own task names the
    file, and a run opening with that task and delivering nothing does not
    report success.
    """
    import time
    from pathlib import Path

    from fastapi.testclient import TestClient

    from app.main import app_erstellen
    from app.providers import mock_endpunkt
    from tests.conftest import provider_setzen

    import app.agentendock as modul

    monkeypatch.setattr(modul, "MAX_BYTES", 8)
    config.features.mcp = True
    config.mcp.servers_file = str(Path(config.app.data_dir) / "keine_server.json")
    ordner = Path(config.app.agenten_verzeichnis)
    ordner.mkdir(parents=True, exist_ok=True)
    (ordner / "ableger.md").write_text(
        f"---\ntools: [{werkzeug.WERKZEUG_NAME}]\n---\n\nLegt ab.\n", encoding="utf-8"
    )

    def bis_ende(client, kennung):
        frist = time.time() + 8
        while time.time() < frist:
            daten = client.get(f"/api/v1/jobs/{kennung}").json()
            if daten.get("state") in {"fertig", "abgebrochen", "gescheitert", "unterbrochen"}:
                return daten
            time.sleep(0.05)
        raise AssertionError("the job reached no end state")

    with TestClient(app_erstellen(config)) as client:
        client.headers["X-Sitzungsschluessel"] = client.app.state.sitzungsschluessel
        client.app.state.discovery.zustaende["test"].endpunkt.capabilities.tool_calls = True
        client.app.state.discovery.zustaende["test"].context_tokens = 1000
        provider_setzen(
            client, _AblageDannUeberlauf(mock_endpunkt("test"), dateiname="daten.csv")
        )

        erst = bis_ende(
            client,
            client.post(
                "/api/v1/jobs", json={"agent": "ableger", "task": "Los"}
            ).json()["id"],
        )
        # Handed on, not failed: the continuation below is already written.
        assert erst["state"] == "unterbrochen"
        assert _ende(erst) == ["kontext_voll"]

        # The continuation the handoff wrote — and it names the file.
        (kette,) = client.app.state.repositories.cronjobs.auflisten()
        assert "daten.csv" in kette.task
        assert zwischenstand.offene_ablagen_lesen(kette.task) == {"daten.csv"}

        # Run 2, opening with exactly that text and delivering nothing.
        provider_setzen(client, MockProvider(mock_endpunkt("test")))
        zweit = bis_ende(
            client,
            client.post(
                "/api/v1/jobs", json={"agent": "ableger", "task": kette.task}
            ).json()["id"],
        )

    assert zweit["state"] == "gescheitert"
    assert _ende(zweit) == [werkzeug.GRUND_NICHT_ABGELEGT]


def test_eine_nachgeholte_ablage_loescht_die_schuld_der_kette(config):
    """The other half, or the fix would brick the chain: a continuation that
    DOES deliver the owed file finishes normally. Without this the debt
    could never be paid and every further run of that chain would fail over
    a file nobody was able to hand in."""
    aufgabe = zwischenstand.naechste_aufgabe("Los", "## Done\n- eins", ["daten.csv"])
    daten = _lauf_mit_ablage(
        config, [_ablage_ruf("a", 4, name="daten.csv")], task=aufgabe
    )

    assert daten["state"] == "fertig"
    assert _ende(daten) == ["fertig"]
