"""Opening a chat that already exists: finding it by id or title, and
writing its messages into the history."""

from __future__ import annotations

import json
from typing import Any

from cli import chat
from cli.texts import Texts
from test_stream import ENTER, Calls, Service, context, recorded, run, where

MESSAGES: list[dict[str, Any]] = [
    {"id": "m1", "role": "user", "content": "List three folders.", "reasoning": None, "stats": {}},
    {
        "id": "m2",
        "role": "assistant",
        "content": "Here they are:\n\n- app\n- cli\n- tests\n",
        "reasoning": "The user wants folders.",
        "stats": {
            "werkzeuge": [
                {
                    "name": "list_files",
                    "server": "files",
                    "argumente": {"path": "."},
                    "fehlgeschlagen": False,
                    "ergebnis": "app\ncli\ntests",
                    "dauer_sekunden": 0.4,
                    "kennung": "a1",
                }
            ]
        },
    },
    {"id": "m3", "role": "user", "content": "Thanks.", "reasoning": None, "stats": {}},
]


def _service(**more: Any) -> Service:
    return Service(
        chats=[
            {"id": "c-folders", "title": "List three folders.", "endpoint_id": "other", "updated_at": "2026-01-01T10:00:00"},
            {"id": "c-twin-1", "title": "Twins", "endpoint_id": None, "updated_at": "2026-01-02T10:00:00"},
            {"id": "c-twin-2", "title": "twins", "endpoint_id": None, "updated_at": "2026-01-03T10:00:00"},
            {"id": "c-plain", "title": "Plain", "endpoint_id": None, "updated_at": "2026-01-04T10:00:00"},
        ],
        messages={"c-folders": MESSAGES},
        **more,
    )


def test_the_messages_of_an_opened_chat_reach_the_renderer_in_order_below_their_count():
    service = _service(totals={"c-folders": 7})
    calls = Calls()
    ctx = context(service, renderer=calls)

    chat.open_chat(ctx, service.chats["c-folders"])

    # Three of the chat's seven messages came; the line above them says so.
    assert calls.calls[0] == ("remark", f"3/7 {Texts('en').t('cli.messages')}")
    assert [name for name, _ in calls.calls[1:]] == ["stored_message"] * 3
    written = [message for _, message in calls.calls[1:]]
    assert [message["role"] for message in written] == ["user", "assistant", "user"]
    assert written == MESSAGES
    # The answer still carries its thinking and its tool call, for whoever
    # draws them.
    assert written[1]["reasoning"] == "The user wants folders."
    assert written[1]["stats"]["werkzeuge"][0]["name"] == "list_files"
    assert ctx.session.chat == service.chats["c-folders"]
    assert ctx.screen.status["chat_title"] == "List three folders."

    asked = next(request for request in service.seen if request.url.path.endswith("/messages"))
    assert asked.url.path == "/api/v1/chats/c-folders/messages"
    assert asked.url.query == b"neueste=true"


def test_an_opened_chat_stands_in_the_history_with_its_count_and_its_messages(tmp_path):
    service = _service(totals={"c-folders": 7})
    shown = recorded("/quit" + ENTER, "--chat", "c-folders", service=service, tmp_path=tmp_path)
    lines = shown.splitlines()

    count = where(lines, f"3/7 {Texts('en').t('cli.messages')}")
    first = where(lines, "List three folders.", after=count)
    tool = where(lines, "list_files", after=first)
    last = where(lines, "Thanks.", after=tool)
    answer = where(lines, "Here they are:", after=first)
    assert answer < last
    # No chat is created beside the opened one.
    assert "POST /api/v1/chats" not in service.paths()


def test_the_head_names_the_model_the_opened_chat_remembers_like_the_status_line(tmp_path):
    service = _service()
    shown = recorded("/quit" + ENTER, "--chat", "c-folders", service=service, tmp_path=tmp_path)
    lines = shown.splitlines()
    stand = next(line for line in lines if line.startswith("CLI 9.8.7"))
    status = next(line for line in lines if "List three folders." in line and "Other Model" in line)
    # The chat remembers a model the service lists: the head names that
    # one, as the status line does — not the first of the list.
    assert "Other Model" in stand and "Local Model" not in stand
    assert status


def test_a_chat_is_found_by_its_title_whatever_the_case(tmp_path):
    service = _service()
    shown = recorded("/quit" + ENTER, "--chat", "LIST THREE FOLDERS.", service=service, tmp_path=tmp_path)
    lines = shown.splitlines()
    assert where(lines, "Thanks.")
    # The chat remembers a model the service can reach, so that one is used:
    # the status line names it behind the chat's title.
    status = next(text for text in lines if "List three folders." in text and "Other Model" in text)
    assert status.index("List three folders.") < status.index("Other Model")
    assert not any(request.method == "PATCH" for request in service.seen)


def test_two_chats_of_the_same_title_end_the_client_with_the_list(capsys, tmp_path):
    service = _service()
    code = run("", "--chat", "Twins", service=service, tmp_path=tmp_path)
    assert code == 1
    listed = capsys.readouterr().out
    assert "c-twin-1" in listed and "c-twin-2" in listed
    assert "c-plain" not in listed
    # Neither of them was opened, and nothing was created in their place.
    assert not any(path.endswith("/messages") for path in service.paths())
    assert "POST /api/v1/chats" not in service.paths()


def test_a_title_no_chat_has_ends_the_client_with_the_sentence_for_it(capsys, tmp_path):
    service = _service()
    code = run("", "--chat", "Nothing like it", service=service, tmp_path=tmp_path)
    assert code == 1
    assert Texts("en").t("cli.chat_unbekannt", name="Nothing like it") in capsys.readouterr().out


def test_a_chat_without_a_model_is_given_the_one_in_use(tmp_path):
    service = _service()
    run("/quit" + ENTER, "--chat", "c-plain", service=service, tmp_path=tmp_path)
    written = [json.loads(request.content) for request in service.seen if request.method == "PATCH"]
    assert written == [{"endpoint_id": "local"}]
    assert service.chats["c-plain"]["endpoint_id"] == "local"


def test_a_chat_that_remembers_a_model_not_listed_right_now_is_left_as_it_is():
    service = _service()
    service.chats["c-plain"]["endpoint_id"] = "gone-for-now"
    ctx = context(service, renderer=Calls())
    chat.open_chat(ctx, service.chats["c-plain"])
    # Opening changes nothing about the chat; the next message goes to the
    # model in use.
    assert not any(request.method == "PATCH" for request in service.seen)
    assert service.chats["c-plain"]["endpoint_id"] == "gone-for-now"
    assert ctx.session.endpoint_id == "local"


def test_a_name_with_a_slash_in_it_is_looked_for_as_a_title_and_reaches_no_other_address(capsys, tmp_path):
    service = _service()
    code = run("", "--chat", "c-folders/messages", service=service, tmp_path=tmp_path)
    assert code == 1
    assert Texts("en").t("cli.chat_unbekannt", name="c-folders/messages") in capsys.readouterr().out
    asked = [request.url.raw_path for request in service.seen if request.method == "GET"]
    assert b"/api/v1/chats/c-folders%2Fmessages" in asked
    assert b"/api/v1/chats/c-folders/messages" not in asked


def test_without_a_chat_named_none_is_created_and_no_history_is_read(tmp_path):
    service = _service()
    run("/quit" + ENTER, service=service, tmp_path=tmp_path)
    # The new chat is the client's alone until something is written into it.
    assert "POST /api/v1/chats" not in service.paths()
    assert not any(path.endswith("/messages") for path in service.paths())
    assert not any(request.method == "PATCH" for request in service.seen)
