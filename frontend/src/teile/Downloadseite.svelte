<!-- The downloads as a page of the catalogue column: what runs, what waits and
     what arrived in this session, one row each. Every row reaches the
     repository it came from through one button with the Hugging Face mark;
     the cross at the end of the first line cancels a running or waiting file.
     Finished rows stay as a receipt while the window lives.

     Layout of a running row, three lines in one grid — the buttons stand in
     the right column, so nothing floats and nothing touches anything else:

       dot  name ........................ X
            bar ........ 46 MB/s  38 %
            12.4 / 32.5 GB ......... [Hugging Face]                       -->
<script>
  import Hauszeichen from './Hauszeichen.svelte'
  import { downloads, ausreihen, zieldatei } from '../lib/downloads.svelte.js'
  import { LOGOS } from '../lib/logos.js'
  import { t } from '../lib/texte.svelte.js'

  let { stand = null, tempo = '', onAbbrechen } = $props()

  const gb = (bytes) => (bytes / 1e9).toFixed(1)
  const laeuft = $derived(Boolean(stand) && !stand.fertig && !stand.fehler)
  const anteil = $derived(Math.round((stand?.anteil ?? 0) * 100))
  const leer = $derived(!laeuft && !downloads.warteschlange.length && !downloads.fertig.length)
  const huggingFace = LOGOS.huggingface

  /* The repository a local file was fetched from, as the queue remembered it. */
  const repoVon = (datei) => downloads.repos[datei] ?? null
  const hatSeite = (repo) => typeof repo === 'string' && repo.includes('/')
  function seiteOeffnen(repo) {
    window.open(`https://huggingface.co/${repo}`, '_blank')
  }
</script>

{#snippet seitenknopf(repo)}
  {#if hatSeite(repo)}
    <button class="knopf" onclick={() => seiteOeffnen(repo)}
            title={t('editor.quelle_hf')} aria-label={t('editor.quelle_hf')}>
      <svg viewBox={huggingFace.vb} width="18" height="18" aria-hidden="true">{@html huggingFace.html}</svg>
    </button>
  {/if}
{/snippet}

<div class="seite">
  {#if leer}
    <p class="leer">{t('downloads.leer')}</p>
  {/if}

  {#if laeuft}
    <div class="zeile">
      <span class="punkt blau"></span>
      <span class="datei">{stand.datei}</span>
      <button class="knopf" onclick={onAbbrechen}
              title={t('katalog.abbrechen')} aria-label={t('katalog.abbrechen')}>
        <Hauszeichen zeichen="kreuz" groesse={16} />
      </button>
      <span></span>
      <div class="laufleiste">
        <span class="balken"><i style="width:{anteil}%"></i></span>
        {#if tempo}<span class="tempo">{tempo}</span>{/if}
        <span class="prozent">{anteil} %</span>
      </div>
      <span></span>
      <span></span>
      <span class="zahlen">{gb(stand.geladen)} / {gb(stand.gesamt)} GB</span>
      <span class="ende">{@render seitenknopf(repoVon(stand.datei))}</span>
    </div>
  {/if}

  {#each downloads.warteschlange as job (job.nummer)}
    <div class="zeile wartet">
      <span class="punkt still"></span>
      <span class="datei">{zieldatei(job)}</span>
      <button class="knopf" onclick={() => ausreihen(job)}
              title={t('katalog.abbrechen')} aria-label={t('katalog.abbrechen')}>
        <Hauszeichen zeichen="kreuz" groesse={16} />
      </button>
      <span></span>
      <span class="zahlen">{t('downloads.wartet')}</span>
      <span class="ende">{@render seitenknopf(job.repo)}</span>
    </div>
  {/each}

  {#each downloads.fertig as eintrag (eintrag.datei)}
    <div class="zeile fertig">
      <span class="punkt gruen"></span>
      <span class="datei">{eintrag.datei}</span>
      <span class="ende">{@render seitenknopf(repoVon(eintrag.datei))}</span>
      <span></span>
      <span class="zahlen">
        {#if eintrag.groesse}{gb(eintrag.groesse)} GB · {/if}{t('downloads.fertig')}
      </span>
    </div>
  {/each}
</div>

<style>
  /* As wide as every other page of the catalogue; its heading and the
     token row above it come from the catalogue itself. */
  .seite {
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 8px 0 4px;
  }
  .leer {
    margin: 0;
    font-size: 13px;
    color: var(--text-still);
  }
  .zeile {
    display: grid;
    grid-template-columns: 10px minmax(0, 1fr) 32px;
    column-gap: 12px;
    row-gap: 8px;
    align-items: center;
    border-radius: 9px;
    background: var(--bg-hoch);
    padding: 12px 14px;
  }
  .zeile.wartet {
    opacity: 0.72;
  }
  .punkt {
    width: 9px;
    height: 9px;
    border-radius: 99px;
  }
  .punkt.blau { background: var(--blau); }
  .punkt.still { background: var(--text-still); }
  .punkt.gruen { background: var(--gruen); }
  .datei {
    font: 500 13px var(--schrift);
    overflow-wrap: anywhere;
    min-width: 0;
  }
  .knopf {
    width: 32px;
    height: 32px;
    display: inline-grid;
    place-items: center;
    padding: 0;
    border: none;
    border-radius: 9px;
    background: none;
    color: var(--text-leise);
    cursor: pointer;
  }
  .knopf:hover {
    background: color-mix(in srgb, var(--text) 8%, transparent);
    color: var(--text);
  }
  .laufleiste {
    display: flex;
    align-items: center;
    gap: 12px;
  }
  .balken {
    flex: 1;
    height: 4px;
    border-radius: 9px;
    background: var(--bg-erhoben);
    overflow: hidden;
  }
  .balken i {
    display: block;
    height: 100%;
    background: var(--blau);
    transition: width 0.3s;
  }
  /* Speed and percentage stand in the bar's own line, one after the other,
     never touching. */
  .tempo,
  .prozent {
    font: 500 12.5px var(--schrift);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
  .tempo { color: var(--text-leise); }
  .prozent { color: var(--blau); }
  .zahlen {
    font: 400 12px var(--schrift);
    color: var(--text-still);
    font-variant-numeric: tabular-nums;
  }
  .ende {
    display: inline-flex;
    justify-content: flex-end;
  }
</style>
