<script>
  /* The bar the next message is written in, floating at the foot of the
     chat: "+" for what can be added, the field, the microphone and the arrow
     that sends — and while an answer runs with nothing typed, the arrow is
     the stop sign. What is attached stands above the field: pictures as
     small previews, documents as tiles with their name, each with its ✕.

     What the bar holds — the words, one draft per chat, the attachments, the
     send, the dictation — is the shared one (lib/eingabe.svelte.js); this is
     its view. */
  import { tick } from 'svelte'
  import Hauszeichen from '../teile/Hauszeichen.svelte'
  import Mikrofonknopf from '../teile/Mikrofonknopf.svelte'
  import AttachSheet from './AttachSheet.svelte'
  import { t } from '../lib/texte.svelte.js'
  import { api } from '../lib/api.js'
  import { zustand, melde } from '../lib/zustand.svelte.js'
  import { chatRun } from '../lib/chatlauf.svelte.js'
  import { chatEingabe } from '../lib/eingabe.svelte.js'
  import { chosenModelOff } from '../lib/modelle.svelte.js'
  import { questionKey } from '../lib/questionbox.svelte.js'
  import {
    aufnahme, starten as startRecording, stoppen as stopRecording, fehlerschluessel,
  } from '../lib/aufnahme.svelte.js'

  let { questions, empty = false } = $props()

  let field = $state(null)
  let attachOpen = $state(false)

  const text = $derived(chatEingabe.text)
  const pictures = $derived(chatEingabe.anhaenge)
  const documents = $derived(chatEingabe.dokumentAnhaenge)
  const busy = $derived(chatEingabe.laeuftGerade)
  const nothing = $derived(!text.trim() && !pictures.length && !documents.length)
  /* The arrow is the stop sign only while a run has nothing to send beside
     it: with something in the field, sending (into the queue) is what the
     hand is after. */
  const stops = $derived(busy && nothing)
  /* Shut while the chat's model is switched off — except where the words
     answer a question the run waits on. */
  const locked = $derived(
    !stops && chosenModelOff() && !chatEingabe.antwortetOffeneFrage(text.trim()),
  )

  export function fokus() {
    field?.focus()
  }
  /* What a send that did not go through gives back, and how a queued
     message goes back into the field — the run calls these on the bar. */
  export function keep(messageId, kept) {
    return chatEingabe.keep(messageId, kept)
  }
  export function zurueckgeben(inhalt, chat, messageId = null) {
    return chatEingabe.zurueckgeben(inhalt, chat, messageId)
  }
  export function takeBack(entry) {
    return chatEingabe.takeBack(entry)
  }
  export function takeBackAll(entries, chat) {
    return chatEingabe.takeBackAll(entries, chat)
  }
  export function transcribing() {
    return chatEingabe.transcribing()
  }
  export function cancelTranscription() {
    chatEingabe.cancelTranscription()
  }

  /* The bar hands the store its field and the questions' hold on the draft;
     the same draft survives a page that is swapped for the desktop's. */
  $effect(() =>
    chatEingabe.ansicht({
      feld: field,
      fokus,
      questionHidden: questions.questionHidden,
      bereich: () => null,
    }),
  )
  $effect(() => chatEingabe.neuladeParken())
  $effect(() => chatEingabe.chatWechseln(zustand.aktiverChat))
  $effect(() => chatEingabe.denkenLaden())

  /* The field grows with the words, up to a share of the screen (the style
     below), and scrolls beyond that. */
  function fit() {
    if (!field) return
    field.style.height = 'auto'
    field.style.height = `${field.scrollHeight}px`
  }
  $effect(() => {
    void text
    tick().then(fit)
  })

  /* A skill picked in the sheet is written as its command, and the field is
     where the words go on. */
  function useSkill(name) {
    chatEingabe.text = `/${name} `
    field?.focus()
  }

  function act() {
    if (stops) chatRun.abbrechenVonHand()
    else if (!locked) chatEingabe.absenden()
  }

  /* Dictation: press, speak, press — the words land in the field and are not
     sent. Asked before the microphone is: a recording nobody can transcribe
     is a refusal at the end of it. */
  async function microphone() {
    if (chatEingabe.holtText) return
    if (aufnahme.laeuft) {
      await chatEingabe.diktatHolen(stopRecording())
      return
    }
    let standing = null
    try {
      standing = await api.spracheAuskunft()
    } catch {
      standing = null
    }
    if (!standing?.laeuft) {
      melde(t('sprache.server_aus'))
      return
    }
    try {
      await startRecording(chatEingabe.diktatHolen)
    } catch (error) {
      melde(t(fehlerschluessel(error)), 'fehler')
    }
  }
</script>

<div class="zone">
  {#if questions.pushedAway.length}
    <!-- A question pushed away with "later" waits here: who is asking; a tap
         brings the card back. -->
    <div class="later">
      {#each questions.pushedAway as item (questionKey(item))}
        <button class="chip" onclick={() => questions.resume(item)}>
          <span class="dot" aria-hidden="true"></span>
          {item.kind === 'agent' ? item.question.agentName : questions.modelName}
        </button>
      {/each}
    </div>
  {/if}

  <div class="bar" class:empty>
    {#if pictures.length || documents.length}
      <div class="attachments">
        {#each pictures as picture, index (picture.url)}
          <span class="attachment picture">
            <button class="face" onclick={() => chatEingabe.bildOeffnen(index)}
                    aria-label={`${t('nachricht.bild_vergroessern')} - ${picture.datei.name}`}>
              <img src={picture.url} alt="" />
            </button>
            <button class="remove" onclick={() => chatEingabe.anhangEntfernen(index)}
                    aria-label={t('eingabe.anhang_entfernen')}>
              <Hauszeichen zeichen="kreuz" groesse={9} strich={2.6} />
            </button>
          </span>
        {/each}
        {#each documents as document, index (document.id)}
          <span class="attachment document" class:loading={!document.dokument}>
            <!-- Not a button: opening a document is done by the machine the
                 service runs on, and nothing would show on the phone. -->
            <span class="face">
              <Hauszeichen zeichen="dokument" groesse={16} />
              <span class="name">{document.datei.name}</span>
            </span>
            <button class="remove" onclick={() => chatEingabe.dokumentEntfernen(index)}
                    aria-label={t('eingabe.dokument_entfernen')}>
              <Hauszeichen zeichen="kreuz" groesse={9} strich={2.6} />
            </button>
          </span>
        {/each}
      </div>
    {/if}

    <div class="row">
      <button class="round plus" onclick={() => (attachOpen = true)}
              aria-label={t('eingabe.attach_files')}>
        <Hauszeichen zeichen="plus" groesse={18} strich={2.2} />
      </button>
      <textarea
        bind:this={field}
        bind:value={chatEingabe.text}
        rows="1"
        enterkeyhint="enter"
        autocapitalize="sentences"
        placeholder={empty ? t('eingabe.los') : t('eingabe.platzhalter')}
        aria-label={t('eingabe.nachricht')}
      ></textarea>
      <span class="mic">
        <Mikrofonknopf nimmt={aufnahme.laeuft} holt={chatEingabe.holtText} onschalten={microphone} />
      </span>
      <button
        class="act"
        class:stops
        class:leer={!busy && nothing}
        onclick={act}
        disabled={locked}
        aria-label={stops
          ? t('eingabe.abbrechen')
          : locked ? t('fehler.modell_deaktiviert') : t('eingabe.senden')}
      >
        <svg class="arrow" width="16" height="16" viewBox="0 0 24 24" fill="none"
             stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
          <path d="M12 19V5M5 12l7-7 7 7" />
        </svg>
        <span class="cube"></span>
      </button>
    </div>
  </div>
</div>

<AttachSheet open={attachOpen} onclose={() => (attachOpen = false)} onskill={useSkill} />

<style>
  .zone {
    padding: 6px calc(10px + env(safe-area-inset-right)) calc(8px + env(safe-area-inset-bottom))
      calc(10px + env(safe-area-inset-left));
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  /* Under the keyboard there is no home bar to keep clear of. */
  :global([data-keyboard]) .zone {
    padding-bottom: 8px;
  }
  .bar {
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: 8px 8px 8px 10px;
    border-radius: 9px;
    background: var(--kachel-eingabe, var(--bg-erhoben));
    box-shadow: 0 14px 34px -14px rgba(0, 0, 0, 0.55), 0 2px 6px -2px rgba(0, 0, 0, 0.25);
  }
  .row {
    display: flex;
    align-items: flex-end;
    gap: 6px;
  }
  textarea {
    flex: 1;
    min-width: 0;
    max-height: 35dvh;
    padding: 8px 2px;
    border: none;
    outline: none;
    resize: none;
    background: none;
    color: var(--text);
    /* 16 px: a smaller field makes the page zoom when it takes the focus. */
    font: inherit;
    font-size: 16px;
    line-height: 22px;
    overflow-y: auto;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }
  textarea::placeholder {
    color: var(--text-still);
  }
  /* The microphone is a 30 px button; its neighbours are 36 px. In a box of
     their size it shares their centre line, whatever the field's height. */
  .mic {
    flex: none;
    width: 36px;
    height: 36px;
    display: grid;
    place-items: center;
  }
  .round {
    flex: none;
    width: 36px;
    height: 36px;
    display: grid;
    place-items: center;
    padding: 0;
    border: none;
    border-radius: 50%;
    background: transparent;
    color: var(--text-leise);
  }
  .round:active {
    background: var(--bg-hoch);
    color: var(--text);
  }
  .act {
    position: relative;
    flex: none;
    width: 36px;
    height: 36px;
    display: grid;
    place-items: center;
    padding: 0;
    border: none;
    border-radius: 50%;
    background: var(--text);
    color: var(--bg);
    transition: opacity 0.16s ease, transform 0.1s ease;
  }
  .act:active {
    transform: scale(0.94);
  }
  /* Nothing to send, or shut while the model is switched off: the house's one
     look for "nothing to send". */
  .act.leer,
  .act:disabled {
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text-still);
  }
  .cube {
    position: absolute;
    width: 11px;
    height: 11px;
    border-radius: 3px;
    background: currentColor;
    opacity: 0;
    transform: scale(0.6);
  }
  .arrow,
  .cube {
    transition: opacity 0.14s ease, transform 0.18s cubic-bezier(0.2, 0.9, 0.3, 1);
  }
  .act.stops {
    background: none;
    color: var(--text-leise);
  }
  .act.stops .arrow {
    opacity: 0;
    transform: scale(0.6);
  }
  .act.stops .cube {
    opacity: 1;
    transform: none;
  }
  .attachments {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }
  .attachment {
    position: relative;
    display: inline-flex;
  }
  .face {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 0;
    border: none;
    background: none;
    color: var(--text-leise);
  }
  .picture img {
    width: 56px;
    height: 56px;
    object-fit: cover;
    border-radius: 9px;
  }
  .document .face {
    max-width: 180px;
    padding: 8px 10px;
    border-radius: 9px;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    font: var(--schrift-hinweis) var(--schrift);
  }
  .document.loading .face {
    opacity: 0.6;
  }
  .name {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .remove {
    position: absolute;
    top: -6px;
    right: -6px;
    width: 20px;
    height: 20px;
    display: grid;
    place-items: center;
    padding: 0;
    border: none;
    border-radius: 50%;
    background: var(--glass-dropdown);
    box-shadow: 0 0 0 1px var(--glass-button-edge);
    color: var(--text);
  }
  .later {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
  .chip {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 6px 10px;
    border: none;
    border-radius: 9px;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text);
    font: var(--schrift-hinweis) var(--schrift);
  }
  .dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--gelb);
  }
</style>
