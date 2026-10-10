<script module>
  /* The folded column's bar of signs, on either side. */
  const SIGN_BAR = 52
  /* The chat's own air: 8px to either column. */
  const CHAT_AIR = 16
  /* What the chat keeps while a column is dragged wider. */
  const CHAT_MIN = 420
  /* This close to the other open column's width, a column takes exactly
     that width: both sides equal, the chat in the middle of the window. */
  const SNAP = 16

  /* The width a drag asks for, as the column may take it: never so wide
     that the chat keeps less than its minimum beside the other column, and
     snapped onto the other column's width when it comes close. The
     column's own minimum and maximum are its setter's business. */
  export function widthFor(raw, other, windowWidth) {
    const beside = other ?? SIGN_BAR
    const room = windowWidth - beside - CHAT_AIR - CHAT_MIN
    const width = Math.min(raw, room)
    if (other != null && Math.abs(width - other) <= SNAP && other <= room) return other
    return width
  }
</script>

<script>
  /* The handle on a seam — invisible until it is looked for. One for each
     column: the sidebar on the left, the tools on the right.

     Its own module because it belongs to neither side: a column does not
     own the border it sits on, and the chat does not own the column. It
     lives on the seam between them.

     There is nothing to see at rest. Brushing the seam shows a plain bar,
     and the bar answers both hands: a click folds the column away or back,
     a drag sets its width — and dragging far past the minimum folds it too,
     the way a hand expects. The width survives restarts; the seam never
     shows a permanent control.

     Because it is invisible, it needs keys: ⌘B for the sidebar, ⌘J for the
     tools. The strip alone would leave anyone who never brushes the seam
     without a way in. */
  import {
    zustand, seitenleisteSchalten, seitenBreiteSetzen, istSeitenleisteSchmal,
  } from '../lib/zustand.svelte.js'
  import { breiteSetzen, leiste, oeffnen, schliessen } from '../lib/arbeitsleiste.svelte.js'
  import { t } from '../lib/texte.svelte.js'

  /* `left` is the sidebar's seam, `right` the tools' one. */
  let { side = 'left' } = $props()
  const right = $derived(side === 'right')

  // Dragged this far below the minimum, the hand clearly wants it gone.
  const ZUKLAPP_BREITE = 150
  // Under this movement a press still counts as a click, not a drag.
  const KLICK_TOLERANZ = 4

  /* The column this seam belongs to, and the one across the chat. */
  const folded = $derived(right ? !leiste.offen : zustand.seitenleisteEingeklappt)
  const dragging = $derived(right ? leiste.zieht : zustand.seitenZieht)
  const ownWidth = () => (right ? leiste.breite : zustand.seitenBreite)
  const otherWidth = () => right
    ? (zustand.seitenleisteEingeklappt ? null : zustand.seitenBreite)
    : (leiste.offen ? leiste.breite : null)

  function setDragging(value) {
    if (right) leiste.zieht = value
    else zustand.seitenZieht = value
  }

  function takeWidth(px) {
    const width = widthFor(px, otherWidth(), window.innerWidth)
    if (right) breiteSetzen(width)
    else seitenBreiteSetzen(width)
  }

  /* `startSchmal` only matters on the left: the sidebar's toggle opens the
     drawer on a narrow window. The tools' seam does not stand there. */
  function toggle() {
    if (!right) seitenleisteSchalten(startSchmal)
    else if (leiste.offen) schliessen()
    else oeffnen()
  }

  let startX = 0
  let startBreite = 0
  let startSchmal = false
  let bewegt = false

  function fassen(e) {
    if (e.button !== 0) return
    e.preventDefault()
    if (folded) return
    startX = e.clientX
    startBreite = ownWidth()
    // Captured once, at the gesture's own start: the window can cross the
    // 760px breakpoint while the hand is still moving, and the release must
    // judge the gesture by the width it began at, not the width it ends at.
    startSchmal = istSeitenleisteSchmal()
    bewegt = false
    e.currentTarget.setPointerCapture(e.pointerId)
  }

  function ziehen(e) {
    if (!e.currentTarget.hasPointerCapture?.(e.pointerId)) return
    // The tools' column grows towards the left.
    const dx = right ? startX - e.clientX : e.clientX - startX
    if (!bewegt && Math.abs(dx) <= KLICK_TOLERANZ) return
    bewegt = true
    setDragging(true)
    if (startBreite + dx < ZUKLAPP_BREITE) {
      setDragging(false)
      e.currentTarget.releasePointerCapture(e.pointerId)
      toggle()
      return
    }
    takeWidth(startBreite + dx)
  }

  function loslassen(e) {
    setDragging(false)
    if (e.currentTarget.hasPointerCapture?.(e.pointerId)) {
      e.currentTarget.releasePointerCapture(e.pointerId)
    }
    if (!bewegt) toggle()
    bewegt = false
  }
</script>

<div class="zone" class:zu={folded} class:right>
  <button
    class="griff"
    class:packt={dragging}
    onpointerdown={fassen}
    onpointermove={ziehen}
    onpointerup={loslassen}
    title={folded ? t('seitenleiste.einblenden') : t('seitenleiste.ausblenden')}
    aria-label={folded ? t('seitenleiste.einblenden') : t('seitenleiste.ausblenden')}
    aria-pressed={!folded}
  ></button>
</div>

<style>
  /* Zero width in the layout: the strip must not push the chat aside for a
     control that is not there most of the time. */
  .zone {
    position: relative;
    width: 0;
    flex: none;
    z-index: 5;
  }
  /* Gone while a window is open. It lies BEHIND the veil already, but the
     veil only half covers what is under it — and a bright vertical bar
     showing through beside a dialog reads as a scrollbar, not as the handle
     of a sidebar nobody can reach right now. */
  :global(body:has(.schleier)) .zone {
    display: none;
  }
  /* The catch area, wider than what it shows — 26 px is what a mouse finds
     without being aimed — centred on the air between sidebar and chat. */
  .zone::before {
    content: '';
    position: absolute;
    left: -9px;
    top: 0;
    bottom: 0;
    width: 26px;
  }

  /* The tools' seam: the chat's air lies left of the column, so the catch
     area and the bar sit on the other side of the zone. */
  .zone.right::before {
    left: -17px;
  }
  .zone.right .griff {
    left: -7px;
  }

  /* A plain bar, nothing else: no arrow, no plate. What it does, the hand
     finds out by using it. */
  .griff {
    position: absolute;
    left: 1px;
    top: 50%;
    transform: translateY(-50%);
    width: 6px;
    height: 96px;
    border-radius: 9px;
    background: var(--linie-stark);
    border: none;
    padding: 0;
    cursor: col-resize;
    touch-action: none;
    opacity: 0;
    transition: opacity 0.14s, background 0.14s;
  }
  /* Appears for the whole catch area, not only over the 6 px itself —
     otherwise it would flicker away the moment you move towards it. */
  .zone:hover .griff,
  .griff:focus-visible,
  .griff.packt {
    opacity: 1;
  }
  .griff:hover,
  .griff.packt {
    background: var(--text-still);
  }

  /* Folded, the seam lies between the bar of signs and the chat: a click
     opens the column again, a drag has nothing to widen. */
  .zone.zu .griff {
    cursor: pointer;
  }

  /* On a narrow screen the sidebar is a drawer and the tools a sheet over
     the chat, opened from their bars. A handle on a seam that is not there
     would point at nothing. */
  @media (width < 760px) {
    .zone { display: none; }
  }
</style>
