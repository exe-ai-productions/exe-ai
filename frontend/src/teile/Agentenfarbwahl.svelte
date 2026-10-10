<script>
  /* The agent's colour: one round swatch filled with it, the colour's code
     beside it and a small "remove". A click on the swatch opens the
     system's own picker (`input[type=color]`, laid invisibly over the
     swatch); its own frame is not shown, it reads as a grey box in a box.
     Without a colour the swatch is an empty dashed ring.

     There is one rule it cannot keep by itself, so it is kept AFTER the
     pick. Six hues are spoken for in this program: four say a state
     (`--gruen` ready, `--gelb` waiting, `--blau` running, `--rot` failed)
     and two say what a model can do (`--violett` vision, `--oliv` tool
     use). An agent wearing one of them would read as a failed run or as a
     capability. A picked colour that lands in one of those stretches is
     therefore turned to the nearest free hue on its way in — the hue moves,
     the saturation and the brightness the hand chose do not. The swatch and
     the code beside it show the colour that was kept.

     What is stored is the picked value; the report line raises it at the
     moment of drawing until it reads against the page (`lesbar`,
     lib/agentenfarbe.svelte.js). */
  import { tonGewahrt } from '../lib/agentenfarbe.svelte.js'
  import { t } from '../lib/texte.svelte.js'

  let { farbe = $bindable('') } = $props()

  /* What the system picker shows and opens on while nothing is chosen: a
     neutral grey, which carries no hue and so cannot start the hand inside
     a stretch it cannot keep. */
  const NEUTRAL = '#8a8a8a'

  function gewaehlt(wert) {
    farbe = tonGewahrt(wert)
  }
</script>

<div class="wahl">
  <div class="zeile">
    <span class="tupfer" class:leer={!farbe} style:--tupfer={farbe || 'transparent'}>
      <input
        type="color"
        aria-label={t('agenten.farbe')}
        title={t('agenten.farbe')}
        value={farbe || NEUTRAL}
        oninput={(e) => gewaehlt(e.currentTarget.value)}
      />
    </span>
    {#if farbe}
      <span class="code">{farbe}</span>
      <button class="weg" onclick={() => (farbe = '')}>
        {t('agenten.farbe_entfernen')}
      </button>
    {/if}
  </div>
</div>

<style>
  .wahl {
    display: flex;
    flex-direction: column;
    gap: 8px;
    min-width: 0;
  }
  .zeile {
    display: flex;
    align-items: center;
    gap: 10px;
    min-width: 0;
  }
  /* Round, as every dot of this program is; a hairline ring keeps a dark
     colour visible on a dark ground. */
  .tupfer {
    position: relative;
    flex: none;
    width: 28px;
    height: 28px;
    border-radius: 50%;
    background: var(--tupfer);
    box-shadow: 0 0 0 1px var(--linie-stark);
    transition: box-shadow 0.12s;
  }
  .tupfer:hover { box-shadow: 0 0 0 2px var(--text-still); }
  .tupfer.leer {
    box-shadow: none;
    border: 1.5px dashed var(--text-still);
    box-sizing: border-box;
  }
  /* The system's picker lies over the swatch, invisible, so a click
     anywhere on it opens the dialog. */
  input[type='color'] {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    opacity: 0;
    border: none;
    padding: 0;
    cursor: pointer;
  }
  .code {
    font: 400 12px var(--schrift-fest);
    color: var(--text-leise);
  }
  .weg {
    border: none;
    background: none;
    padding: 2px 6px;
    border-radius: 9px;
    font: inherit;
    font-size: 12px;
    color: var(--text-still);
    cursor: pointer;
  }
  .weg:hover { background: var(--bg-erhoben); color: var(--text); }
</style>
