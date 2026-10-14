"""The asking tool — `ask_user`.

Every other tool answers a question the model had. This one turns the
direction around: the model asks, and the run stops until somebody answers.

It is built in, and it is the one tool the registry never executes. There is
nothing to execute — the answer comes from a person, so the chat run holds
the call open the same way it holds a confirmation open, and hands the
answer back as the tool's result.

Two decisions are worth naming, because both were made against something:

* **The buttons stand above the input field**, in the same place the
  confirmation appears — not inside the message. Buttons in an old message
  are dead buttons, and a second mechanism for the same gesture is a second
  thing to keep working.
* **Free text always counts.** Whoever types instead of clicking has
  answered; the typed text becomes the tool's result. A question that can
  only be answered with one of four buttons is a cage, and people write
  their way out of cages.
"""

from __future__ import annotations

from typing import Any

from app.tools.mcp_client import MCPWerkzeug

SERVER_NAME = "shell"
WERKZEUG_NAME = "ask_user"

# Four is what fits above the input field without the row wrapping, and it
# is also about as many choices as a question can carry before it stops
# being a question.
MAX_OPTIONEN = 4


class FrageUngueltig(Exception):
    """The call cannot be shown to anybody in this shape."""


def werkzeug_beschreibung() -> MCPWerkzeug:
    return MCPWerkzeug(
        name=WERKZEUG_NAME,
        beschreibung=(
            "Asks the user a question and waits for their answer. Use it "
            "sparingly and only for decisions that are genuinely theirs — "
            "taste, priorities, which of two paths to take, anything you "
            "cannot look up and should not guess.\n"
            "Do not use it for what you can find out yourself, and never to "
            "confirm work you were already asked to do.\n"
            f"One question per call, at most {MAX_OPTIONEN} options, the one "
            "you would recommend first. The user may also answer in their own "
            "words instead of choosing — treat that as the answer."
        ),
        schema={
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "A brief, answerable question in the user's language.",
                },
                "options": {
                    "type": "array",
                    "description": f"Up to {MAX_OPTIONEN} choices, with the recommended option "
                                   "first.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {
                                "type": "string",
                                "description": "A brief button label, not a full sentence.",
                            },
                            "description": {
                                "type": "string",
                                "description": "One line explaining the implications of this "
                                               "choice.",
                            },
                        },
                        "required": ["label"],
                    },
                },
            },
            "required": ["question"],
        },
        server=SERVER_NAME,
    )


def gepruefte_frage(argumente: dict[str, Any]) -> tuple[str, list[dict[str, str]]]:
    """The question and its options, as the window may show them.

    Refuses rather than trims: a model that gets six options past this would
    learn that six is fine, and the user would see four of them.
    """
    frage = str(argumente.get("question") or "").strip()
    if not frage:
        raise FrageUngueltig("No question provided.")

    roh = argumente.get("options") or []
    if not isinstance(roh, list):
        raise FrageUngueltig("options must be a list.")
    if len(roh) > MAX_OPTIONEN:
        raise FrageUngueltig(
            f"{len(roh)} options exceed the limit of {MAX_OPTIONEN}. Narrow the question or "
            "allow a free-text answer."
        )

    optionen: list[dict[str, str]] = []
    for eintrag in roh:
        if not isinstance(eintrag, dict):
            raise FrageUngueltig("Every option must be an object with a label.")
        beschriftung = str(eintrag.get("label") or "").strip()
        if not beschriftung:
            raise FrageUngueltig("An option without a label cannot be displayed.")
        optionen.append(
            {
                "label": beschriftung,
                "description": str(eintrag.get("description") or "").strip(),
            }
        )
    return frage, optionen


# What the model is told when nobody answered — the run went on without the
# decision, and it has to know that it is still missing.
OHNE_ANTWORT = (
    "The user did not answer. Do not repeat the question. Continue with the most reasonable "
    "assumption and state it explicitly."
)

# What the model reads when the user stopped the run while the question was
# open. The window shows its own short word; the model needs to know the call
# did not run to an answer — the plain wording for a call a user interrupt
# skipped.
CANCELLED = "Tool execution cancelled"
