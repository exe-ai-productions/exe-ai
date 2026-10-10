<script>
  /* Where the scripts a schedule may start live, and which ones are there.

     The last part of the schedules, under its own heading rather than a
     block hanging under the schedule form: "Active" should show the active
     schedules, not a folder.

     The row is the house row (Speicherortzeile): path, a button that opens
     the folder, and the pencil that MOVES it. Editing a script happens in
     the user's own editor after the folder is open — this window never
     becomes one. The row stays even with an empty folder: that is exactly
     when somebody needs to open it.

     Clicking a file fills the schedule form. The pick travels through
     lib/skriptwahl.svelte.js, the one thing the wall and the form share. */
  import Speicherortzeile from './Speicherortzeile.svelte'
  import Hauszeichen from './Hauszeichen.svelte'
  import { api } from '../lib/api.js'
  import { t } from '../lib/texte.svelte.js'
  import { skriptwahl, skriptWaehlen } from '../lib/skriptwahl.svelte.js'

  let skripte = $state([])

  async function laden() {
    try {
      skripte = await api.skripteListe()
    } catch {
      /* An unreachable list leaves the field usable — the name can still be
         typed, exactly as it always could. */
      skripte = []
    }
  }

  $effect(() => {
    laden()
  })
</script>

<div class="ordner">
  <Speicherortzeile
    name="scripts"
    etikett={t('speicherorte.skripte_ordner')}
    onaendern={laden}
  />

  <!-- The folder shown as what is IN it, the way the pictures and the agents'
       shelf are (ModulBilder, ModulAgenten). The row alone said where the
       scripts live and never which ones exist, so the field had to be typed
       from memory and a typo became a schedule that fails at its first
       firing.

       A file without the executable bit is listed rather than hidden — it is
       in the folder, so it is on the wall — and says so, because that is the
       one thing that would refuse it at firing time (`geprueft`,
       app/skriptlauf.py). -->
  {#if skripte.length}
    <div class="skriptwand">
      {#each skripte as datei (datei.name)}
        <button
          class="skript"
          class:gewaehlt={skriptwahl.name === datei.name}
          onclick={() => skriptWaehlen(datei.name)}
          title={datei.name}
        >
          <Hauszeichen zeichen="dokument" groesse="klein" />
          <span class="skriptname">{datei.name}</span>
          {#if !datei.startbar}
            <span class="skripthinweis">{t('cronjobs.skripte_nicht_startbar')}</span>
          {/if}
        </button>
      {/each}
    </div>
  {/if}
</div>

<style>
  /* No line above it: the part's heading stands there. */
  .ordner {
    padding: 8px 0 12px;
  }
  /* The wall under the folder row. Tiles that grow with the rail, like the
     pictures' — a name is wider than a thumbnail, so these are rows of one
     line rather than squares. */
  .skriptwand {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-top: 8px;
  }
  /* A filled chip with the file sheet in front, like every button of the
     kit: the ground carries it, no frame. */
  .skript {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    max-width: 100%;
    padding: 5px 9px;
    font: inherit;
    font-size: 12px;
    color: var(--text-leise);
    background: var(--bg-hoch);
    border: none;
    border-radius: 9px;
    cursor: pointer;
  }
  /* The sheet takes the chip's own colour, so it brightens with the name. */
  .skript > :global(svg) {
    flex: none;
  }
  .skript:hover {
    color: var(--text);
    background: color-mix(in srgb, var(--text) 6%, var(--bg-hoch));
  }
  /* Which one is picked is a fact about this form, not a state of the
     program — brightness and a ring in the text colour, none of the four. */
  .skript.gewaehlt {
    color: var(--text);
    box-shadow: inset 0 0 0 1px var(--text);
  }
  .skriptname {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  /* A file that cannot run says so quietly. Not red: nothing has failed, it
     is a fact about the file that a hand can change in one click elsewhere. */
  .skripthinweis {
    flex: none;
    font-size: 11px;
    color: var(--text-still);
  }
</style>
