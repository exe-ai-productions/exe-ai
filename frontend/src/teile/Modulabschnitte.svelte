<script>
  /* Stacked sections for a view on the tool surface: one column, one after
     the other, and the whole surface scrolls.

     The sections used to sit between seams the hand could drag, each with
     a scroll area of its own. A column that scrolls as a whole needs none
     of that: every part stands at the height its content has, and nothing
     can end up squeezed shut behind a seam.

     `abschnitte` describes the stack, top to bottom: name, the title's
     catalog key (or `text`, a title already in words, for one that changes
     with what is shown) and, where a part counts something, `zahl` beside
     the title. A part with neither stands without a title row. `inhalt` is the snippet rendered inside each section, handed the
     section's name. A part that can be folded gives `klapp`
     ({ offen, schalten }): its title row becomes the button that does it,
     with the chevron before the title.

     A view that has two columns when the surface is wide enough names the
     column of each part (`spalte`, 1 or 2) and passes `zweispaltig`. Below
     that width the columns stand one under the other, in the order they are
     written — the same single column as ever. Parts that name no column
     are one column of their own. */
  import { rollfade } from '../lib/rollfade.js'
  import { t } from '../lib/texte.svelte.js'

  let { abschnitte, inhalt = null, zweispaltig = false } = $props()

  const spalten = $derived.by(() => {
    const gruppen = []
    for (const a of abschnitte) {
      const nummer = a.spalte ?? 1
      const gruppe = gruppen.find((g) => g.nummer === nummer)
      if (gruppe) gruppe.abschnitte.push(a)
      else gruppen.push({ nummer, abschnitte: [a] })
    }
    return gruppen.sort((a, b) => a.nummer - b.nummer)
  })
</script>

<div class="abschnitte" use:rollfade>
  <div class="spalten" class:zwei={zweispaltig && spalten.length > 1}>
    {#each spalten as gruppe (gruppe.nummer)}
      <div class="spalte">
        {#each gruppe.abschnitte as a (a.name)}
          <section class="abschnitt">
            {#if !a.titel && !a.text}
              <!-- No title: the part starts with its content. -->
            {:else if a.klapp}
              <button class="titel klapp" aria-expanded={a.klapp.offen} onclick={a.klapp.schalten}>
                <svg class="winkel" class:auf={a.klapp.offen} width="11" height="11" viewBox="0 0 24 24"
                     fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"
                     stroke-linejoin="round" aria-hidden="true">
                  <path d="M9 6l6 6-6 6" />
                </svg>
                <span class="tafelkopf">{a.text ?? t(a.titel)}</span>
                {#if a.zahl != null && a.zahl !== ''}
                  <span class="zahl">{a.zahl}</span>
                {/if}
              </button>
            {:else}
              <div class="titel">
                <span class="tafelkopf">{a.text ?? t(a.titel)}</span>
                {#if a.zahl != null && a.zahl !== ''}
                  <span class="zahl">{a.zahl}</span>
                {/if}
              </div>
            {/if}
            {#if !a.klapp || a.klapp.offen}
              {@render inhalt?.(a.name)}
            {/if}
          </section>
        {/each}
      </div>
    {/each}
  </div>
</div>

<style>
  /* ONE inset for the whole column: panels give their lists no horizontal
     padding of their own, so every part starts on the same left edge. */
  .abschnitte {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    padding: 4px var(--rand, 14px) 18px;
  }
  .abschnitt + .abschnitt {
    margin-top: 22px;
  }
  /* Stacked, the columns follow each other like parts of one column. */
  .spalte + .spalte {
    margin-top: 22px;
  }
  /* Two equal columns side by side; the whole surface still scrolls as one. */
  .spalten.zwei {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    column-gap: 24px;
    align-items: start;
  }
  .spalten.zwei .spalte + .spalte {
    margin-top: 0;
  }
  /* The part's heading, 10px above its card. Text itself: global.css,
     .tafelkopf. */
  .titel {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 8px;
    margin-bottom: 10px;
  }
  /* A hairline runs from the title to the count, so a short title and its
     number still read as one row across the column. */
  .titel::after {
    content: '';
    order: 1;
    flex: 1;
    align-self: center;
    border-top: 1px solid var(--linie);
  }
  /* A part that folds: the whole title row is the button, the count stays at
     the far end. */
  .klapp {
    width: 100%;
    padding: 0;
    border: none;
    background: none;
    font-family: inherit;
    text-align: left;
    color: inherit;
    cursor: pointer;
  }
  .klapp .zahl {
    margin-left: auto;
  }
  /* Folded, nothing stands under the title: no gap to keep. */
  .klapp[aria-expanded='false'] {
    margin-bottom: 0;
  }
  .winkel {
    flex: none;
    align-self: center;
    color: var(--text-still);
    transition: transform 0.15s;
  }
  .winkel.auf { transform: rotate(90deg); }
  @media (prefers-reduced-motion: reduce) {
    .winkel { transition: none; }
  }
  .zahl {
    order: 2;
    font-size: 12px;
    color: var(--text-still);
    font-variant-numeric: tabular-nums;
  }
</style>
