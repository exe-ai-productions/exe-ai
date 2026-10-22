"""The speech server: a fourth llama-server, on a port of its own.

Speech to text, without a second engine and without a codec. The very same
program that answers chat also reads audio — a speech model plus its
projector (``--mmproj``) is loaded the way a vision model is, and the
recording goes in as a plain WAV. So this module is small on purpose: it
builds a runner of the known kind and it asks one question over HTTP.

**One question, two ways of asking it.** The engine offers the OpenAI form,
``POST /v1/audio/transcriptions`` — a multipart form with the file, a
``language`` and a ``prompt``. Internally the engine turns that into a chat
request carrying an ``input_audio`` part, which is the second way and the
one this module falls back on when the first is not answered. Which one is
in force is ``WEG`` below, a constant and not a setting: it is a property of
the engine on this machine, not a choice anybody should have to make.

**Its own everything.** Port, note file, key variable — the rule the
embedding server was built on after its first version collided with the chat
server on all three. Two runners live here, not one: the speech model that
listens, and a small text model that tidies the dictation afterwards. They
are two processes with two ports and two keys, for the same reason.

**No filter on what comes back.** A speech model invents words out of
silence — a thank-you, a subtitle line. Nothing here removes them. The text
goes into the input field and the person reading it decides; that is exactly
why a dictation is never sent off by itself. The one exception is a protocol
marker one family writes in front of its own answer, which is not speech at
all: see ``ASR_MARKE``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

import httpx

from app import runnerzustand
from app.modellrunner import Modellrunner

log = logging.getLogger(__name__)

# The note that finds an orphan again after a service restart. A name of its
# own, so the runners in the same folder never erase each other's.
PID_DATEI = ".sprachserver.pid"
PUTZ_PID_DATEI = ".sprachputz.pid"

# The environment variables the two keys travel in.
SCHLUESSEL_VARIABLE = "EXE_SPRACHE_API_KEY"
PUTZ_SCHLUESSEL_VARIABLE = "EXE_SPRACHPUTZ_API_KEY"

# Nothing extra on the command line. The projector is written by the runner
# itself from what lies next to the model, and the window travels as a start
# value — a second ``--ctx-size`` from a flag list is how the chat server's
# command line ended up carrying that flag twice.
FLAGS: tuple[str, ...] = ()

# A dictation may take longer than a vector. Four minutes of audio on a cold
# processor is the case this number has to survive; a shorter limit turns a
# long sentence into "not available" while the engine is still working.
ZEITGRENZE = 60.0

# The tidy-up talks, so it gets a shorter leash: it is a helper on the way to
# the input field, and a person is watching the button spin.
PUTZ_ZEITGRENZE = 30.0

# How the audio reaches the engine.
#
# "endpunkt" is the OpenAI form (``/v1/audio/transcriptions``), which the
# engine turns into a chat request itself — so the language and the
# instruction ride in fields made for them instead of being smuggled into a
# conversation. "chat" is that same conversation built by hand, kept as the
# fallback for a build whose server does not carry the endpoint.
#
# Measured on the shipped build (b10310): the endpoint is present, and both
# speech models answer on it. So the endpoint is what runs, and the fallback
# stays as the answer to an older engine rather than as a switch on a page.
WEG = "endpunkt"

# The marker one speech family writes in front of every answer. Qwen3-ASR
# reports the language it heard and then opens its transcription with this
# token — measured on both sizes, on both request paths, with and without a
# chat template: the prefix is always there.
#
# It is cut off here, and this is the ONE thing that is cut. It is not speech
# and never was: it is the model's own protocol leaking through the engine's
# answer, and left standing it would put "language German<asr_text>" in front
# of every dictation. What a model INVENTS out of silence stays exactly where
# it is — that is content, however wrong, and the person reading the field is
# the one who decides about it.
ASR_MARKE = "<asr_text>"

# What the multipart form calls the model. The engine does not look it up —
# it serves whatever it was started with — but the field is part of the form,
# and an empty one is a request that reads as unfinished.
MODELLNAME = "speech"


def runner_bauen(
    modellordner, programm: str | None, port: int, shared_with: Callable[[], int | None] | None = None
) -> Modellrunner:
    """The speech server's runner — the same class, another kind.

    WITH the chat template, and that was measured rather than assumed. The
    embedding server next door runs without one because it never samples; a
    speech model does sample, and one of the two known families is a chat
    model with ears — it needs its own template to be told it is being asked
    to transcribe at all. Started without one it answered the same recording
    with three backticks once, with a request to "provide the speech" once,
    and with the sentence twice; with the template the sentence came back in
    two runs out of three. Neither number is a guarantee — that model answers
    the same request differently from one call to the next — but the template
    is the better of the two, and the other family is indifferent to it, so
    it costs nothing there.
    """
    return Modellrunner(
        modellordner,
        programm,
        port=port,
        pid_datei=PID_DATEI,
        schluessel_variable=SCHLUESSEL_VARIABLE,
        zusatzflags=FLAGS,
        sampling_flags=True,
        zustand_callback=runnerzustand.melder(runnerzustand.SPEECH),
        shared_with=shared_with,
    )


def putzrunner_bauen(
    modellordner, programm: str | None, port: int, shared_with: Callable[[], int | None] | None = None
) -> Modellrunner:
    """The tidy-up model's runner — the same folder, everything else its own.

    The same folder because a person who wants a cleaner puts a small text
    model next to their speech model, and a second folder for one file would
    be a second thing to find and to move. Which file is which is answered by
    the two picker fields on the panel, never by a filter on the name.

    Unlike the one above this model CHATS, so it gets the sampling lore and
    the chat template with it.
    """
    return Modellrunner(
        modellordner,
        programm,
        port=port,
        pid_datei=PUTZ_PID_DATEI,
        schluessel_variable=PUTZ_SCHLUESSEL_VARIABLE,
        zusatzflags=(),
        sampling_flags=True,
        zustand_callback=runnerzustand.melder(runnerzustand.CLEANUP),
        shared_with=shared_with,
    )


def _kopf(schluessel: str | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {schluessel}"} if schluessel else {}


def _ueber_endpunkt(
    port: int,
    schluessel: str | None,
    wav: bytes,
    sprache: str | None,
    anweisung: str | None,
) -> str | None:
    """The OpenAI form: one multipart request, one text back.

    ``language`` is left out entirely when nobody named one — an empty field
    is not the same as no field, and the engine reads the empty one as a
    language whose name is nothing.
    """
    formular: dict[str, str] = {"model": MODELLNAME, "response_format": "json"}
    if sprache:
        formular["language"] = sprache
    if anweisung:
        formular["prompt"] = anweisung
    antwort = httpx.post(
        f"http://127.0.0.1:{port}/v1/audio/transcriptions",
        files={"file": ("diktat.wav", wav, "audio/wav")},
        data=formular,
        headers=_kopf(schluessel),
        timeout=ZEITGRENZE,
    )
    antwort.raise_for_status()
    text = antwort.json()["text"]
    return text if isinstance(text, str) else None


def _ueber_chat(
    port: int,
    schluessel: str | None,
    wav: bytes,
    sprache: str | None,
    anweisung: str | None,
) -> str | None:
    """The fallback: the same audio as a chat message.

    What the endpoint above builds internally, built here instead — an
    ``input_audio`` part beside the instruction. The declared format is
    ignored by the engine (it reads the file's own header), and it is sent
    anyway because the field belongs to the shape.

    The language cannot ride in a field of its own on this path, so it goes
    in as a sentence in front of the instruction. Left out at "automatic",
    where saying nothing IS the instruction.
    """
    import base64

    satz = anweisung or ""
    if sprache:
        satz = f"The speech is in {sprache}. {satz}".strip()
    antwort = httpx.post(
        f"http://127.0.0.1:{port}/v1/chat/completions",
        json={
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": satz},
                        {
                            "type": "input_audio",
                            "input_audio": {
                                "data": base64.b64encode(wav).decode("ascii"),
                                "format": "wav",
                            },
                        },
                    ],
                }
            ],
            "stream": False,
            "temperature": 0,
        },
        headers=_kopf(schluessel),
        timeout=ZEITGRENZE,
    )
    antwort.raise_for_status()
    inhalt = antwort.json()["choices"][0]["message"]["content"]
    return inhalt if isinstance(inhalt, str) else None


class SpeechServerError(Exception):
    """The speech server answered, and the answer was an error.

    ``reason`` is what the server said (its own ``error.message``, or the
    status line when it said nothing readable) — the sentence the person
    reads. ``log_text`` is the same with the status in front, for the log.
    """

    def __init__(self, reason: str, status: int) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status = status

    @property
    def log_text(self) -> str:
        return f"HTTP {self.status}: {self.reason}"


def _refusal(fehler: httpx.HTTPStatusError) -> SpeechServerError | None:
    """What the server said in an error answer, or nothing when the error
    carries no answer to read."""
    antwort = getattr(fehler, "response", None)
    if antwort is None:
        return None
    status = antwort.status_code
    try:
        message = antwort.json()["error"]["message"]
    except (ValueError, KeyError, TypeError):
        message = None
    if not isinstance(message, str) or not message.strip():
        message = f"HTTP {status} {antwort.reason_phrase}".strip()
    return SpeechServerError(message.strip(), status)


def transkribieren(
    port: int,
    schluessel: str | None,
    wav: bytes,
    *,
    sprache: str | None = None,
    anweisung: str | None = None,
) -> str | None:
    """The spoken words as text, or None when this way is not available.

    None covers every failure without a readable answer alike — no server,
    one still loading, a timeout, an answer in a shape we do not recognise.
    The caller turns it into one sentence a person can act on; a traceback
    would say the same thing in a language nobody reads. Every one of them is
    in the log, with its kind.

    A server that answers with an error is not silent: ``SpeechServerError``
    carries what it said, and the caller shows it.

    An EMPTY string is not a failure. Silence transcribes to nothing, and
    nothing is a correct answer.
    """
    if not wav:
        return None
    weg = _ueber_endpunkt if WEG == "endpunkt" else _ueber_chat
    try:
        text = weg(port, schluessel, wav, sprache, anweisung)
    except httpx.HTTPStatusError as fehler:
        refusal = _refusal(fehler)
        if refusal is not None:
            log.warning("Speech server answered with an error: %s", refusal.log_text)
            raise refusal from None
        log.warning("Speech server answered with an error that carries no reply", exc_info=True)
        return None
    except httpx.RequestError as fehler:
        # No answer at all: the connection, or the time, ran out.
        log.warning(
            "Speech server does not answer (%s): %s", type(fehler).__name__, str(fehler) or "no detail"
        )
        return None
    except Exception as fehler:  # noqa: BLE001 - every other failure means the same thing here
        log.warning(
            "Speech server answered in a form that cannot be read (%s)", type(fehler).__name__,
            exc_info=True,
        )
        return None
    if text is None:
        return None
    _, marke, danach = text.partition(ASR_MARKE)
    return danach if marke else text


# The dictation travels inside this tag: a small model told to tidy a spoken
# question otherwise reads the question as one put to it and answers it. The
# tag marks the words as material, not as a request.
TRANSCRIPT_OPEN = "<TRANSCRIPT>"
TRANSCRIPT_CLOSE = "</TRANSCRIPT>"


def _without_tag(text: str) -> str:
    """The tidied words without the tag a model sometimes echoes back around
    them (or half of it: only the opening one, or only the closing one)."""
    tidy = text.strip()
    if tidy.startswith(TRANSCRIPT_OPEN):
        tidy = tidy[len(TRANSCRIPT_OPEN):]
    if tidy.endswith(TRANSCRIPT_CLOSE):
        tidy = tidy[: -len(TRANSCRIPT_CLOSE)]
    return tidy.strip()


def bereinigen(
    basis_url: str, schluessel: str | None, anweisung: str, text: str
) -> str | None:
    """The dictation, tidied by a text model — or None when that is not
    available right now.

    One chat request against whichever server was chosen for the job. No
    stream, and no sampler of its own: how the words come out is the
    clean-up server's own setting, read at its start (the panel carries
    it), and its works values — temperature 0, every sampler off — keep
    two runs on the same words as equal as they always were.

    None is the honest answer for a server that is off or silent. What it may
    NEVER become is the raw text handed on as if it had been cleaned — the
    caller says which of the two happened, and the window says so too.
    """
    roh = text.strip()
    if not roh:
        return roh
    try:
        antwort = httpx.post(
            f"{basis_url.rstrip('/')}/chat/completions",
            json={
                "messages": [
                    {"role": "system", "content": anweisung},
                    {
                        "role": "user",
                        "content": f"{TRANSCRIPT_OPEN}\n{roh}\n{TRANSCRIPT_CLOSE}",
                    },
                ],
                "stream": False,
            },
            headers=_kopf(schluessel),
            timeout=PUTZ_ZEITGRENZE,
        )
        antwort.raise_for_status()
        inhalt = antwort.json()["choices"][0]["message"]["content"]
    except Exception:  # noqa: BLE001 - every failure means the same thing here
        log.debug("Dictation clean-up does not answer", exc_info=True)
        return None
    if not isinstance(inhalt, str):
        return None
    sauber = _without_tag(inhalt)
    # A model that answered with nothing has not tidied anything; handing an
    # empty field back would look like the recording had failed.
    return sauber or None


__all__ = [
    "ASR_MARKE",
    "FLAGS",
    "MODELLNAME",
    "PID_DATEI",
    "PUTZ_PID_DATEI",
    "PUTZ_SCHLUESSEL_VARIABLE",
    "PUTZ_ZEITGRENZE",
    "SCHLUESSEL_VARIABLE",
    "TRANSCRIPT_OPEN",
    "TRANSCRIPT_CLOSE",
    "WEG",
    "ZEITGRENZE",
    "bereinigen",
    "putzrunner_bauen",
    "runner_bauen",
    "transkribieren",
]
