"""The rule that travels inside a preview document, run for real.

This is JavaScript, and the suite is Python -- so node runs it, the same way
svelte-check is run from tests/test_frontend_check.py. The reason it is worth
the detour: a wrapper that quietly returned the document unchanged would look
byte for byte like one that worked, in the source view, in the download and
in the saved file. The only place the difference shows is the frame, and no
test looked there.

See frontend/src/lib/vorschauschutz.js.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

MODUL = (
    Path(__file__).resolve().parents[1]
    / "frontend"
    / "src"
    / "lib"
    / "vorschauschutz.js"
)

SKRIPT = """
import { mitSchutzregel } from %(modul)s

const faelle = {
  leer: mitSchutzregel(''),
  nichts: mitSchutzregel(null),
  undefiniert: mitSchutzregel(undefined),
  zahl: mitSchutzregel(42),
  ohne_doctype: mitSchutzregel('<h1>hi</h1>'),
  mit_doctype: mitSchutzregel('<!DOCTYPE html>\\n<html><body>hi</body></html>'),
  doctype_gross: mitSchutzregel('<!doctype HTML><html></html>'),
  doctype_mit_leerraum: mitSchutzregel('\\n  <!DOCTYPE html><html></html>'),
  svg: mitSchutzregel('<svg xmlns="http://www.w3.org/2000/svg"><circle r="1"/></svg>'),
  kommentar_zuerst: mitSchutzregel('<!-- hi --><!DOCTYPE html><html></html>'),
}
console.log(JSON.stringify(faelle))
"""


def _faelle():
    ausdruck = SKRIPT % {"modul": json.dumps(MODUL.as_uri())}
    lauf = subprocess.run(
        ["node", "--input-type=module", "-e", ausdruck],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert lauf.returncode == 0, (lauf.stdout + lauf.stderr)[-2000:]
    return json.loads(lauf.stdout)


MARKE = '<meta http-equiv="Content-Security-Policy"'


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
class TestSchutzregel:
    def test_jedes_dokument_bekommt_die_regel(self):
        """Including the shapes that are not documents at all."""
        for name, ergebnis in _faelle().items():
            assert MARKE in ergebnis, name

    def test_die_regel_schliesst_den_weg_nach_draussen(self):
        ergebnis = _faelle()["ohne_doctype"]
        assert "default-src 'none'" in ergebnis
        assert "connect-src 'none'" in ergebnis
        # Only what cannot leave the machine is allowed in.
        assert "img-src data: blob:" in ergebnis
        assert "http" not in ergebnis.split(MARKE)[1].split(">")[0]

    def test_die_regel_laesst_das_dokument_leben(self):
        """A page that cannot run is not a preview of that page."""
        ergebnis = _faelle()["ohne_doctype"]
        assert "script-src 'unsafe-inline'" in ergebnis
        assert "style-src 'unsafe-inline'" in ergebnis

    def test_ein_doctype_bleibt_vorn(self):
        """In front of it the browser would switch to quirks mode."""
        faelle = _faelle()
        for name in ("mit_doctype", "doctype_gross", "doctype_mit_leerraum"):
            assert faelle[name].lstrip().lower().startswith("<!doctype"), name
            assert faelle[name].index(MARKE) < faelle[name].lower().index("<html"), name

    def test_ohne_doctype_steht_die_regel_ganz_vorn(self):
        """A rule governs what is parsed after it, so nothing may precede it."""
        assert _faelle()["ohne_doctype"].startswith(MARKE)

    def test_der_inhalt_bleibt_erhalten(self):
        """The rule is added, never at the cost of the document."""
        faelle = _faelle()
        assert "<h1>hi</h1>" in faelle["ohne_doctype"]
        assert "<body>hi</body>" in faelle["mit_doctype"]
        assert "<circle r=\"1\"/>" in faelle["svg"]
