"""The HTTP surface over sddownload: which GPU variants a picker could
offer, and choosing one when fetching the generator.

The fetch itself (network, unpacking, the folder it lands in) is
``app/sddownload.py``'s business and is proved in ``test_sddownload.py``,
including how ``waehlbare_varianten()`` and ``installierte_variante()``
answer on each platform. What matters here is the wiring: does the route
call those functions and shape the response, and does an unknown variant
get refused before it ever reaches ``Sddownload.starten()``. Mocked at
that boundary rather than by flipping ``sys.platform`` for the whole
process — the app runs real threads under the TestClient, and other code
reads the real platform along the way.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import sddownload
from app.config import Config


def test_varianten_route_ist_leer_ohne_auswahl(config: Config, client: TestClient, monkeypatch):
    monkeypatch.setattr(sddownload, "waehlbare_varianten", lambda: [])
    antwort = client.get("/api/v1/bild/programm/varianten")
    assert antwort.status_code == 200
    assert antwort.json() == {"varianten": [], "installiert": None}


def test_varianten_route_liefert_was_waehlbare_varianten_meldet(
    config: Config, client: TestClient, monkeypatch
):
    monkeypatch.setattr(
        sddownload, "waehlbare_varianten", lambda: [("cpu", 100), ("cuda12", 200)]
    )
    antwort = client.get("/api/v1/bild/programm/varianten")
    assert antwort.json()["varianten"] == [
        {"variante": "cpu", "groesse": 100}, {"variante": "cuda12", "groesse": 200},
    ]


def test_varianten_route_meldet_die_installierte_variante(
    config: Config, client: TestClient
):
    ordner = config.datenverzeichnis / sddownload.ORDNER / f"{sddownload.BAU}-vulkan"
    ordner.mkdir(parents=True)
    (ordner / sddownload.program_name()).write_bytes(b"x")

    antwort = client.get("/api/v1/bild/programm/varianten")
    assert antwort.json()["installiert"] == "vulkan"


def _fake_starten(aufgerufen: dict):
    def starten(self, variante=None, veroeffentlichung=None, replace_newer=False):
        aufgerufen["variante"] = variante
        aufgerufen["veroeffentlichung"] = veroeffentlichung
        aufgerufen["replace_newer"] = replace_newer
        self._stand = sddownload.Fortschritt(geladen=0, gesamt=0, fertig=True)
        return self._stand
    return starten


def test_holen_ohne_variante_verhaelt_sich_wie_heute(
    config: Config, client: TestClient, monkeypatch
):
    """No body at all — the caller never mentions a variant — must reach
    ``starten()`` with nothing, exactly as before this step."""
    aufgerufen: dict = {}
    monkeypatch.setattr(sddownload.Sddownload, "starten", _fake_starten(aufgerufen))
    antwort = client.post("/api/v1/bild/programm")
    assert antwort.status_code == 200
    assert aufgerufen["variante"] is None


def test_holen_mit_bekannter_variante_reicht_sie_durch(
    config: Config, client: TestClient, monkeypatch
):
    aufgerufen: dict = {}
    monkeypatch.setattr(sddownload.Sddownload, "starten", _fake_starten(aufgerufen))
    antwort = client.post("/api/v1/bild/programm", json={"variante": "cuda12"})
    assert antwort.status_code == 200
    assert aufgerufen["variante"] == "cuda12"


def test_holen_mit_unbekannter_variante_ist_400(config: Config, client: TestClient):
    antwort = client.post("/api/v1/bild/programm", json={"variante": "quanten"})
    assert antwort.status_code == 400
    assert antwort.json()["detail"]


# --- The update offer -------------------------------------------------------


def _veroeffentlichung(nummer: int) -> sddownload.Veroeffentlichung:
    return sddownload.Veroeffentlichung(
        bau=f"master-{nummer}-abc1234", nummer=nummer, darwin=("x.zip", 1),
        varianten={}, cudart=None,
    )


def test_aktualisierung_route_ohne_installation_ist_nicht_verfuegbar(
    config: Config, client: TestClient
):
    """Nothing on disk to compare against — the plain fetch already covers
    a fresh installation, so this route stays quiet rather than asking
    GitHub for nothing."""
    antwort = client.get("/api/v1/bild/programm/aktualisierung")
    assert antwort.json() == {"verfuegbar": False, "bau": None, "aktuell": False}


def test_aktualisierung_route_meldet_eine_neuere_fassung(
    config: Config, client: TestClient, monkeypatch
):
    ordner = config.datenverzeichnis / sddownload.ORDNER / sddownload.BAU
    ordner.mkdir(parents=True)
    (ordner / sddownload.program_name()).write_bytes(b"x")
    monkeypatch.setattr(
        sddownload, "neueste_veroeffentlichung", lambda: _veroeffentlichung(10**6)
    )
    antwort = client.get("/api/v1/bild/programm/aktualisierung")
    assert antwort.json() == {
        "verfuegbar": True, "bau": f"master-{10**6}-abc1234", "aktuell": False,
    }


def test_aktualisierung_route_ohne_neuere_fassung(config: Config, client: TestClient, monkeypatch):
    ordner = config.datenverzeichnis / sddownload.ORDNER / sddownload.BAU
    ordner.mkdir(parents=True)
    (ordner / sddownload.program_name()).write_bytes(b"x")
    monkeypatch.setattr(sddownload, "neueste_veroeffentlichung", lambda: _veroeffentlichung(1))
    antwort = client.get("/api/v1/bild/programm/aktualisierung")
    assert antwort.json() == {"verfuegbar": False, "bau": None, "aktuell": True}


def test_aktualisierung_route_ohne_erreichbare_fassung_ist_nicht_aktuell(
    config: Config, client: TestClient, monkeypatch
):
    """A release page that cannot be read compares nothing — not up to date,
    and nothing on offer either."""
    ordner = config.datenverzeichnis / sddownload.ORDNER / sddownload.BAU
    ordner.mkdir(parents=True)
    (ordner / sddownload.program_name()).write_bytes(b"x")
    monkeypatch.setattr(sddownload, "neueste_veroeffentlichung", lambda: None)
    antwort = client.get("/api/v1/bild/programm/aktualisierung")
    assert antwort.json() == {"verfuegbar": False, "bau": None, "aktuell": False}


def _installation(config: Config, variante: str | None = None) -> None:
    name = sddownload.BAU if variante is None else f"{sddownload.BAU}-{variante}"
    ordner = config.datenverzeichnis / sddownload.ORDNER / name
    ordner.mkdir(parents=True)
    (ordner / sddownload.program_name()).write_bytes(b"x")


def test_holen_mit_aktualisieren_reicht_die_neue_veroeffentlichung_durch(
    config: Config, client: TestClient, monkeypatch
):
    """The route re-reads the newest release itself rather than trust the
    client's word for which build that is — starten() ends up with the
    server's own, freshly-read Veroeffentlichung, not a value the request
    body could forge."""
    _installation(config)
    v = _veroeffentlichung(889)
    monkeypatch.setattr(sddownload, "neuere_fassung", lambda eigener_bau: v)
    aufgerufen: dict = {}
    monkeypatch.setattr(sddownload.Sddownload, "starten", _fake_starten(aufgerufen))
    antwort = client.post("/api/v1/bild/programm", json={"aktualisieren": True})
    assert antwort.status_code == 200
    assert aufgerufen["veroeffentlichung"] is v


def test_holen_mit_aktualisieren_ohne_neuere_fassung_ist_409(
    config: Config, client: TestClient, monkeypatch
):
    _installation(config)
    monkeypatch.setattr(sddownload, "neuere_fassung", lambda eigener_bau: None)
    antwort = client.post("/api/v1/bild/programm", json={"aktualisieren": True})
    assert antwort.status_code == 409


def test_holen_mit_aktualisieren_ohne_installation_ist_409(
    config: Config, client: TestClient, monkeypatch
):
    """An update is a catch-up on an existing install, not a second way to
    bootstrap one — nothing on disk means nothing to compare a release
    against, so this is refused before GitHub is even asked."""
    gefragt = []
    monkeypatch.setattr(
        sddownload, "neuere_fassung", lambda eigener_bau: gefragt.append(eigener_bau)
    )
    antwort = client.post("/api/v1/bild/programm", json={"aktualisieren": True})
    assert antwort.status_code == 409
    assert gefragt == []


def test_holen_mit_aktualisieren_ohne_variante_verwendet_die_installierte(
    config: Config, client: TestClient, monkeypatch
):
    """The panel sends no variant with the update click any more — the
    route resolves whichever one is actually on disk itself, rather than
    trust a `varianten` snapshot the panel might not have loaded yet."""
    _installation(config, "vulkan")
    monkeypatch.setattr(sddownload, "neuere_fassung", lambda eigener_bau: _veroeffentlichung(889))
    aufgerufen: dict = {}
    monkeypatch.setattr(sddownload.Sddownload, "starten", _fake_starten(aufgerufen))
    antwort = client.post("/api/v1/bild/programm", json={"aktualisieren": True})
    assert antwort.status_code == 200
    assert aufgerufen["variante"] == "vulkan"


# --- The way back to the tested build -------------------------------------

_NEWER = "master-989-c678dfe"


def _newer_installation(config: Config, variante: str | None = None) -> None:
    name = _NEWER if variante is None else f"{_NEWER}-{variante}"
    ordner = config.datenverzeichnis / sddownload.ORDNER / name
    ordner.mkdir(parents=True)
    (ordner / sddownload.program_name()).write_bytes(b"x")


def test_the_status_says_whether_there_is_a_build_to_go_back_from(
    config: Config, client: TestClient
):
    assert client.get("/api/v1/bild/modelle").json()["restorable"] is False
    _newer_installation(config)
    stand = client.get("/api/v1/bild/modelle").json()
    assert stand["bau"] == _NEWER
    assert stand["restorable"] is True


def test_restoring_fetches_the_pinned_build_in_place_of_the_installed_one(
    config: Config, client: TestClient, monkeypatch
):
    """No release is read and none is handed on: the pinned build is the
    one fetched, for the variant that is installed, and it replaces a
    newer one."""
    _newer_installation(config, "vulkan")
    monkeypatch.setattr(
        sddownload, "neuere_fassung",
        lambda eigener_bau: (_ for _ in ()).throw(AssertionError("a release was read")),
    )
    aufgerufen: dict = {}
    monkeypatch.setattr(sddownload.Sddownload, "starten", _fake_starten(aufgerufen))
    antwort = client.post("/api/v1/bild/programm", json={"restore": True})
    assert antwort.status_code == 200
    assert aufgerufen == {
        "variante": "vulkan", "veroeffentlichung": None, "replace_newer": True,
    }


def test_with_the_pinned_build_installed_there_is_nothing_to_restore(
    config: Config, client: TestClient, monkeypatch
):
    """Silence probe: the tested build is the one installed — refused, and
    nothing is fetched."""
    _installation(config)
    aufgerufen: dict = {}
    monkeypatch.setattr(sddownload.Sddownload, "starten", _fake_starten(aufgerufen))
    antwort = client.post("/api/v1/bild/programm", json={"restore": True})
    assert antwort.status_code == 409
    assert aufgerufen == {}


def test_a_plain_fetch_and_an_update_do_not_replace_a_newer_build(
    config: Config, client: TestClient, monkeypatch
):
    """Silence probe: only the word to restore removes a newer build."""
    _installation(config)
    monkeypatch.setattr(sddownload, "neuere_fassung", lambda eigener_bau: _veroeffentlichung(889))
    aufgerufen: dict = {}
    monkeypatch.setattr(sddownload.Sddownload, "starten", _fake_starten(aufgerufen))
    for body in (None, {"aktualisieren": True}):
        assert client.post("/api/v1/bild/programm", json=body).status_code == 200
        assert aufgerufen["replace_newer"] is False
