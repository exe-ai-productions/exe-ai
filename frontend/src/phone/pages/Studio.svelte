<script module>
  export const meta = { name: 'studio', title: 'studio.titel', sign: 'bild', place: 'list', order: 36 }
</script>

<script>
  /* The picture studio on the phone, with a surface of its own: the picture
     as large as the room allows in the shape of the generation area, the
     pictures drawn paged through with a swipe, a strip of small ones under
     it, and the foot — four fields and one line to write in. The studio of
     the desktop (`ImageStudio`, columns and a drawing surface) does not
     stand here.

     What the desktop's surface does behind the scenes is done here: the
     line of pictures is handed to the draw, the studio's newest picture comes
     into the area when it is finished, the draw's progress is watched while
     one is drawing, and the picture and mask are handed over when a draw asks
     for them (`handover.js`). The fine settings — the desktop's left and right
     columns — stand under the sign at the right end of the head, in a panel
     that lies over the page; it stays in the page when it is shut, because
     the values fill themselves from the studio's store while it stands. */
  import { untrack } from 'svelte'
  import { bildLokalZeichnen, removeWaitingPicture, stopOnePicture } from '../../lib/bildlinie.svelte.js'
  import { openPictureMenu } from '../../lib/pictureMenu.svelte.js'
  import { pictureProgress, watchPicturePreview, watchPictureProgress } from '../../lib/pictureProgress.svelte.js'
  import {
    leinwand, newestIntoArea, startbildWaehlen, studio, studioPictures, surface, werte, werteVorschlagen,
  } from '../../lib/studio.svelte.js'
  import { zeichnung } from '../../lib/studiozeichnen.svelte.js'
  import { t } from '../../lib/texte.svelte.js'
  import { zustand } from '../../lib/zustand.svelte.js'
  import Hauszeichen from '../../teile/Hauszeichen.svelte'
  import StudioBasics from '../../teile/StudioBasics.svelte'
  import StudioDetails from '../../teile/StudioDetails.svelte'
  import { headRightSet } from '../head.svelte.js'
  import Area from '../studio/Area.svelte'
  import Compose from '../studio/Compose.svelte'
  import InfoSheet from '../studio/InfoSheet.svelte'
  import Mask from '../studio/Mask.svelte'
  import PictureSheet from '../studio/PictureSheet.svelte'
  import Strip from '../studio/Strip.svelte'
  import { handOver } from '../studio/handover.js'
  import { pagesOf, shownIndex, tilesOf } from '../studio/pager.js'
  import { chooseFile } from '../studio/upload.js'

  let settings = $state(false)
  let maskOpen = $state(false)

  /* The studio is open while this page stands. The desktop's way of opening
     it also rearranges its columns; the phone has none. */
  $effect(() => {
    studio.offen = true
    return () => {
      studio.offen = false
    }
  })

  // The line of pictures: drawing, stopping the one drawing, taking a waiting one out.
  $effect(() => {
    zeichnung.losZeichnen = bildLokalZeichnen
    zeichnung.stopEins = stopOnePicture
    zeichnung.entfernen = removeWaitingPicture
    return () => {
      zeichnung.losZeichnen = null
      zeichnung.stopEins = null
      zeichnung.entfernen = null
    }
  })

  // What a draw asks for: the picture and the mask as the area holds them.
  $effect(() => {
    leinwand.ausgeben = handOver
    return () => {
      if (leinwand.ausgeben === handOver) leinwand.ausgeben = null
    }
  })

  /* The studio's newest picture comes into the area by itself: its pictures
     are read when the page comes up and whenever its line of pictures
     changes — a picture that left the line is finished. */
  const line = $derived(zustand.pictureQueue.map((entry) => entry.id).join())
  $effect(() => {
    void line
    untrack(newestIntoArea)
  })

  const running = $derived(zustand.pictureQueue.find((entry) => entry.running) ?? null)
  const waiting = $derived(zustand.pictureQueue.filter((entry) => !entry.running))
  const percent = $derived(Math.round((pictureProgress.share || 0) * 100))
  /* Asked only while a picture is drawing — its counter, and its live
     preview where the picture is drawn with one. The watch follows the
     picture, not the line. */
  const runningId = $derived(running?.id ?? null)
  $effect(() => {
    if (runningId === null) return
    const stopProgress = watchPictureProgress()
    const stopPreview = watchPicturePreview(runningId)
    return () => {
      stopPreview()
      stopProgress()
    }
  })

  /* The original's file may be gone (the pictures folder was cleared): it
     then does not show. */
  let originalGone = $state('')
  let heldGone = $state('')
  const original = $derived(werte.original && originalGone !== werte.original ? werte.original : '')
  /* The picture in the area, when the studio does not hold it (chosen from the
     chat or a folder): it has its page and its tile as well. */
  const held = $derived(werte.startbild && werte.startbild !== heldGone ? werte.startbild : '')
  const pages = $derived(pagesOf({ running, held, original, names: studioPictures.names }))
  const tiles = $derived(tilesOf({ running, waiting, held, original, names: studioPictures.names }))
  const broken = (entry) => {
    if (entry.original) originalGone = entry.name
    else if (entry.name === werte.startbild) heldGone = entry.name
  }

  /* Which page is on show: the one the person last came to — by a swipe or a
     tap on the strip — and, with none, the one that holds the picture in the
     area. A picture drawn now comes forward by itself; a finished one takes
     the area (the newest is shown) and with it the surface. */
  let focus = $state('')
  const index = $derived.by(() => {
    const at = focus ? pages.findIndex((page) => page.key === focus) : -1
    return at >= 0 ? at : shownIndex(pages, werte.startbild)
  })
  const shownKey = $derived(pages[index]?.key ?? '')
  $effect(() => {
    void werte.startbild
    untrack(() => (focus = ''))
  })
  $effect(() => {
    if (runningId !== null) untrack(() => (focus = `run:${runningId}`))
  })

  /* A swipe that came to rest on a page: a picture is shown in the area (as
     the newest is — shown, not chosen: the mode and the strength stay), the
     picture drawing now is only shown. */
  function show(at) {
    const page = pages[at]
    if (!page) return
    focus = page.key
    if (page.kind === 'picture' && werte.startbild !== page.name) {
      werteVorschlagen({ startbild: page.name, maske: '' })
    }
  }
  /* A tile of the strip: the picture is chosen as the input, as on the
     desktop's row of pictures; the picture drawing now is only shown. */
  function pick(tile) {
    if (tile.kind === 'running') focus = tile.key
    else startbildWaehlen(tile.name)
  }

  /* A mask belongs to the picture it was painted on: another picture in the
     area leaves it behind, and the switch goes back to off. It also goes
     with the page. */
  $effect(() => {
    void werte.startbild
    untrack(() => {
      surface.maskOn = false
      surface.masked = false
    })
  })
  $effect(() => () => {
    surface.maskOn = false
    surface.masked = false
  })

  const openMask = () => {
    if (werte.startbild) maskOpen = true
  }

  /* The fine settings: a sign at the right end of the head. */
  $effect(() => headRightSet({ sign: 'feinheiten', label: t('studio.feinheiten'), onclick: () => (settings = true) }))
</script>

<div class="host">
  {#if maskOpen}
    <Mask name={werte.startbild} ondone={() => (maskOpen = false)} />
  {:else}
    <Area
      {pages}
      {index}
      width={werte.breite}
      height={werte.hoehe}
      onshow={show}
      onlong={(name) => openPictureMenu(name)}
      onempty={chooseFile}
      onbroken={broken}
    />
    <Strip {tiles} shown={shownKey} {percent} onpick={pick} onremove={(id) => zeichnung.entfernen?.(id)} onbroken={broken} />
    <Compose onmask={openMask} />
  {/if}

  <div class="settings" hidden={!settings}>
    <header class="top">
      <h2>{t('studio.feinheiten')}</h2>
      <button class="close" onclick={() => (settings = false)} aria-label={t('app.schliessen')}>
        <Hauszeichen zeichen="kreuz" groesse={16} />
      </button>
    </header>
    <StudioBasics />
    <StudioDetails />
  </div>
</div>

<PictureSheet onmask={openMask} />
<InfoSheet />

<style>
  .host {
    position: relative;
    height: 100%;
    display: flex;
    flex-direction: column;
  }
  .settings {
    position: absolute;
    inset: 0;
    z-index: 8;
    overflow-y: auto;
    background: var(--bg);
    padding: 0 4px calc(24px + env(safe-area-inset-bottom));
  }
  .settings[hidden] {
    display: none;
  }
  .top {
    display: flex;
    align-items: center;
    justify-content: space-between;
    min-height: 44px;
    padding: 0 6px;
  }
  h2 {
    margin: 0;
    font: 600 16px var(--schrift);
  }
  .close {
    display: grid;
    place-items: center;
    width: 44px;
    height: 44px;
    border: none;
    border-radius: 9px;
    background: none;
    color: var(--text-leise);
  }
</style>
