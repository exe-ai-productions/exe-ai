<script>
  /* The window for choosing a working folder.

     Only the mask lives here — the folders are shown by the input bar's
     folder chip (FolderChip.svelte), and the logic sits in
     lib/arbeitsordner.svelte.js, which both use. This component is mounted
     exactly once.

     Two ways in, because a browser never hands out a real path: the system
     dialog (Finder / Explorer, opened by the service) and the path field.
     The dialog is the comfortable way and brings "New Folder" along; the
     field is the one that works everywhere — in a container, over the
     network, on a machine without a dialog tool. */
  import Fenster from './Fenster.svelte'
  import { t } from '../lib/texte.svelte.js'
  import { system } from '../lib/keyNames.js'
  import { displayPath } from '../lib/paths.js'
  import {
    ordnerZustand, dialogPruefen, ordnerHinzufuegen, systemdialog,
    ersatzBeginnen, ordnerstandPruefen, notizenZurueckholen,
    ordnerListe,
  } from '../lib/arbeitsordner.svelte.js'

  /* The house's caution mark — the triangle from the notices
     (Meldungen.svelte, ZEICHEN.warnung), not a second drawing of the same
     idea. */
  const WARNZEICHEN = 'M12 4L2.5 20h19zM12 10v4M12 17h.01'

  let pfadfeld = $state('')
  let feld = $state(null)

  // Ask once whether this machine has a folder dialog at all. A button that
  // clicks into nothing is worse than no button.
  $effect(() => {
    dialogPruefen()
  })

  // Empty the field each time the window opens, and put the cursor in it.
  $effect(() => {
    if (ordnerZustand.maskeOffen) {
      pfadfeld = ''
      setTimeout(() => feld?.focus(), 80)
    }
  })

  /* Ask on every opening, never once at startup: a folder can move and an
     ``exe.md`` can go missing at any moment — a tool call, a hand, a folder
     resynced from somewhere else — and an answer kept from the last time
     this window was open would offer a copy for a file that is back, or
     stay silent about one that has just gone.

     BOTH halves are asked, through the one function that asks them in
     order: which folders are missing decides which of them may be offered
     their notes back, so a check that asked only the second half would
     offer to write into a folder that is not there any more. */
  $effect(() => {
    if (ordnerZustand.maskeOffen) ordnerstandPruefen()
  })

  /* A closed window is not asking anything any more. Whoever set out to say
     where a missing folder went and then closed this: the next path typed
     is a new share again, not an answer to a question nobody is looking at.
     The missing folder itself stays exactly where it stands. */
  $effect(() => {
    if (!ordnerZustand.maskeOffen) ordnerZustand.ersatzZiel = null
  })

  /* The outcome of the last "get the notes back" belongs to the run that
     made it — a closed window is not showing anything any more, and the
     next opening starts without a stale sentence from a folder the user is
     no longer looking at. */
  $effect(() => {
    if (!ordnerZustand.maskeOffen) ordnerZustand.zurueckMeldung = null
  })

  /* The same for the reason a path was refused: it belongs to the attempt
     that was made, not to the next opening. */
  $effect(() => {
    if (!ordnerZustand.maskeOffen) ordnerZustand.shareError = ''
  })

  function feldTaste(ereignis) {
    if (ereignis.key === 'Enter') {
      ereignis.preventDefault()
      ordnerHinzufuegen(pfadfeld.trim())
    }
  }
</script>

<Fenster bind:offen={ordnerZustand.maskeOffen} titel={t('arbeitsordner.waehlen')} art="frage">
  <p class="unter">{t('arbeitsordner.erklaerung')}</p>

  <!-- A shared folder that is no longer where it was shared from. It stays
       in the list until the user decides — removed quietly, nobody would
       know tomorrow what had once been shared. The button hangs on the
       FOLDER, not on the list: with two of them gone, two buttons are two
       answers, and nothing has to be guessed about which new place belongs
       to which old folder. The list here is only what is missing; the
       shared folders themselves are the pills in the header, and a second
       list of the same folders would be a second way to the same thing. -->
  {#if ordnerZustand.fehlend.length}
    <div class="fehlt">
      <p class="fehltsatz">{t('arbeitsordner.fehlt_satz')}</p>
      {#each ordnerZustand.fehlend as pfad (pfad)}
        <div class="zeile" class:gewaehlt={ordnerZustand.ersatzZiel === pfad}>
          <svg class="warnzeichen" width="15" height="15" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" stroke-width="2" stroke-linecap="round"
               stroke-linejoin="round" aria-hidden="true">
            <path d={WARNZEICHEN} />
          </svg>
          <span class="wo" title={displayPath(pfad)}>{displayPath(pfad)}</span>
          <button
            class="knopf"
            onclick={() => ersatzBeginnen(pfad)}
            aria-pressed={ordnerZustand.ersatzZiel === pfad}
            title={t('arbeitsordner.neu_waehlen_titel', { pfad: displayPath(pfad) })}
          >
            {t('arbeitsordner.neu_waehlen')}
          </button>
        </div>
      {/each}
    </div>
  {/if}

  <!-- The notes of a shared folder are gone and the program still has its
       copy. A fact, not a failure, so it carries no colour: nothing is
       broken, a file is missing and there is something to put back. The
       button hangs on the FOLDER for the same reason it does above — with
       two of them missing, one button per folder is two answers and nothing
       has to be guessed. Only the pair "copy kept, notes gone" is offered;
       notes that say something else are never replaced by an older copy,
       the service refuses that on its own (app/ordnerwissen.py). -->
  {#if ordnerZustand.notizverlust.length}
    <div class="notizen">
      <p class="notizsatz">{t('arbeitsordner.notizen_satz')}</p>
      {#each ordnerZustand.notizverlust as pfad (pfad)}
        <div class="zeile">
          <span class="wo" title={displayPath(pfad)}>{displayPath(pfad)}</span>
          <button
            class="knopf"
            onclick={() => notizenZurueckholen(pfad)}
            disabled={Boolean(ordnerZustand.holtZurueck)}
            title={t('arbeitsordner.notizen_zurueck_titel', { pfad: displayPath(pfad) })}
          >
            {t('arbeitsordner.notizen_zurueck')}
          </button>
        </div>
      {/each}
    </div>
  {/if}

  <!-- How the last "get the notes back" ended — shown right here, not as a
       toast: this window's own veil covers the toast stack
       (Fenster.svelte z-index 70 against Meldungen.svelte's 25), so a toast
       about it used to appear half hidden behind the window it belonged
       to. The folder itself may already be gone from the list above by the
       time this shows (a success removes it), so the sentence stands on
       its own rather than inside that loop. -->
  {#if ordnerZustand.zurueckMeldung}
    <p
      class="zurueckmeldung {ordnerZustand.zurueckMeldung.art}"
      role={ordnerZustand.zurueckMeldung.art === 'fehler' ? 'alert' : 'status'}
    >
      {ordnerZustand.zurueckMeldung.text}
    </p>
  {/if}

  {#if ordnerZustand.dialogDa}
    <button class="durchsuchen" onclick={systemdialog} disabled={ordnerZustand.laeuft}>
      <svg width="17" height="17" viewBox="0 0 64 64" fill="none" stroke="currentColor"
           stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M11 50 V14 H27 L32 21 H53 V50 Z" stroke-width="5" />
        <path d="M11 26 H53" stroke-width="4.5" />
      </svg>
      <span>
        {ordnerZustand.laeuft
          ? t('arbeitsordner.dialog_laeuft')
          : t('arbeitsordner.durchsuchen')}
      </span>
    </button>
    <div class="oder"><span>{t('arbeitsordner.oder')}</span></div>
  {/if}

  <input
    class="pfadfeld"
    bind:this={feld}
    bind:value={pfadfeld}
    onkeydown={feldTaste}
    placeholder={system === 'mac' ? t('arbeitsordner.pfad_platzhalter') : undefined}
    aria-label={t('arbeitsordner.oder')}
    spellcheck="false"
  />
  <p class="hilfe">
    {t(system === 'mac' ? 'arbeitsordner.pfad_hilfe' : 'arbeitsordner.pfad_hilfe_windows')}
  </p>

  {#if ordnerZustand.shareError}
    <p class="grund zurueckmeldung fehler" role="alert">{ordnerZustand.shareError}</p>
  {/if}

  <div class="knopfreihe">
    <button class="button" onclick={() => (ordnerZustand.maskeOffen = false)}>
      {t('app.abbrechen')}
    </button>
    <button class="button primary" disabled={!pfadfeld.trim()}
            onclick={() => ordnerHinzufuegen(pfadfeld.trim())}>
      {t('arbeitsordner.setzen')}
    </button>
  </div>
</Fenster>

<style>
  .unter {
    font-size: 12.5px;
    color: var(--text-still);
    margin: 0 0 14px;
    line-height: 1.5;
  }
  /* The quiet yellow form of the house: colour on text and line, never the
     full colour behind the words (stil/global.css). Caution, not failure —
     nothing is broken, the folder lies somewhere else. */
  .fehlt {
    border: 1px solid color-mix(in srgb, var(--gelb) 45%, var(--linie-stark));
    background: color-mix(in srgb, var(--gelb) 8%, var(--bg));
    border-radius: 9px;
    padding: 11px 12px;
    margin: 0 0 14px;
  }
  .fehltsatz {
    font-size: 12.5px;
    color: var(--gelb-text);
    margin: 0 0 9px;
    line-height: 1.45;
  }
  .fehlt .zeile {
    display: flex;
    align-items: center;
    gap: 9px;
    padding: 6px 0 0;
  }
  .fehlt .zeile + .zeile {
    border-top: 1px solid var(--linie);
    margin-top: 6px;
  }
  .fehlt .warnzeichen {
    flex: none;
    color: var(--gelb-text);
  }
  .fehlt .wo {
    flex: 1;
    min-width: 0;
    font-family: var(--schrift);
    font-size: 11.5px;
    color: var(--text-still);
    text-decoration: line-through;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  /* Which folder the window is currently asking about — the same ring the
     rest of the house uses for a chosen control, in this block's colour. */
  .fehlt .zeile.gewaehlt .knopf {
    border-color: color-mix(in srgb, var(--gelb) 60%, var(--linie-stark));
    color: var(--gelb-text);
  }
  .fehlt .knopf {
    flex: none;
    font-size: 12.5px;
    padding: 4px 11px;
  }
  /* The quiet form of a fact: the house's own lines and still text, no
     colour at all (stil/global.css). The block above this one is yellow
     because a folder that moved needs a decision; a copy that can be put
     back needs a click. */
  .notizen {
    border: 1px solid var(--linie-stark);
    border-radius: 9px;
    padding: 11px 12px;
    margin: 0 0 14px;
  }
  .notizsatz {
    font-size: 12.5px;
    color: var(--text-still);
    margin: 0 0 9px;
    line-height: 1.45;
  }
  .notizen .zeile {
    display: flex;
    align-items: center;
    gap: 9px;
    padding: 6px 0 0;
  }
  .notizen .zeile + .zeile {
    border-top: 1px solid var(--linie);
    margin-top: 6px;
  }
  .notizen .wo {
    flex: 1;
    min-width: 0;
    font-family: var(--schrift);
    font-size: 11.5px;
    color: var(--text-still);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .notizen .knopf {
    flex: none;
    font-size: 12.5px;
    padding: 4px 11px;
  }
  /* While one is being put back, no second one is started — and the button
     says so instead of quietly swallowing the click. */
  .notizen .knopf:disabled {
    opacity: 0.45;
    cursor: default;
  }
  .notizen .knopf:disabled:hover {
    background: none;
  }
  /* Colour carries the outcome, the house rule everywhere else in the
     program: green for the copy written back, still text for a fact that
     needed no write, red for the attempt itself failing. */
  .zurueckmeldung {
    font-size: 12.5px;
    line-height: 1.45;
    margin: 0 0 14px;
  }
  .zurueckmeldung.erfolg {
    color: var(--gruen-text);
  }
  .zurueckmeldung.hinweis {
    color: var(--text-still);
  }
  .zurueckmeldung.fehler {
    color: var(--rot-text);
  }
  /* Under the field it refers to, not above the folder list. */
  .zurueckmeldung.grund {
    margin: 10px 2px 0;
  }
  .durchsuchen {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 9px;
    width: 100%;
    border: 1px solid var(--linie-stark);
    border-radius: 9px;
    background: none;
    color: var(--text);
    font: inherit;
    font-size: 13.5px;
    padding: 10px 14px;
    cursor: pointer;
    transition: background 0.15s, border-color 0.15s;
  }
  .durchsuchen:hover {
    background: var(--linie);
    border-color: var(--text-still);
  }
  .durchsuchen:disabled {
    opacity: 0.55;
    cursor: default;
  }
  .durchsuchen svg {
    color: var(--text-leise);
    flex: none;
  }
  /* A hairline with the word in the middle — the two ways are equal, one is
     just more comfortable. */
  .oder {
    display: flex;
    align-items: center;
    gap: 10px;
    margin: 14px 0;
    color: var(--text-still);
    font-size: 11.5px;
  }
  .oder::before,
  .oder::after {
    content: '';
    flex: 1;
    height: 1px;
    background: var(--linie);
  }
  .pfadfeld {
    width: 100%;
    box-sizing: border-box;
    border: 1px solid var(--linie-stark);
    border-radius: 9px;
    background: var(--bg-seite, var(--bg));
    color: var(--text);
    font-family: var(--schrift);
    font-size: 13px;
    padding: 9px 11px;
    outline: none;
  }
  .pfadfeld:focus {
    border-color: var(--text-still);
  }
  .pfadfeld:disabled {
    opacity: 0.55;
    cursor: default;
  }
  .hilfe {
    font-size: 11.5px;
    color: var(--text-still);
    margin: 7px 2px 0;
  }
  .knopfreihe {
    display: flex;
    gap: 8px;
    justify-content: flex-end;
    margin-top: 18px;
  }
  .knopf {
    border: 1px solid var(--linie-stark);
    background: none;
    color: var(--text);
    font: inherit;
    font-size: 13px;
    padding: 7px 14px;
    border-radius: 9px;
    cursor: pointer;
  }
  .knopf:hover {
    background: var(--linie);
  }
</style>
