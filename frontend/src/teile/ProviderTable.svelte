<script>
  /* The cloud providers as a table: provider, key, models, state and the bin
     that takes the provider away. Under the page head, above the card of the
     chosen provider.

     A row's click chooses it — its card stands beneath the table; the name is
     a button inside the row, so the keyboard reaches it and its click is the
     row's — and the bin, a control of its own, never chooses.

     The maker's logo stands bare in front of the name — no tile around it. A
     provider without a mark of its own (somebody's own server) wears the
     house's server sign in the same place.

     The words in the cells are made by the page (it owns the texts); this
     table only lays them out:
       { id, name, logo, keyText, keyState, keyTitle, modelsText, stateText,
         reachable, notResponding, reason }
     where `logo` is `{ vb, html }` or null and `keyState` is 'set', 'missing'
     or null (no key at all). */
  import { t } from '../lib/texte.svelte.js'
  import Leuchtpunkt from './Leuchtpunkt.svelte'
  import Hauszeichen from './Hauszeichen.svelte'

  let { rows = [], chosen = '', onchoose, onremove } = $props()
</script>

<section class="pick">
  <h3 class="tafelkopf">{t('modell.einrichten')}</h3>
  <div class="table">
    <div role="table" aria-label={t('modell.einrichten')}>
      <div class="row head" role="row">
        <span role="columnheader">{t('modell.column_provider')}</span>
        <span role="columnheader">{t('modell.schluessel')}</span>
        <span role="columnheader">{t('modell.feld_modell')}</span>
        <span role="columnheader">{t('modell.column_status')}</span>
        <span role="columnheader"></span>
      </div>
      {#each rows as r (r.id)}
        <!-- svelte-ignore a11y_click_events_have_key_events -->
        <div class="row line" class:chosen={r.id === chosen} role="row" tabindex="-1"
             onclick={() => onchoose?.(r.id)}>
          <span class="provider" role="cell">
            <span class="logo" aria-hidden="true">
              {#if r.logo}
                <svg viewBox={r.logo.vb} width="22" height="22">{@html r.logo.html}</svg>
              {:else}
                <Hauszeichen zeichen="server" groesse={20} />
              {/if}
            </span>
            <button class="name" aria-label={r.name}>
              <span class="text">{r.name}</span>
            </button>
          </span>
          <span class="cell key" class:missing={r.keyState === 'missing'} role="cell" title={r.keyTitle || null}>
            {#if r.keyState === 'set'}
              <Leuchtpunkt farbe="gruen" groesse={9} />
            {/if}
            <span class="text">{r.keyText}</span>
          </span>
          <span class="cell models" role="cell">{r.modelsText}</span>
          <span class="cell state" class:reachable={r.reachable} class:not-responding={r.notResponding} role="cell">
            {#if r.notResponding}
              <Leuchtpunkt farbe="still" groesse={7} />
            {/if}
            <span class="text">{r.stateText}</span>
          </span>
          <span class="cell bin" role="cell">
            <button
              class="binbutton"
              aria-label={t('modell.anbieter_entfernen')}
              title={t('modell.anbieter_entfernen')}
              onclick={(e) => { e.stopPropagation(); onremove?.(r.id) }}
              onkeydown={(e) => e.stopPropagation()}
            >
              <Hauszeichen zeichen="trash" groesse={16} />
            </button>
          </span>
          {#if r.reason}
            <!-- What the provider said about refusing: its sentence under the
                 whole row, as long as it is. -->
            <span class="reason" role="cell">{r.reason}</span>
          {/if}
        </div>
      {/each}
    </div>
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
  /* A card on the page: card glass with its fine line, as every card of the
     server windows. */
  .table {
    background: var(--glass-card);
    box-shadow: inset 0 0 0 1px var(--glass-card-line);
    border-radius: 9px;
    padding: 4px 0;
  }
  .row {
    display: grid;
    grid-template-columns: minmax(0, 2.2fr) minmax(0, 1.4fr) minmax(0, 0.8fr) minmax(0, 1.1fr) 34px;
    align-items: center;
    gap: 12px;
    padding: 0 16px;
  }
  .head {
    min-height: 40px;
    font-size: 11px;
    font-weight: 600;
    color: var(--text-leise);
  }
  .line {
    /* The row of the cells is 56 high at least; a sentence of the provider
       takes a second row under all of them. */
    grid-template-rows: minmax(55px, auto);
    min-height: 56px;
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
  .provider {
    display: flex;
    align-items: center;
    gap: 10px;
    min-width: 0;
  }
  /* The logo alone, no ground, no frame. */
  .logo {
    flex: none;
    width: 22px;
    height: 22px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    color: var(--text);
  }
  .name {
    flex: 1;
    min-width: 0;
    display: flex;
    align-items: center;
    padding: 0;
    border: none;
    background: none;
    color: var(--text);
    font: inherit;
    font-weight: 600;
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
    display: flex;
    align-items: center;
    gap: 8px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    color: var(--text-leise);
    font-variant-numeric: tabular-nums;
  }
  /* The number of chosen models is the one figure of the row that reads in
     the full ink. */
  .models { color: var(--text); }
  /* A missing key does not resolve by waiting: red, a word without a dot. The
     words wear the text forms of the colours (the base ones are for dots). */
  .key.missing { color: var(--rot-text); }
  /* A state is a word, not a pill: green while it answers, quiet when not. */
  .state.reachable { color: var(--gruen-text); }
  .bin { justify-content: center; overflow: visible; }
  /* What the provider said about refusing: its sentence, whole and
     wrapping, in the hint size and the quiet ink, under the row. */
  .reason {
    grid-column: 1 / -1;
    min-width: 0;
    padding: 0 0 12px;
    font-size: var(--schrift-hinweis);
    color: var(--text-leise);
    white-space: normal;
    overflow-wrap: anywhere;
    cursor: text;
  }
  .binbutton {
    flex: none;
    width: 34px;
    height: 34px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border: none;
    border-radius: 9px;
    /* A button of the page: button glass with its fine edge. */
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text-leise);
    cursor: pointer;
    transition: background 0.12s, color 0.12s;
  }
  .binbutton:hover { background: color-mix(in srgb, var(--text) 6%, var(--glass-button)); color: var(--text); }
  .binbutton:focus-visible { outline: 2px solid var(--linie-stark); outline-offset: -2px; }
</style>
