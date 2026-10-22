<script>
  /* A number field with the house's own steppers.

     The browser's native spinners cannot be styled and sit in the fields
     like a foreign body next to the select chevrons. So the input hides
     them and carries two chevron buttons of its own — same stroke, same
     colour as every other arrow in these forms.

     The field is as wide as what stands in it and no wider, the number in
     its middle, and it keeps to the right end of the place it is given. */
  import { texte } from '../lib/texte.svelte.js'
  import { fractionDigits, formatNumber, parseNumber } from '../lib/numberDisplay.js'

  let {
    wert = $bindable(null),
    min = 0,
    max = 999999,
    schritt = 1,
    id = '',
    gesperrt = false,
    /* A word shown instead of an EMPTY field — for fields where nothing set
       does not mean zero but "the program decides". Empty: plain numbers,
       and then an empty field still commits to the minimum as before.

       It used to stand in for a typed zero, which made a real zero
       unsayable: a field where 0 means something ("Top-K 0 disables it")
       could not tell "off" from "untouched". Nothing set is nothing now,
       and a zero is a zero. */
    nullwort = '',
    /* Off by default: exactly one of this component's other callers
       hands `wert` to a float field (cfg). Several others (breite,
       schritte) bind to a whole-number field on the server and already
       get a visible 422 there if a fraction slips through — clamping
       alone was never enough for them either, it only reads that way
       because the server's own error shows up instead of one from here.
       A picture count is the odd one out: nothing downstream ever named
       the fraction wrong, so it rode all the way to a request as one.
       Typed input for it now goes through the same clamp as the
       chevrons, so a decimal never reaches whatever reads `wert` next
       only to be rejected there instead. */
    ganzzahlig = false,
    /* A grid the committed value is rounded up onto — for a field whose
       service keeps only such values (a picture's edge), so the field shows
       what is kept. 0: no grid. */
    grid = 0,
    // The field's name for a screen reader, where no label names it.
    beschriftung = '',
  } = $props()

  let fokus = $state(false)
  /* A field with a fractional step is a text field: the number stands with
     its fractional digit and the decimal sign of the language, which a
     native number field cannot do (it shows 1 for 1.0 and picks its sign
     from the browser). While it has the focus, what is typed stands as it
     is. A whole step keeps the native field. */
  const digits = $derived(ganzzahlig ? 0 : fractionDigits(schritt))
  const decimal = $derived(digits > 0)
  let typed = $state('')
  /* Nothing in the field. Svelte's number binding hands back `null` for an
     empty input; '' and `undefined` arrive from callers that start their
     state out that way. */
  const leer = (w) => w === null || w === undefined || w === ''
  /* Only a field that HAS a word may stay empty. Without one an empty field
     is still committed to the minimum, exactly as before — those callers
     bind to whole-number fields on the server and would get a 422 for an
     empty value. */
  const wortDa = $derived(Boolean(nullwort) && !fokus && leer(wert))

  function setzen(neu) {
    const onGrid = grid ? Math.ceil(neu / grid) * grid : neu
    const geklemmt = Math.min(max, Math.max(min, onGrid))
    wert = ganzzahlig ? Math.trunc(geklemmt) : geklemmt
  }

  /* Typed input commits through the same clamp as the chevrons — an
     out-of-range field would otherwise travel to the server as it is and
     come back as a validation error. Clearing the field commits the empty
     value itself where a word stands for it: that is how "unset" is said,
     and a typed zero stays the zero it is. */
  function eingerastet() {
    if (leer(wert)) {
      wert = nullwort ? null : min
      return
    }
    const zahl = Number(wert)
    setzen(Number.isFinite(zahl) ? zahl : min)
  }

  const shown = $derived(
    !decimal || leer(wert) ? '' : formatNumber(wert, digits, texte.sprache),
  )

  function takeFocus() {
    fokus = true
    typed = shown
  }

  /* The same commit as above for the typed text: nothing in the field is the
     empty value, anything that is no number goes to the minimum. */
  function commitText() {
    const zahl = parseNumber(typed)
    if (zahl === null) {
      wert = nullwort ? null : min
      return
    }
    setzen(Number.isFinite(zahl) ? zahl : min)
  }

  function textKey(ereignis) {
    if (ereignis.key !== 'ArrowUp' && ereignis.key !== 'ArrowDown') return
    ereignis.preventDefault()
    stufen(ereignis.key === 'ArrowUp' ? +1 : -1)
    typed = leer(wert) ? '' : formatNumber(wert, digits, texte.sprache)
  }

  /* A chevron on an empty field starts at the minimum rather than at zero:
     the field says nothing yet, and the minimum is the first thing it could
     say. */
  function stufen(richtung) {
    if (leer(wert)) {
      setzen(min)
      return
    }
    setzen((Number(wert) || 0) + richtung * schritt)
  }
</script>

<div class="zahl" class:gesperrt>
  {#if wortDa}
    <span class="nullwort">{nullwort}</span>
  {/if}
  {#if decimal}
    <input
      {id}
      type="text"
      inputmode="decimal"
      autocomplete="off"
      aria-label={beschriftung || undefined}
      class:versteckt={wortDa}
      style:min-width={wortDa ? `${nullwort.length + 1}ch` : null}
      value={fokus ? typed : shown}
      role="spinbutton"
      aria-valuemin={min}
      aria-valuemax={max}
      aria-valuenow={leer(wert) ? undefined : Number(wert)}
      disabled={gesperrt}
      oninput={(e) => (typed = e.currentTarget.value)}
      onchange={commitText}
      onkeydown={textKey}
      onfocus={takeFocus}
      onblur={() => (fokus = false)}
    />
  {:else}
    <input
      {id}
      type="number"
      aria-label={beschriftung || undefined}
      class:versteckt={wortDa}
      style:min-width={wortDa ? `${nullwort.length + 1}ch` : null}
      bind:value={wert}
      {min}
      {max}
      step={schritt}
      disabled={gesperrt}
      onchange={eingerastet}
      onfocus={() => (fokus = true)}
      onblur={() => (fokus = false)}
    />
  {/if}
  <span class="treppe">
    <button
      type="button"
      tabindex="-1"
      aria-label="+"
      disabled={gesperrt}
      onclick={() => stufen(+1)}
    >
      <svg width="11" height="7" viewBox="0 0 12 8" fill="none" stroke="currentColor"
           stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M1 6.5 6 1.5l5 5" />
      </svg>
    </button>
    <button
      type="button"
      tabindex="-1"
      aria-label="−"
      disabled={gesperrt}
      onclick={() => stufen(-1)}
    >
      <svg width="11" height="7" viewBox="0 0 12 8" fill="none" stroke="currentColor"
           stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M1 1.5 6 6.5l5-5" />
      </svg>
    </button>
  </span>
</div>

<style>
  .zahl {
    position: relative;
    display: flex;
    align-items: center;
    width: fit-content;
    max-width: 100%;
    margin-left: auto;
    /* The one field height of the house, shared with the selection field,
       and the palette's corner for a control — so a row of fields, pickers
       and buttons reads as one line of equals. Glass with the house's field
       outline, as the selection field wears it. */
    height: 32px;
    border: 1px solid var(--feldstrich);
    border-radius: 9px;
    background: var(--glass-button);
  }
  /* As wide as its number; the room on the left matches the steppers' on
     the right, so the number stands in the middle of the field. */
  input {
    field-sizing: content;
    min-width: 2ch;
    border: none;
    background: none;
    color: var(--text);
    /* The system face with even digits, like every number in the house. */
    font: 400 13px/1.2 var(--schrift);
    font-variant-numeric: tabular-nums;
    padding: 6px 0 6px 23px;
    text-align: center;
    outline: none;
    appearance: textfield;
  }
  input::-webkit-inner-spin-button,
  input::-webkit-outer-spin-button {
    appearance: none;
    margin: 0;
  }
  /* While the word stands in, the field's own text steps aside; a click on
     the field brings it back for typing. */
  input.versteckt {
    color: transparent;
  }
  .nullwort {
    position: absolute;
    left: 23px;
    right: 23px;
    text-align: center;
    font: 400 13px/1.2 var(--schrift);
    font-variant-numeric: tabular-nums;
    color: var(--text-still);
    pointer-events: none;
  }
  .gesperrt input {
    color: var(--text-still);
  }
  /* The steppers only show under the pointer or while the field has focus;
     they keep their room, so the number does not move when they appear. */
  .treppe {
    display: flex;
    flex-direction: column;
    flex: none;
    box-sizing: border-box;
    width: 23px;
    padding: 2px 6px 2px 2px;
    opacity: 0;
    transition: opacity 0.12s;
  }
  .zahl:hover .treppe,
  .zahl:focus-within .treppe {
    opacity: 1;
  }
  /* A touch screen has no pointer to hover with; there the steppers stay in
     sight, or a tap on the field's right edge would change the value
     unseen. */
  @media (hover: none), (any-pointer: coarse) {
    .treppe {
      opacity: 1;
    }
  }
  .treppe button {
    display: inline-flex;
    border: none;
    background: none;
    padding: 1px 2px;
    color: var(--text-still);
    cursor: pointer;
  }
  .treppe button:hover {
    color: var(--text);
  }
  .treppe button:disabled {
    color: var(--linie-stark);
    cursor: default;
  }
</style>
