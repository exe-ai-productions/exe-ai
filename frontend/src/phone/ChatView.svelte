<script>
  /* The chat on the phone page: the history of the open chat, the question
     card that waits on the person, and the bar the next message is written
     in. An empty chat shows the house wordmark and the greeting in the middle.

     The history is drawn by the same message component as the desktop's; the
     run behind it — sending, the answer, stopping, the queue — is the shared
     one (lib/chatlauf.svelte.js), and what the list shows of it (the waiting
     mark, the clocks, the picture tiles) is lib/chatansicht.svelte.js. This
     page brings its own scrolling: the chat runs with a growing answer, a
     finger that goes up ends that, and the end is back within 70 px of it
     (follow.js). */
  import { untrack, tick } from 'svelte'
  import { fly } from 'svelte/transition'
  import { backOut } from 'svelte/easing'
  import Nachricht from '../teile/Nachricht.svelte'
  import Wartezeile from '../teile/Wartezeile.svelte'
  import Warteblasen from '../teile/Warteblasen.svelte'
  import Wortmarke from '../teile/Wortmarke.svelte'
  import Begruessungsecke from '../teile/Begruessungsecke.svelte'
  import Hauszeichen from '../teile/Hauszeichen.svelte'
  import { t } from '../lib/texte.svelte.js'
  import { zustand, nachrichtenAnzeige, laufVon } from '../lib/zustand.svelte.js'
  import { chatRun } from '../lib/chatlauf.svelte.js'
  import { useChatAnsicht } from '../lib/chatansicht.svelte.js'
  import { useQueueDrive } from '../lib/queueDrive.svelte.js'
  import { useFragekarte } from '../lib/fragekarte.svelte.js'
  import { FOLLOW_PX, distanceToFloor, followAfterScroll } from './follow.js'
  import InputBar from './InputBar.svelte'
  import TerminalSheet from './TerminalSheet.svelte'
  import QuestionCard from './QuestionCard.svelte'

  const { neuErzeugen, frageNeuSenden, takeBackQueued, antwortWiederAnhaengen } = chatRun

  const ansicht = useChatAnsicht()
  useQueueDrive()
  const { zeileLaeuft, bildKacheln, laufendeKachel, inKachelAufgegangen, teilausfall } = ansicht
  const laufMarke = $derived(ansicht.laufMarke)
  const laufZeit = $derived(ansicht.laufZeit)
  const wartewort = $derived(ansicht.wartewort)
  const compactFrom = $derived(ansicht.compactFrom)
  const compactClock = $derived(ansicht.compactClock)
  const dateienVorherKarte = $derived(ansicht.dateienVorherKarte)
  const tileSize = $derived(ansicht.BILDLAUF_KACHEL)
  const laufAktuell = $derived(chatRun.laufAktuell)
  const letzteAntwort = $derived(chatRun.letzteAntwort)
  const letzteFrage = $derived(chatRun.letzteFrage)

  const empty = $derived(!nachrichtenAnzeige().length)

  let bar = $state(null)
  /* Answering a card must not bring the soft keyboard up, and the phone has
     no agents view to show a transcript in. */
  const questions = useFragekarte({ showTranscript: false })

  /* --- Following the floor --------------------------------------------- */

  let box = $state(null)
  let following = true
  let lastTop = 0
  let away = $state(false)

  function refreshAway() {
    away = Boolean(box) && !following && distanceToFloor(box) > FOLLOW_PX
  }
  function onscroll() {
    if (!box) return
    following = followAfterScroll(lastTop, box, following)
    lastTop = box.scrollTop
    refreshAway()
  }
  function toFloor() {
    if (!box || distanceToFloor(box) <= 0) return
    box.scrollTop = box.scrollHeight
    lastTop = box.scrollTop
  }
  /* The floor is kept in the frame the content grows — a new line, a growing
     answer (the entry says so, lib/glide.js). */
  function holdFloor() {
    if (following) toFloor()
    // Content that grows under a reader who stayed above the end makes the
    // way back worth offering without any scroll event.
    else refreshAway()
  }
  /* What the run asks of the page: `runter()` follows, `runter(true)` brings
     the reader back to the end first. */
  function runter(force = false) {
    if (force) {
      following = true
      away = false
    }
    if (following) requestAnimationFrame(toFloor)
  }
  function backToFloor() {
    following = true
    away = false
    box.scrollTo({ top: box.scrollHeight, behavior: 'smooth' })
  }

  $effect.pre(() => chatRun.ansicht({ runter, eingabe: bar }))

  /* Opening a chat whose answer is still being written leaves a word for it
     in `zustand.wiederanhaengen`; the answer is attached to again from here,
     exactly once, so it keeps growing and the stop button stands. Only the
     entry of the chat on screen is acted on: the attached answer writes into
     the visible chat's list. An entry for another chat stays untouched and
     is picked up the moment that chat is opened (this effect re-runs on
     `aktiverChat`). */
  $effect(() => {
    const chatId = zustand.aktiverChat
    const wiederanhang = chatId ? zustand.wiederanhaengen[chatId] : null
    if (!wiederanhang) return
    delete zustand.wiederanhaengen[chatId]
    untrack(() => antwortWiederAnhaengen(wiederanhang))
  })

  /* A card that arrives waits on the person and a run waits on the card: it
     is brought into view, wherever the reader stood. */
  $effect(() => {
    if (questions.cardStands) untrack(() => runter(true))
  })

  /* The track and the box change size without a chunk arriving: the bar
     grows with the text typed, the keyboard comes. The end is kept. */
  $effect(() => {
    if (!box || typeof ResizeObserver === 'undefined') return
    const watch = new ResizeObserver(holdFloor)
    watch.observe(box)
    const track = box.querySelector('.spur')
    if (track) watch.observe(track)
    return () => watch.disconnect()
  })

  /* A chat that is opened starts at its end. */
  $effect(() => {
    void zustand.aktiverChat
    untrack(() => {
      following = true
      away = false
      tick().then(() => requestAnimationFrame(toFloor))
    })
  })
</script>

<!-- The live waiting mark, drawn by the answer it waits for. -->
{#snippet wartemarke(nurMarke = false)}
  {#if laufMarke}
    <Wartezeile
      {nurMarke}
      art={laufMarke.art}
      text={laufMarke.kontext
        ? t('nachricht.verarbeitet_kontext', { zeit: laufZeit })
        : laufMarke.text || wartewort}
      zeit={laufMarke.kontext ? '' : laufZeit}
      beschriftung={laufMarke.kontext ? '' : laufMarke.text || t('status.erzeugt_antwort')}
    />
  {/if}
{/snippet}

<main class="chat">
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="verlauf" bind:this={box} {onscroll} onglidegrow={holdFloor}>
    <div class="spur">
      {#each nachrichtenAnzeige() as nachricht (nachricht.id)}
        {@const tiles = bildKacheln(nachricht)}
        {@const drawing = tiles ? laufendeKachel(nachricht, laufAktuell, nachrichtenAnzeige()) : null}
        {#if tiles}
          <!-- The pictures of one run stand together as tiles, two to a row. -->
          <div class="tiles">
            {#each tiles as tile, index (tile.id + '-' + index)}
              <div class="tile" in:fly={{ y: 12, duration: 420, easing: backOut }}>
                <Nachricht nachricht={tile} istLetzte={false} istLetzteFrage={false}
                           laeuft={false} bildDeckel={tileSize} {neuErzeugen}
                           neuSenden={frageNeuSenden} />
              </div>
            {/each}
            {#if drawing}
              <div class="tile">
                <Nachricht nachricht={drawing} istLetzte={false} istLetzteFrage={false}
                           laeuft={false} bildDeckel={tileSize} {neuErzeugen}
                           neuSenden={frageNeuSenden} />
              </div>
            {/if}
          </div>
          {@const shortfall = teilausfall(nachricht, laufAktuell, nachrichtenAnzeige())}
          {#if shortfall}
            <p class="shortfall">{t('bild.lauf_teilweise', shortfall)}</p>
          {/if}
        {:else if (nachricht.art ?? 'nachricht') !== 'werkzeugmeldung'
            && !inKachelAufgegangen(nachricht, laufAktuell, nachrichtenAnzeige())}
          <div class:from-queue={nachricht.fromQueue}
               in:fly={nachricht.fromQueue ? { y: 0, duration: 0 } : { y: 12, duration: 420, easing: backOut }}>
            <Nachricht
              {nachricht}
              dateienVorher={dateienVorherKarte.get(nachricht.id) ?? 0}
              istLetzte={letzteAntwort && nachricht.id === letzteAntwort.id}
              istLetzteFrage={letzteFrage && nachricht.id === letzteFrage.id}
              laeuft={zeileLaeuft(nachricht)
                && (nachricht.zustand === 'laeuft' || Boolean(laufVon(zustand.aktiverChat)))}
              marke={laufMarke && laufMarke.id === nachricht.id ? wartemarke : null}
              {neuErzeugen}
              neuSenden={frageNeuSenden}
            />
          </div>
        {/if}
      {/each}
      {#if compactFrom !== null}
        <div class="folding">
          <Wartezeile art="verdichtung" text={t('status.komprimiert')} zeit={compactClock} />
        </div>
      {/if}
      <!-- What has been typed but not yet said, where it will land. -->
      <Warteblasen takeBack={takeBackQueued} />
      {#if questions.cardStands}
        <QuestionCard {questions} />
      {/if}
    </div>
  </div>

  {#if empty}
    <div class="welcome">
      <Wortmarke hoehe={44} zentriert />
      {#key empty}<Begruessungsecke />{/key}
    </div>
  {/if}

  <div class="foot">
    {#if away && !empty}
      <button class="to-floor" onclick={backToFloor} aria-label={t('terminal.ans_ende')}>
        <Hauszeichen zeichen="pfeil_unten" groesse={14} strich={2.2} />
      </button>
    {/if}
    <InputBar bind:this={bar} {questions} {empty} />
  </div>
</main>

<!-- The terminal over the chat, raised by a tap on the line of a call. -->
<TerminalSheet />

<style>
  /* The chat is a tile on the frame, as on the desktop: the edge of the tile
     is the line between the head and the chat. Over the flat frame of Exe the
     clear glass would mix to nearly the ground of the own bubble, so Exe
     stands on its solid ground; the glass shows on Pearl. The rounded
     corners at the foot follow the corners of the screen, and give way to
     the house corner while the keyboard stands under the tile. */
  .chat {
    position: relative;
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
    margin: 0 calc(8px + env(safe-area-inset-right)) 0 calc(8px + env(safe-area-inset-left));
    border-radius: 9px 9px 30px 30px;
    background: var(--kachel-chat, var(--bg));
    box-shadow: var(--chat-edge, none);
    overflow: hidden;
  }
  :global(html[data-modus='dunkel']) .chat {
    background: var(--bg);
  }
  :global([data-keyboard]) .chat {
    border-radius: 9px;
  }
  .verlauf {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    overscroll-behavior: contain;
    -webkit-overflow-scrolling: touch;
    padding: 0 calc(14px + env(safe-area-inset-right)) 0 calc(14px + env(safe-area-inset-left));
  }
  .spur {
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 8px 0 16px;
  }
  /* The frame around each message is a flex column, as on the desktop page:
     the own bubble is as wide as its text and the buttons under it stand at
     its right edge only because of it. The picture rows keep their own
     layout. */
  .spur > :global(div:not(.tiles)) {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }
  .tiles {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }
  .tile {
    min-width: 0;
    max-width: calc(50% - 4px);
  }
  .shortfall {
    margin: 0;
    color: var(--text-still);
    font: var(--schrift-hinweis) var(--schrift);
  }
  .folding {
    padding: 4px 0;
  }
  /* The empty chat: wordmark and greeting stand in the middle, over the
     history that is not there. */
  .welcome {
    position: absolute;
    inset: 0 0 auto 0;
    bottom: 96px;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 14px;
    pointer-events: none;
    color: var(--text-still);
  }
  .foot {
    position: relative;
    flex: none;
  }
  /* The round button over the bar: back to the end, and the chat runs with
     the answer again. */
  .to-floor {
    position: absolute;
    left: 50%;
    bottom: calc(100% + 8px);
    transform: translateX(-50%);
    width: 36px;
    height: 36px;
    display: grid;
    place-items: center;
    border: none;
    border-radius: 50%;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge), 0 6px 16px -6px rgba(0, 0, 0, 0.5);
    color: var(--text);
  }
  .to-floor:active {
    transform: translateX(-50%) scale(0.94);
  }
</style>
