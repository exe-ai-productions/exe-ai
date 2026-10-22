<script>
  /* A Word document (docx), drawn page by page from the file's address by
     docx-preview (lib/officeDocument.js). The pages keep their own width;
     where the holder is narrower they are scaled down to fit it, so nothing
     rolls sideways. Embedded HTML in the file is not drawn, and a link that
     leads anywhere but to a web page or a mail address stays text. */
  import { onMount } from 'svelte'
  import { drawWord, readBytes } from '../lib/officeDocument.js'
  import OfficeFrame from './OfficeFrame.svelte'

  let { address, name = '' } = $props()

  let host = $state(null)
  let body = $state(null)
  let styles = $state(null)
  let phase = $state('reading')

  /* The pages at their own width, shrunk to the holder's when it is
     narrower. */
  function fit() {
    if (!host || !body) return
    body.style.zoom = ''
    const page = body.querySelector('section')
    if (!page || !host.clientWidth) return
    if (page.offsetWidth > host.clientWidth) body.style.zoom = String(host.clientWidth / page.offsetWidth)
  }

  $effect(() => {
    const source = address
    if (!body || !styles || !source) return
    let current = true
    phase = 'reading'
    ;(async () => {
      try {
        const bytes = await readBytes(source)
        if (!current) return
        body.replaceChildren()
        styles.replaceChildren()
        await drawWord(bytes, body, styles)
        if (!current) return
        phase = 'ready'
        fit()
      } catch {
        if (current) phase = 'failed'
      }
    })()
    return () => { current = false }
  })

  onMount(() => {
    const watcher = new ResizeObserver(fit)
    watcher.observe(host)
    return () => watcher.disconnect()
  })
</script>

<OfficeFrame bind:host {phase} {name}>
  <div class="styles" bind:this={styles}></div>
  <div class="word" bind:this={body}></div>
</OfficeFrame>

<style>
  .styles { display: none; }
  /* The sheets lie on the holder's own ground, with no grey around them. */
  .word :global(.docx-wrapper) {
    background: transparent;
    padding: 0;
  }
  .word :global(.docx-wrapper > section.docx) {
    margin-bottom: 8px;
  }
</style>
