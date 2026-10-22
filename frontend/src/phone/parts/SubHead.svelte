<script>
  /* An inner page's name and way back — a list opens a server, a provider,
     a model. It draws nothing: the head of the whole page says it
     (`../head.svelte.js`, `../PageFrame.svelte`), so there is one head and
     one way back at a time. A page that wants a word instead of the arrow
     (`backText`) or a button at the right end (`right`) says so here, and the
     head draws them. */
  import { headPush } from '../head.svelte.js'

  let { title, onback, backText = '', right = null } = $props()

  const entry = $state({ title: '', onback: null, backText: '', right: null })
  $effect.pre(() => {
    entry.title = title
    entry.onback = onback
    entry.backText = backText
    entry.right = right
  })
  $effect.pre(() => headPush(entry))
</script>
