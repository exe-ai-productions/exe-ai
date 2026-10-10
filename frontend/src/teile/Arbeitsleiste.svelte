<script>
  /* The column right of the chat, built like the sidebar on the left: no
     ground of its own on the frame, a head with the tool's sign, its name
     and the button that folds it, a hairline, the tool, and the row of
     signs at the foot (ToolSigns.svelte). One tool shows at a time; a sign in the row swaps
     it. Folded, it is a bar of signs as wide as the left one, with the
     same heights.

     Head says which tool and, where there is one worth knowing from
     outside, one detail about it — how many runs.

     The column is one component and the tools are files beside it; adding
     one is a sign in the row and a file of its own, not a rebuild. */
  import Modulzeichen from './Modulzeichen.svelte'
  import ModulBilder from './ModulBilder.svelte'
  import DocFolder from './DocFolder.svelte'
  import ModulAgenten from './ModulAgenten.svelte'
  import ModulCronjobs from './ModulCronjobs.svelte'
  import Agentenmarke from './Agentenmarke.svelte'
  import ModulTerminal from './ModulTerminal.svelte'
  import ModulVorschau from './ModulVorschau.svelte'
  import Vektorfeld from './Vektorfeld.svelte'
  import ToolSigns from './ToolSigns.svelte'
  import StudioDetails from './StudioDetails.svelte'
  import Fensterzeichen from './Fensterzeichen.svelte'
  import { studio, studioSichtbar } from '../lib/studio.svelte.js'
  import { untrack } from 'svelte'
  import {
    leiste, oeffnen, schliessen,
  } from '../lib/arbeitsleiste.svelte.js'
  import { t } from '../lib/texte.svelte.js'
  import { terminal } from '../lib/terminalfenster.svelte.js'
  import { eineSeiteOffen } from '../lib/zustand.svelte.js'
  import { flaeche } from '../lib/flaeche.svelte.js'

  /* Whether this surface carries its drawing; the window decides, the
     surface knows which drawing belongs to it. */
  let { vektoren = false } = $props()

  /* The one line of detail in the head. Each module answers for itself what
     is worth knowing about it from outside. The preview has none: the name
     of its file stands on its tab and in its address line, and a third time
     up here it only repeated itself. */
  const detail = $derived.by(() => {
    if (leiste.modul === 'terminal') {
      const anzahl = terminal.laeufe.length
      return anzahl ? t('terminal.laeufe', { n: anzahl }) : ''
    }
    return ''
  })

  const MODULE = [
    ['terminal', 'terminal.titel'],
    ['vorschau', 'vorschau.titel'],
    ['bilder', 'bilder.titel'],
    ['docfolder', 'docfolder.title'],
    ['agenten', 'agenten.titel'],
    ['cronjobs', 'cronjobs.titel'],
  ]

  function titelVon(name) {
    return t(MODULE.find(([modul]) => modul === name)?.[1] ?? 'terminal.titel')
  }
  const titel = $derived(titelVon(leiste.modul))

  /* While the picture studio is open the column shows its details under a
     head of their own; the row of tool signs at the foot stays. A tool the
     user asks for there takes the details' place, unchanged, and the head
     then switches between the details and that tool. */
  const studioAn = $derived(studioSichtbar())
  const feinheitenAn = $derived(studioAn && studio.rechts === 'feinheiten')
  let gewaehltGesehen = leiste.gewaehlt
  $effect(() => {
    const gewaehlt = leiste.gewaehlt
    untrack(() => {
      if (gewaehlt !== gewaehltGesehen && studioSichtbar()) studio.rechts = 'werkzeug'
      gewaehltGesehen = gewaehlt
    })
  })
</script>

{#snippet zeichenVon(name, groesse)}
  {#if name === 'agenten'}
    <!-- The agent mark the job cards already wear — the same figure says
         "agent" wherever agents appear. -->
    <Agentenmarke groesse={groesse + 1} />
  {:else}
    <Modulzeichen modul={name} {groesse} />
  {/if}
{/snippet}

{#if leiste.offen}
  <aside class="leiste" class:unterseite={eineSeiteOffen()} class:eng={flaeche.eng}
         style:--leiste-breite={leiste.breite + 'px'}>
    <!-- The surface's drawing, its first layer: the tool stands on top. -->
    {#if vektoren}
      <Vektorfeld art={vektoren} />
    {/if}
    <div class="kopf">
      {#if feinheitenAn}
        <span class="kopfzeichen"><Fensterzeichen name="feinheiten" groesse={24} /></span>
        <span class="modulname">{t('studio.feinheiten')}</span>
        <span class="detail"></span>
      {:else if studioAn}
        <div class="umschalter" role="group" aria-label={t('studio.titel')}>
          <button aria-pressed="false" onclick={() => (studio.rechts = 'feinheiten')}>{t('studio.feinheiten')}</button>
          <button class="an" aria-pressed="true">{titel}</button>
        </div>
        <span class="detail"></span>
      {:else}
        <span class="kopfzeichen">{@render zeichenVon(leiste.modul, 24)}</span>
        <span class="modulname">{titel}</span>
        <span class="detail">{detail}</span>
      {/if}
      <!-- Folds the column to its bar of signs: the sidebar's own button,
           mirrored, as the column is. -->
      <button
        class="zk gespiegelt"
        onclick={schliessen}
        title={t('seitenleiste.ausblenden')}
        aria-label={t('seitenleiste.ausblenden')}
      >
        {@render leistenzeichen()}
      </button>
    </div>
    <!-- A hairline under the head, clear of both edges, as on the left. -->
    <div class="kopfstrich" aria-hidden="true"></div>

    <div class="inhalt" class:ganz={!feinheitenAn && leiste.modul === 'vorschau'}>
      {#if feinheitenAn}
        <StudioDetails />
      {:else if leiste.modul === 'terminal'}
        <ModulTerminal />
      {:else if leiste.modul === 'vorschau'}
        <ModulVorschau />
      {:else if leiste.modul === 'bilder'}
        <ModulBilder />
      {:else if leiste.modul === 'docfolder'}
        <DocFolder />
      {:else if leiste.modul === 'agenten'}
        <ModulAgenten />
      {:else if leiste.modul === 'cronjobs'}
        <ModulCronjobs />
      {/if}
    </div>

    <!-- The tools, one row at the foot, like the sidebar's windows. -->
    <div class="fusszeile">
      <ToolSigns />
    </div>
  </aside>
{:else}
  <!-- Folded: a bar of signs as wide as the sidebar's, the way back in and
       three tools at the top, the other three at the foot. -->
  <nav class="zeichenleiste">
    <button
      class="zk gespiegelt"
      onclick={oeffnen}
      title={t('seitenleiste.einblenden')}
      aria-label={t('seitenleiste.einblenden')}
    >
      {@render leistenzeichen()}
    </button>
    <ToolSigns gapBefore={3} />
  </nav>
{/if}

{#snippet leistenzeichen()}
  <!-- The sidebar sign of the house catalogue, the one the left column's
       button wears; mirrored by the button, the column is on the right. -->
  <svg width="24" height="24" viewBox="0 0 64 64" fill="none" stroke="currentColor"
       stroke-width="5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    <rect x="9" y="13" width="46" height="38" rx="8" />
    <path d="M25 13 V51" />
  </svg>
{/snippet}

<style>
  .leiste {
    /* A custom property, not a raw `width`: the narrow-screen rule below
       sets `width` directly and needs to outrank this without `!important`
       — the same reasoning as the sidebar's own fix (Seitenleiste.svelte). */
    width: var(--leiste-breite);
    flex: none;
    position: relative;
    display: flex;
    flex-direction: column;
    min-height: 0;
    /* It lies on the frame itself, without a ground of its own, like the
       sidebar on the left; the air before the chat's surface is the seam. */
    /* A stacking context for the drawing's own level (the rule below). */
    isolation: isolate;
    /* The side margin of the views: roomy by default, tighter at the
       narrowest width. */
    --rand: 16px;
  }
  /* The tool's content is not layered, so this surface lifts the drawing
     behind it: one step down, inside its own stacking context, the
     drawing lands between the ground and the tool. */
  .leiste :global(.vektorfeld) {
    z-index: -1;
  }
  /* At the narrowest width the surface can be dragged to (lib/flaeche.svelte.js);
     one pixel wider, the roomy ones stand. */
  .leiste.eng {
    --rand: 12px;
  }

  /* The folded column: a bar of signs, as wide as the sidebar's and built
     the same way, so the buttons of both stand at the same heights. */
  .zeichenleiste {
    flex: none;
    width: 52px;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
    padding: 12px 0;
  }
  /* The house's sign button, as on the left: a square, no frame, a ground
     only under the hand. */
  .zk {
    width: 40px;
    height: 40px;
    flex: none;
    display: grid;
    place-items: center;
    padding: 0;
    border: none;
    border-radius: 9px;
    background: none;
    color: var(--rahmen-text, var(--text-still));
    cursor: pointer;
    transition: background 0.12s, color 0.12s;
  }
  .zk:hover { background: var(--glass-hover); color: var(--text-leise); }
  /* The column stands on the right: its sign faces the other way. */
  .gespiegelt :global(svg) { transform: scaleX(-1); }

  /* The head: the tool's sign and name, the folding button — the same
     height and padding as the sidebar's head with the mark. */
  .kopf {
    flex: none;
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 14px 12px 12px 18px;
    font-size: 16px;
    color: var(--rahmen-text, var(--text-leise));
  }
  .kopfstrich {
    flex: none;
    margin: 0 18px 14px;
    border-top: 1px solid color-mix(in srgb, var(--rahmen-text, var(--text)) 16%, transparent);
  }
  /* The head buttons: the house's sign button, no frame. */
  .kopfzeichen {
    flex: none;
    display: grid;
    place-items: center;
    color: var(--text-leise);
  }
  /* The head's switch in the studio: the details or the tool, two halves
     of one glass track, as the studio's own "Picture | Video". */
  .umschalter {
    display: flex;
    gap: 2px;
    padding: 3px;
    border-radius: 9px;
    background: var(--glass-card);
    box-shadow: inset 0 0 0 1px var(--glass-card-line);
  }
  .umschalter button {
    min-width: 112px;
    height: 28px;
    padding: 0 12px;
    border: none;
    border-radius: 9px;
    background: none;
    color: var(--text-leise);
    font: 400 13px/18px var(--schrift);
    cursor: pointer;
  }
  .umschalter button:hover {
    color: var(--text);
  }
  .umschalter button.an {
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text);
    cursor: default;
  }
  .modulname {
    font-weight: 600;
    color: var(--rahmen-text, var(--text));
    white-space: nowrap;
  }
  /* Takes the free room of the head, so the fold button stands at its end. */
  .detail {
    flex: 1;
    min-width: 0;
    font-size: 13px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--text-still);
  }

  /* The tool, melting out over its last 40 px into the row below — except
     the preview, which reaches down to the row. */
  .inhalt {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    -webkit-mask-image: linear-gradient(to bottom, #000 calc(100% - 40px), transparent);
    mask-image: linear-gradient(to bottom, #000 calc(100% - 40px), transparent);
  }
  .inhalt.ganz {
    -webkit-mask-image: none;
    mask-image: none;
  }
  /* The row of signs at the foot, as the sidebar's windows row. */
  .fusszeile {
    flex: none;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    padding: 4px 12px 12px;
  }

  /* On a narrow screen the chat needs its whole width — so the open
     column is a sheet OVER the chat here instead of a column beside it,
     the whole window, with its own head and row to fold it and to switch
     tools; folded, the bar of signs stands as on a wide one. This query
     only has to reach what the desktop layout gets wrong for a sheet: the
     full window instead of the remembered width, and a ground — the
     frame's gradient, as the sidebar's drawer wears. The seam's handle
     (Seitengriff.svelte) hides itself here. */
  @media (width < 760px) {
    .leiste {
      position: fixed;
      inset: 0;
      z-index: 45;
      width: 100%;
      background: var(--frame);
    }
    /* A menu page (Seitenrahmen.svelte, 20) lies over the sheet while it is
       open: the sheet slips just under it and stays mounted and open, so
       closing the page shows the tool again exactly as it was. The drawer
       (40) stays above both. */
    .leiste.unterseite {
      z-index: 19;
    }
  }
</style>
