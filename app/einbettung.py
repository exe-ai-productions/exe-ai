"""Big documents, without blowing the context.

A hundred-page PDF attached to a chat used to go into every request whole.
That works until it does not: past a certain size the model server refuses,
or worse, silently drops the front of the conversation to make room — and
the answer is then confidently wrong about a document that WAS attached.

So past a threshold the document stops travelling as a block. It is cut
into sections, each section gets a vector, and every question carries only
the handful of sections that actually have to do with it. Below the
threshold nothing changes: a two-page letter is cheaper to send whole than
to search.

**No second server.** The vectors come from llama.cpp's one-shot
``llama-embedding`` — one call per document, the program starts, computes,
prints and is gone. The runner lock in this house says one model server at
a time, and an embedding server running beside the language model would
break it for a job that takes two seconds.

**No numpy.** Cosine similarity over a few thousand sections is a few
thousand multiply-adds, which plain Python does in milliseconds. A
dependency that ships a hundred megabytes of compiled code for that would
have to be carried into every installer on every platform, and the house
rule says the installer decides.
"""

from __future__ import annotations

import json
import logging
import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

from app import serverdownload
from app.no_console import no_window

log = logging.getLogger(__name__)

PROGRAMM = "llama-embedding.exe" if sys.platform == "win32" else "llama-embedding"

# A section is about this many words, and consecutive sections share this
# many. The overlap is what keeps a sentence that straddles a boundary from
# being lost to both sides — the single most common way a search like this
# misses the one paragraph it was built for.
WOERTER = 600
UEBERLAPPUNG = 100

# And never more than this many characters, whatever the word count says.
# The embedding program takes one section as one input line and refuses a
# line past its batch of 2048 tokens; six hundred words of prose are about
# eight hundred tokens, but six hundred "words" of a markdown catalog —
# table rows, paths, code — are not words at all, and one such section was
# measured at 2065 tokens. The program then exits, the whole document goes
# unembedded, and the request falls back to the first 24,000 characters.
# Three thousand characters stay under the batch even at two characters a
# token, the density dense markup reaches.
ZEICHEN = 3_000

# Above one section's worth of characters a document is cut up: a document
# that is a single section has nothing to search in. Below, it always
# travels whole.
SCHWELLE = ZEICHEN

# How many sections ride along with a question. Six is enough for an answer
# to quote across two or three passages and still leave the context room
# for the conversation itself.
MITREISENDE = 6

ZEITGRENZE = 300
# Sections per call of the one-shot program. The time limit above is per
# call, and a document is no longer cut at a storage ceiling on its way in
# — a book of a few hundred thousand characters used to be the most one
# call ever saw, and this keeps every call at that size. A longer document
# takes more calls, in proportion, and no call runs out of time on it.
STAPEL = 128


class EinbettungFehler(Exception):
    """Carries the key of the sentence to show, not the sentence itself."""

    def __init__(self, grund: str) -> None:
        super().__init__(grund)
        self.grund = grund


@dataclass(frozen=True)
class Treffer:
    nummer: int
    text: str
    naehe: float


def programm_finden(datenordner: Path, neben: Path | None = None) -> Path | None:
    """The llama-embedding binary, or nothing if this machine has none.

    Looked for beside the model server first when one is known: the two come
    out of the same package, so a machine that has one almost always has the
    other in the same folder — including the copy this program fetched
    itself, which is on no PATH.
    """
    if neben is not None:
        geschwister = Path(neben).parent / PROGRAMM
        if geschwister.is_file() and os.access(geschwister, os.X_OK):
            return geschwister
    gefunden = shutil.which(PROGRAMM)
    if gefunden:
        return Path(gefunden)
    # The copy this program fetched: out of the folder of the build the
    # model server takes, never out of another build that still lies
    # beside it — the two programs of one run come from one build.
    build = serverdownload.installed_build(datenordner)
    if build is not None:
        folder = Path(datenordner).expanduser() / serverdownload.ORDNER / build
        treffer = sorted(folder.rglob(PROGRAMM))
        if treffer:
            return treffer[0]
    return None


def modelle(ordner: Path) -> list[str]:
    """The embedding models lying in their own folder, by file name."""
    verzeichnis = Path(ordner).expanduser()
    if not verzeichnis.is_dir():
        return []
    return sorted(
        p.name for p in verzeichnis.iterdir() if p.is_file() and p.suffix == ".gguf"
    )


def modell_finden(ordner: Path) -> Path | None:
    """The embedding model to use, or nothing.

    The FOLDER says what a file is — not its name. The first build read the
    name and looked for "embed" in it, which put an embedding model into the
    language model's picker, sent its start against a port that was already
    taken, and pointed "open model folder" at the wrong folder. A file lying
    in the embedding folder is an embedding model, and nothing else has to
    be guessed.
    """
    gefunden = modelle(ordner)
    return Path(ordner).expanduser() / gefunden[0] if gefunden else None


def zerlegen(
    text: str,
    woerter: int = WOERTER,
    ueberlappung: int = UEBERLAPPUNG,
    zeichen: int = ZEICHEN,
) -> list[str]:
    """Cut a document into overlapping sections.

    Deterministic on purpose: the same document must give the same sections
    every time, or a stored vector would stop belonging to the text it was
    computed from.

    A section is ``woerter`` words long — or fewer, where that many words
    would run past ``zeichen`` characters: the character cap is what keeps
    a section inside the embedding program's batch (see ``ZEICHEN``). A
    single word longer than the cap still becomes a section of its own;
    it cannot be cut, and one such word does not happen in a document.

    Newlines come out. One section is ONE line for the embedding program,
    which reads its inputs line by line — a section that kept its paragraph
    breaks would arrive as several unrelated inputs.
    """
    if ueberlappung >= woerter:
        raise ValueError("Überlappung muss kleiner als die Abschnittslänge sein")
    stuecke = (text or "").split()
    if not stuecke:
        return []
    abschnitte: list[str] = []
    start = 0
    while start < len(stuecke):
        # As many words as fit under both caps, and at least one.
        laenge = 0
        genommen = 0
        for wort in stuecke[start : start + woerter]:
            zuwachs = len(wort) + (1 if genommen else 0)
            if genommen and laenge + zuwachs > zeichen:
                break
            laenge += zuwachs
            genommen += 1
        abschnitte.append(" ".join(stuecke[start : start + genommen]))
        # The last section is whatever is left. Without this the loop would
        # append an extra section made entirely of overlap.
        if start + genommen >= len(stuecke):
            break
        # The overlap SCALES with the section instead of merely shrinking
        # to fit it. `genommen - min(ueberlappung, genommen - 1)` kept the
        # full overlap as long as one word of progress remained — so a
        # section the character cap trimmed below the overlap length
        # stepped one single word: a 205 KB document of 40-character words
        # became 4,928 near-identical sections instead of ten, and the
        # search returned the same passage six times. The overlap is a
        # RATIO (100 of 600 words); a capped section keeps the ratio, not
        # the absolute count. The uncapped case is unchanged: genommen ==
        # woerter gives exactly the old step.
        start += max(1, genommen - min(ueberlappung, genommen * ueberlappung // woerter))
    return abschnitte


def kosinus(a: list[float], b: list[float]) -> float:
    """How close two vectors point. 1 is the same direction, 0 unrelated."""
    if not a or not b or len(a) != len(b):
        return 0.0
    punkt = betrag_a = betrag_b = 0.0
    for x, y in zip(a, b, strict=True):
        punkt += x * y
        betrag_a += x * x
        betrag_b += y * y
    if betrag_a <= 0 or betrag_b <= 0:
        return 0.0
    return punkt / math.sqrt(betrag_a * betrag_b)


def packen(vektor: list[float]) -> bytes:
    """A vector as a blob. Single precision: the seventh decimal place of a
    similarity score has never decided which paragraph was the right one,
    and half the bytes is half the database."""
    return struct.pack(f"<{len(vektor)}f", *vektor)


def entpacken(rohdaten: bytes) -> list[float]:
    return list(struct.unpack(f"<{len(rohdaten) // 4}f", rohdaten))


# One embedding run at a time, for the same reason the picture generator has
# one: the program loads a model of its own, and two of them beside the
# language model share one pool of memory. Two large uploads arriving
# together would otherwise start two loads at once.
_SCHLOSS = threading.Lock()


def vektoren(programm: Path, modell: Path, abschnitte: list[str]) -> list[list[float]]:
    """One call for the whole batch. Returns one vector per section.

    The sections go through a file rather than the command line: a hundred
    sections of six hundred words each is far past any shell's limit, and a
    temporary file has no such ceiling.
    """
    if not abschnitte:
        return []
    with _SCHLOSS:
        return _rechnen(programm, modell, abschnitte)


def _rechnen(programm: Path, modell: Path, abschnitte: list[str]) -> list[list[float]]:
    with tempfile.NamedTemporaryFile(
        "w", suffix=".txt", delete=False, encoding="utf-8"
    ) as datei:
        # One section per line — that is how the program separates inputs.
        datei.write("\n".join(a.replace("\n", " ") for a in abschnitte))
        pfad = Path(datei.name)
    try:
        lauf = subprocess.run(
            [
                str(programm),
                "-m", str(modell),
                "-f", str(pfad),
                "--embd-output-format", "array",
                # Mean pooling: one vector for a whole section, which is what
                # a section IS here. Without it the program answers per token
                # and there is nothing to compare.
                "--pooling", "mean",
            ],
            capture_output=True,
            text=True,
            # The program writes UTF-8 whatever the system's own code page is.
            encoding="utf-8",
            errors="replace",
            timeout=ZEITGRENZE,
            **no_window(),
        )
    except subprocess.TimeoutExpired as fehler:
        raise EinbettungFehler("einbettung.zeit_abgelaufen") from fehler
    except OSError as fehler:
        raise EinbettungFehler("einbettung.kein_programm") from fehler
    finally:
        pfad.unlink(missing_ok=True)
    if lauf.returncode != 0:
        log.warning("Embedding failed (%s): %s", lauf.returncode, lauf.stderr[-500:])
        raise EinbettungFehler("einbettung.gescheitert")
    try:
        gelesen = json.loads(lauf.stdout)
    except json.JSONDecodeError as fehler:
        raise EinbettungFehler("einbettung.gescheitert") from fehler
    if len(gelesen) != len(abschnitte):
        # A mismatch means the sections and the vectors no longer line up,
        # and a wrong pairing is worse than no search at all.
        log.warning("Embedding: %d vectors for %d sections", len(gelesen), len(abschnitte))
        raise EinbettungFehler("einbettung.gescheitert")
    return [[float(z) for z in vektor] for vektor in gelesen]


def naechste(
    frage: list[float],
    gespeichert: list[tuple[int, str, list[float]]],
    anzahl: int = MITREISENDE,
) -> list[Treffer]:
    """The sections closest to a question, best first.

    Only sections that actually point somewhere come back. A vector of a
    different length scores 0.0 — and so does one that genuinely has nothing
    to do with the question. Sorting a list of zeros is still sorting: it
    leaves the sections in the order they were inserted, which is document
    order, so the first few sections of the file would come back looking
    exactly like an answer.

    Nothing found is a real answer here and a safe one: the caller reads an
    empty list as "no selection" and sends the whole document instead.
    """
    if not frage:
        return []
    bewertet = [
        treffer
        for treffer in (
            Treffer(nummer=nummer, text=text, naehe=kosinus(frage, vektor))
            for nummer, text, vektor in gespeichert
            if len(vektor) == len(frage)
        )
        if treffer.naehe > 0
    ]
    bewertet.sort(key=lambda t: t.naehe, reverse=True)
    return bewertet[:anzahl]


def als_kontext(dateiname: str, treffer: list[Treffer]) -> str:
    """The sections, written so the model can cite where it read something.

    Every section says which document and which number it came from. A
    model that quotes "from report.pdf, section 12" can be checked; one that
    quotes a floating paragraph cannot.
    """
    if not treffer:
        return ""
    teile = [f'[From "{dateiname}", the passages that fit the question]']
    for eintrag in treffer:
        teile.append(f"[{dateiname}, section {eintrag.nummer}]\n{eintrag.text}")
    teile.append("[End of passages]")
    return "\n\n".join(teile)
