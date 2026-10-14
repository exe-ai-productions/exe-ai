<script>
  /* The chat's working folders, as one chip in the input bar's row.

     The chip names the first folder and how many more there are; a click
     opens the list above it. Each folder there can be opened in the file
     manager or let go, a folder that is no longer where it was shared from
     stands in yellow with the way to name its new place, the row below the
     list adds one, and the last row opens the chat's own folder — the one
     the program keeps for every chat. This is the only place the folders
     are shown and changed.

     A folder is a fact, so the chip answers with brightness; the one state
     it can be in — a folder gone missing — wears the waiting colour. */
  import Hauszeichen from './Hauszeichen.svelte'
  import {
    ordnerListe, ordnerName, ordnerZustand,
    ordnerLoesen, ordnerZeigen, maskeOeffnen, ersatzBeginnen,
  } from '../lib/arbeitsordner.svelte.js'
  import { t } from '../lib/texte.svelte.js'
  import { zustand } from '../lib/zustand.svelte.js'

  /* `open` and `onToggle` belong to the bar: it keeps one menu open at a
     time across all of its chips. `narrow` drops the words and keeps the
     sign with the count. */
  let { open = false, onToggle = () => {}, narrow = false } = $props()

  const folders = $derived(ordnerListe())
  const missing = $derived(new Set(ordnerZustand.fehlend))
  const anyMissing = $derived(folders.some((path) => missing.has(path)))
  /* The chat's own folder belongs to a chat: on the start page, with no
     chat open, its row stands greyed out instead of making a chat. */
  const noOwnFolder = $derived(!zustand.aktiverChat)

  function act(action) {
    onToggle(false)
    action()
  }
</script>

<div class="anchor" data-bar-menu="folder">
  <button
    class="chip"
    class:open
    class:warn={anyMissing}
    aria-expanded={open}
    aria-label={t('arbeitsordner.titel')}
    title={folders.length ? folders.join('\n') : t('arbeitsordner.titel')}
    onclick={() => onToggle(!open)}
  >
    <Hauszeichen zeichen="ordner" groesse={15} />
    {#if folders.length}
      {#if narrow}
        <span class="count">{folders.length}</span>
      {:else}
        <span class="name">{ordnerName(folders[0])}</span>
        {#if folders.length > 1}<span class="count">+{folders.length - 1}</span>{/if}
      {/if}
    {/if}
    {#if !narrow}<span class="chevron"><Hauszeichen zeichen="pfeil_unten" groesse={11} strich={2.6} /></span>{/if}
  </button>

  {#if open}
    <div class="menu" role="menu">
      {#each folders as path (path)}
        {#if missing.has(path)}
          <div class="row missing" title={path}>
            <Hauszeichen zeichen="ordner" groesse={16} />
            <span class="label">{ordnerName(path)}</span>
            <span class="tail">
              <button class="small" title={t('arbeitsordner.neu_waehlen_titel', { pfad: path })}
                      onclick={() => act(() => ersatzBeginnen(path))}>{t('arbeitsordner.neu_waehlen')}</button>
            </span>
          </div>
        {:else}
          <div class="row" title={path}>
            <Hauszeichen zeichen="ordner" groesse={16} />
            <span class="label">{ordnerName(path)}</span>
            <span class="tail">
              <button class="mini" aria-label={t('arbeitsordner.zeigen', { pfad: path })}
                      title={t('arbeitsordner.zeigen', { pfad: path })}
                      onclick={() => act(() => ordnerZeigen(path))}>
                <Hauszeichen zeichen="auskoppeln" groesse={13} />
              </button>
              <button class="mini" aria-label={t('arbeitsordner.loesen')} title={t('arbeitsordner.loesen')}
                      onclick={() => ordnerLoesen(path)}>
                <Hauszeichen zeichen="kreuz" groesse={11} />
              </button>
            </span>
          </div>
        {/if}
      {/each}
      {#if folders.length}<div class="divider" aria-hidden="true"></div>{/if}
      <button
        class="row add"
        role="menuitem"
        onclick={() => act(maskeOeffnen)}
      >
        <Hauszeichen zeichen="plus" groesse={14} />
        <span class="label">{t(folders.length ? 'arbeitsordner.hinzufuegen' : 'arbeitsordner.waehlen')}</span>
      </button>
      <button
        class="row own"
        role="menuitem"
        disabled={noOwnFolder}
        aria-label={t('arbeitsordner.eigener_oeffnen_titel')}
        onclick={() => act(() => ordnerZeigen())}
      >
        <Hauszeichen zeichen="ordner" groesse={14} />
        <span class="label">{t('arbeitsordner.eigener_oeffnen')}</span>
      </button>
    </div>
  {/if}
</div>

<style>
  .anchor { position: relative; flex: none; }

  /* The row's chip: no fill at rest, the field's fill under the pointer and
     while its list is open. */
  .chip {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    height: 30px;
    padding: 0 9px;
    border: none;
    border-radius: 9px;
    background: transparent;
    color: var(--text-leise);
    font: 400 12.5px var(--schrift);
    white-space: nowrap;
    cursor: pointer;
    transition: background 0.15s, color 0.15s;
  }
  .chip:hover, .chip.open { background: var(--bg-hoch); color: var(--text); }
  .name { max-width: 160px; overflow: hidden; text-overflow: ellipsis; }
  .count { color: var(--text-still); font-variant-numeric: tabular-nums; }
  .chip.warn, .chip.warn .count { color: var(--gelb-text); }
  .chevron { display: inline-flex; color: var(--text-still); transition: transform 0.2s; }
  .chip.open .chevron { transform: rotate(180deg); }

  /* Grows upward out of the chip, flush with its left edge. */
  .menu {
    position: absolute;
    bottom: calc(100% + 12px);
    left: 0;
    min-width: 240px;
    background: var(--bg-erhoben);
    border-radius: 9px;
    padding: 5px;
    box-shadow: 0 0 0 1px var(--linie), 0 16px 36px -8px rgba(0, 0, 0, 0.5);
    transform-origin: bottom left;
    animation: rise 0.16s cubic-bezier(0.2, 0.9, 0.3, 1) both;
    z-index: 30;
  }
  @keyframes rise { from { opacity: 0; transform: translateY(6px) scale(0.98); } }

  .row {
    display: flex;
    align-items: center;
    gap: 10px;
    width: 100%;
    min-height: 34px;
    padding: 5px 8px 5px 10px;
    border: none;
    border-radius: 9px;
    background: none;
    color: var(--text-leise);
    font: 400 13px var(--schrift);
    text-align: left;
  }
  .row:hover { background: var(--bg-hoch); color: var(--text); }
  .label { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .tail { margin-left: auto; display: inline-flex; gap: 2px; align-items: center; }
  .row.missing, .row.missing:hover { color: var(--gelb-text); }
  .row.missing .label { text-decoration: line-through; }
  .add, .own { cursor: pointer; }
  .own:disabled { opacity: 0.5; cursor: default; }
  .own:disabled:hover { background: none; color: var(--text-leise); }
  .divider { height: 1px; margin: 4px 6px; background: var(--linie); }

  .mini {
    width: 24px;
    height: 24px;
    display: grid;
    place-items: center;
    padding: 0;
    border: none;
    border-radius: 9px;
    background: none;
    color: var(--text-still);
    cursor: pointer;
  }
  .mini:hover { background: var(--bg-erhoben); color: var(--text); }
  .small {
    padding: 3px 8px;
    border: none;
    border-radius: 9px;
    background: var(--bg-hoch);
    box-shadow: inset 0 0 0 1px var(--feldstrich);
    color: var(--text);
    font: 400 12px var(--schrift);
    cursor: pointer;
  }
  .small:hover { background: color-mix(in srgb, var(--text) 8%, var(--bg-hoch)); }

  @media (prefers-reduced-motion: reduce) {
    .menu { animation: none; }
    .chevron { transition: none; }
  }
</style>
