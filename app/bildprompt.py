"""Turning a written wish into a prompt an image model understands.

People describe the picture they want in their own language, and picture
models answer far more reliably to English — and each family to English of
its own kind: a CLIP reader to short phrases, a T5 reader to clear
sentences, a language-model reader to a full description. A language model
of the user's choice writes the prompt for the family of the picture model
in use, with the family's own instruction, for the window's "Enhance"
button and for ``draw_image`` alike.

Two rules every instruction below keeps:

* The scene stays the scene. Expanding a prompt is adding detail to what
  was described, never inventing a different picture — a user who asked for
  a red bicycle and got a motorcycle has been given a worse tool than none.
* Only the prompt comes back. Models like to explain what they did; an
  explanation pasted into the prompt field would be drawn as if it were part
  of the picture.

The embedding model is deliberately not an option here. Embeddings produce
vectors, not text — the call goes to the ordinary chat interface of a
language model, and it never touches a chat history.
"""

from __future__ import annotations

import contextlib
import logging

from app import faltversuche, image_families
from app.providers import ChatNachricht, Generierungsanfrage, Provider

log = logging.getLogger(__name__)

# The text readers a picture model hears through, each with the way of
# writing that suits it (sd.cpp's conditioners): a CLIP reader takes short
# phrases in chunks of 77 tokens and weights like (word:1.2); a T5 reader
# takes clear sentences; a language-model reader takes a full description,
# text inside the picture in quotes. The families are listed under the
# reader their text goes through, by the names of app/image_families.py.
LESER: dict[str, tuple[str, ...]] = {
    "clip": ("sd15", "sd2", "sdxl", "sdxs"),
    "t5": ("sd3", "flux", "chroma", "chroma_radiance", "minit2i", "pixart"),
    "llm": (
        "flux2", "flux2_klein", "zimage", "qwen_image", "qwen_image_2_1", "krea2",
        "ideogram4", "ernie", "lens", "longcat", "ovis", "sefi", "anima", "boogu",
        "mage_flow", "hidream_o1", "llada_image", "sensenova_u1",
    ),
}

# In English in the code and not in the translation catalogue: this is not
# interface text but part of the call, and the models answer best to it in
# the language it was written in. One instruction per family that draws
# from text; the user can rewrite each one in the picture server, and
# "reset" brings this text back.
#
# Where the maker of a family says how its model wants to be prompted, the
# instruction follows that, with the maker's page beside it; where the
# maker says nothing, it follows the family's reader (the three below).
_CLIP = (
    "You write prompts for {name}, an image model that reads its prompt "
    "through CLIP. Write one English prompt as short, concrete phrases "
    "separated by commas, the most important first: the subject, then "
    "setting, light, style and camera. Weights like (word:1.2) are allowed "
    "for what must stand out. The model reads long prompts in separate "
    "chunks of 77 tokens, so keep it short. Return only the prompt."
)
_T5 = (
    "You write prompts for {name}, an image model that reads its prompt "
    "through T5. Write one or two clear English sentences: the main subject "
    "first, then action, setting, light and style. Return only the prompt."
)
_LLM = (
    "You write prompts for {name}, an image model that reads its prompt "
    "through a language model. Write a detailed English description of the "
    "finished picture: subject, composition, setting, light, colours and "
    "style. Put any text that must appear in the picture in double quotes. "
    "Return only the prompt."
)
_VORLAGE = {"clip": _CLIP, "t5": _T5, "llm": _LLM}

_EIGENE: dict[str, str] = {
    # huggingface.co/lodestones/Chroma1-HD: one long English paragraph.
    "chroma": (
        "You write prompts for Chroma, an image model that reads its prompt "
        "through T5. Write one detailed English paragraph in plain prose: "
        "the main subject first, then action, setting, light, colours and "
        "style. Return only the prompt."
    ),
    # docs.bfl.ai/guides/prompting_guide_flux2: subject, action, style,
    # context, the key items first; no negative prompt; text in quotes.
    "flux2": (
        "You write prompts for Flux.2, an image model that reads its prompt "
        "through a language model. Write natural English prose in this "
        "order: subject, action, style, context, with the most important "
        "elements first. Describe what should be in the picture rather than "
        "what should not; the model has no negative prompt. Put any text "
        "that must appear in the picture in double quotes, and give exact "
        "colours as hex codes where the request names them. Return only the "
        "prompt."
    ),
    # docs.bfl.ai, unified prompting reference for FLUX.2 klein: prose, not
    # keyword lists; the light with its source and direction; style and
    # mood at the end.
    "flux2_klein": (
        "You write prompts for Flux.2 klein, an image model that reads its "
        "prompt through a language model and draws exactly what is written. "
        "Write English prose, not a keyword list: the subject and what it "
        "does, the setting, and the light with its source and direction. End "
        "with \"Style:\" and \"Mood:\" followed by a few words each. Put any "
        "text that must appear in the picture in double quotes. Return only "
        "the prompt."
    ),
    # Tongyi-MAI/Z-Image, the prompt enhancer of its demo: keep subject,
    # count and action, text in double quotes, no quality tags.
    "zimage": (
        "You write prompts for Z-Image, an image model that reads its prompt "
        "through a language model. Write a detailed English description of "
        "the finished picture. Keep every subject, its number and its action "
        "exactly as requested, then add setting, composition, light and "
        "style. Put any text that must appear in the picture in double "
        "quotes. Do not add quality tags such as \"8K\" or \"masterpiece\". "
        "Return only the prompt."
    ),
    # huggingface.co/Qwen/Qwen-Image: a detailed description, text in
    # quotes, and the card's own closing words.
    "qwen_image": (
        "You write prompts for Qwen-Image, an image model that reads its "
        "prompt through a language model. Write a detailed English "
        "description of the finished picture: subject, composition, setting, "
        "light, colours and style. Put any text that must appear in the "
        "picture in double quotes. End the prompt with \"Ultra HD, 4K, "
        "cinematic composition.\" Return only the prompt."
    ),
    # huggingface.co/krea/Krea-2-Raw and its makers' prompt enhancer: long,
    # detailed natural language gives the best pictures.
    "krea2": (
        "You write prompts for Krea 2, an image model that reads its prompt "
        "through a language model and draws best from long prompts. Write a "
        "long, detailed English description in natural sentences: subject, "
        "composition, setting, light, colours, materials and style. Put any "
        "text that must appear in the picture in double quotes. Return only "
        "the prompt."
    ),
    # huggingface.co/ideogram-ai/ideogram-4-fp8: trained on exhaustive
    # captions; its own prompt expander writes everything out.
    "ideogram4": (
        "You write prompts for Ideogram 4, an image model that reads its "
        "prompt through a language model and was trained on exhaustive "
        "captions. Write an exhaustive English description of the finished "
        "picture: every subject with its position, the composition, the "
        "setting, the light, the colour palette and the style. Put any text "
        "that must appear in the picture in double quotes. Return only the "
        "prompt."
    ),
    # huggingface.co/baidu/ERNIE-Image: long descriptive prose, about 150
    # words in the card's example.
    "ernie": (
        "You write prompts for ERNIE-Image, an image model that reads its "
        "prompt through a language model. Write one long English paragraph "
        "of descriptive prose, about 150 words: subject, composition, "
        "setting, light, colours and style. Put any text that must appear in "
        "the picture in double quotes. Return only the prompt."
    ),
    # github.com/microsoft/Lens: trained on long captions; the examples run
    # from 30 to 100 words.
    "lens": (
        "You write prompts for Lens, an image model that reads its prompt "
        "through a language model and was trained on long captions. Write a "
        "detailed English description of 30 to 100 words: subject, "
        "composition, setting, light, colours and style. Put any text that "
        "must appear in the picture in double quotes. Return only the prompt."
    ),
    # huggingface.co/meituan-longcat/LongCat-Image: only text in quotes is
    # drawn letter by letter.
    "longcat": (
        "You write prompts for LongCat Image, an image model that reads its "
        "prompt through a language model. Write a detailed English "
        "description of the finished picture: subject, composition, setting, "
        "light, colours and style. Any text that must appear in the picture "
        "has to stand in double quotes, or it is not drawn as letters. "
        "Return only the prompt."
    ),
    # huggingface.co/circlestone-labs/Anima: Danbooru tags, prose, or both;
    # the quality tags in front, artists with "@".
    "anima": (
        "You write prompts for Anima, an anime image model that reads its "
        "prompt through a language model. Start with \"masterpiece, best "
        "quality, score_7, safe,\" then write lowercase Danbooru tags with "
        "spaces instead of underscores, in this order: the number of people "
        "(such as 1girl), the character, the series, the artist with \"@\" "
        "in front, then the general tags. After the tags you may add one or "
        "two English sentences for what tags cannot say. Return only the "
        "prompt."
    ),
}

ANWEISUNGEN: dict[str, str] = {
    name: _EIGENE.get(name) or _VORLAGE[leser].format(name=image_families.get(name).label)
    for leser, namen in LESER.items()
    for name in namen
}


def leser_von(family: str) -> str | None:
    """The reader a family's text goes through, or None for a family the
    table does not list."""
    for leser, namen in LESER.items():
        if family in namen:
            return leser
    return None


# The negative prompt gets its own, narrower instruction: it is a list of
# things to KEEP OUT of the picture. Translating is wanted, inventing is
# not — an expanded negative would quietly forbid things the user never
# named.
ANWEISUNG_NEGATIV = (
    "You rewrite the NEGATIVE prompt for a Stable-Diffusion image model — "
    "the list of things to avoid in the picture. Translate it to English "
    "and tidy it into concise comma-separated phrases. Stay faithful: do "
    "not add new concepts and do not drop any. Return ONLY the list, with "
    "no preamble, no quotes and no explanation."
)

# Long enough for a rich prompt, short enough that a model which starts
# writing an essay is cut off rather than left running. The generous half of
# that room exists for thinking models whose thinking cannot be switched
# off: their deliberation is counted here too, and a budget that only fits
# the prompt itself would be spent before the prompt is written.
MAX_TOKENS = 600

# A prompt is a prompt, not a document. What arrives longer than this is a
# mistake somewhere upstream, and sending it would cost a full context.
MAX_EINGABE = 2000

# The whole message: the request and the style at most MAX_EINGABE each, the
# trigger words and the note at most as long as a prompt in the picture
# window, and the lines that frame them.
MAX_NACHRICHT = 5 * MAX_EINGABE


class PromptFehler(Exception):
    """The model could not be asked, or said nothing usable."""


def _saeubern(text: str) -> str:
    """Strips what models wrap around an answer they were asked not to wrap.

    Quotes around the whole thing and a trailing full stop are the two that
    survive the instruction most often, and both would be drawn.
    """
    sauber = text.strip()
    # A fenced block first, and as a block: the loop below takes one
    # character off each side, so three backticks would leave two behind and
    # they would be drawn into the picture. The opening fence may carry a
    # language word, which belongs to the fence and not to the prompt.
    if sauber.startswith("```"):
        sauber = sauber[3:]
        if "\n" in sauber:
            erste, rest = sauber.split("\n", 1)
            if not erste.strip() or erste.strip().isalpha():
                sauber = rest
        if sauber.rstrip().endswith("```"):
            sauber = sauber.rstrip()[:-3]
        sauber = sauber.strip()
    for zeichen in ('"', "'", "`"):
        if len(sauber) > 1 and sauber.startswith(zeichen) and sauber.endswith(zeichen):
            sauber = sauber[1:-1].strip()
    return sauber.rstrip(".").strip()


# The facts about the picture model travel in the user's message, not in the
# instruction: the instruction is the job, the same for every request of a
# family, and the facts are what this one request is about. The request
# itself comes last and is marked as what it is, so a style or a note never
# reads as the thing to draw.
FAKT_MODELL = "The picture is drawn with the image model {datei} ({familie})."
FAKT_OHNE_NEGATIV = (
    "This model ignores a negative prompt at its current settings, so keep "
    "everything that must stay out of the picture out of the prompt as well."
)
FAKT_TRIGGER = (
    "This model was trained on these trigger words; include them in the "
    "prompt: {trigger}"
)
FAKT_HINWEIS = "A note the user keeps on this model: {hinweis}"
FAKT_STIL = (
    "The user wants this style for the picture: {stil}. Where the request "
    "below asks for something else, the request wins."
)
FAKT_WUNSCH = "The request to write the prompt for:\n{wunsch}"


def nachricht(
    wunsch: str,
    *,
    datei: str = "",
    familie: str = "",
    negativ_wirkt: bool = True,
    trigger: str = "",
    hinweis: str = "",
    stil: str = "",
) -> str:
    """The user's message to the prompt writer: what is known about the
    picture model, then the request. A fact that is not there is left out
    rather than sent empty, so two requests for the same picture are the
    same message, byte for byte."""
    zeilen: list[str] = []
    if datei:
        zeilen.append(FAKT_MODELL.format(datei=datei, familie=familie or "family not known"))
    if not negativ_wirkt:
        zeilen.append(FAKT_OHNE_NEGATIV)
    if trigger.strip():
        zeilen.append(FAKT_TRIGGER.format(trigger=trigger.strip()))
    if hinweis.strip():
        zeilen.append(FAKT_HINWEIS.format(hinweis=hinweis.strip()))
    if stil.strip():
        zeilen.append(FAKT_STIL.format(stil=stil.strip()))
    zeilen.append(FAKT_WUNSCH.format(wunsch=wunsch.strip()))
    return "\n\n".join(zeilen)


async def verbessern(
    provider: Provider,
    modell: str | None,
    eingabe: str,
    zusatz: dict | None = None,
    anweisung: str = ANWEISUNG_NEGATIV,
) -> str:
    """Asks a language model to write ``eingabe`` over as ``anweisung`` says.

    Streams and collects rather than waiting for a whole response, because
    that is the one way every provider in the house can be asked; the caller
    gets the finished text. ``eingabe`` is the whole user message — for the
    prompt, the facts and the request (:func:`nachricht`); for the negative
    prompt, the avoid-list as it stands.
    """
    eingabe = eingabe.strip()
    if not eingabe:
        raise PromptFehler("empty prompt")
    if len(eingabe) > MAX_NACHRICHT:
        raise PromptFehler("prompt too long")

    anfrage = Generierungsanfrage(
        nachrichten=[
            ChatNachricht(role="system", content=anweisung),
            ChatNachricht(role="user", content=eingabe),
        ],
        modell=modell,
        max_tokens=MAX_TOKENS,
        # Low but not zero: a prompt writer that always returns the same six
        # adjectives stops being useful on the second try.
        temperature=0.7,
        zusatz=zusatz or {},
    )

    stuecke: list[str] = []
    strom = provider.streamen(anfrage)
    # The fold request's two clocks, read by the one loop that knows them
    # (app/faltversuche.read_stream): a server that sends nothing but keepalives,
    # or streams on and on, would otherwise hold this request — and the
    # person waiting for the field — for good. What stays this file's own is
    # the view of an error piece and the words that go with the outcome.
    try:
        # aclosing and not a bare loop: breaking out of it on an error piece
        # leaves the generator suspended at its yield, and an ``async for``
        # does not close it — the stream would stay open until the loop's
        # finalizer gets to it.
        async with contextlib.aclosing(
            faltversuche.read_stream(strom, "image prompt request")
        ) as stuecke_vom_modell:
            async for stueck in stuecke_vom_modell:
                if stueck.sorte == "content":
                    stuecke.append(stueck.text)
                elif stueck.sorte == "error":
                    raise PromptFehler(stueck.text or "model error")
    except faltversuche.Stille as fehler:
        log.warning("%s", fehler)
        raise PromptFehler(str(fehler)) from fehler

    ergebnis = _saeubern("".join(stuecke))
    if not ergebnis:
        # A model that thought until the budget ran out is the common case
        # here, and it is still nothing to put in the field.
        raise PromptFehler("model returned nothing")
    return ergebnis
