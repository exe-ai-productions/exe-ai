<script>
  /* The list of the settings, as it stands in the sidebar while the settings
     are open: the field to search them, then five groups of rows. A row is
     the same one every menu list builds (Menuezeile.svelte): a sign, the
     name, a short quiet value at the right and, where a state is worth one,
     a dot at the far end.

     The list knows the rows and what they show of the servers and the
     program; what the settings page itself shows (its values, its dots, the
     page that is open) and what a row does when it is picked come from the
     page that owns the list.

     The field filters the rows by their title; under them stand the single
     switches whose label holds the words, each as "Page › Switch" and leading
     to the switch itself. */
  import Menuezeile from './Menuezeile.svelte'
  import Hauszeichen from './Hauszeichen.svelte'
  import Fensterzeichen from './Fensterzeichen.svelte'
  import { t } from '../lib/texte.svelte.js'
  import { GRUPPEN, FELDER, zeile as zeileMitId } from '../lib/einstellungsliste.js'
  import { zeilenFiltern, schalterTreffer } from '../lib/einstellungssuche.js'
  import { serverstandHalten, serverPunkt } from '../lib/serverstand.svelte.js'
  import { updates } from '../lib/updates.svelte.js'
  import { updatesRowShow } from '../lib/updatesRow.js'

  /* `aktuell`: the id of the row whose page is open. `wert(id)` and
     `punkt(id)`: what the settings page shows at its own rows. `waehlen(zeile)`:
     what a pick does; `springen(feld)`: what a pick of a switch does. */
  let {
    aktuell = '', wert = () => '', punkt = () => null, waehlen = () => {}, springen = () => {},
  } = $props()

  let frage = $state('')

  /* The servers report while this list stands. */
  $effect(() => serverstandHalten())

  /* The program's version and the look for a newer one exist only where the
     shell tells them; a browser has neither, and the row stays away. */
  const mitUpdates = $derived(updates.present && Boolean(updates.version))

  function sichtbar(zeile) {
    return zeile.id !== 'updates' || mitUpdates
  }
  const gruppen = $derived(
    zeilenFiltern(
      GRUPPEN.map((g) => ({ ...g, zeilen: g.zeilen.filter(sichtbar) })),
      frage,
      t,
    ),
  )
  const treffer = $derived(schalterTreffer(FELDER, frage, t, zeileMitId))
  /* Escape empties the field, the way a search field is left. */
  function taste(e) {
    if (e.key === 'Escape' && frage) {
      e.stopPropagation()
      frage = ''
    }
  }
  function wertVon(zeile) {
    // The row of the updates shows its value in its own snippet below.
    if (zeile.id === 'updates') return ''
    return wert(zeile.id)
  }
  const updateAnzeige = $derived(updatesRowShow())
  function punktVon(zeile) {
    if (zeile.id.startsWith('server:')) return serverPunkt(zeile.id.slice(7))
    return punkt(zeile.id)
  }
</script>

<!-- The field stands where the chats' search stands: the first thing under
     the mark. -->
<div class="einstellungssuche">
  <Hauszeichen zeichen="lupe" groesse={15} />
  <input
    type="text"
    placeholder={t('einstellungen.suche')}
    aria-label={t('einstellungen.suche')}
    autocomplete="off"
    spellcheck="false"
    bind:value={frage}
    onkeydown={taste}
  />
</div>

{#snippet updatesRechts()}
  <!-- The running version at rest; after a click what came of the look and the
       word of the next step. Both stand level with the name of the row. -->
  <span class="update-ergebnis {updateAnzeige.art}">{updateAnzeige.text}</span>
  {#if updateAnzeige.tat}<span class="update-tat">{updateAnzeige.tat}</span>{/if}
{/snippet}

{#each gruppen as gruppe (gruppe.name)}
  <div class="menuegruppe gruppenkopf">{t(gruppe.titel)}</div>
  <div class="gruppenzeilen">
    {#each gruppe.zeilen as zeile (zeile.id)}
      <Menuezeile
        titel={t(zeile.titel)}
        wert={wertVon(zeile)}
        punkt={punktVon(zeile)}
        gewaehlt={aktuell === zeile.id}
        size="sidebar"
        rechts={zeile.id === 'updates' ? updatesRechts : undefined}
        onclick={() => waehlen(zeile)}
      >
        {#snippet zeichen()}
          {#if zeile.fenster}
            <Fensterzeichen name={zeile.fenster} groesse={20} />
          {:else}
            <Hauszeichen zeichen={zeile.zeichen} groesse={20} />
          {/if}
        {/snippet}
      </Menuezeile>
    {/each}
  </div>
{/each}

{#if frage.trim() && !gruppen.length && !treffer.length}
  <!-- The same quiet line the list of chats shows for a search without a hit. -->
  <div class="menuegruppe">{t('chat.keine_treffer')}</div>
{/if}

{#if treffer.length}
  <div class="gruppenzeilen schalter">
    {#each treffer as hit (hit.feld.zeile + hit.feld.titel)}
      <Menuezeile titel={hit.text} size="sidebar" onclick={() => springen(hit.feld)}>
        {#snippet zeichen()}
          {#if hit.zeile.fenster}
            <Fensterzeichen name={hit.zeile.fenster} groesse={20} />
          {:else}
            <Hauszeichen zeichen={hit.zeile.zeichen} groesse={20} />
          {/if}
        {/snippet}
      </Menuezeile>
    {/each}
  </div>
{/if}

<style>
  /* The search reads as a quiet field with a fine edge: a ground only under
     the hand or while typing is the chats' way; here the field is drawn at
     rest, as the list's first row. */
  .einstellungssuche {
    display: flex;
    align-items: center;
    gap: 8px;
    height: 32px;
    box-sizing: border-box;
    margin: 0;
    padding: 0 8px 0 10px;
    border-radius: 9px;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--feldstrich);
    color: var(--rahmen-text, var(--text-still));
  }
  .einstellungssuche:focus-within {
    color: var(--text);
  }
  .einstellungssuche input {
    flex: 1;
    min-width: 0;
    border: none;
    background: none;
    outline: none;
    color: var(--rahmen-text, var(--text));
    font: inherit;
    font-size: 13px;
  }
  /* The heading of a group in this list: small and semibold, indented 10 px,
     with the room of the drawing between the groups and under the search. */
  .gruppenkopf {
    margin: 14px 10px 6px;
    font: 600 11px/1.4 var(--schrift);
  }
  .einstellungssuche + .gruppenkopf {
    margin-top: 18px;
  }
  .gruppenzeilen {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  /* The right end of the row "Updates": the value in the size and ink of the
     other values, a state in the colour of its kind, the next step in full
     ink. The value takes the room the name leaves and breaks over two lines
     rather than being cut, since a failure names its reason. */
  .update-ergebnis {
    flex: 0 1 auto;
    min-width: 0;
    margin-left: auto;
    font-size: 11px;
    font-weight: 400;
    line-height: 1.3;
    text-align: right;
    overflow-wrap: anywhere;
    color: var(--rahmen-text, var(--text-still));
  }
  .update-ergebnis.running { color: var(--blau-text); }
  .update-ergebnis.failed { color: var(--rot-text); }
  .update-ergebnis.done { color: var(--gruen-text); }
  .update-tat {
    flex: none;
    font-size: 11px;
    font-weight: 600;
    color: var(--text);
  }
  /* The switches found stand below the rows, set off by a little room. */
  .gruppenzeilen.schalter {
    margin-top: 12px;
  }
</style>
