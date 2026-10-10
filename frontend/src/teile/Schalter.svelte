<script>
  /* The house's switch — one build, used everywhere.

     Two tones, and the difference matters: red says this is an
     intervention (suspending the system prompt), blue says something is
     switched on (a skill, a model in the quick picker). Whoever reaches for
     red should feel that something is being taken away.

     Its own component so the next switch is not drawn a second time with
     slightly different numbers. */
  let {
    an = false,
    /* 'eingriff' → red when on, 'vorliebe' → blue. */
    art = 'vorliebe',
    beschriftung = '',
    gesperrt = false,
    onschalten = null,
    /* So a `<label for="…">` elsewhere can point at this exact switch, the
       way every other field's own picker already lets its label do. */
    id = undefined,
  } = $props()
</script>

<button
  {id}
  class="schalter"
  class:eingriff={art === 'eingriff'}
  role="switch"
  aria-checked={an}
  aria-label={beschriftung}
  disabled={gesperrt}
  onclick={(e) => { e.stopPropagation(); onschalten?.(!an) }}
><i></i></button>

<style>
  .schalter {
    position: relative;
    width: 34px;
    height: 20px;
    flex: none;
    border: none;
    padding: 0;
    /* The one shape that stays round while everything else went to 9: a
       switch is a track with a knob sliding in it, and a track with corners
       reads as a box the knob happens to sit in. The knob is a circle, and
       the groove it runs in has to be its shape. */
    border-radius: 99px;
    /* Off, the track is glass with a fine edge; on, it fills (below). */
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    cursor: pointer;
    transition: background 0.2s cubic-bezier(0.2, 0.9, 0.3, 1);
  }
  .schalter i {
    position: absolute;
    top: 3px;
    left: 3px;
    width: 14px;
    height: 14px;
    border-radius: 50%;
    background: var(--text-still);
    transition: transform 0.2s cubic-bezier(0.2, 0.9, 0.3, 1);
  }
  /* On, the track carries the full colour of "switched on": a state is
     read off a filled track at a glance, off a tinted glass it is not. */
  .schalter[aria-checked='true'] {
    background: var(--blau);
    box-shadow: none;
  }
  /* Red is reserved for taking something away, not for taste. */
  .schalter.eingriff[aria-checked='true'] {
    background: var(--rot);
  }
  /* The knob on the colour is the ground of the look: opaque everywhere,
     light on the colour where the look is light and dark where it is dark.
     The raised ground would not do — a menu page turns it into glass, and a
     knob one can see through sinks into its track. */
  .schalter[aria-checked='true'] i {
    background: var(--bg);
    transform: translateX(14px);
  }
  .schalter:disabled {
    opacity: 0.4;
    cursor: default;
  }
</style>
