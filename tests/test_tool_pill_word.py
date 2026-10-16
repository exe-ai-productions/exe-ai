"""The standing pill in the detail of a tool says active or inactive, the
two words every other state pill of the program uses, and not on or off.
Checked at the source, since there is no Svelte runtime harness here."""

from __future__ import annotations

import re
from pathlib import Path

SOURCE = Path(__file__).resolve().parent.parent / "frontend/src/teile/Werkzeuge.svelte"


def test_the_detail_pill_reads_active_and_inactive():
    source = SOURCE.read_text(encoding="utf-8")
    pill = re.search(
        r"<Standpille farbe=\{istAn\(gewaehltesWerkzeug\.name\)[^}]*\}>(.*?)</Standpille>",
        source,
        re.S,
    )
    assert pill, "the detail card has no standing pill"
    assert "'status.aktiv'" in pill.group(1)
    assert "'status.inaktiv'" in pill.group(1)
    assert "werkzeuge.an'" not in pill.group(1)
    assert "werkzeuge.aus'" not in pill.group(1)
