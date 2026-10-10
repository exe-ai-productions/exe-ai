"""What happens between the microphone and the input field.

Twelve answers live here, and all twelve are the user's rather than the code's:

  * ``sprache``   which language is being spoken, or "automatic"
  * ``anweisung`` the instruction the speech model is given
  * ``bereinigung`` who tidies the dictation afterwards, if anybody
  * ``putzmodell`` which file the small tidy-up model runs from
  * ``bereinigung_anweisung`` the instruction that tidy-up is given
  * ``vorlesen`` whether a finished answer is read aloud in a conversation
  * ``stimme`` which file the voice speaks from
  * ``stimmprobe`` which file its voice sample is, if any
  * ``stimmsprache`` which language the voice speaks in, if chosen
  * ``stimmtemperatur`` how freely the voice samples its next sound — with
    ``stimmtop_k``, ``stimmtop_p``, ``stimmmin_p`` and ``stimmstrafe`` in
    the house's own ranges (app/parameter.py)
  * ``stimmschichten``/``stimmfaeden`` how much of the voice model runs on
    the card and on how many cores
  * ``putzkontext``/``putzschichten``/``putzfaeden`` the tidy-up server's
    memory, and ``putztemperatur``/``putztop_k``/``putztop_p``/
    ``putzmin_p``/``putzstrafe`` its generation values — empty means "not
    set", and then it starts exactly as it always has
  * ``gespraechsanweisung`` the instruction only a live conversation's
    message gets, in front of what was actually said
  * ``automatik`` whether a finished dictation is sent at once instead of
    waiting in the field for Enter

The three instructions are the reason this is a setting and not a constant.
Between sound and text sits a prompt, and it decides whether a model writes
down what it heard or "helps" — somebody who brings a model for another
language may have to say it differently. A prompt hidden in the source is a
prompt nobody can correct.

The language is here for a plainer reason: without it the model guesses from
the first seconds, and on a short sentence, a name or a technical term it
guesses wrong — a German sentence comes back as English nonsense.

Stored under its own key, not under the one the interface language uses:
that one (app/sprachwahl.py) answers which language the PROGRAM speaks,
which is a different question from which language is being spoken into the
microphone, and two answers in one row would be one answer too few.
"""

from __future__ import annotations

import re
from typing import Any

# Under its own name: ``stimme`` is also this module's function for the
# chosen voice file further down.
from app.feineinstellungen import MAX_FAEDEN
from app.parameter import pruefen as parameter_pruefen
from app.runnermodellwahl import KONTEXT_MAX, KONTEXT_MIN, SCHICHTEN_MAX, SCHICHTEN_MIN
from app.stimme import (
    MIN_P as STIMME_MIN_P,
    TEMPERATUR as STIMME_TEMPERATUR,
    TOP_K as STIMME_TOP_K,
    TOP_P as STIMME_TOP_P,
    WIEDERHOLUNGSSTRAFE as STIMME_WIEDERHOLUNGSSTRAFE,
)

SCHLUESSEL = "diktat"

# "Automatic" is a value, not the absence of one: it means "let the model
# decide", and somebody who goes back to it from a fixed language is making a
# choice that has to survive being stored.
AUTO = "auto"

# The languages offered, as the codes the engine's own field takes. A closed
# list rather than a free text field: the code travels into a request, and a
# typed-in word would come back as a transcription in a language nobody
# asked for. Adding one means adding its name to the catalogues as well.
SPRACHEN: tuple[str, ...] = (
    "de", "en", "fr", "es", "it", "pt", "nl", "pl", "sv", "tr",
    "ru", "uk", "ar", "he", "hi", "zh", "ja", "ko",
)

# The languages llama-tts documents for Qwen3-TTS — a smaller, closed list
# than the dictation one above, because the voice reads only what that one
# engine can be asked to speak. Empty is "none chosen", not "automatic": a
# voice does not guess its own language from the text the way a listening
# model guesses the speaker's.
STIMMSPRACHEN: tuple[str, ...] = (
    "zh", "en", "de", "it", "pt", "es", "ja", "ko", "fr", "ru",
)

# Who tidies the dictation. "aus" is nobody — the raw text lands in the
# field. The other three are the three servers this program can hold that
# could do it.
BEREINIGUNGEN: tuple[str, ...] = ("aus", "putzmodell", "modell", "agent")

# English, because every model understands it — including one brought in for
# another language, whose own tongue we cannot know here. The language the
# speech is in travels separately, in a field of its own, so this text stays
# free of it.
ANWEISUNG_VORGABE = (
    "Transcribe the speech exactly as spoken, word for word. Keep the "
    "speaker's language. Do not translate, do not summarise, do not answer. "
    "Output only the transcription."
)

BEREINIGUNG_ANWEISUNG_VORGABE = (
    "You are cleaning up dictated text. Fix punctuation and capitalisation, "
    "remove filler words, stutters and false starts, apply spoken "
    'punctuation ("comma", "full stop", "new line" and their equivalents in '
    "the text's language). Keep every word of content, keep the language, "
    "keep file names and technical terms exactly. Do not answer, do not add, "
    "do not comment. Output only the cleaned text."
)

# Goes in front of the message text ONLY inside a live conversation — never
# stored, never shown, and never touching a typed chat (app/verlaufsbau.py).
GESPRAECHSANWEISUNG_VORGABE = (
    "This is a spoken conversation. Answer in the language the user speaks. "
    "Your answer is read aloud, so speak in two or three short, natural "
    "sentences: the answer first, then at most one brief, useful remark. "
    "No lists, no markdown, no emojis. Never grovel and never "
    "over-apologise; if something is not possible, say so plainly and "
    "offer the next best step."
)

# How long an instruction may be. Bounded like every other stored string —
# the settings column holds JSON and cannot check anything by itself.
TEXT_HOECHSTLAENGE = 4000
NAME_HOECHSTLAENGE = 200

# The range the voice's temperature slider offers.
TEMPERATUR_MIN = 0.0
TEMPERATUR_MAX = 1.0
TEMPERATUR_SCHRITT = 0.05

VORGABE: dict[str, Any] = {
    "sprache": AUTO,
    "anweisung": ANWEISUNG_VORGABE,
    # Shipped switched on, the house rule for anything with a visible switch
    # next to it. It costs nothing until a tidy-up model is chosen: without
    # one there is nobody to ask, and the raw text lands in the field exactly
    # as it would with this off.
    "bereinigung": "putzmodell",
    # Empty is "none chosen", which is the as-installed state — nothing ships
    # with this program, the folder starts empty.
    "putzmodell": "",
    "bereinigung_anweisung": BEREINIGUNG_ANWEISUNG_VORGABE,
    # Shipped switched on, the same rule "bereinigung" follows above: it
    # costs nothing until a voice is chosen, and without one there is
    # nothing to read aloud regardless of this switch.
    "vorlesen": True,
    # Empty is "none chosen" for all three — the folder starts empty, the
    # same as "putzmodell" above.
    "stimme": "",
    "stimmprobe": "",
    "stimmsprache": "",
    # The model's own value until a measured one replaces it (app/stimme.py).
    "stimmtemperatur": STIMME_TEMPERATUR,
    # The voice's other four generation values, in the house's ranges; the
    # works values are the ones llama-tts has always been called with.
    "stimmtop_k": STIMME_TOP_K,
    "stimmtop_p": STIMME_TOP_P,
    "stimmmin_p": STIMME_MIN_P,
    "stimmstrafe": STIMME_WIEDERHOLUNGSSTRAFE,
    # The voice model's memory: layers on the card (99 = all of them, the
    # flag's own meaning) and threads (0 = the engine decides), the same two
    # levers the chat servers carry.
    "stimmschichten": 99,
    "stimmfaeden": 0,
    # The tidy-up server's memory and generation values. The memory starts
    # at the values it has always started with (app/sprachserver.py); the
    # generation values are the works ones the window shows — a cleaner is
    # meant to be unsurprising. Greedy, and with every sampler but the
    # top-p cut-off off, and every one of them is a setting that can be
    # moved.
    "putzkontext": 2048,
    "putzschichten": 99,
    "putzfaeden": 0,
    "putztemperatur": 0.0,
    "putztop_k": 0,
    "putztop_p": 1.0,
    "putzmin_p": 0.0,
    "putzstrafe": 1.0,
    "gespraechsanweisung": GESPRAECHSANWEISUNG_VORGABE,
    # Shipped off: a dictated text waits in the field, where it can still be
    # read and corrected before Enter sends it — the way dictation always
    # worked. Switched on, it goes out the moment the recording is stopped.
    "automatik": False,
    # The key that works like a click on the microphone button while the
    # window is in front: Cmd + Option, pressed and let go with no other key
    # between (frontend/src/lib/microphoneKey.js). Written the way that
    # module writes it.
    "microphone_key": "Meta+Alt",
}

# A stored microphone key: modifiers in their fixed order, then at most one
# key `code` (frontend/src/lib/microphoneKey.js writes it that way). Checked
# here so that nothing else reaches the page, by the rule the page records
# with: a key needs Cmd or Control with it and is no modifier key itself,
# modifiers alone need two. The page also refuses the program's own
# shortcuts; it never sends one.
_MODIFIERS = ("Meta", "Control", "Alt", "Shift")
_KEY_CODE = re.compile(r"^(?!(Meta|OS|Control|Alt|Shift)(Left|Right)$)[A-Za-z0-9]{1,24}$")


def _microphone_key(raw: Any) -> str:
    """A stored key combination, or the works key when it is none."""
    parts = str(raw or "").strip().split("+")
    mods = [part for part in parts if part in _MODIFIERS]
    keys = parts[len(mods):]
    usable = (
        mods == [mod for mod in _MODIFIERS if mod in mods]
        and len(keys) <= 1
        and all(_KEY_CODE.match(key) and key not in _MODIFIERS for key in keys)
        and (("Meta" in mods or "Control" in mods) if keys else len(mods) >= 2)
    )
    return "+".join(parts) if usable else VORGABE["microphone_key"]


def _text(roh: Any, ersatz: str) -> str:
    """A stored instruction, or the works text when the field was emptied.

    An empty instruction is not a choice anybody makes on purpose — it is a
    field that was cleared and not filled in again, and sending nothing at
    all would leave the model to invent its own job.
    """
    if not isinstance(roh, str):
        return ersatz
    sauber = roh.strip()[:TEXT_HOECHSTLAENGE]
    return sauber or ersatz


def _zahl(roh: Any, tief: int, hoch: int, ersatz: int) -> int | None:
    """A whole number inside its bounds, or the works value for anything
    unreadable. ``None`` stays ``None`` and means "not set"."""
    if roh is None:
        return None
    try:
        zahl = int(roh)
    except (TypeError, ValueError):
        return ersatz
    return max(tief, min(hoch, zahl))


def _generation(roh: Any, name: str) -> float | int | None:
    """One generation value, clamped into the house's own range for that
    knob (app/parameter.py) — the same numbers and steps the chat's
    parameter panel offers. ``None`` stays out; only a set value travels."""
    if roh is None:
        return None
    sauber = parameter_pruefen({name: roh})
    return sauber.get(name)


# Our setting key -> the house's parameter name (app/parameter.py), for the
# two blocks: the voice's and the tidy-up server's.
_VOICE_PARAMETER = (
    ("stimmtop_k", "top_k"),
    ("stimmtop_p", "top_p"),
    ("stimmmin_p", "min_p"),
    ("stimmstrafe", "repeat_penalty"),
)
_PUTZ_PARAMETER = (
    ("putztemperatur", "temperature"),
    ("putztop_k", "top_k"),
    ("putztop_p", "top_p"),
    ("putzmin_p", "min_p"),
    ("putzstrafe", "repeat_penalty"),
)


def wahl_pruefen(wert: Any) -> dict[str, Any]:
    """The dictation choice, before it is stored.

    Each key survives only when it was sent, so the panel can write the
    instruction without resending the language and the other way round — the
    same rule the server start choice follows.
    """
    if not isinstance(wert, dict):
        return {}
    sauber: dict[str, Any] = {}
    if "sprache" in wert:
        roh = str(wert["sprache"] or AUTO).strip().lower()
        sauber["sprache"] = roh if roh in (AUTO, *SPRACHEN) else AUTO
    if "anweisung" in wert:
        sauber["anweisung"] = _text(wert["anweisung"], ANWEISUNG_VORGABE)
    if "bereinigung" in wert:
        roh = str(wert["bereinigung"] or "").strip().lower()
        sauber["bereinigung"] = roh if roh in BEREINIGUNGEN else VORGABE["bereinigung"]
    if "putzmodell" in wert:
        roh = wert["putzmodell"]
        sauber["putzmodell"] = "" if roh is None else str(roh).strip()[:NAME_HOECHSTLAENGE]
    if "bereinigung_anweisung" in wert:
        sauber["bereinigung_anweisung"] = _text(
            wert["bereinigung_anweisung"], BEREINIGUNG_ANWEISUNG_VORGABE
        )
    if "vorlesen" in wert:
        sauber["vorlesen"] = bool(wert["vorlesen"])
    if "stimme" in wert:
        roh = wert["stimme"]
        sauber["stimme"] = "" if roh is None else str(roh).strip()[:NAME_HOECHSTLAENGE]
    if "stimmprobe" in wert:
        roh = wert["stimmprobe"]
        sauber["stimmprobe"] = "" if roh is None else str(roh).strip()[:NAME_HOECHSTLAENGE]
    if "stimmsprache" in wert:
        roh = str(wert["stimmsprache"] or "").strip().lower()
        sauber["stimmsprache"] = roh if roh in STIMMSPRACHEN else ""
    if "stimmtemperatur" in wert:
        # A number from 0 to 1, or nothing is stored: quietly clamping a
        # value outside the range would store a choice nobody made. The
        # stored value is kept as typed — the slider finds the nearest
        # step, the number field shows exactly what was stored.
        roh = wert["stimmtemperatur"]
        if (
            isinstance(roh, (int, float))
            and not isinstance(roh, bool)
            and TEMPERATUR_MIN <= roh <= TEMPERATUR_MAX
        ):
            sauber["stimmtemperatur"] = float(roh)
    for schluessel, knob in _VOICE_PARAMETER:
        if schluessel in wert:
            sauber[schluessel] = _generation(wert[schluessel], knob)
    for schluessel, knob in _PUTZ_PARAMETER:
        if schluessel in wert:
            sauber[schluessel] = _generation(wert[schluessel], knob)
    if "stimmschichten" in wert:
        sauber["stimmschichten"] = _zahl(
            wert["stimmschichten"], SCHICHTEN_MIN, SCHICHTEN_MAX, VORGABE["stimmschichten"]
        )
    if "stimmfaeden" in wert:
        sauber["stimmfaeden"] = _zahl(wert["stimmfaeden"], 0, MAX_FAEDEN, VORGABE["stimmfaeden"])
    if "putzkontext" in wert:
        sauber["putzkontext"] = _zahl(
            wert["putzkontext"], KONTEXT_MIN, KONTEXT_MAX, VORGABE["putzkontext"]
        )
    if "putzschichten" in wert:
        sauber["putzschichten"] = _zahl(
            wert["putzschichten"], SCHICHTEN_MIN, SCHICHTEN_MAX, VORGABE["putzschichten"]
        )
    if "putzfaeden" in wert:
        sauber["putzfaeden"] = _zahl(wert["putzfaeden"], 0, MAX_FAEDEN, VORGABE["putzfaeden"])
    if "gespraechsanweisung" in wert:
        sauber["gespraechsanweisung"] = _text(
            wert["gespraechsanweisung"], GESPRAECHSANWEISUNG_VORGABE
        )
    if "automatik" in wert:
        sauber["automatik"] = bool(wert["automatik"])
    if "microphone_key" in wert:
        sauber["microphone_key"] = _microphone_key(wert["microphone_key"])
    # A None is "not set", and "not set" is a key that is simply not there —
    # the works answer stands in. A stored null would win over the works
    # answer in the merge and every reader would trip on it (the generator
    # values and memory pairs arrive as None when a field was cleared).
    return {name: wert for name, wert in sauber.items() if wert is not None}


def wahl(repositories) -> dict[str, Any]:
    """What the fields say right now, with the works answers behind them.

    Global scope only: a microphone belongs to the machine, not to one
    conversation, and a per-chat dictation language would be a setting whose
    value depends on which window happens to be open.
    """
    stand = repositories.einstellungen.zusammengefuehrt(SCHLUESSEL, vorgabe={})
    return {**VORGABE, **wahl_pruefen(stand if isinstance(stand, dict) else {})}


def sprachcode(repositories) -> str | None:
    """The language code to send, or None at "automatic".

    None means the field is left out of the request entirely. An empty string
    would be a language whose name is nothing, which is not the same thing.
    """
    gewaehlt = wahl(repositories)["sprache"]
    return None if gewaehlt == AUTO else gewaehlt


def anweisung(repositories) -> str:
    """The instruction the speech model gets, read on every request.

    Read here and not at start: changing the text has to take effect at once,
    without stopping and restarting a server that has a model in memory.
    """
    return wahl(repositories)["anweisung"]


def bereinigung(repositories) -> str:
    """Who tidies, as it applies right now.

    "putzmodell" with no file chosen resolves to "aus": nothing is configured
    to tidy, so nothing was skipped either, and a window told "skipped" would
    complain about a state nobody set up.
    """
    stand = wahl(repositories)
    gewaehlt = stand["bereinigung"]
    if gewaehlt == "putzmodell" and not stand["putzmodell"]:
        return "aus"
    return gewaehlt


def putzmodell(repositories) -> str:
    """The file the tidy-up model runs from, or an empty string for none."""
    return wahl(repositories)["putzmodell"]


def bereinigung_anweisung(repositories) -> str:
    return wahl(repositories)["bereinigung_anweisung"]


def vorlesen(repositories) -> bool:
    """Whether a finished answer is read aloud during a conversation."""
    return bool(wahl(repositories)["vorlesen"])


def stimme(repositories) -> str:
    """The voice model's file name, or an empty string for none chosen."""
    return wahl(repositories)["stimme"]


def stimmprobe(repositories) -> str:
    """The voice sample's file name, or an empty string for none chosen."""
    return wahl(repositories)["stimmprobe"]


def stimmsprache(repositories) -> str:
    """The voice's own language, or an empty string for none chosen.

    Independent of both the dictation language and the interface language:
    a voice reading German answers does not have to be a German voice, and
    a voice does not follow whatever language the speaker used.
    """
    return wahl(repositories)["stimmsprache"]


def automatik(repositories) -> bool:
    """Whether a finished dictation is sent at once."""
    return bool(wahl(repositories)["automatik"])


def stimmwerte(repositories, stand: dict[str, Any] | None = None) -> dict[str, float]:
    """The voice's five generation values under the engine's own names, read
    fresh for every sentence — the works values stand in for anything not
    set, so the call reads exactly as before this setting existed. A caller
    that already read the setting hands its `stand` in instead of paying
    for a second read."""
    stand = wahl(repositories) if stand is None else stand
    return {
        "temperature": float(stand["stimmtemperatur"]),
        "top_k": float(stand["stimmtop_k"]),
        "top_p": float(stand["stimmtop_p"]),
        "min_p": float(stand["stimmmin_p"]),
        "repeat_penalty": float(stand["stimmstrafe"]),
    }


def stimmspeicher(repositories, stand: dict[str, Any] | None = None) -> tuple[int, int]:
    """The voice model's layers and threads, as the call wants them."""
    stand = wahl(repositories) if stand is None else stand
    return int(stand["stimmschichten"]), int(stand["stimmfaeden"])


def putzspeicher(
    repositories, stand: dict[str, Any] | None = None
) -> tuple[int, int, int]:
    """The tidy-up server's context, layers and threads for its start."""
    stand = wahl(repositories) if stand is None else stand
    return (
        int(stand["putzkontext"]),
        int(stand["putzschichten"]),
        int(stand["putzfaeden"]),
    )


def putzsampling(
    repositories, stand: dict[str, Any] | None = None
) -> dict[str, float] | None:
    """The tidy-up server's five generation values for its start, works
    answers included — all five always travel, so a cleaner writes the
    same way everywhere: greedy and with the samplers off is the works
    state, and the model's own card (written for conversation) does not
    sample on top of it. A value somebody cleared on purpose stays out;
    None only when all five were."""
    stand = wahl(repositories) if stand is None else stand
    werte = {
        knob: stand[schluessel]
        for schluessel, knob in _PUTZ_PARAMETER
        if stand[schluessel] is not None
    }
    return werte or None


def gespraechsanweisung(repositories) -> str:
    """The instruction a live conversation's message gets, read fresh on
    every request — never the stored row, never a typed chat."""
    return wahl(repositories)["gespraechsanweisung"]


# Told to the model when the person cut its spoken reply short — without it
# the half answer in the history reads like a finished one. The brackets
# mark it as a note about the talk, not as words the person said.
UNTERBRECHUNGSHINWEIS = (
    "[Note: the user interrupted your previous spoken reply before it finished.]"
)


def gespraechsvorsatz(repositories, unterbrochen: bool = False) -> str:
    """What goes in front of a conversation message on its way to the model:
    the conversation instruction, and before it the interruption note when
    the previous reply was cut short while it was being spoken. Like the
    instruction, it travels with this one request and is never stored."""
    anweisung = gespraechsanweisung(repositories)
    return f"{UNTERBRECHUNGSHINWEIS}\n\n{anweisung}" if unterbrochen else anweisung


def vorgaben() -> dict[str, Any]:
    """The works answers, for the window to be told rather than to carry.

    The instruction texts above all: the panel's "restore" button has to put
    back exactly what the service would use, and a second copy in the page
    would agree with this one only until somebody changed one of them.
    """
    return dict(VORGABE)


__all__ = [
    "ANWEISUNG_VORGABE",
    "AUTO",
    "BEREINIGUNGEN",
    "BEREINIGUNG_ANWEISUNG_VORGABE",
    "GESPRAECHSANWEISUNG_VORGABE",
    "SCHLUESSEL",
    "SPRACHEN",
    "STIMMSPRACHEN",
    "UNTERBRECHUNGSHINWEIS",
    "VORGABE",
    "anweisung",
    "automatik",
    "bereinigung",
    "bereinigung_anweisung",
    "gespraechsanweisung",
    "gespraechsvorsatz",
    "putzmodell",
    "putzsampling",
    "putzspeicher",
    "sprachcode",
    "stimme",
    "stimmprobe",
    "stimmspeicher",
    "stimmsprache",
    "stimmwerte",
    "vorgaben",
    "vorlesen",
    "wahl",
    "wahl_pruefen",
]
