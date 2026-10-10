"""A drawing job as an entry in the chat's little history."""

from __future__ import annotations

from app import bildlauf
from app.api.v1.befehle import _als_daten
from app.tools.hintergrund import ABGEBROCHEN, ART_BEFEHL, ART_BILD, FEHLER, FERTIG, laeufe


def test_ohne_chat_kein_eintrag():
    assert bildlauf.beginnen(None, "egal") is None
    # And closing that non-entry is allowed and does nothing.
    bildlauf.beenden(None)


def test_lauf_erscheint_und_endet_fertig():
    lauf = bildlauf.beginnen("chat-bild-1", "ein rotes Fahrrad im Regen")
    assert lauf is not None
    assert lauf.art == ART_BILD
    assert lauf.zustand == "laeuft"
    assert laeufe.laeufe("chat-bild-1")[-1].befehl == "ein rotes Fahrrad im Regen"

    bildlauf.beenden(lauf)
    assert lauf.zustand == FERTIG
    assert lauf.dauer_sekunden is not None and lauf.dauer_sekunden >= 0
    laeufe.vergessen("chat-bild-1")


def test_gescheiterter_lauf_ist_rot_abgebrochener_nicht():
    a = bildlauf.beginnen("chat-bild-2", "kaputt")
    bildlauf.beenden(a, gescheitert=True)
    assert a.zustand == FEHLER

    b = bildlauf.beginnen("chat-bild-2", "gestoppt")
    bildlauf.beenden(b, abgebrochen=True)
    assert b.zustand == ABGEBROCHEN
    laeufe.vergessen("chat-bild-2")


def test_befehlslaeufe_bleiben_befehle():
    """The registry learned a word, not a second behaviour."""
    lauf = laeufe.anlegen("chat-bild-3", "ls -la")
    assert lauf.art == ART_BEFEHL
    laeufe.beenden(lauf, code=0)
    assert lauf.zustand == FERTIG
    assert lauf.dauer_sekunden is not None
    laeufe.vergessen("chat-bild-3")


def test_langer_prompt_bleibt_ganz():
    """The 80-character cut is gone from the service — the surface shortens
    the line for display now, the same way it already does for a command."""
    lang = " ".join(["Fahrrad"] * 40)
    lauf = bildlauf.beginnen("chat-bild-lang", lang)
    assert laeufe.laeufe("chat-bild-lang")[-1].befehl == lang
    laeufe.vergessen("chat-bild-lang")


def test_ohne_wunsch_keine_regler():
    """A caller that never hands one over (none exists yet) gets a plain
    run, exactly as before — regler_von() says so honestly instead of
    guessing at defaults nobody chose."""
    lauf = bildlauf.beginnen("chat-bild-5", "ein Bild")
    assert bildlauf.regler_von("chat-bild-5", lauf.nummer) is None
    laeufe.vergessen("chat-bild-5")


def test_regler_zeigt_kerndaten_und_gesetztes():
    """The core dials (here: modell, seed) stand even at their default —
    everything else only if it was actually chosen, and routing fields
    (chat_id) are not a drawing choice at all."""
    wunsch = {
        "chat_id": "chat-bild-6",
        "lauf_chat": None,
        "modell": "irgendein-modell",
        "prompt": "ein Bild",
        "negativ": "",
        "breite": 512,
        "hoehe": 512,
        "schritte": 20,
        "cfg": 7.0,
        "seed": -1,
        "sampler": "euler_a",
        "scheduler": "normal",
        "loras": [],
        "hires": False,
        "hires_scale": 2.0,
        "control_net": None,
        "canny": True,
    }
    lauf = bildlauf.beginnen("chat-bild-6", "ein Bild", wunsch)
    regler = bildlauf.regler_von("chat-bild-6", lauf.nummer)
    assert regler["modell"] == "irgendein-modell"
    assert regler["seed"] == -1
    for weg in ("chat_id", "lauf_chat", "negativ", "loras", "hires", "hires_scale", "canny"):
        assert weg not in regler
    laeufe.vergessen("chat-bild-6")


def test_schnappschuss_traegt_regler_nur_fuer_bild():
    """A reload does not replay bildlauf's own event (see regler_von's own
    note) — the snapshot the reader actually gets has to ask for it
    directly instead, and only for the kind of run that has one."""
    bild = bildlauf.beginnen("chat-bild-7", "ein Bild", {"modell": "x", "chat_id": "chat-bild-7"})
    befehl = laeufe.anlegen("chat-bild-7", "ls -la")
    assert _als_daten(bild)["regler"] == {"modell": "x"}
    assert _als_daten(befehl)["regler"] is None
    laeufe.vergessen("chat-bild-7")


def test_zuschauer_erfahren_art_und_dauer():
    """What the terminal module draws has to arrive over the stream."""
    gesehen = []
    laeufe._zuschauer.setdefault("chat-bild-4", set())
    import asyncio

    schlange = asyncio.Queue()
    laeufe._zuschauer["chat-bild-4"].add(schlange)
    try:
        lauf = bildlauf.beginnen("chat-bild-4", "ein Bild")
        bildlauf.beenden(lauf)
        while not schlange.empty():
            gesehen.append(schlange.get_nowait())
    finally:
        laeufe._zuschauer["chat-bild-4"].discard(schlange)
        laeufe.vergessen("chat-bild-4")

    start = next(e for e in gesehen if e["typ"] == "lauf_start")
    ende = next(e for e in gesehen if e["typ"] == "lauf_ende")
    assert start["art"] == ART_BILD
    assert ende["dauer_sekunden"] is not None


def test_modell_und_dict_lesen_vorgaben_verschieden():
    """Two ways in, two readings — a decision, not an accident.

    A model can be asked which of its fields still stand at their OWN
    default; a bare dict carries no defaults and can only be asked whether a
    value looks filled in. `clip_skip=-1` is exactly that gap: the model's
    own default, and a plain non-zero number to a dict. `_gewaehlte`'s
    docstring says why the two cannot be brought together — this pins both
    readings so the difference stays visible instead of turning back into a
    surprise.
    """
    from app.api.v1.bild import BildWunsch

    wunsch = BildWunsch(modell="m", prompt="ein Bild", clip_skip=-1)
    aus_modell = bildlauf._regler_von(wunsch)
    aus_dict = bildlauf._regler_von(wunsch.model_dump())

    assert "clip_skip" not in aus_modell
    assert aus_dict["clip_skip"] == -1
    # What both agree on: the core dials stand either way, default or not.
    assert aus_modell["modell"] == aus_dict["modell"] == "m"
    assert aus_modell["seed"] == aus_dict["seed"] == -1


def test_auto_gilt_dem_dict_pfad_als_gewaehlt():
    """The one value `_wirklich_gesetzt` names outright: "auto" is a real,
    behaviour-changing choice for several dials, never an empty one."""
    assert bildlauf._wirklich_gesetzt("auto") is True
    assert bildlauf._wirklich_gesetzt("") is False
    assert bildlauf._wirklich_gesetzt(None) is False


def test_where_a_drawn_piece_goes_is_no_dial_of_the_picture():
    """A request that names the picture its starting image was cut from and
    the piece's place lists neither among its dials; the starting image, its
    strength and its mask stand there as before."""
    from app.api.v1.bild import BildWunsch

    wunsch = BildWunsch(
        modell="m", prompt="a picture", startbild="piece.png", staerke=0.4, maske="mask.png",
        crop_of="whole.png", crop_box=(8, 16, 64, 64),
    )
    for dials in (bildlauf._regler_von(wunsch), bildlauf._regler_von(wunsch.model_dump())):
        assert "crop_of" not in dials and "crop_box" not in dials
        assert (dials["startbild"], dials["staerke"], dials["maske"]) == ("piece.png", 0.4, "mask.png")
