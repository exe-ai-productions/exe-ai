<!-- The downloads as a page of the catalogue column: what runs, what waits and
     what arrived in this session, in one card with a hairline between the
     entries. Every entry is 72 high and has two lines in one grid, so nothing
     floats and nothing touches anything else, and the card is as high as its
     entries:

       [maker] name ............................ [HF]
               bar .... 42 % | 12,4 / 32,5 GB · 48,2 MB/s [X]

     The maker's logo stands before the name; the small Hugging Face mark at
     the end of the first line reaches the repository the file came from and
     sits over the cross of the second line, in the same 22 px column. The
     second line begins under the name and is the download row of the
     catalogue (DownloadRow): the bar and the cross while it runs, "Waiting"
     and the cross while it waits, the green tick when it arrived. Finished
     entries stay as a receipt while the window lives. -->
<script>
  import DownloadRow from './DownloadRow.svelte'
  import OwnerMark from './OwnerMark.svelte'
  import { downloads, ausreihen, zieldatei } from '../lib/downloads.svelte.js'
  import { fileMark } from '../lib/fileMark.js'
  import { LOGOS } from '../lib/logos.js'
  import { t, texte } from '../lib/texte.svelte.js'
  import { formatGb } from '../lib/numberDisplay.js'

  let { stand = null, tempo = '', onAbbrechen } = $props()

  /* A receipt keeps the size in bytes, as the service reports it; a queued job
     carries it in GB, as the catalogue lists it. */
  const gb = (bytes) => formatGb(bytes / 1e9, texte.sprache)
  const laeuft = $derived(Boolean(stand) && !stand.fertig && !stand.fehler)
  const anteil = $derived(Math.round((stand?.anteil ?? 0) * 100))
  const leer = $derived(!laeuft && !downloads.warteschlange.length && !downloads.fertig.length)
  const huggingFace = LOGOS.huggingface

  /* The repository a local file was fetched from, as the queue remembered it. */
  const repoVon = (datei) => downloads.repos[datei] ?? null
  const hatSeite = (repo) => typeof repo === 'string' && repo.includes('/')
  const ownerOf = (repo) => (hatSeite(repo) ? repo.split('/')[0] : '')
  function seiteOeffnen(repo) {
    window.open(`https://huggingface.co/${repo}`, '_blank')
  }
</script>

{#snippet head(datei, repo)}
  <span class="mark">
    <OwnerMark mark={fileMark(datei)} owner={ownerOf(repo)} letter={String(datei).slice(0, 1).toUpperCase()} size={18} />
  </span>
  <span class="datei" title={datei}>{datei}</span>
  <span class="hf">
    {#if hatSeite(repo)}
      <button class="seitenknopf" onclick={() => seiteOeffnen(repo)}
              title={t('editor.quelle_hf')} aria-label={t('editor.quelle_hf')}>
        <svg viewBox={huggingFace.vb} width="14" height="14" aria-hidden="true">{@html huggingFace.html}</svg>
      </button>
    {/if}
  </span>
{/snippet}

<div class="page">
  {#if leer}
    <p class="leer">{t('downloads.leer')}</p>
  {:else}
    <div class="list">
      {#if laeuft}
        <div class="entry">
          {@render head(stand.datei, repoVon(stand.datei))}
          <div class="zeile">
            <DownloadRow status="laedt" percent={anteil}
                         amounts={`${gb(stand.geladen)} / ${gb(stand.gesamt)} GB${tempo ? ' · ' + tempo : ''}`}
                         onCancel={onAbbrechen} />
          </div>
        </div>
      {/if}

      {#each downloads.warteschlange as job (job.nummer)}
        <div class="entry">
          {@render head(zieldatei(job), job.repo)}
          <div class="zeile">
            {#if job.groesse}<span class="size">{t('modell.gb', { zahl: formatGb(job.groesse, texte.sprache) })}</span>{/if}
            <DownloadRow status="wartet" onDequeue={() => ausreihen(job)} />
          </div>
        </div>
      {/each}

      {#each downloads.fertig as eintrag (eintrag.datei)}
        <div class="entry">
          {@render head(eintrag.datei, repoVon(eintrag.datei))}
          <div class="zeile">
            {#if eintrag.groesse}<span class="size">{t('modell.gb', { zahl: gb(eintrag.groesse) })}</span>{/if}
            <DownloadRow status="bereit" />
          </div>
        </div>
      {/each}
    </div>
  {/if}
</div>

<style>
  /* As wide as every other page of the catalogue; its heading and the
     token row above it come from the catalogue itself. */
  .page {
    padding: 8px 0 4px;
  }
  /* One card for every entry, as high as they are, with a hairline between
     the entries. */
  .list {
    padding: 4px 0;
    border-radius: 9px;
    background: var(--glass-card);
    box-shadow: inset 0 0 0 1px var(--glass-card-line);
  }
  /* No entry: a card of one line, the sentence in its middle. */
  .leer {
    margin: 0;
    border-radius: 9px;
    background: var(--glass-card);
    box-shadow: inset 0 0 0 1px var(--glass-card-line);
    padding: 16px;
    font-size: 13px;
    line-height: 18px;
    text-align: center;
    color: var(--text-still);
  }
  /* An entry is 72 high: 10 above and below, two lines of 22 and 8 between
     them. The hairline is drawn inside, so it adds no height. */
  .entry {
    box-sizing: border-box;
    height: 72px;
    padding: 10px 10px 10px 14px;
    display: grid;
    grid-template-columns: 18px minmax(0, 1fr) 22px;
    grid-template-rows: 22px 22px;
    column-gap: 10px;
    row-gap: 8px;
    align-items: center;
  }
  .entry + .entry {
    box-shadow: inset 0 1px 0 var(--linie);
  }
  .mark {
    display: inline-flex;
    justify-content: center;
  }
  /* Cut with an ellipsis; the whole name stands in the tooltip. */
  .datei {
    min-width: 0;
    font: 500 13px var(--schrift);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  /* The Hugging Face mark in the 22 px column of the cross below it. */
  .hf {
    display: inline-grid;
    place-items: center;
    width: 22px;
    height: 22px;
  }
  .seitenknopf {
    width: 22px;
    height: 22px;
    display: inline-grid;
    place-items: center;
    padding: 0;
    border: none;
    border-radius: 9px;
    background: none;
    cursor: pointer;
  }
  .seitenknopf:hover {
    background: color-mix(in srgb, var(--text) 8%, transparent);
  }
  /* The second line begins under the name and ends at the cross: the bar or
     the size, then the state. */
  .zeile {
    grid-column: 2 / -1;
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: 12px;
    min-width: 0;
  }
  .size {
    font: 400 12px var(--schrift);
    color: var(--text-still);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
</style>
