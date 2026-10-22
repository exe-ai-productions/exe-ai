"""The memory-at-a-glance endpoint the header pill polls."""

from __future__ import annotations


def test_speicherblick_liefert_das_zahlenpaar(client):
    antwort = client.get("/api/v1/system/speicher")
    assert antwort.status_code == 200
    daten = antwort.json()
    # None is a legal answer on a platform that cannot say — the window
    # then shows nothing. What must hold is the shape.
    assert set(daten) == {"belegt_gb", "gesamt_gb", "anteil", "wired_gb", "wired_anteil", "wired_limit_gb"}
    if daten["belegt_gb"] is not None and daten["gesamt_gb"]:
        assert 0 < daten["belegt_gb"] <= daten["gesamt_gb"] * 1.0
        assert 0 < daten["anteil"] <= 1.0


def test_the_wired_value_stands_beside_the_sum_and_is_at_most_as_large(client):
    daten = client.get("/api/v1/system/speicher").json()
    # None on a platform that has no such figure: then the dash stands, not a guess.
    if daten["wired_gb"] is not None:
        assert 0 < daten["wired_gb"] <= daten["gesamt_gb"]
        assert 0 < daten["wired_anteil"] <= 1.0
    else:
        assert daten["wired_anteil"] is None


def test_the_wired_share_is_measured_against_the_limit_where_there_is_one(client, monkeypatch):
    from app import systemspeicher

    monkeypatch.setattr(systemspeicher, "used_and_wired_gb", lambda: (30.0, 20.0))
    monkeypatch.setattr(systemspeicher, "gesamt_gb", lambda: 64.0)
    monkeypatch.setattr(systemspeicher, "wired_limit_gb", lambda: 58.0)
    daten = client.get("/api/v1/system/speicher").json()
    assert daten["wired_limit_gb"] == 58.0
    assert daten["wired_anteil"] == round(20.0 / 58.0, 4)
    # The sum for the pill keeps the whole memory.
    assert daten["anteil"] == round(30.0 / 64.0, 4)


def test_without_a_limit_the_wired_share_stays_against_the_whole_memory(client, monkeypatch):
    from app import systemspeicher

    monkeypatch.setattr(systemspeicher, "used_and_wired_gb", lambda: (30.0, 20.0))
    monkeypatch.setattr(systemspeicher, "gesamt_gb", lambda: 64.0)
    monkeypatch.setattr(systemspeicher, "wired_limit_gb", lambda: None)
    daten = client.get("/api/v1/system/speicher").json()
    assert daten["wired_limit_gb"] is None
    assert daten["wired_anteil"] == round(20.0 / 64.0, 4)
