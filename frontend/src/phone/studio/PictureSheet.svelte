<script>
  /* What can be done with one picture, as a sheet from the bottom: opened by
     a long press on the picture in the studio's surface and in the reader.
     The entries are the ones the desktop's "···" menu has
     (`StudioPictureMenu.svelte`), the mask one more: as the input, as a
     video, its infos, the faces redone, upscaled, saved — and, for the
     picture in the area, taken out of it.

     Two of these stand in the program, one for the studio and one for the
     reader (`reader`); the word between them is `pictureMenu`. A picture
     that was long-pressed in the reader leaves it for the studio, where what
     is done with it happens. */
  import { api } from '../../lib/api.js'
  import { closeReader } from '../../lib/bildschau.svelte.js'
  import { closePictureMenu, pictureMenu } from '../../lib/pictureMenu.svelte.js'
  import { startbildWaehlen, werte } from '../../lib/studio.svelte.js'
  import {
    alsEingabe, bildEntfernen, hochskalieren, infosZeigen, nachbessern, zuVideo,
  } from '../../lib/studiobilder.svelte.js'
  import { t } from '../../lib/texte.svelte.js'
  import { pageOpen } from '../pages.svelte.js'
  import Sheet from '../Sheet.svelte'

  /* `reader`: this is the reader's sheet. `onmask(name)`: the way into the
     mask page, where the studio has one. */
  let { reader = false, onmask = null } = $props()

  const name = $derived(pictureMenu.fromReader === reader ? pictureMenu.name : '')
  const inArea = $derived(!reader && Boolean(name) && name === werte.startbild)

  // The name is read before the sheet shuts: shutting can take its source away.
  function run(action) {
    const picture = name
    closePictureMenu()
    if (reader) {
      closeReader()
      pageOpen('studio')
    }
    action(picture)
  }

  function mask(picture) {
    if (werte.startbild !== picture) startbildWaehlen(picture)
    onmask?.(picture)
  }
</script>

<!-- Over the reader, which lies at 90. -->
<Sheet open={Boolean(name)} label={t('studio.bilder')} onclose={closePictureMenu} layer={reader ? 100 : 40}>
  <div class="entries" role="menu">
    <button role="menuitem" onclick={() => run(alsEingabe)}>{t('bild.als_eingabe')}</button>
    {#if onmask}
      <button role="menuitem" onclick={() => run(mask)}>{t('studio.maske')}</button>
    {/if}
    <button role="menuitem" onclick={() => run(zuVideo)}>{t('bild.zu_video')}</button>
    <button role="menuitem" onclick={() => run(infosZeigen)}>{t('bild.bild_infos')}</button>
    <button role="menuitem" onclick={() => run(nachbessern)}>{t('bild.nur_adetailer')}</button>
    <button role="menuitem" onclick={() => run(hochskalieren)}>{t('bild.nur_hochskalieren')}</button>
    <a role="menuitem" href={api.bildAdresse(name)} download={name} onclick={closePictureMenu}>
      {t('nachricht.bild_sichern')}
    </a>
    {#if inArea}
      <button role="menuitem" class="remove" onclick={() => run(bildEntfernen)}>{t('studio.bild_entfernen')}</button>
    {/if}
  </div>
</Sheet>

<style>
  .entries {
    display: flex;
    flex-direction: column;
  }
  .entries > * {
    display: block;
    min-height: var(--menuezeile);
    padding: 14px 6px;
    box-sizing: border-box;
    border: none;
    border-top: 1px solid var(--linie);
    background: none;
    color: var(--text);
    font: 400 var(--schrift-text) var(--schrift);
    text-align: left;
    text-decoration: none;
  }
  .entries > :first-child {
    border-top: none;
  }
  .remove {
    color: var(--rot-text);
  }
</style>
