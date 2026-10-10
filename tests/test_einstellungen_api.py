"""The settings route, and above all the collective read.

A screen needs a dozen settings before it can draw anything. Asking for each
one on its own means a dozen round trips and a window that assembles itself
in front of the user, so there is one route that resolves a whole list at
once. It has to give back exactly what the single route would — same value,
same provenance — or the two would drift apart and nobody would notice which
of them lied.
"""

from __future__ import annotations


def test_mehrere_schluessel_auf_einmal(client):
    client.put("/api/v1/settings/global/klaenge", json={"wert": {"an": True, "pegel": 42}})
    client.put(
        "/api/v1/settings/global/gedaechtnis",
        json={"wert": {"lokal": True, "cloud": False}},
    )

    antwort = client.get("/api/v1/settings/resolved?keys=klaenge,gedaechtnis")
    assert antwort.status_code == 200, antwort.text
    daten = antwort.json()

    assert set(daten) == {"klaenge", "gedaechtnis"}
    assert daten["klaenge"]["wert"] == {"an": True, "pegel": 42}
    assert daten["gedaechtnis"]["wert"] == {"lokal": True, "cloud": False}


def test_dasselbe_wie_die_einzelne_lesung(client):
    client.put("/api/v1/settings/global/klaenge", json={"wert": {"an": True, "pegel": 42}})

    einzeln = client.get("/api/v1/settings/resolved/klaenge").json()
    viele = client.get("/api/v1/settings/resolved?keys=klaenge").json()["klaenge"]

    assert viele["wert"] == einzeln["wert"]
    assert viele["herkunft"] == einzeln["herkunft"]


def test_der_engere_bereich_gewinnt_und_die_herkunft_sagt_es(client):
    client.put("/api/v1/settings/global/klaenge", json={"wert": {"an": True, "pegel": 42}})
    client.put(
        "/api/v1/settings/chat:c1/klaenge", json={"wert": {"pegel": 7}}
    )

    daten = client.get("/api/v1/settings/resolved?keys=klaenge&chat=c1").json()
    # Merged key by key: the chat only moved the level, the switch stays.
    assert daten["klaenge"]["wert"] == {"an": True, "pegel": 7}
    assert daten["klaenge"]["herkunft"] == {"an": "global", "pegel": "chat:c1"}

    # Without the chat the global value is untouched.
    ohne = client.get("/api/v1/settings/resolved?keys=klaenge").json()
    assert ohne["klaenge"]["wert"]["pegel"] == 42


def test_ein_ungesetzter_schluessel_kommt_leer_zurueck(client):
    daten = client.get("/api/v1/settings/resolved?keys=klaenge,parameter").json()
    assert daten["parameter"]["wert"] == {}
    assert daten["parameter"]["herkunft"] == {}


def test_doppelte_und_leere_namen_stoeren_nicht(client):
    daten = client.get("/api/v1/settings/resolved?keys=klaenge,,klaenge").json()
    assert list(daten) == ["klaenge"]

    assert client.get("/api/v1/settings/resolved?keys=").status_code == 400
    assert client.get("/api/v1/settings/resolved?keys=,%20,").status_code == 400


# --- writing only what changed --------------------------------------------
#
# PUT replaces, which is right for a setting one writer owns and wrong where
# two windows share a row: to keep what it did not change, each writer has to
# resend the whole object, and that object is the copy it read when its page
# opened. PATCH writes the values named and leaves the rest alone.


def test_teilweise_setzen_laesst_den_rest_stehen(client):
    client.put(
        "/api/v1/settings/global/runnermodell",
        json={"wert": {"modell": "a.gguf", "kontext": 65536, "schichten": 40}},
    )
    antwort = client.patch(
        "/api/v1/settings/global/runnermodell", json={"wert": {"kontext": 8192}}
    )
    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["wert"] == {
        "modell": "a.gguf", "kontext": 8192, "schichten": 40
    }


def test_zwei_fenster_loeschen_einander_nicht(client):
    """The finding this route exists for.

    Window A picks a module, window B — which read the row before that — then
    moves a slider. With a whole-object write B's stale copy would go out and
    A's pick would be gone. Written key by key, both survive.
    """
    client.put(
        "/api/v1/settings/global/runnermodell",
        json={"wert": {"modell": "a.gguf", "kontext": 65536, "module": {}}},
    )
    # A
    client.patch(
        "/api/v1/settings/global/runnermodell",
        json={"wert": {"module": {"a.gguf": {"drafter": "mtp-a.gguf"}}}},
    )
    # B, still holding the row as it was before A wrote
    client.patch(
        "/api/v1/settings/global/runnermodell", json={"wert": {"kontext": 8192}}
    )
    stand = client.get("/api/v1/settings/global/runnermodell").json()["wert"]
    assert stand["kontext"] == 8192
    assert stand["module"] == {"a.gguf": {"drafter": "mtp-a.gguf"}}


def test_zwei_fenster_auf_zwei_dateien_stehen_nebeneinander(client):
    """The module memory is a set of sets, so the merge goes one level down —
    a row for one model says nothing about the model next to it."""
    client.patch(
        "/api/v1/settings/global/runnermodell",
        json={"wert": {"module": {"a.gguf": {"drafter": "mtp-a.gguf"}}}},
    )
    client.patch(
        "/api/v1/settings/global/runnermodell",
        json={"wert": {"module": {"b.gguf": {"vision": "augen-b.gguf"}}}},
    )
    client.patch(
        "/api/v1/settings/global/runnermodell",
        json={"wert": {"module": {"a.gguf": {"vision": ""}}}},
    )
    stand = client.get("/api/v1/settings/global/runnermodell").json()["wert"]
    assert stand["module"] == {
        "a.gguf": {"drafter": "mtp-a.gguf", "vision": ""},
        "b.gguf": {"vision": "augen-b.gguf"},
    }


def test_teilweise_setzen_prueft_wie_das_ganze(client):
    """Not a way past the check — the same PRUEFER entry, and no entry at all
    means no write."""
    assert client.patch(
        "/api/v1/settings/global/gibtsnicht", json={"wert": {"a": 1}}
    ).status_code == 400
    # Out of range is brought into range here as well.
    client.patch("/api/v1/settings/global/runnermodell", json={"wert": {"kontext": 10}})
    stand = client.get("/api/v1/settings/global/runnermodell").json()["wert"]
    assert stand["kontext"] == 512


def test_nur_ein_wertesatz_laesst_sich_teilweise_setzen(client):
    """A list or a bare value has nothing to merge along — that caller means
    PUT."""
    assert client.patch(
        "/api/v1/settings/global/runnermodell", json={"wert": "nein"}
    ).status_code == 400
    assert client.patch(
        "/api/v1/settings/global/runnermodell", json={"wert": None}
    ).status_code == 400


def test_teilweise_setzen_prueft_die_zusammengelegte_zeile(client):
    """A part that means nothing on its own can mean something together with
    what is stored: "above" next to the stored offset is a real place."""
    client.put(
        "/api/v1/settings/chat:c1/scrollstelle",
        json={"wert": {"am_boden": True, "versatz": 640}},
    )
    antwort = client.patch(
        "/api/v1/settings/chat:c1/scrollstelle", json={"wert": {"am_boden": False}}
    )
    assert antwort.status_code == 200, antwort.text
    stand = client.get("/api/v1/settings/chat:c1/scrollstelle").json()["wert"]
    assert stand == {"am_boden": False, "versatz": 640}


def test_teilweise_setzen_ohne_versatz_daneben_bleibt_abgelehnt(client):
    """No offset stored beside it: the merged row is still "above without a
    place to go back to", which the check throws out — refused, and the row
    stays as it was."""
    client.put("/api/v1/settings/chat:c1/scrollstelle", json={"wert": {"am_boden": True}})
    assert client.patch(
        "/api/v1/settings/chat:c1/scrollstelle", json={"wert": {"am_boden": False}}
    ).status_code == 400
    stand = client.get("/api/v1/settings/chat:c1/scrollstelle").json()["wert"]
    assert stand == {"am_boden": True}

    # Nothing stored at all, and nothing usable sent: refused as before.
    assert client.patch(
        "/api/v1/settings/chat:c2/scrollstelle", json={"wert": {"am_boden": "ja"}}
    ).status_code == 400
    assert client.get("/api/v1/settings/chat:c2/scrollstelle").json()["wert"] is None


def test_teilweise_setzen_eines_anderen_schluessels_wie_bisher(client):
    client.put("/api/v1/settings/global/klaenge", json={"wert": {"an": True, "pegel": 42}})
    antwort = client.patch("/api/v1/settings/global/klaenge", json={"wert": {"pegel": 7}})
    assert antwort.status_code == 200, antwort.text
    assert client.get("/api/v1/settings/global/klaenge").json()["wert"] == {
        "an": True,
        "pegel": 7,
    }


def test_two_concurrent_patches_of_different_fields_both_stay(client, monkeypatch):
    """Read, check and write are one step: two PATCHes that are checked at
    the same moment must not both start from the same stored row, or the
    second write takes the first one's field back."""
    import threading
    import time

    from app.api.v1 import einstellungen as settings_route

    real = settings_route.PRUEFER["klaenge"]

    def slow(value):
        time.sleep(0.3)
        return real(value)

    monkeypatch.setitem(settings_route.PRUEFER, "klaenge", slow)
    client.app.state.repositories.einstellungen.setzen(
        "global", "klaenge", {"an": True, "pegel": 42}
    )
    codes: list[int] = []

    def write(value: dict) -> None:
        codes.append(
            client.patch("/api/v1/settings/global/klaenge", json={"wert": value}).status_code
        )

    threads = [
        threading.Thread(target=write, args=({"an": False},)),
        threading.Thread(target=write, args=({"pegel": 7},)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
    assert codes == [200, 200]
    assert client.app.state.repositories.einstellungen.holen("global", "klaenge") == {
        "an": False,
        "pegel": 7,
    }


def test_a_patch_without_a_valid_value_is_refused(client):
    """Every value sent is thrown out by the check: refused, even when the
    stored row next to it is fine — the caller is told nothing was written."""
    client.put("/api/v1/settings/global/klaenge", json={"wert": {"an": True, "pegel": 42}})
    assert client.patch(
        "/api/v1/settings/global/klaenge", json={"wert": {"pegel": "laut"}}
    ).status_code == 400
    assert client.get("/api/v1/settings/global/klaenge").json()["wert"] == {
        "an": True,
        "pegel": 42,
    }


def test_a_partly_invalid_patch_writes_the_valid_part(client):
    """The silence probe: what the check keeps of the sent values is written;
    a sent value it drops leaves the stored one of that key standing."""
    client.put("/api/v1/settings/global/klaenge", json={"wert": {"an": True, "pegel": 42}})
    response = client.patch(
        "/api/v1/settings/global/klaenge", json={"wert": {"an": False, "pegel": "laut"}}
    )
    assert response.status_code == 200, response.text
    assert response.json()["wert"] == {"an": False, "pegel": 42}


def test_a_new_module_on_a_full_set_is_refused(client):
    """The cap on the module memory holds for the merged row: an entry
    appended to a full set is refused, never cut off silently, and the
    stored row stays as it was."""
    from app.runnermodellwahl import MODULE_HOECHSTZAHL

    full = {f"m{number}.gguf": {"drafter": ""} for number in range(MODULE_HOECHSTZAHL)}
    settings = client.app.state.repositories.einstellungen
    settings.setzen("global", "runnermodell", {"module": full})
    response = client.patch(
        "/api/v1/settings/global/runnermodell",
        json={"wert": {"module": {"neu.gguf": {"drafter": "mtp-neu.gguf"}}}},
    )
    assert response.status_code == 400, response.text
    assert settings.holen("global", "runnermodell") == {"module": full}


def test_a_put_over_the_module_cap_is_refused(client):
    from app.runnermodellwahl import MODULE_HOECHSTZAHL

    client.put("/api/v1/settings/global/runnermodell", json={"wert": {"kontext": 8192}})
    too_many = {f"m{number}.gguf": {"drafter": ""} for number in range(MODULE_HOECHSTZAHL + 1)}
    response = client.put(
        "/api/v1/settings/global/runnermodell", json={"wert": {"module": too_many}}
    )
    assert response.status_code == 400, response.text
    assert client.get("/api/v1/settings/global/runnermodell").json()["wert"] == {"kontext": 8192}


def test_a_set_reaching_the_cap_is_still_taken(client):
    """The silence probe: exactly at the cap the row is written."""
    from app.runnermodellwahl import MODULE_HOECHSTZAHL

    almost = {f"m{number}.gguf": {"drafter": ""} for number in range(MODULE_HOECHSTZAHL - 1)}
    client.app.state.repositories.einstellungen.setzen("global", "runnermodell", {"module": almost})
    response = client.patch(
        "/api/v1/settings/global/runnermodell",
        json={"wert": {"module": {"neu.gguf": {"drafter": "mtp-neu.gguf"}}}},
    )
    assert response.status_code == 200, response.text
    assert len(response.json()["wert"]["module"]) == MODULE_HOECHSTZAHL


def test_a_value_without_fields_has_no_field_origin(client):
    """The origin only names fields the value has: a list from the chat over
    a set from the global scope carries no field origin of the set."""
    settings = client.app.state.repositories.einstellungen
    settings.setzen("global", "liste", {"a": 1})
    settings.setzen("chat:c1", "liste", ["x"])
    single = client.get("/api/v1/settings/resolved/liste?chat=c1").json()
    collective = client.get("/api/v1/settings/resolved?keys=liste&chat=c1").json()["liste"]
    for response in (single, collective):
        assert response["wert"] == ["x"]
        assert response["herkunft"] == {}


def test_an_old_oversized_set_still_takes_a_slider(client):
    """A row stored with more modules than the cap allows still takes a
    write that adds none; one that adds a module is refused."""
    old = {f"m{number}.gguf": {"drafter": ""} for number in range(600)}
    settings = client.app.state.repositories.einstellungen
    settings.setzen("global", "runnermodell", {"module": old, "kontext": 65536})
    slider = client.patch("/api/v1/settings/global/runnermodell", json={"wert": {"kontext": 8192}})
    assert slider.status_code == 200, slider.text
    assert settings.holen("global", "runnermodell") == {"module": old, "kontext": 8192}
    more = client.patch(
        "/api/v1/settings/global/runnermodell",
        json={"wert": {"module": {"neu.gguf": {"drafter": "mtp-neu.gguf"}}}},
    )
    assert more.status_code == 400, more.text
    assert settings.holen("global", "runnermodell") == {"module": old, "kontext": 8192}


def test_a_more_specific_set_wins_over_a_list(client):
    """Only two sets are merged; otherwise the more specific scope wins —
    a set over a list, with its own origin."""
    settings = client.app.state.repositories.einstellungen
    settings.setzen("global", "liste", ["x"])
    settings.setzen("chat:c1", "liste", {"a": 1})
    single = client.get("/api/v1/settings/resolved/liste?chat=c1").json()
    collective = client.get("/api/v1/settings/resolved?keys=liste&chat=c1").json()["liste"]
    for response in (single, collective):
        assert response["wert"] == {"a": 1}
        assert response["herkunft"] == {"a": "chat:c1"}
    assert settings.zusammengefuehrt("liste", chat="c1") == {"a": 1}


def test_a_patch_whose_nested_values_are_all_dropped_is_refused(client):
    """What is left of a sent set once the check dropped everything in it is
    an empty set — nothing was written, and the caller is told so."""
    client.put("/api/v1/settings/global/runnermodell", json={"wert": {"kontext": 8192}})
    response = client.patch(
        "/api/v1/settings/global/runnermodell", json={"wert": {"module": {"a.gguf": "x"}}}
    )
    assert response.status_code == 400, response.text
    assert client.get("/api/v1/settings/global/runnermodell").json()["wert"] == {"kontext": 8192}


def test_only_a_refused_row_is_answered_with_400(client, monkeypatch):
    """Any other error inside a check stays the error it is — it is not
    taken for a refused write."""
    import pytest

    from app.api.v1 import einstellungen as settings_route

    def broken(value):
        raise ValueError("a check that breaks")

    monkeypatch.setitem(settings_route.PRUEFER, "klaenge", broken)
    with pytest.raises(ValueError):
        client.patch("/api/v1/settings/global/klaenge", json={"wert": {"pegel": 7}})


def test_a_nested_set_is_merged_with_the_stored_one_before_the_check(client):
    """A check that fills in what a set lacks must see the stored values:
    one lever sent leaves the other stored levers standing."""
    settings = client.app.state.repositories.einstellungen
    settings.setzen(
        "global", "agentenmodell",
        {"fein": {"kv_cache": "q8_0", "parallel": 4, "faeden": 6}},
    )
    response = client.patch(
        "/api/v1/settings/global/agentenmodell", json={"wert": {"fein": {"faeden": 12}}}
    )
    assert response.status_code == 200, response.text
    fein = settings.holen("global", "agentenmodell")["fein"]
    assert fein["faeden"] == 12
    assert fein["kv_cache"] == "q8_0"
    assert fein["parallel"] == 4
