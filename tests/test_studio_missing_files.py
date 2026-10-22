"""A file a choice of the studio names and its folder does not hold goes nowhere.

The fields of the studio that name one file of a companion folder (the upscaler,
the tiny autoencoder, the detector, PuLID, the control net, the upscaler of the
highres pass) and the two stacks of LoRAs may still name a file that was taken
out of the folder. Drawn like that, the service refuses the picture ("no such
companion file") and the studio draws nothing until someone finds the choice.
After the lists are read the studio stands at "-" for such a choice, shows it
and sends nothing for it — shown, not written: the store keeps what it holds,
the file may come back (`missingFiles` in `lib/studio.svelte.js`, called
where the column fills the values).

The studio's own modules run for real in node (`studio_test_run.py`).
"""

from __future__ import annotations

import pytest

from tests.studio_test_run import FRONTEND, needs_node, run

LISTS = """
studio.listen.geladen = true
studio.listen.taesd = ['taesdxl.safetensors']
studio.listen.upscalers = ['x2.pth']
studio.listen.upscalerFeste = ['ESRGAN_4x']
studio.listen.yolos = ['face.pt']
studio.listen.pulids = ['pulid.safetensors']
studio.listen.pulidEmbeddings = ['id.safetensors']
studio.listen.controlnets = ['canny.safetensors']
studio.listen.loras = ['a.safetensors']
"""

FIELDS = [
    ("taesd", "taesdxl.safetensors"),
    ("upscale_model", "x2.pth"),
    ("ad_modell", "face.pt"),
    ("pulid_weights", "pulid.safetensors"),
    ("pulid_id_embedding", "id.safetensors"),
    ("control_net", "canny.safetensors"),
    ("hires_upscaler", "x2.pth"),
]


@needs_node
@pytest.mark.parametrize(("field", "there"), FIELDS)
def test_a_choice_whose_file_is_gone_is_taken_back_and_one_that_is_there_stays(field, there):
    report = run(f"""{LISTS}
    studio.werte.{field} = 'gone.bin'
    const gone = studio.missingFiles()
    studio.werte.{field} = {there!r}
    const kept = studio.missingFiles()
    return {{ gone, kept }}
    """)
    assert report["gone"] == {field: ""}, report
    assert report["kept"] == {}, report


@needs_node
def test_a_built_in_name_of_the_highres_upscaler_is_no_file_and_stays():
    report = run(f"""{LISTS}
    studio.werte.hires_upscaler = 'ESRGAN_4x'
    return studio.missingFiles()
    """)
    assert report == {}, report


@needs_node
def test_nothing_is_judged_before_the_lists_were_read():
    """Silence probe: while the lists are not there (or could not be read) every
    choice stays as it is."""
    report = run("""
    studio.listen.geladen = false
    studio.werte.taesd = 'gone.safetensors'
    studio.werte.upscale_model = 'gone.pth'
    studio.werte.stapel = [{ name: 'gone.safetensors', staerke: 0.7 }]
    return studio.missingFiles()
    """)
    assert report == {}, report


@needs_node
def test_a_stack_loses_the_loras_the_folder_does_not_hold():
    report = run(f"""{LISTS}
    studio.werte.stapel = [{{ name: 'a.safetensors', staerke: 0.7 }}, {{ name: 'gone.safetensors', staerke: 1 }}]
    studio.werte.ad_stapel = [{{ name: 'gone.safetensors', staerke: 1 }}]
    return studio.missingFiles()
    """)
    assert report == {"stapel": [{"name": "a.safetensors", "staerke": 0.7}], "ad_stapel": []}, report


@needs_node
def test_the_draw_after_that_carries_no_file_that_is_gone_and_still_draws():
    """Falls over without the fix: the missing file went out and the service
    refused the picture."""
    report = run(f"""{LISTS}
    studio.werte.modell = 'picture-model'
    studio.werte.prompt = 'a cat'
    studio.werte.live_preview = 'tae'
    studio.werte.taesd = 'gone.safetensors'
    studio.werte.ad_modell = 'gone.pt'
    studio.werteVorschlagen(studio.missingFiles())
    await draw.studioZeichnen()
    await settled()
    const wish = wishes[0]
    return {{ drawn: wishes.length, taesd: wish?.taesd, ad: wish?.ad_modell }}
    """)
    assert report == {"drawn": 1, "taesd": None, "ad": None}, report


@needs_node
def test_the_draw_carries_a_file_that_is_there():
    """Silence probe: the choice whose file the folder holds goes out."""
    report = run(f"""{LISTS}
    studio.werte.modell = 'picture-model'
    studio.werte.prompt = 'a cat'
    studio.werte.live_preview = 'tae'
    studio.werte.taesd = 'taesdxl.safetensors'
    studio.werte.ad_modell = 'face.pt'
    studio.werteVorschlagen(studio.missingFiles())
    await draw.studioZeichnen()
    await settled()
    const wish = wishes[0]
    return {{ taesd: wish?.taesd, ad: wish?.ad_modell }}
    """)
    assert report == {"taesd": "taesdxl.safetensors", "ad": "face.pt"}, report


@needs_node
def test_taking_a_choice_back_is_shown_and_not_written():
    """The store keeps what it holds: the file may come back with the folder."""
    report = run(f"""{LISTS}
    service.stores.global = {{ bildfenster: {{ taesd: 'gone.safetensors', prompt: 'stored' }} }}
    stubs.mounted()
    await speicher.readStudioStore()
    stubs.mounted()
    await settled()
    studio.werteVorschlagen(studio.missingFiles())
    stubs.changed()
    await flushed()
    return {{ shown: studio.werte.taesd, written: calls.filter((c) => c[0] === 'write').length,
             stored: service.stores.global.bildfenster.taesd }}
    """)
    assert report == {"shown": "", "written": 0, "stored": "gone.safetensors"}, report


def test_the_column_takes_the_choices_back_where_it_fills_the_values():
    basics = (FRONTEND / "src/teile/StudioBasics.svelte").read_text(encoding="utf-8")
    assert "werteVorschlagen(missingFiles())" in basics
    # After the lists (the model's own check stands before it).
    assert basics.index("await listenDa") < basics.index("werteVorschlagen(missingFiles())")
