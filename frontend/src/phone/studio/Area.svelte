<script>
  /* The studio's surface on the phone: the picture as large as the room
     allows, in the shape of the generation area. The pictures stand side by
     side and are paged through with a swipe (the browser's own sideways
     scroll with a stop at every picture); the dots under it say where one
     stands. Two fingers zoom the picture on show, a double tap goes to its
     own size and back, a long press asks for its menu.

     The picture drawing now is the first page: its live preview where the
     service has one, a bar at the foot and the stop on a pill over it. */
  import { untrack } from 'svelte'
  import { api } from '../../lib/api.js'
  import { gestures } from '../../lib/pictureGesturesAction.js'
  import { pictureProgress } from '../../lib/pictureProgress.svelte.js'
  import { zeichnung } from '../../lib/studiozeichnen.svelte.js'
  import { t } from '../../lib/texte.svelte.js'
  import Hauszeichen from '../../teile/Hauszeichen.svelte'
  import { dotsOf, pageAt } from './pager.js'

  /* `pages` as `pagesOf` makes them, `index` the one on show, `width` and
     `height` the generation area's. `onshow(index)`: a swipe came to rest on
     another page. `onlong(name)`: a long press on a picture. `onempty()`: a
     tap on the empty surface. `onbroken(page)`: a picture's file is gone. */
  let { pages, index, width, height, onshow, onlong, onempty, onbroken } = $props()

  let room = $state({ w: 0, h: 0 })
  let roomNode = $state(null)
  $effect(() => {
    if (!roomNode) return
    const measure = () => {
      room = { w: roomNode.clientWidth, h: roomNode.clientHeight }
    }
    const watch = new ResizeObserver(measure)
    watch.observe(roomNode)
    measure()
    return () => watch.disconnect()
  })

  /* The box: the area's shape, as large as the room allows — which is what
     the row of dots under it leaves. */
  const DOTS_ROOM = 22
  const box = $derived.by(() => {
    const aw = Math.max(64, Number(width) || 1024)
    const ah = Math.max(64, Number(height) || 1024)
    const scale = Math.min(room.w / aw, (room.h - DOTS_ROOM) / ah)
    return { w: Math.floor(aw * scale), h: Math.floor(ah * scale) }
  })

  let pager = $state(null)
  const reduced = () => globalThis.matchMedia?.('(prefers-reduced-motion: reduce)').matches

  /* The page on show follows `index` — a picture laid in, a tile tapped, a
     new picture finished; the swipe's own rest reports itself below. */
  $effect(() => {
    const at = index
    void box.w
    void pages.length
    void pager
    untrack(() => {
      if (!pager || at < 0 || !box.w) return
      const target = at * box.w
      if (Math.abs(pager.scrollLeft - target) > 2) {
        pager.scrollTo({ left: target, behavior: reduced() ? 'auto' : 'smooth' })
      }
    })
  })

  /* A swipe reports itself when it comes to rest. Only a scroll that a finger
     began counts: a page list that changes under the surface (a picture
     finished, the one drawing gone) moves the scroll position by itself and
     must not read as a swipe to some other picture. */
  let touched = false
  let moved = false
  let rest = null
  const pressed = () => {
    touched = true
    moved = false
  }
  /* A touch that moved nothing (a tap, a long press) is over once it is lifted. */
  const lifted = () => {
    setTimeout(() => {
      if (!moved) touched = false
    }, 300)
  }
  function scrolled() {
    moved = true
    clearTimeout(rest)
    rest = setTimeout(() => {
      const swiped = touched
      touched = false
      if (!swiped || !pager || zoomed) return
      const at = pageAt(pager.scrollLeft, box.w, pages.length)
      if (at !== index) onshow?.(at)
    }, 90)
  }

  /* The zoom of the picture on show; it starts over with every other one. */
  let view = $state({ zoom: 1, x: 0, y: 0 })
  const zoomed = $derived(view.zoom > 1.001)
  const shownName = $derived(pages[index]?.name ?? pages[index]?.key ?? '')

  /* A picture's own size, noted when it has loaded: the double tap goes from
     the whole picture to this. */
  const naturals = new Map()
  const noteSize = (name) => (event) => {
    naturals.set(name, { w: event.currentTarget.naturalWidth, h: event.currentTarget.naturalHeight })
  }
  const natural = () => naturals.get(pages[index]?.name) ?? null
  /* The picture is shown whole inside the box, so its width is the box's or
     what its shape leaves of it. */
  const shown = () => {
    const nat = natural()
    if (!nat || !box.w) return null
    return { w: Math.min(box.w, (box.h * nat.w) / nat.h) }
  }

  const options = $derived({
    sideways: true,
    swipe: false,
    paint: false,
    resetKey: shownName,
    natural,
    shown,
    onview: (next) => (view = next),
    onlong: () => {
      const page = pages[index]
      if (page?.kind === 'picture') onlong?.(page.name)
    },
  })

  const running = $derived(pages.find((page) => page.kind === 'running') ?? null)
  const percent = $derived(Math.round((pictureProgress.share || 0) * 100))
  const dots = $derived(dotsOf(pages.length, index))
</script>

<div class="room" bind:this={roomNode}>
  {#if pages.length && index >= 0}
    <div
      class="pager"
      role="group"
      aria-label={t('studio.bilder')}
      class:locked={zoomed}
      style:width="{box.w}px"
      style:height="{box.h}px"
      bind:this={pager}
      onpointerdown={pressed}
      onpointerup={lifted}
      onpointercancel={lifted}
      onscroll={scrolled}
      use:gestures={options}
    >
      {#each pages as page, at (page.key)}
        <div class="slide">
          <div
            class="inner"
            style:transform={at === index && zoomed ? `translate(${view.x}px, ${view.y}px) scale(${view.zoom})` : null}
          >
            {#if page.kind === 'picture'}
              <img src={api.bildAdresse(page.name)} alt="" draggable="false" loading="lazy" decoding="async"
                   onload={noteSize(page.name)} onerror={() => onbroken?.(page)} />
            {:else}
              {#if pictureProgress.previewUrl}<img src={pictureProgress.previewUrl} alt="" draggable="false" />{/if}
            {/if}
          </div>
          {#if page.kind === 'running'}
            <span class="bar" style:width="{percent}%"></span>
            <div class="over">
              <span class="pill">
                {percent} %
                <span aria-hidden="true">·</span>
                <button onclick={() => zeichnung.stopEins?.(page.id)}>{t('bild.stopp')}</button>
              </span>
            </div>
          {/if}
        </div>
      {/each}
    </div>
    <div class="dots" aria-hidden="true">
      {#if dots.dots}
        {#each Array(dots.dots) as _, at (at)}<i class:on={at === dots.at}></i>{/each}
      {/if}
    </div>
  {:else}
    <button class="empty" style:width="{box.w}px" style:height="{box.h}px" onclick={() => onempty?.()}
            aria-label={t('bild.startbild')}>
      <Hauszeichen zeichen="bild" groesse={34} />
    </button>
    <div class="dots"></div>
  {/if}
</div>

<style>
  .room {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    margin: 0 12px;
  }
  /* The room the box may fill is what the dots leave. */
  .pager,
  .empty {
    flex: none;
    border-radius: 9px;
  }
  .pager {
    display: flex;
    overflow-x: auto;
    overflow-y: hidden;
    scroll-snap-type: x mandatory;
    overscroll-behavior-x: contain;
    scrollbar-width: none;
    background: var(--bg-hoch);
    /* The row is one thing to the finger: a zoom starts here, not on the
       page. */
    -webkit-user-select: none;
    user-select: none;
    -webkit-touch-callout: none;
  }
  .pager::-webkit-scrollbar {
    display: none;
  }
  /* Zoomed, one finger moves the picture: the row stands still. */
  .pager.locked {
    overflow-x: hidden;
  }
  .slide {
    position: relative;
    flex: 0 0 100%;
    height: 100%;
    overflow: hidden;
    scroll-snap-align: center;
    scroll-snap-stop: always;
  }
  .inner {
    width: 100%;
    height: 100%;
    transform-origin: 50% 50%;
  }
  .inner img {
    display: block;
    width: 100%;
    height: 100%;
    object-fit: contain;
    pointer-events: none;
  }
  /* The picture drawing: a bar of 3 px at the foot, the stop on a pill. */
  .bar {
    position: absolute;
    left: 0;
    bottom: 0;
    height: 3px;
    background: var(--blau);
  }
  .over {
    position: absolute;
    left: 0;
    right: 0;
    bottom: 0;
    padding: 12px;
    display: flex;
    justify-content: center;
    pointer-events: none;
  }
  .pill {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    height: 34px;
    padding: 0 14px;
    border-radius: 99px;
    font: 500 13px var(--schrift);
    color: var(--text);
    background: var(--glass-dropdown);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    -webkit-backdrop-filter: blur(16px);
    backdrop-filter: blur(16px);
    pointer-events: auto;
  }
  .pill button {
    padding: 0;
    border: none;
    background: none;
    color: inherit;
    font: inherit;
  }
  .empty {
    display: grid;
    place-items: center;
    padding: 0;
    border: 1.5px dashed var(--glass-button-edge);
    background: var(--glass-card);
    color: var(--text-still);
  }
  .dots {
    flex: none;
    height: 22px; /* DOTS_ROOM */
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
  }
  .dots i {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--text-still);
    opacity: 0.45;
  }
  .dots i.on {
    background: var(--text);
    opacity: 1;
  }
</style>
