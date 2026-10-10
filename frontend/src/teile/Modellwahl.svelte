<script>
  /* The model picker in the input bar: the chosen model's name with its
     three lamps and the context ring, and a list that opens upward with a
     search field on top and the models under "Local" and "Cloud".

     The list is the server's answer, unchanged: `zustand.modelle` goes in
     raw, filtered only by what the user switched off in the model window.
     Nothing is hard-coded here and nothing gets renamed — what the model
     query doesn't provide isn't displayed. */
  import Hauszeichen from './Hauszeichen.svelte'
  import ContextRing from './ContextRing.svelte'
  import { zustand, modellWaehlen } from '../lib/zustand.svelte.js'
  import { sichtbare, modellwahl, auswahlLaden, chosenModelOff } from '../lib/modelle.svelte.js'
  import { serverzustand } from '../lib/serverzustand.svelte.js'
  import { t } from '../lib/texte.svelte.js'

  /* `open` and `onToggle` belong to the bar, which keeps one menu open at a
     time; `narrow` shortens the name when the window runs out of room, and
     `label` hands the bar the words shown, which it measures by. */
  let { open = false, onToggle = () => {}, narrow = false, label = $bindable('') } = $props()

  /* Filtered even before the selection has arrived: unfiltered means every
     model of every catalogue, and one provider alone reports 124. */
  $effect(() => {
    if (!modellwahl.geladen) auswahlLaden()
  })
  const offered = $derived(sichtbare())
  const chosen = $derived(offered.find((m) => m.id === zustand.modellId) ?? null)
  /* The chosen model missing from the list has two causes, and the empty
     text tells them apart: switched off in the model window reads "Model
     disabled", anything else keeps the broader "No model reachable". */
  const disabled = $derived(chosenModelOff())
  const emptyText = $derived(
    t(disabled ? 'fehler.modell_deaktiviert' : 'fehler.kein_modell_verfuegbar'),
  )

  /* The speed module is a fact about the local model server, so its lamp
     lights for the models that server runs and never for a cloud one. */
  const mtpRunning = $derived(serverzustand.mtp_aktiv === 'aktiv')
  function lamps(model) {
    return {
      tools: Boolean(model?.capabilities?.tool_calls),
      speed: mtpRunning && model?.group === 'local',
      vision: Boolean(model?.capabilities?.vision),
    }
  }
  const chosenLamps = $derived(lamps(chosen))
  $effect(() => {
    label = chosen?.name ?? emptyText
  })

  let query = $state('')
  let search = $state(null)
  $effect(() => {
    if (open) {
      query = ''
      queueMicrotask(() => search?.focus())
    }
  })
  const groups = $derived.by(() => {
    const needle = query.trim().toLowerCase()
    const hits = offered.filter((m) => !needle || String(m.name ?? m.id).toLowerCase().includes(needle))
    return [
      { key: 'local', title: t('menue.lokal'), models: hits.filter((m) => m.group === 'local') },
      { key: 'cloud', title: t('menue.cloud'), models: hits.filter((m) => m.group !== 'local') },
    ].filter((group) => group.models.length)
  })

  function pick(id) {
    onToggle(false)
    modellWaehlen(id)
  }
</script>

{#snippet lampRow(state)}
  <span class="lamps">
    <span class="lamp tools" class:on={state.tools} title={t(state.tools ? 'eingabe.werkzeug_an' : 'eingabe.werkzeug_aus')}>
      <Hauszeichen zeichen="werkzeug" groesse={13} />
    </span>
    <span class="lamp speed" class:on={state.speed} title={t(state.speed ? 'modell.mtp_aktiv' : 'eingabe.mtp_aus')}>
      <Hauszeichen zeichen="blitz" groesse={13} />
    </span>
    <span class="lamp vision" class:on={state.vision} title={t(state.vision ? 'eingabe.anhang_hinweis' : 'fehler.kein_vision')}>
      <Hauszeichen zeichen="auge" groesse={13} />
    </span>
  </span>
{/snippet}

<div class="anchor" data-bar-menu="model">
  <span class="group" class:open>
    <button class="part" class:narrow onclick={() => onToggle(!open)}
            title={chosen?.name ?? emptyText} aria-label={t('modell.titel')} aria-expanded={open}>
      <span class="name" class:empty={!chosen}>{chosen?.name ?? emptyText}</span>
      {@render lampRow(chosenLamps)}
    </button>
    <ContextRing />
    <button class="part tail" onclick={() => onToggle(!open)}
            aria-label={t('modell.titel')}>
      <span class="chevron"><Hauszeichen zeichen="pfeil_unten" groesse={11} strich={2.6} /></span>
    </button>
  </span>

  {#if open}
    <div class="menu" role="menu">
      <label class="search">
        <Hauszeichen zeichen="lupe" groesse={13} />
        <input bind:this={search} bind:value={query} aria-label={t('app.suchen')} />
      </label>
      {#each groups as group (group.key)}
        <div class="title tafelkopf">{group.title}</div>
        {#each group.models as model (model.id)}
          <button class="row" class:chosen={model.id === zustand.modellId} role="menuitem"
                  onclick={() => pick(model.id)}>
            <span class="check">{#if model.id === zustand.modellId}<Hauszeichen zeichen="haken" groesse={13} strich={2.6} />{/if}</span>
            <span class="label">{model.name ?? model.id}</span>
            <span class="tail-lamps">{@render lampRow(lamps(model))}</span>
          </button>
        {/each}
      {:else}
        <div class="nothing">{emptyText}</div>
      {/each}
    </div>
  {/if}
</div>

<style>
  .anchor { position: relative; flex: none; min-width: 0; }

  /* Name, lamps, ring and chevron are one control to the eye: they share
     one fill under the pointer. */
  .group {
    display: inline-flex;
    align-items: center;
    border-radius: 9px;
    transition: background 0.15s;
    max-width: 100%;
  }
  .group:hover, .group.open { background: var(--bg-hoch); }
  .part {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    height: 30px;
    padding: 0 4px 0 9px;
    border: none;
    border-radius: 9px;
    background: transparent;
    color: var(--text-leise);
    font: 400 12.5px var(--schrift);
    white-space: nowrap;
    cursor: pointer;
    min-width: 0;
  }
  .part.tail { padding: 0 8px 0 4px; }
  .name {
    max-width: 160px;
    overflow: hidden;
    text-overflow: ellipsis;
    color: var(--text);
  }
  .part.narrow .name { max-width: 58px; }
  .name.empty { color: var(--text-still); }
  .chevron { display: inline-flex; color: var(--text-still); transition: transform 0.2s; }
  .group.open .chevron { transform: rotate(180deg); }

  /* A lamp is a reading, never a button: lit it is the reading colour, the
     speed module's own lamp blue; unlit it steps far back. */
  .lamps { display: inline-flex; gap: 4px; align-items: center; }
  .lamp { display: inline-flex; color: var(--text-still); opacity: 0.3; transition: opacity 0.2s, color 0.2s; }
  .lamp.on { opacity: 1; color: var(--text-leise); }
  /* One capability, one colour, everywhere: wrench olive, bolt blue, eye
     violet (FAEHIGKEIT_FARBE, lib/modellempfehlungen.js). */
  .lamp.tools.on { color: var(--oliv); }
  .lamp.speed.on { color: var(--blau); }
  .lamp.vision.on { color: var(--violett); }

  /* Opens upward, flush with the picker's right edge. */
  .menu {
    position: absolute;
    bottom: calc(100% + 12px);
    right: 0;
    width: 280px;
    max-height: min(420px, 60vh);
    overflow-y: auto;
    scrollbar-width: none;
    background: var(--bg-erhoben);
    border-radius: 9px;
    padding: 5px;
    box-shadow: 0 0 0 1px var(--linie), 0 16px 36px -8px rgba(0, 0, 0, 0.5);
    transform-origin: bottom right;
    animation: rise 0.16s cubic-bezier(0.2, 0.9, 0.3, 1) both;
    z-index: 30;
  }
  .menu::-webkit-scrollbar { display: none; }
  @keyframes rise { from { opacity: 0; transform: translateY(6px) scale(0.98); } }
  .search {
    display: flex;
    align-items: center;
    gap: 8px;
    margin: 2px 2px 4px;
    padding: 6px 9px;
    border-radius: 9px;
    background: var(--bg-hoch);
    color: var(--text-still);
  }
  .search input {
    flex: 1;
    min-width: 0;
    border: none;
    background: transparent;
    outline: none;
    color: var(--text);
    font: 400 12.5px/18px var(--schrift);
  }
  /* The group's name wears the house heading, like every heading. */
  .title { padding: 8px 10px 3px; }
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
    cursor: pointer;
  }
  .row:hover { background: var(--bg-hoch); color: var(--text); }
  .row.chosen { color: var(--text); }
  .check { width: 14px; display: inline-flex; flex: none; color: var(--blau); }
  .label { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .tail-lamps { margin-left: auto; display: inline-flex; }
  .nothing { padding: 8px 10px; font-size: 12.5px; color: var(--text-still); }

  @media (prefers-reduced-motion: reduce) {
    .menu { animation: none; }
    .chevron, .lamp { transition: none; }
  }
</style>
