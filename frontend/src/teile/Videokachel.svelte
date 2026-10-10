<script>
  /* A finished video where a picture would stand: its first frame, still,
     with its length in the corner — the tile of the gallery and the chat.
     It plays at full size in the viewer (Bildschau.svelte), not here: a
     wall of moving tiles is no place to look at one. */
  import { dauerText } from '../lib/dauer.js'
  import { t } from '../lib/texte.svelte.js'

  /* `ownShape`: the tile takes the video's own proportions instead of
     filling the place it is given. */
  let { src, ownShape = false } = $props()

  let seconds = $state(null)
  let shape = $state('')
</script>

<span class="kachel" style={ownShape && shape ? `aspect-ratio:${shape}` : ''}>
  <video {src} muted playsinline preload="metadata"
         onloadedmetadata={(e) => {
           const video = e.currentTarget
           seconds = Number.isFinite(video.duration) ? video.duration : null
           if (video.videoWidth && video.videoHeight) shape = `${video.videoWidth} / ${video.videoHeight}`
         }}></video>
  {#if seconds !== null}
    <span class="dauer">{dauerText(t, seconds)}</span>
  {/if}
</span>

<style>
  .kachel {
    position: relative;
    display: block;
    width: 100%;
    height: 100%;
  }
  video {
    display: block;
    width: 100%;
    height: 100%;
    object-fit: cover;
  }
  /* The length in the same dark glass as the seed and the dots. */
  .dauer {
    position: absolute;
    right: 8px;
    bottom: 8px;
    padding: 2px 7px;
    border-radius: 9px;
    background: rgba(0, 0, 0, 0.45);
    color: #fff;
    font-family: var(--schrift-fest);
    font-size: 11px;
    /* Its own line: a picture frame around it may set the line to 0. */
    line-height: normal;
  }
</style>
