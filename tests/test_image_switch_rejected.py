"""A switch value the service refuses leaves the stored one standing.

A value its row does not take (``conditioning_cache_size`` below 0, a text
over 500 characters) used to be dropped from the memory block together with
the value that was stored for it, and the window went on showing what was
typed. The answer names what is kept; the window shows that and says the
change was not kept.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.image_window_page import needs_browser, run_cases

URL = "/api/v1/settings/global/bildgeraete"


def _patch(client: TestClient, switches: dict) -> dict:
    answer = client.patch(URL, json={"wert": {"switches": switches}})
    assert answer.status_code == 200, answer.text
    return answer.json()["wert"]["switches"]


def test_a_refused_number_leaves_the_stored_one(client: TestClient):
    assert _patch(client, {"conditioning_cache_size": 5}) == {"conditioning_cache_size": 5}
    assert _patch(client, {"conditioning_cache_size": -1}) == {"conditioning_cache_size": 5}


def test_a_refused_text_leaves_the_stored_one(client: TestClient):
    assert _patch(client, {"tensor_type_rules": "a=f16"}) == {"tensor_type_rules": "a=f16"}
    kept = _patch(client, {"tensor_type_rules": "x" * 501})
    assert kept == {"tensor_type_rules": "a=f16"}


def test_a_value_sent_as_unset_is_still_taken_out(client: TestClient):
    _patch(client, {"conditioning_cache_size": 5, "tensor_type_rules": "a=f16"})
    kept = _patch(client, {"conditioning_cache_size": None, "tensor_type_rules": ""})
    assert kept == {}


def test_a_refused_value_of_a_switch_that_was_never_stored_stays_unset(client: TestClient):
    assert _patch(client, {"conditioning_cache_size": -1}) == {}


def test_the_other_stored_switches_stay_beside_a_refusal(client: TestClient):
    _patch(client, {"conditioning_cache_size": 5, "tensor_type_rules": "a=f16"})
    kept = _patch(client, {"conditioning_cache_size": -1})
    assert kept == {"conditioning_cache_size": 5, "tensor_type_rules": "a=f16"}


CASES = r"""
backend.settings.bildgeraete.switches = { conditioning_cache_size: 5 }
await show('devices')
document.querySelector('button.klappe').click()
await wait(300)
const field = () => document.querySelector('.schalterflaeche input.feldein')
report.firstShown = field().value
typeInto(field(), '-1')
await wait(1500)
report.stored = backend.settings.bildgeraete.switches
report.shown = field().value
report.notices = notices.liste.map((n) => n.text)
"""


@pytest.fixture(scope="module")
def report() -> dict:
    return run_cases(CASES)


@needs_browser
def test_the_window_shows_the_kept_value_and_says_the_change_was_not_kept(report):
    assert report["firstShown"] == "5"
    assert report["stored"] == {"conditioning_cache_size": 5}
    assert report["shown"] == "5"
    assert any("einstellung_speichern" in text for text in report["notices"]), report["notices"]
