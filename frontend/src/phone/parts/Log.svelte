<script>
  /* A server's protocol, newest line at the foot. It rolls inside its own
     frame and sticks to the foot while it is there — a person who scrolled
     up to read is left where they are. A button at its corner opens it
     large, over the whole page, and the large one is fed with the lines
     that come in. */
  import { tick } from 'svelte'
  import { t } from '../../lib/texte.svelte.js'
  import Hauszeichen from '../../teile/Hauszeichen.svelte'
  import { oeffneProtokoll, protokollOffen, setzeProtokollZeilen } from '../../lib/protokollfenster.svelte.js'

  let { text = '' } = $props()
  let box = $state(null)
  let atFoot = true

  $effect(() => {
    void text
    if (!box || !atFoot) return
    tick().then(() => {
      if (box) box.scrollTop = box.scrollHeight
    })
  })

  /* The large window shows what this log holds, and goes on showing it —
     only the log that opened it feeds it. */
  let opened = false
  $effect(() => {
    if (!protokollOffen()) opened = false
    else if (opened) setzeProtokollZeilen(text ? text.split('\n') : [])
  })

  function enlarge() {
    opened = true
    oeffneProtokoll(t('modell.protokoll_titel'))
    setzeProtokollZeilen(text ? text.split('\n') : [])
  }

  function watch() {
    atFoot = box.scrollHeight - box.scrollTop - box.clientHeight < 24
  }
</script>

<div class="frame">
  <div class="log" bind:this={box} onscroll={watch} role="log" aria-label={t('modell.protokoll')}>
    {#if text}<pre>{text}</pre>{:else}<span class="empty">-</span>{/if}
  </div>
  <button class="big" onclick={enlarge} title={t('modell.protokoll_vergroessern')}
          aria-label={t('modell.protokoll_vergroessern')}>
    <Hauszeichen zeichen="auskoppeln" groesse="klein" />
  </button>
</div>

<style>
  .frame {
    position: relative;
  }
  .big {
    position: absolute;
    top: 8px;
    right: 18px;
    display: grid;
    place-items: center;
    width: 32px;
    height: 32px;
    border: none;
    border-radius: 9px;
    background: color-mix(in srgb, var(--bg) 70%, transparent);
    color: var(--text-leise);
  }
  .log {
    max-height: 260px;
    overflow: auto;
    margin: 4px 10px;
    padding: 10px 12px;
    border-radius: 9px;
    background: var(--kachel-eingabe);
    box-shadow: inset 0 0 0 1px var(--linie);
    font: 400 11px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace;
    color: var(--text-leise);
  }
  pre {
    margin: 0;
    white-space: pre-wrap;
    word-break: break-word;
    font: inherit;
  }
  .empty {
    color: var(--text-still);
  }
</style>
