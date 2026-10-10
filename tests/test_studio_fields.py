"""Field logic of the picture studio: what its right column offers
(`frontend/src/teile/Studio*.svelte`) and what a run sends
(`frontend/src/lib/studiozeichnen.svelte.js`)."""

from __future__ import annotations

import json
import re
from pathlib import Path



WURZEL = Path(__file__).resolve().parent.parent
TEILE = WURZEL / "frontend" / "src" / "teile"
DETAILS = TEILE / "StudioDetails.svelte"
DRAW = WURZEL / "frontend" / "src" / "lib" / "studiozeichnen.svelte.js"


def _studio_parts() -> dict[str, str]:
    return {pfad.name: pfad.read_text(encoding="utf-8") for pfad in sorted(TEILE.glob("Studio*.svelte"))}


def test_no_control_is_locked_for_the_image_server():
    """Silence probe: the picture server locks nothing in the studio. A
    value it cannot carry sends the picture to sd-cli instead
    (app/api/v1/bild.py), so there is no Turbo switch, no restart pill,
    no CLI-only pill and no control greyed out while the server runs."""
    parts = _studio_parts()
    assert parts, "no studio part found"
    for name, quelle in parts.items():
        for trace in ("turboAn", "turboGespann", "turboSchalten", "Turbozeichen",
                      "pille_neustart", "pille_nur_cli", "hires_ohne_turbo_img2img"):
            assert trace not in quelle, f"{name}: {trace}"


def test_pulid_und_controlnet_felder_reisen_im_zeichnen_body_mit():
    """'Ein PuLID-Lauf traegt --pulid-weights + Embedding' and
    'ein ControlNet-Lauf traegt --control-net/--control-image' both start
    with the studio's own request -- a value nobody sends is not a run."""
    quelle = DRAW.read_text(encoding="utf-8")
    for zeile in (
        r"pulid_weights:\s*w\.pulid_weights \|\| null,",
        r"pulid_id_embedding:\s*w\.pulid_id_embedding \|\| null,",
        r"pulid_id_weight:\s*w\.pulid_id_weight,",
        r"control_net:\s*w\.control_net \|\| null,",
        r"control_image:\s*w\.control_image \|\| null,",
        r"control_strength:\s*w\.control_strength,",
        r"canny:\s*Boolean\(w\.canny\),",
    ):
        assert re.search(zeile, quelle), f"missing in the draw body: {zeile}"


def test_slg_felder_reisen_im_zeichnen_body_mit():
    """Skip layer/Layers/From/To must reach the request the studio actually
    sends, not just exist as values nobody reads."""
    quelle = DRAW.read_text(encoding="utf-8")
    for zeile in (
        r"slg_scale:\s*zahl\(w\.slg_scale, 0\),",
        r"skip_layer_start:\s*w\.skip_layer_start,",
        r"skip_layer_end:\s*w\.skip_layer_end,",
        r"skip_layers:\s*w\.skip_layers\.trim\(\),",
    ):
        assert re.search(zeile, quelle), f"missing in the draw body: {zeile}"


def test_the_hires_scale_travels_only_while_hires_is_on():
    """The studio keeps the scale as the one value `hires_wahl`, empty while
    the second pass is off: the switch is that value, and the request names
    a scale only for a pass that runs."""
    request = DRAW.read_text(encoding="utf-8")
    assert re.search(r"const hires = Boolean\(w\.hires_wahl\)", request)
    assert re.search(r"hires_scale:\s*hires \? Number\(w\.hires_wahl\) : undefined,", request)
    column = DETAILS.read_text(encoding="utf-8")
    switch = re.search(r"<Schalter[^>]*an=\{hires\}[^>]*>", column)
    assert switch, "the second pass no longer has its switch"
    assert "onschalten={hiresSchalten}" in switch.group(0)
    # The silence check: the rows of the pass stand inside the switch's
    # block, so a pass that is off shows none of them.
    block = column.split("{#if hires}", 1)
    assert len(block) == 2, "the rows of the second pass are no longer tied to the switch"
    assert "hires_steps" in block[1].split("{/if}", 1)[0]


def test_die_zwei_freien_adetailer_felder_tragen_keinen_platzhalter():
    """The two free ADetailer fields
    held a sentence as their placeholder — "empty inherits the main prompt".
    A text field that arrives with text in it reads as filled in, and the
    labels beside them already say whose prompt they override. Both the
    sentence and the attribute that showed it are gone."""
    quelle = DETAILS.read_text(encoding="utf-8")
    for feld in ("ad_prompt", "ad_negativ"):
        # The whole tag, not only what follows the binding: a placeholder
        # put IN FRONT of it is the same finding as one behind it.
        tag = re.search(rf"<input[^>]*bind:value=\{{werte\.{feld}\}}[^>]*>", quelle)
        assert tag, f"the input field {feld} no longer reads as expected"
        assert "placeholder" not in tag.group(0), f"{feld} shows a placeholder again"
    for sprache in ("de", "en"):
        katalog = json.loads((WURZEL / "app" / "locales" / f"{sprache}.json").read_text(encoding="utf-8"))
        assert "ad_prompt_platzhalter" not in katalog["bild"]
        assert "ad_negativ_platzhalter" not in katalog["bild"]


def test_no_field_of_the_studio_carries_a_placeholder():
    """An input field of the studio stays empty until something is typed
    into it: every field has its name beside it, and a text standing in an
    empty field reads as a value. No part of the studio sets a placeholder,
    and the sentences that were shown as one are gone from both catalogues."""
    for name, part in _studio_parts().items():
        assert "placeholder" not in part, f"{name} shows a placeholder"
    for sprache in ("de", "en"):
        katalog = json.loads((WURZEL / "app" / "locales" / f"{sprache}.json").read_text(encoding="utf-8"))
        gone = [key for key in katalog["bild"] if key.endswith("_platzhalter")]
        assert not gone, f"{sprache}: {gone}"
        # The silence check: what names a field or an entry of a list stays —
        # the search still says what it is, the seed's kinds keep "random".
        assert katalog["app"]["suchen"].strip()
        assert katalog["bild"]["seed_zufall"].strip()
    basics = _studio_parts()["StudioBasics.svelte"]
    assert "aria-label={t('app.suchen')}" in basics
    assert "{ wert: 'zufall', text: t('bild.seed_zufall') }" in basics


def test_the_studio_sends_no_kit_and_no_memory():
    """The model's kit and the machine's memory and devices are the picture
    server's (app/bildmodellwerte.py, app/bildgeraete.py): the studio has no
    field for them and sends none of them; the draw route adds them."""
    quelle = DRAW.read_text(encoding="utf-8")
    for feld in (
        "diffusion_model", "t5xxl", "clip_l", "clip_g", "llm", "vae",
        "high_noise_diffusion_model", "threads", "vram_limit",
        "offload_to_cpu", "split_mode", "backend",
    ):
        assert not re.search(rf"^\s+{feld}:", quelle, re.MULTILINE), feld
    # The silence check: the probe reads the body the request is built from.
    assert re.search(r"^\s+vae_format:", quelle, re.MULTILINE)
    for name, part in _studio_parts().items():
        assert 'group="memory"' not in part, name
        assert "bild.gruppe_speicher" not in part, name


def test_no_way_opens_a_picture_window_any_more():
    """The studio is the one place a picture is set up: the window part is
    gone, and nothing in the frontend asks for it."""
    assert not (TEILE / "Bildfenster.svelte").exists()
    quellen = sorted((WURZEL / "frontend" / "src").rglob("*.svelte")) + sorted(
        (WURZEL / "frontend" / "src").rglob("*.js")
    )
    for pfad in quellen:
        if "node_modules" in pfad.parts:
            continue
        text = pfad.read_text(encoding="utf-8")
        for trace in ("Bildfenster.svelte", "bildfensterOeffnen", "bildModellWunsch", "pictureInputWish"):
            assert trace not in text, f"{pfad.relative_to(WURZEL)}: {trace}"
    # The two ways that opened the window open the studio.
    eingabe = (TEILE / "Eingabeleiste.svelte").read_text(encoding="utf-8")
    assert "studioOeffnen()" in eingabe
    assert "studioWithPicture(nachricht.bild)" in (TEILE / "Nachricht.svelte").read_text(encoding="utf-8")


def test_a_catalogue_card_has_no_way_to_start_a_model():
    """A card of the catalogue opens its page, fetches its file and stops a
    fetch. It never had a button that starts a model, so the way behind such
    a button is gone: the callback, the catalogue's start and the model the
    studio was to open on."""
    quellen = sorted((WURZEL / "frontend" / "src").rglob("*.svelte")) + sorted(
        (WURZEL / "frontend" / "src").rglob("*.js")
    )
    for pfad in quellen:
        text = pfad.read_text(encoding="utf-8")
        for trace in ("onStart", "studioWithModel", "chooseWished"):
            assert not re.search(rf"\b{trace}\b", text), f"{pfad.relative_to(WURZEL)}: {trace}"
    # The silence check: what a card does do stays.
    card = (TEILE / "Modellkarte.svelte").read_text(encoding="utf-8")
    catalogue = (TEILE / "Katalog.svelte").read_text(encoding="utf-8")
    for callback in ("onOeffnen", "onDownload", "onCancel"):
        assert f"    {callback},\n" in card, callback
        assert f"{callback}=" in catalogue, callback
        # Taken as a property and used by the card itself.
        assert card.count(callback) >= 2, callback


def test_a_picture_handed_to_the_closed_studio_outlives_the_filling():
    """The left column fills the values from the chat's store when it comes
    up. A picture handed over while the studio is shut is set before that,
    so it is noted for the filling, which then keeps it instead of putting
    the stored start picture back."""
    store = (WURZEL / "frontend" / "src" / "lib" / "studio.svelte.js").read_text(encoding="utf-8")
    handed = store.split("export function studioWithPicture(name) {", 1)[1].split("\n}\n", 1)[0]
    assert "const columnUp = studioSichtbar()" in handed
    assert "if (!columnUp) vorgemerkt = { chat: chatanzeige.chatId, startbild: name }" in handed
    # The order matters: the note is read before the studio is opened.
    assert handed.index("studioSichtbar()") < handed.index("studioOeffnen()") < handed.index("vorgemerkt")
    filling = store.split("export function werteFuellen() {", 1)[1].split("\n}\n", 1)[0]
    assert "werte.startbild = vorgemerkt.startbild" in filling


def test_a_new_chat_is_the_open_chat_of_the_window():
    """A chat is created in one place, and that place makes it the chat the
    window's own state belongs to. A chat that was only made the active one
    left the studio without a chat: it kept no values and drew into a second
    chat."""
    source = WURZEL / "frontend" / "src"
    calls = {}
    for pfad in sorted(source.rglob("*.svelte")) + sorted(source.rglob("*.js")):
        found = pfad.read_text(encoding="utf-8").count("api.chatAnlegen(")
        if found:
            calls[pfad.relative_to(source).as_posix()] = found
    assert calls == {"lib/zustand.svelte.js": 1}, calls
    state = (source / "lib" / "zustand.svelte.js").read_text(encoding="utf-8")
    opened = state.split("export async function openNewChat(data) {", 1)[1].split("\n}\n", 1)[0]
    assert "await api.chatAnlegen(data)" in opened
    assert "chatZustandLaden(chat.id)" in opened
    # What the window held without a chat is in the store before it is read.
    assert opened.index("einstellungSetzen(`chat:${chat.id}`, 'bildfenster'") < opened.index("chatZustandLaden(chat.id)")
    # The four ways a chat comes into being all go through it.
    assert "await openNewChat({ title: t('chat.unbenannt')" in state
    assert "await openNewChat({ title: ersterTitel" in (source / "App.svelte").read_text(encoding="utf-8")
    assert "await openNewChat({ endpoint_id: zustand.modellId })" in (source / "lib" / "cli.svelte.js").read_text(encoding="utf-8")
    assert "await openNewChat({ title, endpoint_id: zustand.modellId || null })" in DRAW.read_text(encoding="utf-8")
    # The studio hands in what it holds without a chat, and stays silent
    # while a chat is open or while it neither shows nor prepares a draw.
    draw = DRAW.read_text(encoding="utf-8")
    reader = draw.split("chatless.pictureValues = (chatId) => {", 1)[1].split("\n}\n", 1)[0]
    assert "if (chatanzeige.chatId || !(studioSichtbar() || zeichnung.bereitet)) return null" in reader
    assert "if (steuervideo.datei) steuervideo.chat = chatId" in reader
    # The painted mask moves with the chat, and so does what was set —
    # whether or not the model's start values have arrived by then.
    assert "maskIntoChat(chatId)" in reader and "startValues" not in reader
    studio = (source / "lib" / "studio.svelte.js").read_text(encoding="utf-8")
    moved = studio.split("export function maskIntoChat(chatId) {", 1)[1].split("\n}\n", 1)[0]
    assert "masken.get(null)" in moved and "masken.set(chatId, held)" in moved and "masken.delete(null)" in moved
    assert "startValuesIn" not in studio and "startValuesArrived" not in studio
    assert "chatless.pictureValues?.(chat.id)" in opened
    # The family of the draw is read at the press, before a new chat refills
    # the column.
    drawn = draw.split("async function vorbereitenUndZeichnen(modeWish) {", 1)[1]
    assert drawn.index("const fam = familyOf(") < drawn.index("await openNewChat(")
    # The silence check: opening a chat and leaving for a new one load the
    # window's state as before.
    switch = state.split("export async function chatOeffnen(id) {", 1)[1].split("\nexport ", 1)[0]
    assert switch.count("chatZustandLaden(id)") == 2 and "chatZustandLaden(null)" in switch
    fresh = state.split("export function neuerChat() {", 1)[1].split("\n}\n", 1)[0]
    assert "chatZustandLaden(null)" in fresh


def test_a_picture_in_the_area_sets_kind_and_strength_in_one_place():
    """Whichever way a picture comes into the generation area, it passes
    `startbildWaehlen`, and that is where a full strength steps down and,
    after that, a mode that does not draw from the picture gives way to
    one that does. No caller sets either on its own."""
    source = WURZEL / "frontend" / "src"
    studio = (source / "lib" / "studio.svelte.js").read_text(encoding="utf-8")
    chosen = studio.split("export function startbildWaehlen(name) {", 1)[1].split("\n}\n", 1)[0]
    assert "pictureInArea()" in chosen
    rule = studio.split("export function pictureInArea() {", 1)[1].split("\n}\n", 1)[0]
    # The strength first: "auto" goes by it when it names the kind it draws.
    lowered = "if (Number(werte.staerke) >= 1) werte.staerke = art().video ? 0.75 : 0.6"
    assert rule.index(lowered) < rule.index("kindOntoPicture()")
    onto = studio.split("function kindOntoPicture() {", 1)[1].split("\n}\n", 1)[0]
    assert "if (!FROM_AREA.includes(now.value))" in onto
    assert "kindsOf(now.video).find((k) => FROM_AREA.includes(k.value))" in onto
    assert "KINDS.filter((k) => k.video === video && (!family || family.tasks.includes(k.task))" in studio
    assert "const FROM_AREA = ['img2img', 'edit', 'i2v', 'flf2v']" in studio
    # A family unknown at that moment is asked again when it arrives, for
    # the model and the chat the picture came into the area with.
    assert "kindDue = familie() ? null : { model: werte.modell, chat: chatanzeige.chatId }" in rule
    asked_again = studio.split("export async function vorgabenHolen() {", 1)[1].split("\n}\n", 1)[0]
    assert "if (due && dueModel === model && due.chat === chat && werte.startbild) kindOntoPicture()" in asked_again
    # Picture to picture stands before the edit in the table the rule walks.
    kinds = studio.split("export const KINDS = [", 1)[1].split("\n]\n", 1)[0]
    assert kinds.index("'img2img'") < kinds.index("'edit'") and kinds.index("'i2v'") < kinds.index("'flf2v'")
    # A chat that opens with a picture in its area is shown the same, unwritten.
    # The family off a header is the model's it was read for: another model in
    # the values makes it unknown before the rule walks the kinds.
    filling = studio.split("export function werteFuellen() {", 1)[1].split("\n}\n", 1)[0]
    assert "if ((werte.modell || listen.standardmodell) !== headerModel) auswahl.klasse = ''" in filling
    assert filling.index("auswahl.klasse = ''") < filling.index("pictureInArea()")
    assert filling.count("pictureInArea()") == 2
    assert "geschrieben.staerke = werte.staerke" in filling
    asked = studio.split("export async function vorgabenHolen() {", 1)[1].split("\n}\n", 1)[0]
    assert "headerModel = model" in asked
    # No caller lowers the strength or names the kind for a picture itself.
    for pfad in sorted(source.rglob("*.svelte")) + sorted(source.rglob("*.js")):
        text = pfad.read_text(encoding="utf-8")
        if pfad.name != "studio.svelte.js":
            assert "? 0.75 : 0.6" not in text, pfad.name
            assert "werte.staerke = 0.6" not in text and "werte.staerke = 0.75" not in text, pfad.name
        assert "auswahl.art = 'img2img'" not in text, pfad.name
    assert "staerkeAnfangen" not in DETAILS.read_text(encoding="utf-8")
    # "To video" names the video kind first, so the picture starts at a
    # video's strength.
    pictures = (source / "lib" / "studiobilder.svelte.js").read_text(encoding="utf-8")
    to_video = pictures.split("export function zuVideo(name) {", 1)[1].split("\n}\n", 1)[0]
    assert to_video.index("auswahl.art = kind") < to_video.index("startbildWaehlen(name)")
    # Taking the picture out puts the strength back to 1, and a mode that
    # cannot draw without the picture back to "auto"; any other mode stays.
    removed = pictures.split("export function bildEntfernen() {", 1)[1].split("\n}\n", 1)[0]
    assert removed.index("emptyArea()") < removed.index("if (pictureMissing()) auswahl.art = 'auto'")
    assert removed.count("auswahl") == 1
    emptied = studio.split("export function emptyArea() {", 1)[1].split("\n}\n", 1)[0]
    assert "werte.startbild = ''" in emptied and "werte.maske = ''" in emptied and "werte.staerke = 1" in emptied


def test_an_edit_sends_the_picture_in_the_area_as_its_first_reference():
    """In an edit the picture in the generation area travels as the first
    reference, before the ones of the right column; a family that takes one
    reference sends that one, and the column offers no second place."""
    draw = DRAW.read_text(encoding="utf-8")
    assert "ref_bilder: kind.value === 'edit' ? references(w, fam, flaeche?.startbild ?? w.startbild) : []," in draw
    refs = draw.split("function references(w, fam, inArea) {", 1)[1].split("\n}\n", 1)[0]
    assert "const first = inArea ? [inArea] : []" in refs
    assert "if (!fam?.many_references) return first" in refs
    assert "return [...first, ...w.ref_bilder.filter((name) => name !== w.startbild)]" in refs
    # What the area holds is asked for an edit as for a picture to start from.
    assert "const fromArea = nutztStart || kind.value === 'edit'" in draw
    assert "if (!modeWish && fromArea && w.startbild && leinwand.ausgeben) {" in draw
    # The silence check: the start picture and the mask still go with
    # picture to picture and the videos only, never with an edit.
    assert "const nutztStart = ['img2img', 'i2v', 'flf2v'].includes(kind.value)" in draw
    assert "maske: kind.value === 'img2img' ? flaeche?.maske ?? (w.maske || null) : null," in draw
    column = DETAILS.read_text(encoding="utf-8")
    edit = column.split("{#if kind.value === 'edit'}", 1)[1].split("{:else if kind.input}", 1)[0]
    row = edit.split("{#if viele}", 1)
    assert len(row) == 2, "the further references are no longer tied to a family that takes several"
    assert "studio.referenzbilder" in row[1].split("{/if}", 1)[0]
    assert "studio.referenzbilder" not in row[0]


def test_a_chat_stores_only_what_was_set_for_it():
    """A chat's picture values start empty in the window: no built-in
    default stands among them, so none is written back as the chat's own,
    and the studio shows the model's start value for every value the chat
    does not hold — each on its own."""
    source = WURZEL / "frontend" / "src"
    state = (source / "lib" / "chatanzeige.svelte.js").read_text(encoding="utf-8")
    assert "VORGABE_BILDFENSTER" not in state
    assert "cfg: 7" not in state and "offen:" not in state
    assert "  bildfenster: {},\n" in state
    loading = state.split("async function readChatState(chatId) {", 1)[1].split("\n}\n", 1)[0]
    assert "chatanzeige.bildfenster = {}\n" in loading
    assert "chatanzeige.bildfenster = { ...(daten.bildfenster?.wert || {}) }" in loading
    # What is written is the chat's own values with the change laid over.
    saving = state.split("function speichern(schluessel, teil) {", 1)[1].split("\n}\n", 1)[0]
    assert "Object.assign(stand, teil)" in saving
    assert "merken(chatanzeige.chatId, schluessel, { ...stand })" in saving
    # The start values go to every field the chat has none of its own for,
    # the CFG of a chat with a size of its own among them.
    column = (TEILE / "StudioBasics.svelte").read_text(encoding="utf-8")
    assert "MITGROESSE" not in column
    assert "if (!fehlen.includes(name) || !asFilled) delete teil[name]" in column
    # The silence check: a value the chat does hold is its own in the
    # studio, and only a changed value is written.
    studio = (source / "lib" / "studio.svelte.js").read_text(encoding="utf-8")
    filling = studio.split("export function werteFuellen() {", 1)[1].split("\n}\n", 1)[0]
    assert "const eigen = stand[name] !== undefined" in filling
    chosen = studio.split("export function setValues() {", 1)[1].split("\n}\n", 1)[0]
    assert "if (JSON.stringify(value) !== JSON.stringify(geschrieben[name])) set[name] = value" in chosen
    writing = studio.split("export function werteSchreiben() {", 1)[1].split("\n}\n", 1)[0]
    assert "const teil = setValues()" in writing and "bildfensterAusDemStudio(teil)" in writing
    # A chat created out of the studio is given the same and no more: not
    # the whole of what the window shows.
    reader = DRAW.read_text(encoding="utf-8").split("chatless.pictureValues = (chatId) => {", 1)[1].split("\n}\n", 1)[0]
    assert "const set = setValues()" in reader and "snapshot" not in reader
    assert "return Object.keys(set).length ? set : null" in reader


def test_the_search_goes_over_both_columns_by_one_rule():
    """One search field, at the top of the left column, and one rule for
    what it does: both columns hang it on their root, so a row of the right
    column is found like one of the left. While a search stands, the two
    folded sections of the right column and every fold of switches show
    their rows; afterwards each stands as it was left."""
    parts = _studio_parts()
    store = (WURZEL / "frontend" / "src" / "lib" / "studio.svelte.js").read_text(encoding="utf-8")
    # The rule stands once, in the studio's store, and reads the one text.
    assert "export const search = $state({ text: '' })" in store
    rule = store.split("export function searchRows(column) {", 1)[1].split("\n}\n", 1)[0]
    assert "const query = search.text.trim().toLowerCase()" in rule
    assert "row.hidden = !stays" in rule and "section.hidden = Boolean(query) && !headMatches && shown === 0" in rule
    assert "new MutationObserver(apply)" in rule
    for name, source in parts.items():
        assert ".hidden = " not in source, f"{name} hides rows of its own"
        assert "MutationObserver" not in source, name
    # Both columns use it; the field itself stands in the left one only.
    basics, details = parts["StudioBasics.svelte"], parts["StudioDetails.svelte"]
    assert '<section class="grundlagen" use:rollfade={40} use:searchRows' in basics
    assert '<section class="feinheiten" use:rollfade={40} use:searchRows' in details
    assert '<input type="search" bind:value={search.text}' in basics
    assert 'type="search"' not in details
    # What was typed goes with the field.
    assert "$effect(() => () => { search.text = '' })" in basics
    # A standing search opens the folded sections and the folds of switches.
    # A click on a head changes nothing meanwhile, so each stands afterwards
    # as it stood before.
    assert "const sucht = $derived(searching())" in basics
    assert "() => tuningOpen || searching(), (open) => (tuningOpen = searching() ? tuningOpen : open)" in details
    assert "() => erweitertOffen || searching()," in details
    assert "(open) => (erweitertOffen = searching() ? erweitertOffen : open)" in details
    assert basics.count("<StudioSwitches ") == basics.count("{sucht} />") == 1
    assert details.count("<StudioSwitches ") == details.count("sucht={searching()} />") == 4
    # The silence check: without a search no row is hidden and the folded
    # sections start shut.
    assert "const stays = !query || headMatches || name(row).toLowerCase().includes(query)" in rule
    assert "let tuningOpen = $state(false)" in details and "let erweitertOffen = $state(false)" in details


def test_the_head_of_a_folded_section_rests_while_a_search_stands():
    """While a search stands a folded section shows its rows whatever its
    fold says, and a press on its head changes nothing — neither the rows
    now nor the fold afterwards. A button that does nothing is not offered:
    the head rests for as long as the search stands, and shows no fold sign
    meanwhile."""
    section = _studio_parts()["StudioSection.svelte"]
    # The whole line of the tag: its press holds an arrow, so the tag does
    # not end at the first ">".
    head = re.search(r'^.*<button class="klappe".*$', section, re.MULTILINE)
    assert head, "the head of a folded section no longer reads as expected"
    assert "disabled={searching()}" in head.group(0)
    assert "import { searching } from '../lib/studio.svelte.js'" in section
    assert ".klappe:disabled .winkel" in section
    # The silence check: without a search the head folds as before — the
    # same press, bound to the same state.
    assert "onclick={() => (offen = !offen)}" in head.group(0)
    assert "aria-expanded={offen}" in head.group(0)
    store = (WURZEL / "frontend" / "src" / "lib" / "studio.svelte.js").read_text(encoding="utf-8")
    assert "export const searching = () => Boolean(search.text.trim())" in store


def test_a_draw_waits_for_the_start_values_of_the_shown_model():
    """A value the chat has none of its own for is the model's start value.
    Those arrive a moment after the studio shows a model; a picture pressed
    for meanwhile is drawn with them once they are laid in, never with the
    values the fields start at — and not at all when they do not arrive."""
    draw = DRAW.read_text(encoding="utf-8")
    drawn = draw.split("async function vorbereitenUndZeichnen(modeWish) {", 1)[1].split("\n}\n", 1)[0]
    # The values are taken after the wait, not at the press.
    assert drawn.index("const startValues = await startValuesThere()") < drawn.index(
        "const w = $state.snapshot(werte)")
    assert drawn.count("$state.snapshot(werte)") == 1
    # The press counts for the chat it was made in, and without start
    # values nothing is drawn — after the word about a missing model.
    assert drawn.index("const chat = chatanzeige.chatId") < drawn.index("await startValuesThere()")
    assert drawn.split("await startValuesThere()", 1)[1].lstrip().startswith(
        "if (chatanzeige.chatId !== chat) return")
    assert drawn.index("melde(t('bildserver.kein_standardmodell'), 'hinweis')") < drawn.index(
        "if (!startValues) return") < drawn.index("const kind = art()")
    store = (WURZEL / "frontend" / "src" / "lib" / "studio.svelte.js").read_text(encoding="utf-8")
    waiting = store.split("export async function startValuesThere() {", 1)[1].split("\n}\n", 1)[0]
    # Start values asked for again while the draw waited are waited for too.
    assert "due = startValuesDue" in waiting and "await due" in waiting
    assert "} while (due !== startValuesDue)" in waiting and "return startValuesLaid" in waiting
    # Each one that begins puts the values in question, the one that lays
    # them in settles it; the draw waits for every one still on its way.
    laying = store.split("export function layingStartValues(work) {", 1)[1].split("\n}\n", 1)[0]
    assert laying.index("startValuesLaid = false") < laying.index("const laying = work()")
    assert "laying.then((laid) => { if (laid) startValuesLaid = true }, () => {})" in laying
    assert "startValuesDue = Promise.all([startValuesDue, settled])" in laying
    # Every way the start values come into the studio says so: the filling
    # for a chat, a model picked, "Standard", a family said by hand.
    basics = (TEILE / "StudioBasics.svelte").read_text(encoding="utf-8")
    for source, heads in ((basics, ("async function fuellen(id, dabei) {", "async function modellGewaehlt(name) {",
                                    "async function standardHolen() {")),
                          (store, ("export async function familieWaehlen(name) {",))):
        for head in heads:
            body = source.split(head, 1)[1].split("\n}\n" if source is store else "\n  }\n", 1)[0]
            assert body.index("return layingStartValues(async () => {") < body.index("await vorgabenHolen()"), head
            assert "return false" in body or "return Boolean(v)" in body, head
        fetches = source.count("await vorgabenHolen()")
        assert fetches == len(heads), "start values fetched outside layingStartValues"
    filling = basics.split("async function fuellen(id, dabei) {", 1)[1].split("\n  }\n", 1)[0]
    # What was set by hand while the start values were on their way stays:
    # they go only to a value that still stands as it was filled.
    assert filling.index("const fehlen = werteFuellen()") < filling.index(
        "const filled = $state.snapshot(werte)") < filling.index("return layingStartValues(async () => {")
    assert "const asFilled = JSON.stringify(werte[name]) === JSON.stringify(filled[name])" in filling
    assert "if (!fehlen.includes(name) || !asFilled) delete teil[name]" in filling
    # The filling waits for the lists inside it, so a press while they load waits too.
    assert filling.index("return layingStartValues(async () => {") < filling.index("await listenDa")
    # The silence check: start values that are there hold nothing up — the
    # wait starts out met — and one press at a time stays the rule while a
    # draw is prepared.
    assert "let startValuesLaid = true" in store and "let startValuesDue = Promise.resolve()" in store
    press = draw.split("export async function studioZeichnen(modeWish = null) {", 1)[1].split("\n}\n", 1)[0]
    assert press.index("if (zeichnung.bereitet) return") < press.index("zeichnung.bereitet = true") < press.index(
        "await vorbereitenUndZeichnen(modeWish)")
    # The values the fields start at stay; they are only no longer drawn.
    assert "export const ANFANG = {" in store


def test_a_chat_keeps_its_style_by_the_styles_id():
    """A style has an id that never changes, and that id is what a chat
    keeps: the prompt bar picks by it and shows the name the style has now,
    the draw reads the style through the same lookup, and the card that
    renames a style follows no name. A chat that chose before styles had ids
    still finds its style by the name."""
    parts = _studio_parts()
    store = (WURZEL / "frontend" / "src" / "lib" / "studio.svelte.js").read_text(encoding="utf-8")
    lookup = store.split("export function stilVon(chosen) {", 1)[1].split("\n}\n", 1)[0]
    assert "named.find((s) => s.id === chosen) ?? named.find((s) => s.name === chosen) ?? null" in lookup
    bar = parts["StudioPromptBar.svelte"]
    assert "const chosenStyle = $derived(stilVon(werte.stil))" in bar
    assert "const stilName = $derived(chosenStyle?.name ?? '')" in bar
    assert "onclick={() => stilWaehlen(stil.id)}" in bar
    assert "stilWaehlen(stil.name)" not in bar
    assert "const stil = stilVon(w.stil)" in DRAW.read_text(encoding="utf-8")
    card = parts["StudioStyles.svelte"]
    assert "stile.liste.push({ id: newStyleId(), name, text: '{prompt}', negativ: '' })" in card
    assert "werte.stil = stil.name" not in card, "the card follows a name again"
    # Styles stored before they had ids get theirs once, when the list is read.
    assert "if (read.some((style) => !style.id)) {" in store
    # A list that never arrived is not written over the stored one, and
    # nothing is added to it.
    save = store.split("export function stileSpeichern() {", 1)[1].split("\n}\n", 1)[0]
    assert "if (!stile.geladen) return Promise.resolve()" in save
    assert '<button class="neu" onclick={neu} disabled={!stile.geladen}>' in card
    # The silence check: no style is still picked with '', and an older
    # chat's name is moved over to the id only when that name is about to change.
    assert "onclick={() => stilWaehlen('')}" in bar
    assert "if (werte.stil && werte.stil === stil.name) werte.stil = stil.id" in card


def test_the_mode_stands_at_the_prompt_bar_and_auto_names_the_kind_it_draws():
    """What the next press draws is chosen at the prompt bar: "auto" or one
    kind of the chosen half. The studio begins on "auto", which draws from
    the picture in the area while a mask is painted on it or the strength
    stands below 1 and the family can, else from the text, and never picks
    an edit, a first and last frame or a video to video while the family
    draws one of the others. A press that needs a picture rests while the
    area holds none. The left column has no row for the kind any more."""
    parts = _studio_parts()
    store = (WURZEL / "frontend" / "src" / "lib" / "studio.svelte.js").read_text(encoding="utf-8")
    assert "export const auswahl = $state({ art: 'auto', medium: 'bild', klasse: '', startKante: 0 })" in store
    now = store.split("export function art() {", 1)[1].split("\n}\n", 1)[0]
    assert "if (auswahl.art === 'auto') return autoKind()" in now
    auto = store.split("export function autoKind() {", 1)[1].split("\n}\n", 1)[0]
    assert "const [fromText, fromPicture] = autoPair(kinds, video)" in auto
    assert "return (video ? ['t2v', 'i2v'] : ['txt2img', 'img2img']).map(" in store
    assert "const masked = surface.masked || Boolean(werte.maske)" in auto
    assert "if (fromPicture && werte.startbild && (masked || Number(werte.staerke) < 1)) return fromPicture" in auto
    assert "return fromText ?? kinds.find((k) => FROM_AREA.includes(k.value)) ?? kinds[0]" in auto
    missing = store.split("export function pictureMissing() {", 1)[1].split("\n}\n", 1)[0]
    assert "if (!FROM_AREA.includes(kind.value) || werte.startbild) return false" in missing
    # An edit whose family takes several references draws from those of the
    # right column alone, as the draw's own list of references has it.
    assert "return !(kind.value === 'edit' && familie()?.many_references && werte.ref_bilder.length)" in missing
    assert "if (!fam?.many_references) return first" in DRAW.read_text(encoding="utf-8")
    # The strength stays in reach while it is what "auto" goes by, also at 1,
    # where the next press draws from the text; a kind chosen by hand that
    # draws from the text shows no strength, as before.
    decides = store.split("export function strengthDecides() {", 1)[1].split("\n}\n", 1)[0]
    assert "if (auswahl.art !== 'auto' || !werte.startbild) return false" in decides
    assert "return autoPair(kindsOf(video), video).every(Boolean)" in decides
    details = DETAILS.read_text(encoding="utf-8")
    assert "const strengthShown = $derived(strengthDecides())" in details
    assert "{#if kind.input || strengthShown || soundShown || refVideoShown}" in details
    assert "{:else if kind.input || strengthShown}" in details
    # The surface tells the studio whether a mask is painted.
    canvas = parts["StudioCanvas.svelte"]
    assert "surface.masked = etwasGemalt" in canvas
    bar = parts["StudioPromptBar.svelte"]
    field = bar.split('<div class="modeplace"', 1)[1].split('<div class="leiste glas"', 1)[0]
    assert "onclick={() => chooseMode('auto')}>{autoEntry}</button>" in field
    assert "{#each kinds as kind (kind.value)}" in field
    assert "onclick={() => chooseMode(kind.value)}>{t(kind.text)}</button>" in field
    assert "const kinds = $derived(kindsOf(auswahl.medium === 'video'))" in bar
    assert "const autoEntry = $derived(`${t('bild.art_auto')} · ${t(autoKind().text)}`)" in bar
    assert "const modeText = $derived(auswahl.art === 'auto' ? t('bild.art_auto') : t(art().text))" in bar
    assert "disabled={!werte.prompt.trim() || zeichnung.bereitet || !zeichnung.losZeichnen || noPicture}" in bar
    # The draw refuses it itself, so no way of asking draws from the text instead.
    drawn = DRAW.read_text(encoding="utf-8").split("async function vorbereitenUndZeichnen(modeWish) {", 1)[1]
    refused = "if (!modeWish && pictureMissing()) return"
    assert drawn.index("const kind = art()") < drawn.index(refused) < drawn.index("leinwand.ausgeben(")
    # The field keeps its room at the bar's left: the bar is the track that gives.
    assert "grid-template-columns: minmax(max-content, 1fr) minmax(0, 640px) 1fr;" in bar
    basics = parts["StudioBasics.svelte"]
    assert "feld('art')" not in basics and "bild.info_art" not in basics
    assert "bind:wert={auswahl.art}" not in basics
    # A kind chosen by hand gives way to its counterpart or to "auto";
    # "auto" stays through every change of model and half.
    gave_way = basics.split("const COUNTERPART = {", 1)[1].split("\n  /* The format tiles.", 1)[0]
    assert "if (auswahl.art === 'auto' || !kinds.length || kinds.some((k) => k.value === auswahl.art)) return" in gave_way
    assert "auswahl.art = kinds.find((k) => k.value === COUNTERPART[auswahl.art])?.value ?? 'auto'" in gave_way
    for language in ("de", "en"):
        texts = json.loads((WURZEL / "app" / "locales" / f"{language}.json").read_text(encoding="utf-8"))["bild"]
        assert texts["art_auto"] == "Auto" and "info_art" not in texts
    # The silence check: the draw still asks the one function for its kind,
    # and the switch between the halves stands where it stood.
    assert "const kind = art()" in DRAW.read_text(encoding="utf-8")
    assert "onclick={() => (auswahl.medium = name)}>{t(`bild.medium_${name}`)}</button>" in basics


def test_the_newest_picture_of_a_chat_stands_in_its_area_by_itself():
    """A picture drawn for the chat stands in the generation area once it is
    finished, the newest wins; a chat that opens with no picture of its own
    there shows the newest it has. It is shown, not written, changes neither
    mode nor strength, and an area emptied by hand stays empty until the next
    picture is finished or one is laid in. A finished video stays in the row
    of pictures. A finished picture as large as the one it replaces keeps
    zoom and place."""
    parts = _studio_parts()
    source = WURZEL / "frontend" / "src"
    store = (source / "lib" / "studio.svelte.js").read_text(encoding="utf-8")
    shown = store.split("function showInArea(name) {", 1)[1].split("\n}\n", 1)[0]
    # Shown, not written, and not through the rule of a picture laid in.
    assert "werteVorschlagen({ startbild: name, maske: '' })" in shown
    assert "pictureInArea" not in shown and "staerke" not in shown and "auswahl" not in shown
    looked = store.split("export async function newestIntoArea() {", 1)[1].split("\n}\n", 1)[0]
    assert "names = (await api.bilderListe({ chat })).bilder ?? []" in looked
    assert "if (look !== areaLook || chat !== chatanzeige.chatId) return" in looked
    finished = "if (newest && before !== undefined && newest !== before && drawAskedFor.has(chat)) {"
    assert finished in looked
    assert looked.index(finished) < looked.index("leinwand.keepView = newest") < looked.index("showInArea(newest)")
    assert "if (!zustand.pictureQueue.some((w) => w.chat_id === chat)) drawAskedFor.delete(chat)" in looked
    # A chat's own picture comes first, and an emptied area stays empty.
    none = store.split("function newestWhereNone() {", 1)[1].split("\n}\n", 1)[0]
    assert "if (!chatanzeige.geladen || werte.startbild || emptied.has(chat)) return" in none
    filling = store.split("export function werteFuellen() {", 1)[1].split("\n}\n", 1)[0]
    assert filling.rindex("pictureInArea()") < filling.index("newestWhereNone()")
    chosen = store.split("export function startbildWaehlen(name) {", 1)[1].split("\n}\n", 1)[0]
    assert "if (geschrieben.startbild === name) geschrieben.startbild = ''" in chosen
    assert "emptied.delete(chatanzeige.chatId)" in chosen
    pictures = (source / "lib" / "studiobilder.svelte.js").read_text(encoding="utf-8")
    emptied = store.split("export function emptyArea() {", 1)[1].split("\n}\n", 1)[0]
    assert "emptied.add(chatanzeige.chatId)" in emptied
    # One way empties the area: the area's own "remove" and the first-frame
    # field of the right column both take it.
    assert "emptyArea()" in pictures.split("export function bildEntfernen() {", 1)[1].split("\n}\n", 1)[0]
    released = DETAILS.read_text(encoding="utf-8").split("function startbildLoesen() {", 1)[1].split("\n  }\n", 1)[0]
    assert "emptyArea()" in released and "werte.startbild" not in released
    # The chat's pictures are read once: the row of pictures shows what the
    # area read, and asks only for a project's.
    assert "Object.assign(chatPictures, { chat, names })" in looked
    rail = parts["StudioGallery.svelte"]
    assert "ofProject ? projectPictures : chatPictures.chat === chatId ? chatPictures.names : []" in rail
    assert "api.bilderListe({ projekt })" in rail and "api.bilderListe({ chat" not in rail
    # The draw says that a picture is on its way; a video is none.
    drawn = DRAW.read_text(encoding="utf-8").split("async function vorbereitenUndZeichnen(modeWish) {", 1)[1]
    assert "if (modeWish || !drawsVideo) drawAsked(ziel)" in drawn
    assert drawn.index("drawAsked(ziel)") < drawn.index("losZeichnen({ ...base")
    canvas = parts["StudioCanvas.svelte"]
    assert "untrack(newestIntoArea)" in canvas
    loaded = canvas.split("function bildGeladen(ereignis) {", 1)[1].split("\n  }\n", 1)[0]
    assert "const finished = Boolean(leinwand.keepView) && loaded === api.bildAdresse(leinwand.keepView)" in loaded
    assert "if (!(finished && replaced.w === natur.w && replaced.h === natur.h)) einpassen()" in loaded
    # The silence check: a picture laid in by hand still passes the one rule
    # that sets strength and mode, and is written.
    assert "pictureInArea()" in chosen
    assert "onclick={() => startbildWaehlen(name)}" in parts["StudioGallery.svelte"]


def test_a_draw_from_a_part_of_the_picture_names_the_part_s_place():
    """Where the generation area shows only a part of the picture and lies
    wholly inside it, a picture drawn from that picture carries the
    picture's name and the part's place, under the names the draw route
    takes — so the drawn piece is set back into the whole picture. Start
    picture and mask are then cut at that very place; any other draw from
    the area is cut where the area lies, as before."""
    canvas = _studio_parts()["StudioCanvas.svelte"]
    place = canvas.split("function placeInPicture() {", 1)[1].split("\n  }\n", 1)[0]
    # Inside is told on the area's own pixels: no pixel without picture.
    assert "const inside = lage.x <= HALF_PIXEL && lage.y <= HALF_PIXEL" in place
    assert "&& lage.x + natur.w * lage.zoom >= gw - HALF_PIXEL" in place
    assert "&& lage.y + natur.h * lage.zoom >= gh - HALF_PIXEL" in place
    assert place.index("if (!inside) return null") < place.index("const left")
    # The area's four edges in the picture's pixels: whole numbers, never
    # beyond the picture.
    for edge in ("const left = Math.max(0, Math.round(-lage.x / lage.zoom))",
                 "const top = Math.max(0, Math.round(-lage.y / lage.zoom))",
                 "const right = Math.min(natur.w, Math.round((gw - lage.x) / lage.zoom))",
                 "const bottom = Math.min(natur.h, Math.round((gh - lage.y) / lage.zoom))"):
        assert edge in place
    # Less than the whole picture.
    assert "const part = right - left < natur.w || bottom - top < natur.h" in place
    assert "? [left, top, right - left, bottom - top] : null" in place
    handed = canvas.split("async function ausgebenNeu(name, mitMaske) {", 1)[1].split("\n  }\n", 1)[0]
    # Only a picture drawn from the picture is set back, and it is cut at
    # exactly the place it is set back at: the picture's whole pixels.
    assert "const place = wieEs || !mitMaske ? null : placeInPicture()" in handed
    assert "return { startbild, maske: maskenName, place }" in handed
    assert "const cut = wieEs ? null : aufDenBereich(bildKnoten, place)" in handed
    assert "cutMask = wieEs ? schwarzWeiss : aufDenBereich(schwarzWeiss, place)" in handed
    # Both are cut before either is laid down: the view may move meanwhile.
    assert handed.index("cutMask = wieEs ?") < handed.index("await hochladen(cut, 'startbild.png')")
    onto = canvas.split("function aufDenBereich(quelle, place = null) {", 1)[1].split("\n  }\n", 1)[0]
    assert "if (place) stift.drawImage(quelle, ...place, 0, 0, gw, gh)" in onto
    # The silence check: without a place the cut is where the area lies, and
    # a picture fitted whole into an area of its own shape goes as it is.
    assert "else stift.drawImage(quelle, lage.x, lage.y, natur.w * lage.zoom, natur.h * lage.zoom)" in onto
    assert "const startbild = cut ? await hochladen(cut, 'startbild.png') : name" in handed
    assert "const maskenName = cutMask ? await hochladen(cutMask, 'maske.png') : null" in handed
    drawn = DRAW.read_text(encoding="utf-8")
    # Only a picture drawn from a picture has a place to go back to.
    assert "const place = kind.value === 'img2img' ? flaeche?.place ?? null : null" in drawn
    assert "crop_of: place ? w.startbild : null," in drawn
    assert "crop_box: place," in drawn
    assert "startbild: nutztStart ? flaeche?.startbild ?? (w.startbild || null) : null," in drawn
    # The names are the draw route's own.
    route = (WURZEL / "app" / "api" / "v1" / "bild.py").read_text(encoding="utf-8")
    assert "    crop_of: str | None = None\n    crop_box: tuple[int, int, int, int] | None = None\n" in route


def test_a_family_that_edits_only_with_a_lora_offers_the_edit_with_one():
    """A family whose table entry says it edits only with a LoRA has the
    edit in the mode list only while a LoRA is chosen in the studio. The
    studio reads that from the family table and names no family itself;
    the list at the prompt bar and the giving way of a chosen kind both go
    by the one list of kinds."""
    parts = _studio_parts()
    source = WURZEL / "frontend" / "src"
    store = (source / "lib" / "studio.svelte.js").read_text(encoding="utf-8")
    kinds = store.split("export function kindsOf(video) {", 1)[1].split("\n}\n", 1)[0]
    assert "const noEdit = Boolean(family?.edit_needs_lora) && lorasKnown" in kinds
    assert "&& !werte.stapel.some((entry) => entry.name)" in kinds
    assert "&& !(noEdit && k.value === 'edit'))" in kinds
    # Until the values shown are filled from the open chat's read store its
    # LoRAs are not known: a chosen edit must not give way in that moment.
    assert "const lorasKnown = !chatanzeige.chatId || (filledFor.chat === chatanzeige.chatId && filledFor.read)" in kinds
    filling = store.split("export function werteFuellen() {", 1)[1].split("\n}\n", 1)[0]
    assert "Object.assign(filledFor, { chat: chatanzeige.chatId, read: chatanzeige.geladen })" in filling
    assert filling.index("werte[name] = structuredClone(") < filling.index("Object.assign(filledFor,")
    # The rule is the table's: the field is the one the family list hands
    # over, and the list of kinds names no family itself.
    from app import image_families
    assert all("edit_needs_lora" in entry for entry in image_families.as_json())
    assert ".name ===" not in kinds
    # One list of kinds for the mode field and for the kind that gives way.
    asked = "const kinds = $derived(kindsOf(auswahl.medium === 'video'))"
    assert asked in parts["StudioPromptBar.svelte"] and asked in parts["StudioBasics.svelte"]
    # The silence check: every other kind of the family stays in the list,
    # and the chosen LoRAs are the ones the draw sends.
    assert "k.video === video && (!family || family.tasks.includes(k.task))" in kinds
    assert "loras: w.stapel.filter((e) => e.name)" in DRAW.read_text(encoding="utf-8")


def test_picture_infos_ask_the_program_first_and_the_file_second():
    """ "Picture infos" shows what the program kept for the picture, asked
    for by the picture's name; only where it kept nothing is the file
    itself read. The card and "use" take either answer alike."""
    source = WURZEL / "frontend" / "src"
    api = (source / "lib" / "api.js").read_text(encoding="utf-8")
    assert "drawnWith: (name) => ruf(`/bild/info?name=${encodeURIComponent(name)}`)," in api
    pictures = (source / "lib" / "studiobilder.svelte.js").read_text(encoding="utf-8")
    asked = pictures.split("export async function infosZeigen(name) {", 1)[1].split("\n}\n", 1)[0]
    # A look-up that fails counts as nothing kept: the file is still read.
    kept = "let gefunden = await api.drawnWith(name).catch(() => null)"
    empty = "if (!gefunden || !Object.keys(gefunden).length) {"
    read = "gefunden = await api.pictureInfo(await api.bildBlob(name))"
    assert asked.index(kept) < asked.index(empty) < asked.index(read)
    # The silence check: the newest question for the open chat still wins,
    # and the file is read the way it was.
    assert "if (nr === infoAnfrage && fuer === chatanzeige.chatId) bildInfo.werte = gefunden ?? {}" in asked
    assert "ruf('/bild/info', { method: 'POST', headers: { 'Content-Type': file.type }, body: file })" in api
    # Both routes are the service's own, and answer in the same names.
    route = (WURZEL / "app" / "api" / "v1" / "bild.py").read_text(encoding="utf-8")
    assert '@router.get("/bild/info"' in route and '@router.post("/bild/info"' in route
    used = pictures.split("export function infoUebernehmen() {", 1)[1].split("\n}\n", 1)[0]
    for name in ("prompt", "negativ", "breite", "hoehe", "schritte", "cfg", "guidance", "sampler", "scheduler"):
        assert f"'{name}'" in used


def test_the_studio_lays_in_the_vae_format_the_rng_and_the_switch_rows_a_family_starts_with():
    """A family's start values name a VAE format, an RNG and switch rows
    (app/image_families.py). The studio lays them in like the measures: from
    the service's answer for the shown model, or from the family table for a
    family said by hand. A switch row is a start value only where some
    family starts with it; every other row stays as it was set."""
    from app import bildwahlen, image_families

    studio = (WURZEL / "frontend" / "src" / "lib" / "studio.svelte.js").read_text(encoding="utf-8")
    start = studio.split("export function startwerte(v) {", 1)[1].split("\n}\n", 1)[0]
    # A family said by hand hands in the same three the service's answer names.
    assert "vae_format: start.vae_format, rng: start.rng, switches: start.switches }" in start
    assert "VAE_FORMATS_OFFERED.includes(werteDerKlasse.vae_format)" in start
    assert "? werteDerKlasse.vae_format : ANFANG.vae_format" in start
    assert "teil.rng = werteDerKlasse.rng || ANFANG.rng" in start
    assert "imageFamilies.list.flatMap((family) => Object.keys(family.start?.switches ?? {}))" in start
    assert ".filter(([key]) => !started.has(key))" in start
    assert start.index("!started.has(key)") < start.index("...werteDerKlasse.switches,")

    # The formats laid in are the ones the field offers, and the service knows each.
    offered = re.findall(r"'(\w+)'", re.search(r"const VAE_FORMATS_OFFERED = \[(.*?)\]", studio).group(1))
    field = DETAILS.read_text(encoding="utf-8").split("bind:wert={werte.vae_format}", 1)[1].split("/>", 1)[0]
    assert re.findall(r"wert: '(\w+)'", field) == offered
    assert set(offered) <= set(bildwahlen.VAE_FORMATE)
    rng_field = DETAILS.read_text(encoding="utf-8").split("bind:wert={werte.rng}", 1)[1].split("/>", 1)[0]
    assert re.findall(r"wert: '(\w+)'", rng_field) == list(bildwahlen.RNG_WERTE)

    families = {family["name"]: family["start"] for family in image_families.as_json()}
    for name, values in families.items():
        assert values["vae_format"] in ("", *offered), name
        assert values["rng"] in ("", *bildwahlen.RNG_WERTE), name
    assert (families["pid"]["vae_format"], families["pid"]["rng"]) == ("flux", "cpu")
    assert families["wan22_i2v"]["switches"] == {
        "high_noise_cfg_scale": 3.5, "high_noise_sampling_method": "euler", "high_noise_steps": 8}
    # The silence check: a family without such start values leaves the
    # fields at their own start and lays in no switch row.
    assert (families["flux"]["vae_format"], families["flux"]["rng"], families["flux"]["switches"]) == ("", "", {})
    assert "  vae_format: 'auto',\n  rng: 'cuda'," in studio


def test_a_draw_in_a_chat_waits_for_that_chat_s_own_values():
    """While a chat's store is still being read the studio shows the default
    model. A press on "draw" then waits for the read and for the column's
    filling, and only then for the start values; a read that failed draws
    nothing and says what it failed with."""
    source = WURZEL / "frontend" / "src"
    press = DRAW.read_text(encoding="utf-8").split("async function vorbereitenUndZeichnen(modeWish) {", 1)[1]
    press = press.split("const startValues = await startValuesThere()", 1)
    assert len(press) == 2
    waiting = press[0]
    assert "if (chat) {" in waiting
    order = [waiting.index(part) for part in (
        "read = chatStateRead()", "await read", "} while (read !== chatStateRead())",
        "if (chatanzeige.chatId !== chat) return", "if (!chatanzeige.geladen) {", "await tick()")]
    assert order == sorted(order)
    assert "if (chatanzeige.readError) melde(chatanzeige.readError, 'fehler')" in waiting
    # What the press waits for is the read the chat was opened with.
    state = (source / "lib" / "chatanzeige.svelte.js").read_text(encoding="utf-8")
    assert "export const chatStateRead = () => reading" in state
    opened = state.split("export function chatZustandLaden(chatId) {", 1)[1].split("\n}\n", 1)[0]
    assert "reading = readChatState(chatId)" in opened and "return reading" in opened
    read = state.split("async function readChatState(chatId) {", 1)[1].split("\n}\n", 1)[0]
    # A new read starts without a failure; a failure counts only for the chat still open.
    assert read.index("chatanzeige.readError = ''") < read.index("chatanzeige.chatId = chatId")
    assert "if (chatanzeige.chatId === chatId) chatanzeige.readError = String(error.message || error)" in read
    # The silence check: without a chat nothing is waited for but the start
    # values, and a read that came through sets no failure.
    assert waiting.index("if (chat) {") < waiting.index("read = chatStateRead()")
    assert read.count("chatanzeige.readError = ") == 2


def test_a_failed_read_of_the_chat_s_values_leaves_the_area_empty_like_any_other():
    """The surface keeps its fitted picture while a chat's values are on
    their way. A read that failed brings none: the picture is forgotten and
    the next one is fitted."""
    canvas = (TEILE / "StudioCanvas.svelte").read_text(encoding="utf-8")
    assert ("if (bildUrl) return\n"
            "    if (chatanzeige.chatId && !chatanzeige.geladen && !chatanzeige.readError) return\n"
            "    tick().then(() => {\n"
            "      if (!bildUrl) fittedPicture = null\n") in canvas


def test_what_was_set_since_a_chat_opened_stays_when_its_stored_values_arrive():
    """A chat's stored values arrive a moment after it was opened. What was
    typed or set in that moment stays: the late store fills only what is
    untouched since, and what stayed is the chat's own from here on."""
    studio = (WURZEL / "frontend" / "src" / "lib" / "studio.svelte.js").read_text(encoding="utf-8")
    filling = studio.split("export function werteFuellen() {", 1)[1].split("\n}\n", 1)[0]
    # Late is the read store of the chat the values were last filled for unread.
    assert ("const late = chatanzeige.geladen && !filledFor.read && filledFor.chat === chatanzeige.chatId\n"
            "  const touched = late ? setValues() : {}\n") in filling
    loop = filling.split("for (const [name, start] of Object.entries(ANFANG)) {", 1)[1].split("\n  }\n", 1)[0]
    order = [loop.index(part) for part in (
        "read[name] = structuredClone($state.snapshot(eigen ? stand[name] : start))",
        "if (name in touched) continue",
        "if (!eigen) fehlen.push(name)",
        "werte[name] = structuredClone(read[name])")]
    assert order == sorted(order)
    # What stayed differs from what was read, so it is written as set by hand.
    assert "\n  geschrieben = read\n" in filling
    assert filling.index("geschrieben = read") < filling.index(
        "Object.assign(filledFor, { chat: chatanzeige.chatId, read: chatanzeige.geladen })")
    assert "if (Object.keys(touched).length) werteSchreiben()\n  return fehlen" in filling
    # The silence check: an untouched field is filled as before, and what
    # counts as set is what differs from what was read or shown.
    assert "const eigen = stand[name] !== undefined" in loop
    set_here = studio.split("export function setValues() {", 1)[1].split("\n}\n", 1)[0]
    assert "if (JSON.stringify(value) !== JSON.stringify(geschrieben[name])) set[name] = value" in set_here


def test_a_draw_without_a_prompt_says_so_and_the_two_sentences_read_as_decided():
    """A press on "draw" without a prompt draws nothing and says that the
    prompt is missing; the sentence about a missing model names the picture
    model. Both read word for word as decided, in both languages."""
    press = DRAW.read_text(encoding="utf-8").split("async function vorbereitenUndZeichnen(modeWish) {", 1)[1]
    assert ("  if (!modeWish && !w.prompt.trim()) {\n"
            "    melde(t('studio.no_prompt'), 'hinweis')\n"
            "    return\n"
            "  }\n") in press
    texts = {
        language: json.loads((WURZEL / "app" / "locales" / f"{language}.json").read_text(encoding="utf-8"))
        for language in ("de", "en")
    }
    assert {language: catalogue["studio"]["no_prompt"] for language, catalogue in texts.items()} == {
        "de": "Kein Prompt eingegeben. Schreib in die Prompt-Leiste, was gezeichnet werden soll.",
        "en": "No prompt entered. Write in the prompt bar what should be drawn.",
    }
    assert {language: catalogue["bildserver"]["kein_standardmodell"] for language, catalogue in texts.items()} == {
        "de": "Kein Bildmodell ausgewählt. Wähle es auf der Seite Bild-Server.",
        "en": "No picture model selected. Choose it on the picture server page.",
    }
    # The silence check: a press with a prompt goes on to the model as
    # before, and a mode on a finished picture is asked for no prompt.
    assert press.index("melde(t('studio.no_prompt'), 'hinweis')") < press.index(
        "melde(t('bildserver.kein_standardmodell'), 'hinweis')") < press.index("const kind = art()")
