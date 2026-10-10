"""What a model IS, and everything that hangs on that one answer.

The handling used to be split in half: the starting values read the file
NAME, while the CFG lock and ``--guidance`` read "were separate files
supplied". A merged single-file Flux answered yes to the first and no to
the second, so it opened at flux's 832x1216 and then drew at a free CFG --
which the code's own comment calls noise. These pin the halves together.
"""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from app import bildbausatz, bildrunner, image_families
from app.bildrunner import Auftrag, Bildrunner


@pytest.fixture
def runner(tmp_path: Path):
    with mock.patch.object(bildrunner.shutil, "which", lambda _: "/irgendwo/sd-cli"):
        yield Bildrunner(tmp_path)


def _befehl(runner: Bildrunner, **felder) -> list[str]:
    auftrag = Auftrag(modell=Path("/m/x.gguf"), prompt="x", **felder)
    return runner.befehl(auftrag, Path("/tmp/a.png"))


def test_guidance_reist_auch_ohne_einzelteile(runner: Bildrunner):
    """The distilled guidance belongs to the MODEL, not to the way its
    files arrived. It used to live inside the branch that assembles a
    Gespann, so a merged single-file Flux -- the common case, one .gguf --
    could never receive it however the request was built."""
    befehl = _befehl(runner, guidance=2.5)
    assert "--guidance" in befehl
    assert befehl[befehl.index("--guidance") + 1] == "2.5"


def test_ohne_guidance_kein_schalter(runner: Bildrunner):
    """The silence half: unset stays unset. sd-cli's own default (3.5)
    applies through the flag's absence, exactly as it did before this
    field existed -- otherwise every plain SD-1.5 picture would quietly
    start carrying a guidance it never had."""
    assert "--guidance" not in _befehl(runner)


@pytest.mark.parametrize("familie, erwartet", [
    ("flux", True), ("flux2", True),
    ("zimage", False), ("sd15", False), ("sdxl", False),
])
def test_nur_flux_familien_haben_eine_guidance(familie, erwartet):
    """sd-cli calls --guidance the "distilled guidance scale for models
    with guidance input". flux and flux2 have that input, zimage does not,
    a plain model has none -- and the answer is read off the family's own
    starting values so the two lists cannot drift apart."""
    assert (image_families.start_values(familie).guidance is not None) is erwartet


def test_eine_familie_darf_auch_ohne_einzelteile_genannt_werden():
    """Naming the family is a statement about WHAT the model is, and every
    family may make it -- a merged Flux is still a Flux. Only Bausatz
    PARTS still require a Bausatz family, and only an unknown word is
    refused, so a renamed file can be set right by hand."""
    for familie in ("sd15", "sdxl", "flux", "zimage", "flux2"):
        bildbausatz.familie_pruefen(
            familie, diffusion_model=None, t5xxl=None, clip_l=None, clip_g=None, llm=None,
        )
    with pytest.raises(ValueError):
        bildbausatz.familie_pruefen(
            "unsinn", diffusion_model=None, t5xxl=None, clip_l=None, clip_g=None, llm=None,
        )
    # Parts still bind: a plain family cannot carry a diffusion model.
    with pytest.raises(ValueError):
        bildbausatz.familie_pruefen(
            "sd15", diffusion_model="d.gguf", t5xxl=None, clip_l=None, clip_g=None, llm=None,
        )


