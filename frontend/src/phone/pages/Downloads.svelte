<script module>
  export const meta = { name: 'downloads', title: 'downloads.titel', sign: 'download', place: 'list', order: 34 }
</script>

<script>
  /* What is being fetched, what waits and what arrived in this session: one
     card for each, the running one with its bar, its speed and a way to
     stop it. */
  import { t } from '../../lib/texte.svelte.js'
  import { downloads, ausreihen, zieldatei } from '../../lib/downloads.svelte.js'
  import Hauszeichen from '../../teile/Hauszeichen.svelte'
  import Group from '../parts/Group.svelte'
  import Line from '../parts/Line.svelte'
  import { feed, watchDownloads, cancelDownload, running } from '../downloadFeed.svelte.js'
  import { gigabytes } from '../catalog.js'

  $effect(() => watchDownloads())

  const percent = $derived(Math.round((feed.stand?.anteil ?? 0) * 100))
  const rate = $derived(feed.speed > 50_000 ? `${(feed.speed / 1e6).toFixed(1)} MB/s` : '')
  const empty = $derived(!running() && !downloads.warteschlange.length && !downloads.fertig.length)
</script>

{#if empty}
  <Group><Line label={t('downloads.leer')} /></Group>
{/if}

{#if running()}
  <div class="card">
    <div class="top">
      <span class="name">{feed.stand.datei}</span>
      <button class="cross" onclick={cancelDownload} aria-label={t('katalog.abbrechen')}>
        <Hauszeichen zeichen="kreuz" groesse={16} />
      </button>
    </div>
    <div class="bar"><i style="width:{percent}%"></i></div>
    <div class="facts">
      <span>{gigabytes(feed.stand.geladen)} / {gigabytes(feed.stand.gesamt)} GB</span>
      <span>{rate ? `${rate} · ` : ''}{percent} %</span>
    </div>
  </div>
{/if}

{#each downloads.warteschlange as job (job.nummer)}
  <div class="card waiting">
    <div class="top">
      <span class="name">{zieldatei(job)}</span>
      <button class="cross" onclick={() => ausreihen(job)} aria-label={t('katalog.abbrechen')}>
        <Hauszeichen zeichen="kreuz" groesse={16} />
      </button>
    </div>
    <div class="facts"><span>{t('downloads.wartet')}</span></div>
  </div>
{/each}

{#each downloads.fertig as entry (entry.datei)}
  <div class="card done">
    <div class="top"><span class="name">{entry.datei}</span></div>
    <div class="facts">
      <span>{entry.groesse ? `${gigabytes(entry.groesse)} GB · ` : ''}{t('downloads.fertig')}</span>
    </div>
  </div>
{/each}

<style>
.card {
  margin: 8px 2px 0;
  padding: 12px 14px;
  border-radius: 9px;
  background: var(--bg-hoch);
}
.top {
  display: flex;
  align-items: center;
  gap: 10px;
}
.name {
  flex: 1;
  min-width: 0;
  overflow-wrap: anywhere;
  font: 500 var(--schrift-text) var(--schrift);
  color: var(--text);
}
.cross {
  display: grid;
  place-items: center;
  flex: none;
  width: 36px;
  height: 36px;
  border: none;
  border-radius: 9px;
  background: none;
  color: var(--text-leise);
}
.cross:active {
  background: var(--glass-button);
}
.bar {
  height: 6px;
  margin: 10px 0 6px;
  border-radius: 99px;
  background: var(--glass-button);
  overflow: hidden;
}
.bar i {
  display: block;
  height: 100%;
  background: var(--blau, var(--text));
  transition: width 0.4s;
}
.facts {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  margin-top: 6px;
  font: 400 var(--schrift-hinweis) var(--schrift);
  color: var(--text-still);
  font-variant-numeric: tabular-nums;
}
.waiting .name,
.done .name {
  color: var(--text-leise);
}
</style>
