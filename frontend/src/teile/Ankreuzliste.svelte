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
  let {
    eintraege = [], istAn, istFest = () => false, onschalten, onalle,
    namensklasse = '',
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

<div class="suche">
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor"
       stroke-width="2.2" stroke-linecap="round">
    <circle cx="10.5" cy="10.5" r="7" /><path d="M16 16 L21 21" />
  </svg>
  <input bind:value={suche} placeholder={t('app.suchen')} aria-label={t('app.suchen')} />
</div>

<div class="listenkarte">
<div class="liste" use:rollfade>
  {#each gefiltert as eintrag (eintrag.id)}
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
  {:else}
    <p class="leer">{t('liste.nichts_gefunden')}</p>
  {/each}
</div>
</div>

<div class="fuss">
  <span>{t('liste.gewaehlt_zahl').replace('{zahl}', anzahlAn)}</span>
  <button class="textknopf" onclick={() => onalle(!alleAn)}>
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
