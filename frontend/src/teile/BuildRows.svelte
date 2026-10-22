<script>
  /* The builds of a server program, one row each, and the way back to the
     tested one under a fold. It stands inside the card of the program's
     section: every row is a direct child of the card, so the card's row
     rules (height, inset, hairline) apply to it.

     A row names the build and what it is:
       installed   "Installed" in green with a tick
       available   its size, then the download button of a file row
       locked      the same, but dimmed and pressed by nothing: the build is
                   listed so that it is seen, and this machine cannot run it

     The rows, what is installed and the two actions come from above; the
     piece itself asks no service. `status` is drawn under the rows (the bar
     of a running download, its error). The fold "Advanced" stands only
     where there is a tested build to go back to (`restorable`), is open when
     it first shows, and holds the one row that goes back. */
  import DownloadRow from './DownloadRow.svelte'
  import Hauszeichen from './Hauszeichen.svelte'
  import { t } from '../lib/texte.svelte.js'

  let {
    /* [{ variante, groesse }] — the size in bytes of all a build downloads. */
    builds = [],
    /* The name of the build that is installed, if one is. */
    installed = null,
    /* The builds are shown but cannot be fetched on this machine. */
    locked = false,
    /* A download is on its way: nothing else can be started. */
    busy = false,
    restorable = false,
    onDownload,
    onRestore,
    status,
  } = $props()

  let foldOpen = $state(true)

  function sizeText(bytes) {
    return `${Math.round(bytes / (1024 * 1024))} MB`
  }
</script>

{#each builds as b (b.variante)}
  <div class="zeile" class:gesperrt={locked}>
    <span class="name">{b.variante}</span>
    {#if !locked && b.variante === installed}
      <span class="da">
        {t('bildserver.variante_installiert')}
        <span class="haken"><Hauszeichen zeichen="haken" groesse={14} strich={2.6} /></span>
      </span>
    {:else}
      <span class="groesse">{sizeText(b.groesse)}</span>
      <DownloadRow status="neu" disabled={locked || busy} onDownload={() => onDownload?.(b.variante)} />
    {/if}
  </div>
{/each}
{@render status?.()}
{#if restorable}
  <button class="zeile klappzeile" aria-expanded={foldOpen} onclick={() => (foldOpen = !foldOpen)}>
    <span class="winkel" class:auf={foldOpen}><Hauszeichen zeichen="chevron_right" groesse={14} /></span>
    <span class="klapptext">{t('modell.gruppe_erweitert')}</span>
  </button>
  {#if foldOpen}
    <div class="zeile">
      <span class="name">{t('bildserver.restore_tested_build')}</span>
      <button class="zeichenknopf" disabled={busy} onclick={() => onRestore?.()}
              title={t('bildserver.restore_tested_build')}
              aria-label={t('bildserver.restore_tested_build')}>
        <Hauszeichen zeichen="refresh" groesse={14} />
      </button>
    </div>
  {/if}
{/if}

<style>
  /* The names of the builds and of the way back are set in the semi-bold
     the section's version line has; the sizes and the word "Installed" stay
     in the regular weight. */
  .name {
    font-weight: 600;
  }
  /* A build that cannot be fetched here stands back: its name and its size
     are dimmed, and its button is locked. */
  .gesperrt .name,
  .gesperrt .groesse {
    opacity: 0.4;
  }
  .groesse {
    flex: none;
    font: 400 12px var(--schrift-fest);
    color: var(--text-leise);
    white-space: nowrap;
  }
  .da {
    flex: none;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 13px;
    color: var(--gruen-text);
    white-space: nowrap;
  }
  /* The tick is a shape: the colour of the shape, as the tick of a finished
     download wears it, next to the word in the colour of text. */
  .haken {
    display: inline-flex;
    color: var(--gruen);
  }
  /* The fold is a row of its own, lower than the rest, and a button. It
     names the element as well, so that it outweighs the row rule of the
     card. */
  button.zeile.klappzeile {
    min-height: 44px;
    padding-top: 0;
    padding-bottom: 0;
    flex-grow: 0;
    gap: 8px;
    width: 100%;
    border: none;
    background: none;
    font: inherit;
    text-align: left;
    cursor: pointer;
  }
  .klapptext {
    font: 600 13px/18px var(--schrift);
    color: var(--text-leise);
  }
  .winkel {
    flex: none;
    display: inline-flex;
    color: var(--text-still);
    transition: transform 0.15s;
  }
  .winkel.auf {
    transform: rotate(90deg);
  }
  @media (prefers-reduced-motion: reduce) {
    .winkel {
      transition: none;
    }
  }
  /* The one sign button of a row that is 34 px, like the buttons of a card:
     button glass with its fine edge. */
  .zeichenknopf {
    width: 34px;
    height: 34px;
    flex: none;
    display: inline-grid;
    place-items: center;
    padding: 0;
    border: none;
    border-radius: 9px;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text);
    cursor: pointer;
    transition: background 0.12s;
  }
  .zeichenknopf:hover:not(:disabled) {
    background: var(--glass-hover);
  }
  .zeichenknopf:disabled {
    cursor: default;
    opacity: 0.5;
  }
</style>
