<script>
  /* A PDF, drawn by the program itself with pdf.js (lib/pdfDocument.js): the
     one file the program shows that is not text. The rail beside the chat and
     the view over the window both show it through this component, so a PDF
     looks and rolls the same in both, and the same on every system.

     The pages stand one under the other, fitted to the width of what holds
     them and sharp on a dense screen; the text on them can be marked. They
     roll like every surface of the house — no bar on show, no fade at the
     edge — and the sheet reaches the edge of its holder and wears its
     corners. Until the first page stands the line for "reading" stands;
     a file that is no PDF says what any failure says. Only the pages that
     are in view (and a screen's height around them) are drawn: a long file
     costs what its visible pages cost.

     Whatever holds this is positioned and has a size of its own. */
  import { onMount, tick } from 'svelte'
  import { t } from '../lib/texte.svelte.js'
  import { closePdf, drawPage, drawText, openPdf, pageSize } from '../lib/pdfDocument.js'

  let { address, title } = $props()

  let host = $state(null)
  let count = $state(0)
  let failed = $state(false)
  let firstDrawn = $state(false)

  let doc = null
  let width = 0
  /* Page n's box and the picture in it: what is drawn at which width. */
  const boxes = []
  const drawn = new Map()
  let ratio = 1.4142
  let watcher = null

  const GAP = 8

  function boxOf(n) {
    return boxes[n]
  }

  async function release(n) {
    const state = drawn.get(n)
    if (!state) return
    drawn.delete(n)
    state.task?.cancel()
    const box = boxOf(n)
    const canvas = box?.querySelector('canvas')
    if (canvas) canvas.width = 0
    box?.querySelector('.textLayer')?.replaceChildren()
  }

  async function show(n) {
    if (!doc || !width) return
    const state = drawn.get(n)
    if (state?.width === width) return
    release(n)
    const mine = { width, task: null }
    drawn.set(n, mine)
    try {
      const page = await doc.getPage(n + 1)
      if (drawn.get(n) !== mine) return
      const box = boxOf(n)
      const canvas = box.querySelector('canvas')
      const { viewport, task } = drawPage(page, canvas, width)
      mine.task = task
      box.style.height = `${Math.floor(viewport.height)}px`
      box.style.setProperty('--scale-factor', String(viewport.scale))
      await task.promise
      if (drawn.get(n) !== mine) return
      firstDrawn = true
      await drawText(page, viewport, box.querySelector('.textLayer'))
    } catch (error) {
      if (error?.name === 'RenderingCancelledException') return
      drawn.delete(n)
      if (n === 0) failed = true
    }
  }

  function layOut() {
    for (const box of boxes) {
      if (box && !drawn.has(Number(box.dataset.n))) box.style.height = `${Math.floor(width * ratio)}px`
    }
  }

  async function open() {
    try {
      doc = await openPdf(address)
    } catch {
      failed = true
      return
    }
    const first = await doc.getPage(1)
    const size = pageSize(first)
    ratio = size.height / size.width
    count = doc.numPages
    await tick()
    watch()
    layOut()
  }

  /* The pages in view, and a screen's height around them, are drawn; the
     others give their picture back. */
  function watch() {
    watcher?.disconnect()
    watcher = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          const n = Number(entry.target.dataset.n)
          if (entry.isIntersecting) show(n)
          else release(n)
        }
      },
      { root: host, rootMargin: '100% 0px' },
    )
    for (const box of host.querySelectorAll('.seite')) {
      boxes[Number(box.dataset.n)] = box
      watcher.observe(box)
    }
  }

  onMount(() => {
    width = host.clientWidth
    const sizer = new ResizeObserver(() => {
      const now = host.clientWidth
      if (!now || now === width) return
      width = now
      layOut()
      /* A new width: every page in the drawing is drawn again at it. */
      for (const n of [...drawn.keys()]) show(n)
    })
    sizer.observe(host)
    open()
    return () => {
      sizer.disconnect()
      watcher?.disconnect()
      for (const n of [...drawn.keys()]) release(n)
      if (doc) closePdf(doc)
    }
  })
</script>

<!-- Reachable by key, so the arrows and Page Down roll the pages. -->
<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
<div class="pdf" bind:this={host} tabindex="0" role="document" aria-label={title}>
  {#if failed}
    <p class="note failure">{t('fehler.allgemein')}</p>
  {:else if !firstDrawn}
    <p class="note">{t('nachricht.dokument_liest')}</p>
  {/if}
  {#each { length: count } as _, n (n)}
    <div class="seite" data-n={n} style:margin-top="{n ? GAP : 0}px">
      <canvas></canvas>
      <div class="textLayer"></div>
    </div>
  {/each}
</div>

<style>
  /* Fills what holds it and rolls inside itself; the holder's rounding cuts
     the sheet, so the corners are the holder's own. */
  .pdf {
    position: absolute;
    inset: 0;
    overflow-x: hidden;
    overflow-y: auto;
    border-radius: inherit;
    background: var(--bg-hoch);
    outline: none;
  }
  .note {
    position: absolute;
    inset: 0;
    display: grid;
    place-items: center;
    margin: 0;
    color: var(--text-still);
    font-size: 12.5px;
    pointer-events: none;
  }
  .note.failure { color: var(--rot-text); }
  .seite {
    position: relative;
    background: #fff;
    overflow: hidden;
  }
  canvas {
    display: block;
  }
  /* The text over the page: invisible, in the place of the drawn letters,
     there to be marked and copied. */
  .textLayer {
    position: absolute;
    inset: 0;
    overflow: clip;
    line-height: 1;
    text-size-adjust: none;
    forced-color-adjust: none;
    transform-origin: 0 0;
    --user-unit: 1;
    --total-scale-factor: var(--scale-factor, 1);
    --min-font-size: 1;
    --text-scale-factor: calc(var(--total-scale-factor) * var(--min-font-size));
    --min-font-size-inv: calc(1 / var(--min-font-size));
  }
  .textLayer :global(:is(span, br)) {
    position: absolute;
    color: transparent;
    white-space: pre;
    cursor: text;
    transform-origin: 0% 0%;
    user-select: text;
  }
  .textLayer :global(> :not(.markedContent)),
  .textLayer :global(.markedContent span:not(.markedContent)) {
    --font-height: 0;
    --scale-x: 1;
    --rotate: 0deg;
    font-size: calc(var(--text-scale-factor) * var(--font-height));
    transform: rotate(var(--rotate)) scaleX(var(--scale-x)) scale(var(--min-font-size-inv));
  }
  .textLayer :global(.markedContent) {
    display: contents;
  }
  .textLayer :global(span::selection) {
    background: color-mix(in srgb, var(--blau) 35%, transparent);
  }
</style>
