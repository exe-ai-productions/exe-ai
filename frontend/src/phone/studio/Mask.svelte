<script>
  /* The mask page: the picture across the page's width and four tools under
     it — brush, eraser, invert, clear. One finger paints or erases, two
     fingers move and zoom the picture (never paint); a vertical slider at the
     right edge sets the brush's size, undo and redo lie on the picture's top
     left. "Cancel" and "Done" stand in the head. Done takes the mask into the
     draw: the field "Mask" over the prompt then wears its dot.

     The mask is painted at the picture's own size with the desktop's brush
     (`lib/maske.js`) and kept in the same session store (`studioMask`), so a
     mask painted here is the one the draw hands over (`handover.js`). */
  import { gestures } from '../../lib/pictureGesturesAction.js'
  import { aufFlaeche, bemalt, malflaeche, strich } from '../../lib/maske.js'
  import { releaseLayers, studioMask, surface, werte } from '../../lib/studio.svelte.js'
  import { t } from '../../lib/texte.svelte.js'
  import { melde } from '../../lib/zustand.svelte.js'
  import { api } from '../../lib/api.js'
  import MaskenZeichen from '../../teile/MaskenZeichen.svelte'
  import SubHead from '../parts/SubHead.svelte'
  import { loadPicture } from './handover.js'
  import { applyStep, loadStored, replay } from './maskwork.js'

  /* `name`: the picture in the area. `ondone()`: the page is left. */
  let { name, ondone } = $props()

  // What the eye sees of the mask: the painted layer in this colour, at this strength.
  const TINT = 'rgba(90, 150, 255, 1)'
  const TINT_STRENGTH = 0.55
  const SIZE_MIN = 4
  const SIZE_MAX = 240

  let natural = $state(null)
  let mask = $state.raw(null)
  // Counts every change of the mask, so what reads it follows.
  let count = $state(0)
  let tool = $state('pinsel')
  let size = $state(48)
  let hinted = $state(false)

  /* The steps and the redo list as the page found them: "Cancel" goes back
     to them. */
  let atOpen = null
  let dirty = false

  let stageNode = $state(null)
  let stage = $state({ w: 0, h: 0 })
  $effect(() => {
    if (!stageNode) return
    const measure = () => {
      stage = { w: stageNode.clientWidth, h: stageNode.clientHeight }
    }
    const watch = new ResizeObserver(measure)
    watch.observe(stageNode)
    measure()
    return () => watch.disconnect()
  })

  /* The picture whole inside the stage: its box. */
  const box = $derived.by(() => {
    if (!natural || !stage.w) return { w: 0, h: 0 }
    const fit = Math.min(stage.w / natural.w, stage.h / natural.h)
    return { w: Math.floor(natural.w * fit), h: Math.floor(natural.h * fit) }
  })

  let view = $state({ zoom: 1, x: 0, y: 0 })
  let picbox = $state(null)
  let seen = $state(null)

  function draw() {
    if (!seen || !mask?.flaeche) return
    const layer = mask.flaeche
    if (seen.width !== layer.width) seen.width = layer.width
    if (seen.height !== layer.height) seen.height = layer.height
    const pen = seen.getContext('2d')
    pen.clearRect(0, 0, seen.width, seen.height)
    pen.drawImage(layer, 0, 0)
    pen.save()
    pen.globalCompositeOperation = 'source-in'
    pen.fillStyle = TINT
    pen.fillRect(0, 0, seen.width, seen.height)
    pen.restore()
  }

  /* While a finger moves, the layer is redrawn once per frame, not once per
     pointer event: a large picture's layer is costly to tint. */
  let frame = 0
  function drawSoon() {
    if (frame) return
    frame = requestAnimationFrame(() => {
      frame = 0
      draw()
    })
  }

  /* The picture loaded: the mask of this picture comes forward — the one
     painted this session, else the one the studio has stored, else an empty
     layer at the picture's size. */
  function prepare(width, height) {
    const found = studioMask(name)
    const fits = (w, h) => w === width && h === height
    if (!found.flaeche || !fits(found.flaeche.width, found.flaeche.height)) {
      const givenBack = !found.flaeche && Boolean(found.size) && fits(...found.size)
      if (found.flaeche) releaseLayers(found)
      if (!givenBack) Object.assign(found, { stored: werte.maske, verlauf: [], zukunft: [] })
      found.flaeche = malflaeche(width, height)
      if (givenBack) replay(found)
      if (found.stored) loadStored(found, found.flaeche, found.stored, () => { count += 1; draw() })
    }
    mask = found
    atOpen = { verlauf: [...found.verlauf], zukunft: [...found.zukunft] }
    count += 1
  }

  $effect(() => {
    const wanted = name
    let current = true
    loadPicture(wanted)
      .then((image) => {
        if (!current) return
        natural = { w: image.naturalWidth, h: image.naturalHeight }
        prepare(image.naturalWidth, image.naturalHeight)
      })
      .catch((error) => melde(String(error.message || error), 'fehler'))
    return () => {
      current = false
    }
  })
  $effect(() => {
    void count
    void box.w
    draw()
  })

  // --- painting -----------------------------------------------------------

  let stroke = null
  const onLayer = (point) => aufFlaeche({ clientX: point.x, clientY: point.y }, picbox, mask.flaeche)

  function begin(point) {
    if (!mask?.flaeche || !picbox) return
    const here = onLayer(point)
    const erase = tool === 'radierer'
    stroke = { art: 'strich', punkte: [here], groesse: size, radiert: erase }
    strich(mask.flaeche, here, here, size, erase)
    hinted = true
    draw()
  }
  function more(point) {
    if (!stroke || !mask?.flaeche) return
    const here = onLayer(point)
    const points = stroke.punkte
    strich(mask.flaeche, points[points.length - 1], here, stroke.groesse, stroke.radiert)
    points.push(here)
    drawSoon()
  }
  /* One step is one stroke, finger down to finger up. */
  function end() {
    if (!stroke || !mask) return
    mask.verlauf.push(stroke)
    mask.zukunft = []
    stroke = null
    draw()
    changed()
  }
  /* A second finger came: what the first one painted is void. */
  function drop() {
    if (!stroke || !mask?.flaeche) return
    stroke = null
    replay(mask)
    draw()
  }
  function changed() {
    dirty = true
    count += 1
  }

  const canUndo = $derived(count >= 0 && Boolean(mask?.verlauf.length))
  const canRedo = $derived(count >= 0 && Boolean(mask?.zukunft.length))
  function undo() {
    if (!canUndo) return
    mask.zukunft.push(mask.verlauf.pop())
    replay(mask)
    changed()
  }
  function redo() {
    if (!canRedo) return
    mask.verlauf.push(mask.zukunft.pop())
    replay(mask)
    changed()
  }
  function whole(kind) {
    if (!mask?.flaeche) return
    const step = { art: kind }
    applyStep(mask.flaeche, step)
    mask.verlauf.push(step)
    mask.zukunft = []
    changed()
  }
  const hasPaint = $derived(count >= 0 && mask?.flaeche ? bemalt(mask.flaeche) : false)

  const options = $derived({
    paint: true,
    swipe: false,
    resetKey: name,
    natural: () => natural,
    shown: () => (box.w ? { w: box.w } : null),
    onview: (next) => (view = next),
    onpaintstart: begin,
    onpaintmove: more,
    onpaintend: end,
    onpaintcancel: drop,
  })

  // --- the size ---------------------------------------------------------------

  let sizeNode = $state(null)
  let sizing = $state(false)
  const fraction = $derived((size - SIZE_MIN) / (SIZE_MAX - SIZE_MIN))
  function setSize(event) {
    const room = sizeNode.getBoundingClientRect()
    const up = 1 - Math.min(1, Math.max(0, (event.clientY - room.top) / room.height))
    size = Math.round(SIZE_MIN + up * (SIZE_MAX - SIZE_MIN))
  }
  function sizeDown(event) {
    sizing = true
    sizeNode.setPointerCapture(event.pointerId)
    setSize(event)
  }
  function sizeMove(event) {
    if (sizing) setSize(event)
  }
  function sizeUp(event) {
    sizing = false
    sizeNode.releasePointerCapture?.(event.pointerId)
  }
  /* The brush as it is on the screen: its size in the picture's pixels, scaled
     as the picture is shown and zoomed. */
  const ring = $derived(natural && box.w ? size * (box.w / natural.w) * view.zoom : 0)

  // --- leaving ---------------------------------------------------------------

  function done() {
    const painted = mask?.flaeche ? bemalt(mask.flaeche) : false
    // A changed mask is no longer the one the studio has stored.
    if (dirty) werte.maske = ''
    surface.maskOn = painted
    surface.masked = painted
    ondone?.()
  }
  function cancel() {
    if (mask?.flaeche && atOpen) {
      mask.verlauf = atOpen.verlauf
      mask.zukunft = atOpen.zukunft
      replay(mask)
    }
    ondone?.()
  }

  const TOOLS = [
    { name: 'pinsel', sign: 'pinsel', text: 'maske.pinsel' },
    { name: 'radierer', sign: 'radierer', text: 'maske.radierer' },
  ]
</script>

<SubHead
  title={t('studio.maske')}
  onback={cancel}
  backText={t('app.abbrechen')}
  right={{ text: t('phonestudio.done'), onclick: done }}
/>

<div class="page">
  <div class="frame">
    <div class="stage" bind:this={stageNode} use:gestures={options}>
      {#if natural && box.w}
        <div class="zoom" style:transform={`translate(${view.x}px, ${view.y}px) scale(${view.zoom})`}>
          <div class="picbox" bind:this={picbox} style:width="{box.w}px" style:height="{box.h}px">
            <img src={api.bildAdresse(name)} alt={t('bild.startbild')} draggable="false" />
            <canvas class="layer" bind:this={seen} style:opacity={TINT_STRENGTH}></canvas>
          </div>
        </div>
      {/if}
    </div>

    <div class="top">
      <button class="round" disabled={!canUndo} onclick={undo} aria-label={t('maske.zurueck')}>
        <MaskenZeichen name="zurueck" groesse={17} />
      </button>
      <button class="round" disabled={!canRedo} onclick={redo} aria-label={t('maske.vor')}>
        <MaskenZeichen name="vor" groesse={17} />
      </button>
    </div>

    <div class="size" bind:this={sizeNode} role="slider" tabindex="0" aria-label={t('maske.groesse')}
         aria-orientation="vertical" aria-valuemin={SIZE_MIN} aria-valuemax={SIZE_MAX} aria-valuenow={size}
         onpointerdown={sizeDown} onpointermove={sizeMove} onpointerup={sizeUp} onpointercancel={sizeUp}>
      <div class="track"><i style:top="{(1 - fraction) * 100}%"></i></div>
    </div>

    {#if sizing && ring}
      <div class="ring" aria-hidden="true" style:width="{ring}px" style:height="{ring}px"></div>
    {/if}
    {#if !hinted}
      <span class="hint">{t('phonestudio.mask_hint')}</span>
    {/if}
  </div>

  <div class="tools" role="toolbar" aria-label={t('studio.maske')}>
    {#each TOOLS as entry (entry.name)}
      <button class:on={tool === entry.name} aria-pressed={tool === entry.name} onclick={() => (tool = entry.name)}>
        <MaskenZeichen name={entry.sign} groesse={22} />
        <span>{t(entry.text)}</span>
      </button>
    {/each}
    <button onclick={() => whole('umkehren')} disabled={!mask?.flaeche}>
      <MaskenZeichen name="umkehren" groesse={22} />
      <span>{t('maske.umkehren')}</span>
    </button>
    <button onclick={() => whole('leeren')} disabled={!hasPaint}>
      <MaskenZeichen name="leeren" groesse={22} />
      <span>{t('maske.leeren')}</span>
    </button>
  </div>
</div>

<style>
  .page {
    height: 100%;
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 0 4px calc(8px + env(safe-area-inset-bottom));
  }
  /* The picture across the width; the controls lie on it. */
  .frame {
    position: relative;
    flex: 1;
    min-height: 0;
    border-radius: 9px;
    overflow: hidden;
    background: var(--bg-hoch);
  }
  .stage {
    position: absolute;
    inset: 0;
    display: grid;
    place-items: center;
    overflow: hidden;
    -webkit-user-select: none;
    user-select: none;
    -webkit-touch-callout: none;
  }
  .zoom {
    transform-origin: 50% 50%;
  }
  .picbox {
    position: relative;
  }
  .picbox img,
  .picbox .layer {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    pointer-events: none;
  }
  .picbox img {
    display: block;
  }
  .top {
    position: absolute;
    top: 10px;
    left: 10px;
    display: flex;
    gap: 6px;
  }
  .round {
    width: 36px;
    height: 36px;
    display: grid;
    place-items: center;
    padding: 0;
    border: none;
    border-radius: 50%;
    background: var(--glass-dropdown);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text);
  }
  .round:disabled {
    opacity: 0.4;
  }
  /* The brush's size: a slider standing up at the right edge. */
  .size {
    position: absolute;
    right: 10px;
    top: 50%;
    width: 36px;
    height: 200px;
    transform: translateY(-50%);
    display: flex;
    justify-content: center;
    padding: 12px 0;
    box-sizing: border-box;
    border-radius: 18px;
    background: var(--glass-dropdown);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    touch-action: none;
  }
  .track {
    position: relative;
    width: 4px;
    height: 100%;
    border-radius: 2px;
    background: var(--text-still);
    opacity: 0.8;
  }
  .track i {
    position: absolute;
    left: 50%;
    width: 22px;
    height: 22px;
    border-radius: 50%;
    transform: translate(-50%, -50%);
    background: var(--text);
    box-shadow: 0 2px 6px rgba(0, 0, 0, 0.35);
  }
  /* While the size is set: the brush as it will paint, in the middle. */
  .ring {
    position: absolute;
    left: 50%;
    top: 50%;
    transform: translate(-50%, -50%);
    border-radius: 50%;
    border: 1.5px solid #fff;
    box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.5);
    pointer-events: none;
  }
  .hint {
    position: absolute;
    left: 50%;
    bottom: 12px;
    transform: translateX(-50%);
    max-width: calc(100% - 24px);
    padding: 0 12px;
    height: 30px;
    line-height: 30px;
    border-radius: 99px;
    font: 500 12px var(--schrift);
    white-space: nowrap;
    color: var(--text);
    background: var(--glass-dropdown);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    pointer-events: none;
  }
  /* Four tools, one width, one height, each with its word. */
  .tools {
    flex: none;
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 4px;
    padding: 6px;
    border-radius: 9px;
    background: var(--kachel-eingabe, var(--bg-erhoben));
    box-shadow: 0 14px 34px -14px rgba(0, 0, 0, 0.55), 0 2px 6px -2px rgba(0, 0, 0, 0.25);
  }
  .tools button {
    height: 54px;
    min-width: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 4px;
    padding: 0 2px;
    border: none;
    border-radius: 7px;
    background: none;
    color: var(--text-leise);
    font: 500 11px var(--schrift);
  }
  .tools button span {
    max-width: 100%;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .tools button.on {
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text);
  }
  .tools button:disabled {
    opacity: 0.4;
  }
</style>
