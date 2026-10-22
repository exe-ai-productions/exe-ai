<script>
  /* A presentation (pptx): its slides one under the other, as wide as the
     holder (pptx-preview, lib/officeDocument.js). A new width draws them
     again once the holder has stopped changing. */
  import { onMount } from 'svelte'
  import { drawSlides, readBytes } from '../lib/officeDocument.js'
  import OfficeFrame from './OfficeFrame.svelte'

  let { address, name = '' } = $props()

  let host = $state(null)
  let stage = $state(null)
  let phase = $state('reading')
  let width = $state(0)

  $effect(() => {
    const source = address
    const wide = width
    if (!stage || !source || !wide) return
    let current = true
    let takeDown = null
    ;(async () => {
      try {
        const bytes = await readBytes(source)
        if (!current) return
        stage.replaceChildren()
        takeDown = await drawSlides(bytes, stage, wide)
        if (!current) return takeDown()
        phase = 'ready'
      } catch {
        if (current) phase = 'failed'
      }
    })()
    return () => {
      current = false
      takeDown?.()
    }
  })

  onMount(() => {
    let timer = 0
    const watcher = new ResizeObserver(() => {
      clearTimeout(timer)
      timer = setTimeout(() => { width = Math.floor(host.clientWidth) }, 150)
    })
    width = Math.floor(host.clientWidth)
    watcher.observe(host)
    return () => {
      clearTimeout(timer)
      watcher.disconnect()
    }
  })
</script>

<OfficeFrame bind:host {phase} {name}>
  <div class="slides" bind:this={stage}></div>
</OfficeFrame>

<style>
  /* The slides stand one under the other and the holder rolls them: the
     library's own frame, which is one slide high and rolls by itself on a
     black ground, gives way. */
  .slides :global(.pptx-preview-wrapper) {
    height: auto !important;
    overflow: visible !important;
    background: transparent !important;
  }
</style>
