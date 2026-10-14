"""Where the rounds of a failed answer go when a request must not end on a
turn of the model's own.

A request that ends on a turn of the model is not answered by most servers:
llama.cpp reads it as a prefix and writes that text further, others refuse
it. The repeated call of a failed answer closes on the model's finished tool
rounds. With tools on, those go back as calls and results, and the request
ends on a result, which the model answers. With no tool offered they go as
one block of text, and that block was a turn of the model.

Here the block is hung on the question it belongs to instead — the user's
last turn, in the same message — so the request ends on the user, with the
same words in it and no sentence of our own added.
"""

from __future__ import annotations

import dataclasses

from app.providers import ChatNachricht


def fold_into_question(
    messages: list[ChatNachricht], turns: list[ChatNachricht]
) -> list[ChatNachricht]:
    """``messages`` with ``turns`` behind them, ending on a turn the model
    answers.

    Where ``turns`` already end on something the model answers (a tool
    result), they simply follow. Where they end on a turn of the model's
    own, their text goes at the end of the last user turn of ``messages``
    and no turn of the model is added; with no user turn to hang it on, they
    follow as they are.
    """
    if not turns:
        return list(messages)
    if turns[-1].role != "assistant":
        return [*messages, *turns]
    text = "\n\n".join(turn.content for turn in turns if turn.content)
    last = messages[-1] if messages else None
    if not text or last is None or last.role != "user":
        return [*messages, *turns]
    merged = f"{last.content}\n\n{text}" if last.content else text
    return [*messages[:-1], dataclasses.replace(last, content=merged)]
