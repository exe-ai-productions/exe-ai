"""The page paints in the chosen look from the first frame.

The look lives with the service; the first frame comes before the service
has answered, so the chosen look is mirrored in the browser under one key,
and a script in the page head sets the attribute the stylesheet keys off
before anything is painted. Read off the source.
"""

from __future__ import annotations

import re
from pathlib import Path

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
SEITE = (FRONTEND / "index.html").read_text(encoding="utf-8")
ANZEIGE = (FRONTEND / "src/lib/anzeige.js").read_text(encoding="utf-8")


def test_die_seite_setzt_den_look_vor_dem_ersten_anstrich():
    kopf = SEITE.split("</head>", 1)[0]
    assert "localStorage.getItem('exe-modus')" in kopf
    assert "setAttribute('data-modus', modus)" in kopf
    # "auto" sets nothing: the stylesheet follows the device.
    assert "modus !== 'auto'" in kopf
    # The script stands before the module that mounts the app.
    assert kopf.index("exe-modus") < SEITE.index("/src/main.js")


def test_der_schluessel_ist_derselbe_und_wird_beim_waehlen_und_beim_laden_geschrieben():
    assert "export const MODUS_SCHLUESSEL = 'exe-modus'" in ANZEIGE
    # Written when the look is chosen and when it is loaded: two calls, one definition.
    assert ANZEIGE.count("modusVormerken(modus)\n") == 2
    # Silence probe: nothing else of the settings touches the browser's storage.
    code = re.sub(r"/\*.*?\*/", "", ANZEIGE, flags=re.S)
    assert code.count("localStorage") == 1
