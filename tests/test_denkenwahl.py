"""The thinking stage, per model, in the settings cascade.

It belongs to the model and not to the chat: somebody who set thinking low
for a small local model does not mean it for the big one in the next chat.
"""

from __future__ import annotations

from app import denkenwahl, denkstufen


def _profil(stufen, standard=None):
    return denkstufen.Denkprofil(
        stufen=list(stufen),
        standard=standard,
        art="schalter" if set(stufen) <= {"off", "on"} else "stufen",
        quelle="katalog",
    )


def test_beide_formen_kommen_durch():
    assert denkenwahl.schalter_pruefen({"stufe": "high"}) == {"stufe": "high"}
    assert denkenwahl.schalter_pruefen({"stufe": "OFF"}) == {"stufe": "off"}
    # The older shape is still out there in stored rows, so it still passes.
    assert denkenwahl.schalter_pruefen({"an": True}) == {"an": True}
    assert denkenwahl.schalter_pruefen({"an": False}) == {"an": False}


def test_muell_faellt_raus():
    assert denkenwahl.schalter_pruefen(True) is None
    assert denkenwahl.schalter_pruefen({"an": "ja"}) is None
    assert denkenwahl.schalter_pruefen({"stufe": "  "}) is None
    assert denkenwahl.schalter_pruefen({"stufe": 3}) is None
    assert denkenwahl.schalter_pruefen({}) is None


def test_eine_unbekannte_stufe_kommt_trotzdem_durch():
    """Not checked against the closed vocabulary: a model's own template can
    name a stage the catalogue does not, and this route only ever writes
    what a profile is already offering."""
    assert denkenwahl.schalter_pruefen({"stufe": "Adaptive"}) == {"stufe": "adaptive"}


def test_altwerte_lesen_sich_als_stellung():
    assert denkenwahl.gespeicherte_stufe({"an": False}) == "off"
    assert denkenwahl.gespeicherte_stufe({"an": True}) == "on"
    assert denkenwahl.gespeicherte_stufe(None) is None


def test_die_vorgabe_steht_dahinter():
    stufen = _profil(["off", "low", "medium", "high"])
    # Nothing stored: the middle of the scale, since no default is documented.
    assert denkenwahl.aufgeloest(None, stufen) == "medium"
    # An old "no" is the off position and stays it.
    assert denkenwahl.aufgeloest({"an": False}, stufen) == "off"
    # An old "yes" says no more than "think" — on a scale that is the default.
    assert denkenwahl.aufgeloest({"an": True}, stufen) == "medium"
    # A stage the model no longer offers is not sent: the nearest weaker one is.
    assert denkenwahl.aufgeloest({"stufe": "xhigh"}, stufen) == "high"
    # What the provider documents wins over the middle.
    assert denkenwahl.aufgeloest(None, _profil(["off", "low", "high"], "high")) == "high"
    # A plain switch starts switched on where nothing says otherwise.
    assert denkenwahl.aufgeloest(None, _profil(["off", "on"])) == "on"
    # Nothing to set, nothing to answer.
    assert denkenwahl.aufgeloest({"stufe": "high"}, _profil([])) is None


def test_jedes_modell_hat_seine_eigene_stellung(client):
    """The point of the model scope: switching one off must not reach the
    other."""
    client.put("/api/v1/settings/modell:klein/denken", json={"wert": {"an": False}})

    klein = client.get("/api/v1/settings/resolved/denken?modell=klein").json()
    assert klein["wert"]["an"] is False
    assert klein["herkunft"]["an"] == "modell:klein"

    gross = client.get("/api/v1/settings/resolved/denken?modell=gross").json()
    assert gross["wert"] == {}


def test_aus_bleibt_aus(client):
    """Stored as an object because the route reads a falsy value as
    "nothing set" — a bare false could never switch thinking off."""
    client.put("/api/v1/settings/modell:klein/denken", json={"wert": {"an": True}})
    client.put("/api/v1/settings/modell:klein/denken", json={"wert": {"an": False}})
    gelesen = client.get("/api/v1/settings/resolved/denken?modell=klein").json()
    assert gelesen["wert"]["an"] is False


# --- A stored stage the model no longer offers -----------------------------


def _profile_with(*stufen: str):
    from app import denkstufen

    return denkstufen.Denkprofil(
        stufen=list(stufen), standard="max", art="stufen", quelle="katalog"
    )


def test_a_dropped_stage_takes_the_nearest_weaker():
    from app.denkenwahl import aufgeloest

    profile = _profile_with("low", "medium", "max")
    assert aufgeloest({"stufe": "high"}, profile) == "medium"
    assert aufgeloest({"stufe": "xhigh"}, profile) == "medium"


def test_glm_low_and_medium_become_high():
    """Nothing weaker is offered: the weakest depth, never "off"."""
    from app.denkenwahl import aufgeloest

    glm = _profile_with("off", "high", "max")
    assert aufgeloest({"stufe": "low"}, glm) == "high"
    assert aufgeloest({"stufe": "medium"}, glm) == "high"
    assert aufgeloest({"stufe": "xhigh"}, glm) == "high"


def test_a_stored_off_without_off_takes_the_weakest_depth():
    from app.denkenwahl import aufgeloest

    assert aufgeloest({"stufe": "off"}, _profile_with("low", "high", "max")) == "low"


def test_a_word_off_the_ladder_takes_the_default():
    """Silence probe: a word the scale does not know, and a stage still
    offered, behave as before."""
    from app.denkenwahl import aufgeloest

    profile = _profile_with("low", "high", "max")
    assert aufgeloest({"stufe": "turbo"}, profile) == "max"
    assert aufgeloest({"stufe": "high"}, profile) == "high"
    assert aufgeloest({"stufe": "on"}, profile) == "max"

