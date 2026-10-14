<script>
  /* The one line with the newest thought under a running thinking head
     (Nachricht.svelte): the newest thought that is finished, kept for at
     least a second before the next one takes its place (lib/thoughtLine.js).
     It has its height before the first thought stands in it. */
  import { finishedThought, minimumDisplay } from '../lib/thoughtLine.js'

  let { text = '' } = $props()

  const MIN_MS = 1000
  let shown = $state('')
  const hold = minimumDisplay(MIN_MS, (value) => (shown = value))

  $effect(() => {
    hold.offer(finishedThought(text))
  })
  $effect(() => () => hold.dispose())
</script>

<div class="mitlesen">{shown}</div>

<style>
  .mitlesen {
    font-size: 12.5px;
    line-height: 20px;
    min-height: 20px;
    color: var(--text-still);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
</style>
