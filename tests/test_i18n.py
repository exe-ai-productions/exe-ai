"""Internationalization: catalog upkeep and fallback behavior."""

from __future__ import annotations

import json
import re
from functools import lru_cache

from app.i18n import (
    LOCALES_VERZEICHNIS,
    STANDARDSPRACHE,
    _nachschlagen,
    t,
    verfuegbare_sprachen,
)


def _schluessel_sammeln(knoten, praefix=""):
    for name, wert in knoten.items():
        pfad = f"{praefix}{name}"
        if isinstance(wert, dict):
            yield from _schluessel_sammeln(wert, f"{pfad}.")
        else:
            yield pfad


def test_deutsch_und_englisch_vorhanden():
    assert set(verfuegbare_sprachen()) >= {"de", "en"}


def test_kataloge_haben_dieselben_schluessel():
    """A text that exists in only one language is an error."""
    kataloge = {
        sprache: json.loads((LOCALES_VERZEICHNIS / f"{sprache}.json").read_text("utf-8"))
        for sprache in verfuegbare_sprachen()
    }
    referenz = set(_schluessel_sammeln(kataloge[STANDARDSPRACHE]))
    for sprache, katalog in kataloge.items():
        assert set(_schluessel_sammeln(katalog)) == referenz, f"Abweichung in {sprache}.json"


def test_die_toten_schluessel_sind_weg():
    """Six keys nobody read any more, out of both catalogues at once.

    They named the editor's groups by an older set of names, a model field
    that no longer exists and two words for a setting that follows the
    device. Nothing in `frontend/` or `app/` reached any of them — measured
    key by key over the whole tree, and the group list in
    frontend/src/teile/SystemPrompt.svelte is a fixed five-entry array.

    Names ARE built at runtime there (`meldeschluessel`, SystemPrompt.svelte
    :491-501, ends with `editor.${fall}`), so a static search is not the
    whole answer for this prefix: `fall` takes exactly two values,
    'nicht_geladen' and 'nicht_gesichert', and neither is a group. Anything
    removed under `editor.` has to be checked against those two by hand —
    `editor.nicht_geladen` exists and is reached ONLY through that built
    name.

    A key removed from only one language is a new defect, so the test asks
    both. And it asks the other way round too: the five groups the editor
    really shows have to stay — a sweep that took one of them with it would
    leave a heading blank on screen.
    """
    kataloge = {
        sprache: json.loads((LOCALES_VERZEICHNIS / f"{sprache}.json").read_text("utf-8"))
        for sprache in ("de", "en")
    }
    tot = {
        "editor.gruppe_app",
        "editor.gruppe_agents",
        "editor.gruppe_tools",
        "agenten.modell_frei",
        "editor.folgt_geraet",
        "editor.fest_gewaehlt",
    }
    lebt = {
        "editor.gruppe_general",
        "editor.gruppe_verhalten",
        "editor.gruppe_prompts",
        "editor.gruppe_verbindungen",
        "editor.gruppe_dateien",
    }
    for sprache, katalog in kataloge.items():
        vorhanden = set(_schluessel_sammeln(katalog))
        assert not (tot & vorhanden), f"still there in {sprache}.json: {sorted(tot & vorhanden)}"
        assert lebt <= vorhanden, f"missing in {sprache}.json: {sorted(lebt - vorhanden)}"


def test_kein_text_steht_unuebersetzt_in_beiden_katalogen():
    """The same wording in both files usually means one was copied and never
    translated — that is how two English sentences ended up in the German
    catalogue and stood there unnoticed.

    Some words really are the same in both languages. They are named here, one
    by one, so the list stays an argument and not a hiding place.
    """
    gleich_erlaubt = {
        # Proper names and marks.
        "app.ok",
        # A number with a percent sign is written the same in both languages.
        "bild.fortschritt_prozent",
        # Bare step marks — plus or minus one is no language at all.
        "bild.seed_plus", "bild.seed_minus",
        # Accessory kinds — VAE, LoRA, ADetailer and Vision (mmproj) are
        # technical names, the same word in both languages.
        "katalog.sorte_vae", "katalog.sorte_lora", "katalog.sorte_adetailer",
        "katalog.sorte_mmproj",
        # A port is a port in both languages.
        "kopf.port",
        # The words printed on two keys, the same on a German keyboard as on
        # an English one. The other two modifier keys ARE named differently.
        "shortcuts.key_alt", "shortcuts.key_win",
        # "8-Bit" is a unit, written the same in both languages.
        "modell.feld_kv_wert",
        # "Version" is the same word in both languages; only the build tag
        # behind it changes.
        "bildserver.version_zeile",
        # The same word again, before the program's own version number.
        "updates.version",
        # Memory Lock is what the flag is called, in both languages.
        "modell.feld_mlock",
        # The engine's own sampling knobs keep their flag names, the same
        # word in both languages, like the VAE kinds above.
        "sprachserver.feld_top_k", "sprachserver.feld_top_p",
        "sprachserver.feld_min_p",
        # "Auto" is the same word in both languages.
        "modell.faeden_auto",
        # Hindi is spelled the same in both languages. The other seventeen
        # dictation languages are not, which is what makes this one entry
        # an exception rather than a hole.
        "sprache.name_hi",
        # Embeddings, VAE and ADetailer are called that in both languages —
        # technical names of the file kinds, not words to translate.
        "bild.embedding", "bild.vae", "bild.adetailer",
        # PuLID and ControlNet are method names, the same word in both
        # languages, like ADetailer above.
        "bild.pulid", "bild.control_net",
        # "Video" is the same word in both languages.
        "bild.medium_video",
        # Words English and German share unchanged.
        "downloads.titel",
        # The fetch button of the model-server row says the same word in
        # both languages.
        "modell.server_download",
        "menue.chat", "menue.cloud", "jobs.bereich_chats",
        # "Cloud" is the same word in both languages, the same reason as
        # menue.cloud above — this is the Improve window's own copy of it,
        # a separate key because each field owns its own text.
        "modell.cloud",
        "werkzeuge.eingebaut",
        # The names of the kinds of tool that are a product or a tool's own
        # name in both languages.
        "werkzeug.art_web", "werkzeug.art_terminal", "werkzeug.art_github", "werkzeug.art_gmail",
        "editor.gruppe_prompts", "jobs.agent_waehlen",
        # The first of a schedule's three kinds — "Agent", the same word in
        # both languages, like the field above.
        "cronjobs.kind_agent",
        # Whose files the doc folder shows — "Agent" again, and the dock,
        # which is called "Dock" in both languages.
        "docfolder.origin_agent", "werkzeuge.quelle_dock",
        # A reminder's field: its text — "Text" in both languages.
        "cronjobs.field_text",
        "einstellungen.auto", "parameter.aus_global", "bild.clip_auto",
        # The one word every field with nothing set shows, in every window
        # that has such a field. "Auto" is the same word in both languages,
        # like the entries above and below it.
        "parameter.auto",
        # The name of the smallest thinking depth. Both languages spell it
        # the same way, and every other stage of the scale IS translated —
        # so this one entry is a coincidence of spelling, not a forgotten
        # line.
        "denken.stufe.minimal",
        # Language names stand in their own language, on purpose.
        "einstellungen.sprache_deutsch", "einstellungen.sprache_englisch",
        # Pure units and placeholders.
        "werkzeug.laeuft",
        # The three words under an answer are the line's labels, and the
        # line is built this way on purpose: the number is what one reads,
        # the word only says what it is. TPS, TTFT and Cache are units and a
        # name of the thing, spelled the same in both languages (like "GB"), and
        # they stand here so the next reader sees the reason instead of a
        # red suite.
        "nachricht.tps", "nachricht.ttft", "nachricht.cache",
        # "Skill" is the name of the thing, in both languages. Translating it
        # would invent a German word nobody types into the slash list.
        "skills.quelle",
        # VRAM is the label on graphics memory in both languages — a German
        # spelling of it does not exist outside dictionaries.
        "modell.vram_label",
        # Seconds and milliseconds are written the same way in both
        # languages; the entry is a number with a unit, not a sentence.
        "terminal.dauer", "werkzeug.dauer",
        "terminal.dauer_ms", "werkzeug.dauer_ms",
        # A port is a port in both languages, exactly as it already is in
        # the model server's own form.
        "einbettungsserver.port",
        # The catalogue chip names the same graphics memory as the local
        # window, so it carries the same untranslatable label.
        "katalog.maschine",
        # "Chat" is the German word for chat as much as the English one —
        # one of the three catalogue tab names, and the only one of the
        # three that happens to be spelled the same in both languages.
        "katalog.art_chat",
        # A network port is called a port in German too. "Anschluss" is the
        # dictionary answer and not what anybody says or reads.
        "modell.feld_port",
        # The generator's own vocabulary. Sampler, scheduler and LoRA are
        # what the picture world calls these things in German as well —
        # translating them would name controls nobody could look up, and the
        # values inside them stay English either way.
        "bild.sampler", "bild.scheduler", "bild.lora",
        # "Prompt" is the word German speakers already type and read for it —
        # the existing prompt fields spell it out the same way ("Positiver
        # Prompt"). "Upscaling" is the same case: the German rendering of it
        # is the English one, same as Skill or VRAM above.
        "bild.gruppe_prompt", "bild.gruppe_upscaling",
        # sd-cli's own flag values (--lora-apply-mode) — the German
        # rendering of a command-line value is the value itself, same as
        # Sampler/Scheduler/LoRA above.
        "bild.lora_modus_at_runtime", "bild.lora_modus_auto",
        # sd-cli's own --vae-format values, and a plain digit — a format
        # name (Flux, SD3, Flux.2) does not translate, and "2" reads the
        # same in both languages.
        "bild.vae_format_auto", "bild.vae_format_flux", "bild.vae_format_sd3",
        "bild.vae_format_flux2", "bild.clip_skip_1", "bild.clip_skip_2",
        # "CFG" and "RNG" are the technical abbreviations themselves,
        # written the same way in both languages -- not text to translate.
        "bild.cfg",
        # RNG is an acronym (same category as VRAM/CFG above); its two
        # values name the ecosystem convention they mimic, not a German
        # word; the weight-type names are sd-cli's own, and "Auto" repeats
        # the same accepted word as clip_auto/vae_format_auto. "Threads" is
        # the word German tech speech itself uses, same as "downloaded"
        # above.
        "bild.rng", "bild.rng_cuda", "bild.rng_cpu", "bild.weight_type_auto",
        "bild.weight_type_f16", "bild.weight_type_q8_0", "bild.weight_type_q4_k",
        "bild.threads", "bild.vram_limit_platzhalter",
        # Eta is the Greek letter's name in both languages; "auto" repeats
        # the accepted placeholder word from vram_limit_platzhalter above —
        # all three fields borrow sd-cli's own "the program decides".
        "bild.eta", "bild.eta_platzhalter", "bild.flow_shift_platzhalter",
        "bild.ad_confidence_platzhalter",
        # --prediction is the generator's own vocabulary (its values are
        # eps/v/edm_v/…), same category as Sampler/Scheduler above; "Auto"
        # repeats the accepted word, and LLM is an acronym like RNG/VRAM.
        "bild.prediction", "bild.prediction_auto", "bild.llm",
        # "Guidance" is sd-cli's own name for this dial and the word the
        # window was asked to carry, not a phrase to translate.
        "bild.guidance",
        # "Vision" is what both communities call a model that sees; only the
        # capital letter differs and the comparison is case-sensitive anyway.
        "modell.augen",
        # "Name" is the same word in both languages, and an example address
        # is a literal — translating either would only invent a difference.
        "modell.eigener_name", "modell.eigener_adresse_beispiel",
        # MTP is the acronym for the prediction module in both languages,
        # and Hugging Face is a product name — neither is translated.
        "modell.mtp_label", "editor.quelle_hf",
        # "Terminal" is the same word in both languages, and it is the name
        # of the thing the program is.
        "terminal.titel",
        # The names of the colour packs. Eight are the names their authors
        # gave them, and "Exe" is ours — none of the nine is translated.
        "einstellungen.codefarben_exe",
        "einstellungen.codefarben_tokyo",
        "einstellungen.codefarben_onelight",
        "einstellungen.codefarben_github",
        "einstellungen.codefarben_githubdark",
        "einstellungen.codefarben_dracula",
        "einstellungen.codefarben_nord",
        "einstellungen.codefarben_solarizedlight",
        "einstellungen.codefarben_solarizeddark",
        # The skins carry proper names now — Pearl, Exe, Dark Matter,
        # Heaven, Moune — kept the same in both languages, like the colour
        # packs above.
        "einstellungen.hell", "einstellungen.dunkel",
        "einstellungen.darkmatter", "einstellungen.heaven",
        "einstellungen.moune",
        # CLI is the name of the panel in both languages, and "Chat" is the
        # same word — the status line names both.
        "cli.titel", "cli.status_chat",
        # "Auto" is the same word in both languages (see einstellungen.auto
        # above). "Manual" and "Restricted" are translated ("Manuell",
        # "Eingeschränkt"), so neither is listed here.
        "berechtigungen.modus_auto",
        "bild.split_mode_auto",
        "bild.art_auto",
        # "Cronjobs" is the module's own name in both languages — the
        # dictionary word ("Zeitpläne") is not what the interface calls it.
        # The source label names that same module, so it wears the same word.
        "cronjobs.titel",
        "cronjobs.quelle",
        # "Denoise" is the name the image models themselves print for this
        # dial, and every workflow and manual uses it in both languages — a
        # German second wording would name a thing that already has a name.
        "bild.staerke",
        # `exit 1` is what the shell says, not a sentence about it. It is
        # the word every terminal, every CI log and every manual page uses,
        # in every language — a German "Beendigungscode 1" would be a term
        # this house invented for a thing that already has a name.
        "werkzeug.exit",
        # "Sandboxed" is what an agent held to its shared folders IS, and the
        # word is the same one in both languages — it travelled into German
        # whole, the way "Container" and "Backup" did. A translation would
        # have to invent a second name for a thing that already has one.
        "berechtigungen.modus_agent_manuell",
        # The MCP sheet's own vocabulary: "URL" is the acronym itself, same
        # category as "kopf.port" above; "Tools" is the heading the approved
        # preview drew in both languages, like "Skill" or "Prompt"; "online"
        # is the plain status word every protocol calls it; and a bare count
        # with "tools" after it is a unit, like "bild.fortschritt_prozent".
        "mcp.url", "mcp.tools_titel", "mcp.online", "mcp.tools_zahl",
        # The server windows' start button: "Start" is the German word as
        # much as the English one.
        "modell.server_starten",
        # A count of chosen models out of offered ones, "2/23": two numbers
        # and a stroke read the same in every language.
        "modell.von_zahl",
        # The label over an agent's name: "Name" is the German word too.
        "agenten.name",
    }

    def flach(knoten, praefix=""):
        for name, wert in knoten.items():
            pfad = f"{praefix}{name}"
            if isinstance(wert, dict):
                yield from flach(wert, f"{pfad}.")
            else:
                yield pfad, wert

    de = dict(flach(json.loads((LOCALES_VERZEICHNIS / "de.json").read_text("utf-8"))))
    en = dict(flach(json.loads((LOCALES_VERZEICHNIS / "en.json").read_text("utf-8"))))

    verdaechtig = sorted(
        schluessel
        for schluessel, text in de.items()
        if schluessel not in gleich_erlaubt and en.get(schluessel) == text
    )
    assert not verdaechtig, (
        "Same text in both catalogues — probably not translated: "
        + ", ".join(verdaechtig)
    )


def test_uebersetzung_je_sprache():
    assert t("chat.neu", "de") == "Neuer Chat"
    assert t("chat.neu", "en") == "New chat"


def test_platzhalter_werden_gesetzt():
    text = t("fehler.modell_nicht_erreichbar", "de", name="Mana")
    assert "Mana" in text


def test_die_notfallnaht_nennt_den_grund_und_die_anzahl():
    """The seam over an emergency compaction says what kind it was FIRST and
    how many messages it speaks for after it — word for word, in both
    languages. The count matters more here than over an ordinary fold, not
    less: the summary under it was assembled mechanically."""
    assert (
        t("nachricht.verdichtet_notfall", "de", anzahl=7)
        == "Notfall-Komprimierung · 7 Nachrichten"
    )
    assert (
        t("nachricht.verdichtet_notfall", "en", anzahl=7)
        == "Emergency compression · 7 messages"
    )
    # And the wording without a count stays exactly as it was — it is what
    # stands where no count is known.
    assert t("nachricht.verdichtet_notfall_ohne_zahl", "de") == "Notfall-Komprimierung"
    assert t("nachricht.verdichtet_notfall_ohne_zahl", "en") == "Emergency compression"


def test_unbekannte_sprache_faellt_zurueck():
    assert t("chat.neu", "fr") == t("chat.neu", STANDARDSPRACHE)


def test_unbekannter_schluessel_gibt_schluessel_zurueck():
    assert t("gibt.es.nicht", "de") == "gibt.es.nicht"


def test_fehlender_platzhalter_stuerzt_nicht_ab():
    # No crash — just the unchanged text.
    assert "{" in t("kontext.auslastung", "de")


def test_die_wartewoerter_stehen_im_katalog_und_sind_uebersetzt():
    """The words the live mark shows while it waits.

    They used to stand in the window's own file, in English for every
    language, with a comment saying that was on purpose. It is not any more:
    these are words a person reads while they wait, and a German window says
    them in German.

    Checked here rather than in the window, because the catalogue is what the
    window now reads — and because the one thing that could go wrong quietly
    is exactly a catalogue thing: ten keys in one language and nine in the
    other, or the German list still holding the English words.

    Every locale on disk, like the key-parity test above: a language added
    later has to bring the words with it, and a check that names two of them
    would be silent about the third.
    """
    kataloge = {
        sprache: json.loads(
            (LOCALES_VERZEICHNIS / f"{sprache}.json").read_text("utf-8")
        )
        for sprache in verfuegbare_sprachen()
    }
    for sprache, katalog in kataloge.items():
        assert "wartewort" in katalog, sprache
        # Ten is the chosen count. The window reads however many are here,
        # so this number pins the catalogue and is not a limit of the code.
        assert len(katalog["wartewort"]) == 10, sprache
        # Plain numbers, in order: that IS the order the window reads them in,
        # because an object's integer-like keys are walked ascending.
        assert list(katalog["wartewort"]) == [str(n) for n in range(1, 11)], sprache

    deutsch = list(kataloge["de"]["wartewort"].values())
    englisch = list(kataloge["en"]["wartewort"].values())
    # Each one really translated, not one row copied over and forgotten. Row
    # by row rather than list against list: two lists can differ in one place
    # and still hold eight untranslated rows.
    paare = zip(deutsch, englisch, strict=True)
    for nummer, (links, rechts) in enumerate(paare, start=1):
        assert links != rechts, nummer
    # The English list is the one that was already there, word for word.
    assert englisch[0] == "Turning it over"
    assert englisch[-1] == "Getting there"
    # And the three spellings that were corrected on the way in.
    assert "Legt sich Zahlen zurecht" in deutsch
    assert "Sortiert die Dateien" in deutsch
    assert "Ist gleich so weit" in deutsch
    # All ten start with a capital, like the English ones.
    assert all(wort[:1] == wort[:1].upper() for wort in deutsch)


# --- The six server names, spelled one way --------------------------------
#
# Two of the five once carried a hyphen and three did not, and in the server
# bar all five stand under one another. All five carry it now, and the sixth
# arrived with it. The English side is untouched — it has been two plain
# words all along.

# The model server is the one without a `titel` of its own — its name sits in
# `modell.server`, where the window reads it from.
SERVERNAMEN = (("modell", "server"), ("agentserver", "titel"),
               ("einbettungsserver", "titel"), ("sprachserver", "titel"),
               ("bereinigungsserver", "titel"), ("bildserver", "titel"))


def _katalog(sprache):
    return json.loads((LOCALES_VERZEICHNIS / f"{sprache}.json").read_text("utf-8"))


def _servernamen(sprache):
    katalog = _katalog(sprache)
    return [katalog[bereich][schluessel] for bereich, schluessel in SERVERNAMEN]


def test_die_sechs_servernamen_tragen_alle_den_bindestrich():
    namen = _servernamen("de")

    assert namen == [
        "Modell-Server",
        "Agenten-Server",
        "Einbettungs-Server",
        "Sprach-Server",
        "Bereinigungs-Server",
        "Bild-Server",
    ], namen


def test_kein_servername_ohne_bindestrich_im_deutschen_katalog():
    """The four mentions in running text travel with the names. Read from the
    whole file rather than from single keys: a seventh mention somewhere else
    would be the same inconsistency again."""
    roh = (LOCALES_VERZEICHNIS / "de.json").read_text("utf-8")

    # All six, not only the three that moved: a later mention of the ones
    # that were already right would bring the same mixed bar back.
    for wort in ("Modellserver", "Agentserver", "Agentenserver",
                 "Sprachserver", "Bereinigungsserver", "Bildserver",
                 "Einbettungsserver"):
        assert wort not in roh, wort


def test_das_englische_bleibt_bei_den_servernamen_wie_es_war():
    """The silence check: English was already consistent as two plain words,
    so nothing there moves."""
    namen = _servernamen("en")

    assert namen == [
        "Model server",
        "Agent server",
        "Embedding server",
        "Speech server",
        "Clean-up server",
        "Image server",
    ], namen


def test_schnellwahl_titel_traegt_dasselbe_wort_wie_aktiv_zahl():
    """The rail heading and the count sentence under it name the same list —
    the order's own instruction was to reuse the word
    ``modell.aktiv_zahl`` already carries, not to invent a second one."""
    for sprache, wort in (("de", "Schnellwahl"), ("en", "quick picker")):
        katalog = json.loads((LOCALES_VERZEICHNIS / f"{sprache}.json").read_text("utf-8"))
        titel = katalog["modell"]["schnellwahl_titel"]
        aktiv_zahl = katalog["modell"]["aktiv_zahl"]
        assert titel.lower() == wort.lower()
        assert wort.lower() in aktiv_zahl.lower()


def test_kein_katalog_nennt_einen_abschnitt_der_nicht_existiert():
    """One sentence sent the user to "Your Local Models" — a heading that
    exists in neither catalogue nor anywhere in the frontend. The section
    above the server tiles is `modell.einrichten` ("Server" / "Servers",
    frontend/src/teile/ModelleLokal.svelte:245)."""
    for sprache in ("de", "en"):
        roh = (LOCALES_VERZEICHNIS / f"{sprache}.json").read_text("utf-8")
        assert "Your Local Models" not in roh, sprache


# --- The catalogue's speech heading -----------------------------------------


def test_die_katalogrubrik_heisst_sprache():
    """"Spracherkennung" was narrower than the English "Speech" and narrower
    than the card lying in it: Voxtral 3B writes speech down AND answers it."""
    assert _katalog("de")["katalog"]["art_sprache"] == "Sprache"


def test_die_uebrigen_katalogrubriken_stehen_unveraendert():
    """The silence check on the other four."""
    katalog = _katalog("de")["katalog"]

    assert katalog["art_chat"] == "Chat"
    assert katalog["art_einbettung"] == "Einbettung"
    assert katalog["art_bild"] == "Bild"
    assert katalog["art_zubehoer"] == "Zubehör"


# --- The built-in sources and their sentences ------------------------------


def _eingebaute_zeilen() -> list[dict]:
    """What the registry itself reports as built by this program.

    Asked of the registry and not counted by hand: a tool that comes or goes
    moves this list with it, and `uebersicht()` marks every row it builds
    itself as `builtin` (app/tools/registry.py:803 — "A new row added here
    is therefore a built-in without anyone having to remember it"). Every
    switch is on, so nothing is missing from the list.
    """
    from pathlib import Path

    from app.tools.registry import WerkzeugRegistry

    registry = WerkzeugRegistry(
        [],
        shell_an=True,
        memory_pfad=Path("/tmp"),
        skills_orte=(Path("/tmp"), Path("/tmp")),
        bild_zugang=("http://127.0.0.1:1", Path("/tmp"), "x"),
        cronjobs_repo=object(),
        agenten_orte=(Path("/tmp"),),
        agentendock=object(),
    )
    return [zeile for zeile in registry.uebersicht() if zeile.get("builtin")]


@lru_cache(maxsize=1)
def _quellenwoerter() -> dict[str, str]:
    """The catalogue key the window uses for each built-in source.

    Read once out of the window's own table — that file decides what is on
    screen, and a second list here would be a copy that can only fall behind
    it. The map ends on a `}` of its own, so the cut is at the line and not
    at the first brace anywhere (a brace in prose would truncate that).
    """
    datei = LOCALES_VERZEICHNIS.parent.parent / "frontend" / "src" / "lib" / "werkzeuge.svelte.js"
    text = datei.read_text("utf-8")
    block = text.split("export const EINGEBAUTE_NAMEN = {", 1)[1].split("\n}", 1)[0]
    return dict(re.findall(r"""(\w+):\s*'([^']+)'""", block))


def _quelle_wort(kennung: str) -> str:
    woerter = _quellenwoerter()
    if kennung not in woerter:
        raise AssertionError(f"no word for the built-in source {kennung!r}")
    return woerter[kennung]


def test_jede_eingebaute_quelle_traegt_ihr_eigenes_wort():
    """A source of this program is named by the catalogue, never by its
    server name.

    One server may be called like a built-in source — a server called
    "clock" beside the built-in clock — and two rows of the same name cannot
    be told apart on screen (`quellen()`, frontend/src/lib/werkzeuge.svelte.js,
    keeps the two apart by `builtin`, which is what makes this word the only
    thing left that differs).

    So every built-in source of the registry has a word, no two of the words
    that reach the screen are the same, and the three that had one keep it.
    """
    quellen = sorted({zeile["server"] for zeile in _eingebaute_zeilen()})
    for kennung in quellen:
        schluessel = _quelle_wort(kennung)
        for sprache in verfuegbare_sprachen():
            wert = _nachschlagen(_katalog(sprache), schluessel)
            assert wert, f"{sprache}: {kennung} -> {schluessel}"

    # The words that reach the screen and not the keys: two keys are always
    # different, two labels need not be.
    for sprache in verfuegbare_sprachen():
        woerter = [
            _nachschlagen(_katalog(sprache), _quelle_wort(kennung)) for kennung in quellen
        ]
        assert len(set(woerter)) == len(woerter), (sprache, woerter)

    # The silence check: the three words that were already there stay, in
    # both languages — the English side is on screen for an English window.
    for sprache, erwartet in (
        ("de", {"shell": "Terminal", "memory": "Gedächtnis", "skills": "Skills"}),
        ("en", {"shell": "Terminal", "memory": "Memory", "skills": "Skills"}),
    ):
        for kennung, wort in erwartet.items():
            assert _nachschlagen(_katalog(sprache), _quelle_wort(kennung)) == wort, (
                sprache,
                kennung,
            )


def test_jedes_eingebaute_werkzeug_hat_einen_satz():
    """Every built-in tool is explained in the window, in every language.

    The window shows `werkzeuge.eingebaut_satz.<name>` under each tool's name
    (frontend/src/teile/Werkzeuge.svelte:264). Two tools had no sentence, so
    their rows showed the key itself — `werkzeuge.eingebaut_satz.goal` — to
    whoever opened them. A key the code reads and a catalogue lacks is the
    `totalAbsent` i18next-cli fails on.
    """
    namen = sorted({zeile["name"] for zeile in _eingebaute_zeilen()})
    for sprache in verfuegbare_sprachen():
        saetze = _katalog(sprache)["werkzeuge"]["eingebaut_satz"]
        fehlend = [name for name in namen if not saetze.get(name)]
        assert not fehlend, f"{sprache}: {fehlend}"

    # The silence check: the sixteen sentences that were there, word for word
    # in German (the language the wording is written in) and complete in
    # English. A dictionary and not a checksum: a failure has to name the
    # sentence that moved.
    bestand = {
        "run_command": "Führt Shell-Befehle auf diesem Rechner aus — Programme, Skripte, Dateien verschieben und umbenennen.",
        "ask_user": "Fragt dich, wenn eine Entscheidung wirklich deine ist.",
        "memory_save": "Merkt sich etwas über dich oder dein Projekt, über Gespräche hinweg.",
        "read_file": "Liest den Inhalt einer Textdatei.",
        "write_file": "Schreibt Text in eine Datei, legt sie bei Bedarf neu an.",
        "edit_file": "Ersetzt eine genau passende Stelle in einer Textdatei.",
        "list_dir": "Listet auf, was in einem Ordner liegt.",
        "skill_load": "Lädt eine festgehaltene Anleitung für eine Art von Arbeit.",
        "skill_save": "Schreibt eine Arbeitsweise auf, damit sie später wieder geladen werden kann.",
        "cronjob": "Richtet einmalige oder wiederkehrende Erinnerungen ein, die eine Aufgabe zu fester Zeit auslösen.",
        "draw_image": "Zeichnet ein Bild mit dem lokalen Bildmodell.",
        "deliver_file": "Legt eine fertige Datei im Dock ab, wo du sie abholst.",
        "start_job": "Übergibt Arbeit an einen Agenten, der sie im Hintergrund erledigt und einen Bericht hinterlässt.",
        "search_files": "Durchsucht die freigegebenen Ordner nach Text und nennt jede Zeile, in der er vorkommt.",
        "create_folder": "Legt einen Ordner an und gibt ihn als Arbeitsordner für diesen Chat frei.",
        "get_current_time": "Liest die aktuelle Uhrzeit, den Wochentag und die Zeitzone.",
    }
    saetze_de = _katalog("de")["werkzeuge"]["eingebaut_satz"]
    for name, satz in bestand.items():
        assert saetze_de[name] == satz, name
    # The other languages have to carry the sixteen too (empty is a row
    # without a sentence, and the standard language is English).
    for sprache in verfuegbare_sprachen():
        if sprache == "de":
            continue
        saetze = _katalog(sprache)["werkzeuge"]["eingebaut_satz"]
        for name in bestand:
            assert saetze[name].strip(), f"{sprache}: {name}"
