<script>
  /* A picture's infos as a card on the studio surface: what it was drawn
     with, as the program kept it, else read from the picture itself. "Use"
     writes the values into the fields (lib/studiobilder.svelte.js). */
  import Hauszeichen from './Hauszeichen.svelte'
  import { bildInfo, infoUebernehmen } from '../lib/studiobilder.svelte.js'
  import { t } from '../lib/texte.svelte.js'

  const INFO_ZEILEN = [
    ['prompt', 'bild.prompt'], ['negativ', 'bild.negativ'], ['modell', 'bild.modell'],
    ['diffusion_model', 'bild.diffusion_model'], ['vae', 'bild.vae'],
    ['breite', 'bild.breite'], ['hoehe', 'bild.hoehe'], ['schritte', 'bild.schritte'],
    ['cfg', 'bild.cfg'], ['guidance', 'bild.guidance'], ['seed', 'bild.seed'],
    ['sampler', 'bild.sampler'], ['scheduler', 'bild.scheduler'],
  ]
  const info = $derived(bildInfo.werte)
  // What is known about the picture; nothing where the program kept
  // nothing for it and its file says nothing either.
  const rows = $derived(INFO_ZEILEN.filter(([name]) =>
    info && info[name] !== undefined && info[name] !== null && info[name] !== ''))

  // The card belongs to the open studio.
  $effect(() => () => (bildInfo.werte = null))
</script>

{#if info}
  <div class="infokarte" role="dialog" aria-label={t('bild.bild_infos')}>
    <div class="infokopf">
      <span class="infotitel">{t('bild.bild_infos')}</span>
      <button class="weg" onclick={() => (bildInfo.werte = null)} aria-label={t('app.schliessen')}
              title={t('app.schliessen')}><Hauszeichen zeichen="kreuz" groesse={12} /></button>
    </div>
    {#each rows as [name, text] (name)}
      <div class="infozeile" class:block={name === 'prompt'}>
        <span class="infoname">{t(text)}</span>
        <span class="infowert">{info[name]}</span>
      </div>
    {:else}
      <p class="leer">{t('bild.infos_keine')}</p>
    {/each}
    {#if rows.length}
      <div class="infofuss">
        <button class="uebernehmen" onclick={infoUebernehmen}>{t('studio.uebernehmen')}</button>
      </div>
    {/if}
  </div>
{/if}

<style>
  .infokarte {
    position: absolute;
    top: 122px;
    right: 160px;
    z-index: 6;
    width: 320px;
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 14px 14px 12px;
    border-radius: 9px;
    background: var(--glass-card);
    box-shadow: inset 0 0 0 1px var(--glass-card-line), 0 16px 48px rgba(0, 0, 0, 0.18);
    backdrop-filter: blur(14px);
    color: var(--text);
    font: 400 13px/18px var(--schrift);
  }
  .infokopf {
    display: flex;
    align-items: center;
    margin-bottom: 2px;
  }
  .infotitel {
    flex: 1;
    font-weight: 600;
    font-size: 14px;
  }
  .weg {
    display: grid;
    place-items: center;
    width: 24px;
    height: 24px;
    padding: 0;
    border: none;
    border-radius: 9px;
    background: none;
    color: var(--text-leise);
    cursor: pointer;
  }
  .weg:hover {
    background: var(--glass-hover);
    color: var(--text);
  }
  .infozeile {
    display: grid;
    grid-template-columns: 106px 1fr;
    gap: 8px;
  }
  .infozeile.block {
    grid-template-columns: 1fr;
    gap: 2px;
  }
  .infoname {
    color: var(--text-leise);
  }
  .infowert {
    overflow-wrap: anywhere;
  }
  .leer {
    margin: 0;
    font-size: 12px;
    line-height: 1.45;
    color: var(--text-still);
  }
  .infofuss {
    display: flex;
    justify-content: flex-end;
    margin-top: 4px;
  }
  .uebernehmen {
    height: 30px;
    padding: 0 12px;
    border: none;
    border-radius: 9px;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text);
    font: 400 13px/18px var(--schrift);
    cursor: pointer;
  }
</style>
