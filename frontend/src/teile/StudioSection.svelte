<script>
  /* One section of the picture studio, in both of its columns: a head and
     one glass card under it — or, folded, a card whose first row opens it.

     The rows are styled here, not in each column, the way the server
     windows share Serverabschnitt.svelte: a row is a direct child of the
     card with the class `zeile`, its name a `label.name` (the ⓘ beside it,
     outside the label), its field in a `rechts` at the right end (`wahl`
     for a picker of the shared width). A `regel` row carries its number on
     a `kopfzeile` and the slider under the whole row; a `stapel` row puts
     its name over a box of the full width. `hinweis` is a quiet sentence
     under a row, `vorsicht` the caution tone. The folded rows of sd.cpp's
     switches stand in a `schalterflaeche`.

     `suche` is what the column's search reads for the section; it defaults
     to the title. While a search stands a folded section shows its rows
     anyway (StudioDetails.svelte), so its head rests: a press would change
     nothing, neither then nor once the search is emptied. */
  import { searching } from '../lib/studio.svelte.js'

  let {
    titel = '',
    suche = '',
    rechts = null,
    klappbar = false,
    offen = $bindable(false),
    children,
  } = $props()
</script>

<section class="abschnitt studioabschnitt" data-suche={suche || titel}>
  {#if klappbar}
    <div class="karte">
      <div class="zeile klappzeile">
        <button class="klappe" aria-expanded={offen} disabled={searching()} onclick={() => (offen = !offen)}>
          <svg class="winkel" class:auf={offen} width="11" height="11" viewBox="0 0 11 11" fill="none"
               stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"
               aria-hidden="true">
            <path d="M4.125 2.75L6.875 5.5L4.125 8.25" />
          </svg>
          <span class="klappname">{titel}</span>
        </button>
      </div>
      {#if offen}{@render children?.()}{/if}
    </div>
  {:else}
    <div class="kopf tafelkopf">
      <span class="kopftitel">{titel}</span>
      {#if rechts}
        <span class="kopfknoepfe">{@render rechts()}</span>
      {/if}
    </div>
    <div class="karte">{@render children?.()}</div>
  {/if}
</section>

<style>
  .abschnitt {
    flex: none;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  /* Set by the column's search, so the compiler sees no hidden one. */
  :global(section.studioabschnitt[hidden]) {
    display: none;
  }
  .kopf {
    height: 26px;
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
  }
  /* A head is one line: the title ends with an ellipsis when the buttons
     leave it too little room, and the buttons stay whole. */
  .kopftitel {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .kopfknoepfe {
    flex: none;
    margin-left: auto;
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }
  /* The buttons a head carries: a small glass pill (`kopfknopf`) or a
     folder sign (`ordnerzeichen`). */
  .kopf :global(.kopfknopf) {
    height: 22px;
    padding: 0 12px;
    border: none;
    border-radius: 9px;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text);
    font: 400 12px/16px var(--schrift);
    white-space: nowrap;
    cursor: pointer;
  }
  .kopf :global(.kopfknopf:hover) {
    background: color-mix(in srgb, var(--text) 6%, var(--glass-button));
  }
  .abschnitt :global(.ordnerzeichen) {
    flex: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 26px;
    height: 26px;
    padding: 0;
    border: none;
    border-radius: 9px;
    background: none;
    color: var(--text-leise);
    cursor: pointer;
  }
  .abschnitt :global(.ordnerzeichen:hover) {
    background: var(--glass-hover);
    color: var(--text);
  }

  /* A glass card: see-through, its edge one fine line. Not clipped, so an
     open list lies over what is below it. Inside it the raised grounds and
     the hairline turn to the cards' glass, as on a menu page
     (Seitenrahmen.svelte): the sliders' tracks read them. */
  .karte {
    display: flex;
    flex-direction: column;
    padding: 0 12px;
    border-radius: 9px;
    background: var(--glass-card);
    box-shadow: inset 0 0 0 1px var(--glass-card-line);
    --bg-erhoben: var(--glass-card);
    --bg-hoch: var(--glass-card);
    --linie: var(--glass-card-line);
  }
  /* A number field on glass wears the glass field of the pickers beside it
     (Auswahlfeld.svelte, `glass`). */
  .karte :global(.zahl) {
    background: var(--glass-button);
    border-color: var(--feldstrich);
  }
  .karte > :global(.zeile) {
    min-height: 46px;
    box-sizing: border-box;
    padding: 8px 0;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px 8px;
    min-width: 0;
  }
  .karte > :global(.zeile[hidden]) {
    display: none;
  }
  .karte > :global(.zeile + .zeile) {
    border-top: 1px solid var(--glass-card-line);
  }
  .karte > :global(.zeile.voll > *) {
    flex: 1;
    min-width: 0;
  }
  .karte > :global(.zeile.leer) {
    margin: 0;
    font-size: 12px;
    color: var(--text-still);
  }
  .karte :global(.name) {
    flex: none;
    font: 400 13px/18px var(--schrift);
    color: var(--text);
    white-space: nowrap;
  }
  .karte :global(.gesperrt .name) {
    color: var(--text-still);
  }
  /* The ⓘ sits right after the name; its sentence opens on a line of its
     own under the row. */
  .karte :global(.mark) {
    margin-left: 0;
  }
  .karte :global(.rechts) {
    margin-left: auto;
    flex: none;
    display: flex;
    align-items: center;
    min-width: 0;
  }
  .karte :global(.wahl) {
    width: 140px;
  }
  .karte :global(.wahl > *) {
    flex: 1;
    min-width: 0;
  }
  /* A text field on glass, the pickers' width. */
  .karte :global(.eingabe) {
    width: 140px;
    height: 32px;
    box-sizing: border-box;
    padding: 0 10px;
    border: 1px solid var(--feldstrich, transparent);
    border-radius: 9px;
    background: var(--glass-button);
    color: var(--text);
    font: 400 13px/18px var(--schrift);
    font-variant-numeric: tabular-nums;
    outline: none;
  }
  .karte :global(.eingabe:disabled) {
    opacity: 0.6;
  }

  /* A slider row: the name, the ⓘ and the number on one line, the slider
     over the whole width under them. */
  .karte > :global(.zeile.regel),
  .karte > :global(.zeile.stapel) {
    flex-direction: column;
    flex-wrap: nowrap;
    align-items: stretch;
    gap: 2px;
  }
  .karte > :global(.zeile.stapel) {
    gap: 8px;
  }
  .karte :global(.kopfzeile) {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px 8px;
    min-width: 0;
  }

  /* The fold: a row you press, its chevron turning; how many of its rows
     are set out of how many there are at the right end. */
  .karte :global(.klappe) {
    flex: 1;
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 0;
    border: none;
    background: none;
    color: var(--text);
    font: 400 13px/18px var(--schrift);
    cursor: pointer;
    text-align: left;
  }
  /* A resting head is nothing to press: no hand, and no fold sign. */
  .karte :global(.klappe:disabled) {
    cursor: default;
  }
  .karte :global(.klappe:disabled .winkel) {
    visibility: hidden;
  }
  .karte :global(.winkel) {
    flex: none;
    color: var(--text-still);
    transition: transform 0.15s;
  }
  .karte :global(.winkel.auf) {
    transform: rotate(90deg);
  }
  @media (prefers-reduced-motion: reduce) {
    .karte :global(.winkel) {
      transition: none;
    }
  }
  .karte :global(.zaehler) {
    margin-left: auto;
    color: var(--text-still);
    font-variant-numeric: tabular-nums;
  }

  /* sd.cpp's further switches (ImageSwitchRows.svelte) as rows of the
     card: the name on the left, the control at the right end. */
  .karte > :global(.zeile.schalterflaeche) {
    flex-direction: column;
    flex-wrap: nowrap;
    align-items: stretch;
    gap: 0;
    padding: 0;
  }
  .karte :global(.schalterflaeche .switchrow) {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px 8px;
    min-height: 46px;
    padding: 8px 0;
    box-sizing: border-box;
  }
  .karte :global(.schalterflaeche .switchrow[hidden]) {
    display: none;
  }
  .karte :global(.schalterflaeche .switchrow + .switchrow) {
    border-top: 1px solid var(--glass-card-line);
  }
  .karte :global(.schalterflaeche .switchrow > span) {
    flex: 1;
    min-width: 0;
    display: inline-flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px;
    font: 400 13px/18px var(--schrift);
    color: var(--text);
  }
  .karte :global(.schalterflaeche .switchrow.gesperrt > span) {
    color: var(--text-still);
  }
  .karte :global(.schalterflaeche .switchrow > :not(span)) {
    flex: none;
    width: 140px;
  }
  .karte :global(.schalterflaeche .switchrow .feldein) {
    height: 32px;
    box-sizing: border-box;
    border: 1px solid var(--feldstrich, transparent);
    border-radius: 9px;
    background: var(--glass-button);
    color: var(--text);
    font: 400 13px/18px var(--schrift);
    padding: 0 10px;
  }

  .karte :global(.hinweis) {
    flex-basis: 100%;
    margin: 0;
    font-size: 11.5px;
    line-height: 1.45;
    color: var(--text-still);
  }
  /* Colour means state: the house's "caution" tone for a known crash. */
  .karte :global(.hinweis.vorsicht) {
    color: var(--gelb-text);
  }
</style>
