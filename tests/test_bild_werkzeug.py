"""The drawing tool — offered like the built-ins, honest without a painter."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.tools import bild_werkzeug
from app.tools.registry import WerkzeugRegistry
from tests.conftest import NOT_JSON, Antwort, Bilddienst


def test_registry_bietet_draw_image_mit_zugang(tmp_path):
    registry = WerkzeugRegistry(
        [], bild_zugang=("http://127.0.0.1:1/api/v1", tmp_path, "testschluessel")
    )
    assert bild_werkzeug.WERKZEUG_NAME in registry.namen()
    offen = [w["function"]["name"] for w in registry.als_openai_werkzeuge()]
    assert bild_werkzeug.WERKZEUG_NAME in offen
    assert registry.server_von(bild_werkzeug.WERKZEUG_NAME) == bild_werkzeug.SERVER_NAME
    zeile = next(
        e for e in registry.uebersicht() if e["name"] == bild_werkzeug.WERKZEUG_NAME
    )
    assert zeile["needs_confirmation"] is False


def test_ohne_zugang_gibt_es_das_werkzeug_nicht():
    registry = WerkzeugRegistry([])
    assert bild_werkzeug.WERKZEUG_NAME not in registry.namen()
    assert registry.server_von(bild_werkzeug.WERKZEUG_NAME) == ""


def test_leerer_prompt_wird_abgewiesen(tmp_path):
    with pytest.raises(bild_werkzeug.BildWerkzeugFehler):
        asyncio.run(
            bild_werkzeug.ausfuehren({}, "http://127.0.0.1:1", tmp_path, "testschluessel")
        )


def test_ohne_maler_kommt_ein_ehrlicher_satz(tmp_path, monkeypatch):
    monkeypatch.setattr(
        bild_werkzeug.httpx,
        "AsyncClient",
        lambda timeout, headers: Bilddienst(modelle=[], programm_da=False),
    )
    text = asyncio.run(
        bild_werkzeug.ausfuehren({"prompt": "a dog"}, "http://x", tmp_path, "testschluessel")
    )
    assert "No image generator" in text


def test_ohne_modell_kommt_ein_ehrlicher_satz(tmp_path, monkeypatch):
    monkeypatch.setattr(
        bild_werkzeug.httpx,
        "AsyncClient",
        lambda timeout, headers: Bilddienst(modelle=[], programm_da=True),
    )
    text = asyncio.run(
        bild_werkzeug.ausfuehren({"prompt": "a dog"}, "http://x", tmp_path, "testschluessel")
    )
    assert "No image model" in text


def test_a_refused_model_list_names_its_reason(tmp_path, monkeypatch):
    """A failed model list carries no ``programm_da`` — read as a body it
    would claim the generator is missing. The reason goes to the model."""
    service = Bilddienst(model_list_status=401)
    monkeypatch.setattr(bild_werkzeug.httpx, "AsyncClient", lambda timeout, headers: service)
    text = asyncio.run(
        bild_werkzeug.ausfuehren({"prompt": "a dog"}, "http://x", tmp_path, "testschluessel")
    )
    assert text == "The image could not be generated: Invalid session key."
    assert "No image generator" not in text
    assert service.gezeichnet == []


def test_refused_defaults_do_not_draw_with_fixed_values(tmp_path, monkeypatch):
    service, text = _zeichnen_mit_dienst(
        tmp_path, monkeypatch, {"c1": {"modell": "a.safetensors", "familie": "sdxl"}}, "c1",
        vorgaben={"detail": "defaults unreadable"}, vorgaben_status=500,
    )
    assert text == "The image could not be generated: defaults unreadable"
    assert service.gezeichnet == []


def _draw_with_model_list(tmp_path, monkeypatch, answer):
    """One call whose model list answers with exactly ``answer``."""
    service = Bilddienst(answers={"/bild/modelle": answer})
    monkeypatch.setattr(bild_werkzeug.httpx, "AsyncClient", lambda timeout, headers: service)
    text = asyncio.run(
        bild_werkzeug.ausfuehren({"prompt": "a dog"}, "http://x", tmp_path, "testschluessel")
    )
    assert service.gezeichnet == []
    return text


@pytest.mark.parametrize(
    "answer, reason",
    [
        # Not JSON at all: the raw text is the reason.
        (Antwort(NOT_JSON, 502, text="Bad gateway upstream"), "Bad gateway upstream"),
        # Not JSON and empty: the status line stands in.
        (Antwort(NOT_JSON, 503, text=""), "HTTP 503 Service Unavailable"),
        # An object without a detail, and one with an empty detail.
        (Antwort({"fehler": "x"}, 500), "HTTP 500 Internal Server Error"),
        (Antwort({"detail": ""}, 500), "HTTP 500 Internal Server Error"),
        # A JSON list and a JSON null: no ``.get`` on either.
        (Antwort(["kaputt"], 500), '["kaputt"]'),
        (Antwort(None, 500), "null"),
        # A rejected request: the ``msg`` parts, not a Python repr.
        (
            Antwort({"detail": [
                {"loc": ["query", "modell"], "msg": "Field required"},
                {"loc": ["query", "x"], "msg": "Input should be a number"},
            ]}, 422),
            "Field required; Input should be a number",
        ),
    ],
)
def test_a_failure_without_a_readable_detail_still_names_a_reason(
    tmp_path, monkeypatch, answer, reason
):
    assert _draw_with_model_list(tmp_path, monkeypatch, answer) == (
        f"The image could not be generated: {reason}"
    )


# The two sentences for a 200 the tool cannot use, word for word.
_UNUSABLE = (
    "The image could not be generated: the image service returned an unusable "
    "response."
)
_NO_PICTURE = "The image could not be generated: the image service returned no image."


@pytest.mark.parametrize(
    "answer",
    [
        Antwort(NOT_JSON, 200, text="<html>proxy</html>"),
        Antwort(["a.safetensors"], 200),
        Antwort(None, 200),
    ],
)
def test_an_unreadable_model_list_with_200_draws_nothing(tmp_path, monkeypatch, answer):
    text = _draw_with_model_list(tmp_path, monkeypatch, answer)
    assert text == _UNUSABLE
    assert "No image generator" not in text


@pytest.mark.parametrize(
    "answer",
    [Antwort(NOT_JSON, 200, text="<html>proxy</html>"), Antwort(["sdxl"], 200)],
)
def test_unreadable_defaults_with_200_draw_nothing(tmp_path, monkeypatch, answer):
    service, text = _zeichnen_mit_dienst(
        tmp_path, monkeypatch, {"c1": {"modell": "a.safetensors", "familie": "sdxl"}}, "c1",
        answers={"/bild/vorgaben": answer},
    )
    assert text == _UNUSABLE
    assert service.gezeichnet == []


_WINDOW_C1 = {"c1": {"modell": "b.safetensors", "familie": "sdxl"}}


def _draw_from_job(tmp_path, monkeypatch, service, job_id="j1"):
    """One call from a job: the tool asks the job route for its chat."""
    monkeypatch.setattr(bild_werkzeug.httpx, "AsyncClient", lambda timeout, headers: service)
    return asyncio.run(
        bild_werkzeug.ausfuehren(
            {"prompt": "a dog"}, "http://x", tmp_path, "testschluessel", job_id=job_id
        )
    )


def test_a_failed_picture_window_does_not_draw_with_the_first_model(
    tmp_path, monkeypatch
):
    service, text = _zeichnen_mit_dienst(
        tmp_path, monkeypatch, _WINDOW_C1, "c1",
        answers={"/settings/resolved/bildfenster": Antwort({"detail": "settings broken"}, 500)},
    )
    assert text == "The image could not be generated: settings broken"
    assert service.gezeichnet == []


def test_a_failed_job_does_not_draw_with_the_first_model(
    tmp_path, monkeypatch
):
    service = Bilddienst(
        _WINDOW_C1, jobs={"j1": "c1"},
        answers={"/jobs/j1": Antwort({"detail": "Invalid session key."}, 401)},
    )
    text = _draw_from_job(tmp_path, monkeypatch, service)
    assert text == "The image could not be generated: Invalid session key."
    assert service.gezeichnet == []


def test_an_unknown_job_is_no_failure(tmp_path, monkeypatch):
    """Silence probe: the job route answers 404 for a job it does not know —
    that is "no chat", not a failure; drawn with the first model as before."""
    service = Bilddienst(_WINDOW_C1)
    text = _draw_from_job(tmp_path, monkeypatch, service, job_id="unbekannt")
    assert text.startswith("The image was generated")
    assert service.gezeichnet[0]["modell"] == "a.safetensors"


def test_a_job_with_a_chat_draws_with_its_window(tmp_path, monkeypatch):
    """Silence probe: job and window both answer — the chat's own model."""
    service = Bilddienst(_WINDOW_C1, jobs={"j1": "c1"})
    text = _draw_from_job(tmp_path, monkeypatch, service)
    assert text.startswith("The image was generated")
    assert service.gezeichnet[0]["modell"] == "b.safetensors"


_ALL_CALLS = (
    "/bild/modelle", "/bild/vorgaben", "/settings/resolved/bildfenster", "/jobs/j1", "/bild",
)


@pytest.mark.parametrize(
    "ending, error, reason",
    [
        ("/bild/modelle", httpx.ConnectError("Connection refused"), "Connection refused"),
        ("/bild/vorgaben", httpx.ReadTimeout(""), "ReadTimeout"),
        ("/settings/resolved/bildfenster", httpx.ConnectError("Connection reset"),
         "Connection reset"),
        ("/jobs/j1", httpx.ConnectTimeout("timed out"), "timed out"),
        ("/bild", httpx.ConnectError("Connection refused"), "Connection refused"),
    ],
)
def test_a_call_without_an_answer_names_the_reason(tmp_path, monkeypatch, ending, error, reason):
    """A call that got no answer at all reaches the model as a sentence, not
    as a raw exception — at every one of the tool's calls."""
    service = Bilddienst(_WINDOW_C1, jobs={"j1": "c1"}, answers={ending: error})
    text = _draw_from_job(tmp_path, monkeypatch, service)
    assert text == f"The image could not be generated: {reason}"
    # Only the draw call itself reaches the route — with the chat's model.
    assert [body["modell"] for body in service.gezeichnet] == (
        ["b.safetensors"] if ending == "/bild" else []
    )


@pytest.mark.parametrize("ending", _ALL_CALLS)
def test_an_undecodable_answer_does_not_draw_with_the_first_model(
    tmp_path, monkeypatch, ending
):
    """An httpx error that is no transport error (here: a body it cannot
    decode) is a failure at every call too — never a silent "no chat" or
    "no window" that draws with the first model in the folder."""
    service = Bilddienst(
        _WINDOW_C1, jobs={"j1": "c1"},
        answers={ending: httpx.DecodingError("Error decoding the body")},
    )
    text = _draw_from_job(tmp_path, monkeypatch, service)
    assert text == "The image could not be generated: Error decoding the body"
    assert [body["modell"] for body in service.gezeichnet] == (
        ["b.safetensors"] if ending == "/bild" else []
    )


def test_a_timed_out_drawing_is_not_drawn_again(
    tmp_path, monkeypatch
):
    """The draw request went out and no answer came in time: the route may
    still be drawing, so the model must not send it a second time."""
    service = Bilddienst(
        _WINDOW_C1, jobs={"j1": "c1"}, answers={"/bild": httpx.ReadTimeout("")}
    )
    text = _draw_from_job(tmp_path, monkeypatch, service)
    assert text == (
        "Image generation timed out: no response was received within 15 minutes. "
        "Generation may still be running; do not start it again."
    )


@pytest.mark.parametrize(
    "answer",
    [Antwort(NOT_JSON, 200, text="<html>proxy</html>"), Antwort(["bild.png"], 200)],
)
def test_an_unreadable_draw_answer_with_200_names_the_reason(tmp_path, monkeypatch, answer):
    service = Bilddienst(_WINDOW_C1, jobs={"j1": "c1"}, answers={"/bild": answer})
    text = _draw_from_job(tmp_path, monkeypatch, service)
    assert text == _UNUSABLE


def test_a_large_foreign_body_is_cut_like_the_picture_log(
    tmp_path, monkeypatch
):
    """A proxy's HTML page is kept to the painter's log limit, from the end."""
    from app import bildrunner

    lines = [f"<p>line {number}</p>" for number in range(2000)]
    text = _draw_with_model_list(
        tmp_path, monkeypatch, Antwort(NOT_JSON, 502, text="\n".join(lines))
    )
    reason = text.removeprefix("The image could not be generated: ")
    assert len(reason) <= bildrunner.LOG_LIMIT
    assert reason.endswith("<p>line 1999</p>")
    assert "<p>line 0</p>" not in reason


def test_a_long_detail_of_the_route_stays_whole(tmp_path, monkeypatch):
    """Silence probe: the route's own ``detail`` — the run's log of a failed
    picture included — is not cut, whatever its length."""
    from app import bildrunner

    detail = "\n".join(f"[ERROR] step {number}" for number in range(400))
    assert len(detail) > bildrunner.LOG_LIMIT
    service = Bilddienst(
        _WINDOW_C1, jobs={"j1": "c1"},
        answers={"/bild": Antwort({"detail": detail}, 500)},
    )
    text = _draw_from_job(tmp_path, monkeypatch, service)
    assert text == f"The image could not be generated: {detail}"


@pytest.mark.parametrize(
    "ending, body",
    [
        ("/bild/modelle", {"programm_da": True, "modelle": ["a.safetensors"], "families": []}),
        ("/bild/modelle", {"programm_da": True, "modelle": "a.safetensors"}),
        ("/bild/vorgaben", {"family": "sdxl", "parts": []}),
        ("/bild/vorgaben", {"family": "sdxl", "standalone": "yes"}),
        ("/bild/vorgaben", {"family": ["sdxl"]}),
        ("/bild/modelle", {"programm_da": "yes", "modelle": ["b.safetensors"]}),
        # The entries inside count too: a model name, a family per model.
        ("/bild/modelle", {"programm_da": True, "modelle": [["b.safetensors"]]}),
        ("/bild/modelle", {"programm_da": True, "modelle": ["b.safetensors"],
                           "families": {"b.safetensors": ["sdxl"]}}),
        ("/settings/resolved/bildfenster",
         {"wert": {"modell": "b.safetensors", "familie": ["sdxl"]}}),
    ],
)
def test_a_field_of_the_wrong_kind_draws_nothing(tmp_path, monkeypatch, ending, body):
    """A 200 whose fields have the wrong kind is read like an unreadable
    answer: nothing is drawn, the model reads why."""
    service = Bilddienst(_WINDOW_C1, jobs={"j1": "c1"}, answers={ending: Antwort(body)})
    text = _draw_from_job(tmp_path, monkeypatch, service)
    assert text == _UNUSABLE
    assert service.gezeichnet == []


@pytest.mark.parametrize("bild", [None, 5, ["x.png"], "", "missing", "../x.png", "/tmp/x.png", "sub/x.png"])
def test_a_draw_answer_without_a_picture_name_names_the_reason(tmp_path, monkeypatch, bild):
    body = {"seed": 1} if bild == "missing" else {"bild": bild, "seed": 1}
    service = Bilddienst(_WINDOW_C1, jobs={"j1": "c1"}, answers={"/bild": Antwort(body)})
    text = _draw_from_job(tmp_path, monkeypatch, service)
    assert text == _NO_PICTURE


@pytest.mark.parametrize(
    "detail, reason",
    [
        ([{"loc": ["x"]}, "busy"], '[{"loc":["x"]},"busy"]'),
        (42, "42"),
        (True, "true"),
    ],
)
def test_any_other_detail_reaches_the_model_as_json(tmp_path, monkeypatch, detail, reason):
    service = Bilddienst(
        _WINDOW_C1, jobs={"j1": "c1"}, answers={"/bild": Antwort({"detail": detail}, 409)}
    )
    text = _draw_from_job(tmp_path, monkeypatch, service)
    assert text == f"The image could not be generated: {reason}"


def test_an_invalid_address_names_the_reason(tmp_path, monkeypatch):
    service = Bilddienst(
        _WINDOW_C1, jobs={"j1": "c1"},
        answers={"/bild/modelle": httpx.InvalidURL("Invalid URL 'x'")},
    )
    text = _draw_from_job(tmp_path, monkeypatch, service)
    assert text == "The image could not be generated: Invalid URL 'x'"
    assert service.gezeichnet == []


def test_a_detail_object_reaches_the_model_as_json(tmp_path, monkeypatch):
    service = Bilddienst(
        _WINDOW_C1, jobs={"j1": "c1"},
        answers={"/bild": Antwort({"detail": {"code": "busy", "wait": 3}}, 409)},
    )
    text = _draw_from_job(tmp_path, monkeypatch, service)
    assert text == 'The image could not be generated: {"code":"busy","wait":3}'


def test_missing_fields_still_draw_as_before(tmp_path, monkeypatch):
    """Silence probe: a field that is missing or null reads as empty, as
    before — only a wrong kind stops the drawing."""
    service = Bilddienst(
        _WINDOW_C1, jobs={"j1": "c1"},
        answers={
            "/bild/modelle": Antwort({"programm_da": True, "modelle": ["b.safetensors"],
                                      "families": None}),
            "/bild/vorgaben": Antwort({"family": None, "parts": None}),
            "/settings/resolved/bildfenster": Antwort(
                {"wert": {"modell": "b.safetensors", "familie": None}}
            ),
        },
    )
    text = _draw_from_job(tmp_path, monkeypatch, service)
    assert text.startswith("The image was generated")
    assert service.gezeichnet[0]["modell"] == "b.safetensors"


def test_text_entries_draw_as_before(tmp_path, monkeypatch):
    """Silence probe: model names, families and the window's family as text
    draw exactly as before."""
    service = Bilddienst(
        _WINDOW_C1, jobs={"j1": "c1"}, familien={"b.safetensors": "sdxl"},
    )
    text = _draw_from_job(tmp_path, monkeypatch, service)
    assert text.startswith("The image was generated")
    assert service.gezeichnet[0]["modell"] == "b.safetensors"
    assert service.gezeichnet[0]["familie"] == "sdxl"


def test_both_lookups_with_200_draw_as_before(tmp_path, monkeypatch):
    """Silence probe: both answers fine — drawn as before, no refusal."""
    service, text = _zeichnen_mit_dienst(
        tmp_path, monkeypatch, {"c1": {"modell": "a.safetensors", "familie": "sdxl"}}, "c1",
        vorgaben={"family": "sdxl"},
    )
    assert "could not be generated" not in text
    assert text.startswith("The image was generated")
    assert service.gezeichnet and service.gezeichnet[0]["prompt"] == "a dog"


def test_der_aufruf_traegt_den_sitzungsschluessel(tmp_path, monkeypatch):
    """This tool calls the service's own API over HTTP like any
    other caller — the session key guard does not exempt it. Without the
    header these calls would all be rejected with 401.

    And the language rides along: every sentence the picture route answers
    with is written in the language of the request, and this tool's reader
    is a model, which must not be handed German. Drop the second header and
    the tool quietly goes back to handing the model the window's language —
    this assertion is what keeps that from happening unnoticed."""
    gesehen = {}

    def gefaelschter_client(timeout, headers):
        gesehen["headers"] = headers
        return Bilddienst(modelle=[], programm_da=False)

    monkeypatch.setattr(bild_werkzeug.httpx, "AsyncClient", gefaelschter_client)
    asyncio.run(
        bild_werkzeug.ausfuehren({"prompt": "a dog"}, "http://x", tmp_path, "testschluessel")
    )
    assert gesehen["headers"] == {
        "X-Sitzungsschluessel": "testschluessel",
        "X-Ui-Language": "en",
    }


# --- The model of the chat the tool runs in ---------------------------------

# The stand-in itself is shared — tests/conftest.py, ``Bilddienst``: one table
# of the service's routes for every test file that drives this tool. It holds
# the folder's two models and answers the model list with what its headers say
# (`families`, app/api/v1/bild.py:321, filled :422).


def _zeichnen_mit_dienst(tmp_path, monkeypatch, fenster, chat_id, **dienst_werte):
    """One call of the tool against the stand-in — and the stand-in itself.

    A call that is REFUSED draws nothing, so `gezeichnet[0]` would raise on
    exactly the case the two guards below are about; those two read what
    went to the picture route instead. `dienst_werte` go to the stand-in:
    what the folder's headers say, and whether `/bild/vorgaben` answers.
    """
    dienst = Bilddienst(fenster, **dienst_werte)
    monkeypatch.setattr(bild_werkzeug.httpx, "AsyncClient", lambda timeout, headers: dienst)
    text = asyncio.run(
        bild_werkzeug.ausfuehren(
            {"prompt": "a dog"}, "http://x", tmp_path, "testschluessel", chat_id=chat_id
        )
    )
    return dienst, text


def _zeichnen(tmp_path, monkeypatch, fenster, chat_id):
    dienst, text = _zeichnen_mit_dienst(tmp_path, monkeypatch, fenster, chat_id)
    return dienst.gezeichnet[0]["modell"], text


def test_der_chat_zeichnet_mit_seinem_eigenen_modell(tmp_path, monkeypatch):
    fenster = {"c1": {"modell": "b.safetensors"}, "c2": {"modell": "a.safetensors"}}
    assert _zeichnen(tmp_path, monkeypatch, fenster, "c1")[0] == "b.safetensors"
    assert _zeichnen(tmp_path, monkeypatch, fenster, "c2")[0] == "a.safetensors"


def test_fehlt_das_modell_des_chats_zeichnet_das_erste_und_sagt_es(
    tmp_path, monkeypatch, caplog
):
    """The silence check: a model gone from the folder, a chat without one,
    and a run without a chat all fall back to the first — and the log says
    which case it was."""
    caplog.set_level("INFO", logger=bild_werkzeug.__name__)
    fenster = {"c1": {"modell": "weg.safetensors"}, "c2": {}}
    assert _zeichnen(tmp_path, monkeypatch, fenster, "c1")[0] == "a.safetensors"
    assert "the chat's model weg.safetensors is not in the folder" in caplog.text
    assert _zeichnen(tmp_path, monkeypatch, fenster, "c2")[0] == "a.safetensors"
    assert _zeichnen(tmp_path, monkeypatch, fenster, None)[0] == "a.safetensors"
    assert caplog.text.count("no model is set in this chat's picture window") == 1
    assert "a run outside a chat has no picture window" in caplog.text


def test_ein_auftragslauf_liest_kein_bildfenster(tmp_path, monkeypatch):
    """A job hands its own id in as the chat id; it has no picture window,
    so the registry does not pass it on to the drawing tool."""
    dienst = Bilddienst({"lauf1": {"modell": "b.safetensors"}})
    monkeypatch.setattr(bild_werkzeug.httpx, "AsyncClient", lambda timeout, headers: dienst)
    registry = WerkzeugRegistry([], bild_zugang=("http://x", tmp_path, "testschluessel"))
    asyncio.run(
        registry.ausfuehren(
            bild_werkzeug.WERKZEUG_NAME, {"prompt": "a dog"}, chat_id="lauf1", herkunft="agent"
        )
    )
    assert dienst.gezeichnet[0]["modell"] == "a.safetensors"


def test_die_registry_reicht_den_chat_weiter(tmp_path, monkeypatch):
    dienst = Bilddienst({"c9": {"modell": "b.safetensors"}})
    monkeypatch.setattr(bild_werkzeug.httpx, "AsyncClient", lambda timeout, headers: dienst)
    registry = WerkzeugRegistry(
        [], bild_zugang=("http://x", tmp_path, "testschluessel")
    )
    asyncio.run(registry.ausfuehren(bild_werkzeug.WERKZEUG_NAME, {"prompt": "a dog"}, chat_id="c9"))
    assert dienst.gezeichnet[0]["modell"] == "b.safetensors"


# --- The description follows the image model --------------------------------


def test_die_beschreibung_ist_fuer_sdxl_gebaut():
    """A checkpoint family reads its prompt with CLIP: keyword phrases,
    weights, 77-token pieces — and it has no distilled guidance to send."""
    from app import image_families

    werkzeug = bild_werkzeug.werkzeug_beschreibung(image_families.get("sdxl"))
    assert "SDXL" in werkzeug.beschreibung
    assert "English" in werkzeug.beschreibung
    assert "keyword phrases" in werkzeug.beschreibung
    assert "(word:1.2)" in werkzeug.beschreibung
    assert "77 tokens" in werkzeug.beschreibung
    assert "guidance" not in (werkzeug.schema or {}).get("properties", {})


def test_die_beschreibung_ist_fuer_flux_gebaut():
    """Flux reads sentences (T5, 256-token pieces), starts at CFG 1 — where a
    negative prompt does nothing — and it DOES have a guidance."""
    from app import image_families

    werkzeug = bild_werkzeug.werkzeug_beschreibung(image_families.get("flux"))
    assert "Flux" in werkzeug.beschreibung
    assert "complete, fluent sentences" in werkzeug.beschreibung
    assert "256 tokens" in werkzeug.beschreibung
    assert "no effect" in werkzeug.beschreibung
    felder = (werkzeug.schema or {}).get("properties", {})
    assert "guidance" in felder


def test_eine_familie_ohne_txt2img_bekommt_keine_beschreibung_mehr():
    """The refusing DESCRIPTION from the earlier build stays gone.

    A family that cannot draw from text is not offered the tool at all
    (app/tools/registry.py), so its description has no refusal to carry — a
    sentence saying "this does nothing" is a promise the tool cannot keep,
    and it would ride in every request of that run. The refusal that does
    exist is spoken where the call happens, when the window has turned
    around since the offer (`ausfuehren`, below) — never in the text the
    model reads beforehand.
    """
    from app import image_families

    familie = image_families.get("wan")
    assert "txt2img" not in familie.tasks
    werkzeug = bild_werkzeug.werkzeug_beschreibung(familie)
    assert "cannot make a picture from text" not in werkzeug.beschreibung
    assert "guidance" not in (werkzeug.schema or {}).get("properties", {})


def test_zwei_anfragen_derselben_familie_tragen_denselben_satz():
    """Byte-identical ACROSS two builds, not just within one: the description
    rides in every request, and one that wobbles between two turns costs the
    cache of the whole prompt prefix. Built twice from separately read
    families, the way two requests read them."""
    from app import image_families

    erste = bild_werkzeug.werkzeug_beschreibung(image_families.get("sdxl"), values={"cfg": 7.0})
    zweite = bild_werkzeug.werkzeug_beschreibung(image_families.get("sdxl"), values={"cfg": 7.0})
    assert erste.beschreibung == zweite.beschreibung
    assert erste.schema == zweite.schema


def _told_style(tmp_path, monkeypatch, chosen, styles) -> str:
    """What the prompt preparation is told as the style's name."""
    told: list[str] = []

    def preparation(body):
        told.append(body.get("stil"))
        return {"prompt": body["prompt"], "negativ": body["negativ"]}

    dienst = Bilddienst(
        {"c1": {"modell": "a.safetensors", "familie": "sdxl", "stil": chosen}},
        answers={"/settings/resolved/bildstile": styles},
        aufbereitung=preparation,
    )
    monkeypatch.setattr(bild_werkzeug.httpx, "AsyncClient", lambda timeout, headers: dienst)
    asyncio.run(
        bild_werkzeug.ausfuehren(
            {"prompt": "a lighthouse"}, "http://x", tmp_path, "testschluessel", chat_id="c1",
        )
    )
    assert len(dienst.gezeichnet) == 1, "the picture was not drawn"
    return told[0]


def test_the_preparation_is_told_only_a_style_that_exists(tmp_path, monkeypatch):
    """The window keeps its style by the style's id. The prompt preparation
    is told the name that style has now — and none for a style that is gone,
    the way the button in the picture studio sends none. Handed on as stored,
    the writer was told the name of a style nobody has any more."""
    kept = "5" * 32
    styles = Antwort({"wert": [{"id": kept, "name": "Lichtbild", "text": "{prompt}", "negativ": ""}]})
    assert _told_style(tmp_path, monkeypatch, kept, styles) == "Lichtbild"
    # A style that is gone, by its id or by the name an older chat kept.
    assert _told_style(tmp_path, monkeypatch, "7" * 32, styles) == ""
    assert _told_style(tmp_path, monkeypatch, "Foto", styles) == ""
    # A chat that chose before styles had ids finds its style by the name.
    assert _told_style(tmp_path, monkeypatch, "Lichtbild", styles) == "Lichtbild"
    # A list that cannot be read names no style; the picture is drawn anyway.
    assert _told_style(tmp_path, monkeypatch, kept, Antwort({"detail": "broken"}, 500)) == ""
    assert _told_style(tmp_path, monkeypatch, kept, httpx.ConnectError("reset")) == ""
    # The silence check: a window without a style asks for no list at all.
    assert _told_style(tmp_path, monkeypatch, "", httpx.ConnectError("never asked")) == ""


def test_genannte_werte_gehen_mit_und_das_fenster_bleibt(tmp_path, monkeypatch):
    """A number the user names travels with THIS picture and is written
    nowhere: the picture window is the user's, and a wish spoken once in a
    chat is not a setting."""
    dienst = Bilddienst({"c1": {"modell": "a.safetensors", "familie": "sdxl"}})
    monkeypatch.setattr(bild_werkzeug.httpx, "AsyncClient", lambda timeout, headers: dienst)
    text = asyncio.run(
        bild_werkzeug.ausfuehren(
            {"prompt": "a lighthouse", "width": 512, "height": 896, "seed": 42},
            "http://x", tmp_path, "testschluessel", chat_id="c1",
        )
    )
    koerper = dienst.gezeichnet[0]
    assert koerper["breite"] == 512
    assert koerper["hoehe"] == 896
    assert koerper["seed"] == 42
    # The prompt preparation and the picture route — no setting was written.
    assert [url for url, _ in dienst.aufrufe] == ["http://x/bild/prompt", "http://x/bild"]
    assert "512×896" in text and "seed 42" in text


def test_ohne_genannte_werte_bleibt_die_anfrage_wie_sie_war(tmp_path, monkeypatch):
    """The silence probe: a call that names nothing asks for exactly what it
    asked for before this change — the window's and the family's own values,
    and not one field the model did not name."""
    dienst = Bilddienst({})
    monkeypatch.setattr(bild_werkzeug.httpx, "AsyncClient", lambda timeout, headers: dienst)
    asyncio.run(
        bild_werkzeug.ausfuehren({"prompt": "a dog"}, "http://x", tmp_path, "testschluessel")
    )
    koerper = dienst.gezeichnet[0]
    assert koerper["prompt"] == "a dog"
    assert koerper["breite"] == 512
    assert koerper["hoehe"] == 512
    # And the counter-check for the passing-on: the same call WITH values
    # changes exactly those fields and nothing else.
    dienst2 = Bilddienst({})
    monkeypatch.setattr(bild_werkzeug.httpx, "AsyncClient", lambda timeout, headers: dienst2)
    asyncio.run(
        bild_werkzeug.ausfuehren(
            {"prompt": "a dog", "width": 1024}, "http://x", tmp_path, "testschluessel"
        )
    )
    assert dienst2.gezeichnet[0]["breite"] == 1024
    assert dienst2.gezeichnet[0]["hoehe"] == 512


def test_eine_video_familie_im_fenster_wird_beim_ausfuehren_abgewiesen(
    tmp_path, monkeypatch
):
    """The window can turn around between the offer and the call.

    A run outlives the offer it started with: the user switches the picture
    window to a family that cannot draw from text while the answer is still
    going, and the call that follows was made against the old offer. Then
    nothing is drawn and the model reads why — a video drawn from a text
    prompt and handed back as a picture is the one outcome that must not
    happen (app/tools/bild_werkzeug.py, the same rule the offer keeps).
    """
    dienst, text = _zeichnen_mit_dienst(
        tmp_path, monkeypatch, {"c1": {"modell": "a.safetensors", "familie": "wan"}}, "c1"
    )

    assert "cannot generate images from text" in text
    assert dienst.gezeichnet == [], dienst.gezeichnet


def test_ein_fenster_auf_sdxl_zeichnet_wie_bisher(tmp_path, monkeypatch):
    """Silence probe for the same guard: a window that stays where it was —
    at a family that draws from text — is drawn with, exactly as before.
    The check must not turn the ordinary call into a refusal."""
    dienst, text = _zeichnen_mit_dienst(
        tmp_path, monkeypatch, {"c1": {"modell": "a.safetensors", "familie": "sdxl"}}, "c1"
    )

    assert "was not drawn" not in text
    assert dienst.gezeichnet and dienst.gezeichnet[0]["prompt"] == "a dog"


def test_die_wache_liest_die_familie_dort_wo_die_zeichenroute_sie_liest(tmp_path, monkeypatch):
    """The window says no family and the route says nothing — then the header decides.

    Two voices can stay silent together: a picture window that names no
    family (a run outside a chat has none at all, a window whose model left
    the folder is read the same way) and `/bild/vorgaben`, which answers
    with an empty body here. The test stands for both with the window it
    has: the window names a model but no family, and the route answers
    nothing. Before this the guard knew of no family then and let the call
    through, while the draw route reads the model file's own header and
    would have recognised the video family very well: a text prompt against
    a video model comes back as VIDEO. The same header, reported by the
    service with the model list (app/api/v1/bild.py:321), is what the guard
    now reads.
    """
    dienst, text = _zeichnen_mit_dienst(
        tmp_path,
        monkeypatch,
        {"c1": {"modell": "b.safetensors"}},  # no family in the window
        "c1",
        familien={"b.safetensors": "wan"},  # the file's header, and no defaults
    )

    assert "cannot generate images from text" in text
    assert dienst.gezeichnet == [], dienst.gezeichnet


@pytest.mark.parametrize(
    "kopf",
    [
        # A family that draws from text: drawn with, as ever.
        "sdxl",
        # A KIT family (Flux brings its own encoders): read only for the one
        # question "can this model draw from text", the header must NOT slip
        # its kit into the request body — the route refuses a body with
        # `t5xxl` but no `diffusion_model` (app/bildbausatz.py:143).
        "flux",
    ],
)
def test_ein_kopf_der_zeichnen_kann_aendert_den_aufruf_nicht(tmp_path, monkeypatch, kopf):
    """Silence probes for the same guard: whatever the header says, as long
    as it draws from text, the call goes out exactly as before — with the
    window's own values and without anything the header might carry."""
    dienst, text = _zeichnen_mit_dienst(
        tmp_path,
        monkeypatch,
        # The window says NO family but carries an encoder — the state that
        # broke before: a family read from the header would have chosen the
        # kit and sent `t5xxl` along without a `diffusion_model` to assemble
        # it with, and the route refuses such a body (app/bildbausatz.py:143).
        {"c1": {"modell": "b.safetensors", "t5xxl": "t5.safetensors"}},
        "c1",
        familien={"b.safetensors": kopf},
    )

    assert "was not drawn" not in text
    assert dienst.gezeichnet and dienst.gezeichnet[0]["prompt"] == "a dog"
    # Nothing of the header's family reached the body: no `familie`, and the
    # window's own encoder is dropped like any other value without a family
    # to use it.
    assert "familie" not in dienst.gezeichnet[0]
    assert "t5xxl" not in dienst.gezeichnet[0]


class _Repo:
    """Just enough of the repositories for the window reading."""

    def __init__(self, wert, standard=""):
        self.einstellungen = self
        self._wert = wert
        self._standard = standard

    def zusammengefuehrt(self, schluessel, *, chat=None, vorgabe=None):
        if schluessel == "bild_standardmodell":
            return self._standard
        return self._wert


def _ordnung(tmp_path, monkeypatch, dateien):
    """A folder with real model files (their headers name the family)."""
    import json

    from app import bildinhalt

    for name, familie in dateien:
        (tmp_path / name).write_bytes(
            json.dumps({"__metadata__": {"familie": familie}}).encode()
            + b"\x00" * 8
        )
    del bildinhalt


def test_das_fenster_entscheidet_welche_familie_gilt(tmp_path, monkeypatch):
    """The window's model wins while it is in the folder — and its stated
    family wins over what the file's header says (the same order the
    drawing keeps)."""
    import json

    from app.tools import bild_werkzeug

    ordner = tmp_path / "bilder"
    ordner.mkdir()
    for name in ("a.safetensors", "b.safetensors"):
        (ordner / name).write_bytes(
            json.dumps({"__metadata__": {"modelspec.architecture": "stable-diffusion-xl-v1-base"}}).encode()
        )
    monkeypatch.setattr(bild_werkzeug, "ort", lambda config, was: ordner)
    repos = _Repo({"modell": "b.safetensors", "familie": "flux", "cfg": 3.5})

    fenster = bild_werkzeug.fensterbild(repos, "c1", None)

    assert fenster.familie is not None
    assert fenster.familie.name == "flux"
    assert fenster.values["cfg"] == 3.5


def test_ein_verschwundenes_modell_zeichnet_das_standardmodell(tmp_path, monkeypatch):
    """Gone from the folder, the window changes nothing — the default model
    draws, and the description has to say THAT model's family."""
    import json

    from app.tools import bild_werkzeug

    ordner = tmp_path / "bilder"
    ordner.mkdir()
    (ordner / "a.safetensors").write_bytes(
        json.dumps({"__metadata__": {"modelspec.architecture": "stable-diffusion-xl-v1-base"}}).encode()
    )
    monkeypatch.setattr(bild_werkzeug, "ort", lambda config, was: ordner)
    # The header the model list reads names SDXL for the default model.
    monkeypatch.setattr(
        bild_werkzeug.bildinhalt, "family",
        lambda pfad: "sdxl" if pfad.name == "a.safetensors" else None,
    )
    repos = _Repo({"modell": "weg.safetensors", "familie": "flux"}, standard="a.safetensors")

    fenster = bild_werkzeug.fensterbild(repos, "c1", None)

    assert fenster.familie is not None and fenster.familie.name == "sdxl"
    # Silence: without a default model nothing draws, and no family is told.
    ohne = bild_werkzeug.fensterbild(_Repo({"modell": "weg.safetensors"}), "c1", None)
    assert ohne.familie is None


def test_die_werkzeugliste_traegt_die_familie_des_fensters():
    """The list the model reads is built with the window's family — and
    without one it is the general sentence."""
    from app import image_families
    from app.tools import bild_werkzeug
    from app.tools.registry import WerkzeugRegistry

    registry = WerkzeugRegistry(
        [], bild_zugang=("http://x", None, "testschluessel")
    )
    ohne = registry.als_openai_werkzeuge(bild_fenster=None)
    zeichnen = next(w for w in ohne if w["function"]["name"] == bild_werkzeug.WERKZEUG_NAME)
    assert "SDXL" not in zeichnen["function"]["description"]

    mit = registry.als_openai_werkeuge if False else registry.als_openai_werkzeuge(
        bild_fenster=lambda: bild_werkzeug.FensterBild(image_families.get("sdxl"), {"cfg": 7.0})
    )
    zeichnen = next(w for w in mit if w["function"]["name"] == bild_werkzeug.WERKZEUG_NAME)
    assert "SDXL" in zeichnen["function"]["description"]
    assert "keyword phrases" in zeichnen["function"]["description"]


def test_der_seed_kommt_aus_der_antwort_nicht_aus_der_anfrage(tmp_path, monkeypatch):
    """The route turns -1 into a real seed so a picture can be drawn again —
    the reply and the stored message have to name THAT number, not what was
    asked for."""
    dienst = Bilddienst({})

    async def post(url, json=None, **_):
        dienst.gezeichnet.append(json)
        dienst.aufrufe.append((url, json or {}))
        # A different number than the one asked for: the route rolls its own.
        return Antwort({"bild": "out.png", "seed": 424242})

    monkeypatch.setattr(dienst, "post", post)
    monkeypatch.setattr(bild_werkzeug.httpx, "AsyncClient", lambda timeout, headers: dienst)
    text = asyncio.run(
        bild_werkzeug.ausfuehren(
            {"prompt": "a dog", "seed": -1}, "http://x", tmp_path, "testschluessel"
        )
    )
    assert "seed 424242" in text


def test_draws_from_text_kennt_die_drei_faelle():
    """The one predicate both ends of the drawing tool ask — the offer
    (app/tools/registry.py) and the call (app/tools/bild_werkzeug.py).

    An unknown family counts as one that draws: the values then come from
    the file's own header, and a "no" for a name nobody knows would turn a
    working call into a refusal.
    """
    from app import image_families

    assert image_families.draws_from_text(image_families.get("sdxl")) is True
    assert image_families.draws_from_text(image_families.get("wan")) is False
    assert image_families.draws_from_text(None) is True


# --- A stop of the run ends the picture ---------------------------------------


class _ZeichnetBisStopp(Bilddienst):
    """A picture route that draws until a stop reaches it, like the real one.

    ``stopps_noetig`` is how many stops it takes: a stop that arrives before
    the painter has started ends nothing, which is why the tool sends it again.
    """

    def __init__(self, stopps_noetig: int = 1):
        super().__init__()
        self.stopps = 0
        self.stopps_noetig = stopps_noetig
        self.angefangen = asyncio.Event()
        self._beendet = asyncio.Event()

    async def post(self, url, json=None, **_):
        if url.endswith("/bild/stop"):
            self.stopps += 1
            if self.stopps >= self.stopps_noetig:
                self._beendet.set()
            return Antwort(self._beendet.is_set())
        if url.endswith("/bild"):
            self.gezeichnet.append(json)
            self.angefangen.set()
            await self._beendet.wait()
            return Antwort({"detail": "Image generation cancelled"}, 499)
        return await super().post(url, json=json, **_)


def _zeichnen_und_stoppen(tmp_path, monkeypatch, dienst):
    monkeypatch.setattr(bild_werkzeug.httpx, "AsyncClient", lambda timeout, headers: dienst)
    monkeypatch.setattr(bild_werkzeug, "STOPP_TAKT_S", 0.01)

    async def lauf():
        abbruch = asyncio.Event()
        aufgabe = asyncio.ensure_future(
            bild_werkzeug.ausfuehren(
                {"prompt": "a dog"}, "http://x", tmp_path, "testschluessel",
                chat_id="c1", abbruch=abbruch,
            )
        )
        await asyncio.wait_for(dienst.angefangen.wait(), timeout=5)
        abbruch.set()
        return await asyncio.wait_for(aufgabe, timeout=5)

    return asyncio.run(lauf())


def test_a_stop_during_the_drawing_ends_the_picture(tmp_path, monkeypatch):
    """The run's stop reaches the painter: the route is asked to end the
    picture, and the answer is the route's own sentence for a stopped one —
    the tool does not wait out the picture for a run that is over."""
    dienst = _ZeichnetBisStopp()
    text = _zeichnen_und_stoppen(tmp_path, monkeypatch, dienst)
    assert text == "The image could not be generated: Image generation cancelled"
    assert dienst.stopps == 1


def test_a_stop_that_came_before_the_painter_started_is_sent_again(tmp_path, monkeypatch):
    dienst = _ZeichnetBisStopp(stopps_noetig=3)
    text = _zeichnen_und_stoppen(tmp_path, monkeypatch, dienst)
    assert text == "The image could not be generated: Image generation cancelled"
    assert dienst.stopps == 3


def test_a_stop_before_the_request_draws_nothing(tmp_path, monkeypatch):
    dienst = _ZeichnetBisStopp()
    monkeypatch.setattr(bild_werkzeug.httpx, "AsyncClient", lambda timeout, headers: dienst)
    abbruch = asyncio.Event()
    abbruch.set()
    text = asyncio.run(
        bild_werkzeug.ausfuehren(
            {"prompt": "a dog"}, "http://x", tmp_path, "testschluessel",
            chat_id="c1", abbruch=abbruch,
        )
    )
    assert text == "The image could not be generated: Image generation cancelled"
    assert dienst.gezeichnet == []
    assert dienst.stopps == 0


def test_a_signal_that_is_never_set_changes_nothing(tmp_path, monkeypatch):
    dienst = Bilddienst()
    monkeypatch.setattr(bild_werkzeug.httpx, "AsyncClient", lambda timeout, headers: dienst)
    text = asyncio.run(
        bild_werkzeug.ausfuehren(
            {"prompt": "a dog"}, "http://x", tmp_path, "testschluessel",
            chat_id="c1", abbruch=asyncio.Event(),
        )
    )
    assert "could not be generated" not in text
    assert not any(url.endswith("/bild/stop") for url, _ in dienst.aufrufe)


def test_a_stop_during_the_prompt_preparation_ends_the_run_at_once(tmp_path, monkeypatch):
    """The preparation is a model request of its own and can be slow: a stop
    that comes while it is out is not held until it answers."""

    class _Haengt(Bilddienst):
        def __init__(self):
            super().__init__()
            self.vorbereitung = asyncio.Event()

        async def post(self, url, json=None, **_):
            if url.endswith("/bild/prompt"):
                self.vorbereitung.set()
                await asyncio.Event().wait()
            return await super().post(url, json=json, **_)

    dienst = _Haengt()
    monkeypatch.setattr(bild_werkzeug.httpx, "AsyncClient", lambda timeout, headers: dienst)

    async def lauf():
        abbruch = asyncio.Event()
        aufgabe = asyncio.ensure_future(
            bild_werkzeug.ausfuehren(
                {"prompt": "a dog"}, "http://x", tmp_path, "testschluessel",
                chat_id="c1", abbruch=abbruch,
            )
        )
        await asyncio.wait_for(dienst.vorbereitung.wait(), timeout=5)
        abbruch.set()
        return await asyncio.wait_for(aufgabe, timeout=5)

    assert asyncio.run(lauf()) == "The image could not be generated: Image generation cancelled"
    assert dienst.gezeichnet == []


def test_the_signal_goes_to_the_drawing_tool_and_to_no_other():
    """The run's stop signal is handed to draw_image, and to run_command,
    whose command outlives its answer the same way: every other tool ends
    with its call, and a registry that does not know the keyword must not be
    handed it."""
    from types import SimpleNamespace

    from app.api.v1.generierung import _werkzeug_ausfuehren

    class _Register:
        def __init__(self):
            self.aufrufe: list[tuple[str, dict]] = []

        async def ausfuehren(self, name, argumente, bild_senke=None, **zusatz):
            self.aufrufe.append((name, zusatz))
            return "ok"

    register = _Register()
    signal = asyncio.Event()

    async def lauf():
        for name in (bild_werkzeug.WERKZEUG_NAME, "run_command", "read_file"):
            aufruf = SimpleNamespace(name=name, argumente={})
            await _werkzeug_ausfuehren(register, aufruf, "en", abbruch=signal)

    asyncio.run(lauf())
    gesehen = dict(register.aufrufe)
    assert gesehen[bild_werkzeug.WERKZEUG_NAME]["abbruch"] is signal
    assert gesehen["run_command"]["abbruch"] is signal
    assert "abbruch" not in gesehen["read_file"]


def test_draw_image_takes_a_family_s_format_rng_and_switch_lines_as_start_values(
    tmp_path, monkeypatch,
):
    """The VAE format, the RNG and the switch lines a family starts with go
    along where the chat set none; what the chat set wins. No family that
    draws from text starts with one today (PiD edits, Wan makes video), so
    Flux is given some here."""
    import dataclasses

    from app import image_families

    started = dataclasses.replace(
        image_families.get("flux").start, vae_format="flux2", rng="cpu",
        switches={"high_noise_steps": 8, "high_noise_cfg_scale": 3.5},
    )
    monkeypatch.setattr(image_families, "start_values", lambda name, file_name=None: started)
    model = "flux1-dev-Q4_K_S.gguf"
    drawn = []
    for window in (
        {"modell": model},
        {"modell": model, "vae_format": "sd3", "rng": "std_default",
         "switches": {"high_noise_steps": 4}},
    ):
        service, _ = _zeichnen_mit_dienst(
            tmp_path, monkeypatch, {"c1": window}, "c1", modelle=[model],
            familien={model: "flux"}, vorgaben={"family": "flux", "standalone": False, "parts": {}},
        )
        drawn.append(service.gezeichnet[0])
    assert (drawn[0]["vae_format"], drawn[0]["rng"]) == ("flux2", "cpu")
    assert drawn[0]["switches"] == {"high_noise_steps": 8, "high_noise_cfg_scale": 3.5}
    assert (drawn[1]["vae_format"], drawn[1]["rng"]) == ("sd3", "std_default")
    assert drawn[1]["switches"] == {"high_noise_steps": 4, "high_noise_cfg_scale": 3.5}


def test_draw_image_starts_a_distilled_model_at_its_own_values(tmp_path, monkeypatch):
    """The drawing tool reads the start values with the model's file name: a
    schnell file of Flux draws in 4 steps, not in the family's 20."""
    modelle = ["flux1-schnell-Q4_K_S.gguf", "flux1-dev-Q4_K_S.gguf"]
    vorgaben = {"family": "flux", "standalone": False, "parts": {}}
    gezeichnet = {}
    for name in modelle:
        dienst, _ = _zeichnen_mit_dienst(
            tmp_path, monkeypatch, {"c1": {"modell": name}}, "c1",
            modelle=modelle, familien={name: "flux" for name in modelle}, vorgaben=vorgaben,
        )
        gezeichnet[name] = dienst.gezeichnet[0]
    assert (gezeichnet[modelle[0]]["schritte"], gezeichnet[modelle[0]]["cfg"]) == (4, 1.0)
    assert (gezeichnet[modelle[1]]["schritte"], gezeichnet[modelle[1]]["cfg"]) == (20, 1.0)


# --- A model whose family is not read ------------------------------------------


class _RepoWithModelValues(_Repo):
    """The window reading plus what the picture server holds per model."""

    def __init__(self, wert, model_values):
        super().__init__(wert)
        self._model_values = model_values

    def zusammengefuehrt(self, schluessel, *, chat=None, vorgabe=None):
        if schluessel == "bildmodellwerte":
            return self._model_values
        return super().zusammengefuehrt(schluessel, chat=chat, vorgabe=vorgabe)


def test_a_model_whose_family_is_not_read_is_described_without_one(tmp_path, monkeypatch):
    """The tool's description follows the switch of the picture server: with
    the reading off, the header's family is not told to the language model —
    and with it on (the silence probe) it is, as before."""
    ordner = tmp_path / "bilder"
    ordner.mkdir()
    (ordner / "a.safetensors").write_bytes(b"x")
    monkeypatch.setattr(bild_werkzeug, "ort", lambda config, was: ordner)
    # What the file's header would say, were it asked.
    monkeypatch.setattr(bild_werkzeug.bildinhalt, "family", lambda pfad: "sdxl")
    window = {"modell": "a.safetensors"}

    read = bild_werkzeug.fensterbild(_RepoWithModelValues(window, {}), "c1", None)
    assert read.familie is not None and read.familie.name == "sdxl"

    unread = bild_werkzeug.fensterbild(
        _RepoWithModelValues(window, {"a.safetensors": {"family_detection": False}}), "c1", None
    )
    assert unread.familie is None


def test_draw_image_leaves_the_kit_of_such_a_model_to_the_service(tmp_path, monkeypatch):
    """Drawn from the chat, a model whose family is not read goes to the
    picture route exactly as the picture window sends it: the model alone,
    no family and no part named. The route then puts in the parts the model
    was given, the same for both."""
    model = "model.safetensors"
    vorgaben = {
        "family": "", "family_detection": False, "standalone": True,
        "parts": {"llm": "llm.gguf", "tokenizer": "tokenizer.json", "vae": "ae.safetensors"},
    }
    service, text = _zeichnen_mit_dienst(
        tmp_path, monkeypatch, {"c1": {"modell": model}}, "c1",
        modelle=[model], familien={model: ""}, vorgaben=vorgaben,
    )
    assert len(service.gezeichnet) == 1, text
    body = service.gezeichnet[0]
    assert body["modell"] == model
    assert "familie" not in body
    for field in ("diffusion_model", "t5xxl", "clip_l", "clip_g", "llm", "tokenizer", "vae"):
        assert field not in body, field


def test_in_a_chat_the_result_says_the_picture_hangs_on_the_answer_already(tmp_path, monkeypatch):
    """The model is told its path, and a model told a path writes a link onto
    it. In a chat the picture is attached to the answer already: the result
    says so and asks for no link and no image markdown — with the file name
    and the path still in it. In a job the picture is not attached to
    anything, and the sentence is not there."""
    painter = Bilddienst({})
    monkeypatch.setattr(bild_werkzeug.httpx, "AsyncClient", lambda timeout, headers: painter)
    registry = WerkzeugRegistry([], bild_zugang=("http://x", tmp_path, "testschluessel"))
    in_chat = asyncio.run(
        registry.ausfuehren(
            bild_werkzeug.WERKZEUG_NAME, {"prompt": "a dog"}, chat_id="c1", antwort_id="answer-1"
        )
    )
    in_job = asyncio.run(
        bild_werkzeug.ausfuehren(
            {"prompt": "a dog"}, "http://x", tmp_path, "testschluessel", job_id="a-job"
        )
    )
    sentence = "write no link and no image markdown for it"
    assert sentence in in_chat
    assert "attached to this response, and saved as " in in_chat
    assert ".png" in in_chat.split("saved as ", 1)[1]
    # Silence probe: the job's result is as it was.
    assert sentence not in in_job
