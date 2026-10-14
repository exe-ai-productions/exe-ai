<script module>
  /* Only one list stands open in the whole program. Shared by every
     instance, so opening one closes whatever was open before it — the job
     the window click would do if the fields did not have to swallow their
     own opening click. */
  let offener = null
</script>

<script>
  /* The house's one selection field.

     It replaces the browser's `<select>` everywhere a form asks a question
     with a fixed set of answers, and it exists for two reasons the native
     control could not give:

     * **One measure.** Three windows styled their own selects and drifted:
       11.5px here, 13.5px there, different padding again. A field is a
       field — the numbers live here once, and every form that uses this
       component is the same height without anybody measuring.
     * **It opens downward.** A native select on this platform drops its
       list OVER the field, so the thing you just clicked disappears under
       its own menu. Reading a list while the question is hidden is the
       wrong way round; here the question stays put and the answers appear
       beneath it.

     `eintraege` is a list of `{ wert, text }`. The caller decides what a
     value is called; this component only draws it. An entry may carry a
     `group`: the list then shows that name above the first entry of each
     run of the same group. `search` puts a search field at the top of the
     open list — for a list too long to walk, like every model file in a
     folder. The field and its open list are glass: a see-through ground
     with the house's field outline, the list dense and blurred — one way,
     wherever the field stands. */

  let {
    wert = $bindable(''),
    eintraege = [],
    gesperrt = false,
    ungueltig = false,
    id = undefined,
    beschriftung = '',
    leerText = '',
    gewaehlt: onGewaehlt = null,
    search = false,
    searchLabel = '',
  } = $props()

  let offen = $state(false)
  let dran = $state(-1)
  let feld = $state(null)
  let liste = $state(null)
  let klapp = $state(null)

  /* The list's own measure and its distance from the field and from the
     window's edge. */
  const LIST_HEIGHT = 260
  const LIST_GAP = 4
  const LIST_EDGE = 12
  const LIST_MIN = 120

  /* Every field stops the click that opens it, so the window handler that
     closes the others never hears it — two lists could stand open at once,
     both claiming to be the answer to their own question. Rather than let
     the click through (it would close this one again in the same breath),
     the open field says so here and the next one to open closes it. */
  let schliesserAbmelden = null

  const kennung = `auswahl-${Math.random().toString(36).slice(2, 9)}`
  const aktuell = $derived(eintraege.find((e) => e.wert === wert) ?? null)
  /* What the open list shows: every entry, or the ones whose text holds
     what was typed into the search field. The arrow keys walk this list. */
  let searchText = $state('')
  let searchField = $state(null)
  const visible = $derived.by(() => {
    const query = search ? searchText.trim().toLowerCase() : ''
    return query
      ? eintraege.filter((e) => (e.text ?? '').toLowerCase().includes(query))
      : eintraege
  })
  const text = $derived(aktuell?.text ?? leerText)

  function oeffnen() {
    offener?.()
    offen = true
    offener = zumachen
    schliesserAbmelden = zumachen
    searchText = ''
    /* Opening lands on what is chosen, so the arrow keys carry on from
       there instead of from the top of a list somebody already answered. */
    dran = Math.max(0, eintraege.findIndex((e) => e.wert === wert))
  }

  // A list with a search field opens with the cursor in it.
  $effect(() => {
    if (offen && search) searchField?.focus()
  })

  // What was typed narrows the list; the walk starts again at its top.
  function narrowed() {
    dran = visible.length ? 0 : -1
  }

  // Takes the walked-to entry, if the walk stands on one.
  function take() {
    if (dran >= 0 && visible[dran]) waehlen(visible[dran].wert)
  }

  /* What the open list does with a key, wherever the cursor is — on the
     field or in the search field: the arrows walk the shown entries, Enter
     takes the walked-to one. Written once, so a change to the walk reaches
     both. Says whether the key was one of these; every other key is the
     caller's own. Home and End are left out on purpose: on the field they
     jump to the ends of the list, in the search field they move through
     the typed text, as in any text field. */
  function listKey(event) {
    const { key } = event
    if (key === 'ArrowDown' || key === 'ArrowUp') {
      event.preventDefault()
      const direction = key === 'ArrowDown' ? 1 : -1
      dran = Math.min(visible.length - 1, Math.max(0, dran + direction))
      return true
    }
    if (key === 'Enter') {
      event.preventDefault()
      take()
      return true
    }
    return false
  }

  /* The keys inside the search field: Escape closes, Tab leaves, the list's
     own keys walk and take (`listKey`) — every other key types. */
  function searchKeys(event) {
    // Enter that ends a composition belongs to the input method (Safari
    // says so only through the key code).
    if (event.isComposing || event.keyCode === 229) return
    const { key } = event
    if (key === 'Escape') {
      // The key is the list's: nothing around it (a pop-up that holds the
      // field) may take it as its own close request.
      event.stopPropagation()
      event.preventDefault()
      zumachen()
      feld?.focus()
      return
    }
    /* Tab leaves the list closed behind it, never standing open alone. The
       search field goes with the list, so the cursor steps back onto the
       field first and Tab goes on from there; Shift+Tab stops on the field,
       which stood right before the search field. */
    if (key === 'Tab') {
      if (event.shiftKey) event.preventDefault()
      feld?.focus()
      zumachen()
      return
    }
    listKey(event)
  }

  /* A window that only grows or shrinks in height while a search is typed
     is the on-screen keyboard coming or going, not the page changing: that
     keeps the list open. Any other resize closes it. */
  let breite = typeof window === 'undefined' ? 0 : window.innerWidth
  function groesse() {
    const typing = document.activeElement === searchField && window.innerWidth === breite
    breite = window.innerWidth
    if (!typing) zumachen()
  }

  function zumachen() {
    offen = false
    dran = -1
    if (offener === schliesserAbmelden) offener = null
  }

  function schalten(ereignis) {
    ereignis.stopPropagation()
    if (gesperrt || !eintraege.length) return
    if (offen) zumachen()
    else oeffnen()
  }

  function waehlen(neu) {
    zumachen()
    /* Back to the field. A native select never leaves the focus on nothing;
       losing it here would drop the caller out of the form and make the next
       Tab start over from the top of the page. */
    feld?.focus()
    if (neu === wert) return
    wert = neu
    onGewaehlt?.(neu)
  }

  /* The open list stands in the top layer — a popover of its own — so no
     container the field sits in (a pop-up that scrolls, a card that clips)
     can cut it off. It is placed by hand beneath the field, as wide as the
     field, and as tall as the room below allows; where the room beneath is
     short and the room above is longer, it opens upward instead. */
  function place() {
    if (!klapp || !feld) return
    const rect = feld.getBoundingClientRect()
    const spaceBelow = window.innerHeight - rect.bottom - LIST_GAP - LIST_EDGE
    const spaceAbove = rect.top - LIST_GAP - LIST_EDGE
    const below = spaceBelow >= Math.min(LIST_HEIGHT, LIST_MIN) || spaceBelow >= spaceAbove
    const room = Math.max(below ? spaceBelow : spaceAbove, 0)
    klapp.style.left = `${rect.left}px`
    klapp.style.width = `${rect.width}px`
    klapp.style.maxHeight = `${Math.min(room, LIST_HEIGHT + 60)}px`
    if (below) {
      klapp.style.top = `${rect.bottom + LIST_GAP}px`
      klapp.style.bottom = 'auto'
    } else {
      klapp.style.top = 'auto'
      klapp.style.bottom = `${window.innerHeight - rect.top + LIST_GAP}px`
    }
  }

  /* Whether the scroll of ``source`` moves the field: the page itself or a
     box that holds the field. A box elsewhere that scrolls by itself (an
     answer being written, a log running along) does not, and the list
     beneath the field stays where it belongs. The list's own scrolling is
     not the field's either. */
  function scrollMovesField(source) {
    if (!(source instanceof Node)) return true
    if (klapp?.contains(source)) return false
    return Boolean(feld && source.contains(feld))
  }

  $effect(() => {
    if (!offen || !klapp) return
    if (!klapp.matches(':popover-open')) klapp.showPopover()
    place()
    /* The field moving away from under it, or a window that changes size,
       takes the list away: it would otherwise hang where the field was. */
    const dismiss = (event) => {
      if (event.type === 'scroll' && !scrollMovesField(event.target)) return
      zumachen()
    }
    window.addEventListener('scroll', dismiss, true)
    window.addEventListener('resize', dismiss)
    return () => {
      window.removeEventListener('scroll', dismiss, true)
      window.removeEventListener('resize', dismiss)
    }
  })

  /* The walked-to entry is scrolled into view. Without this the list moves
     the highlight below its own edge from about the eighth entry on, and
     everything after that is chosen blind. */
  $effect(() => {
    if (!offen || dran < 0 || !liste) return
    liste.querySelector(`#${kennung}-${dran}`)?.scrollIntoView({ block: 'nearest' })
  })

  $effect(() => () => {
    if (offener === schliesserAbmelden) offener = null
  })

  /* Typing a letter jumps to the entry that starts with it, the way the
     native control does. On a list of model files that is the difference
     between finding one and scrolling for it. The buffer resets after a
     pause, so "ge" finds "gemma" and a later "g" starts again. */
  let getippt = ''
  let tippUhr = null

  function tippsuche(zeichen) {
    clearTimeout(tippUhr)
    getippt += zeichen.toLowerCase()
    tippUhr = setTimeout(() => (getippt = ''), 700)
    const ab = offen ? dran : eintraege.findIndex((e) => e.wert === wert)
    // The open list walks what it shows — narrowed by a search, if any.
    const treffer = (offen ? visible : eintraege)
      .findIndex((e) => (e.text ?? '').toLowerCase().startsWith(getippt))
    if (treffer < 0) return
    if (offen) dran = treffer
    else if (treffer !== ab) waehlen(eintraege[treffer].wert)
  }

  /* The keyboard walks the list without opening it, the same way the native
     control did — losing that would make the field worse than what it
     replaces. */
  function tasten(ereignis) {
    if (gesperrt || !eintraege.length) return
    const { key } = ereignis
    // Tab moves on from the field; the list does not stay open behind it.
    if (key === 'Tab' && offen) {
      zumachen()
      return
    }
    if (key === 'Escape' && offen) {
      ereignis.stopPropagation()
      ereignis.preventDefault()
      zumachen()
      return
    }
    // Open, the arrows and Enter are the list's own keys.
    if (offen && listKey(ereignis)) return
    // Shut, an arrow steps the chosen value itself.
    if (key === 'ArrowDown' || key === 'ArrowUp') {
      ereignis.preventDefault()
      const richtung = key === 'ArrowDown' ? 1 : -1
      const jetzt = eintraege.findIndex((e) => e.wert === wert)
      const naechster = Math.min(eintraege.length - 1, Math.max(0, jetzt + richtung))
      waehlen(eintraege[naechster].wert)
      return
    }
    if (key === 'Home' || key === 'End') {
      ereignis.preventDefault()
      const ziel = key === 'Home' ? 0 : (offen ? visible : eintraege).length - 1
      if (offen) dran = ziel
      else waehlen(eintraege[ziel].wert)
      return
    }
    // Space takes like Enter on the field; in the search field it is a
    // letter, so it is not one of the list's shared keys.
    if (key === ' ' && offen) {
      ereignis.preventDefault()
      take()
      return
    }
    /* Enter or Space on a shut field opens it — the native control does the
       same, and without it the keyboard can only ever step one entry at a
       time without seeing the list. */
    if ((key === 'Enter' || key === ' ') && !offen) {
      ereignis.preventDefault()
      oeffnen()
      return
    }
    if (key.length === 1 && !ereignis.metaKey && !ereignis.ctrlKey && !ereignis.altKey) {
      ereignis.preventDefault()
      tippsuche(key)
    }
  }
</script>

<svelte:window onclick={zumachen} onresize={groesse} />

<div class="feldplatz">
  <button
    bind:this={feld}
    {id}
    type="button"
    class="feld"
    class:offen
    class:gesperrt
    role="combobox"
    aria-haspopup="listbox"
    aria-expanded={offen}
    aria-controls={offen ? `${kennung}-liste` : undefined}
    aria-label={beschriftung || undefined}
    aria-activedescendant={offen && dran >= 0 ? `${kennung}-${dran}` : undefined}
    aria-invalid={ungueltig || undefined}
    disabled={gesperrt}
    onclick={schalten}
    onkeydown={tasten}
  >
    <span class="text">{text}</span>
    <svg class="winkel" width="11" height="11" viewBox="0 0 24 24" fill="none"
         stroke="currentColor" stroke-width="2.6" stroke-linecap="round"
         stroke-linejoin="round" aria-hidden="true">
      <path d="M6 9l6 6 6-6" />
    </svg>
  </button>

  {#if offen}
    <div
      class="klapp"
      popover="manual"
      role="presentation"
      bind:this={klapp}
      onclick={(e) => e.stopPropagation()}
    >
      {#if search}
        <input class="search" type="search" bind:this={searchField} bind:value={searchText}
               role="combobox" aria-expanded="true" aria-autocomplete="list"
               aria-label={searchLabel || undefined}
               aria-controls="{kennung}-liste"
               aria-activedescendant={dran >= 0 ? `${kennung}-${dran}` : undefined}
               oninput={narrowed} onkeydown={searchKeys} />
      {/if}
      <div class="liste" id="{kennung}-liste" role="listbox" tabindex="-1"
           bind:this={liste}>
        <!-- tabindex="-1" is deliberate: the field is the one tab stop and
             the arrow keys walk from there. Tabbable entries let Tab fall
             into the open list, where Escape and the arrows are no longer
             heard and the list stays open with nothing driving it. -->
        {#each visible as eintrag, i (eintrag.wert)}
          {#if eintrag.group !== undefined && eintrag.group !== visible[i - 1]?.group}
            <div class="group-name" role="presentation">{eintrag.group}</div>
          {/if}
          <button
            type="button"
            role="option"
            id="{kennung}-{i}"
            tabindex="-1"
            class:dran={i === dran}
            aria-selected={eintrag.wert === wert}
            onclick={() => waehlen(eintrag.wert)}
            onmouseenter={() => (dran = i)}
          >
            <span class="haken">
              {#if eintrag.wert === wert}
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                     stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M4 12.5 L9.5 18 L20 6.5" />
                </svg>
              {/if}
            </span>
            <span class="zeile">{eintrag.text}</span>
          </button>
        {/each}
      </div>
    </div>
  {/if}
</div>

<style>
  /* The anchor the list hangs under. Relative and nothing else — the field
     keeps its own place in whatever form it stands in. */
  .feldplatz {
    position: relative;
    min-width: 0;
  }

  /* THE measure. Every selection field in the house is this. */
  .feld {
    width: 100%;
    box-sizing: border-box;
    display: flex;
    align-items: center;
    gap: 8px;
    font: inherit;
    font-size: 13px;
    line-height: 1.3;
    color: var(--text);
    /* Glass with the house's field outline, so the field is told from the
       glass it stands on in every look; the floor holds the one field
       height of the house, the number field's. */
    min-height: 32px;
    background: var(--glass-button);
    border: 1px solid var(--feldstrich);
    border-radius: 9px;
    padding: 6px 10px 6px 12px;
    cursor: pointer;
    text-align: left;
  }
  .feld:hover:not(.gesperrt),
  .feld.offen {
    background: color-mix(in srgb, var(--text) 5%, var(--glass-button));
  }
  .feld.gesperrt {
    opacity: 0.6;
    cursor: default;
  }
  .text {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .winkel {
    flex: none;
    color: var(--text-still);
    transition: transform 0.15s;
  }
  .feld.offen .winkel {
    transform: rotate(180deg);
  }

  /* Beneath the field, never over it, in the top layer: placed by hand
     (`place`), the browser's own centring of a popover undone. */
  .klapp {
    position: fixed;
    inset: auto;
    margin: 0;
    padding: 0;
    color: inherit;
    /* The dense glass of a floating layer, blurred, with the glass edge. */
    background: var(--glass-dropdown);
    -webkit-backdrop-filter: blur(16px);
    backdrop-filter: blur(16px);
    border: 1px solid var(--glass-button-edge);
    border-radius: 9px;
    box-shadow: 0 18px 40px -8px rgba(0, 0, 0, 0.55);
    overflow: hidden;
  }
  /* Laid out as a column only while it stands open: a display set on the
     list itself would show it before the browser has put it in the top
     layer. */
  .klapp:popover-open {
    display: flex;
    flex-direction: column;
  }
  .liste {
    flex: 1 1 auto;
    min-height: 0;
    max-height: 260px;
    overflow-y: auto;
    padding: 4px;
  }
  .liste button {
    width: 100%;
    display: flex;
    align-items: center;
    gap: 7px;
    font: inherit;
    font-size: 13px;
    color: var(--text);
    background: none;
    border: none;
    border-radius: 9px;
    padding: 7px 8px;
    cursor: pointer;
    text-align: left;
  }
  .liste button.dran {
    background: var(--glass-button);
  }
  /* The group's name above its entries: quiet, not choosable. */
  .group-name {
    padding: 8px 8px 3px;
    font-size: 11px;
    font-weight: 600;
    color: var(--text-still);
  }
  .search {
    display: block;
    width: calc(100% - 8px);
    box-sizing: border-box;
    margin: 4px 4px 0;
    padding: 6px 10px;
    font: inherit;
    font-size: 13px;
    color: var(--text);
    /* A field like the one above it: glass with the field outline; focus
       lifts the ground as the field's hover does. */
    background: var(--glass-button);
    border: 1px solid var(--feldstrich);
    border-radius: 9px;
    outline: none;
  }
  .search:focus {
    background: color-mix(in srgb, var(--text) 5%, var(--glass-button));
  }
  .haken {
    flex: none;
    width: 12px;
    display: inline-flex;
    color: var(--text-leise);
  }
  .zeile {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  @media (prefers-reduced-motion: reduce) {
    .winkel { transition: none; }
  }
</style>
