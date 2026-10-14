"""Tor 3 — is THIS call allowed to run, with these arguments?

Tor 1 (``mcp_servers.json``) and Tor 2 (the ``tools:`` list offered to the
model) only know names. This gate also sees the arguments — which file,
which command — and answers one of three ways:

* ``ja``     — runs right away, no confirmation
* ``fragen`` — the confirmation prompt above the input field (chat only)
* ``nein``   — refused; the reason goes back to the model as text

Two holes this module closes:

* **Hole A** — an agent used to reach any file at all: outside the shared
  folders there was only the confirmation prompt, and a job run never has
  one.
* **Hole B** — an agent's ``tools:`` list only mattered when tools were
  offered to the model, not anymore once one was actually called.

Both holes trace back to the same rule: for an agent, "asks" becomes "no",
because an unattended run has nobody there to answer.

One place is shut whatever the mode says: the program's own private places —
the database with the chats, the notes, the folders of other chats, the files
with keys and rules (``grenzen.private_check``). A call of the shell or a file
tool that names one is refused before any rule is read.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from app.berechtigungsregeln import Antwort, GUELTIGE_ANTWORTEN, Regeldatei, laden
from app.tools import dateiwerkzeuge, grenzen, shell, uhr

if TYPE_CHECKING:
    from app.agenten import Agent

Herkunft = Literal["chat", "agent"]


@dataclass
class Urteil:
    antwort: Antwort
    # Set only for "nein" — goes back to the model as text: what, why, and
    # what to do instead. English, like every tool-facing text.
    grund: str | None = None
    # Set only for a "nein" about the call's PATH — outside the shared
    # folders — rather than about the tool (app/tools/registry.py,
    # ``WerkzeugVerboten.about_path``).
    about_path: bool = False


# The only names a path can actually be computed for. A name reaching this
# module only because an operator listed it under `dateien.werkzeuge` in
# berechtigungen.json does NOT belong here — see the `regeln.dateiwerkzeuge`
# check in `urteil()`, which now requires both.
_BEKANNTE_DATEIWERKZEUGE = frozenset({shell.WERKZEUG_NAME, *dateiwerkzeuge.NAMEN})

# Tools that only READ something the program already holds and hand it back:
# no file, no folder, no row, no message, nothing of the user's. They answer
# "ja" whichever mode is set — Auto, Manuell, Restricted.
#
# The clock is the whole list, and it is not a convenience: it is the only
# place a run can learn what the time is (app/tools/uhr.py). A question
# would be a prompt with nothing behind it, and in an unattended run
# "fragen" becomes "nein" (``_abschliessen``) — so a scheduled run would be
# refused the one reading it cannot work "in ten minutes" without.
#
# Only the MODE is skipped here. An explicit per-tool rule above still
# wins, and so does an agent's own ``permissions: get_current_time: nein``
# after this — both are somebody's deliberate word, not a mode.
READS_ONLY: frozenset[str] = frozenset({uhr.WERKZEUG_NAME})


def _dateiwerkzeug_aussenpfad(name: str, argumente: dict, ordner: list[str]) -> str | None:
    if name == shell.WERKZEUG_NAME:
        return shell.aussenpfad(argumente, ordner)
    if name in dateiwerkzeuge.NAMEN:
        return dateiwerkzeuge.aussenpfad(name, argumente, ordner)
    return None


def _private_pfad(
    name: str, argumente: dict, ordner: list[str], private: Callable[[Path], bool]
) -> str | None:
    """The private place of the program this call names, for the shell and
    the file tools, or None."""
    if name == shell.WERKZEUG_NAME:
        return shell.private_target(argumente, ordner, private)
    if name in dateiwerkzeuge.NAMEN:
        return dateiwerkzeuge.private_target(name, argumente, ordner, private)
    return None


def _niemals_treffer(name: str, argumente: dict, regeln: Regeldatei) -> str | None:
    """The only rule type meant to work on the command TEXT, not a path.

    Deliberately a plain substring check: a command pattern is a tripwire
    against the obvious accident, never a security boundary — that density
    comes from the path rules above and later from a real OS sandbox.
    """
    if name != shell.WERKZEUG_NAME or not regeln.niemals:
        return None
    befehl = str(argumente.get("command") or "")
    if not befehl:
        return None
    for muster in regeln.niemals:
        if muster in befehl:
            return muster
    return None


def _ausserhalb_grund(pfad: str, ordner: list[str]) -> str:
    geteilt = ", ".join(ordner) if ordner else "(none)"
    return (
        f"'{pfad}' is outside the shared folders.\n"
        f"Shared with this run: {geteilt}\n"
        "Work inside those, or ask the user to share another folder."
    )


# Strictness order for the per-agent tightening below: an agent's own
# `permissions:` may only move a call rightward on this line, never left.
_STRENGE = {"ja": 0, "fragen": 1, "nein": 2}
assert set(_STRENGE) == GUELTIGE_ANTWORTEN, "an Antwort value is missing its strictness order"


def urteil(
    name: str,
    argumente: dict,
    ordner: list[str],
    herkunft: Herkunft,
    agent: "Agent | None" = None,
    regeln: Regeldatei | None = None,
    statisch_bestaetigen: bool = False,
    rules_of: Herkunft | None = None,
    private: Callable[[Path], bool] | None = None,
) -> Urteil:
    """The judgment for one call: ``ja`` / ``fragen`` / ``nein`` (+ reason).

    ``rules_of`` is whose mode and rules judge the call, where that is not
    ``herkunft`` itself: an agent the chat model sent off works under the
    chat's (``"chat"``), and its calls that would be asked about in the chat
    are asked about there. Its own tools list still binds it — that is the
    agent's, not the mode's.

    ``statisch_bestaetigen`` is the static ``needs_confirmation`` flag from
    ``mcp_servers.json`` — the registry knows it, this function does not need
    to know about MCP entries to fold it into the same three-way decision.

    ``private`` says whether a path is a private place of the program
    (``grenzen.private_check``): a call of the shell or a file tool that
    names one is refused in every mode.
    """
    ergebnis = _kern_urteil(
        name, argumente, ordner, herkunft, agent, regeln, statisch_bestaetigen,
        rules_of or herkunft, private,
    )
    return _agentregel_verschaerft(ergebnis, name, rules_of or herkunft, agent)


def _agentregel_verschaerft(
    ergebnis: Urteil, name: str, herkunft: Herkunft, agent: "Agent | None",
) -> Urteil:
    """An agent's own ``permissions:`` can tighten this call, never loosen it.

    Checked last, against whatever the rule file already decided — an agent
    that can write files must never be able to grant itself a permission the
    file withheld, simply by naming that permission in its own front matter.
    """
    if agent is None or name not in agent.berechtigungen:
        return ergebnis
    gewuenscht = agent.berechtigungen[name]
    if _STRENGE[gewuenscht] <= _STRENGE[ergebnis.antwort]:
        return ergebnis
    if gewuenscht == "nein":
        return Urteil("nein", (
            f"'{name}' is restricted by this agent's permissions. Use a different tool, or ask "
            "the user to adjust the permissions in the agent file."
        ))
    # gewuenscht == "fragen": an agent cannot be asked either, same as
    # everywhere else "fragen" meets an unattended run.
    return _abschliessen("fragen", herkunft, name)


def _kern_urteil(
    name: str,
    argumente: dict,
    ordner: list[str],
    herkunft: Herkunft,
    agent: "Agent | None",
    regeln: Regeldatei | None,
    statisch_bestaetigen: bool,
    rules_of: Herkunft,
    private: Callable[[Path], bool] | None = None,
) -> Urteil:
    regeln = regeln or laden()

    if (muster := _niemals_treffer(name, argumente, regeln)) is not None:
        return Urteil("nein", (
            f"This command matches a rule that prohibits execution ('{muster}'). Choose a "
            "different, more narrowly scoped command, or ask the user to run it themselves."
        ))

    # The program's private places — its chats, settings, keys and notes —
    # are shut to every tool call in every mode: before any per-tool rule,
    # because no mode and no rule is meant to open them.
    if private is not None and name in _BEKANNTE_DATEIWERKZEUGE:
        privat = _private_pfad(name, argumente, ordner, private)
        if privat is not None:
            return Urteil("nein", grenzen.PRIVATE_PLACE.format(path=privat))

    # Hole B: what the agent did not name in tools: must not run at
    # execution time either — not only when it was offered to the model.
    # `agent.werkzeuge is None` means the field was left out of the front
    # matter entirely (every approved tool runs then) — an empty list
    # is a deliberate "none of them" and still gets refused here.
    if (
        herkunft == "agent"
        and regeln.nur_was_der_agent_nennt
        and agent is not None
        and agent.werkzeuge is not None
        and name not in agent.werkzeuge
    ):
        genannt = ", ".join(agent.werkzeuge) or "(none)"
        return Urteil("nein", (
            f"'{name}' is not in this agent's tool list. Listed tools: {genannt}. Use those "
            "tools, or ask the user to add this one to the agent."
        ))

    # An explicit per-tool rule is the strongest signal an operator can give,
    # and always wins — including over the path rule below. Without this, a
    # "nein" (or "ja") aimed at one of the five file/shell tools by name has
    # no effect: the path branch used to return before this dict was ever
    # consulted for them.
    if name in regeln.regeln:
        return _abschliessen(regeln.regeln[name], rules_of, name)

    # Hole A: the load-bearing layer — path rules for the five tools that
    # touch the disk, and only those. A name that reached `dateien.werkzeuge`
    # without being one of the five has no path to check and falls through
    # to `standard` below instead of being waved through unconditionally.
    if name in regeln.dateiwerkzeuge and name in _BEKANNTE_DATEIWERKZEUGE:
        aussen = _dateiwerkzeug_aussenpfad(name, argumente, ordner)
        if aussen is None:
            # Restricted is the one mode that asks even inside a shared
            # folder — everywhere else, sharing it already was the answer.
            return _abschliessen(regeln.innerhalb_der_ordner.get(rules_of, "ja"), rules_of, name)
        antwort = regeln.ausserhalb_der_ordner.get(rules_of, "fragen")
        if antwort == "nein" or (antwort == "fragen" and rules_of == "agent"):
            return Urteil("nein", _ausserhalb_grund(aussen, ordner), about_path=True)
        return Urteil(antwort)

    # A server's own needs_confirmation flag is unconditional — the mode
    # governs the tools it has an opinion about, not a flag an MCP server
    # set on itself for reasons this file cannot see. Checked before the
    # read-only exemption below, so that exemption can only ever mean what
    # its comment says: the MODE is skipped, nothing else.
    if statisch_bestaetigen:
        return _abschliessen("fragen", rules_of, name)

    # Read-only tools never reach the mode at all (``READS_ONLY`` above).
    # They come after the per-tool rules and after the path branch, because
    # both of those are stronger statements than a mode and neither can have
    # anything to say about a tool with no path and no effect.
    if name in READS_ONLY:
        return Urteil("ja")

    return _abschliessen(regeln.standard.get(rules_of, "ja"), rules_of, name)


def zugriffslage(herkunft: Herkunft, regeln: Regeldatei | None = None) -> tuple[Antwort, Antwort]:
    """What the path rules answer for this origin — inside the shared
    folders and outside them.

    The two words the shipped prompt tells the model (app/grundprompt.py,
    ORDNER), read from the very path rules the gate applies, so the
    sentence and that rule cannot disagree. For an agent, "fragen" outside
    is "nein": an unattended run has nobody there to answer — the reading
    `_kern_urteil` gives, said here once more so the prompt says the same.

    The PATH rules only. A per-tool rule ("always allow" on `run_command`,
    a name in `regeln`) wins over them at the gate and is not read here:
    one sentence cannot say five tools' exceptions, and the prompt already
    tells the model that a question or a refusal at a call is a setting at
    work, not an error — so a call waved through where the sentence said
    "asks" costs nothing.
    """
    regeln = regeln or laden()
    innen = regeln.innerhalb_der_ordner.get(herkunft, "ja")
    aussen = regeln.ausserhalb_der_ordner.get(herkunft, "fragen")
    if herkunft == "agent" and aussen == "fragen":
        aussen = "nein"
    return innen, aussen


def _abschliessen(antwort: Antwort, herkunft: Herkunft, name: str) -> Urteil:
    """Turns a raw answer into the final Urteil for the two generic sources
    (a per-tool rule, or the standard/static-confirm fallback).

    An agent cannot be asked — an unattended run has nobody to answer — so
    "fragen" becomes "nein" here. The path branch above applies the same
    downgrade itself instead of calling this: it already has a better,
    path-specific reason to give than the generic one below.
    """
    if herkunft == "agent" and antwort == "fragen":
        return Urteil("nein", (
            f"'{name}' requires confirmation, which is unavailable during an unattended run. "
            "Ask the user to run this in a chat or allow it in berechtigungen.json."
        ))
    return Urteil(antwort)
