<script>
  /* The picture studio in the chat tile: it lies over the whole tile while
     the studio is open, and the chat stays mounted underneath, hidden, so
     it comes back with its scroll position and everything typed into it.
     The drawing surface fills it; the prompt bar floats at its foot and the
     row of pictures stands at its right edge.

     The chat's picture line (App.svelte) is handed in: drawing, stopping
     the picture drawing now, taking a waiting one out. */
  import StudioCanvas from './StudioCanvas.svelte'
  import StudioGallery from './StudioGallery.svelte'
  import StudioPictureInfo from './StudioPictureInfo.svelte'
  import StudioPromptBar from './StudioPromptBar.svelte'
  import { zeichnung } from '../lib/studiozeichnen.svelte.js'

  let { zeichnen = null, stopEins = null, entfernen = null } = $props()

  $effect(() => {
    zeichnung.losZeichnen = zeichnen
    zeichnung.stopEins = stopEins
    zeichnung.entfernen = entfernen
    return () => {
      zeichnung.losZeichnen = null
      zeichnung.stopEins = null
      zeichnung.entfernen = null
    }
  })
</script>

<!-- Nothing in the studio zooms the page: a pinch arrives as a wheel with
     Ctrl held, and a zoomed page would move and resize the generation area
     with it. Over the surface the gesture zooms the picture (StudioCanvas);
     over what floats on it — the tools, the row of pictures, the prompt bar
     — it does nothing. A plain wheel stays with whatever it rolls. -->
<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="studio" onwheel={(e) => { if (e.ctrlKey) e.preventDefault() }}>
  <StudioCanvas />
  <StudioGallery />
  <StudioPromptBar />
  <StudioPictureInfo />
</div>

<style>
  .studio {
    position: absolute;
    inset: 0;
    /* Over the chat's own layers (head at 3), under the notices (25). */
    z-index: 4;
    display: flex;
    flex-direction: column;
    border-radius: inherit;
  }
</style>
