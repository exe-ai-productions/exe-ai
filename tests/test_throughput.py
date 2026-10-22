"""Tokens per second of the running servers: the counters, the series made of
their readings, the round that reads them and the route that tells them."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app import throughput
from app.modellrunner import Lauf, Modellrunner
from app.throughput import Series, Watch, parse_counters

METRICS = """# HELP llamacpp:prompt_tokens_total Number of prompt tokens processed.
# TYPE llamacpp:prompt_tokens_total counter
llamacpp:prompt_tokens_total 120
# HELP llamacpp:tokens_predicted_total Number of generation tokens processed.
# TYPE llamacpp:tokens_predicted_total counter
llamacpp:tokens_predicted_total 3840
# HELP llamacpp:tokens_predicted_seconds_total Predict process time
# TYPE llamacpp:tokens_predicted_seconds_total counter
llamacpp:tokens_predicted_seconds_total 100.0
# HELP llamacpp:predicted_tokens_seconds Average generation throughput in tokens/s.
# TYPE llamacpp:predicted_tokens_seconds gauge
llamacpp:predicted_tokens_seconds 38.4
"""


def test_the_two_counters_are_read_out_of_the_metrics_text():
    assert parse_counters(METRICS) == (3840.0, 100.0)


@pytest.mark.parametrize("text", [
    "",
    "llamacpp:tokens_predicted_total 5\n",
    "llamacpp:tokens_predicted_seconds_total 5\n",
    "llamacpp:tokens_predicted_total five\nllamacpp:tokens_predicted_seconds_total 5\n",
])
def test_a_text_without_both_counters_says_nothing(text):
    assert parse_counters(text) is None


def _series(*readings: tuple[float, float, float]) -> Series:
    series = Series()
    for at, tokens, seconds in readings:
        series.add(at, tokens, seconds)
    return series


def test_a_run_of_readings_gives_now_average_and_thirty_slices():
    # 40 tokens/s for ten seconds of work, then a pause, then 20 tokens/s.
    series = _series(
        (0, 0, 0), (2, 80, 2), (4, 160, 4), (6, 160, 4), (8, 160, 4), (10, 200, 6),
    )
    figures = series.figures(10)
    assert figures is not None
    # "now" is the latest stretch with tokens: 40 tokens over 2 s of work.
    assert figures["now"] == pytest.approx(20.0)
    # The average is all tokens over all compute time: 200 / 6.
    assert figures["average"] == pytest.approx(200 / 6)
    history = figures["history"]
    assert len(history) == 30
    # The window of the course ends at 10 s: the last slice holds the stretch
    # ending at 10, the slices for 4..8 s hold the pause as 0.
    assert history[-1] == pytest.approx(20.0)
    assert history[-2] == 0.0
    assert history[-3] == 0.0
    assert history[-4] == pytest.approx(40.0)
    assert history[-5] == pytest.approx(40.0)
    assert history[0] == 0.0


def test_the_pause_after_the_last_token_keeps_now_for_five_minutes_and_then_nothing():
    series = _series((0, 0, 0), (2, 80, 2))
    for at in range(4, 300, 2):
        series.add(at, 80, 2)
    assert series.figures(298)["now"] == pytest.approx(40.0)
    # The stretch with tokens ended at 2 s; at 305 s it has left the window.
    series.add(302, 80, 2)
    series.add(304, 80, 2)
    assert series.figures(304) is None


def test_the_average_spans_only_the_last_five_minutes():
    series = _series((0, 0, 0), (1, 200, 1))  # 200 tokens/s, long ago
    series.add(298, 200, 1)
    series.add(300, 240, 2)  # 40 tokens/s now
    series.add(302, 280, 3)
    figures = series.figures(302)
    # The stretch ending at 1 s is outside the window of 302 - 300.
    assert figures["average"] == pytest.approx(40.0)


def test_a_counter_that_begins_again_ends_the_series_without_a_negative_number():
    series = _series((0, 0, 0), (2, 80, 2), (4, 160, 4))
    series.add(6, 10, 0.5)  # the server was restarted: the counters started again
    series.add(8, 50, 1.5)
    figures = series.figures(8)
    assert figures["now"] == pytest.approx(40.0)
    assert figures["average"] == pytest.approx(40.0)
    assert min(figures["history"]) >= 0.0
    # Nothing of the old run is in the course: before the restart reading
    # there is only 0.
    assert figures["history"][-5] == 0.0


def test_a_series_without_a_token_says_nothing_instead_of_a_zero():
    assert _series().figures(10) is None
    assert _series((0, 0, 0)).figures(0) is None
    assert _series((0, 0, 0), (2, 0, 0), (4, 0, 0)).figures(4) is None


def test_the_readings_older_than_the_window_are_dropped_from_memory():
    series = Series()
    for at in range(0, 2000, 2):
        series.add(at, at * 10, at / 4)
    assert len(series._readings) <= 300 / 2 + 2


def _app(**runners):
    return SimpleNamespace(state=SimpleNamespace(**runners))


class _Runner:
    def __init__(self, run: Lauf | None, key: str | None = "k"):
        self._run = run
        self.schluessel = key

    def lauf(self):
        return self._run


def _lauf(port: int) -> Lauf:
    return Lauf(modell="a.gguf", kontext=8192, schichten=99, port=port)


def test_a_round_reads_a_running_server_and_never_a_stopped_one(monkeypatch):
    asked = []

    def read(port, key):
        asked.append((port, key))
        return (80.0 * len(asked), 2.0 * len(asked))

    monkeypatch.setattr(throughput, "_read", read)
    app = _app(
        modellrunner=_Runner(_lauf(8080)),
        agentenrunner=_Runner(None),
        sprachputzrunner=_Runner(None),
        sprachrunner=_Runner(None),
    )
    watch = Watch()
    watch.sample(app, 0)
    watch.sample(app, 2)
    assert asked == [(8080, "k"), (8080, "k")]
    assert watch.figures("model", 2)["now"] == pytest.approx(40.0)
    assert watch.figures("agent", 2) is None
    assert watch.figures("speech", 2) is None
    assert watch.figures("cleanup", 2) is None


def test_a_server_that_stops_loses_its_series_and_a_new_run_begins_a_new_one(monkeypatch):
    values = iter([(80.0, 2.0), (160.0, 4.0), (40.0, 1.0), (80.0, 2.0)])
    monkeypatch.setattr(throughput, "_read", lambda port, key: next(values))
    first = _Runner(_lauf(8080))
    app = _app(modellrunner=first, agentenrunner=None, sprachputzrunner=None, sprachrunner=None)
    watch = Watch()
    watch.sample(app, 0)
    watch.sample(app, 2)
    assert watch.figures("model", 2) is not None
    first._run = None
    watch.sample(app, 4)
    assert watch.figures("model", 4) is None
    # A new run: the first reading only starts the series, no stretch yet.
    first._run = _lauf(8080)
    watch.sample(app, 6)
    assert watch.figures("model", 6) is None
    watch.sample(app, 8)
    assert watch.figures("model", 8)["now"] == pytest.approx(40.0)


def test_a_failed_read_leaves_the_series_as_it_was(monkeypatch):
    readings = iter([(80.0, 2.0), None, (240.0, 6.0)])
    monkeypatch.setattr(throughput, "_read", lambda port, key: next(readings))
    app = _app(modellrunner=_Runner(_lauf(8080)), agentenrunner=None, sprachputzrunner=None,
               sprachrunner=None)
    watch = Watch()
    for at in (0, 2, 4):
        watch.sample(app, at)
    assert watch.figures("model", 4)["now"] == pytest.approx(40.0)


def test_every_server_the_program_starts_carries_the_metrics_switch(tmp_path):
    # One command builder serves the model, agent, clean-up, speech and
    # embedding servers alike.
    command = Modellrunner(tmp_path).befehl("a.gguf", 8192, 99, 8080)
    assert "--metrics" in command


def test_the_embedding_and_speech_commands_carry_it_too(tmp_path):
    from app import einbettungsserver, sprachserver

    embedding = einbettungsserver.runner_bauen(tmp_path, None, 8091, None)
    speech = sprachserver.runner_bauen(tmp_path, None, 8093, None)
    cleanup = sprachserver.putzrunner_bauen(tmp_path, None, 8094, None)
    for runner in (embedding, speech, cleanup):
        assert "--metrics" in runner.befehl("a.gguf", 8192, 99, 8080)


def _route(client, server):
    return client.get(f"/api/v1/servers/{server}/throughput")


def test_the_route_answers_nothing_without_a_reading_with_tokens(client):
    for server in ("model", "agent", "cleanup", "speech"):
        reply = _route(client, server)
        assert reply.status_code == 200, reply.text
        assert reply.json() == {"now": None, "average": None, "history": []}


def test_the_route_tells_the_figures_of_the_series(client):
    watch = client.app.state.throughput
    series = watch._series["model"]
    now = throughput.time.monotonic()
    series.add(now - 4, 0, 0)
    series.add(now - 2, 80, 2)
    series.add(now, 160, 4)
    body = _route(client, "model").json()
    assert body["now"] == pytest.approx(40.0)
    assert body["average"] == pytest.approx(40.0)
    assert len(body["history"]) == 30


def test_the_route_knows_only_the_four_servers_that_make_text(client):
    assert _route(client, "image").status_code == 422
    assert _route(client, "embedding").status_code == 422
