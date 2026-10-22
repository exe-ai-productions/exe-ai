"""The phone pages for models and servers: the readings they make of what a
server says, the plan a tap on "download" turns into, and the shape of the
page files themselves.

The readings live in import-free modules (`servers.js`, `cloud.js`,
`catalog.js`) so they run here exactly as they ship, without the Svelte
build around them.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
PHONE = FRONTEND / "src" / "phone"
LOCALES = ROOT / "app" / "locales"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")


def _run(body: str) -> dict:
    driver = FRONTEND / f"phone_servers.{os.getpid()}.check.mjs"
    driver.write_text(
        textwrap.dedent(
            """
            import * as servers from './src/phone/servers.js'
            import * as cloud from './src/phone/cloud.js'
            import * as catalog from './src/phone/catalog.js'
            import * as speech from './src/phone/speech.js'
            """
        )
        + textwrap.dedent(body),
        encoding="utf-8",
    )
    try:
        done = subprocess.run(
            ["node", driver.name], cwd=FRONTEND, capture_output=True, text=True, timeout=60
        )
    finally:
        driver.unlink(missing_ok=True)
    assert done.returncode == 0, (done.stdout + done.stderr)[-2000:]
    return json.loads(done.stdout.strip().splitlines()[-1])


# ——— the row of one server ———


@needs_node
def test_a_running_server_has_a_green_dot_its_model_and_its_port():
    out = _run(
        """
        console.log(JSON.stringify(servers.serverRow('model', {laeuft: true, modell: 'a.gguf', port: 8080})))
        """
    )
    assert out == {
        "dot": "gruen", "word": "status.aktiv", "running": True, "model": "a.gguf", "port": 8080,
    }


@needs_node
def test_a_stopped_server_says_nothing_of_a_model_and_wears_no_dot():
    """The quiet case: a report that still carries the last model must not
    make a stopped server look as if it held it."""
    out = _run(
        """
        const row = servers.serverRow('agent', {laeuft: false, modell: 'old.gguf', port: 8081})
        console.log(JSON.stringify(row))
        """
    )
    assert out["running"] is False
    assert out["dot"] is None
    assert out["model"] is None
    assert out["word"] == "status.inaktiv"


@needs_node
def test_a_server_that_has_not_answered_has_no_state_at_all():
    """No report is not "stopped": the list must not claim what it does not know."""
    out = _run(
        """
        console.log(JSON.stringify(['model', 'embedding', 'image'].map((k) => servers.serverRow(k, null))))
        """
    )
    for row in out:
        assert row == {"dot": None, "word": None, "running": False, "model": None, "port": None}


@needs_node
def test_the_picture_server_has_four_states_and_a_colour_for_each():
    out = _run(
        """
        const states = ['aus', 'bereit', 'zeichnet', 'fehler', 'unknown']
        console.log(JSON.stringify(states.map((z) => servers.serverRow('image', {zustand: z, modell: 'm'}))))
        """
    )
    assert [row["dot"] for row in out] == [None, "gruen", "blau", "rot", None]
    assert [row["running"] for row in out] == [False, True, True, False, False]
    assert out[1]["word"] == "studio.bildserver_bereit"
    assert out[4]["word"] == "studio.bildserver_aus"


@needs_node
def test_the_list_names_six_servers_once_each():
    out = _run("console.log(JSON.stringify(servers.SERVERS.map((s) => s.kind)))")
    assert out == ["model", "agent", "embedding", "speech", "cleanup", "image"]


# ——— the model a start would use ———


@needs_node
def test_start_model_prefers_the_pick_then_the_running_one_then_the_first():
    out = _run(
        """
        const report = {laeuft: true, modell: 'b.gguf', modelle: [{name: 'a.gguf'}, {name: 'b.gguf'}, {name: 'c.gguf'}]}
        console.log(JSON.stringify([
          servers.startModel(report, 'c.gguf'),
          servers.startModel(report, ''),
          servers.startModel({...report, laeuft: false, modell: 'c.gguf'}, ''),
          servers.startModel(report, 'gone.gguf'),
          servers.startModel({modelle: []}, 'x.gguf'),
          servers.startModel(null, ''),
          servers.startModel({laeuft: false, modelle: report.modelle}, '', 'c.gguf'),
          servers.startModel({laeuft: false, modelle: report.modelle}, '', 'gone.gguf'),
        ]))
        """
    )
    assert out == ["c.gguf", "b.gguf", "c.gguf", "b.gguf", "", "", "c.gguf", "a.gguf"]


@needs_node
def test_the_fields_start_from_the_chosen_values_and_a_running_server_from_its_own():
    out = _run(
        """
        const idle = {laeuft: false, port: 8080, vorgaben: {kontext: 32768, schichten: 99, port: 8080}}
        const stored = {kontext: 131072, schichten: 0, port: 9000}
        const running = {laeuft: true, kontext: 4096, schichten: 12, port: 8081, vorgaben: idle.vorgaben}
        const read = (report, st) => ['kontext', 'schichten', 'port'].map((n) => servers.seedValue(report, n, st))
        console.log(JSON.stringify({
          chosen: read(idle, stored),
          nothingChosen: read(idle, {kontext: null, schichten: null, port: null}),
          running: read(running, stored),
          noStore: ['port'].map((n) => servers.seedValue({laeuft: false, port: 8685}, n, undefined)),
          empty: servers.seedValue(null, 'port', undefined),
        }))
        """
    )
    # A stopped server shows what was chosen, not the default its report carries.
    assert out["chosen"] == ["131072", "0", "9000"]
    assert out["nothingChosen"] == ["32768", "99", "8080"]
    assert out["running"] == ["4096", "12", "8081"]
    assert out["noStore"] == ["8685"]
    assert out["empty"] == ""


@needs_node
def test_whole_number_takes_digits_only_and_nothing_else():
    out = _run(
        """
        const inputs = ['8080', ' 12 ', '', null, 'abc', '1.5', '-3', '99999999999999999999', '0']
        console.log(JSON.stringify(inputs.map(servers.wholeNumber)))
        """
    )
    assert out == [8080, 12, None, None, None, None, None, None, 0]


@needs_node
def test_sizes_are_said_with_one_decimal():
    out = _run(
        """
        console.log(JSON.stringify([servers.gbLabel(4.25), servers.gbLabel(0.04), servers.gbLabel(null), servers.gbLabel(12)]))
        """
    )
    assert out == ["4.3 GB", "0.0 GB", "", "12.0 GB"]


@needs_node
def test_model_options_carry_the_size_and_tolerate_a_missing_list():
    out = _run(
        """
        console.log(JSON.stringify([
          servers.modelOptions({modelle: [{name: 'a.gguf', groesse_gb: 2.5}, {name: 'b.gguf'}]}),
          servers.modelOptions({}),
        ]))
        """
    )
    assert out[0] == [
        {"value": "a.gguf", "label": "a.gguf", "gb": 2.5},
        {"value": "b.gguf", "label": "b.gguf", "gb": None},
    ]
    assert out[1] == []


# ——— the cloud page ———


@needs_node
def test_context_field_means_empty_ask_the_server_or_a_whole_number():
    out = _run(
        """
        const inputs = ['', '  ', '8192', '0', '12x', '-1', '10000001', '10000000']
        console.log(JSON.stringify(inputs.map(cloud.contextValue)))
        """
    )
    # `undefined` is not JSON: it comes out as null, so the empty field (also
    # null) is told apart by position.
    assert out == [None, None, 8192, None, None, None, None, 10000000]


@needs_node
def test_context_field_keeps_the_old_value_for_nonsense():
    out = _run(
        """
        console.log(JSON.stringify([cloud.contextValue('12x') === undefined, cloud.contextValue('') === null]))
        """
    )
    assert out == [True, True]


@needs_node
def test_a_found_context_is_said_short_and_a_stand_in_is_not_a_finding():
    out = _run(
        """
        console.log(JSON.stringify([
          cloud.contextFound({kontext: 200000, kontextQuelle: 'server'}),
          cloud.contextFound({kontext: 800, kontextQuelle: 'server'}),
          cloud.contextFound({kontext: 4096, kontextQuelle: 'ersatz'}),
          cloud.contextFound({kontext: null}),
          cloud.contextFound(null),
        ]))
        """
    )
    assert out == ["200k", "800", None, None, None]


@needs_node
def test_a_provider_needs_a_key_and_the_own_server_also_a_name_and_an_address():
    out = _run(
        """
        const key = 'sk-12345678'
        console.log(JSON.stringify([
          cloud.providerReady('anthropic', {key, id: '', url: ''}),
          cloud.providerReady('anthropic', {key: 'short', id: '', url: ''}),
          cloud.providerReady('eigen', {key, id: 'home', url: ''}),
          cloud.providerReady('eigen', {key, id: '', url: 'http://x/v1'}),
          cloud.providerReady('eigen', {key, id: 'home', url: 'http://x/v1'}),
          cloud.providerReady('openai', {key: '        ', id: '', url: ''}),
        ]))
        """
    )
    assert out == [True, False, False, False, True, False]


# ——— the plan of a download ———


FILE = "{datei: 'sub/model-Q4.gguf', groesse_gb: 4}"


@needs_node
def test_a_new_file_is_fetched_under_its_flat_name_with_its_projector():
    out = _run(
        f"""
        const plan = catalog.planDownload({{
          repo: 'a/b', file: {FILE}, projector: {{datei: 'mmproj-F16.gguf'}}, present: [], partLists: null,
        }})
        console.log(JSON.stringify(plan))
        """
    )
    names = [job["datei"] for job in out["queue"]]
    assert names == ["sub/model-Q4.gguf", "mmproj-F16.gguf"]
    # The model is first and keeps its flat name; the projector is tied to it.
    assert out["queue"][0]["ziel"] is None
    assert out["queue"][1]["ziel"] == "model-Q4-mmproj-F16.gguf"
    assert out["queue"][1]["gehoert_zu"] == "model-Q4.gguf"
    assert out["queue"][1]["rolle"] == "mmproj"
    assert out["ties"] == []


@needs_node
def test_a_file_that_is_here_fetches_nothing_again_and_not_its_projector():
    """Counter-check of the first: with the model present, neither the model nor
    a projector is asked for."""
    out = _run(
        f"""
        const plan = catalog.planDownload({{
          repo: 'a/b', file: {FILE}, projector: {{datei: 'mmproj-F16.gguf'}},
          present: ['model-Q4.gguf'], partLists: null,
        }})
        console.log(JSON.stringify(plan))
        """
    )
    assert out == {"queue": [], "ties": []}


@needs_node
def test_a_projector_that_is_here_is_not_fetched_twice():
    out = _run(
        f"""
        const plan = catalog.planDownload({{
          repo: 'a/b', file: {FILE}, projector: {{datei: 'mmproj-F16.gguf'}},
          present: ['model-Q4-mmproj-F16.gguf'], partLists: null,
        }})
        console.log(JSON.stringify(plan.queue.map((j) => j.datei)))
        """
    )
    assert out == ["sub/model-Q4.gguf"]


@needs_node
def test_the_parts_of_a_kit_are_split_into_fetch_and_tie():
    """A part that lies in its folder is only tied to the model; one that
    does not is fetched after the model."""
    out = _run(
        """
        const file = {
          datei: 'sd.safetensors',
          bausatz: {teile: [
            {rolle: 'modell', datei: 'sd.safetensors'},
            {rolle: 'vae', repo: 'v/v', datei: 'vae.safetensors', ordner: 'vae', feld: 'vae', da: false},
            {rolle: 'textleser', repo: 't/t', datei: 'enc.safetensors', ordner: 'text_encoders', feld: 'clip', da: false},
          ]},
        }
        const lists = {vae: ['vae.safetensors'], text_encoders: []}
        const plan = catalog.planDownload({repo: 'a/b', file, projector: null, present: [], partLists: lists})
        console.log(JSON.stringify({queue: plan.queue.map((j) => j.datei), ties: plan.ties.map((j) => j.datei)}))
        """
    )
    assert out == {"queue": ["sd.safetensors", "enc.safetensors"], "ties": ["vae.safetensors"]}


@needs_node
def test_before_the_lists_are_read_the_file_lists_own_answer_decides():
    out = _run(
        """
        const file = {
          datei: 'sd.safetensors',
          bausatz: {teile: [{rolle: 'vae', repo: 'v/v', datei: 'vae.safetensors', ordner: 'vae', feld: 'vae', da: true}]},
        }
        const plan = catalog.planDownload({repo: 'a/b', file, projector: null, present: [], partLists: null})
        console.log(JSON.stringify({queue: plan.queue.length, ties: plan.ties.length}))
        """
    )
    assert out == {"queue": 1, "ties": 1}


@needs_node
def test_a_file_of_another_size_under_the_same_name_is_not_taken_for_present():
    out = _run(
        """
        const file = {datei: 'm.gguf', local_name: 'repo-m.gguf', collision: true}
        const plan = catalog.planDownload({repo: 'a/b', file, projector: null, present: ['m.gguf', 'repo-m.gguf'], partLists: null})
        console.log(JSON.stringify(plan.queue))
        """
    )
    assert out == [{"repo": "a/b", "datei": "m.gguf", "ziel": "repo-m.gguf"}]


@needs_node
def test_counts_and_sizes_are_short():
    out = _run(
        """
        console.log(JSON.stringify([catalog.shortCount(999), catalog.shortCount(12400), catalog.gigabytes(4.26e9)]))
        """
    )
    assert out == ["999", "12k", "4.3"]


# ——— the page files ———


def _page_files() -> list[Path]:
    return sorted((PHONE / "pages").glob("*.svelte"))


def test_the_pages_of_this_series_declare_a_unique_name_and_order():
    names, orders = [], []
    for page in _page_files():
        text = page.read_text(encoding="utf-8")
        if "export const meta" not in text:
            continue
        names.append(re.search(r"name:\s*'([^']+)'", text).group(1))
        orders.append(int(re.search(r"order:\s*(\d+)", text).group(1)))
    assert {"models-local", "models-cloud", "catalog", "downloads", "tools"} <= set(names)
    assert len(names) == len(set(names))
    assert len(orders) == len(set(orders))


def test_every_page_meta_title_exists_in_both_catalogues():
    catalogues = [json.loads((LOCALES / f"{lang}.json").read_text(encoding="utf-8")) for lang in ("de", "en")]
    for page in _page_files():
        text = page.read_text(encoding="utf-8")
        if "export const meta" not in text:
            continue
        key = re.search(r"title:\s*'([^']+)'", text).group(1)
        for catalogue in catalogues:
            node = catalogue
            for part in key.split("."):
                node = node[part]
            assert isinstance(node, str), key


def test_every_key_the_phone_files_read_exists_in_both_catalogues():
    catalogues = [json.loads((LOCALES / f"{lang}.json").read_text(encoding="utf-8")) for lang in ("de", "en")]

    def has(catalogue: dict, key: str) -> bool:
        node = catalogue
        for part in key.split("."):
            if not isinstance(node, dict) or part not in node:
                return False
            node = node[part]
        return isinstance(node, str)

    own = [
        *PHONE.glob("servers/*"), *PHONE.glob("cloud/*"), *PHONE.glob("catalog/*"), *PHONE.glob("tools/*"),
        *PHONE.glob("parts/*"), PHONE / "servers.js", PHONE / "cloud.js", PHONE / "catalog.js",
        PHONE / "downloadFeed.svelte.js", *PHONE.glob("pages/Models*.svelte"),
        PHONE / "pages" / "Catalog.svelte", PHONE / "pages" / "Downloads.svelte", PHONE / "pages" / "Tools.svelte",
    ]
    key = re.compile(r"""['"`]([a-z_]+(?:\.[a-z_0-9]+)+)['"`]""")
    missing = []
    for path in own:
        for found in key.findall(path.read_text(encoding="utf-8")):
            root = found.split(".")[0]
            # Only the roots of the catalogue are keys; a file name like
            # 'a.gguf' or an import path is not.
            if any(root in catalogue for catalogue in catalogues) and not all(has(c, found) for c in catalogues):
                missing.append(f"{path.name}: {found}")
    assert not missing, missing


def test_no_phone_file_hides_the_state_rune_behind_a_local_name():
    """A local name `state` turns `$state(...)` into a store subscription and
    the declaration silently stops being reactive."""
    clash = re.compile(r"(?:let|const|function)\s+state\b|\bstate\s*=\s*\$props|\{[^}]*\bstate\b[^}]*\}\s*=\s*\$props")
    for path in PHONE.rglob("*.svelte"):
        assert not clash.search(path.read_text(encoding="utf-8")), path.name


def test_each_server_page_reaches_the_routes_of_its_own_server():
    drivers = (PHONE / "servers" / "drivers.js").read_text(encoding="utf-8")
    expected = {
        "model": ["runnerAuskunft", "runnerProtokoll", "runnerStoppen", "runnerStarten"],
        "agent": ["agentenmodellAuskunft", "agentenmodellProtokoll"],
        "embedding": ["einbettungAuskunft", "einbettungStarten", "einbettungStoppen"],
        "speech": ["spracheAuskunft", "spracheStarten", "spracheStoppen"],
        "cleanup": ["bereinigungAuskunft", "bereinigungStarten", "bereinigungStoppen"],
    }
    for kind, calls in expected.items():
        block = drivers.split(f"  {kind}: {{", 1)[1].split("\n  },", 1)[0]
        for call in calls:
            assert f"api.{call}" in block, (kind, call)


def test_the_servers_page_never_starts_by_itself():
    """A start is the press of a button: no effect of the server page calls
    a start, whatever the state it reads."""
    view = (PHONE / "servers" / "ServerView.svelte").read_text(encoding="utf-8")
    effects = re.findall(r"\$effect\(\(\) => \{.*?\n  \}\)", view, flags=re.S)
    assert effects
    for body in effects:
        assert "start(" not in body.replace("driver.start", "X") or "driver.start" not in body
        assert "driver.start" not in body


# ——— the speech server page: what the desktop holds beside the start ———


def _desktop_speech_keys() -> set[str]:
    text = (FRONTEND / "src" / "teile" / "Sprachserver.svelte").read_text(encoding="utf-8")
    return set(re.findall(r"t\('sprachserver\.([a-z_]+)'", text))


def test_every_speech_text_the_desktop_page_shows_stands_on_the_phone_page_too():
    # What the phone page words differently or does not repeat: the title of
    # the page, the line of a running port, the empty list, the model's own
    # label (the page has the shared one), and the recording of a voice
    # sample, which only the desktop page offers.
    own = {
        "titel",
        "laeuft",
        "kein_modell",
        "modell",
        "sample_record",
        "sample_play",
        "sample_stop",
        "sample_delete",
        "sample_delete_question",
        "sample_dictation_busy",
        "sample_file",
    }
    phone = "".join(
        (PHONE / "servers" / name).read_text(encoding="utf-8")
        for name in ("ServerView.svelte", "SpeechSettings.svelte")
    ) + (PHONE / "speech.js").read_text(encoding="utf-8")
    missing = sorted(key for key in _desktop_speech_keys() - own if f"sprachserver.{key}" not in phone)
    assert not missing, missing


def test_the_cleanup_server_page_carries_no_speech_settings():
    view = (PHONE / "servers" / "ServerView.svelte").read_text(encoding="utf-8")
    assert "{#if kind === 'speech'}\n  <SpeechSettings" in view
    assert "SpeechSettings" not in (PHONE / "servers" / "ImageServerView.svelte").read_text(encoding="utf-8")


@needs_node
def test_the_five_voice_values_keep_the_bounds_and_steps_of_the_desktop_page():
    desktop = (FRONTEND / "src" / "teile" / "Sprachserver.svelte").read_text(encoding="utf-8")
    rows = re.findall(
        r"knopf: '(\w+)', schluessel: '(\w+)',\s*stufen: STUFEN\.\w+, min: ([\d.]+), max: ([\d.]+), "
        r"schritt: ([\d.]+), ganzzahlig: (true|false)",
        desktop,
    )
    expected = [
        {"name": a, "key": b, "min": float(c), "max": float(d), "step": float(e), "whole": f == "true"}
        for a, b, c, d, e, f in rows
    ]
    assert len(expected) == 5
    out = _run(
        "console.log(JSON.stringify(speech.PARAMETERS.map(({name, key, min, max, step, whole}) => ({name, key, min, max, step, whole}))))"
    )
    assert out == expected


@needs_node
def test_a_field_shows_what_is_stored_else_the_works_answer_and_zero_is_an_answer():
    out = _run(
        """
        console.log(JSON.stringify([
          speech.shownText('mine', 'works'), speech.shownText('', 'works'),
          speech.shownNumber(0, 5), speech.shownNumber(null, 5), speech.shownNumber(null, null),
          speech.shownSwitch(false, true), speech.shownSwitch(null, true), speech.shownSwitch(null, null, true),
        ]))
        """
    )
    assert out == ["mine", "works", 0, 5, None, False, True, True]


@needs_node
def test_silence_the_works_answer_standing_is_no_choice_and_is_not_stored():
    out = _run(
        """
        console.log(JSON.stringify([
          speech.worthStoring('works text', '', 'works text'),
          speech.worthStoring('mine', 'mine', 'works text'),
          speech.worthStoring(0.9, null, 0.9),
          speech.worthStoring(0, null, 0),
          speech.worthStoring(null, null, null),
          speech.worthStoring('', '', 'works text'),
        ]))
        """
    )
    assert out == [False, False, False, False, False, False]


@needs_node
def test_a_change_away_from_the_works_answer_is_stored_and_so_is_taking_a_number_away():
    out = _run(
        """
        console.log(JSON.stringify([
          speech.worthStoring('other', '', 'works text'),
          speech.worthStoring('works text', 'mine', 'works text'),
          speech.worthStoring(0.5, null, 0.9),
          speech.worthStoring(null, 4, null),
          speech.worthStoring('', 'mine', 'works text'),
        ]))
        """
    )
    assert out == [True, True, True, True, True]


@needs_node
def test_a_typed_number_is_kept_to_its_bounds_and_its_step_and_nonsense_is_refused():
    out = _run(
        """
        const temp = speech.PARAMETERS[0]
        const topk = speech.PARAMETERS[1]
        console.log(JSON.stringify([
          speech.parseNumber('0,73', temp), speech.parseNumber('7', temp), speech.parseNumber('-3', temp),
          speech.parseNumber('42.6', topk), speech.parseNumber('', speech.PAUSE), speech.parseNumber('abc', temp),
          speech.parseNumber('0', speech.PAUSE), speech.parseNumber('1e3', temp),
        ]))
        """
    )
    assert out == [0.75, 1, 0, 43, None, None, 0.1, None]


def test_the_voice_list_holds_the_voices_of_the_system_and_the_fields_of_a_voice_model_lock_with_one():
    page = (PHONE / "servers" / "SpeechSettings.svelte").read_text(encoding="utf-8")
    assert "report?.system_voices" in page
    assert "const voice = $derived(diktat.stimme ?? works.stimme ?? '')" in page
    # Layers, threads, sample and language lock one by one, the five values
    # through one loop: five places in the page.
    assert page.count("disabled={systemVoice}") == 5
    assert "{#each PARAMETERS as p (p.key)}" in page and "placeholder={t('parameter.auto')} disabled={systemVoice}" in page


def test_a_stored_voice_the_lists_do_not_carry_stands_in_the_field_under_its_own_name():
    phone = (PHONE / "servers" / "SpeechSettings.svelte").read_text(encoding="utf-8")
    assert "voice && !knownVoices.some((e) => e.value === voice)" in phone
    assert "[...knownVoices, { value: voice, label: voice }]" in phone
    window = (FRONTEND / "src" / "teile" / "Sprachserver.svelte").read_text(encoding="utf-8")
    assert "stimmewahl && !stimmeauswahl.some((e) => e.wert === stimmewahl)" in window
    assert "[...stimmeauswahl, { wert: stimmewahl, text: stimmewahl }]" in window


@needs_node
def test_a_voice_value_on_auto_is_an_empty_field_stored_as_the_word():
    """"Auto" in one of the five values is the word in the setting and an
    empty field on the page; an empty number would take the stored value away
    and bring back the works answer, which is not Auto."""
    out = _run(
        """
        console.log(JSON.stringify([
          speech.AUTO, speech.shownNumber('auto', 0.9), speech.shownNumber(null, 0.9),
          speech.worthStoring('auto', null, 0.9), speech.worthStoring('auto', 'auto', 0.9),
          speech.worthStoring(0.9, 'auto', 0.9), speech.worthStoring(0.9, null, 0.9),
        ]))
        """
    )
    assert out == ["auto", None, 0.9, True, False, True, False]


@needs_node
def test_a_number_is_shown_with_the_digits_of_its_step_and_nothing_as_empty():
    out = _run(
        """
        console.log(JSON.stringify([
          speech.numberText(0.9, {step: 0.05}), speech.numberText(50, {step: 1, whole: true}),
          speech.numberText(null, {step: 1}), speech.numberText(3, speech.PAUSE),
        ]))
        """
    )
    assert out == ["0.90", "50", "", "3.0"]


@needs_node
def test_the_clean_up_model_is_offered_only_once_a_file_stands_in_its_picker():
    out = _run(
        """
        const words = {aus: 'empty', putzmodell: 'Clean-up server', putzmodellLeer: 'Clean-up model - empty', modell: 'M', agent: 'A'}
        const without = speech.cleanerOptions(words, false).find((o) => o.value === 'putzmodell').label
        const withFile = speech.cleanerOptions(words, true).find((o) => o.value === 'putzmodell').label
        console.log(JSON.stringify([without, withFile, speech.cleanerOptions(words, true).length]))
        """
    )
    assert out == ["Clean-up model - empty", "Clean-up server", 4]


def test_a_switch_is_flipped_from_what_was_asked_last_and_a_value_is_sent_once():
    page = (PHONE / "servers" / "SpeechSettings.svelte").read_text(encoding="utf-8")
    assert "asked[key] ?? shown" in page
    assert "value === sent[key]" in page
    # What was typed a moment before the page goes is written too: texts and numbers.
    teardown = page.split("$effect(() => () => {", 1)[1].split("})", 1)[0]
    assert "commitText" in teardown and "commitNumber" in teardown
