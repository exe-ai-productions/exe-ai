<script>
  /* The "···" menu of one studio picture. The row of pictures offers it
     with "As input"; the generation area, whose picture already is the
     input, offers "Remove picture" in its place. Every entry shuts it. */
  import { api } from '../lib/api.js'
  import { alsEingabe, bildEntfernen, hochskalieren, infosZeigen, nachbessern, zuVideo } from '../lib/studiobilder.svelte.js'
  import { t } from '../lib/texte.svelte.js'

  let { name, zu, imBereich = false } = $props()

  // The name is read before the menu shuts: shutting can take its source away.
  function waehle(tun) {
    const bild = name
    zu()
    tun(bild)
  }
</script>

<div class="menue" role="menu">
  {#if !imBereich}
    <button role="menuitem" onclick={() => waehle(alsEingabe)}>{t('bild.als_eingabe')}</button>
  {/if}
  <button role="menuitem" onclick={() => waehle(zuVideo)}>{t('bild.zu_video')}</button>
  <button role="menuitem" onclick={() => waehle(infosZeigen)}>{t('bild.bild_infos')}</button>
  <button role="menuitem" onclick={() => waehle(nachbessern)}>{t('bild.nur_adetailer')}</button>
  <button role="menuitem" onclick={() => waehle(hochskalieren)}>{t('bild.nur_hochskalieren')}</button>
  <a role="menuitem" href={api.bildAdresse(name)} download={name} onclick={zu}>{t('nachricht.bild_sichern')}</a>
  {#if imBereich}
    <span class="trenner" aria-hidden="true"></span>
    <button role="menuitem" onclick={() => waehle(bildEntfernen)}>{t('studio.bild_entfernen')}</button>
  {/if}
</div>

<style>
  .menue {
    display: flex;
    flex-direction: column;
    min-width: 190px;
    padding: 4px;
    border-radius: 9px;
    background: var(--glass-card);
    box-shadow: inset 0 0 0 1px var(--glass-card-line), 0 8px 28px rgba(0, 0, 0, 0.14);
    backdrop-filter: blur(14px);
  }
  button,
  a {
    height: 30px;
    padding: 0 10px;
    border: none;
    border-radius: 9px;
    background: none;
    color: var(--text);
    font: 400 13px/30px var(--schrift);
    text-align: left;
    text-decoration: none;
    white-space: nowrap;
    cursor: pointer;
  }
  button:hover,
  a:hover {
    background: var(--glass-hover);
  }
  .trenner {
    height: 1px;
    margin: 4px 6px;
    background: var(--glass-card-line);
  }
</style>
