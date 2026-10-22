<script>
  /* The house's drawn signs, in one place.

     Every sign the catalog, the local view and the settings reach for —
     the model capabilities (chevron, eye, bulb, bolt), the section marks
     (a grid, server racks, a cloud, a mallet, a pencil, a person, a box,
     a key, a document), and a folder. All one idiom: no fill, round-capped
     strokes, currentColor so the sign takes the colour of whatever wraps
     it (grey as a fact, blue when it stands for a live speed module).

     Its own module because a sign that appears in a card, a tile badge and
     a settings row must be the same drawing in all three — one file to
     draw it, none to keep in step. These are static signposts, not the
     running-tool marks, so no stroke-draw animation. A tool row reaches
     for them all the same: where the tool catalogue names a sign for a
     server and the row has no drawing of its own under that name, it
     hands the name here (Werkzeugzeichen.svelte).

       werkzeug   calls tools (wrench)  raster     the local models grid
       ranking_bars  the overview of the servers (a baseline, three bars)
       handy      the web app (a phone)
       auge       sees images           server     a model server (racks)
       gluehbirne thinks first          wolke      memory
       blitz      the speed module      buch       skills
       sprache    language              feder      the standing instructions
       erscheinung appearance           person     an agent
       paket      Hugging Face          schluessel a stored key
       dokument   a file (config, script)  dokument_pfeil  a raw list file
       dokument_zeilen  a page with lines (nothing to preview)
       ordner     a folder (models, projects)  bild  a picture server
       folder_plus  the same folder with a plus (a new project)
       einbettung an embedding server   stoppuhr   the schedules (cronjobs)
       blatt_zeilen a report (sheet with lines)
       agent      the agent server      schloss_offen  auto mode's own risk —
                                                   the shackle open, not shut
       sprache_welle  the speech server
       netzwerk   the chip with a network     besen  clean-up, house style
       plus       adding something new        plug   an MCP server
       archive    the archive (a drawer)
       keyboard   the shortcuts       microphone  the microphone key
       sprechblase  a chat           puzzle      an add-on (accessories)
       speech_bubble_dots  a chat with three dots (the instructions are on)
       download   a download (arrow onto a line)
       neu_laden  loading again (a clockwise arc with its tip at the end)
       ecken      the layout mode (two opposite corners)
       clapperboard  a video (the clapper above its board)
       kamera     the camera (take a picture)  neu   a new chat (pencil on a line)
       schild     how far tools may go (a shield)
       hilfe      the manual (a question mark)
       trash      remove (a bin)         info       an explanation (a circle with an i)
       chevron_right  a way in (a right-pointing chevron)
       chevron_left   a way back (a left-pointing chevron)
       gear       the settings (a cog)   chip_bolt  a chip with a bolt
       flag       a goal (a pennant on its pole)
       play       play a recording (a triangle)   stop  stop (a rounded square)
       clock      the time (a dial with its four quarter marks)
       branch     a fork (a line that splits)
       save       save (a floppy)        refresh    reload both ways (two arrows)
       ellipsis   more (three dots)      settings_two  two sliders
       update_available  a newer version (a circle fading out, an arrow up)
       shrink     a smaller copy (four corners moving in)
       speaker    a loudspeaker with sound waves (the test button of a notification)

     The three server kinds used to share the rack sign, which said "a
     server" three times and which of the three never. Now the rack stays
     with the model server alone, the picture server wears the framed
     picture the chat menu already uses for making one, and the embedding
     server gets a sign of its own: three points held together by fine
     lines — a vector space small enough to fit in a tile. */
  /* Three sizes, no loose numbers. Callers name a step instead of passing
     pixels, so the whole house can grow or shrink from this one table —
     the old way spread eleven hand-picked numbers over six files, and the
     same sign ended up in three different sizes depending on where it
     stood. A bare number still works where one truly has to differ. */
  const STUFEN = { klein: 15, mittel: 19, gross: 23 }

  /* `strich` follows the same escape hatch as `groesse`: most callers leave
     it at the house default, and a sign whose catalogue drawing is heavier
     (the chevron and the tick, 2.6 in the house icon set) passes its
     own number instead of a new step nobody else would use. */
  let { zeichen = '', groesse = 'mittel', strich = 2 } = $props()

  const kante = $derived(STUFEN[groesse] ?? groesse)

  /* Almost every sign here was drawn on a 24-grid, and for those this is one
     number nobody has to think about. A sign that comes out of the house
     catalogue on its own grid keeps that grid instead of being redrawn onto
     this one: retracing a path by hand is how a sign stops being the sign in
     the catalogue, and the catalogue is the original. The paths travel
     verbatim, coordinates and per-path stroke widths included; only the
     coordinate system they were drawn in travels with them. */
  /* The agent mark is drawn from y 8 to 60 — its own middle sits at 34, not
     at 32, so on a plain 0 0 64 64 it hangs 0.8 px low next to the other
     three signs of the rail (measured: +7 image points against +2). The view
     travels down by the same 2 instead, which centres the mark without
     touching a single coordinate of the catalogue drawing. Sideways all four
     already sit on one axis. The clapperboard hangs the same way: its flap
     leans down and its drawing sits off the middle of the 24 grid, so the
     view is cut to the drawing's own extent and the sign stands in the
     middle of its box. */
  const SICHTFELDER = { agent: '0 2 64 64', sprache_welle: '0 0 64 64', plug: '0 0 64 64', archive: '0 0 64 64', keyboard: '0 0 64 64', microphone: '0 0 64 64', dokument_zeilen: '0 0 64 64', palette: '0 0 64 64', server: '0 0 64 64', ranking_bars: '0 0 64 64', chip_bolt: '0 0 64 64', netzwerk: '0 0 64 64', clock: '0 0 64 64', clapperboard: '-1.15 -0.25 26.5 26.5', branch: '0 0 64 64', stopwatch: '0 0 64 64', blatt_zeilen: '0 0 64 64', sprechblase: '0 0 64 64', speech_bubble_dots: '0 0 64 64', puzzle: '0 0 64 64' }
  const sichtfeld = $derived(SICHTFELDER[zeichen] ?? '0 0 24 24')
</script>

<svg
  viewBox={sichtfeld}
  width={kante}
  height={kante}
  fill="none"
  stroke="currentColor"
  stroke-width={strich}
  stroke-linecap="round"
  stroke-linejoin="round"
  aria-hidden="true"
>
  {#if zeichen === 'handy'}
    <!-- A phone: the body and the home dot. -->
    <rect x="5" y="2" width="14" height="20" rx="2" />
    <path d="M12 18h.01" />
  {:else if zeichen === 'werkzeug'}
    <!-- The open-end wrench — it replaced the caret, which said
         "terminal" when it meant "calls tools". -->
    <path d="M7 10h3v-3l-3.5-3.5a6 6 0 0 1 8 8l6 6a2 2 0 0 1-3 3l-6-6a6 6 0 0 1-8-8l3.5 3.5" />
  {:else if zeichen === 'auge'}
    <path d="M2.5 12 C6 6.5, 18 6.5, 21.5 12 C18 17.5, 6 17.5, 2.5 12 Z" />
    <circle cx="12" cy="12" r="3" />
  {:else if zeichen === 'gluehbirne'}
    <path d="M12 3 a6.3 6.3 0 0 1 3.4 11.6 c-.6.4-1 1-1 1.7 v.7 h-4.8 v-.7 c0-.7-.4-1.3-1-1.7 A6.3 6.3 0 0 1 12 3 Z" />
    <path d="M10 20.5 h4" />
  {:else if zeichen === 'blitz'}
    <path d="M13 3 L5 13.5 H10.5 L9.5 21 L17.5 10.5 H12 Z" />
  {:else if zeichen === 'raster'}
    <rect x="3.5" y="3.5" width="7.5" height="7.5" rx="2" />
    <rect x="13" y="3.5" width="7.5" height="7.5" rx="2" />
    <rect x="3.5" y="13" width="7.5" height="7.5" rx="2" />
    <rect x="13" y="13" width="7.5" height="7.5" rx="2" />
  {:else if zeichen === 'server'}
    <!-- The house icon server-stack, verbatim on its own 64 grid: two racks,
         each with its lamp and its slot. Every server of the program wears
         this one drawing. -->
    <rect x="12" y="13" width="40" height="17" rx="5.5" stroke-width="5" />
    <rect x="12" y="34" width="40" height="17" rx="5.5" stroke-width="5" />
    <circle cx="21" cy="21.5" r="1.4" stroke-width="4.2" />
    <circle cx="21" cy="42.5" r="1.4" stroke-width="4.2" />
    <path d="M36 21.5 H44 M36 42.5 H44" stroke-width="4.5" />
  {:else if zeichen === 'ranking_bars'}
    <!-- The house icon ranking-bars, verbatim on its own 64 grid: a baseline
         and three bars of falling height. The overview of the servers wears
         it. -->
    <path d="M9 55 H55" stroke-width="4.5" />
    <path d="M17 55 V19 M32 55 V29 M47 55 V39" stroke-width="5" />
  {:else if zeichen === 'wolke'}
    <path d="M6.3 17.5 h10.9 a3.3 3.3 0 0 0 .4-6.6 A5 5 0 0 0 7.9 9.6 A3.7 3.7 0 0 0 6.3 17.5 Z" />
  {:else if zeichen === 'buch'}
    <path d="M12 6.6 C9.5 5.1 6 5.1 3.6 5.9 V18.2 C6 17.4 9.5 17.4 12 18.9 C14.5 17.4 18 17.4 20.4 18.2 V5.9 C18 5.1 14.5 5.1 12 6.6 Z" />
    <path d="M12 6.6 V18.9" />
  {:else if zeichen === 'sprache'}
    <path d="M20 5.5 H4 V15.5 H8 V19 L12.5 15.5 H20 Z" />
  {:else if zeichen === 'keyboard'}
    <!-- The keyboard, for the shortcuts: `zeichen/keyboard.svg` of the
         catalogue, path for path. -->
    <rect x="6" y="17" width="52" height="30" rx="6" stroke-width="5" />
    <path d="M17 27 h0 M27 27 h0 M37 27 h0 M47 27 h0" stroke-width="5" />
    <path d="M21 37 H43" stroke-width="4.5" />
  {:else if zeichen === 'microphone'}
    <!-- The microphone: capsule, arc, foot, the same catalogue drawing the
         microphone button (Mikrofonknopf.svelte) draws with its breathing
         rings around it. -->
    <path d="M32 9 a8 8 0 0 1 8 8 V29 a8 8 0 0 1 -16 0 V17 a8 8 0 0 1 8 -8 Z" stroke-width="5" />
    <path d="M15 29 a17 17 0 0 0 34 0" stroke-width="5" />
    <path d="M32 46 V56" stroke-width="5" />
  {:else if zeichen === 'glocke'}
    <!-- The bell: what the program is allowed to say, and how loudly. A
         dome on a rim with the clapper under it — the plain "it will let
         you know" mark, drawn in the same stroke as its neighbours. -->
    <path d="M6.2 17 h11.6 l-1.6-2.2 V10.6 a4.2 4.2 0 0 0-8.4 0 v4.2 Z" />
    <path d="M10.4 19.6 a1.9 1.9 0 0 0 3.2 0" />
  {:else if zeichen === 'erscheinung'}
    <circle cx="12" cy="12" r="4.2" />
    <path d="M12 3.5v1.8 M12 18.7v1.8 M3.5 12h1.8 M18.7 12h1.8 M6 6l1.3 1.3 M16.7 16.7 18 18 M18 6l-1.3 1.3 M7.3 16.7 6 18" />
  {:else if zeichen === 'feder'}
    <path d="M4 20 l3.5-1 L19 7.5 a1.75 1.75 0 0 0-2.5-2.5 L5 16.5 Z" />
    <path d="M14 6.5 l3.5 3.5" />
  {:else if zeichen === 'person'}
    <circle cx="12" cy="8" r="3.6" />
    <path d="M5.5 19.5 a6.5 6.5 0 0 1 13 0" />
  {:else if zeichen === 'paket'}
    <path d="M12 3 L20.5 7.5 L12 12 L3.5 7.5 Z" />
    <path d="M3.5 7.5 V16 L12 20.5 L20.5 16 V7.5" />
    <path d="M12 12 V20.5" />
  {:else if zeichen === 'schluessel'}
    <circle cx="8.5" cy="8.5" r="3.8" />
    <path d="M11.5 11.5 19.5 19.5 M16.5 16.5 19 14 M14 14 l2.5-2.5" />
  {:else if zeichen === 'schloss_offen'}
    <!-- The shackle stands open rather than snapped shut — meant for the
         one place a mode is running with nobody asked first, and nowhere
         else. -->
    <rect x="5" y="11" width="14" height="9.5" rx="2.4" />
    <path d="M8.2 11 V7.6 a3.8 3.8 0 0 1 7.2-1.4" />
  {:else if zeichen === 'dokument'}
    <path d="M6 3.5 h8 l4 4 V20.5 H6 Z" />
    <path d="M14 3.5 V7.5 h4" />
  {:else if zeichen === 'dokument_pfeil'}
    <path d="M6 3.5 h8 l4 4 V20.5 H6 Z" />
    <path d="M14 3.5 V7.5 h4" />
    <path d="M10 12.5 l2.2 2.2-2.2 2.2" />
  {:else if zeichen === 'dokument_zeilen'}
    <!-- The house icon dog-eared-page, verbatim: a page with a
         folded corner and two lines. It stands where nothing can be shown
         of a file — no picture, no preview; the caller picks its size like
         any other sign's. -->
    <path d="M16 8 H38 L48 18 V56 H16 Z" stroke-width="5" />
    <path d="M38 8 V18 H48" stroke-width="4.5" />
    <path d="M25 34 H39 M25 44 H39" stroke-width="4.5" />
  {:else if zeichen === 'ordner' || zeichen === 'folder_plus'}
    <path d="M3.75 18 V6 H9.75 L11.63 8.25 H18 V11.25" />
    <path d="M3.75 18 H16.5 L20.25 11.25 H7.5 Z" />
    {#if zeichen === 'folder_plus'}
      <!-- The plus at the top right, a little finer than the folder. -->
      <path d="M21 2.5v4M19 4.5h4" stroke-width="1.8" />
    {/if}
  {:else if zeichen === 'auskoppeln'}
    <!-- Pop out: a frame with an arrow breaking out of its top-right corner,
         the sign for the same thing shown large in a window of its own. -->
    <path d="M18 13 V19 a2 2 0 0 1-2 2 H5 a2 2 0 0 1-2-2 V8 a2 2 0 0 1 2-2 H11" />
    <path d="M14 4 H20 V10" />
    <path d="M20 4 L10.5 13.5" />
  {:else if zeichen === 'bild'}
    <rect x="3" y="4" width="18" height="16" rx="2" />
    <circle cx="8.5" cy="9.5" r="1.6" />
    <path d="M4 17l4.5-5 3.5 4 3-2.5L20 17" />
  {:else if zeichen === 'einbettung'}
    <!-- The web first, the points on top of it: the lines carry less weight
         than what they connect, which is what makes it read as three things
         in a relation rather than as a triangle. -->
    <path d="M5.5 17.5 L12 5.5 L18.5 14.5 Z" stroke-width="1.4" />
    <path d="M5.5 17.5 h.01 M12 5.5 h.01 M18.5 14.5 h.01" stroke-width="4.2" />
  {:else if zeichen === 'stoppuhr'}
    <!-- A stopwatch, not a wall clock: the crown on top and the button on
         its shoulder say something is being STARTED, which is what a
         schedule does. Hands at an angle rather than square, so the two
         never merge into one stroke at 14 px. -->
    <circle cx="12" cy="14.5" r="6.8" />
    <path d="M9.6 4.8 h4.8" />
    <path d="M12 4.8 v2.9" />
    <path d="M17.3 9.6 l1.6 -1.6" />
    <path d="M12 14.5 V10.3" />
    <path d="M12 14.5 l2.4 1.5" />
  {:else if zeichen === 'stopwatch'}
    <!-- The catalogue's stopwatch (stopwatch.svg), verbatim on its own 64
         grid: the sign of the schedules. -->
    <circle cx="32" cy="39" r="18" stroke-width="5" />
    <path d="M26 13h12" stroke-width="5" />
    <path d="M32 13v8" stroke-width="5" />
    <path d="M46.5 25.5l4.5-4.5" stroke-width="5" />
    <path d="M32 39V27" stroke-width="5" />
    <path d="M32 39l6.5 4" stroke-width="5" />
  {:else if zeichen === 'clock'}
    <!-- The catalogue's clock with its four quarter marks (clock-marks.svg),
         verbatim on its own 64 grid: the sign of the time. -->
    <circle cx="32" cy="32" r="22" stroke-width="5" />
    <path d="M32 12v4" stroke-width="5" />
    <path d="M52 32h-4" stroke-width="5" />
    <path d="M32 52v-4" stroke-width="5" />
    <path d="M12 32h4" stroke-width="5" />
    <path d="M32 32V21" stroke-width="5" />
    <path d="M32 32h8" stroke-width="5" />
  {:else if zeichen === 'flag'}
    <!-- A pennant on its pole: the sign of a goal. -->
    <path d="M4 22V4a1 1 0 0 1 .4-.8A6 6 0 0 1 8 2c3 0 5 2 7.333 2q2 0 3.067-.8A1 1 0 0 1 20 4v10a1 1 0 0 1-.4.8A6 6 0 0 1 16 16c-3 0-5-2-8-2a6 6 0 0 0-4 1.528" />
  {:else if zeichen === 'speaker'}
    <!-- The catalogue's volume-2, verbatim: a loudspeaker and two sound
         waves. The sign of a sound test. -->
    <path d="M11 4.702a.705.705 0 0 0-1.203-.498L6.413 7.587A1.4 1.4 0 0 1 5.416 8H3a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h2.416a1.4 1.4 0 0 1 .997.413l3.383 3.384A.705.705 0 0 0 11 19.298z" />
    <path d="M16 9a5 5 0 0 1 0 6" />
    <path d="M19.364 18.364a9 9 0 0 0 0-12.728" />
  {:else if zeichen === 'blatt_zeilen'}
    <!-- The catalogue's sheet with lines (sheet-lines.svg), verbatim on its
         own 64 grid: the sign of a report. -->
    <path d="M16 8 H38 L48 18 V56 H16 Z" stroke-width="5" />
    <path d="M38 8 V18 H48" stroke-width="4.5" />
    <path d="M24 32 H40 M24 42 H40" stroke-width="4.5" />
  {:else if zeichen === 'palette'}
    <!-- The catalogue's colour palette (palette.svg), verbatim on its own
         64 grid: the sign of the appearance page. -->
    <path d="M32 56 A24 24 0 1 1 56 30 C56 36.5 51 41 44.5 41 L38.5 41 C34.8 41 32.5 43.5 32.5 46.3 C32.5 47.9 33.2 49.3 34.2 50.4 C35.8 52.4 34.6 56 32 56 Z" stroke-width="5" />
    <circle cx="22.5" cy="28" r="2.8" stroke-width="4.2" />
    <circle cx="33.5" cy="20" r="2.8" stroke-width="4.2" />
    <circle cx="44.5" cy="28" r="2.8" stroke-width="4.2" />
  {:else if zeichen === 'speicherriegel'}
    <!-- The catalogue's memory stick (memory-stick.svg), on its 24 grid. -->
    <rect x="2.8" y="6.6" width="18.4" height="10.2" rx="1.6" />
    <path d="M8 10 V13.4 M12 10 V13.4 M16 10 V13.4" stroke-width="1.7" />
    <path d="M7.5 16.8 V19.6 M16.5 16.8 V19.6" stroke-width="1.7" />
  {:else if zeichen === 'agent'}
    <!-- The agent server. Taken from the house catalogue
         (agent-mark) path for path, on its own
         64-grid — a head with a visor and two brackets facing each other,
         over the shoulders of the thing that carries it.

         The catalogue file is drawn at 3.6/3.2, and that is too thin here:
         a 64-grid weight lands on a 24-grid at x 0.375, so 3.6 reads as
         1.35 next to neighbours drawn at 1.8. The house weights for this
         mark are 5 and 4.5 — what Agentenmarke.svelte already carries in
         the work rail, where it sits right at 1.88 against those same
         neighbours. Same paths, house weights. -->
    <path d="M6 24 Q32 30 58 24" stroke-width="5" />
    <path d="M18 24 V15 Q18 8 32 8 Q46 8 46 15 V24" stroke-width="5" />
    <path d="M23 30 L27 33 L23 36" stroke-width="4.5" />
    <path d="M41 30 L37 33 L41 36" stroke-width="4.5" />
    <path d="M8 60 V51 Q8 42 19 39.5 L32 47 L45 39.5 Q56 42 56 51 V60" stroke-width="5" />
  {:else if zeichen === 'sprache_welle'}
    <!-- The speech server. Taken from the house catalogue
         (voicetype-wave) verbatim, on its own
         64-grid: five bars of a level meter, tallest in the middle. -->
    <path d="M10 26 V38 M21 18 V46 M32 10 V54 M43 20 V44 M54 28 V36" stroke-width="5" />
  {:else if zeichen === 'netzwerk'}
    <!-- The house icon chip-with-network, verbatim on its own 64 grid: a
         chip with three nodes joined by lines. -->
    <rect x="12" y="12" width="40" height="40" rx="7" stroke-width="5" />
    <path d="M24 5 V12 M40 5 V12 M24 52 V59 M40 52 V59" stroke-width="4.5" />
    <circle cx="32" cy="24" r="3.5" stroke-width="4.5" />
    <circle cx="23" cy="40" r="3.5" stroke-width="4.5" />
    <circle cx="41" cy="40" r="3.5" stroke-width="4.5" />
    <path d="M30 27.5 L25 36.5 M34 27.5 L39 36.5 M26.5 40 H37.5" stroke-width="4.5" />
  {:else if zeichen === 'besen'}
    <!-- A broom, head at seven o'clock and canted rather than square to the
         handle — a tool caught mid-sweep, not standing at rest. -->
    <path d="M18 4 L9.5 13.5" />
    <path d="M9.5 13.5 L4.5 19.5 M9.5 13.5 L7 20.5 M9.5 13.5 L10 21 M9.5 13.5 L12.5 20" />
    <path d="M4.5 19.5 Q8 21.7 12.5 20" />
  {:else if zeichen === 'plus'}
    <path d="M12 5v14M5 12h14" />
  {:else if zeichen === 'plug'}
    <!-- The house icon plug, verbatim: coordinates and
         per-path stroke widths travel with the drawing, only the 24-grid
         everything else here sits on gives way to its own 0 0 64 64. -->
    <path d="M23 26 H41 V36 C41 42.5 37 46.5 32 46.5 C27 46.5 23 42.5 23 36 Z" stroke-width="5" />
    <path d="M27.5 26 V13 M36.5 26 V13" stroke-width="5" />
    <path d="M32 46.5 V56" stroke-width="4.5" />
  {:else if zeichen === 'archive'}
    <!-- The house icon drawer, verbatim on its own 64-grid. -->
    <path d="M14 11 H50 V31 H14 Z" stroke-width="5" />
    <path d="M7 37 H57 V53 H7 Z" stroke-width="5" />
    <path d="M27 45 H37" stroke-width="4.5" />
  {:else if zeichen === 'kreuz'}
    <!-- The signs the input bar's chips and menus share, each verbatim from
         the house icon set (cross, chevron-down, magnifier-small, check,
         pen), on the same 24-grid as everything above. -->
    <path d="M6 6l12 12M18 6L6 18" />
  {:else if zeichen === 'pfeil_unten'}
    <path d="M6 9l6 6 6-6" />
  {:else if zeichen === 'lupe'}
    <circle cx="11" cy="11" r="7" />
    <path d="M20 20l-3.5-3.5" />
  {:else if zeichen === 'haken'}
    <path d="M4 12.5 L9.5 18 L20 6.5" />
  {:else if zeichen === 'stift'}
    <path d="M17 3l4 4L8 20l-5 1 1-5L17 3z" />
  {:else if zeichen === 'sprechblase'}
    <path d="M14 12 H50 A8 8 0 0 1 58 20 V38 A8 8 0 0 1 50 46 H32 L20 56 V46 H14 A8 8 0 0 1 6 38 V20 A8 8 0 0 1 14 12 Z" stroke-width="5" />
  {:else if zeichen === 'speech_bubble_dots'}
    <!-- The house icon speech-bubble-dots, verbatim on its own 64 grid: the
         outline of the chat bubble and three dots in it. -->
    <path d="M14 12 H50 A8 8 0 0 1 58 20 V38 A8 8 0 0 1 50 46 H32 L20 56 V46 H14 A8 8 0 0 1 6 38 V20 A8 8 0 0 1 14 12 Z" stroke-width="5" />
    <circle cx="18" cy="29" r="2.75" fill="currentColor" stroke="none" />
    <circle cx="32" cy="29" r="2.75" fill="currentColor" stroke="none" />
    <circle cx="46" cy="29" r="2.75" fill="currentColor" stroke="none" />
  {:else if zeichen === 'puzzle'}
    <path d="M14 24 H24 C21.5 20 23.5 14 29 14 C34.5 14 36.5 20 34 24 H44 V34 C48 31.5 54 33.5 54 39 C54 44.5 48 46.5 44 44 V54 H14 Z" stroke-width="5" />
  {:else if zeichen === 'download'}
    <path d="M12 4 V15" />
    <path d="M7 11 L12 16 L17 11" />
    <path d="M4 20 H20" />
  {:else if zeichen === 'neu_laden'}
    <!-- The circular arrow of the house: an arc running clockwise whose tip
         stands at its end, as on every other sign of this 24 grid (stroke 2,
         round ends and corners). -->
    <path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8" />
    <path d="M21 3v5h-5" />
  {:else if zeichen === 'clapperboard'}
    <!-- The house icon clapperboard, verbatim with its own stroke widths:
         the board and the raised clapper with its stripes. -->
    <rect x="5.89" y="13.04" width="14" height="9.6" rx="1.6" />
    <path d="M5.89 13.04 L15.79 3.14 L14.02 1.37 L4.12 11.27 Z" stroke-width="1.33" />
    <path d="M7.87 11.06 L6.10 9.29" stroke-width="1.33" />
    <path d="M9.85 9.08 L8.08 7.31" stroke-width="1.33" />
    <path d="M11.83 7.10 L10.06 5.33" stroke-width="1.33" />
    <path d="M13.81 5.12 L12.04 3.35" stroke-width="1.33" />
  {:else if zeichen === 'ecken'}
    <!-- The house icon corners, verbatim with its own stroke width. -->
    <path d="M10 4 H4 V10" stroke-width="2.5" />
    <path d="M14 20 H20 V14" stroke-width="2.5" />
  {:else if zeichen === 'kamera'}
    <path d="M4 8h3l2-3h6l2 3h3a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1Z" />
    <circle cx="12" cy="13.5" r="3.5" />
  {:else if zeichen === 'neu'}
    <path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z" />
  {:else if zeichen === 'schild'}
    <path d="M12 3 5 6v6c0 4.5 3 7.5 7 9 4-1.5 7-4.5 7-9V6Z" />
  {:else if zeichen === 'hilfe'}
    <!-- A question mark: the manual, the place a question about a setting
         leads to. -->
    <path d="M9.2 9a2.8 2.8 0 1 1 4 2.55c-.9.42-1.2 1.05-1.2 2.05v.4" />
    <path d="M12 17.6 V17.7" />
  {:else if zeichen === 'play'}
    <!-- The house icon play, verbatim. -->
    <path d="M8.5 6 L18.5 12 L8.5 18 Z" stroke-width="2.2" />
  {:else if zeichen === 'stop'}
    <!-- The house icon stop, verbatim. -->
    <rect x="6.5" y="6.5" width="11" height="11" rx="2" stroke-width="2.2" />
  {:else if zeichen === 'trash'}
    <!-- The house icon trash, verbatim. -->
    <path d="M3 6h18" />
    <path d="M8 6V4h8v2" />
    <path d="M6 6l1 14h10l1-14" />
  {:else if zeichen === 'info'}
    <!-- The house icon info-circle, with the letter i where the catalogue
         has an exclamation mark: the sign says "an explanation", not "a
         warning". -->
    <circle cx="12" cy="12" r="9" />
    <path d="M12 11v5M12 8h.01" />
  {:else if zeichen === 'chevron_right'}
    <path d="M9 6l6 6-6 6" stroke-width="2.5" />
  {:else if zeichen === 'chevron_left'}
    <!-- The house icon chevron-left, verbatim. -->
    <path d="M15 5 8 12l7 7" stroke-width="2.2" />
  {:else if zeichen === 'gear'}
    <!-- The cog of the settings, drawn on the 24 grid. -->
    <path d="M9.671 4.136a2.34 2.34 0 0 1 4.659 0 2.34 2.34 0 0 0 3.319 1.915 2.34 2.34 0 0 1 2.33 4.033 2.34 2.34 0 0 0 0 3.831 2.34 2.34 0 0 1-2.33 4.033 2.34 2.34 0 0 0-3.319 1.915 2.34 2.34 0 0 1-4.659 0 2.34 2.34 0 0 0-3.32-1.915 2.34 2.34 0 0 1-2.33-4.033 2.34 2.34 0 0 0 0-3.831A2.34 2.34 0 0 1 6.35 6.051a2.34 2.34 0 0 0 3.319-1.915" />
    <circle cx="12" cy="12" r="3" />
  {:else if zeichen === 'chip_bolt'}
    <!-- The house icon chip-with-bolt, verbatim on its own 64 grid. -->
    <rect x="14" y="14" width="36" height="36" rx="7" stroke-width="5" />
    <path d="M24 6 V14 M40 6 V14 M24 50 V58 M40 50 V58 M6 24 H14 M6 40 H14 M50 24 H58 M50 40 H58" stroke-width="4.5" />
    <path d="M35 21 L27 33 H37 L29 43" stroke-width="4.5" />
  {:else if zeichen === 'branch'}
    <!-- The house icon branch, verbatim on its own 64 grid. -->
    <path d="M20 15 V49" stroke-width="5" />
    <path d="M20 32 H33 C39 32 44 27 44 21" stroke-width="4.5" />
    <circle cx="44" cy="16" r="4.5" stroke-width="4.5" />
  {:else if zeichen === 'save'}
    <path d="M15.2 3a2 2 0 0 1 1.4.6l3.8 3.8a2 2 0 0 1 .6 1.4V19a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z" />
    <path d="M17 21v-7a1 1 0 0 0-1-1H8a1 1 0 0 0-1 1v7" />
    <path d="M7 3v4a1 1 0 0 0 1 1h7" />
  {:else if zeichen === 'refresh'}
    <path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8" />
    <path d="M21 3v5h-5" />
    <path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16" />
    <path d="M8 16H3v5" />
  {:else if zeichen === 'ellipsis'}
    <circle cx="12" cy="12" r="1" />
    <circle cx="19" cy="12" r="1" />
    <circle cx="5" cy="12" r="1" />
  {:else if zeichen === 'settings_two'}
    <path d="M20 7h-9" />
    <path d="M14 17H5" />
    <circle cx="17" cy="17" r="3" />
    <circle cx="7" cy="7" r="3" />
  {:else if zeichen === 'shrink'}
    <path d="m15 15 6 6m-6-6v4.8m0-4.8h4.8" />
    <path d="M9 19.8V15m0 0H4.2M9 15l-6 6" />
    <path d="M15 4.2V9m0 0h4.8M15 9l6-6" />
    <path d="M9 4.2V9m0 0H4.2M9 9 3 3" />
  {:else if zeichen === 'update_available'}
    <path d="M12 2a10 10 0 0 1 7.38 16.75" />
    <path d="m16 12-4-4-4 4" />
    <path d="M12 16V8" />
    <path d="M2.5 8.875a10 10 0 0 0-.5 3" />
    <path d="M2.83 16a10 10 0 0 0 2.43 3.4" />
    <path d="M4.636 5.235a10 10 0 0 1 .891-.857" />
    <path d="M8.644 21.42a10 10 0 0 0 7.631-.38" />
  {/if}
</svg>

<style>
  svg {
    flex: none;
    display: block;
  }
</style>
