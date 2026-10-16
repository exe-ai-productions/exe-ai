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

from types import SimpleNamespace

from fastapi.testclient import TestClient

from app import sddownload
from app.config import Config


def _windows(monkeypatch) -> None:
    """Only the generator's own module plays Windows — the variants exist
    there and nowhere else, and the rest of the program keeps the system it
    runs on (the app has real threads under the TestClient)."""
    monkeypatch.setattr(sddownload, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(sddownload.platform, "machine", lambda: "AMD64")


def _macos(monkeypatch) -> None:
    monkeypatch.setattr(sddownload, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(sddownload.platform, "machine", lambda: "arm64")


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
    config: Config, client: TestClient, monkeypatch
):
    _windows(monkeypatch)
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
    assert antwort.json() == {
        "verfuegbar": False, "bau": None, "aktuell": False, "unreadable": False,
    }


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
        "unreadable": False,
    }


def test_aktualisierung_route_ohne_neuere_fassung(config: Config, client: TestClient, monkeypatch):
    ordner = config.datenverzeichnis / sddownload.ORDNER / sddownload.BAU
    ordner.mkdir(parents=True)
    (ordner / sddownload.program_name()).write_bytes(b"x")
    monkeypatch.setattr(sddownload, "neueste_veroeffentlichung", lambda: _veroeffentlichung(1))
    antwort = client.get("/api/v1/bild/programm/aktualisierung")
    assert antwort.json() == {
        "verfuegbar": False, "bau": None, "aktuell": True, "unreadable": False,
    }


def test_aktualisierung_route_ohne_erreichbare_fassung_ist_nicht_aktuell(
    config: Config, client: TestClient, monkeypatch
):
    """A release page that cannot be read compares nothing — not up to date,
    nothing on offer, and the answer says the list was not readable, so the
    window can tell the user instead of showing nothing."""
    ordner = config.datenverzeichnis / sddownload.ORDNER / sddownload.BAU
    ordner.mkdir(parents=True)
    (ordner / sddownload.program_name()).write_bytes(b"x")
    monkeypatch.setattr(sddownload, "neueste_veroeffentlichung", lambda: None)
    antwort = client.get("/api/v1/bild/programm/aktualisierung")
    assert antwort.json() == {
        "verfuegbar": False, "bau": None, "aktuell": False, "unreadable": True,
    }


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
    _windows(monkeypatch)
    _installation(config, "vulkan")
    monkeypatch.setattr(sddownload, "neuere_fassung", lambda eigener_bau: _veroeffentlichung(889))
    aufgerufen: dict = {}
    monkeypatch.setattr(sddownload.Sddownload, "starten", _fake_starten(aufgerufen))
    antwort = client.post("/api/v1/bild/programm", json={"aktualisieren": True})
    assert antwort.status_code == 200
    assert aufgerufen["variante"] == "vulkan"


def test_am_mac_aktualisiert_ein_alter_variantenordner_das_eine_paket(
    config: Config, client: TestClient, monkeypatch
):
    """A Mac that still has a folder named for a backend from before the
    variants were refused: the update asks for the one package of the
    system, not for a variant it does not have — which would be answered
    with 'no package' for good."""
    _macos(monkeypatch)
    _installation(config, "vulkan")
    monkeypatch.setattr(sddownload, "neuere_fassung", lambda eigener_bau: _veroeffentlichung(889))
    aufgerufen: dict = {}
    monkeypatch.setattr(sddownload.Sddownload, "starten", _fake_starten(aufgerufen))
    antwort = client.post("/api/v1/bild/programm", json={"aktualisieren": True})
    assert antwort.status_code == 200
    assert aufgerufen["variante"] is None


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
    _windows(monkeypatch)
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


# --- The variant that was picked -------------------------------------------


def _picked(client: TestClient) -> str | None:
    wert = client.get("/api/v1/settings/global/bildprogramm_fassung").json()["wert"]
    return wert["variante"] if wert else None


def test_a_fetch_of_a_variant_is_what_the_program_remembers(
    config: Config, client: TestClient, monkeypatch
):
    """Vulkan picked beside a newer CPU build: the window is told vulkan runs,
    and the program starts it (the folder is the one the status names)."""
    _windows(monkeypatch)
    _newer_installation(config)  # a newer CPU build, the plain folder
    _installation(config, "vulkan")  # the pinned build of vulkan
    assert client.get("/api/v1/bild/programm/varianten").json()["installiert"] == "cpu"

    aufgerufen: dict = {}
    monkeypatch.setattr(sddownload.Sddownload, "starten", _fake_starten(aufgerufen))
    monkeypatch.setattr(sddownload, "neueste_veroeffentlichung", lambda: None)
    antwort = client.post("/api/v1/bild/programm", json={"variante": "vulkan"})
    assert antwort.status_code == 200
    assert _picked(client) == "vulkan"

    assert client.get("/api/v1/bild/programm/varianten").json()["installiert"] == "vulkan"
    assert client.get("/api/v1/bild/modelle").json()["bau"] == sddownload.BAU


def test_a_switch_fetches_the_newest_number_of_the_variant_asked_for(
    config: Config, client: TestClient, monkeypatch
):
    _windows(monkeypatch)
    _installation(config, "vulkan")
    neueste = _veroeffentlichung(889)
    neueste.varianten["cuda12"] = ("x.zip", 1)
    neueste.cudart = 1
    monkeypatch.setattr(sddownload, "neueste_veroeffentlichung", lambda: neueste)
    aufgerufen: dict = {}
    monkeypatch.setattr(sddownload.Sddownload, "starten", _fake_starten(aufgerufen))

    antwort = client.post("/api/v1/bild/programm", json={"variante": "cuda12"})
    assert antwort.status_code == 200
    assert aufgerufen == {
        "variante": "cuda12", "veroeffentlichung": neueste, "replace_newer": False,
    }
    assert _picked(client) == "cuda12"


def test_a_switch_keeps_to_the_pinned_build_when_the_newest_release_has_no_package(
    config: Config, client: TestClient, monkeypatch
):
    """Silence probe: a release that does not carry the variant must not turn
    a switch that worked into a refusal — the pinned build has one."""
    _windows(monkeypatch)
    _installation(config, "vulkan")
    neueste = _veroeffentlichung(889)  # carries no variant at all
    monkeypatch.setattr(sddownload, "neueste_veroeffentlichung", lambda: neueste)
    aufgerufen: dict = {}
    monkeypatch.setattr(sddownload.Sddownload, "starten", _fake_starten(aufgerufen))

    antwort = client.post("/api/v1/bild/programm", json={"variante": "cuda12"})
    assert antwort.status_code == 200
    assert aufgerufen["veroeffentlichung"] is None


def test_a_first_fetch_takes_the_pinned_build_not_the_newest(
    config: Config, client: TestClient, monkeypatch
):
    """Silence probe: nothing installed means nothing to switch from; the
    release page is not even read."""
    _windows(monkeypatch)
    monkeypatch.setattr(
        sddownload, "neueste_veroeffentlichung",
        lambda: (_ for _ in ()).throw(AssertionError("a release was read")),
    )
    aufgerufen: dict = {}
    monkeypatch.setattr(sddownload.Sddownload, "starten", _fake_starten(aufgerufen))

    antwort = client.post("/api/v1/bild/programm", json={"variante": "vulkan"})
    assert antwort.status_code == 200
    assert aufgerufen["veroeffentlichung"] is None
    assert _picked(client) == "vulkan"


def test_a_switch_to_a_variant_that_is_installed_in_the_newest_number_only_picks_it(
    config: Config, client: TestClient, monkeypatch
):
    """Both builds stand on disk, the CPU one runs. Asking for vulkan finds
    nothing to fetch — and is not an error: the pick is all that is left."""
    _windows(monkeypatch)
    _installation(config)
    _installation(config, "vulkan")
    # The fetch looks for a program it can run, as the starting does.
    for ordner in (config.datenverzeichnis / sddownload.ORDNER).iterdir():
        (ordner / sddownload.program_name()).chmod(0o755)
    monkeypatch.setattr(sddownload, "neueste_veroeffentlichung", lambda: None)
    assert client.get("/api/v1/bild/programm/varianten").json()["installiert"] == "vulkan"

    # The plain fetch finds the folder there and says so, as it always did.
    antwort = client.post("/api/v1/bild/programm", json={"variante": "cpu"})
    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["fertig"] is True
    assert _picked(client) == "cpu"
    assert client.get("/api/v1/bild/programm/varianten").json()["installiert"] == "cpu"


def test_nothing_is_remembered_off_windows(
    config: Config, client: TestClient, monkeypatch
):
    """Silence probe: no variants there, so no pick is stored."""
    _macos(monkeypatch)
    aufgerufen: dict = {}
    monkeypatch.setattr(sddownload.Sddownload, "starten", _fake_starten(aufgerufen))

    antwort = client.post("/api/v1/bild/programm", json={})
    assert antwort.status_code == 200
    assert _picked(client) is None


def test_an_unknown_variant_is_not_stored_as_the_pick(client: TestClient):
    antwort = client.put(
        "/api/v1/settings/global/bildprogramm_fassung", json={"wert": {"variante": "quanten"}}
    )
    assert antwort.status_code == 200
    assert antwort.json()["wert"] is None


def test_asking_for_the_variant_that_runs_is_still_already_there(
    config: Config, client: TestClient, monkeypatch
):
    """Silence probe: only a switch turns "already there" into a pick."""
    _windows(monkeypatch)
    _installation(config)
    (config.datenverzeichnis / sddownload.ORDNER / sddownload.BAU / sddownload.program_name()).chmod(
        0o755
    )
    monkeypatch.setattr(sddownload, "neueste_veroeffentlichung", lambda: None)

    antwort = client.post("/api/v1/bild/programm", json={"variante": "cpu"})
    assert antwort.status_code == 409
    assert _picked(client) is None
