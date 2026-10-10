<script>
  /* The signs for the menus of the window row: local, cloud and the
     catalogue; the settings wear their sun-wheel beside them, and the
     picture studio its brush at the row's end. They open a
     page instead of a panel beside the chat, which is why they are not
     modules — but they are reached from the same rail, so they are drawn to
     the same measure the module signs are: the 64 grid, 5 for the main
     stroke and 4.5 for the secondary one, round caps, colour inherited.

     All three lay in the house catalogue without an office.

     One file rather than inline blocks in the rail: the rail says
     WHICH sign belongs where, this says what each one looks like. */
  let { name, groesse = 23 } = $props()
</script>

<svg viewBox="0 0 64 64" width={groesse} height={groesse}
     fill="none" stroke="currentColor"
     stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
  {#if name === 'chats'}
    <!-- The house's speech bubble: the way back to the chat list. -->
    <path d="M14 12 H50 A8 8 0 0 1 58 20 V38 A8 8 0 0 1 50 46 H32 L20 56 V46 H14 A8 8 0 0 1 6 38 V20 A8 8 0 0 1 14 12 Z"
          stroke-width="5" />
  {:else if name === 'lokal'}
    <!-- The stack of servers: what the models run on. Lay in the
         catalogue as "Server-Stapel", drawn but unassigned. -->
    <rect x="12" y="13" width="40" height="17" rx="5.5" stroke-width="5" />
    <rect x="12" y="34" width="40" height="17" rx="5.5" stroke-width="5" />
    <circle cx="21" cy="21.5" r="1.4" stroke-width="4.2" />
    <circle cx="21" cy="42.5" r="1.4" stroke-width="4.2" />
    <path d="M36 21.5 H44 M36 42.5 H44" stroke-width="4.5" />
  {:else if name === 'cloud'}
    <!-- The cloud, whole, with a plus at its shoulder — the sign the rail
         wore before the two model pages were merged, and the one the page
         draft for the split carries. An arrow rising THROUGH the outline
         was drawn first and dropped: breaking the top for it costs a
         single-hump cloud its crown, so the shape stopped reading as a
         cloud, and the daylight either side of the shaft closed up at the
         size this actually renders at once the round caps were counted in.
         A plus beside the closed shape says the same thing and survives 23
         pixels.

         It is also the house's own phrasing for this: the working folder
         in the input row wears an open folder WITH A PLUS. One rule in two
         signs — a plus means something is added here. -->
    <path d="M11 52 A13 13 0 0 1 12 28 A16 16 0 0 1 42 31 A12 12 0 0 1 41 52 Z"
          stroke-width="5" />
    <path d="M50 12 V24 M44 18 H56" stroke-width="4.5" />
  {:else if name === 'studio'}
    <!-- The brush of the house catalogue ("brush.svg", the mask tools'
         brush), on its own 24 grid: scaled onto the 64 one, its strokes land
         on this rail's 5 and 4.5. The picture studio. -->
    <g transform="scale(2.6667)">
      <g transform="rotate(-135 12 12)">
        <path d="M12 9.77 L12 21.67" stroke-width="1.9" />
        <path d="M10.13 9.42 L13.87 9.42" stroke-width="1.9" />
        <path d="M12 2.15 C13.35 4.21, 14.05 5.67, 14.05 6.96 A2.05 2.05 0 1 1 9.95 6.96 C9.95 5.67, 10.65 4.21, 12 2.15 Z"
              stroke-width="1.7" stroke-linejoin="miter" />
      </g>
    </g>
  {:else if name === 'feinheiten'}
    <!-- The sliders of the house catalogue ("slider.svg"): the head of the
         studio's details in the right column. -->
    <path d="M12 18 H30 M46 18 H52" stroke-width="4.5" />
    <circle cx="38" cy="18" r="5.5" stroke-width="5" />
    <path d="M12 32 H16 M32 32 H52" stroke-width="4.5" />
    <circle cx="24" cy="32" r="5.5" stroke-width="5" />
    <path d="M12 46 H34 M50 46 H52" stroke-width="4.5" />
    <circle cx="42" cy="46" r="5.5" stroke-width="5" />
  {:else if name === 'katalog'}
    <!-- The catalogue card: a card with its lines of entry. Lay in the
         catalogue as "Katalogkarte", redrawn from its 100 grid onto the 64
         one every other sign in this rail uses. -->
    <rect x="13" y="15" width="38" height="34" rx="7" stroke-width="5" />
    <path d="M22 25 H42 M22 32 H42 M22 39 H33" stroke-width="4.5" />
  {/if}
</svg>

<style>
  svg {
    display: block;
    flex: none;
  }
</style>
