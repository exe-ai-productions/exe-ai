<script>
  /* One shape for every server window.

     The six windows used to be six layouts — head cards of different
     heights, the action button sometimes in the head and sometimes at the
     foot. Read one after the other they looked like six programs rather than
     six rooms of one. So the shape lives here, once, and the windows only
     fill it in. The server's sign, its name and its start button stand in
     the page's own head (ModelleLokal.svelte), once, and not in the window:

       1  the model section: a head line and one card holding the picker, the
          folder the models lie in and whatever else the window lists there
       2  the window's own sections, 28 px apart, in rows of two columns
          where the window has them (Serverreihe.svelte)
       3  the server log at the foot

     A window with rows hands `inhalt` in; it receives the model section as a
     snippet and places it in its first row. A window without rows hands
     `mitte` in, which stands under the model section in one column.

     `modelle` is a list of {wert, text}: the window decides what a model is
     called here, the shell only draws it. */
  import Auswahlfeld from './Auswahlfeld.svelte'
  import Fenstertafel from './Fenstertafel.svelte'
  import Hauszeichen from './Hauszeichen.svelte'
  import Serverabschnitt from './Serverabschnitt.svelte'
  import Speicherortzeile from './Speicherortzeile.svelte'
  import ThroughputCard from './ThroughputCard.svelte'
  import { t } from '../lib/texte.svelte.js'

  let {
    modelle = [],
    gewaehlt = $bindable(''),
    modellBeschriftung = '',
    modellGesperrt = false,
    modellGeaendert = null,
    leerText = '',
    /* Where a model for this window is to be had: opens the catalogue on
       this window's own tab, from the door at the end of the picker row. */
    katalogTat = null,
    /* The storage location this window keeps its models in ('image_models',
       'models', 'embedding_models', 'speech_models'): the folder row of the
       model card — path, open, move. */
    speicherort = null,
    onOrtGeaendert = null,
    /* A sentence on what the picker chooses, behind the head's name: the
       small mark that shows it when pressed. */
    modellInfo = '',
    /* How many rows the model card holds, so a card beside it in the same
       row ends on the same line (Serverabschnitt.svelte, `gewicht`). */
    modellGewicht = 2,
    // Rows of the model card under the folder row: what else the folder holds.
    belowModel = null,
    /* The sign of the model card's head: the packet, unless a page has a
       sign of its own for what its models are. */
    zeichen = 'paket',
    /* The server whose tokens per second the block "Performance" shows at the
       top of the window ('model', 'agent', 'cleanup', 'speech'); none, no
       block (the picture and embedding windows make no text). */
    throughput = '',
    inhalt = null,
    mitte = null,
    unten = null,
  } = $props()
</script>

{#snippet modellblock()}
  <Serverabschnitt {zeichen} titel={modellBeschriftung} info={modellInfo} gewicht={modellGewicht}>
    <!-- The picker and the way to more of them, on one line: choosing a
         model and fetching one are the same errand. An empty folder keeps
         the same row — the picker stands there locked and says so. -->
    <div class="zeile auswahlzeile">
      <div class="feldplatz">
        <Auswahlfeld
          bind:wert={gewaehlt}
          eintraege={modelle}
          gesperrt={modellGesperrt || !modelle.length}
          leerText={modelle.length ? '' : leerText}
          beschriftung={modellBeschriftung}
          gewaehlt={modellGeaendert}
        />
      </div>
      {#if katalogTat}
        <!-- It points, it is not pressed: quiet, the brightness of a
             heading sign. -->
        <svg class="weiter" width="15" height="15" viewBox="0 0 15 15" fill="none"
             stroke="currentColor" stroke-width="1.2" stroke-linecap="round"
             stroke-linejoin="round" aria-hidden="true">
          <path d="M3.125 7.5H11.875M7.5 11.875L11.875 7.5L7.5 3.125" />
        </svg>
        <button class="katalogtuer" onclick={katalogTat}
                title={t('modell.zum_katalog')} aria-label={t('modell.zum_katalog')}>
          <Hauszeichen zeichen="raster" groesse="klein" />
        </button>
      {/if}
    </div>
    {#if speicherort}
      <Speicherortzeile name={speicherort} onaendern={onOrtGeaendert} />
    {/if}
    <!-- Under the folder row even while it is empty: the picture server's
         device list is there before any model is. -->
    {@render belowModel?.()}
  </Serverabschnitt>
{/snippet}

<Fenstertafel>
  {#if throughput}
    <ThroughputCard server={throughput} />
  {/if}
  {#if inhalt}
    {@render inhalt(modellblock)}
  {:else}
    {@render modellblock()}
    {@render mitte?.()}
  {/if}

  {@render unten?.()}
</Fenstertafel>

<style>
  /* The picker takes the line but for the arrow and the door at its end. */
  .auswahlzeile {
    gap: 10px;
  }
  .feldplatz {
    flex: 1;
    min-width: 0;
  }
  .weiter {
    flex: none;
    color: var(--text-leise);
  }
  /* Square and a little taller than the picker beside it, so the row reads
     as one control with a door at its end. */
  .katalogtuer {
    flex: none;
    width: 34px;
    height: 34px;
    padding: 0;
    display: grid;
    place-items: center;
    border: none;
    border-radius: 9px;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text-leise);
    cursor: pointer;
    transition: background 0.12s, color 0.12s;
  }
  .katalogtuer:hover {
    background: color-mix(in srgb, var(--text) 6%, var(--glass-button));
    color: var(--text);
  }
</style>
