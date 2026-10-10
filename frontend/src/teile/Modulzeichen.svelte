<script>
  /* The module signs, drawn in one place.

     The strip and the rail's head both show them, and they have to be the
     same stroke: two copies of one drawing drift apart at the first change,
     and a head that shows a slightly different mark than the button beside
     it reads as two different things. */
  import Hauszeichen from './Hauszeichen.svelte'

  let { modul = 'terminal', groesse = 16 } = $props()
</script>

{#if modul === 'terminal'}
  <svg width={groesse} height={groesse} viewBox="0 0 24 24" fill="none" stroke="currentColor"
       stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m4 17 6-6-6-6" /><path d="M12 19h8" /></svg>
{:else if modul === 'cli'}
  <svg width={groesse} height={groesse} viewBox="0 0 24 24" fill="none" stroke="currentColor"
       stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="2" /><path d="m7 9 3 3-3 3" /></svg>
{:else if modul === 'vorschau'}
  <svg width={groesse} height={groesse} viewBox="0 0 24 24" fill="none" stroke="currentColor"
       stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9" /><path d="M3 12h18" /><path d="M12 3a15 15 0 0 1 0 18a15 15 0 0 1 0-18" /></svg>
{:else if modul === 'bilder'}
  <!-- The picture frame: a frame, a sun, a mountain — the plain "images" mark. -->
  <svg width={groesse} height={groesse} viewBox="0 0 24 24" fill="none" stroke="currentColor"
       stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="2" /><circle cx="8.5" cy="8.5" r="1.5" /><path d="m21 15-4.5-4.5L7 20" /></svg>
{:else if modul === 'docfolder'}
  <!-- The open folder — the house catalogue's own mark (Hauszeichen,
       `ordner`), the same the input bar's folder wears, without its plus.
       Asked for rather than drawn again: a hand-copied path keeps its old
       shape when the original is redrawn, and the mark then looks
       different here than beside the input field. Two points larger on
       purpose: the folder's drawing fills barely fourteen of its
       twenty-four units, the four marks beside it eighteen to twenty — at
       one number it reads smaller than they do. -->
  <Hauszeichen zeichen="ordner" groesse={groesse + 2} />
{:else if modul === 'cronjobs'}
  <!-- A stopwatch, not a wall clock: the crown on top and the button on
       its shoulder say something is being STARTED, which is what a
       schedule does. The house catalogue's own mark, asked for rather than
       drawn again. -->
  <Hauszeichen zeichen="stopwatch" {groesse} />
{:else}
  <svg width={groesse} height={groesse} viewBox="0 0 24 24" fill="none" stroke="currentColor"
       stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z" /></svg>
{/if}
