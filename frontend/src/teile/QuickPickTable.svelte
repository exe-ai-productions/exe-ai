<script>
  /* The quick picker of the local models as a table: model, server,
     context, framework and the switch that puts the model into the chat's
     choice. Under the servers of the page, above whatever is chosen.

     A row's click chooses it — its parameters open beneath the table; the
     name is a button inside the row, so the keyboard reaches it and its
     click is the row's — and the switch, a control of its own, never
     chooses. A row without a switch
     (`switchable` false) is the agent server's own file: nothing in the chat
     would be switched by it, but its parameters are reachable here.

     The maker's logo stands bare in front of the name — no tile around it.
     A model of a family the house has no original vector for gets its first
     letter in the same place: a mark is never guessed. */
  import { t, texte } from '../lib/texte.svelte.js'
  import { kurz } from '../lib/tokenzahl.js'
  import { modellMarke } from '../lib/anbieterzeichen.js'
  import Leuchtpunkt from './Leuchtpunkt.svelte'
  import MakerMark from './MakerMark.svelte'
  import Schalter from './Schalter.svelte'

  /* One row: { id, name, maker, server, context, framework, reachable,
     switchable, on }. */
  let { rows = [], chosen = '', emptyText = '', onchoose, onswitch } = $props()
</script>

<section class="pick">
  <h3 class="tafelkopf">{t('modell.schnellwahl_titel')}</h3>
  <div class="table">
    <div role="table" aria-label={t('modell.schnellwahl_titel')}>
    <div class="row head" role="row">
      <span role="columnheader">{t('modell.spalte_modell')}</span>
      <span role="columnheader">{t('modell.spalte_server')}</span>
      <span role="columnheader">{t('modell.kontext')}</span>
      <span role="columnheader">{t('modell.spalte_framework')}</span>
      <span role="columnheader" class="center">{t('modell.schnellwahl_titel')}</span>
    </div>
    {#each rows as r (r.id)}
      {@const mark = modellMarke(r.name, r.maker)}
      <!-- svelte-ignore a11y_click_events_have_key_events -->
      <div class="row line" class:chosen={r.id === chosen} role="row" tabindex="-1"
           onclick={() => onchoose?.(r.id)}>
        <span class="model" role="cell">
          <MakerMark {mark} name={r.name} />
          <button class="name" aria-label={r.name}>
            <Leuchtpunkt farbe={r.reachable ? 'gruen' : 'still'} groesse={9} />
            <span class="text">{r.name}</span>
          </button>
        </span>
        <span class="cell" role="cell">{r.server}</span>
        <span class="cell" role="cell">{kurz(r.context, texte.sprache) ?? '-'}</span>
        <span class="cell" role="cell">{r.framework}</span>
        <span class="cell center" role="cell">
          {#if r.switchable}
            <!-- svelte-ignore a11y_no_static_element_interactions -->
            <span class="switch" onclick={(e) => e.stopPropagation()}>
              <Schalter an={r.on} beschriftung={r.name} onschalten={(an) => onswitch?.(r.id, an)} />
            </span>
          {/if}
        </span>
      </div>
    {/each}
    </div>
    {#if !rows.length}
      <!-- A single dash while nothing is loaded: the heading already says
           what this place is for, and the reason is the dash's title. -->
      <p class="empty" title={emptyText}>-</p>
    {/if}
  </div>
</section>

<style>
  .pick {
    display: flex;
    flex-direction: column;
    gap: 10px;
    margin-bottom: 28px;
  }
  .tafelkopf {
    margin: 0;
  }
  /* A card on the page: card glass with its fine line, as every card of
     the server windows. */
  .table {
    background: var(--glass-card);
    box-shadow: inset 0 0 0 1px var(--glass-card-line);
    border-radius: 9px;
    padding: 4px 0;
  }
  .row {
    display: grid;
    grid-template-columns: minmax(0, 2.6fr) minmax(0, 1.3fr) minmax(0, 0.8fr) minmax(0, 1fr) minmax(0, 0.9fr);
    align-items: center;
    gap: 12px;
    padding: 0 16px;
  }
  .head {
    min-height: 34px;
    font-size: 11.5px;
    color: var(--text-still);
  }
  .line {
    min-height: 48px;
    border-top: 1px solid var(--linie);
    font-size: 13px;
    cursor: pointer;
    transition: background 0.12s;
  }
  .line:hover {
    background: var(--glass-hover);
  }
  .line.chosen {
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
  }
  .center {
    text-align: center;
    justify-self: center;
  }
  .model {
    display: flex;
    align-items: center;
    gap: 10px;
    min-width: 0;
  }
  .name {
    flex: 1;
    min-width: 0;
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 0;
    border: none;
    background: none;
    color: var(--text);
    font: inherit;
    text-align: left;
    cursor: pointer;
  }
  .text {
    min-width: 0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .cell {
    min-width: 0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    color: var(--text-leise);
    font-variant-numeric: tabular-nums;
  }
  .switch {
    display: inline-flex;
  }
  .empty {
    margin: 0;
    padding: 12px 16px;
    font-size: 12px;
    color: var(--text-still);
    border-top: 1px solid var(--linie);
  }
</style>
