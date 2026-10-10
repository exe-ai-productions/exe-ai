"""Where a conversation was left standing."""

from __future__ import annotations

from app import scrollwahl


def test_beides_kommt_durch():
    assert scrollwahl.wahl_pruefen({"am_boden": False, "versatz": 1200}) == {
        "am_boden": False,
        "versatz": 1200,
    }


def test_am_boden_ist_ein_modus_kein_ort():
    """Following the end of a running answer must come back as following —
    whatever height the messages happen to render at this time."""
    assert scrollwahl.wahl_pruefen({"am_boden": True}) == {"am_boden": True}


def test_above_without_a_usable_offset_opens_at_the_end():
    """"Somewhere above" with no offset would open the chat at its very top;
    without a place to go back to it opens at the end, like a new chat."""
    for value in (
        {"am_boden": False},
        {"am_boden": False, "versatz": "x"},
        {"am_boden": False, "versatz": None},
        {"am_boden": False, "versatz": float("nan")},
        {"am_boden": False, "versatz": float("inf")},
    ):
        assert scrollwahl.wahl_pruefen(value) is None, value


def test_left_at_the_very_top_is_a_real_place():
    """Offset 0 is a usable offset, not a missing one."""
    assert scrollwahl.wahl_pruefen({"am_boden": False, "versatz": 0}) == {
        "am_boden": False,
        "versatz": 0,
    }


def test_der_versatz_bleibt_in_seinen_grenzen():
    assert scrollwahl.wahl_pruefen({"versatz": -20}) == {"versatz": 0}
    assert scrollwahl.wahl_pruefen({"versatz": 10**9}) == {"versatz": scrollwahl.VERSATZ_MAX}
    assert scrollwahl.wahl_pruefen({"versatz": 10**400}) == {"versatz": scrollwahl.VERSATZ_MAX}


def test_muell_faellt_raus():
    assert scrollwahl.wahl_pruefen(0) is None
    assert scrollwahl.wahl_pruefen({"am_boden": "ja"}) is None
    assert scrollwahl.wahl_pruefen({"versatz": True}) is None
    assert scrollwahl.wahl_pruefen({}) is None


def test_die_vorgabe_steht_dahinter(client):
    """Nothing stored: the read path answers the default, and no scope."""
    for read in _beide_lesungen(client, "leer"):
        assert read == {"am_boden": True, "versatz": 0}, read
    for origin in _both_origins(client, "leer"):
        assert origin == {}, origin


def test_above_without_a_usable_offset_reads_as_the_end(client):
    """Stored as they are, the rows the check throws out read as the
    default through the real read path."""
    settings = client.app.state.repositories.einstellungen
    for number, value in enumerate((
        {"am_boden": False},
        {"am_boden": False, "versatz": "x"},
        {"am_boden": False, "versatz": None},
    )):
        settings.setzen(f"chat:old{number}", "scrollstelle", value)
        for read in _beide_lesungen(client, f"old{number}"):
            assert read == scrollwahl.VORGABE, (value, read)


def test_die_route_speichert_je_chat(client):
    client.put(
        "/api/v1/settings/chat:c1/scrollstelle",
        json={"wert": {"am_boden": False, "versatz": 840}},
    )
    gelesen = client.get("/api/v1/settings/resolved/scrollstelle?chat=c1").json()
    assert gelesen["wert"] == {"am_boden": False, "versatz": 840}

    # Another chat knows nothing of it.
    anderer = client.get("/api/v1/settings/resolved/scrollstelle?chat=c2").json()
    assert anderer["wert"] == scrollwahl.VORGABE


def test_the_route_drops_above_without_an_offset(client):
    """Written without a place to go back to, the stored position goes away
    and the chat reads as the default: at its end."""
    client.put(
        "/api/v1/settings/chat:c1/scrollstelle",
        json={"wert": {"am_boden": False, "versatz": 840}},
    )
    client.put(
        "/api/v1/settings/chat:c1/scrollstelle",
        json={"wert": {"am_boden": False, "versatz": None}},
    )
    gelesen = client.get("/api/v1/settings/resolved/scrollstelle?chat=c1").json()
    assert gelesen["wert"] == scrollwahl.VORGABE


def _beide_lesungen(client, chat: str) -> list[dict]:
    """What the single and the collective read route give back for one chat."""
    einzeln = client.get(f"/api/v1/settings/resolved/scrollstelle?chat={chat}").json()
    viele = client.get(f"/api/v1/settings/resolved?keys=scrollstelle&chat={chat}").json()
    return [einzeln["wert"], viele["scrollstelle"]["wert"]]


def test_an_old_row_above_without_an_offset_reads_as_the_end(client):
    """A row stored before the write was checked never went through the
    check. Read back unchecked, the window would fill the missing offset in
    as 0 and open the chat at its very top."""
    client.app.state.repositories.einstellungen.setzen(
        "chat:c1", "scrollstelle", {"am_boden": False}
    )
    for wert in _beide_lesungen(client, "c1"):
        assert wert["am_boden"] is True, wert


def test_above_without_an_offset_merged_from_two_scopes_reads_as_the_end(client):
    """The row only says "above without an offset" once the scopes are
    merged: the chat's old row lies over a global one."""
    client.put("/api/v1/settings/global/scrollstelle", json={"wert": {"am_boden": True}})
    client.app.state.repositories.einstellungen.setzen(
        "chat:c1", "scrollstelle", {"am_boden": False}
    )
    for wert in _beide_lesungen(client, "c1"):
        assert wert["am_boden"] is True, wert


def test_a_usable_offset_is_read_back_as_it_was_stored(client):
    """The read check leaves a real place alone — the top included."""
    einstellungen = client.app.state.repositories.einstellungen
    einstellungen.setzen("chat:oben", "scrollstelle", {"am_boden": False, "versatz": 0})
    einstellungen.setzen("chat:mitte", "scrollstelle", {"am_boden": False, "versatz": 640})
    for wert in _beide_lesungen(client, "oben"):
        assert wert == {"am_boden": False, "versatz": 0}, wert
    for wert in _beide_lesungen(client, "mitte"):
        assert wert == {"am_boden": False, "versatz": 640}, wert


def _both_origins(client, chat: str) -> list[dict]:
    """The origins the single and the collective read route give back."""
    single = client.get(f"/api/v1/settings/resolved/scrollstelle?chat={chat}").json()
    collective = client.get(f"/api/v1/settings/resolved?keys=scrollstelle&chat={chat}").json()
    return [single["herkunft"], collective["scrollstelle"]["herkunft"]]


def test_a_field_the_read_check_replaced_names_no_scope(client):
    """The origin matches the value that is read: a field replaced by the
    default carries no origin, like a field no scope ever set."""
    client.app.state.repositories.einstellungen.setzen(
        "chat:c1", "scrollstelle", {"am_boden": False}
    )
    for read in _beide_lesungen(client, "c1"):
        assert read == scrollwahl.VORGABE, read
    for origin in _both_origins(client, "c1"):
        assert origin == {}, origin


def test_a_usable_position_keeps_its_origin(client):
    """The silence probe: a row the read check leaves alone still names the
    chat it was stored for."""
    client.app.state.repositories.einstellungen.setzen(
        "chat:mitte", "scrollstelle", {"am_boden": False, "versatz": 640}
    )
    for origin in _both_origins(client, "mitte"):
        assert origin == {"am_boden": "chat:mitte", "versatz": "chat:mitte"}, origin


def test_each_scope_is_checked_before_the_merge(client):
    """An old chat row "above" without an offset does not borrow the offset
    of the global scope: it counts as unset, and the global row applies as
    it was written."""
    settings = client.app.state.repositories.einstellungen
    settings.setzen("global", "scrollstelle", {"am_boden": True, "versatz": 300})
    settings.setzen("chat:c1", "scrollstelle", {"am_boden": False})
    for read in _beide_lesungen(client, "c1"):
        assert read == {"am_boden": True, "versatz": 300}, read
    for origin in _both_origins(client, "c1"):
        assert origin == {"am_boden": "global", "versatz": "global"}, origin
