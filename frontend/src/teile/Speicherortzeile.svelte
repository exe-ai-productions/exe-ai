<script>
  /* One storage location as a row: where it is, a button to open it, and the
     catalogue's folder mark to move it. The same control wherever a folder
     can be seen and changed — the pictures module and each of the three
     server panels — so "this is about a folder" reads the same everywhere,
     and there is one place to change how it works.

     It owns only this one location, addressed by name ('images',
     'image_models', 'models', 'embedding_models'). After a move it reloads itself
     and tells the parent, so a picture wall or a model list built on the old
     folder can refresh.

     The row is the same wherever it stands: the name, the path, the two
     buttons — the gallery's and the doc folder's alike. A place whose path
     is not the named location's (the doc folder inside a chat, whose files
     lie in that chat's own folder) hands the path to show as `pathText`,
     together with `onopen`. The buttons' size comes from `--ordnerknopf`
     where a place sets it. */
  import { api } from '../lib/api.js'
  import Hauszeichen from './Hauszeichen.svelte'
  import { t } from '../lib/texte.svelte.js'
  import { melde, frage } from '../lib/zustand.svelte.js'

  /* `onopen` is for a row that at times stands for another folder than its
     named location — the doc folder inside a chat, where the files lie in
     that chat's own folder: the folder button then asks the parent to show
     that one. */
  let {
    name, etikett = '', onaendern = null, onopen = null, pathText = null,
  } = $props()

  let pfad = $state('')
  const shownPath = $derived(pathText ?? pfad)
  let neustartNoetig = $state(false)

  async function laden() {
    try {
      const orte = await api.speicherorteLesen()
      const o = orte.find((x) => x.name === name)
      pfad = o ? o.pfad : ''
    } catch (fehler) {
      melde(String(fehler.message || fehler), 'fehler')
    }
  }

  $effect(() => { if (name) laden() })

  async function oeffnen() {
    try {
      if (onopen) await onopen()
      else await api.speicherortOeffnen(name)
    } catch (fehler) {
      melde(String(fehler.message || fehler), 'fehler')
    }
  }

  async function aendern() {
    const neu = await frage(t('speicherorte.frage'), { eingabe: pfad })
    if (!neu || neu === pfad) return
    try {
      const antwort = await api.speicherortSetzen(name, neu)
      neustartNoetig = !antwort.ist_standard && antwort.neustart_noetig
      pfad = antwort.pfad
      melde(t('speicherorte.geaendert'), 'hinweis')
      onaendern?.()
    } catch (fehler) {
      melde(String(fehler.message || fehler), 'fehler')
    }
  }
</script>

<div class="zeile">
  {#if etikett}<span class="etikett">{etikett}</span>{/if}
  <span class="pfad" title={shownPath}>{shownPath}</span>
  <!-- Open and change as a tight cluster of square icon buttons, held closer
       to each other than to the path, so they read as one group of tools. -->
  <div class="knopfpaar">
    <button class="ordnerknopf" onclick={oeffnen} title={t('speicherorte.oeffnen')}
            aria-label={t('speicherorte.oeffnen')}>
      <Hauszeichen zeichen="ordner" groesse="klein" />
    </button>
    <button class="ordnerknopf" onclick={aendern} title={t('speicherorte.aendern')}
            aria-label={t('speicherorte.aendern')}>
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
           stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <!-- The house pencil, not a folder: this button does not open the
             folder — the one beside it does — it CHANGES which folder is
             meant. Two buttons wearing one sign taught two different lessons
             in two different windows. -->
        <path d="M17 3l4 4L8 20l-5 1 1-5L17 3z" />
      </svg>
    </button>
  </div>
</div>
{#if neustartNoetig}
  <p class="hinweis">{t('speicherorte.neustart')}</p>
{/if}

<style>
  .zeile {
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
  }
  .etikett {
    font-size: 12px;
    font-weight: 600;
    color: var(--text);
    flex: none;
  }
  .pfad {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    /* Keep the folder name in view under the ellipsis, not the drive root.
       plaintext keeps the path itself reading left-to-right, so the digits
       and punctuation in a path like /Volumes/Data Disk/… are not reordered by
       the rtl box — only the truncation side moves to the front. */
    direction: rtl;
    unicode-bidi: plaintext;
    text-align: left;
    /* A path reads in the one face of the house, like every other datum. A
       server window's card sets it one step larger (Serverabschnitt.svelte). */
    font: 400 var(--pfad-schrift, 11px) var(--schrift);
    color: var(--text-still);
  }
  .knopfpaar {
    flex: none;
    display: inline-flex;
    align-items: center;
    gap: 8px;
  }
  .ordnerknopf {
    flex: none;
    font: inherit;
    font-size: 12px;
    /* A sign button in button glass with its fine edge. */
    border: none;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text);
    border-radius: 9px;
    cursor: pointer;
  }
  /* Square, the one size of a sign button in the house. */
  .ordnerknopf {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: var(--ordnerknopf, 30px);
    height: var(--ordnerknopf, 30px);
    box-sizing: border-box;
    padding: 0;
    border-radius: 9px;
    color: var(--text-leise);
  }
  .ordnerknopf:hover { background: var(--glass-hover); }
  .hinweis {
    margin: 6px 0 0;
    font-size: 11.5px;
    color: var(--gelb);
  }
</style>
