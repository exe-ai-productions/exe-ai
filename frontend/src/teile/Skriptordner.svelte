<script>
  /* Where the scripts a schedule may start live, and which ones are there.

     The last part of the schedules, under its own heading rather than a
     block hanging under the schedule form: "Active" should show the active
     schedules, not a folder.

     The row is the house row (Speicherortzeile): path, a button that opens
     the folder, and the three dots that MOVE it. Editing a script happens in
     the user's own editor after the folder is open — this window never
     becomes one. The row stays even with an empty folder: that is exactly
     when somebody needs to open it.

     Clicking a file fills the schedule form. The pick travels through
     lib/skriptwahl.svelte.js, the one thing the wall and the form share. */
  import { untrack } from 'svelte'
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

  /* A tile shows the first lines of its script, as the doc folder's tiles
     show a text file's: only so many bytes are asked for as a tile holds.
     The key names the file as it was last changed, so an edited script is
     read again and an unchanged one is not asked for twice. */
  const START_BYTES = 251
  let starts = $state({})
  const startKey = (datei) => `skript|${datei.name}|${datei.groesse}|${datei.geaendert}`
  async function loadStart(datei) {
    const key = startKey(datei)
    if (key in starts) return
    starts = { ...starts, [key]: '' }
    try {
      const text = await api.scriptStart(datei.name, START_BYTES)
      starts = { ...starts, [key]: text }
    } catch {
      /* A read that failed is forgotten, so the next listing asks again; the
         tile shows the page sign meanwhile, like an empty script. */
      const { [key]: _gone, ...rest } = starts
      starts = rest
    }
  }
  $effect(() => {
    for (const datei of skripte) untrack(() => loadStart(datei))
  })
  const showsText = (datei) => Boolean(starts[startKey(datei)])
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
    <div class="tilewall skriptwand">
      {#each skripte as datei, n (datei.name)}
        <div class="karte">
          <button
            class="kachel kachel-ein"
            class:nurzeichen={!showsText(datei)}
            class:gewaehlt={skriptwahl.name === datei.name}
            style:animation-delay="{Math.min(n, 8) * 0.05}s"
            onclick={() => skriptWaehlen(datei.name)}
            title={datei.name}
          >
            {#if showsText(datei)}
              <span class="blick">{starts[startKey(datei)]}</span>
            {:else}
              <Hauszeichen zeichen="dokument_zeilen" groesse={30} />
            {/if}
          </button>
          <span class="name" title={datei.name}>{datei.name}</span>
          {#if !datei.startbar}
            <span class="skripthinweis">{t('cronjobs.skripte_nicht_startbar')}</span>
          {/if}
        </div>
      {/each}
    </div>
  {/if}
</div>

<style>
  /* No line above it: the part's heading stands there. */
  .ordner {
    padding: 8px 0 12px;
  }
  /* The wall under the folder row: the square tiles of the doc folder
     (stil/tiles.css), the beginning of the script on each, its name under
     it. */
  .skriptwand {
    margin-top: 10px;
  }
  .karte {
    position: relative;
    display: flex;
    flex-direction: column;
    gap: 5px;
    min-width: 0;
  }
  .karte .kachel {
    position: relative;
    width: 100%;
    padding: 0;
    font: inherit;
    text-align: left;
    cursor: pointer;
  }
  /* A script whose beginning could not be read: the page sign alone, as
     large as a tile, with no tile behind it. */
  .skriptwand .kachel.nurzeichen {
    background: none;
    box-shadow: none;
    border-color: transparent;
  }
  .kachel.nurzeichen :global(svg) {
    width: 100%;
    height: 100%;
  }
  .kachel.nurzeichen :global(svg path) {
    vector-effect: non-scaling-stroke;
    stroke-width: calc(4.5px * 30 / 64);
  }
  .kachel.nurzeichen :global(svg path:first-child) {
    stroke-width: calc(5px * 30 / 64);
  }
  /* Which one is picked is a fact about this form, not a state of the
     program — a ring in the text colour, none of the four. */
  .skriptwand .kachel.gewaehlt {
    border-color: var(--text);
    box-shadow: inset 0 0 0 1px var(--text);
  }
  /* The first lines on a finer surface inside the tile, fading out at the
     bottom where the tile cuts them; a script is code, so the fixed face. */
  .blick {
    align-self: stretch;
    justify-self: stretch;
    margin: 8px;
    padding: 7px 8px;
    border-radius: 6px;
    overflow: hidden;
    background: color-mix(in srgb, var(--text) 6%, transparent);
    color: var(--text-leise);
    font: 8.5px/1.35 var(--schrift-fest);
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    -webkit-mask-image: linear-gradient(to bottom, #000 60%, transparent);
    mask-image: linear-gradient(to bottom, #000 60%, transparent);
  }
  /* The name in the fixed font, bright in 10 px on at most two lines,
     centred under its tile. */
  .name {
    padding: 0 2px;
    font-family: var(--schrift-fest);
    font-size: 10px;
    letter-spacing: -0.01em;
    overflow: hidden;
    text-align: center;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow-wrap: anywhere;
    line-height: 14px;
    color: var(--text);
  }
  /* A file that cannot run says so under its name, in red: the schedule
     would be refused on it, and a hand can change it in one click
     elsewhere. */
  .skripthinweis {
    text-align: center;
    font-size: 11px;
    color: var(--rot-text);
  }
</style>
