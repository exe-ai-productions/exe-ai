<script>
  /* The one card for everything that waits on the user: a tool asking for
     permission, the model asking a question of its own (ask_user), and an
     agent this chat started asking one of its own (kind `agent`). It stands
     in the middle of the chat column on a veil that blurs the history and
     the bar behind it, so a question is seen the moment it is asked: who
     asks, the question as a heading, its answers as cards, a field for an
     answer in the user's own words, and a quiet way to answer later —
     which takes the card away and leaves a chip in the bar to bring it
     back.

     Under the veil nothing else takes the pointer, so the card takes the
     focus when it appears — the card itself, with no answer chosen: an Enter
     then answers nothing, and neither does a digit, which may be the rest
     of a sentence that was being typed into the bar. The arrows walk the
     answers, Enter sends the chosen one and, once one is chosen, a digit
     sends the answer of that number; Tab stays in the card and Escape
     means later. */
  import Hauszeichen from './Hauszeichen.svelte'
  import { rollfade } from '../lib/rollfade.js'
  import { hervorheben, maskieren } from '../lib/einfaerben.js'
  import { t } from '../lib/texte.svelte.js'
  import { untrack } from 'svelte'
  import { fade } from 'svelte/transition'
  import { keepOwnDraft, ownDraft, questionKey } from '../lib/questionbox.svelte.js'
  import { eineSeiteOffen } from '../lib/zustand.svelte.js'
  import { studioSichtbar } from '../lib/studio.svelte.js'

  /* `answerTool(allowed, always, words)` and `answerAsk(text)` are the two
     ways an answer leaves — an agent's question answers the way the model's
     does; `onLater` takes the card away. `position` and `total` are the
     place of this question in the row of everything waiting in the chat. */
  let { kind, question, position = 1, total = 1, modelName = '', answerTool, answerAsk, onLater } = $props()

  let box = $state(null)
  let ownField = $state(null)
  let rowButtons = $state([])
  let own = $state('')
  /* Which row holds the focus: -1 for none, the rows by index, and one past
     the last for the row of one's own words. It follows the focus and
     nothing else, so the highlighted row and the one Enter answers with are
     always the same. */
  let active = $state(-1)
  let argumentsOpen = $state(false)

  /* A question asked through ask_user follows its own permission in this
     very card — the two share one call. What the permission left behind
     (a chosen answer, unfolded arguments) does not carry over. The words
     typed for a question come back with it after "later". */
  const identity = $derived(questionKey({ kind, question }))
  let shownIdentity
  $effect.pre(() => {
    if (identity === shownIdentity) return
    shownIdentity = identity
    untrack(() => {
      active = -1
      argumentsOpen = false
      /* The words of an answer that did not arrive come back with the
         question (`zurueck`, lib/zustand.svelte.js); words kept for "later"
         come first. */
      own = ownDraft(question.chatId, { kind, question }) || question.zurueck || ''
    })
  })
  /* The focus comes to the card when it appears, and again when the next
     question takes its place. While a menu page or the picture studio
     covers the chat the card is out of sight and cannot hold it; it takes
     it when the cover lifts.

     It is taken from where nothing is lost by it: from nowhere, from the
     chat column itself (an answer of the question before, the bar under
     the veil) and from a button in one of the columns beside the chat.
     Everywhere else it stays — in a field somebody may be writing in, in
     a page shown inside the program, and in whatever lies above the page,
     a window with its own buttons: what is typed or confirmed there must
     not land on the card. */
  const inSight = $derived(!eineSeiteOffen() && !studioSichtbar())
  $effect(() => {
    if (!identity || !inSight) return
    untrack(() => {
      const held = document.activeElement
      const nowhere = !held || held === document.body
      const inChat = Boolean(box?.closest('main')?.contains(held))
      const besideChat =
        Boolean(held?.closest('aside, nav')) &&
        !held.closest('input, textarea, select, [contenteditable], [role=textbox], iframe')
      if (nowhere || inChat || besideChat) box?.focus({ preventScroll: true })
    })
  })
  function keepDraft() {
    keepOwnDraft(question.chatId, { kind, question }, own)
  }
  /* A question that comes back after its answer could not be sent can arrive
     while the card is still leaving: the same card then stays standing,
     the identity above does not change, and the words would be lost. They
     are taken here as well — into an empty field only, so what was typed
     since stays. */
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
          { label: t('werkzeug.just_this_once'), pick: () => answerTool(true) },
          { label: t('werkzeug.yes_dont_ask_again'), pick: () => answerTool(true, true) },
          { label: t('app.nein'), pick: () => answerTool(false) },
        ]
      : // An answer is its label and nothing under it.
        (question.optionen ?? []).map((option) => ({
          label: option.label,
          pick: () => answerAsk(option.label),
        })),
  )
  /* What stands in the pill over the heading: for a tool that this is a
     permission, for a question which one it is. */
  const pill = $derived.by(() => {
    // Several things waiting at once: one after the other.
    if (total > 1) return t('question_box.agent_position', { n: position, total })
    if (kind === 'tool') return t('werkzeug.permission_label')
    return question.nummer ? t('benutzerfrage.nummer', { zahl: question.nummer }) : ''
  })
  const ownPlaceholder = $derived(
    t(kind === 'tool' ? 'werkzeug.no_with_words' : 'benutzerfrage.eigene_platzhalter'),
  )

  /* A tool's arguments as pairs; strings raw, everything else as JSON. */
  const argumentPairs = $derived(
    kind === 'tool'
      ? Object.entries(question.argumente ?? {}).map(([name, value]) => [
          name,
          typeof value === 'string' ? value : JSON.stringify(value),
        ])
      : [],
  )
  /* What the decision rests on, always in view: the command for a shell
     call, otherwise the first argument, which says what the tool touches. */
  const command = $derived(
    kind === 'tool' ? String(question.argumente?.command ?? argumentPairs[0]?.[1] ?? '') : '',
  )
  const commandColoured = $derived(command ? hervorheben(command, 'bash') : '')
  /* The reason names a path, and a path is read letter by letter — so it
     stands in monospace inside the sentence. */
  const reasonText = $derived.by(() => {
    const sentence = maskieren(question.grund || '')
    const value = question.grundWert || ''
    if (!value) return sentence
    // A function, not a string: a `$` in the path must stay a dollar sign.
    return sentence.replace(maskieren(value), () => `<span class="path">${maskieren(value)}</span>`)
  })

  function sendOwn() {
    const words = own.trim()
    if (!words) return
    own = ''
    keepDraft()
    if (kind === 'tool') answerTool(false, false, words)
    else answerAsk(words)
  }

  function key(event) {
    const inOwn = event.target === ownField
    if (event.key === 'Escape') {
      event.preventDefault()
      event.stopPropagation()
      onLater()
      return
    }
    /* Tab stays in the card: past its last stop it comes round to the
       first, and back the other way. */
    if (event.key === 'Tab') {
      const stops = [...box.querySelectorAll('button:not(:disabled), input')]
      const edge = event.shiftKey ? stops[0] : stops.at(-1)
      const at = document.activeElement
      if (at === edge || (event.shiftKey && at === box)) {
        event.preventDefault()
        ;(event.shiftKey ? stops.at(-1) : stops[0])?.focus()
      }
      return
    }
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      const count = rows.length + 1
      const step = event.key === 'ArrowDown' ? 1 : -1
      const next = active < 0 ? (step > 0 ? 0 : count - 1) : (active + step + count) % count
      // The focus moves with it; set here as well, not only by the focus
      // event, so the count goes on from the answer just reached.
      if (next === rows.length) ownField?.focus()
      else rowButtons[next]?.focus()
      active = next
      return
    }
    /* Enter on a focused answer or button is that element's own click;
       only the own-answer field needs saying what Enter means there. */
    if (event.key === 'Enter' && inOwn) {
      // An input method still composing a word keeps its own Enter.
      if (event.isComposing) return
      event.preventDefault()
      sendOwn()
      return
    }
    /* A digit answers only while an answer holds the focus: on the bare
       card it may be a key meant for the bar the card just took the focus
       from. */
    if (!inOwn && active >= 0 && /^[1-9]$/.test(event.key)) {
      const row = rows[Number(event.key) - 1]
      if (row) {
        event.preventDefault()
        row.pick()
      }
    }
  }

  /* Leaving: the entrance run backwards, quicker. */
  function leave() {
    return {
      duration: 220,
      css: (t, u) => `opacity:${t}; transform: translateY(${14 * u}px) scale(${0.97 + 0.03 * t})`,
    }
  }

  /* The veil covers the chat column — its head, the history and the bar —
     while this card is written inside the bar, whose own layer ends below
     the head. So the veil hangs itself into the column, the last of its
     layers, and takes itself out again when it goes. */
  function intoColumn(node) {
    const column = node.closest('main')
    column?.appendChild(node)
    return {
      destroy() {
        if (node.parentNode === column) node.remove()
      },
    }
  }

  /* A click beside the card lands on the veil: it answers nothing, and the
     focus stays in the card — or comes to it. */
  function holdFocus(event) {
    if (event.target !== event.currentTarget) return
    event.preventDefault()
    if (!box?.contains(document.activeElement)) box?.focus({ preventScroll: true })
  }
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="veil" use:intoColumn onmousedown={holdFocus} out:fade={{ duration: 220 }}>
  <!-- svelte-ignore a11y_no_noninteractive_element_to_interactive_role -->
  <div
    class="card"
    bind:this={box}
    tabindex="-1"
    role="alertdialog"
    aria-label={kind === 'tool' ? t('werkzeug.bestaetigen') : question.frage}
    onkeydown={key}
    out:leave
  >
    <div class="badge" aria-hidden="true">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
           stroke-linecap="round" stroke-linejoin="round">
        <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" />
        <path d="M12 17h.01" />
      </svg>
    </div>
    <!-- Who is asking: the model, or the agent by its name. -->
    <p class="asker">
      <b>{kind === 'agent' ? question.agentName : modelName}</b>
      {#if kind === 'tool'}
        <span>{t('werkzeug.wants_to_run_before')}<b class="werkzeugname">{question.name}</b>{t('werkzeug.wants_to_run_after')}</span>
      {:else}
        <span>{t('werkzeuge.fragt')}</span>
      {/if}
    </p>
    {#if pill}<div class="pill">{pill}</div>{/if}
    <h2 class="title">{kind === 'tool' ? t('werkzeug.permission_question') : question.frage}</h2>

    {#if kind === 'tool' && (command || question.grund)}
      <div class="details">
        <!-- The command is never folded away. With more arguments than the
             one it shows, a click on it unfolds the rest. -->
        {#if command && argumentPairs.length > 1}
          <button class="command" class:open={argumentsOpen} aria-expanded={argumentsOpen}
                  onclick={() => (argumentsOpen = !argumentsOpen)} use:rollfade>
            <span class="quiet">$</span> {@html commandColoured}
            <span class="unfold"><Hauszeichen zeichen="pfeil_unten" groesse={11} strich={2.6} /></span>
          </button>
        {:else if command}
          <div class="command" use:rollfade><span class="quiet">$</span> {@html commandColoured}</div>
        {/if}
        {#if argumentsOpen}
          <dl class="arguments" use:rollfade>
            {#each argumentPairs as [name, value] (name)}
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
            <span>{@html reasonText}</span>
          </p>
        {/if}
      </div>
    {/if}

    <div class="answers">
      <!-- By place, not by label: two answers of the model may read the same. -->
      {#each rows as row, index}
        <button class="answer" class:active={active === index} bind:this={rowButtons[index]}
                onclick={row.pick} onfocus={() => (active = index)} onblur={() => (active = -1)}>
          <span class="label">{row.label}</span>
          <span class="check" aria-hidden="true">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                 stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
              <path d="M20 6 9 17l-5-5" />
            </svg>
          </span>
        </button>
      {/each}
    </div>

    <div class="own">
      <input class="field" bind:this={ownField} bind:value={own} placeholder={ownPlaceholder}
             aria-label={ownPlaceholder} oninput={keepDraft}
             onfocus={() => (active = rows.length)} onblur={() => (active = -1)} />
      <button class="send" onclick={sendOwn} disabled={!own.trim()}
              aria-label={t('benutzerfrage.eigene_senden')} title={t('benutzerfrage.eigene_senden')}>
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M12 19V5M5 12l7-7 7 7" />
        </svg>
      </button>
    </div>

    <button class="later" onclick={onLater}>{t('benutzerfrage.later')}</button>
  </div>
</div>

<style>
  /* The veil: the look's ground at 45 %, frosted, over the whole chat
     column and nothing beside it. Over the chat's own layers (its head at
     3), under the notices (25). */
  .veil {
    position: absolute;
    inset: 0;
    z-index: 4;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 24px;
    border-radius: inherit;
    background: color-mix(in srgb, var(--bg) 45%, transparent);
    -webkit-backdrop-filter: var(--kachel-frost);
    backdrop-filter: var(--kachel-frost);
    animation: dawn 0.3s ease both;
  }
  @keyframes dawn { from { opacity: 0; } }
  /* While the picture studio lies over the chat, the chat's own layers are
     out of sight — and so is what waits in it. */
  :global(main.studio) > .veil { visibility: hidden; }

  /* The card: glass in the look's raised ground, one radius like every
     edge in the program, lifted by the shadow a window of the house wears.
     Taller than the column, it scrolls in itself. */
  .card {
    width: min(100%, 520px);
    max-height: 100%;
    overflow-y: auto;
    padding: 28px 28px 24px;
    border-radius: 9px;
    background: color-mix(in srgb, var(--bg-erhoben) 70%, transparent);
    -webkit-backdrop-filter: var(--kachel-frost);
    backdrop-filter: var(--kachel-frost);
    box-shadow: inset 0 0 0 1px var(--glass-card-line), 0 28px 70px -12px rgba(0, 0, 0, 0.55);
    color: var(--text);
    text-align: center;
    outline: none;
    animation: rise 0.46s cubic-bezier(0.32, 0.72, 0.2, 1) both;
  }
  @keyframes rise { from { opacity: 0; transform: translateY(14px) scale(0.97); } }

  /* The mark of a question: a round glass badge, the question mark drawn
     as a line in the pill's colour. */
  .badge {
    display: grid;
    place-items: center;
    width: 52px;
    height: 52px;
    margin: 0 auto 12px;
    border-radius: 50%;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--blau);
  }
  .badge svg { width: 30px; height: 30px; }

  .asker {
    margin: 0 0 12px;
    font-size: 12.5px;
    color: var(--text-leise);
  }
  .asker b { font-weight: 600; color: var(--text); }
  /* A tool's name wears the tool colour wherever it stands. */
  .asker b.werkzeugname { color: var(--werkzeug); }

  /* Coloured the quiet way: the colour on a ground that holds 12 % of it. */
  .pill {
    width: fit-content;
    margin: 0 auto 12px;
    padding: 4px 12px;
    border-radius: 9px;
    background: color-mix(in srgb, var(--blau) 12%, var(--bg));
    color: var(--blau);
    font-size: 11.5px;
    font-weight: 600;
    letter-spacing: 0.04em;
    font-variant-numeric: tabular-nums;
  }
  .title {
    margin: 0 0 20px;
    font-size: 22px;
    font-weight: 600;
    letter-spacing: -0.01em;
    line-height: 1.3;
    color: var(--text);
    text-wrap: balance;
    overflow-wrap: anywhere;
  }

  /* What a permission rests on reads like a terminal: left-aligned, in
     monospace. */
  .details {
    display: flex;
    flex-direction: column;
    gap: 8px;
    margin: 0 0 16px;
    text-align: left;
  }
  .command {
    width: 100%;
    max-height: 30vh;
    overflow-y: auto;
    padding: 8px 10px;
    border-radius: 9px;
    background: var(--glass-card);
    box-shadow: inset 0 0 0 1px var(--glass-card-line);
    font: 12px/18px var(--schrift-fest);
    color: var(--text);
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }
  button.command { border: none; text-align: left; cursor: pointer; }
  .quiet { color: var(--text-still); }
  .unfold {
    display: inline-flex;
    vertical-align: middle;
    margin-left: 6px;
    color: var(--text-still);
    transition: transform 0.18s;
  }
  .command.open .unfold { transform: rotate(180deg); }
  .arguments {
    margin: 0;
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 2px 10px;
    max-height: 30vh;
    overflow-y: auto;
    font-size: 12px;
  }
  dt { color: var(--text-still); font: 11.5px var(--schrift-fest); white-space: nowrap; }
  dd { margin: 0; min-width: 0; color: var(--text); font: 12px var(--schrift-fest); white-space: pre-wrap; overflow-wrap: anywhere; }
  /* Reaching beyond what was shared: the waiting colour, on a quiet
     surface and never as a line of full yellow text. */
  .reason {
    display: flex;
    align-items: center;
    gap: 7px;
    margin: 0;
    padding: 6px 9px;
    border-radius: 9px;
    background: color-mix(in srgb, var(--gelb) 12%, var(--bg-erhoben));
    font-size: 12px;
    color: var(--text);
  }
  .reason svg { flex: none; color: var(--gelb); }
  .reason span { min-width: 0; overflow-wrap: anywhere; }
  .reason :global(.path) { font: 11.5px var(--schrift-fest); }

  /* Each answer is a card of its own, as wide as the window. */
  .answers { display: flex; flex-direction: column; gap: 10px; }
  .answer {
    position: relative;
    width: 100%;
    min-height: 60px;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 12px 44px;
    border: none;
    border-radius: 9px;
    background: var(--glass-card);
    box-shadow: inset 0 0 0 1px var(--glass-card-line);
    color: var(--text);
    font: inherit;
    text-align: center;
    cursor: pointer;
    outline: none;
    transition: background 0.18s ease, box-shadow 0.18s ease, transform 0.18s ease;
  }
  /* Under the pointer it lifts a breath. */
  .answer:hover {
    background: var(--glass-hover);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge), 0 12px 26px -16px rgba(0, 0, 0, 0.5);
    transform: translateY(-1px);
  }
  .answer:active { transform: none; }
  /* The chosen one — the answer Enter sends — wears the text's line and a
     tick at its right. */
  .answer.active {
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1.5px var(--text);
  }
  .label { font-size: 14.5px; font-weight: 600; overflow-wrap: anywhere; }
  .check {
    position: absolute;
    right: 14px;
    top: 50%;
    width: 20px;
    height: 20px;
    margin-top: -10px;
    display: grid;
    place-items: center;
    border-radius: 50%;
    background: var(--text);
    color: var(--bg);
    opacity: 0;
    transform: scale(0.6);
    transition: opacity 0.16s, transform 0.16s;
  }
  .answer.active .check { opacity: 1; transform: none; }

  /* An answer in one's own words, and the round button that sends it. */
  .own { display: flex; align-items: center; gap: 8px; margin-top: 16px; }
  .field {
    flex: 1;
    min-width: 0;
    height: 40px;
    padding: 0 14px;
    border: none;
    border-radius: 9px;
    outline: none;
    background: var(--kachel-eingabe);
    box-shadow: inset 0 0 0 1px var(--glass-card-line);
    color: var(--text);
    font: 400 13.5px var(--schrift);
    text-align: center;
    transition: box-shadow 0.16s;
  }
  .field:focus { box-shadow: inset 0 0 0 1.5px var(--text-leise); text-align: left; }
  .field::placeholder { color: var(--text-still); }
  .send {
    flex: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 40px;
    height: 40px;
    border: none;
    border-radius: 50%;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text);
    cursor: pointer;
    transition: background 0.16s, opacity 0.16s, transform 0.16s;
  }
  .send:hover:not(:disabled) { background: var(--glass-hover); transform: translateY(-1px); }
  .send:disabled { opacity: 0.35; cursor: default; }

  /* The quiet way out, centred under the field. */
  .later {
    display: block;
    margin: 14px auto 0;
    padding: 6px 14px;
    border: none;
    border-radius: 9px;
    background: transparent;
    color: var(--text-leise);
    font: 500 12.5px var(--schrift);
    cursor: pointer;
  }
  .later:hover { background: var(--glass-hover); color: var(--text); }

  @media (prefers-reduced-motion: reduce) {
    .veil, .card { animation: none; }
    .answer, .check, .send, .field, .unfold { transition: none; }
  }
</style>
