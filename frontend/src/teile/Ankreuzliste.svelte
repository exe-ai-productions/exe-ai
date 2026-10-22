<script>
  import { rollfade } from '../lib/rollfade.js'
  /* A catalogue to tick off: search field, one line per entry, a cross.

     Its own component because it is not the cloud window's business how a
     long list becomes usable. Nothing is filtered or sorted by name — a
     provider does not say which of its models are good for talking, and what
     we cannot judge we do not sort out. The search field is enough: typing
     `gpt` turns 124 lines into thirty. */
  import { t } from '../lib/texte.svelte.js'

  /* `istFest` marks entries that cannot be unticked — the configuration named
     them, and a cross that springs back would be a control that lies. */
  /* What the entries ARE, as a class on the name. This list ticks off two
     different things — the cloud window's models and the tools window's
     tools — and only one of them is a tool. A tool name looks the same
     wherever it stands (`.werkzeugname`, stil/global.css), a model name
     does not, and this component cannot know which it is holding. So the
     caller says. */
  /* The default look is the box on the left (the tools list). `tickEnd`
     draws the page's other look: no box, the tick at the end of the row, and
     the row's own action (`rowAction`, a snippet that gets the entry, shown on
     ticked rows only) before it. `isOpen` marks the row whose action is
     open. The row is then a row of its own and not a button: its action is a
     button, and a button does not stand in a button.

     In that look everything is a row of the card it stands in, edge to edge:
     the search row, one 57 px row per entry with a hairline under it, and
     the foot row with the count and the card's own button. */
  let {
    eintraege = [], istAn, istFest = () => false, onschalten, onalle,
    namensklasse = '', tickEnd = false, isOpen = () => false, rowAction = null,
  } = $props()

  let suche = $state('')

  const gefiltert = $derived(
    suche.trim()
      ? eintraege.filter((e) => e.name.toLowerCase().includes(suche.trim().toLowerCase()))
      : eintraege,
  )
  const anzahlAn = $derived(eintraege.filter(istAn).length)
  const alleAn = $derived(eintraege.length > 0 && anzahlAn === eintraege.length)
</script>

<div class="suchzeile" class:end-look={tickEnd}>
  <div class="suche">
    <svg width={tickEnd ? 15 : 13} height={tickEnd ? 15 : 13} viewBox="0 0 24 24" fill="none" stroke="currentColor"
         stroke-width="2.2" stroke-linecap="round">
      <circle cx="10.5" cy="10.5" r="7" /><path d="M16 16 L21 21" />
    </svg>
    <input bind:value={suche} aria-label={t('app.suchen')} />
  </div>
</div>

<div class="listenkarte" class:end-look={tickEnd}>
<div class="liste" use:rollfade>
  {#each gefiltert as eintrag (eintrag.id)}
    {#if tickEnd}
      <!-- svelte-ignore a11y_click_events_have_key_events -->
      <div
        class="zeile end"
        class:fest={istFest(eintrag)}
        class:open={isOpen(eintrag)}
        role="button"
        tabindex={istFest(eintrag) ? -1 : 0}
        aria-pressed={istAn(eintrag)}
        onclick={() => { if (!istFest(eintrag)) onschalten(eintrag, !istAn(eintrag)) }}
        onkeydown={(e) => {
          if (e.target === e.currentTarget && (e.key === 'Enter' || e.key === ' ') && !istFest(eintrag)) {
            e.preventDefault()
            onschalten(eintrag, !istAn(eintrag))
          }
        }}
      >
        <span class="name {namensklasse}">{eintrag.name}</span>
        {#if istFest(eintrag)}<span class="woher">{t('liste.aus_konfiguration')}</span>{/if}
        {#if istAn(eintrag)}
          {#if rowAction}
            <!-- svelte-ignore a11y_no_static_element_interactions -->
            <span class="action" onclick={(e) => e.stopPropagation()} onkeydown={(e) => e.stopPropagation()}>
              {@render rowAction(eintrag)}
            </span>
          {/if}
          <span class="end-tick" aria-hidden="true">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                 stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M4 12.5 L9.5 18 L20 6" />
            </svg>
          </span>
        {/if}
      </div>
    {:else}
      <button
        class="zeile"
        class:fest={istFest(eintrag)}
        disabled={istFest(eintrag)}
        onclick={() => onschalten(eintrag, !istAn(eintrag))}
      >
        <span class="kreuz" class:an={istAn(eintrag)}>
          {#if istAn(eintrag)}
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                 stroke-width="3.4" stroke-linecap="round" stroke-linejoin="round">
              <path d="M4 12.5 L9.5 18 L20 6" />
            </svg>
          {/if}
        </span>
        <span class="name {namensklasse}">{eintrag.name}</span>
        {#if istFest(eintrag)}<span class="woher">{t('liste.aus_konfiguration')}</span>{/if}
      </button>
    {/if}
  {:else}
    <p class="leer">{t('liste.nichts_gefunden')}</p>
  {/each}
</div>
</div>

<div class="fuss" class:end-look={tickEnd}>
  <span class="zahl">{t('liste.gewaehlt_zahl').replace('{zahl}', anzahlAn)}</span>
  <button class={tickEnd ? 'feldknopf' : 'textknopf'} onclick={() => onalle(!alleAn)}>
    {alleAn ? t('liste.alle_abwaehlen') : t('liste.alle_waehlen')}
  </button>
</div>

<style>
  .suche {
    display: flex;
    align-items: center;
    gap: 8px;
    border: none;
    /* 9 px — small control, see the radius palette. */
    border-radius: 9px;
    padding: 0 12px;
    color: var(--text-still);
    margin-bottom: 10px;
    height: 32px;
    background: var(--bg-hoch);
    box-shadow: inset 0 0 0 1px var(--feldstrich);
  }
  .suche input {
    flex: 1;
    min-width: 0;
    border: none;
    background: none;
    color: var(--text);
    font: inherit;
    font-size: 13px;
    outline: none;
  }

  /* No visible scrollbars anywhere. The card holds the ground and the
     corners; the list scrolls inside it, so the melt at a scrolling edge
     (rollfade) takes rows, never the card. */
  .listenkarte {
    background: var(--bg-erhoben);
    border-radius: 9px;
    padding: 2px 16px;
  }
  .liste {
    max-height: 252px;
    overflow-y: auto;
    scrollbar-width: none;
  }
  .liste::-webkit-scrollbar { display: none; }

  .zeile {
    display: flex;
    align-items: center;
    gap: 10px;
    width: 100%;
    text-align: left;
    border: none;
    border-bottom: 1px solid var(--linie);
    background: none;
    color: var(--text);
    font: inherit;
    font-size: 13px;
    padding: 9px 0;
    cursor: pointer;
  }
  .zeile:last-child { border-bottom: 0; }
  /* The row of the other look: a name at the left, the row's action and the
     tick at the right end; the row of the open one stands on a lighter
     ground. */
  .zeile.end {
    height: 57px;
    box-sizing: border-box;
    padding: 0 16px;
    gap: 14px;
    border-radius: 0;
    outline: none;
  }
  /* Every row keeps its hairline, the last one too: the foot row stands
     under it. */
  .zeile.end:last-child { border-bottom: 1px solid var(--linie); }
  .zeile.end:hover:not(.fest) { background: var(--glass-hover); }
  .zeile.end:focus-visible { box-shadow: inset 0 0 0 2px var(--linie-stark); }
  .zeile.end.open { background: var(--glass-button); }
  .zeile.end .name { flex: 1; min-width: 0; font-weight: 600; }
  .zeile.end .woher { margin-left: 0; }
  .action { flex: none; display: inline-flex; }
  .end-tick { flex: none; display: inline-flex; width: 22px; justify-content: center; color: var(--gruen); }

  /* The search as a row: the field stands in it, a hairline under it. */
  .suchzeile.end-look {
    box-sizing: border-box;
    height: 57px;
    padding: 0 16px;
    display: flex;
    align-items: center;
    border-bottom: 1px solid var(--linie);
  }
  .suchzeile.end-look .suche {
    flex: 1;
    margin-bottom: 0;
    background: var(--glass-button);
  }
  /* No second ground and no inset: the card holds both. */
  .listenkarte.end-look {
    background: none;
    padding: 0;
  }
  /* The message of an empty search stands in line with the rows. */
  .listenkarte.end-look .leer { padding: 18px 16px; }
  /* The foot as a row: the count of the chosen ones at the left, the card's
     own button at the right (`.feldknopf` is drawn by the card this list
     stands in, Serverabschnitt.svelte). */
  .fuss.end-look {
    box-sizing: border-box;
    height: 57px;
    margin-top: 0;
    padding: 0 16px;
    font-size: 13px;
  }
  .fuss.end-look .zahl { font-weight: 600; color: var(--text); }
  .zeile:hover:not(.fest) .kreuz:not(.an) { background: color-mix(in srgb, var(--text) 10%, var(--bg-hoch)); }
  .zeile.fest { cursor: default; }
  .woher { margin-left: auto; font-size: 12px; color: var(--text-still); }
  .name {
    font-family: var(--schrift);
    font-size: 13px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  /* A tool keeps the tool face here too; the rule above would outweigh the
     global one. */
  .name.werkzeugname {
    font-family: var(--schrift-fest);
    font-size: 12px;
  }
  .kreuz {
    width: 17px;
    height: 17px;
    border-radius: 9px;
    border: 1px solid transparent;
    flex: none;
    display: grid;
    place-items: center;
    color: var(--bg-erhoben);
    background: var(--bg-hoch);
  }
  .kreuz.an { background: var(--text); }

  .leer { color: var(--text-still); font-size: 12.5px; padding: 10px 4px; }

  .fuss {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-top: 10px;
    font-size: 12px;
    color: var(--text-still);
  }
  .textknopf {
    background: none;
    border: none;
    color: var(--text-leise);
    font: inherit;
    font-size: 12px;
    cursor: pointer;
    padding: 0;
  }
  .textknopf:hover { color: var(--text); }
</style>
