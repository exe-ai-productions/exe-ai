"""The memory and devices of the picture server show what the service keeps.

A split or a budget the generator cannot read is kept as "Auto" (empty); the
window used to take over only two of its seven fields from the answer and
went on showing the typed text, while the generator was started without the
flag. The service's answer is the one value that acts, so every field of a
write takes it over.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.image_window_page import needs_browser, run_cases

BROWSER_ON_MAC_ONLY = pytest.mark.platforms("darwin", reason="the browser run of the interface is checked on macOS only")

URL = "/api/v1/settings/global/bildgeraete"


def test_a_split_the_service_cannot_read_comes_back_as_auto(client: TestClient):
    answer = client.patch(URL, json={"wert": {"split_mode": "diffusion=bogus"}})
    assert answer.status_code == 200
    assert answer.json()["wert"]["split_mode"] == ""


def test_a_text_with_spaces_is_kept_without_them(client: TestClient):
    answer = client.patch(URL, json={"wert": {"backend": "clip = cpu"}})
    assert answer.json()["wert"]["backend"] == "clip=cpu"


CASES = r"""
backend.settings.bildgeraete.split_mode = 'diffusion=row'
await show('devices')
const splitField = () => document.querySelector('input[aria-label="bildserver.split_je_modul"]')
report.splitTextShownFirst = Boolean(splitField())
typeInto(splitField(), 'diffusion=bogus')
await wait(1500)
report.splitStored = backend.settings.bildgeraete.split_mode
report.splitTextShownAfter = Boolean(splitField())

const backendField = () => document.querySelector('input[aria-label="bild.backend"]')
typeInto(backendField(), 'clip = cpu')
await wait(1500)
report.backendStored = backend.settings.bildgeraete.backend
report.backendShown = backendField().value
"""


@pytest.fixture(scope="module")
def report() -> dict:
    return run_cases(CASES)


@BROWSER_ON_MAC_ONLY
@needs_browser
def test_the_window_takes_over_the_corrected_split(report):
    assert report["splitTextShownFirst"] is True
    assert report["splitStored"] == ""
    # The text field of "one mode per module" is gone: the picker says "Auto".
    assert report["splitTextShownAfter"] is False


@BROWSER_ON_MAC_ONLY
@needs_browser
def test_the_window_takes_over_a_text_the_service_tidied(report):
    assert report["backendStored"] == "clip=cpu"
    assert report["backendShown"] == "clip=cpu"
