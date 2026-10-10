<script>
  /* start_job's confirmation window — the task, EDITABLE, before the run.

     The model wrote the task out of a half-sentence; here it is read and
     straightened BEFORE twenty minutes burn on it. What is confirmed is
     what runs — the edited text travels back as the answer. Closing the
     window is a no: nothing starts unconfirmed. */
  import Auftragfenster from './Auftragfenster.svelte'
  import { api } from '../lib/api.js'
  import { t } from '../lib/texte.svelte.js'
  import { zustand, jobfrageBeantworten } from '../lib/zustand.svelte.js'
  import { untrack } from 'svelte'

  let offen = $state(false)
  let text = $state('')
  /* What has been typed, kept per question rather than as one string.

     The window belongs to whichever chat is on screen, so switching chats
     takes the question away and brings it back — and one string would be
     written over by whichever question came into view last. That is exactly
     how a straightened task used to be lost: leave the chat, come back, and
     the model's own wording stood there again as though nothing had been
     touched. Twenty minutes of a run hang off this text.

     Keyed by the call id, so two chats can each hold a question with its own
     edit, and neither reaches into the other. */
  let entwuerfe = $state({})
  /* Which question the field currently holds. Only a DIFFERENT one refills
     it — the same question coming back into view must not. */
  let textFuer = $state(null)

  /* The job confirmation for the chat on screen, or undefined. `jobfrage`
     is a map keyed by chat id now — the window belongs to one chat, the
     same way the question box above the input bar does. */
  const frage = $derived(zustand.jobfrage[zustand.aktiverChat])

  /* Which tools this agent may use. The question names the agent, the
     agent's own entry names its tools — `null` there means every approved
     one, and that is passed on unchanged (Auftragfenster.svelte). Loaded
     while the window is open: an unasked question needs no list. */
  let agenten = $state([])
  $effect(() => {
    if (!frage) return
    api.agenten()
      .then((liste) => (agenten = liste ?? []))
      .catch(() => (agenten = []))
  })
  /* The agent's entry first, its tools second — the two questions are not
     the same one. A missing ENTRY means the list has not arrived yet (or the
     question is already answered and `frage` is gone); a missing `tools:`
     inside an entry means every approved tool. Read as one, the row showed
     the full list of tools for as long as /agents took to answer, and for
     good if it failed. */
  const eintrag = $derived(agenten.find((agent) => agent.name === frage?.agent))
  const werkzeugnamen = $derived(eintrag ? eintrag.tools ?? null : [])

  $effect(() => {
    if (!frage) {
      offen = false
      return
    }
    offen = true
    if (textFuer !== frage.aufrufId) {
      /* Untracked on purpose: this reads the drafts to fill the field, and
         the field's own writing fills the drafts. Tracked, the two would
         chase each other. */
      text = untrack(() => entwuerfe[frage.aufrufId]) ?? frage.task
      textFuer = frage.aufrufId
    }
  })

  /* Every keystroke into the draft of the question it belongs to. The refill
     above reads this map untracked, so the two do not chase each other. */
  $effect(() => {
    const jetzt = text
    const fuer = textFuer
    if (fuer) entwuerfe[fuer] = jetzt
  })

  function vergessen() {
    /* Answered means gone: the question does not come back, and its draft
       has nothing left to belong to. */
    if (textFuer) delete entwuerfe[textFuer]
    textFuer = null
  }

  /* The window's own X and Escape land here: closed without a start is a
     no, and the model is told so. */
  $effect(() => {
    if (!offen && frage) jobfrageBeantworten(false)
  })

  function starten() {
    if (!text.trim()) return
    const fertig = text.trim()
    vergessen()
    jobfrageBeantworten(true, fertig)
  }

  function abbrechen() {
    vergessen()
    jobfrageBeantworten(false)
  }
</script>

<Auftragfenster
  bind:offen
  titel={t('jobs.bestaetigen_titel')}
  agent={frage?.agent ?? ''}
  {werkzeugnamen}
  hinweis={t('jobs.bestaetigen_hinweis')}
  bind:text
  feldbeschriftung={t('jobs.bestaetigen_titel')}
  startbar={Boolean(text.trim())}
  aufStarten={starten}
  aufAbbrechen={abbrechen}
/>
