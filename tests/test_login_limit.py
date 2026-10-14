"""Wrong passwords are braked: two a minute and twelve an hour, counted for
all callers together. At a limit the sign-in answers with one sentence and
compares nothing — the right password included. A right password is never
counted.
"""

from __future__ import annotations

import threading
import time

import pytest
from fastapi.testclient import TestClient

from app.i18n import t
from app.login_limit import LIMITS, LimitReached, LoginLimit
from app.main import app_erstellen

PASSWORD = "open-sesame"


class Clock:
    """A clock that stands still until the test moves it."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def service(config, tmp_path):
    """A service beyond this machine, with a password, and its clock."""
    config.app.host = "0.0.0.0"
    file = tmp_path / "password.txt"
    file.write_text(PASSWORD + "\n", encoding="utf-8")
    config.app.password_file = str(file)
    app = app_erstellen(config)
    clock = Clock()
    app.state.login_limit = LoginLimit(clock)
    with TestClient(app) as client:
        yield client, clock


def _sign_in(client, password: str, language: str = "en"):
    return client.post(
        "/api/v1/login", json={"password": password}, headers={"X-Ui-Language": language}
    )


def test_the_limits_are_two_a_minute_and_twelve_an_hour():
    assert LIMITS == ((2, 60.0), (12, 3600.0))


def test_the_third_attempt_within_a_minute_gets_the_sentence_even_with_the_right_password(
    service,
):
    client, _ = service
    assert _sign_in(client, "wrong-1").status_code == 401
    assert _sign_in(client, "wrong-2").status_code == 401

    third = _sign_in(client, PASSWORD)
    assert third.status_code == 429
    assert third.json() == {"detail": t("fehler.login_limited", "en")}


def test_the_sentence_speaks_the_requests_language(service):
    client, _ = service
    _sign_in(client, "wrong-1")
    _sign_in(client, "wrong-2")
    braked = _sign_in(client, "wrong-3", language="de")
    assert braked.status_code == 429
    assert braked.json()["detail"] == t("fehler.login_limited", "de")
    assert t("fehler.login_limited", "de") != t("fehler.login_limited", "en")


def test_after_a_minute_the_sign_in_goes_on(service):
    client, clock = service
    _sign_in(client, "wrong-1")
    _sign_in(client, "wrong-2")
    clock.now += 59.0
    assert _sign_in(client, PASSWORD).status_code == 429

    clock.now += 1.0
    right = _sign_in(client, PASSWORD)
    assert right.status_code == 200
    assert right.json()["key"] == client.app.state.sitzungsschluessel


def test_an_attempt_at_the_limit_is_not_counted(service):
    """Knocking while the brake holds does not make it hold longer."""
    client, clock = service
    _sign_in(client, "wrong-1")
    _sign_in(client, "wrong-2")
    for _ in range(5):
        clock.now += 10.0
        assert _sign_in(client, "wrong-again").status_code == 429
    clock.now += 10.0
    assert _sign_in(client, PASSWORD).status_code == 200


def test_the_thirteenth_failure_of_an_hour_gets_the_sentence(service):
    """Slow enough for the minute's limit, the hour's still holds."""
    client, clock = service
    for number in range(12):
        assert _sign_in(client, f"wrong-{number}").status_code == 401
        clock.now += 61.0

    # More than a minute after the last failure: the hour is what brakes.
    assert _sign_in(client, PASSWORD).status_code == 429

    # The first failure was 12 * 61 seconds ago; once it is an hour old,
    # there is room for one attempt again.
    clock.now += 3600.0 - 12 * 61.0
    assert _sign_in(client, PASSWORD).status_code == 200


def test_right_sign_ins_are_never_counted(service):
    """The quiet case: however many right passwords, the next wrong one is
    answered as the first."""
    client, _ = service
    for _ in range(20):
        assert _sign_in(client, PASSWORD).status_code == 200
    assert _sign_in(client, "wrong-1").status_code == 401
    assert _sign_in(client, PASSWORD).status_code == 200
    assert _sign_in(client, "wrong-2").status_code == 401
    # Two failures stand now, and only they brake.
    assert _sign_in(client, PASSWORD).status_code == 429


def test_on_the_loopback_address_nothing_is_counted(client):
    """The quiet case: a service that demands no password has nothing to
    guess, and its refusal stays the one it always was."""
    client.headers.pop("X-Sitzungsschluessel", None)
    for _ in range(5):
        refused = client.post("/api/v1/login", json={"password": "anything"})
        assert refused.status_code == 401


def test_at_a_limit_nothing_is_compared():
    clock = Clock()
    limit = LoginLimit(clock)
    asked = []

    def wrong() -> bool:
        asked.append(True)
        return False

    assert limit.attempt(wrong) is False
    assert limit.attempt(wrong) is False
    with pytest.raises(LimitReached):
        limit.attempt(wrong)
    assert len(asked) == 2


def test_attempts_sent_at_once_are_counted_one_after_the_other():
    """A burst does not get past the limit by arriving together: each
    attempt is judged with the failures before it already counted."""
    limit = LoginLimit(Clock())
    together = threading.Barrier(20)
    asked = []
    braked = []

    def wrong() -> bool:
        asked.append(True)
        # Long enough for every other attempt to arrive meanwhile.
        time.sleep(0.02)
        return False

    def knock() -> None:
        together.wait()
        try:
            limit.attempt(wrong)
        except LimitReached:
            braked.append(True)

    burst = [threading.Thread(target=knock) for _ in range(20)]
    for thread in burst:
        thread.start()
    for thread in burst:
        thread.join()
    assert len(asked) == 2
    assert len(braked) == 18
