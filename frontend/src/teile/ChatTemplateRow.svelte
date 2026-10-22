<script>
  /* The row "Chat template" of a chat server's model card: where the
     template the server starts with comes from — the one the model file
     carries (Jinja, the default) or a copy of it that the user edits — and
     the two things to do about it: open the copy in the text editor, and
     show the file in the file manager.

     It owns nothing. The page holds the choice (`wert`, bound) and does the
     two deeds (`onedit`, `onreveal`); a server that runs is not edited
     (`gesperrt`), as every other row of the window. The row stands under the
     folder row of the model card (Servertafel.svelte, `belowModel`) and is
     there only while a model is chosen: the template is the model's. */
  import { t } from '../lib/texte.svelte.js'
  import Auswahlfeld from './Auswahlfeld.svelte'
  import Hauszeichen from './Hauszeichen.svelte'

  let { modell = '', wert = $bindable('model'), gesperrt = false, onchoose = null, onedit = null, onreveal = null } = $props()

  const auswahl = $derived([
    { wert: 'model', text: t('modell.vorlage_jinja') },
    { wert: 'file', text: t('modell.vorlage_datei') },
  ])
</script>

<div class="zeile template">
  <div class="head">
    <span class="name">{t('modell.feld_chat_vorlage')}</span>
    <span class="file" title={modell}>{modell}</span>
  </div>
  <div class="wahl narrow">
    <Auswahlfeld bind:wert eintraege={auswahl} {gesperrt}
                 beschriftung={t('modell.feld_chat_vorlage')} gewaehlt={onchoose} />
  </div>
  <button class="rowsign" type="button" disabled={gesperrt} onclick={onedit}
          title={t('modell.vorlage_bearbeiten')} aria-label={t('modell.vorlage_bearbeiten')}>
    <Hauszeichen zeichen="stift" groesse={16} />
  </button>
  <button class="rowsign" type="button" onclick={onreveal}
          title={t('modell.vorlage_zeigen')} aria-label={t('modell.vorlage_zeigen')}>
    <Hauszeichen zeichen="ordner" groesse={16} />
  </button>
</div>

<style>
  /* The name over the model's file, in the typewriter face the page uses for
     a file name. */
  .head {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .file {
    font: 400 11px/14px var(--schrift-fest);
    color: var(--text-still);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .wahl.narrow {
    flex: none;
    width: 160px;
  }
  .rowsign:disabled {
    cursor: default;
    opacity: 0.5;
  }
</style>
