<script>
  /* The windows' text field: grows with the text up to a cap, after
     which the window stays the same size and the text scrolls INSIDE the
     field — no visible scrollbar and no resize handle (without the cap,
     the editor grew out of the picture in all directions).

     Prose stands in the system face. A file shown as it lies on disk —
     the configuration, the tool list, an agent's file with its front
     matter — is a source view and keeps the fixed face (`quelle`), which
     holds its indentation and dashes in line. Extracted from the
     system-prompt window so the job dialog doesn't maintain the same
     mechanics a second time. */
  let {
    wert = $bindable(''),
    platzhalter = '',
    beschriftung = '',
    gesperrt = false,
    // Grayed out but readable — the system prompt uses this when it is
    // suspended for the current chat.
    gedimmt = false,
    quelle = false,
    /* Always fill the full available height instead of growing with the
       content. The editor alternates between short
       (system prompt) and long content (MCP configuration) — without
       this, the window jumped to a different size on every switch. The
       job windows use it too since they hold a height of their own
       (Auftragfenster.svelte): in a box of a fixed 650 px, a field that
       grew with its text would sit one line tall under all that room and
       shift the buttons under the pointer with every keystroke. */
    volleHoehe = false,
    /* The server windows' instruction fields:
       the field's own inset and an 18 px line, and at most `zeilen` lines
       high before the text scrolls inside — so a long default text does not
       stretch every card beside it. */
    knapp = false,
    zeilen = 0,
    /* A block of a fixed height that scrolls inside itself and that the
       corner drags taller — the form of an agent's instruction. It neither
       grows with its text nor fills the page. */
    block = false,
  } = $props()

  let feld = $state(null)

  function hoehe() {
    // In full mode, flexbox determines the size (rest of the 60vh row
    // after the extra blocks below) - setting a height of our own here
    // would work against it.
    if (!feld || volleHoehe || block) return
    feld.style.height = 'auto'
    feld.style.height = feld.scrollHeight + 'px'
  }

  $effect(() => {
    wert
    hoehe()
  })

  /* For the caller: put the cursor into the field after loading. */
  export function fokus() {
    feld?.focus()
    hoehe()
  }
</script>

<div class="feld" class:gedimmt class:volleHoehe class:quelle class:knapp class:block>
  <textarea
    bind:this={feld}
    bind:value={wert}
    style:max-height={knapp && zeilen ? `${zeilen * 18 + 20}px` : null}
    rows="1"
    disabled={gesperrt}
    placeholder={platzhalter}
    aria-label={beschriftung}
  ></textarea>
</div>

<style>
  /* Its own box with air all around, not a borderless band. Border,
     rounding and behavior like the input bar at the bottom of the
     window. */
  .feld {
    border: 1px solid transparent;
    /* 12 — it is a surface, and the palette gives surfaces 12. */
    border-radius: 9px;
    background: var(--bg-hoch);
    padding: 4px;
    transition: border-color 0.15s, opacity 0.18s;
  }
  .feld:focus-within {
    border-color: transparent;
    background: color-mix(in srgb, var(--text) 4%, var(--bg-hoch));
  }
  .feld.gedimmt {
    opacity: 0.35;
  }
  textarea {
    width: 100%;
    border: none;
    background: none;
    color: var(--text);
    font-family: var(--schrift);
    font-size: 13px;
    line-height: 1.6;
    padding: 9px 11px;
    resize: none;
    outline: none;
    display: block;
    /* The cap: the field grows up to here, from then on the text scrolls
       inside. No visible scrollbar — scrolling still works (wheel,
       swipe, cursor), and while typing the field follows the cursor by
       itself, because IT is the scroll container, not a frame around
       it. */
    max-height: 60vh;
    overflow-y: auto;
    scrollbar-width: none;
    transition: height 0.16s cubic-bezier(0.2, 0.9, 0.3, 1);
  }
  .feld.knapp {
    padding: 0;
    border: none;
  }
  .knapp textarea {
    padding: 10px 12px;
    line-height: 18px;
  }
  .quelle textarea {
    font-family: var(--schrift-fest);
    font-size: 12.5px;
  }
  textarea::-webkit-scrollbar {
    display: none;
  }
  textarea::placeholder {
    color: var(--text-still);
  }
  /* Full mode: the field takes up the rest of the fixed height the
     caller sets for its content area. That makes the window exactly the
     same height on every tab, even though some show extra blocks below
     (status lights, read indicator, suspend switch). Its own cap goes
     away — capping is now done by the flex frame. The floor is the one
     place that holds its least height: where the rows above it take the
     room, the field stops at about six lines and the body of the window
     scrolls instead of the field shrinking to a single row. */
  .feld.volleHoehe {
    display: flex;
    flex: 1;
    min-height: 10rem;
  }
  /* No height of its own: the row stretches it to the field. A percentage
     would need a parent with a set height, and a settings page only gives a
     least height — the field shrank to its one row. */
  .feld.volleHoehe textarea {
    flex: 1;
    max-height: none;
  }
  /* The block: 320 px high, the text scrolls in it, the corner drags it
     taller. Its height is the field's own, so there is no transition that
     would trail the pointer while it is dragged. */
  .feld.block textarea {
    height: 320px;
    min-height: 78px;
    max-height: none;
    resize: vertical;
    transition: none;
  }
  @media (prefers-reduced-motion: reduce) {
    textarea { transition: none; }
  }
</style>
