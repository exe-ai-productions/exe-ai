<script>
  /* The thinking switch, left of the microphone: the bulb and one dot for
     every stage that thinks, in the text colour as far as the chosen stage reaches. No
     word in the bar — the dots say how much, and the list says which.

     What it offers is what the service reports for the chosen model
     (`denkprofil`, app/denkstufen.py) and nothing else, so it takes one of
     three shapes:

       stufen     a click opens the list of stages
       schalter   a click turns thinking on or off
       immer/nie  the bulb stands still beside its word; nothing to click,
                  because a control that opens onto nothing lies about what
                  it can do. In the narrow form of the bar the word steps
                  aside and the bulb stands alone: the word stays in the
                  tooltip and for a screen reader.

     The stage belongs to the model and is stored by the caller
     (`denkenSetzen`, Eingabeleiste.svelte); this component only draws it and
     reports a new one.

     The list hangs off nothing (`position: fixed`, placed from the button's
     own rectangle): the bar clips its overflow so the field's rounded
     corners stay clean, and a list inside it would be cut off at its edge. */
  import { t } from '../lib/texte.svelte.js'

  /* `denken` is the stage in force, as the caller works it out — the same
     value the request carries (Eingabeleiste.svelte, `denkStufe`). */
  let { denkprofil = null, denken = null, denkenSetzen = () => {}, narrow = false } = $props()

  const art = $derived(denkprofil?.art ?? 'nie')
  const stufen = $derived(denkprofil?.stufen ?? [])
  /* "Off" is the one stage that does not think, so it has no dot of its
     own: the dots count the stages that do, and a model without "off" in
     its list (one that always thinks a little) lights its first dot at its
     lowest stage. */
  const denkende = $derived(stufen.filter((s) => s !== 'off'))
  const rang = (stufe) => denkende.indexOf(stufe) + 1
  const an = $derived(art === 'immer' || (art !== 'nie' && Boolean(denken) && denken !== 'off'))
  const roh = $derived(denkprofil?.nativ ?? {})

  let offen = $state(false)
  let knopf = $state(null)
  let liste = $state(null)
  let ort = $state({ rechts: 0, unten: 0, hoch: 0 })

  /* Right-aligned to the button, and kept inside the window on the left as
     well: the list's own width is only known once it hangs in the tree, so
     the first call estimates with the minimum and the call right after
     opening corrects against the real width. */
  function ortBerechnen() {
    if (!knopf) return
    const r = knopf.getBoundingClientRect()
    const breite = liste?.offsetWidth ?? 190
    ort = {
      rechts: Math.max(16, Math.min(window.innerWidth - r.right, window.innerWidth - breite - 16)),
      unten: window.innerHeight - r.top + 6,
      // As high as the room above the button allows; the rest scrolls.
      hoch: Math.max(0, r.top - 22),
    }
  }

  function klick() {
    if (art === 'schalter') {
      /* The other of the two. A model whose list holds only one of them
         has nothing to switch to, and the click does nothing. */
      const andere = stufen.find((s) => s !== denken)
      if (andere) denkenSetzen(andere)
      return
    }
    if (offen) {
      offen = false
      return
    }
    oeffnen()
  }

  function oeffnen() {
    ortBerechnen()
    offen = true
    /* The chosen entry takes the focus, so the arrow keys start from it. */
    queueMicrotask(() => {
      ortBerechnen()
      liste?.querySelector('[aria-checked="true"]')?.focus()
    })
  }

  function waehlen(stufe) {
    offen = false
    knopf?.focus()
    denkenSetzen(stufe)
  }

  /* The keys a menu is expected to know: the arrows walk it, Escape leaves
     without changing anything. Enter and Space are the buttons' own. */
  function taste(ereignis) {
    if (ereignis.key === 'Escape') {
      /* Only the list's own Escape is taken here. Let through, it reaches
         the window's shortcut, which stops a running answer or throws away
         a recording — not what closing a menu means. */
      if (!offen) return
      ereignis.stopPropagation()
      ereignis.preventDefault()
      offen = false
      knopf?.focus()
      return
    }
    if (ereignis.key !== 'ArrowDown' && ereignis.key !== 'ArrowUp') return
    /* On the closed button an arrow opens the list, as a menu button does.
       A button with no list leaves the key alone. */
    if (!offen) {
      if (art !== 'stufen') return
      ereignis.preventDefault()
      oeffnen()
      return
    }
    ereignis.preventDefault()
    const eintraege = [...(liste?.querySelectorAll('.eintrag') ?? [])]
    const stelle = eintraege.indexOf(document.activeElement)
    const schritt = ereignis.key === 'ArrowDown' ? 1 : -1
    eintraege[Math.min(eintraege.length - 1, Math.max(0, stelle + schritt))]?.focus()
  }

  /* Tabbing out of the list to anything outside it and its button closes
     it. Only a named target counts: a pointer press on an entry can take
     the focus away with no target at all (WebKit does not focus a pressed
     button), and closing then would pull the entry away before its click
     arrives. Clicks elsewhere are `daneben`'s. */
  function fokusWeg(ereignis) {
    const ziel = ereignis.relatedTarget
    if (!ziel || liste?.contains(ziel) || knopf?.contains(ziel)) return
    offen = false
  }

  /* A press anywhere else closes the list; scrolling or resizing moves the
     button under it, so the place is worked out again while it is open. */
  function daneben(ereignis) {
    if (!offen) return
    if (knopf?.contains(ereignis.target) || liste?.contains(ereignis.target)) return
    offen = false
  }
  $effect(() => {
    if (!offen) return
    window.addEventListener('scroll', ortBerechnen, true)
    window.addEventListener('resize', ortBerechnen)
    return () => {
      window.removeEventListener('scroll', ortBerechnen, true)
      window.removeEventListener('resize', ortBerechnen)
    }
  })
  /* A model switch can take the list away underneath an open menu. */
  $effect(() => {
    if (art !== 'stufen') offen = false
  })
</script>

<!-- On the way down, before any button below can stop the click: the plus
     next to it stops its own, and the list must still close. -->
<svelte:window onpointerdowncapture={daneben} />

{#snippet birne(geist)}
  <svg class="birne" viewBox="0 0 64 64" fill="none" stroke="currentColor"
       stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    <g opacity={geist ? 0.55 : 1}>
      <path d="M32 8 a16.8 16.8 0 0 1 9.07 30.93 c-1.6 1.07 -2.67 2.67 -2.67 4.53 v1.87 h-12.8 v-1.87 c0 -1.87 -1.07 -3.47 -2.67 -4.53 A16.8 16.8 0 0 1 32 8 Z" stroke-width="5" />
      <path d="M26.7 54.7 H37.3" stroke-width="4.5" />
    </g>
    {#if !geist}<path d="M32 20 v10 M27 25 h10" stroke-width="4" />{/if}
  </svg>
{/snippet}

{#snippet punkte(voll)}
  <span class="punkte" aria-hidden="true">
    {#each denkende as stufe, i (stufe)}<i class:voll={i < voll}></i>{/each}
  </span>
{/snippet}

{#if art === 'stufen' || art === 'schalter'}
  <button
    bind:this={knopf}
    class="pille"
    class:an
    class:offen
    aria-label={t('eingabe.denken')}
    aria-haspopup={art === 'stufen' ? 'menu' : undefined}
    aria-expanded={art === 'stufen' ? offen : undefined}
    aria-pressed={art === 'schalter' ? an : undefined}
    title={denken ? t('denken.stufe.' + denken) : t('eingabe.denken')}
    onclick={klick}
    onkeydown={taste}
  >
    {@render birne(!an)}
    {@render punkte(rang(denken))}
  </button>
{:else}
  <span class="pille fest" class:an title={t(art === 'immer' ? 'denken.immer' : 'denken.nie')}>
    {@render birne(art !== 'immer')}
    <span class="wort" class:fort={narrow}>{t(art === 'immer' ? 'denken.immer' : 'denken.nie')}</span>
  </span>
{/if}

{#if offen}
  <div
    bind:this={liste}
    class="liste"
    role="menu"
    tabindex="-1"
    aria-label={t('eingabe.denken')}
    onkeydown={taste}
    onfocusout={fokusWeg}
    style="right: {ort.rechts}px; bottom: {ort.unten}px; max-height: {ort.hoch}px;"
  >
    <div class="kopf">{t('eingabe.denken')}</div>
    {#each stufen as stufe (stufe)}
      <button
        class="eintrag"
        role="menuitemradio"
        aria-checked={stufe === denken}
        onclick={() => waehlen(stufe)}
      >
        <span class="name">{t('denken.stufe.' + stufe)}</span>
        <!-- The word that actually goes into the request, beside the name
             it is shown under. Fixed width font: a value, not prose. -->
        {#if roh[stufe]}<span class="roh">{roh[stufe]}</span>{/if}
        {@render punkte(rang(stufe))}
        <svg class="haken" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M5 12l5 5 9-10" />
        </svg>
      </button>
    {/each}
  </div>
{/if}

<style>
  /* The same height as the microphone beside it, and no fill of its own:
     the bar's round buttons stand on its ground, and so does this one. */
  .pille {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    flex: none;
    height: 32px;
    padding: 0 9px;
    border: none;
    border-radius: 9px;
    background: none;
    color: var(--text-still);
    font: 500 12px/1 var(--schrift);
    cursor: pointer;
    transition: background 0.15s, color 0.15s;
  }
  .pille:hover,
  .pille.offen { background: var(--bg-hoch); color: var(--text); }
  .pille.an { color: var(--text); }
  .pille:focus-visible { outline: 2px solid var(--linie-stark); outline-offset: -2px; }
  .birne { width: 16px; height: 16px; flex: none; overflow: visible; }

  /* How much: one dot per thinking stage, in the text colour as far as the
     chosen one and quiet beyond it, in every look — the ring of the context
     wears the same pair. */
  .punkte { display: inline-flex; gap: 3px; }
  .punkte i {
    width: 5px;
    height: 5px;
    border-radius: 50%;
    background: var(--indicator-empty);
    transition: background 0.2s;
  }
  .punkte i.voll { background: var(--text); }

  /* The two models with nothing to set: a word beside the bulb, not a dead
     button. */
  .pille.fest { position: relative; cursor: default; }
  .pille.fest:hover { background: none; color: var(--text-still); }
  .pille.fest.an:hover { color: var(--text); }
  .wort { white-space: nowrap; }
  /* The narrow form: out of the row and out of the sight, still in the
     tree for a screen reader. */
  .wort.fort {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
  }

  .liste {
    position: fixed;
    z-index: 10;
    min-width: 190px;
    max-width: calc(100vw - 32px);
    overflow-y: auto;
    scrollbar-width: none;
    padding: 5px;
    border-radius: 9px;
    background: var(--bg-erhoben);
    box-shadow: 0 0 0 1px var(--linie), 0 18px 40px -8px rgba(0, 0, 0, 0.55);
  }
  .kopf {
    padding: 6px 10px 4px;
    font-size: 12px;
    color: var(--text-still);
  }
  .eintrag {
    display: flex;
    align-items: center;
    gap: 10px;
    width: 100%;
    padding: 7px 10px;
    border: none;
    border-radius: 9px;
    background: none;
    color: var(--text-leise);
    font: 400 13px var(--schrift);
    text-align: left;
    white-space: nowrap;
    cursor: pointer;
  }
  .eintrag:hover,
  .eintrag:focus-visible { background: var(--bg-hoch); color: var(--text); outline: none; }
  .eintrag[aria-checked='true'] { color: var(--text); }
  .roh { font: 400 11.5px var(--schrift-fest); color: var(--text-still); }
  .haken {
    width: 14px;
    height: 14px;
    flex: none;
    margin-left: auto;
    color: var(--text-leise);
    opacity: 0;
  }
  .eintrag[aria-checked='true'] .haken { opacity: 1; }

  @media (prefers-reduced-motion: reduce) {
    .pille, .punkte i { transition: none; }
  }
</style>
