<script>
  /* The choice of the look as a row of cards, always in sight: each card the
     look in miniature with its name, the chosen one marked with a tick and
     "Active". It is one group of radio buttons — one card takes the tab,
     the arrow keys move the choice, Enter and Space pick the card in focus —
     and what it picks is the choice of the appearance itself, so a change is
     made the moment a card is chosen. */
  import { tick } from 'svelte'
  import Looksvorschau from './Looksvorschau.svelte'
  import Hauszeichen from './Hauszeichen.svelte'
  import { t } from '../lib/texte.svelte.js'

  /* `optionen`: `[[look, title], …]` in the order the cards stand. `wert`:
     the chosen look. `eigen`: the picture of the own gradient. */
  let { optionen, wert = $bindable(''), beschriftung = '', eigen = null } = $props()

  let karten = $state([])
  /* With a value no card stands for, the first card takes the tab stop, or the
     group could not be reached with the keyboard. */
  const bekannt = $derived(optionen.some(([look]) => look === wert))

  async function taste(ereignis, stelle) {
    const schritt = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[ereignis.key]
    if (!schritt) return
    ereignis.preventDefault()
    const neu = (stelle + schritt + optionen.length) % optionen.length
    wert = optionen[neu][0]
    await tick()
    karten[neu]?.focus()
  }
</script>

<div class="looktafel" role="radiogroup" aria-label={beschriftung}>
  {#each optionen as [look, titel], i (look)}
    <button
      type="button"
      class="karte"
      class:aktiv={wert === look}
      role="radio"
      aria-checked={wert === look}
      tabindex={wert === look || (!bekannt && i === 0) ? 0 : -1}
      bind:this={karten[i]}
      onclick={() => (wert = look)}
      onkeydown={(e) => taste(e, i)}
    >
      <Looksvorschau {look} {eigen} />
      <span class="name">
        <span class="titel">{titel}</span>
        {#if wert === look}
          <span class="marke">
            <Hauszeichen zeichen="haken" groesse={14} strich={2.2} />
            {t('einstellungen.aktiv')}
          </span>
        {/if}
      </span>
    </button>
  {/each}
</div>

<style>
  .looktafel {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
    gap: 12px;
  }
  /* The card is a card of the page: card glass with its fine line; the
     chosen one takes the ink of the look as its edge. The edge is an inset
     shadow, so a card keeps its size whether it is chosen or not. */
  .karte {
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 8px 8px 10px;
    border: none;
    border-radius: 9px;
    background: var(--glass-card);
    box-shadow: inset 0 0 0 1px var(--glass-card-line);
    color: var(--text);
    font: inherit;
    text-align: left;
    cursor: pointer;
    transition: box-shadow 0.12s;
  }
  .karte:hover {
    box-shadow: inset 0 0 0 1px var(--text-still);
  }
  .karte.aktiv {
    box-shadow: inset 0 0 0 1.5px var(--text);
  }
  .karte:focus-visible {
    outline: 2px solid var(--text);
    outline-offset: 2px;
  }
  .name {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 0 4px;
    min-height: 18px;
  }
  .titel {
    flex: 1;
    min-width: 0;
    font: 600 13px/1.4 var(--schrift);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .marke {
    flex: none;
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font: 500 13px/18px var(--schrift);
  }
</style>
