<script>
  /* One choice out of many, in the space of a single control.

     A row of buttons shows every option at once, which is the right shape
     for two or three of them. Beyond that the row grows past the tile it
     sits in and pushes itself over the label next to it — and the list of
     skins is meant to grow. This keeps the width of one button no matter
     how long the list gets.

     Not a native <select>: its list is drawn by the operating system and
     carries none of the house tokens, so the window would show a grey
     system menu in the middle of a themed dialog. */

  let {
    optionen = [],           // [[wert, beschriftung], …] — beschriftung already translated
    wert = $bindable(null),
    beschriftung = '',       // what the control is called, for screen readers
    nachOben = false,        // opens upward — for a control pinned near the bottom
    kompakt = false,         // a narrow pill instead of the settings-tile width
    aufWahl = null,          // called with the new value — for a caller that
                              // persists it itself instead of only binding
    farbe = null,            // a fixed CSS colour ("var(--gruen)") for a value
                              // that IS a state, not a neutral choice — the
                              // chat permission mode is the one caller
    klasse = '',             // extra class names on the button, so a caller
                              // can style its own instance without a second
                              // copy of this component
    zeichen = null,          // Snippet(wert): a mark before the text, drawn in
                              // the button AND before every entry — a status
                              // dot belongs to the value, not to the border
    vorne = null,            // Snippet(): a mark at the very front of the
                              // button only, for a control that has one
    rohwerte = null,         // { wert: "native word" } — shown small and
                              // right in the entry, so the word that goes
                              // into the request stays readable
    trennerNach = null,      // a line under this value, for a list whose
                              // first entry is a different kind of thing
    schliessen = false,      // true while something else has come up over the
                              // control (a dialog, a page): an open list goes
                              // with it instead of hanging above that layer
  } = $props()

  let offen = $state(false)
  $effect(() => {
    if (schliessen) offen = false
  })
  let knopf = $state(null)
  let liste = $state(null)
  let ort = $state({ left: 0, minWeite: 0, oben: null, unten: null })

  const jetzige = $derived(optionen.find(([w]) => w === wert))
  const jetzigerText = $derived(jetzige ? jetzige[1] : '')

  /* The button sits inside `.eingabe`, which clips overflow so the field's
     rounded corners stay clean while it grows — an absolutely positioned
     list there gets cut off the moment it reaches the field's edge. Fixed
     positioning off the button's own rectangle escapes that clip, wherever
     the control is used.

     The list's own width is only known once it hangs in the tree (an
     entry can run wider than the button, e.g. a raw value next to its
     name) — so the first call, before it opens, estimates with the
     button's own width, and a second call right after opening corrects
     `left` against the list's real width. The edge clamp itself borrows
     `StilleWahl.svelte`'s `ausrichten`. Without the correction a wide list
     opening near the right edge ran off the window — exactly the
     overflow this control was built to stop, just on the other side. */
  function ortBerechnen() {
    if (!knopf) return
    const r = knopf.getBoundingClientRect()
    const weite = liste?.offsetWidth ?? r.width
    ort = {
      left: Math.max(16, Math.min(r.left, window.innerWidth - weite - 16)),
      minWeite: r.width,
      oben: nachOben ? null : r.bottom + 5,
      unten: nachOben ? window.innerHeight - r.top + 5 : null,
    }
  }

  function waehlen(neu) {
    wert = neu
    offen = false
    knopf?.focus()
    aufWahl?.(neu)
  }

  function umschalten() {
    if (!offen) {
      ortBerechnen()
      offen = true
      queueMicrotask(ortBerechnen)
    } else {
      offen = false
    }
  }

  /* Fixed positioning is a screen coordinate, not a spot in the button's own
     flow — it does not move when a scrolling ancestor carries the button
     away underneath it (a settings tile inside a scrolled column, for
     instance). Recompute on every scroll (capture, so an inner scrollable
     column is caught too) and on resize while the list is open. */
  $effect(() => {
    if (!offen) return
    window.addEventListener('scroll', ortBerechnen, true)
    window.addEventListener('resize', ortBerechnen)
    return () => {
      window.removeEventListener('scroll', ortBerechnen, true)
      window.removeEventListener('resize', ortBerechnen)
    }
  })

  /* The keys people expect from a menu: arrows walk it, Enter and Space take
     what is under the cursor, Escape leaves without changing anything. */
  function taste(ereignis) {
    if (ereignis.key === 'Escape') {
      /* Only the open list's own Escape is taken here. With the list
         closed it travels on to the window's shortcut and closes the page
         as before; with the list open it must stop here, or one key would
         close both the list and the page under it. */
      if (!offen) return
      ereignis.stopPropagation()
      ereignis.preventDefault()
      offen = false
      knopf?.focus()
      return
    }
    if (!offen && (ereignis.key === 'ArrowDown' || ereignis.key === 'ArrowUp')) {
      ortBerechnen()
      offen = true
      queueMicrotask(ortBerechnen)
      ereignis.preventDefault()
      return
    }
    if (!offen) return

    const stelle = optionen.findIndex(([w]) => w === wert)
    if (ereignis.key === 'ArrowDown') {
      ereignis.preventDefault()
      waehlenOhneSchliessen(stelle + 1)
    } else if (ereignis.key === 'ArrowUp') {
      ereignis.preventDefault()
      waehlenOhneSchliessen(stelle - 1)
    } else if (ereignis.key === 'Enter' || ereignis.key === ' ') {
      ereignis.preventDefault()
      offen = false
      knopf?.focus()
    }
  }

  function waehlenOhneSchliessen(stelle) {
    if (stelle < 0 || stelle >= optionen.length) return
    wert = optionen[stelle][0]
  }

  /* A click anywhere else closes the list — the same thing every menu does,
     and without it the list would stay open behind the next window. */
  function daneben(ereignis) {
    if (!offen) return
    if (knopf?.contains(ereignis.target) || liste?.contains(ereignis.target)) return
    offen = false
  }
</script>

<svelte:window onclick={daneben} />

<div class="klappwahl" class:kompakt>
  <button
    bind:this={knopf}
    class="knopf {klasse}"
    class:offen
    style={farbe ? `border-color:${farbe}; color:${farbe};` : undefined}
    aria-haspopup="listbox"
    aria-expanded={offen}
    aria-label={beschriftung}
    onclick={umschalten}
    onkeydown={taste}
  >
    {#if vorne}{@render vorne()}{/if}
    {#if zeichen}{@render zeichen(wert)}{/if}
    <span class="text">{jetzigerText}</span>
    <svg class="pfeil" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <path d="M6 9l6 6 6-6" />
    </svg>
  </button>

  {#if offen}
    <div
      bind:this={liste}
      class="liste"
      role="listbox"
      tabindex="-1"
      aria-label={beschriftung}
      onkeydown={taste}
      style="left: {ort.left}px; min-width: {ort.minWeite}px; {ort.oben !== null ? `top: ${ort.oben}px;` : `bottom: ${ort.unten}px;`}"
    >
      {#each optionen as [w, text] (w)}
        <button
          class="eintrag"
          role="option"
          aria-selected={w === wert}
          onclick={() => waehlen(w)}
        >
          <span class="haken" aria-hidden="true">
            {#if w === wert}
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5" /></svg>
            {/if}
          </span>
          {#if zeichen}{@render zeichen(w)}{/if}
          {text}
          {#if rohwerte?.[w]}<span class="roh">{rohwerte[w]}</span>{/if}
        </button>
        {#if trennerNach !== null && w === trennerNach}
          <div class="trenner" aria-hidden="true"></div>
        {/if}
      {/each}
    </div>
  {/if}
</div>

<style>
  .klappwahl { position: relative; flex: none; }

  .knopf {
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 116px;
    /* Button glass with its fine edge; the input bar dresses its own
       button (Eingabeleiste.svelte). */
    border: 1px solid var(--glass-button-edge);
    border-radius: 9px;
    background: var(--glass-button);
    color: var(--text);
    font: 400 13px var(--schrift);
    padding: 0 10px 0 12px;
    cursor: pointer;
    text-align: left;
    height: 32px;
  }
  .knopf:hover,
  .knopf.offen { background: color-mix(in srgb, var(--text) 5%, var(--glass-button)); }
  .text { flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .pfeil { flex: none; width: 11px; height: 11px; color: var(--text-still); transition: transform 0.16s ease; }
  .knopf.offen .pfeil { transform: rotate(180deg); }

  /* A pill among round icon-buttons (the input bar's capability row) — no
     settings-tile minimum width, a touch smaller so it sits at the same
     height as its neighbours. */
  .kompakt .knopf { min-width: 0; padding: 0 9px; font-size: 12.5px; gap: 6px; height: 28px; }

  .liste {
    position: fixed;
    z-index: 10;
    border: 1px solid transparent;
    border-radius: 9px;
    /* The dense glass of a floating layer, blurred, with the glass edge. */
    background: var(--glass-dropdown);
    -webkit-backdrop-filter: blur(16px);
    backdrop-filter: blur(16px);
    box-shadow: 0 0 0 1px var(--glass-button-edge), 0 18px 40px -8px rgba(0, 0, 0, 0.55);
    padding: 4px;
    max-height: 232px;
    overflow-y: auto;
    scrollbar-width: none;
  }
  .liste::-webkit-scrollbar { display: none; }

  .eintrag {
    display: flex;
    align-items: center;
    gap: 7px;
    width: 100%;
    border: none;
    border-radius: 9px;
    background: none;
    color: var(--text-leise);
    font: 400 13px var(--schrift);
    padding: 6px 9px;
    cursor: pointer;
    text-align: left;
    white-space: nowrap;
  }
  .eintrag:hover { background: var(--glass-hover); color: var(--text); }
  .eintrag[aria-selected='true'] { background: var(--glass-button); color: var(--text); }
  .haken { flex: none; width: 12px; display: grid; place-items: center; color: var(--text); }
  /* The word that actually goes into the request, beside the name it is
     shown under. Fixed width font, because it is a value, not prose. */
  .roh {
    margin-left: auto;
    padding-left: 14px;
    font: 400 11.5px var(--schrift-fest);
    color: var(--text-still);
  }
  .trenner { height: 1px; background: var(--linie); margin: 3px 6px; }

  @media (prefers-reduced-motion: reduce) {
    .pfeil { transition: none; }
  }
</style>
