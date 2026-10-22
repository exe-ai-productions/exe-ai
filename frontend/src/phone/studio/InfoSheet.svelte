<script>
  /* A picture's infos as a sheet: what it was drawn with, as the program kept
     it, else read from the picture itself (`infosZeigen` in
     `lib/studiobilder.svelte.js` asks; the desktop shows them as a card on
     its surface). "Use" writes the values into the fields. */
  import { bildInfo, infoUebernehmen } from '../../lib/studiobilder.svelte.js'
  import { t } from '../../lib/texte.svelte.js'
  import Sheet from '../Sheet.svelte'

  const ROWS = [
    ['prompt', 'bild.prompt'], ['negativ', 'bild.negativ'], ['modell', 'bild.modell'],
    ['diffusion_model', 'bild.diffusion_model'], ['vae', 'bild.vae'],
    ['breite', 'bild.breite'], ['hoehe', 'bild.hoehe'], ['schritte', 'bild.schritte'],
    ['cfg', 'bild.cfg'], ['guidance', 'bild.guidance'], ['seed', 'bild.seed'],
    ['sampler', 'bild.sampler'], ['scheduler', 'bild.scheduler'],
  ]
  const info = $derived(bildInfo.werte)
  // What is known about the picture; nothing where the program kept nothing
  // for it and its file says nothing either.
  const rows = $derived(
    ROWS.filter(([name]) => info && info[name] !== undefined && info[name] !== null && info[name] !== ''),
  )

  const close = () => (bildInfo.werte = null)
  /* The sheet belongs to the studio that is open. */
  $effect(() => () => (bildInfo.werte = null))
</script>

<Sheet open={Boolean(info)} label={t('bild.bild_infos')} onclose={close}>
  <div class="title">{t('bild.bild_infos')}</div>
  {#each rows as [name, text] (name)}
    <div class="row" class:block={name === 'prompt' || name === 'negativ'}>
      <span class="name">{t(text)}</span>
      <span class="value">{info[name]}</span>
    </div>
  {:else}
    <p class="none">{t('bild.infos_keine')}</p>
  {/each}
  {#if rows.length}
    <button class="use" onclick={infoUebernehmen}>{t('studio.uebernehmen')}</button>
  {/if}
</Sheet>

<style>
  .title {
    padding: 4px 4px 10px;
    font: 600 16px var(--schrift);
  }
  .row {
    display: flex;
    justify-content: space-between;
    gap: 14px;
    padding: 9px 6px;
    border-top: 1px solid var(--linie);
    font: 400 14px var(--schrift);
  }
  .row.block {
    flex-direction: column;
    gap: 4px;
  }
  .name {
    flex: none;
    color: var(--text-still);
  }
  .value {
    min-width: 0;
    overflow-wrap: anywhere;
    text-align: right;
    color: var(--text);
  }
  .row.block .value {
    text-align: left;
  }
  .none {
    margin: 8px 6px;
    color: var(--text-still);
  }
  .use {
    width: 100%;
    height: 44px;
    margin-top: 10px;
  }
</style>
