"""The picture studio and the chats share nothing.

The studio keeps its picture, its mask, its model and every value once, for
itself, in a store that belongs to no chat (`lib/studioStore.svelte.js`,
the global scope under `bildfenster`). Opening, switching, creating or
deleting a chat changes none of it; drawing in the studio opens no chat and
writes into none; its row of pictures lists the pictures the studio drew.

Run rather than read: the studio's modules run in node (the harness of
`tests/studio_test_run.py`); the service and the window's state are
stand-ins.
"""

from __future__ import annotations

from pathlib import Path

from tests.studio_test_run import needs_node, run

FRONTEND = Path(__file__).resolve().parent.parent / "frontend" / "src"


@needs_node
def test_picture_mask_model_and_values_stand_through_every_chat_change():
    """A picture in the area, a mask painted on it, a model picked and a
    prompt typed: chat A, chat B, a new chat, chat A deleted — all of it
    stands as it was, and nothing was written into a chat."""
    report = run("""
    stubs.mounted()
    await settled()
    studio.startbildWaehlen('area.png')
    studio.werte.modell = 'picked-model'
    studio.werte.prompt = 'a lighthouse'
    studio.werte.schritte = 31
    stubs.changed()
    const mask = studio.studioMask('area.png')
    Object.assign(mask, { stored: 'mask.png', verlauf: [1, 2, 3] })
    const before = reading()
    for (const id of ['chat-a', 'chat-b', null, 'new-1', 'chat-a', null]) {
      await stubs.openChat(id)
      await settled()
    }
    await stubs.deleteChat('chat-a')
    await settled()
    await flushed()
    const after = reading()
    const same = studio.studioMask('area.png') === mask && mask.verlauf.length === 3
    return {
      before, after, same,
      created: calls.filter((c) => c[0] === 'create').length,
      scopes: [...new Set(written().map((c) => c[1]))],
    }
    """)
    assert report["same"] is True
    for name in ("startbild", "modell", "prompt", "schritte"):
        assert report["after"][name] == report["before"][name], name
    assert report["after"]["startbild"] == "area.png"
    assert report["after"]["modell"] == "picked-model"
    assert report["created"] == 0
    # Whatever was written went into the one scope that belongs to no chat.
    assert set(report["scopes"]) <= {"global"}, report["scopes"]


@needs_node
def test_a_changed_value_is_written_whole_into_the_global_scope_and_read_back():
    """The store keeps the studio's own values once; after a restart (a new
    run of the modules over what the service holds) they stand again."""
    first = run("""
    stubs.mounted()
    await settled()
    studio.werte.prompt = 'a harbour at dusk'
    studio.werte.breite = 768
    studio.startbildWaehlen('picked.png')
    studio.werte.modell = 'picked-model'
    stubs.changed()
    await settled()
    await flushed()
    return { stores: service.stores, writes: written() }
    """)
    stored = first["stores"]["global"]["bildfenster"]
    assert stored["prompt"] == "a harbour at dusk" and stored["breite"] == 768
    assert stored["startbild"] == "picked.png" and stored["modell"] == "picked-model"
    assert set(first["stores"]) == {"global"}
    assert {tuple(write[1:]) for write in first["writes"]} == {("global", "bildfenster")}

    import json

    second = run(f"""
    service.stores.global = {{ bildfenster: {json.dumps(stored)} }}
    stubs.mounted()
    await settled()
    return {{ ...reading(), writes: written().length }}
    """)
    assert second["prompt"] == "a harbour at dusk" and second["breite"] == 768
    assert second["startbild"] == "picked.png" and second["modell"] == "picked-model"
    # Opening writes nothing: what was shown is what was stored.
    assert second["writes"] == 0


@needs_node
def test_a_press_without_a_chat_opens_none_and_with_one_writes_into_none():
    """No chat open, a press on "draw": the request says it is the studio's,
    names no chat and the window opens none. The same press with a chat open
    names that chat just as little."""
    report = run("""
    stubs.mounted()
    await settled()
    studio.werte.prompt = 'a cat on a roof'
    studio.werte.modell = 'picture-model'
    await draw.studioZeichnen()
    await settled()
    await stubs.openChat('chat-a')
    await settled()
    await draw.studioZeichnen()
    await settled()
    return {
      wishes: wishes.map((w) => ({ studio: w.studio, chat_id: w.chat_id, prompt: w.prompt,
                                    has: Object.keys(w).includes('frage_erstellen') })),
      created: calls.filter((c) => c[0] === 'create').length,
      said,
    }
    """)
    assert report["created"] == 0
    assert report["said"] == []
    assert len(report["wishes"]) == 2
    for wish in report["wishes"]:
        assert wish["studio"] is True
        assert wish.get("chat_id") is None
        assert wish["prompt"] == "a cat on a roof"
        assert wish["has"] is False


@needs_node
def test_a_press_waits_for_the_studios_store_and_says_when_it_cannot_be_read():
    """Silence probe and its counterpart: with the store readable the press
    draws; with the read failing nothing is drawn and the failure is said."""
    ok = run("""
    studio.werte.prompt = 'x'
    studio.werte.modell = 'picture-model'
    await draw.studioZeichnen()
    await settled()
    return { drawn: wishes.length }
    """)
    assert ok["drawn"] == 1
    failed = run("""
    service.readFails = true
    studio.werte.prompt = 'x'
    studio.werte.modell = 'picture-model'
    await draw.studioZeichnen()
    await settled()
    return { drawn: wishes.length, said }
    """)
    assert failed["drawn"] == 0
    assert failed["said"] == [["store unreadable", "fehler"]]


@needs_node
def test_a_finished_picture_of_the_studio_stands_in_the_area_whichever_chat_is_open():
    """The studio's pictures are read when it opens and whenever its line
    changes; a newer one after a press is a finished one and stands in the
    area — also when the chat was switched meanwhile. A picture the list
    already held does not come in by itself while a picture lies there."""
    report = run("""
    service.studioList = ['old.png']
    stubs.mounted()
    await studio.newestIntoArea()
    await settled()
    const opened = studio.werte.startbild
    // The window's gallery reads the same list.
    const listed = [...studio.studioPictures.names]
    draw.zeichnung.losZeichnen = (wish) => wishes.push(wish)
    studio.werte.prompt = 'new one'
    studio.werte.modell = 'picture-model'
    await draw.studioZeichnen()
    await settled()
    await stubs.openChat('chat-b')
    service.studioList = ['new.png', 'old.png']
    await studio.newestIntoArea()
    await settled()
    return { opened, listed, area: studio.werte.startbild, names: [...studio.studioPictures.names],
             asked: calls.filter((c) => c[0] === 'list').map((c) => c[1]) }
    """)
    # The studio opened with no picture of its own: the newest it has.
    assert report["opened"] == "old.png"
    assert report["listed"] == ["old.png"]
    assert report["area"] == "new.png"
    assert report["names"] == ["new.png", "old.png"]
    # Always the studio's list, never a chat's or a project's.
    assert set(report["asked"]) == {'{"studio":true}'}


@needs_node
def test_a_picture_chosen_before_the_store_arrived_outlives_it_and_is_written():
    """A picture handed over while the store is still on its way is noted;
    the late store does not put its own start picture back, and what was
    typed meanwhile stays — both are the studio's own from then on."""
    report = run("""
    service.stores.global = { bildfenster: { startbild: 'stored.png', prompt: 'stored prompt', breite: 640 } }
    // The column fills before the store is read: the start values only.
    stubs.mounted()
    studio.startbildWaehlen('handed.png')
    studio.werte.prompt = 'typed meanwhile'
    await speicher.readStudioStore()
    stubs.mounted()
    await settled()
    await flushed()
    return { ...reading(), written: service.stores.global.bildfenster }
    """)
    assert report["startbild"] == "handed.png"
    assert report["prompt"] == "typed meanwhile"
    # What the store held and nobody touched is filled in.
    assert report["breite"] == 640
    assert report["written"]["startbild"] == "handed.png"
    assert report["written"]["prompt"] == "typed meanwhile"


@needs_node
def test_nothing_is_written_before_the_store_was_read():
    """A write that started first would land on the defaults and take the
    siblings with it: before the read, a change is held back and written
    with the rest once the store is there."""
    report = run("""
    service.stores.global = { bildfenster: { schritte: 9, prompt: 'kept' } }
    service.readDelay = 600
    stubs.mounted()
    studio.werte.negativ = 'blurry'
    stubs.changed()
    await flushed()
    const before = written().length
    await speicher.readStudioStore()
    stubs.mounted()
    await settled()
    await flushed()
    return { before, stored: service.stores.global.bildfenster }
    """)
    assert report["before"] == 0
    assert report["stored"]["schritte"] == 9 and report["stored"]["prompt"] == "kept"
    assert report["stored"]["negativ"] == "blurry"


@needs_node
def test_the_chats_state_holds_no_picture_values_and_writes_only_where_it_looks():
    """The chat's own store carries the place it was read at and nothing
    of the studio: opening a chat reads no picture values, and the studio's
    writes do not go through it."""
    report = run("""
    stubs.mounted()
    await stubs.openChat('chat-a')
    await settled()
    studio.werte.prompt = 'something'
    stubs.changed()
    await settled()
    await flushed()
    return {
      keys: Object.keys(chatanzeige.chatanzeige).sort(),
      chatReads: calls.filter((c) => c[0] === 'read-chat').map((c) => c[2]),
      writes: written().map((c) => c.slice(1)),
    }
    """)
    assert "bildfenster" not in report["keys"]
    assert report["chatReads"] == [["scrollstelle"]]
    assert report["writes"] == [["global", "bildfenster"]]


def test_no_part_of_the_studio_holds_a_chat_any_more():
    """Source silence probe: the pieces the old binding was made of are gone
    from every file of the studio."""
    names = (
        "lib/studio.svelte.js", "lib/studiozeichnen.svelte.js", "lib/studiobilder.svelte.js",
        "lib/studioStore.svelte.js", "teile/StudioBasics.svelte", "teile/StudioCanvas.svelte",
        "teile/StudioDetails.svelte", "teile/StudioGallery.svelte", "teile/StudioPictureInfo.svelte",
    )
    for name in names:
        text = (FRONTEND / name).read_text(encoding="utf-8")
        for gone in ("chatanzeige", "chatless", "maskIntoChat", "maskeDesChats", "CARRIED",
                     "chatPictures", "openNewChat", "chat_id"):
            assert gone not in text, f"{name} still has {gone}"
    state = (FRONTEND / "lib/chatanzeige.svelte.js").read_text(encoding="utf-8")
    assert "bildfenster" not in state
    assert "chatless" not in state and "bildfensterAusDemStudio" not in state


def test_the_row_of_pictures_has_no_choice_between_chat_and_project():
    """The row shows the studio's pictures: no scope field, no project read."""
    rail = (FRONTEND / "teile/StudioGallery.svelte").read_text(encoding="utf-8")
    assert "Auswahlfeld" not in rail and "projekt" not in rail and "api.bilderListe" not in rail
    assert "dieser_chat" not in rail and "ganzes_projekt" not in rail
    assert "const bilder = $derived(studioPictures.names)" in rail


def test_the_studios_bar_and_progress_read_no_chat():
    """The line of pictures belongs to the studio: the gallery and the area
    take the whole of it."""
    rail = (FRONTEND / "teile/StudioGallery.svelte").read_text(encoding="utf-8")
    canvas = (FRONTEND / "teile/StudioCanvas.svelte").read_text(encoding="utf-8")
    assert "const laufend = $derived(zustand.pictureQueue.find((w) => w.running) ?? null)" in rail
    assert "const wartend = $derived(zustand.pictureQueue.filter((w) => !w.running))" in rail
    assert "const laufend = $derived(zustand.pictureQueue.find((w) => w.running) ?? null)" in canvas
    assert "const inLine = $derived(zustand.pictureQueue.length > 0)" in canvas
    app = (FRONTEND / "App.svelte").read_text(encoding="utf-8")
    line = (FRONTEND / "lib/bildlinie.svelte.js").read_text(encoding="utf-8")
    assert "bildLaeuftChat" not in app and "bildChatsAktualisieren" not in app
    assert "bildLaeuftChat" not in line and "bildChatsAktualisieren" not in line
    assert "chat_id" not in line.split("function pictureLineRefresh() {", 1)[1].split("\n}\n", 1)[0]


def test_the_terminal_listens_to_the_studios_runs_while_the_studio_is_shown():
    """The studio draws without a chat, so its runs are filed under the key
    of its own: the terminal is connected to it while the studio is what the
    window shows, and to the open chat otherwise."""
    app = (FRONTEND / "App.svelte").read_text(encoding="utf-8")
    assert "terminalVerbinden(studioSichtbar() ? STUDIO_RUNS : zustand.aktiverChat)" in app
    window = (FRONTEND / "lib/terminalfenster.svelte.js").read_text(encoding="utf-8")
    assert "export const STUDIO_RUNS = 'studio'" in window
    server = (FRONTEND.parent.parent / "app" / "bildlauf.py").read_text(encoding="utf-8")
    assert 'STUDIO = "studio"' in server
