"""Agents — one Markdown file is the whole agent.

A file ``prompts/agenten/<name>.md`` consists of a front matter section between
two ``---`` lines (YAML) and the prompt after it. The file name without its
extension is the agent's name. The front matter holds its rules:

    ---
    description: Researches a topic on the web and writes a summary.
    tools:                 # allowlist — whatever is listed here runs without asking back.
      - mcp__websuche__web_search    # Left out entirely: every approved tool runs. Set to
      - mcp__websuche__read_webpage  # an empty list: none do — different on purpose.
    folders:               # complete paths the file tools may reach, like a chat's shares
      - /Users/you/code
    max_rounds: 30         # tool rounds before we stop
    max_minutes: 20        # minutes before we stop
    max_tokens: 16000      # answer budget; overrides the settings cascade (optional)
    reasoning_budget: 2048 # how long it may think first; same cascade (optional)
    reasoning_effort: high # the thinking stage a run asks for, as in a chat (optional)
    max_command_seconds: 600  # seconds one shell command may run (optional)
    color: "#2f8f84"       # the agent's own colour, wherever its name stands
    permissions:            # per-tool overrides for Tor 3 (app/berechtigungen.py)
      run_command: nein    # only ja/fragen/nein, and only stricter than the
    ---                     # rule file already says for this agent

    You are a research agent. ...

``schedule:`` and ``schedule_task:`` used to stand here too — a second way
to say when something runs, beside the cron table. Two ways to say one thing
is one too many: every later change would have to be made in both places, and
whoever knew only one of them would build a bug. The cron table is the one
way now. An existing file may keep both keys — they are read
without complaint and then ignored, with a line in the log saying so. Nothing
is migrated on its own: a schedule that is wanted is stated again through the
cron tool, by hand, where it can be seen.

``model:`` went the same way, and for the same reason plus one of its own.
Which model a run uses is said in two places now: the one field
(app/agentenmodellwahl.py) for everything that runs unattended, and the hand
pick in the start window for a single run. A model stored per agent was a
third, and a stored one — so the question "and which of them counts now?"
came back on every start. Its own reason on top: an agent file travels, and
what one machine can hold in memory the next one cannot. A key still in a
file is read, logged about, and does nothing.

The keys are English, just like in ``config.yaml`` — the front matter is user
surface. The approval lives in the agent itself: whatever is listed under
``tools`` runs without asking back, and whatever is not listed is never even
offered to the model. Leaving ``tools`` out entirely is different from
setting it to an empty list — the field missing means every tool the server
approves runs, the field present-but-empty means none do. This only became
safe to allow once every call was also checked against the rule file (Tor 3,
``app/berechtigungen.py``) — before that, an empty allowlist was the only
thing standing between an agent and the whole tool catalogue. The server's
allowlist (``mcp_servers.json``) remains the outer boundary regardless — a
tool that only the agent knows about does not exist.

``folders`` works the same way for the file tools: the paths listed there are
the agent's shared working folders, the same permission a chat gets from the
plus menu. Without the field the agent shares nothing and the file tools stay
shut — the permission is a deliberate act, exactly like ``tools``. When a job
is started with folders picked in the start window, those win over the file's,
the same way the window's model wins over the one in the front matter. Paths
must be complete: ``~/code`` is refused, because there is nothing here to
expand the ``~`` and it would silently match nothing.

``permissions`` reaches into Tor 3 for this agent alone, and only in one
direction: it can turn a ``ja``/``fragen`` the rule file would otherwise give
a tool into something stricter, never the other way. A looser value here is
simply ignored — an agent that can edit files must never be able to grant
itself a permission the rule file withheld, by writing a file that says so.

Two places hold agents, and the user's wins — the same layering the skills
already use (``app/skills.py``): the shipped folder ``agenten/`` sits next to
the program and is replaced by every update, the user's folder
``prompts/agenten/`` is never touched, and on a name clash the user's file
overrides the shipped one.

A broken file takes exactly this one agent out of play, not the service —
deliberately a different design than ``config.yaml``, which halts everything
at startup: it is the foundation of the service, an agent is a guest.

Read fresh on every use, like the system prompt: file changed = takes effect
immediately, no restart.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from app import __version__, denkstufen, frontmatter, i18n
from app.auftragdenklaengewahl import AUTO as DENKLAENGE_AUTO
from app.auftragdenklaengewahl import OBERGRENZE as DENKLAENGE_OBERGRENZE
from app.auftragtokenwahl import OBERGRENZE as MAX_TOKENS_OBERGRENZE
from app.berechtigungsregeln import GUELTIGE_ANTWORTEN

log = logging.getLogger(__name__)

# Deleted shipped agents, remembered beside the user's own files. A user's
# agent is deleted by deleting its file; a shipped one comes back with every
# scan of the shipped folder, so its deletion is a note: "gone, as of this
# version". The note carries the version on purpose — an update replaces the
# shipped folder, and the house decision is that a deleted shipped agent
# returns with the next update, no special case, no question asked.
GELOESCHT_DATEI = "geloescht.json"

# Guide values: two restraints, rounds and time.
# They apply when the front matter is silent — turning a restraint off entirely
# is deliberately not possible.
STANDARD_RUNDEN = 30
STANDARD_MINUTEN = 20.0

# ``model``, ``schedule`` and ``schedule_task`` are still listed: they are
# retired, not forbidden. Listing them keeps an old file from being scolded
# for an "unknown field" on top of the one clear line the loader already logs.
BEKANNTE_FELDER = {
    "description", "model", "tools", "folders", "max_rounds", "max_minutes", "max_tokens",
    "reasoning_budget", "reasoning_effort", "max_command_seconds", "schedule", "schedule_task",
    "permissions", "color",
}

# The name helpers run under (app/helper.py) — kept here, where every agent
# file is read, so no file can take it.
HELPER_NAME = "helper"

# A colour is written as it is written everywhere else in this program: a
# six-digit hex value. Three-digit shorthand is refused rather than expanded
# — one spelling means the file and the picker always say the same thing.
FARB_MUSTER = re.compile(r"^#[0-9A-Fa-f]{6}$")

# The retired schedule keys, named once so the check below and the log line
# stay in step.
STILLGELEGTE_ZEITFELDER = ("schedule", "schedule_task")

# The retired model key, named the same way and kept apart from the
# schedule ones: they are two different retirements with two different
# sentences, and one list would say the wrong one about either.
STILLGELEGTES_MODELLFELD = "model"


def kaputte_datei_satz(datei: str, satz: str) -> str:
    """One shape for every unusable agent file: the file's name, then the
    sentence of its reason.

    Read by the class below and by the routes that meet a file they cannot
    read at all. An unreadable file is one of this family, not a second kind
    of answer — its entry in the list has to look like the entries beside it.

    The finished sentence comes in rather than a catalogue key: the key is
    read where it stands (``agent_file.not_utf8`` and its siblings), so the
    catalogue guard keeps proving those keys, instead of seeing one template
    that could name anything."""
    return f"'{datei}': " + satz


class AgentDateiKaputt(ValueError):
    """This one agent file is unusable. The service keeps running.

    Carries the file, the catalogue key of the reason and its values rather
    than a finished sentence: the reason is shown to a person in the
    language of their page (``text``), while ``str()`` stays English for
    the log and every caller that reads it as before."""

    def __init__(self, file: str, key: str, **values: object) -> None:
        self.file = file
        self.key = key
        self.values = values
        super().__init__(self.text(i18n.STANDARDSPRACHE))

    def text(self, language: str) -> str:
        return kaputte_datei_satz(
            self.file, i18n.t(f"agent_file.{self.key}", language, **self.values)
        )

    @property
    def line(self) -> int | None:
        """The line of the file the reader names, where it names one — a
        broken header says where, a missing field does not."""
        zeile = self.values.get("line")
        return zeile if isinstance(zeile, int) else None

    def __reduce__(self):
        # Copied or pickled, it is rebuilt from what it carries, not from
        # the finished sentence ValueError keeps as its argument.
        return (_agent_file_broken, (self.file, self.key, self.values))


def _agent_file_broken(file: str, key: str, values: dict) -> "AgentDateiKaputt":
    return AgentDateiKaputt(file, key, **values)


@dataclass
class Agent:
    name: str
    prompt: str
    # No ``modell`` here any more: which model a run uses is the one
    # field's word, or the start window's for a single run. A field kept here
    # would be a third answer, and every caller would have to decide again
    # which one wins.
    # None means the field was left out of the front matter entirely — every
    # approved tool runs. An explicit empty list is a deliberate "none of
    # them", and stays exactly that. See agent_aus_text() for the parsing.
    werkzeuge: list[str] | None = None
    ordner: list[str] = field(default_factory=list)
    runden: int = STANDARD_RUNDEN
    minuten: float = STANDARD_MINUTEN
    # Overrides the settings cascade (app/auftragtokenwahl.py) outright when
    # set. None means the agent has no opinion and the cascade decides.
    max_tokens: int | None = None
    # How long the model may think before answering — overrides the settings
    # cascade (app/auftragdenklaengewahl.py) outright when set. None means the
    # agent has no opinion and nothing is sent. Zero is a real answer here and
    # means no thinking at all, which is why it may not be mistaken for unset.
    # Minus one is Auto, as in a chat: no cap at all.
    denklaenge: int | None = None
    # The thinking stage a run of this agent asks for, one of the words a chat
    # offers (app/denkstufen.py). It goes out through the same switch as the
    # chat's (app/denkschalter.py); a stage this model does not have is dropped
    # there, not here. None means the agent has no opinion and no thinking field
    # goes out, as before.
    thinking_stage: str | None = None
    # Seconds one shell command may run — overrides the settings cascade
    # (app/befehlszeitwahl.py) the same way. None: the cascade decides. A
    # research agent and a build agent genuinely need different values here.
    befehlssekunden: int | None = None
    # Per-tool overrides for Tor 3 — narrowing only, see agent_aus_text().
    berechtigungen: dict[str, str] = field(default_factory=dict)
    # What colour this agent's NAME is written in, wherever it stands — the
    # report row, the agent list, a scheduled run, a notice. None means the
    # agent never picked one and keeps the shared default, which is what
    # every agent looked like before this field existed.
    #
    # Not validated against the four state colours here. Which colours may
    # be OFFERED is a question about a picker, and the picker is the one
    # place that can answer it; a file written by hand is the user's file,
    # and a refusal at load time would take the whole agent out of play over
    # a shade.
    farbe: str | None = None
    # What the agent is for, in a sentence — the chat's model reads it beside
    # the name when it picks whom to hand work to. Without it the model had
    # nothing but the name to guess from. None: the file says nothing.
    description: str | None = None


def agent_aus_text(name: str, text: str) -> Agent:
    """Reads an agent from raw text. Raises ``AgentDateiKaputt`` with a reason.

    Separate from file access because the edit window (6.6) needs the same
    validator before a file even hits the disk.
    """
    anzeige = f"{name}.md"

    # The helpers run under this name (app/helper.py). A file under it could
    # never run as itself: a call naming it starts a helper. So it reads as
    # broken — out of play, and the editor says why — wherever it is read.
    if name.strip().casefold() == HELPER_NAME:
        raise AgentDateiKaputt(anzeige, "helper_name")

    try:
        kopf_roh, prompt = frontmatter.split(text)
    except frontmatter.NoFrontMatter as error:
        raise AgentDateiKaputt(anzeige, "front_missing") from error
    except frontmatter.NoClosingLine as error:
        raise AgentDateiKaputt(anzeige, "closing_missing") from error

    try:
        kopf = yaml.safe_load(kopf_roh) or {}
    except yaml.YAMLError as fehler:
        # The first place the reader's own message names: where the thing
        # that was left open began, or where it tripped when nothing was
        # open — an unclosed bracket trips only at the end of the header,
        # which is the wrong place to send somebody. The reader counts lines
        # from zero inside the header, whose first line is the opening
        # marker's own, so its count plus one is the line of the file.
        marke = getattr(fehler, "context_mark", None) or getattr(fehler, "problem_mark", None)
        zeile = marke.line + 1 if marke is not None else None
        raise AgentDateiKaputt(
            anzeige, "not_yaml", error=str(fehler), line=zeile
        ) from fehler
    if not isinstance(kopf, dict):
        raise AgentDateiKaputt(anzeige, "not_fields")

    unbekannt = set(kopf) - BEKANNTE_FELDER
    if unbekannt:
        # No reason to fail: a typo should stand out, but a file from a newer
        # program version should still be readable here.
        log.warning(
            "Agent '%s': unknown header fields are ignored: %s",
            name,
            ", ".join(sorted(unbekannt)),
        )

    # The retired model field: read, said out loud, and dropped —
    # the same treatment the schedule keys get below, and for the same
    # reason. Not validated either: there is nothing left to validate it FOR.
    # The value never reaches an Agent, so nothing downstream can run on it.
    if STILLGELEGTES_MODELLFELD in kopf:
        log.info(
            "Agent '%s': 'model' is no longer used — the model is set in the "
            "field 'Model for agents & cronjobs' or is chosen by hand "
            "at the start",
            name,
            extra={"ereignis": "agent_modell_stillgelegt", "agent": name},
        )

    # The key's absence and an empty list mean different things: missing
    # entirely says "every tool", written but empty says "none of them" — so
    # this has to ask whether the key is there at all, not just look at its
    # value the way every other field here does.
    if "tools" not in kopf:
        werkzeuge: list[str] | None = None
    else:
        werkzeuge_roh = kopf.get("tools")
        if werkzeuge_roh is None:
            werkzeuge_roh = []  # `tools:` written with no items under it
        if not isinstance(werkzeuge_roh, list) or not all(
            isinstance(eintrag, str) for eintrag in werkzeuge_roh
        ):
            raise AgentDateiKaputt(anzeige, "tools_list")
        werkzeuge = list(werkzeuge_roh)

    ordner_roh = kopf.get("folders")
    if ordner_roh is None:
        ordner_roh = []  # `folders:` written with no items under it
    if not isinstance(ordner_roh, list) or not all(
        isinstance(eintrag, str) for eintrag in ordner_roh
    ):
        raise AgentDateiKaputt(anzeige, "folders_list")
    ordner: list[str] = []
    for eintrag in ordner_roh:
        pfad = eintrag.strip()
        if not pfad:
            continue
        if not Path(pfad).is_absolute():
            # A path like ~/code is not complete: nothing here expands the ~,
            # so downstream it resolves to a folder literally named '~' and
            # matches nothing. Refuse it loudly instead of handing the agent a
            # share it can never reach — the field exists so the agent CAN read.
            raise AgentDateiKaputt(anzeige, "folders_full", path=pfad)
        if pfad not in ordner:
            ordner.append(pfad)

    runden = kopf.get("max_rounds", STANDARD_RUNDEN)
    if not isinstance(runden, int) or isinstance(runden, bool) or runden < 1:
        raise AgentDateiKaputt(anzeige, "max_rounds")

    minuten = kopf.get("max_minutes", STANDARD_MINUTEN)
    if isinstance(minuten, bool) or not isinstance(minuten, (int, float)) or minuten <= 0:
        raise AgentDateiKaputt(anzeige, "max_minutes")

    max_tokens = kopf.get("max_tokens")
    if max_tokens is not None and (
        isinstance(max_tokens, bool)
        or not isinstance(max_tokens, int)
        # Same ceiling app/auftragtokenwahl.py enforces when this value is
        # resolved for a run — checked again here so a typo with an extra
        # digit fails loudly while editing the file, not silently later.
        or not (1 <= max_tokens <= MAX_TOKENS_OBERGRENZE)
    ):
        raise AgentDateiKaputt(anzeige, "max_tokens", max=MAX_TOKENS_OBERGRENZE)

    denklaenge = kopf.get("reasoning_budget")
    if denklaenge is not None and (
        isinstance(denklaenge, bool)
        or not isinstance(denklaenge, int)
        # Zero is allowed, unlike the answer budget above: a thinking budget
        # of zero is llama.cpp's own way of saying "do not think". Minus one
        # is Auto, no cap at all, as in a chat.
        or not (DENKLAENGE_AUTO <= denklaenge <= DENKLAENGE_OBERGRENZE)
    ):
        raise AgentDateiKaputt(
            anzeige, "reasoning_budget", min=DENKLAENGE_AUTO, max=DENKLAENGE_OBERGRENZE
        )

    thinking_stage = kopf.get("reasoning_effort")
    # A bare ``off`` or ``on`` is a truth value to YAML; it means the word.
    if isinstance(thinking_stage, bool):
        thinking_stage = "on" if thinking_stage else "off"
    # A field left empty says nothing, like one left out.
    if isinstance(thinking_stage, str) and not thinking_stage.strip():
        thinking_stage = None
    if thinking_stage is not None:
        thinking_stage = thinking_stage.strip().lower() if isinstance(thinking_stage, str) else None
        if thinking_stage not in denkstufen.STUFEN:
            raise AgentDateiKaputt(
                anzeige, "reasoning_effort", words=", ".join(denkstufen.STUFEN)
            )

    befehlssekunden = kopf.get("max_command_seconds")
    if befehlssekunden is not None and (
        isinstance(befehlssekunden, bool)
        or not isinstance(befehlssekunden, int)
        # No ceiling on purpose, same reasoning as the settings cascade
        # (app/befehlszeitwahl.py): whoever writes an hour means an hour.
        or befehlssekunden < 1
    ):
        raise AgentDateiKaputt(anzeige, "max_command_seconds")

    # The retired schedule: read, said out loud, and dropped. No
    # refusal — an existing file is the user's, and taking their agent out of
    # play over a field that merely no longer does anything would punish them
    # for an upgrade. Not validated either, for the same reason: there is
    # nothing left to validate it FOR. The value never reaches an Agent, so
    # nothing downstream can fire on it.
    if any(feld in kopf for feld in STILLGELEGTE_ZEITFELDER):
        log.info(
            "Agent '%s': 'schedule' is no longer carried out — "
            "schedules live in the cron table (tool 'cronjob')",
            name,
            extra={"ereignis": "agent_zeitplan_stillgelegt", "agent": name},
        )

    berechtigungen_roh = kopf.get("permissions")
    if berechtigungen_roh is None:
        berechtigungen_roh = {}  # `permissions:` written with nothing under it
    if not isinstance(berechtigungen_roh, dict):
        raise AgentDateiKaputt(anzeige, "permissions_list")
    farbe = kopf.get("color")
    if farbe is not None and (
        not isinstance(farbe, str) or not FARB_MUSTER.match(farbe.strip())
    ):
        raise AgentDateiKaputt(anzeige, "color")
    if isinstance(farbe, str):
        farbe = farbe.strip()

    # Prose, so read leniently: a hand-written `description: 42` comes back
    # from YAML as a number, and taking the agent out of play over what it
    # is for would punish a sentence. A list or a mapping says nothing.
    description = kopf.get("description")
    if isinstance(description, (list, dict)):
        log.warning("Agent '%s': 'description' is not a text and is ignored", name)
        description = None
    description = str(description).strip() if description is not None else ""
    description = description or None

    berechtigungen: dict[str, str] = {}
    for werkzeugname, antwort in berechtigungen_roh.items():
        if (
            not isinstance(werkzeugname, str)
            or not isinstance(antwort, str)
            or antwort not in GUELTIGE_ANTWORTEN
        ):
            raise AgentDateiKaputt(anzeige, "permission_value", tool=werkzeugname)
        berechtigungen[werkzeugname] = antwort

    prompt = prompt.strip()
    if not prompt:
        raise AgentDateiKaputt(anzeige, "no_prompt")

    return Agent(
        name=name,
        prompt=prompt,
        werkzeuge=werkzeuge,
        ordner=ordner,
        runden=runden,
        minuten=float(minuten),
        max_tokens=max_tokens,
        denklaenge=denklaenge,
        thinking_stage=thinking_stage,
        befehlssekunden=befehlssekunden,
        berechtigungen=berechtigungen,
        farbe=farbe,
        description=description,
    )


def agent_text_lesen(datei: Path) -> str:
    """The raw text of one agent file — the ONE place that reads it.

    Read as ``utf-8-sig``: a byte order mark at the front is what a Windows
    editor leaves behind when it saves "UTF-8 with BOM", and the file is a
    healthy one (the routes read the same way; ``encodings.utf_8_sig`` drops
    the mark while decoding). Bytes that are no UTF-8 at all are this one
    file's own breakage: they are reported like every other broken agent file
    — carrying the file's name — instead of escaping as a decoder error that
    the caller has to know about."""
    try:
        return datei.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as fehler:
        # ``datei.name``, not stem plus ".md": a file really called ".md" has
        # no stem to grow, and the sentence would name a file that is not
        # there — one the editor could not even open.
        raise AgentDateiKaputt(datei.name, "not_utf8") from fehler


def agent_lesen(datei: Path) -> Agent:
    """Reads exactly one agent file. Raises ``AgentDateiKaputt`` with a reason."""
    return agent_aus_text(datei.stem, agent_text_lesen(datei))


def geloeschte_agenten(benutzerordner: Path) -> set[str]:
    """The shipped agents deleted under THIS version.

    Notes from an older version are stale — the update that changed the
    version also replaced the shipped folder, and with it the agent returns.
    Stale entries are simply ignored here; the next deletion rewrites the
    file without them.
    """
    pfad = Path(benutzerordner) / GELOESCHT_DATEI
    try:
        # The look before the read stands INSIDE this block: a folder nobody
        # may walk into makes the look itself an error, and that is the same
        # kind of unusable note as a broken one.
        if not pfad.is_file():
            return set()
        daten = json.loads(pfad.read_text(encoding="utf-8-sig"))
    except (ValueError, OSError) as fehler:
        # ValueError covers the JSON error AND a file whose bytes are no
        # UTF-8: either way this note is unusable, and that must cost the
        # note, never the whole list of agents. Worth a line in the log all
        # the same: the note's own loss — which agents a user deleted — is
        # invisible everywhere else.
        log.warning("Note file of the deleted agents is unusable: %s", fehler)
        return set()
    if not isinstance(daten, dict):
        return set()
    return {name for name, version in daten.items() if version == __version__}


def _geloeschte_schreiben(benutzerordner: Path, namen: set[str]) -> None:
    pfad = Path(benutzerordner) / GELOESCHT_DATEI
    if not namen:
        pfad.unlink(missing_ok=True)
        return
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_text(
        json.dumps({name: __version__ for name in sorted(namen)},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def loeschung_merken(benutzerordner: Path, name: str) -> None:
    """Notes a shipped agent as deleted. Stale notes fall away in passing."""
    _geloeschte_schreiben(benutzerordner, geloeschte_agenten(benutzerordner) | {name})


def loeschung_vergessen(benutzerordner: Path, name: str) -> None:
    """A saved file beats an old deletion — the note goes, the agent stands."""
    namen = geloeschte_agenten(benutzerordner)
    if name in namen:
        _geloeschte_schreiben(benutzerordner, namen - {name})


class Agentenverzeichnis(dict):
    """The agents by name, where the capitals are not part of the name.

    An agent name comes from a file name and is therefore lower case, while
    the word for it may not be: ``Recherche`` is how German spells it, and a
    model asked to name an agent writes it that way. The comparison used to
    be exact, and it is made in FIVE places — the cronjob tool on create and
    on update, the job route, the job tool inside a chat, and the firing loop
    itself.

    That is why this lives here rather than at any of them. Fixing two of
    five would be worse than fixing none: the same word would create a
    schedule and then fail to start the job it fires, and nothing on the way
    would say which of the two spellings the program wanted.

    So the folding happens once, where every one of the five already comes
    through. Keys, iteration and ``items()`` keep the real spelling — that is
    what gets stored, never what was typed, or one agent would end up in the
    table under two names. Only looking one up forgives the case.

    Nothing else is forgiven. A name that differs by more than capitals is a
    different name, and running something nobody asked for is worse than
    refusing.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._klein = {name.casefold(): name for name in self}

    def __setitem__(self, name, wert) -> None:
        super().__setitem__(name, wert)
        self._klein[str(name).casefold()] = name

    def __delitem__(self, name) -> None:
        super().__delitem__(name)
        self._klein.pop(str(name).casefold(), None)

    def echter_name(self, name) -> str | None:
        """The spelling on disk for a name however it was written."""
        if not isinstance(name, str):
            return None
        return self._klein.get(name.strip().casefold())

    def __contains__(self, name) -> bool:
        return self.echter_name(name) is not None

    def __getitem__(self, name):
        echt = self.echter_name(name)
        if echt is None:
            raise KeyError(name)
        return super().__getitem__(echt)

    def get(self, name, vorgabe=None):
        echt = self.echter_name(name)
        return super().__getitem__(echt) if echt is not None else vorgabe


def agent_lookup(
    name: str, *folders: Path
) -> tuple[Agent | None, AgentDateiKaputt | None]:
    """What the folders hold under ONE name, read by the same rules as
    ``agenten_laden`` but touching only the files of that name: the agent,
    or — when no readable file stands under it — why the file that does is
    unusable. Both ``None``: nothing of that name is there at all.

    For the question "can this one entry start", asked on every change of an
    entry — reading every agent file for a yes or no is what this is for
    not doing. The name is folded like a lookup in the directory is."""
    wanted = str(name or "").strip().casefold()
    deleted = geloeschte_agenten(folders[-1]) if folders else set()
    found: Agent | None = None
    broken: AgentDateiKaputt | None = None
    for position, folder in enumerate(folders):
        is_last = position == len(folders) - 1
        if not folder.is_dir():
            continue
        for file in sorted(folder.glob("*.md")):
            if file.stem.casefold() != wanted:
                continue
            if not is_last and file.stem in deleted:
                continue
            try:
                found = agent_lesen(file)
            except AgentDateiKaputt as problem:
                broken = problem
            except OSError:
                continue
    return found, (broken if found is None else None)


def agenten_laden(*verzeichnisse: Path) -> "Agentenverzeichnis":
    """All agents from the folders, broken ones reported and skipped.

    A missing folder is not an error — it ships empty
    (guiding idea from 3.10: the place exists, the content belongs to the user).

    Several folders are layers, and a later one wins on a name clash — the
    same rule the skills follow (app/skills.py): the shipped folder comes
    first, the user's folder last, so the user's file always overrides a
    shipped agent of the same name.
    """
    # Deleted shipped agents stay deleted (until the next update): the notes
    # live in the LAST folder — the user's, the only one that is written to —
    # and silence names in every folder before it. The user's own folder is
    # never filtered: a file that lies there is the user's word, and it wins
    # over an old deletion the same way it wins over a shipped file.
    geloescht = geloeschte_agenten(verzeichnisse[-1]) if verzeichnisse else set()
    agenten: Agentenverzeichnis = Agentenverzeichnis()
    for stelle, verzeichnis in enumerate(verzeichnisse):
        letzte = stelle == len(verzeichnisse) - 1
        if not verzeichnis.is_dir():
            continue
        for datei in sorted(verzeichnis.glob("*.md")):
            if not letzte and datei.stem in geloescht:
                continue
            try:
                agenten[datei.stem] = agent_lesen(datei)
            except (AgentDateiKaputt, OSError) as fehler:
                log.error("Agent file skipped: %s", fehler)
    return Agentenverzeichnis(sorted(agenten.items()))
