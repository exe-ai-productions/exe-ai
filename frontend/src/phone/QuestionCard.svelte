<script>
  /* The one card for what waits on the person, on the phone: a tool asking
     for permission, the model putting a question of its own, or a helper
     agent asking one. It stands at the end of the history, where the next
     line would come: who asks, the question, the answers as rows, a field
     for an answer in the person's own words, and a quiet "later" that takes
     the card away and leaves a chip over the bar to bring it back.

     Which question stands, and the ways an answer leaves, are the shared
     ones (lib/fragekarte.svelte.js). */
  import { untrack } from 'svelte'
  import Hauszeichen from '../teile/Hauszeichen.svelte'
  import { t } from '../lib/texte.svelte.js'
  import { keepOwnDraft, ownDraft, questionKey } from '../lib/questionbox.svelte.js'
  import { mainArgument } from '../lib/werkzeughistorie.js'
  import { markPath, plainHtml, reasonLine } from '../lib/markpath.js'

  let { questions } = $props()

  const standing = $derived(questions.standing)
  const kind = $derived(standing.kind)
  const question = $derived(standing.question)

  let own = $state('')
  let argumentsOpen = $state(false)

  /* A question that follows another in the same card starts clean; the
     words typed for one come back with it after "later". */
  const identity = $derived(questionKey({ kind, question }))
  let shownIdentity
  $effect.pre(() => {
    if (identity === shownIdentity) return
    shownIdentity = identity
    untrack(() => {
      argumentsOpen = false
      own = ownDraft(question.chatId, { kind, question }) || question.zurueck || ''
    })
  })
  function keepDraft() {
    keepOwnDraft(question.chatId, { kind, question }, own)
  }

  /* A question that comes back after its answer could not be sent can
     arrive while the same card still stands: the identity above does not
     change, and the words would be lost. They are taken here as well — into
     an empty field only, so what was typed since stays. */
  let takenBack = null
  $effect.pre(() => {
    const back = question.zurueck
    if (!back || takenBack === question) return
    takenBack = question
    untrack(() => {
      if (!own.trim()) {
        own = back
        keepDraft()
      }
    })
  })

  const rows = $derived(
    kind === 'tool'
      ? [
          { label: t('werkzeug.just_this_once'), pick: () => questions.answerTool(true) },
          { label: t('werkzeug.yes_dont_ask_again'), pick: () => questions.answerTool(true, true) },
          { label: t('app.nein'), pick: () => questions.answerTool(false) },
        ]
      : (question.optionen ?? []).map((option) => ({
          label: option.label,
          pick: () => questions.answerAsk(option.label),
        })),
  )
  const pair = $derived(
    kind === 'tool'
      ? Object.entries(question.argumente ?? {}).map(([name, value]) => [
          name,
          typeof value === 'string' ? value : JSON.stringify(value),
        ])
      : [],
  )
  /* What the decision rests on, always in view: the command for a shell
     call, with its dollar sign; for any other call the argument it is about
     (a path, a query, an address), plainly — a file's body or a path is not
     a command and must not look like one. */
  const command = $derived(
    kind === 'tool' && typeof question.argumente?.command === 'string'
      ? question.argumente.command
      : '',
  )
  const headline = $derived(
    command || (kind === 'tool' ? mainArgument(question.argumente) || (pair[0]?.[1] ?? '') : ''),
  )
  /* The line with the place the reason points at marked in it, and the
     reason as a sentence — the place after a colon where the line does not
     carry it as it stands. */
  const shown = $derived(
    markPath(
      plainHtml(headline),
      headline,
      kind === 'tool' && question.grund ? question.grundWert || '' : '',
    ),
  )
  const warning = $derived(reasonLine(question.grund, question.grundWert || '', shown.count))
  const placeholder = $derived(
    t(kind === 'tool' ? 'werkzeug.no_with_words' : 'benutzerfrage.eigene_platzhalter'),
  )

  function sendOwn() {
    const words = own.trim()
    if (!words) return
    own = ''
    keepDraft()
    if (kind === 'tool') questions.answerTool(false, false, words)
    else questions.answerAsk(words)
  }
</script>

<div class="card" role="alertdialog"
         aria-label={kind === 'tool' ? t('werkzeug.bestaetigen') : question.frage}>
  <p class="asker">
    <b>{kind === 'agent' ? question.agentName : questions.modelName}</b>
    {#if kind === 'tool'}
      <span>{t('werkzeug.wants_to_run_before')}<b class="tool">{question.name}</b>{t('werkzeug.wants_to_run_after')}</span>
    {:else}
      <span>{t('werkzeuge.fragt')}</span>
    {/if}
  </p>
  <h2 class="title">{kind === 'tool' ? t('werkzeug.permission_question') : question.frage}</h2>

  {#if kind === 'tool' && (headline || question.grund)}
    <div class="details">
      {#if headline}
        {#if pair.length > 1}
          <button class="command" aria-expanded={argumentsOpen}
                  onclick={() => (argumentsOpen = !argumentsOpen)}>
            {#if command}<span class="quiet">$</span>{' '}{/if}{@html shown.html}
            <span class="unfold" class:open={argumentsOpen}>
              <Hauszeichen zeichen="pfeil_unten" groesse={11} strich={2.6} />
            </span>
          </button>
        {:else}
          <div class="command">{#if command}<span class="quiet">$</span>{' '}{/if}{@html shown.html}</div>
        {/if}
      {/if}
      {#if argumentsOpen}
        <dl class="arguments">
          {#each pair as [name, value] (name)}
            <dt>{name}</dt>
            <dd>{value}</dd>
          {/each}
        </dl>
      {/if}
      {#if question.grund}
        <p class="reason">
          <svg width="13" height="13" viewBox="0 0 64 64" fill="none" stroke="currentColor"
               stroke-width="5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M32 11 L56 52 H8 Z" />
            <path d="M32 28 V38" stroke-width="4.5" />
            <path d="M32 44.5 V45" />
          </svg>
          <span>{warning}</span>
        </p>
      {/if}
    </div>
  {/if}

  <div class="answers">
    {#each rows as row}
      <button class="answer" onclick={row.pick}>{row.label}</button>
    {/each}
  </div>

  <div class="own">
    <input bind:value={own} {placeholder} aria-label={placeholder} oninput={keepDraft}
           enterkeyhint="send" onkeydown={(event) => event.key === 'Enter' && sendOwn()} />
    <button class="send" onclick={sendOwn} disabled={!own.trim()}
            aria-label={t('benutzerfrage.eigene_senden')}>
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
           stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
        <path d="M12 19V5M5 12l7-7 7 7" />
      </svg>
    </button>
  </div>

  <button class="later" onclick={questions.later}>{t('benutzerfrage.later')}</button>
</div>

<style>
  .card {
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 14px;
    border-radius: 9px;
    background: var(--glass-dropdown);
    box-shadow: 0 0 0 1px var(--glass-button-edge);
    color: var(--text);
  }
  .asker {
    margin: 0;
    color: var(--text-leise);
    font: var(--schrift-hinweis) var(--schrift);
  }
  .asker b {
    color: var(--text);
    font-weight: 600;
  }
  .asker .tool {
    font-family: var(--schrift-fest);
  }
  .title {
    margin: 0;
    font: 600 16px/1.35 var(--schrift);
  }
  .details {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .command {
    display: block;
    width: 100%;
    margin: 0;
    padding: 8px 10px;
    border: none;
    border-radius: 9px;
    background: var(--bg-hoch);
    color: var(--text);
    font: 13px/1.4 var(--schrift-fest);
    text-align: left;
    overflow-wrap: anywhere;
  }
  .quiet {
    color: var(--text-still);
  }
  .unfold {
    display: inline-block;
    margin-left: 4px;
    transition: transform 0.18s ease;
  }
  .unfold.open {
    transform: rotate(180deg);
  }
  .arguments {
    margin: 0;
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 2px 10px;
    font: 12px/1.4 var(--schrift-fest);
    color: var(--text-leise);
  }
  .arguments dt {
    color: var(--text-still);
  }
  .arguments dd {
    margin: 0;
    overflow-wrap: anywhere;
  }
  /* The place the reason points at, inside the command: a soft marker in the
     waiting colour over the whole value; the text under it stays. */
  .command :global(mark.outside) {
    padding: 1px 0;
    border-radius: 3px;
    background: color-mix(in srgb, var(--gelb) 22%, transparent);
    color: inherit;
  }
  /* Reaching beyond what was shared: one line under the command, no box, in
     the command's own face and the quiet colour, indented to stand under the
     dollar sign; the sign in front of it is the waiting colour. */
  .reason {
    display: flex;
    align-items: flex-start;
    gap: 7px;
    margin: 0;
    padding: 0 10px;
    color: var(--text-still);
    font: 12px/18px var(--schrift-fest);
  }
  .reason svg {
    flex: none;
    margin-top: 2.5px;
    color: var(--gelb);
  }
  .reason span {
    min-width: 0;
    overflow-wrap: anywhere;
  }
  .answers {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .answer {
    padding: 12px 14px;
    border: none;
    border-radius: 9px;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text);
    font: 500 15px/1.3 var(--schrift);
    text-align: left;
  }
  .answer:active {
    background: var(--bg-hoch);
  }
  .own {
    display: flex;
    gap: 6px;
  }
  .own input {
    flex: 1;
    min-width: 0;
    padding: 10px 12px;
    border: none;
    border-radius: 9px;
    outline: none;
    background: var(--bg-hoch);
    color: var(--text);
    /* 16 px: a smaller field makes the page zoom when it takes the focus. */
    font: 16px var(--schrift);
  }
  .send {
    flex: none;
    width: 40px;
    border: none;
    border-radius: 9px;
    background: var(--text);
    color: var(--bg);
    display: grid;
    place-items: center;
  }
  .send:disabled {
    background: var(--glass-button);
    color: var(--text-still);
  }
  .later {
    align-self: flex-start;
    padding: 4px 0;
    border: none;
    background: none;
    color: var(--text-still);
    font: var(--schrift-hinweis) var(--schrift);
  }
</style>
