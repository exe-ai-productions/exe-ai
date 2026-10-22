<script>
  /* The house's switch — one build, used everywhere.

     White and grey, in every look: off, the track is the ink of the look at
     a sixth of its strength with a quiet knob at the left; on, the track is
     the ink itself and the knob takes the ground of the look. No blue and no
     red — an intervention (suspending the system prompt) looks like any
     other switch, and the word beside it says what it does. The state is
     read off the knob's side and the track's weight, never off a colour
     alone.

     Its own component so the next switch is not drawn a second time with
     slightly different numbers. */
  let {
    an = false,
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
    background: color-mix(in srgb, var(--text) 16%, transparent);
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
    background: var(--text-leise);
    transition: transform 0.2s cubic-bezier(0.2, 0.9, 0.3, 1), background 0.2s;
  }
  /* On, the track is the ink of the look and the knob its ground. */
  .schalter[aria-checked='true'] {
    background: var(--text);
  }
  .schalter[aria-checked='true'] i {
    background: var(--bg);
    transform: translateX(14px);
  }
  .schalter:disabled {
    opacity: 0.4;
    cursor: default;
  }
</style>
