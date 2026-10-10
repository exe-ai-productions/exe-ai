<!-- The place a starting picture is laid down.

     A plaque rather than a button with a thumbnail beside it, and the whole
     plaque is the target: dragging a file onto it works, and clicking
     anywhere on it opens the file picker — the hidden input lives inside
     the label, so no click handler has to fake that.

     The picture fills the frame once it is there, and the frame takes the
     picture's own proportions instead of squeezing it into a fixed box: a
     starting picture decides what comes out, so it should be seen properly
     before the run, not guessed at from a stamp.

     Same shape as the sibling programs' image input, so a hand that knows
     one knows the other. -->
<script>
  import Modulzeichen from './Modulzeichen.svelte'
  import { t } from '../lib/texte.svelte.js'

  /* `mask`: a painted mask for this picture, laid over it half see-through
     so the picture and what will be redrawn are seen together. `fill`: the
     plaque takes the size its place gives it instead of the picture's
     proportions — for a place that sets the size, like the input beside an
     output of the same size. `video`: the place takes a video instead (a
     control video), shown playing. `label`: what the empty plaque says
     instead of "starting picture". `named`: takes a picture dragged off the
     picture wall by its name — it lies in the pictures folder already, so
     there is no file to hand over. */
  let {
    url = '', waehlen, loesen, mask = '', fill = false, video = false, label = '', named = null,
  } = $props()

  let ueberzogen = $state(false)
  let seitenmass = $state('3 / 2')
  let wahl = $state(null)

  /* The frame takes the picture's proportions — and gives them back when
     the picture goes. Without this the empty plaque kept the shape of
     whatever was removed from it, so the same empty frame had a different
     height depending on its history. */
  $effect(() => {
    if (!url) seitenmass = '3 / 2'
  })

  function fallenlassen(ereignis) {
    ereignis.preventDefault()
    /* This tile is the drop's one destination. The chat input listens for
       drops on the whole window, and a drop that bubbled on would arrive
       there too — one file, two takers, and the second one complains. */
    ereignis.stopPropagation()
    ueberzogen = false
    const name = named && ereignis.dataTransfer?.getData('application/x-exe-bild')
    if (name) {
      named(name)
      return
    }
    const datei = ereignis.dataTransfer?.files?.[0]
    if (datei?.type?.startsWith(video ? 'video/' : 'image/')) waehlen(datei)
  }
</script>

<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<label
  class="ablage"
  class:ueberzogen
  class:voll={Boolean(url)}
  class:fill
  ondragover={(e) => { e.preventDefault(); ueberzogen = true }}
  ondragleave={(e) => {
    /* Moving onto the picture or the remove button inside fires a leave on
       the tile too; only a pointer that really left it ends the glow. */
    if (!e.currentTarget.contains(e.relatedTarget)) ueberzogen = false
  }}
  ondrop={fallenlassen}
>
  <div class="flaeche" style={fill ? '' : `aspect-ratio:${seitenmass}`}>
    {#if url && video}
      <video class="bild" src={url} muted loop autoplay playsinline
             onloadedmetadata={(e) => {
               const b = e.currentTarget.videoWidth, h = e.currentTarget.videoHeight
               if (b && h) seitenmass = `${b} / ${h}`
             }}></video>
      <button
        class="weg"
        aria-label={t('warteschlange.entfernen')}
        title={t('warteschlange.entfernen')}
        onclick={(e) => { e.preventDefault(); e.stopPropagation(); loesen() }}
      >✕</button>
    {:else if url}
      <img
        class="bild"
        src={url}
        alt={t('bild.startbild')}
        onload={(e) => {
          const b = e.currentTarget.naturalWidth, h = e.currentTarget.naturalHeight
          if (b && h) seitenmass = `${b} / ${h}`
        }}
      />
      {#if mask}
        <img class="mask" src={mask} alt="" />
      {/if}
      <!-- Inside the label, so the click that removes must not also open
           the picker the label stands for. -->
      <button
        class="weg"
        aria-label={t('warteschlange.entfernen')}
        title={t('warteschlange.entfernen')}
        onclick={(e) => { e.preventDefault(); e.stopPropagation(); loesen() }}
      >✕</button>
    {:else}
      <div class="ablegen">
        <Modulzeichen modul="bilder" groesse={22} />
        <span>{label || t('bild.gruppe_startbild')}</span>
      </div>
    {/if}
  </div>
  <input
    class="versteckt"
    type="file"
    accept={video ? 'video/*' : 'image/png,image/jpeg,image/webp'}
    bind:this={wahl}
    onchange={(e) => { waehlen(e.currentTarget.files?.[0]); e.currentTarget.value = '' }}
  />
</label>

<style>
  /* The plaque, stroke for stroke as the sibling program wears it: no
     border but a one-pixel rim painted as a gradient, light at the top
     edge and dark at the bottom, so the frame reads as lifted rather than
     drawn on. */
  .ablage {
    display: block;
    width: 100%;
    padding: 1px;
    border-radius: 9px;
    background: linear-gradient(
      180deg,
      rgba(255, 255, 255, 0.15),
      rgba(255, 255, 255, 0.02) 42%,
      rgba(0, 0, 0, 0.4)
    );
    box-shadow: 0 14px 34px -16px rgba(0, 0, 0, 0.6);
    cursor: pointer;
    transition: background 0.14s, box-shadow 0.14s;
  }
  /* A file hangs over the frame — a clear, calm highlight. Brightness only:
     an invitation is a fact about what can be dropped, not a state. */
  .ablage.ueberzogen {
    background: var(--linie-stark);
    box-shadow: 0 0 0 1px var(--linie-stark), 0 14px 34px -16px rgba(0, 0, 0, 0.6);
  }
  .flaeche {
    position: relative;
    width: 100%;
    border-radius: 9px;
    overflow: hidden;
    /* A ceiling, so the window keeps its proportions whatever is laid on
       the plaque. Without it an upright picture drew a frame twice the
       height of the column beside it: the settings across the way ended
       half a screen higher than the plaque's foot, and the window grew
       past the screen. The height a landscape picture wants stays below
       this, so those are unaffected; an upright one stops here and shows
       itself whole on the ground instead. */
    max-height: 320px;
    /* The lit depth of the plaque, out of the skin's own tones. */
    background: radial-gradient(
      130% 120% at 42% 32%,
      var(--bg-hoch),
      var(--bg-erhoben) 58%,
      var(--bg)
    );
  }
  .ablage.fill,
  .ablage.fill .flaeche {
    box-sizing: border-box;
    height: 100%;
    max-height: none;
  }
  .bild {
    display: block;
    width: 100%;
    height: 100%;
    /* Whole, not filled: this picture decides what comes out of the run,
       so a cropped-off edge here is a lie about what the run works from.
       Where the frame has the picture's own proportions this looks the
       same as filling it; only a picture stopped by the ceiling above
       shows the lit ground beside it. */
    object-fit: contain;
  }
  .mask {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    object-fit: contain;
    opacity: 0.5;
    pointer-events: none;
  }
  .ablegen {
    position: absolute;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 12px;
    color: var(--text-still);
    font-size: 14px;
  }
  .weg {
    position: absolute;
    top: 7px;
    right: 7px;
    width: 22px;
    height: 22px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border: none;
    border-radius: 99px;
    background: color-mix(in srgb, var(--bg) 72%, transparent);
    color: var(--text);
    font-size: 12px;
    line-height: 1;
    cursor: pointer;
    backdrop-filter: blur(6px);
  }
  .weg:hover {
    background: var(--bg);
  }
  .versteckt {
    display: none;
  }
</style>
