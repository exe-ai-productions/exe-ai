"""The compaction threshold, end to end through the settings route.

A checker exists (`app/verdichtungswahl.py`) and a field exists
(`frontend/src/teile/SystemPrompt.svelte`), but neither proves the value
survives the trip: a setting nobody registered in `PRUEFER` is refused by
the route, and the field would then be a control that silently does
nothing. This is the test that would have caught that.
"""

from __future__ import annotations

import pytest

from app import verdichtungswahl


def _setzen(client, wert):
    return client.put(
        "/api/v1/settings/global/verdichtung_schwelle", json={"wert": wert}
    )


def _stand(client):
    antwort = client.get("/api/v1/settings/resolved/verdichtung_schwelle")
    assert antwort.status_code == 200, antwort.text
    return antwort.json()["wert"]


def test_ein_wert_im_band_ueberlebt_die_reise(client):
    assert _setzen(client, 70).status_code == 200
    assert _stand(client) == 70


@pytest.mark.parametrize("wert", [verdichtungswahl.KLEINSTE, verdichtungswahl.GROESSTE])
def test_die_raender_des_bandes_gehen_durch(client, wert):
    assert _setzen(client, wert).status_code == 200
    assert _stand(client) == wert


@pytest.mark.parametrize("wert", [95, -10, "frueh", True])
def test_was_ausserhalb_liegt_wird_nie_der_stand(client, wert):
    """Refused or filed as "nothing set" — but never stored as given. A
    threshold above the 90% emergency handoff would be a setting able to
    break the net it sits under.

    Three is no longer in this list. The floor was five, and the number box
    cannot say "zero OR five to eighty-five" — zero is how it says
    "default" — so a typed 3 was shown, sent, refused with a plain 200 and
    silently forgotten. A setting that shows one number and obeys another is
    worse than one that lets somebody pick a silly threshold."""
    _setzen(client, wert)
    assert _stand(client) != wert


def test_die_null_heisst_vorgabe_und_nicht_null(client):
    """Zero is how the field says "unset" — the route files any falsy value
    that way, and the window shows the word instead of a number. A stored
    zero would be a threshold of nothing, compacting at once and forever."""
    _setzen(client, 70)
    _setzen(client, 0)
    stand = _stand(client)
    assert not isinstance(stand, (int, float)) or stand is True, stand
    # And the service falls back to what it always used.
    repositories = client.app.state.repositories
    assert verdichtungswahl.schwelle(repositories) == verdichtungswahl.VORGABE


def test_der_chat_sticht_das_globale(client):
    """The cascade is the whole point: one number for the house, a different
    one for the conversation that needs it."""
    chat_id = client.post("/api/v1/chats", json={"title": "Kaskade"}).json()["id"]
    _setzen(client, 60)
    client.put(
        f"/api/v1/settings/chat:{chat_id}/verdichtung_schwelle", json={"wert": 80}
    )

    repositories = client.app.state.repositories
    assert verdichtungswahl.schwelle(repositories) == 60
    assert verdichtungswahl.schwelle(repositories, chat=chat_id) == 80


def test_eine_kleine_schwelle_wird_angenommen(client):
    """The floor is one. Compacting at 2% is a silly choice — and it is the
    user's to make. What must never happen again is the field showing a
    number the service quietly threw away."""
    assert _setzen(client, 2).status_code == 200
    assert _stand(client) == 2
