<script>
  /* The three sheets the chips over the prompt open: the size (the format
     tiles and the two edges), the style the prompt is drawn through, and the
     negative prompt. Each is exactly that one choice and nothing else; the
     values are the studio's own (`werte`), as the desktop's columns write
     them. The mask is a page of its own, not a sheet. */
  import { auswahl, ontoGrid, stile, stilVon, werte } from '../../lib/studio.svelte.js'
  import { t } from '../../lib/texte.svelte.js'
  import Sheet from '../Sheet.svelte'
  import Field from '../parts/Field.svelte'
  import { FORMATS, chosenFormat, formatPair, longEdge, tileShape } from './format.js'

  /* `which`: 'size', 'style', 'negative' or '' — nothing open. */
  let { which = '', onclose } = $props()

  // --- size ---------------------------------------------------------------

  const tile = $derived(chosenFormat(werte.breite, werte.hoehe))

  function setFormat(format) {
    const long = longEdge(auswahl.startKante, werte.breite, werte.hoehe)
    if (!long) return
    const [width, height] = formatPair(format, long)
    werte.breite = width
    werte.hoehe = height
  }

  /* An edge typed by hand stands, once the field is left, at what the
     service keeps: rounded up onto the grid. */
  let widthText = $state('')
  let heightText = $state('')
  $effect(() => {
    widthText = String(werte.breite ?? '')
    heightText = String(werte.hoehe ?? '')
  })
  function commit(name, text) {
    const edge = Math.round(Number(text))
    if (!Number.isFinite(edge) || edge <= 0) {
      widthText = String(werte.breite ?? '')
      heightText = String(werte.hoehe ?? '')
      return
    }
    werte[name] = ontoGrid(edge)
  }

  // --- style --------------------------------------------------------------

  const chosenStyle = $derived(stilVon(werte.stil))
  const styles = $derived(stile.liste.filter((entry) => entry.name))
  function pickStyle(id) {
    werte.stil = id
    onclose?.()
  }
</script>

<Sheet open={which === 'size'} label={t('studio.format')} {onclose}>
  <div class="title">{t('studio.format')}</div>
  <div class="tiles" role="group" aria-label={t('studio.format')}>
    {#each FORMATS as format (format.join(':'))}
      {@const [shapeWidth, shapeHeight] = tileShape(format[0], format[1])}
      <button class="tile" class:on={tile === format} aria-pressed={tile === format} onclick={() => setFormat(format)}>
        <span class="form"><span class="shape" style:width="{shapeWidth}px" style:height="{shapeHeight}px"></span></span>
        <span class="ratio">{format.join(':')}</span>
      </button>
    {/each}
    <!-- Not a button: it only says that the size is no tile's, and pressing
         it would set nothing. -->
    <div class="tile custom" class:on={!tile}>
      <span class="form">
        <span class="shape" style:width="{tileShape(werte.breite, werte.hoehe)[0]}px"
              style:height="{tileShape(werte.breite, werte.hoehe)[1]}px"></span>
      </span>
      <span class="ratio">{t('studio.eigene')}</span>
    </div>
  </div>
  <div class="edges">
    <Field label={t('bild.breite')} bind:value={widthText} inputmode="numeric" onchange={() => commit('breite', widthText)} />
    <Field label={t('bild.hoehe')} bind:value={heightText} inputmode="numeric" onchange={() => commit('hoehe', heightText)} />
  </div>
</Sheet>

<Sheet open={which === 'style'} label={t('studio.stil')} {onclose}>
  <div class="title">{t('studio.stil')}</div>
  <button class="choice" class:chosen={!chosenStyle} onclick={() => pickStyle('')}>{t('studio.stil_keiner')}</button>
  {#each styles as entry (entry.id)}
    <button class="choice" class:chosen={chosenStyle?.id === entry.id} onclick={() => pickStyle(entry.id)}>
      {entry.name}
    </button>
  {/each}
</Sheet>

<Sheet open={which === 'negative'} label={t('bild.negativ')} {onclose}>
  <div class="title">{t('bild.negativ')}</div>
  <textarea class="negative" rows="4" bind:value={werte.negativ} aria-label={t('bild.negativ')}></textarea>
</Sheet>

<style>
  .title {
    padding: 4px 4px 10px;
    font: 600 16px var(--schrift);
  }
  .tiles {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 8px;
    padding: 0 2px;
  }
  .tile {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 6px;
    height: 60px;
    padding: 0;
    border: none;
    border-radius: 9px;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text-leise);
  }
  .tile.on {
    color: var(--text);
    box-shadow: inset 0 0 0 1.5px var(--text);
  }
  /* Every shape stands in the same square, so every ratio word is on one line. */
  .form {
    display: grid;
    place-items: center;
    width: 20px;
    height: 20px;
  }
  .shape {
    box-sizing: border-box;
    border-radius: 2px;
    border: 1.5px solid currentColor;
  }
  .ratio {
    font: 500 11px var(--schrift);
  }
  .edges {
    display: grid;
    grid-template-columns: 1fr 1fr;
    margin-top: 6px;
  }
  .choice {
    display: block;
    width: 100%;
    min-height: var(--menuezeile);
    padding: 6px;
    border: none;
    border-top: 1px solid var(--linie);
    background: none;
    color: var(--text);
    font: 400 var(--schrift-text) var(--schrift);
    text-align: left;
  }
  .choice.chosen {
    color: var(--text);
    font-weight: 600;
  }
  .negative {
    display: block;
    width: 100%;
    box-sizing: border-box;
    padding: 10px 12px;
    border: none;
    border-radius: 9px;
    resize: none;
    background: var(--bg-hoch);
    color: var(--text);
    /* 16 px: a smaller field makes the page zoom when it takes the focus. */
    font: 400 16px/22px var(--schrift);
  }
</style>
