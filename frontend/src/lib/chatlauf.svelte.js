/*
  The run of a chat: sending a question, fetching the answer and attaching
  to a run that is still going, stopping, regenerating, sending again, the
  fold of the chat, and the queue of questions typed meanwhile.

  It lives here, not in a window: the desktop page and the phone page both
  drive the same run, each through its own view. A page hands its view over
  with `ansicht()` — what scrolls the list to its floor (`runter`) and the
  field the question is typed into (`eingabe`, which gives back `keep`,
  `zurueckgeben`, `takeBack` and `fokus`) — and calls the functions below. The state of the run (`laufAktuell`, the fold, the queue) stays
  here and is read through the getters.
*/

import { sharedByModel } from './arbeitsordner.svelte.js'
import { taetigkeitSetzen, taetigkeitUnbekannt } from './taetigkeit.js'
import { antwortStrom, api, zusehenStrom } from './api.js'
import { t } from './texte.svelte.js'
import { aktualisiereMeldung, aktuellerChat, answerDrawingTile, benutzerfrageBeantworten, chatFertigMerken, chatOeffnen, chatsLaden, haltendenWertSetzen, isDrawingTool, laufVon, melde, nachrichtenAnzeige, nachrichtenSetzen, openNewChat, zustand } from './zustand.svelte.js'
import { chatNameFrom } from './chatName.js'
import { WERKZEUG_FEHLER_MS, meldeText, melden, schliesseMeldung, werkzeugFertigDauer } from './meldewesen.svelte.js'
import { dateienAus, dateienDavor, endsInFence, openFile } from './markdown.js'
import { tabWriter } from './vorschautabs.svelte.js'
import { openDeliveredFiles } from './deliveredFile.js'
import { nameUpload } from './picturePreview.js'
import { leiste } from './arbeitsleiste.svelte.js'
import { ausreihen, entfernen, hasInterrupted, takeAllOut, markInterrupted, unmarkInterrupted, zurueckEinreihen } from './warteschlange.svelte.js'
import { chosenModelOff } from './modelle.svelte.js'
import { answerEnding } from './answerEnding.js'
import { chatFehlerGesehen, chatFehlerMerken } from './chatringe.svelte.js'

export function createChatRun() {
  /* The view of the page that is showing the chat right now. */
  let view = null
  let runter = () => {}
  let eingabe = null

  // Running tool calls -> their notification, so the result rewrites the
  // same notification instead of creating a second one.
  const werkzeugMeldungen = new Map()

  /* The chats a hand-made compaction (`/compact`) is running in, by the
     moment it began. Not a row's activity like the marks above: there is no
     answer being written, so the mark stands on its own at the end of the
     list and counts from here. */
  const compactSince = $state({})

  /* The regenerate arrow, and the "send again" of the last question.

     Filtered by `art` as well as by role: a finished background command
     and a picture are assistant rows too, and whichever of them happened
     to land last used to pull the arrow onto itself — regenerating a tool
     report is not a thing, and "send again" would have DELETED it. Only an
     ordinary turn can be one of these. */
  /* How long the end-of-run reconcile may wait for the fresh page before
     the run is released without it. Generous for a page of five hundred
     rows over a slow link; short beside a chat that stays locked. */
  const NACHLADE_FRIST_MS = 15_000

  /* How often a send whose line broke asks the service where its answer
     went. Half a second, the tick the layout guard already uses: the fold
     in front of the answer is not observable any other way, and asking
     faster would only load the very service that is busy folding. */
  const HALTEPRUEFUNG_MS = 500

  /* How long the window waits before it tries the broken line again: one
     second, and twice as much after every further failure, up to half a
     minute. A stream that opens throws the wait away. The run outlives the
     line, so the window has to come back to it. */
  const WIEDERANHANG_PAUSE_MS = 1_000

  const WIEDERANHANG_PAUSE_MAX_MS = 30_000

  const letzteAntwort = $derived(
    [...nachrichtenAnzeige()]
      .reverse()
      .find((n) => n.role === 'assistant' && (n.art ?? 'nachricht') === 'nachricht'),
  )

  const letzteFrage = $derived(
    [...nachrichtenAnzeige()]
      .reverse()
      .find((n) => n.role === 'user' && (n.art ?? 'nachricht') === 'nachricht'),
  )

  /* K4/K4b + C6 (Executor): a message carries its own pictures in one of
     two shapes — the old single upload (`bild`, a bare file name) or a
     Weg-A run's own list (`bilder`, one array entry per requested
     position, `null` where a picture has not finished or did not
     survive) — and more than one place in the window needs to know a
     row's real count regardless of which shape it is: `traegtBild`
     below, and `teilausfall`'s own sum across a lauf split by a mid-run
     restart. Both used to answer that question on their own; asking it
     here instead is what let `teilausfall` count a legacy `bild`-only
     row's picture at all instead of reading it as zero. Mirrors the
     server's own `Message.bild_dateien()`. */
  function bildDateien(nachricht) {
    if (Array.isArray(nachricht?.bilder)) {
      const echte = nachricht.bilder.filter(Boolean)
      if (echte.length) return echte
    }
    return nachricht?.bild ? [nachricht.bild] : []
  }

  /* A run that has not drawn a single picture yet still has a non-empty
     ARRAY of nulls, and in JavaScript that array is truthy same as a
     full one — `!nachricht.bilder` alone would call an all-null run "no
     picture" and let it through. Checked by content, via `bildDateien`,
     not by presence. */
  function traegtBild(nachricht) {
    return bildDateien(nachricht).length > 0
  }

  /* Send again beneath one's own bubble: same effect
     as regenerate beneath the answer — if an answer is there, it gets
     replaced; if it's missing (e.g. after an abort), it simply gets
     fetched. Fetching an answer only ever means asking the LANGUAGE
     model, so this only ever looks for a text answer to replace — K4:
     without the `!traegtBild(letzte)` guard, the chat's last message
     being a picture (this button sits under every question, a lauf's
     own included, and its own last message is one of that lauf's own
     tiles or its one Weg-A answer row) made this delete that picture
     through the same door H1b/K2 already had to close. Under a picture,
     "send again" simply fetches a fresh text answer instead of touching
     it. */
  async function frageNeuSenden() {
    if (laufVon(zustand.aktiverChat)) {
      melde(t('eingabe.laeuft_schon'))
      return
    }
    // A new answer, so the same rule as sending: none from a model that is off.
    if (chosenModelOff()) return
    /* `letzteAntwort`, not the last row: that one may be a finished
       background command, and `neuErzeugen` names what it is given as the
       answer a new one takes the place of. The `traegtBild` test stays —
       it closed the same door for picture rows before `art` existed, and a
       row can still carry a picture without being one. */
    const letzte = letzteAntwort
    /* A failed answer is asked again where it stands, and nothing of it is
       deleted — so it goes that way with a picture on it as well. */
    const failedAnswer = Boolean(letzte?.id) && answerEnding(letzte) === 'fehler'
    if (
      (failedAnswer || (letzte && letzte.id && !traegtBild(letzte)))
      && antwortAufLetzteFrage(zustand.nachrichten, letzte, letzteFrage)
    ) {
      await neuErzeugen(letzte.id)
    } else {
      await antwortHolen(null)
    }
  }

  /* Is that answer the one that belongs to the last question?

     `letzteAntwort` picks the last ORDINARY answer, skipping reports and
     pictures — which is right for the arrow, and wrong on its own for a
     button that deletes: with a picture prompt and its picture standing
     last, the last ordinary answer belongs to the question BEFORE them,
     and "send again" would have deleted that one and regenerated it on a
     history that ends elsewhere. An answer may only be replaced when it
     stands behind the last question; otherwise the question simply gets
     an answer fetched, nothing removed. */
  function antwortAufLetzteFrage(nachrichten, antwort, frage) {
    if (!antwort || !frage) return false
    return nachrichten.indexOf(antwort) > nachrichten.indexOf(frage)
  }

  /* The one swap between thinking and answer, as the drawn stretches see it
     — the service side is `app/reasoning.denktext_als_antwort`, and this is
     what its verdict does to the bubble that is already standing there.

     A model that thought its answer instead of writing it leaves the pieces
     holding a thought as a thought and no answer at all, while the chat's
     own row says the other: the thought that changed sides is the END of
     what streamed in, word for word the answer. So the drawn thinking is
     cut back to the part that stayed thinking — `reasoning` is exactly that
     part — and the answer is drawn after all of it.

     The stretches keep their order, their times and the tool rows they
     carry; only their text is cut, and a stretch the cut emptied out steps
     aside, because an empty thinking head would stand there otherwise. The
     input is left alone — the caller gets a new list.

     One closing event per answer, and one answer per bubble: a run whose
     stream is picked up again clears the bubble and replays every event, so
     this never runs twice on what it already lifted.

     `content` is the whole row's answer. Where an earlier tool round wrote a
     sentence before its call, that sentence already stands drawn and
     `content` begins with it; only what follows it is drawn after the
     thinking, or the sentence would stand twice.
     */
  function liftAnswer(strecken, content, reasoning) {
    let left = reasoning ?? ''
    const kept = []
    for (const a of strecken) {
      if (a.art !== 'reasoning') {
        kept.push(a)
        continue
      }
      const take = Math.min(left.length, a.text.length)
      const text = left.slice(0, take)
      left = left.slice(take)
      if (text) kept.push({ ...a, text })
    }
    const drawn = strecken
      .filter((a) => a.art === 'content')
      .map((a) => a.text)
      .join('')
    const lifted = drawn && content.startsWith(drawn) ? content.slice(drawn.length) : content
    kept.push({ art: 'content', text: lifted })
    return kept
  }

  /* The live readings of a round end with that round. Called wherever the
     run comes to a stand at a tool — its call written (`tool_call`), a
     permission asked (`tool_confirm`), a question put (`user_ask`) or a
     task held for confirmation (`job_confirm`) — and at the answer's end,
     where the measured figure takes over (`stats`): what a round read of
     its own prompt and its own writing must not stand while nothing is
     written. A run without a tool never comes to such a stand, and a
     stream picked up again after a dropped connection keeps the reading —
     it is the same round, still writing. */
  function lesungenLeeren(platzhalter) {
    platzhalter.liveSpeed = null
    platzhalter.liveShare = null
  }

  /* The numbers under an answer that was stopped from this window. The
     stream was cut at the press, so the `stats` event never arrives and the
     row is left with what an earlier round put there — the speed of rounds
     that were not the stopped one. It is emptied at once and filled with what
     the service stored for the answer, which is the same line a reload
     shows. The service stores the answer a moment after the stop lands:
     asked until the row says it was stopped, bounded, and given up quietly —
     the chat shows the stored line at its next open anyway. */
  async function abbruchZeileNachziehen(chatId, zeile) {
    const bis = Date.now() + NACHLADE_FRIST_MS
    while (Date.now() < bis) {
      if (chatId !== zustand.aktiverChat) return
      let lage
      try {
        lage = await api.nachrichten(chatId, {
          signal: AbortSignal.timeout(NACHLADE_FRIST_MS),
          limit: 8,
        })
      } catch {
        return
      }
      const gespeichert = lage?.nachrichten?.find((n) => n.id === zeile.id)
      if (gespeichert?.stats?.abgebrochen) {
        zeile.stats = gespeichert.stats
        return
      }
      await new Promise((frei) => setTimeout(frei, HALTEPRUEFUNG_MS))
    }
  }

  async function senden(
    inhalt, anhaenge = null, dokumente = null, denken = null, skill = null, gespraech = false,
    messageId = null, kept = null, ausReihe = null,
  ) {
    /* A question from the model is waiting: then what was typed IS the
       answer, not a new message. Free text always counts — the buttons are
       an offer, not a cage. */
    if (
      zustand.benutzerfrage[zustand.aktiverChat]
      && inhalt?.trim()
    ) {
      await benutzerfrageBeantworten(inhalt.trim())
      return
    }
    /* A send that ends before the request leaves gives back what was typed
       and what was attached to it, to the chat they were written for — the
       same way as a send the service refuses. Only a send that came out of
       the bar has anything to give back: its own id, or the entries a queued
       message kept, which are put in the bar's keeping under this send's id
       and let go of again when the send is over. */
    const writtenIn = zustand.aktiverChat
    const sendId = messageId ?? Math.random().toString(36).slice(2, 9)
    const fromBar = messageId != null || kept != null
    const release = kept ? eingabe?.keep(sendId, kept) : null
    const giveBack = () => {
      if (fromBar) eingabe?.zurueckgeben(inhalt, writtenIn, sendId)
    }
    if (!zustand.modellId) {
      melde(t('fehler.kein_modell_verfuegbar'), 'fehler')
      giveBack()
      return
    }
    // Switched off in the quick picker: nothing goes to it (lib/modelle).
    if (chosenModelOff()) {
      giveBack()
      return
    }
    /* The images first: if an upload fails, the chat stays untouched and
       the input is still there. The chat is claimed for the uploads' sake
       already (see the send mark below): a queued entry with a picture
       uploaded first and claimed after, and in that stretch the queue,
       woken by the previous run's end, sent the NEXT entry into the same
       chat. A chat that does not exist yet has nothing to claim — and
       nothing queued for it either.

       Documents (4.1) need none of this here: each one is already
       uploaded and read by the time it reaches this function — Eingabeleiste
       uploads it the moment it is attached, not on send. `dokumentListe`
       below is real server meta, not files. */
    const bildDateien = [...(anhaenge || [])]
    const dokumentListe = [...(dokumente || [])]
    const bilder = []
    const ladeChat = zustand.aktiverChat
    if (ladeChat) zustand.sendet[ladeChat] = true
    try {
      for (const datei of bildDateien) {
        try {
          const name = (await api.bildHochladen(datei)).bild
          nameUpload(name, datei)
          bilder.push(name)
        } catch (fehler) {
          melde(String(fehler.message || fehler), 'fehler')
          giveBack()
          return
        }
      }
    } finally {
      // Handed over to the mark below without an await in between.
      if (ladeChat) delete zustand.sendet[ladeChat]
    }
    /* The title says what the chat is about, not which instruction was used
       to get there — so a picked skill is cut off the front of it. */
    const fuerTitel = skill ? inhalt.slice(skill.length + 1).trim() || inhalt : inhalt
    const ersterTitel =
      chatNameFrom(fuerTitel) || dokumentListe[0]?.name || t('eingabe.bild_titel')
    if (!zustand.aktiverChat) {
      try {
        await openNewChat({ title: ersterTitel, endpoint_id: zustand.modellId })
      } catch (fehler) {
        giveBack()
        throw fehler
      }
    } else if (!nachrichtenAnzeige().length) {
      /* A chat can now exist before the first message — setting a working
         folder creates one. It is still untitled
         at that point, so the first message gives it its name here, exactly
         as it would have on creation. */
      const chat = aktuellerChat()
      if (chat && chat.title === t('chat.unbenannt')) {
        chat.title = ersterTitel
        api
          .chatAendern(chat.id, { title: ersterTitel })
          .then(chatsLaden)
          .catch(() => {})
      }
    }
    /* The switch "Suspend instructions" set before this chat existed goes to
       it now, so the very first answer already runs without them. A refusal
       ends the send here, with what was typed given back. */
    if (!(await haltendenWertSetzen())) {
      giveBack()
      return
    }
    /* Busy from here to the run. `laufVon` is still empty in this stretch —
       a second enter used to call senden() again and bear a second answer
       row with the same placeholder id. The input bar queues while this
       stands (laeuftGerade), and the queue itself waits for it. Cleared
       in the finally: by then the run exists and `laufVon` guards, or
       the send failed and the chat is free again. After the chat
       creation above, so a brand-new chat rides on its real id. */
    const sendeChat = zustand.aktiverChat
    /* A chat open that lost its race leaves the list tagged
       for a foreign chat while this one shows empty. Sending here must not
       bury the new question in that foreign, hidden list. */
    if (zustand.nachrichtenChatId !== sendeChat) nachrichtenSetzen(sendeChat, [])
    zustand.sendet[sendeChat] = true
    try {
    /* Given to the service with the request below, so the row it becomes
       carries this same id — not `crypto.randomUUID()`: a service reached
       over plain HTTP from another machine is not a secure context, and
       there that function does not exist at all (see Eingabeleiste.svelte's
       document ids).
       The input bar brings its own: it is the key under which the bar keeps
       what this send took out of it, so a refusal gives back exactly that. */
    const frageKennung = sendId
    /* The document's own card is real from the first frame — the meta IS
       the server's, read the moment it was attached, not a guess off the
       File that gets replaced later. Nothing here can fail any more: a
       document that made it into `dokumentListe` already exists. */
    zustand.nachrichten.push({
      id: 'eigen-' + frageKennung,
      role: 'user',
      content: inhalt,
      bild: bilder[0] ?? null,
      anhaenge: bilder.length > 1 ? bilder : null,
      dokument: dokumentListe.length === 1 ? dokumentListe[0] : null,
      dokumente: dokumentListe.length > 1 ? dokumentListe : null,
      /* Came out of the line: its bubble fills in from the waiting one's
         strength (`.from-queue` in stil/global.css). */
      fromQueue: Boolean(ausReihe),
    })
    runter(true)
    const dokumentIds = dokumentListe.map((dokument) => dokument.id)
    await antwortHolen(
      inhalt, bilder, dokumentIds, denken, skill, null, gespraech, frageKennung, null, ausReihe,
    )
    } finally {
      delete zustand.sendet[sendeChat]
      release?.()
    }
  }

  /* The ONE run (`lauf_kennung`) a model's drawing call is writing into a
     chat right now, or null between runs — the chat's tile row uses it to
     tell "still filling in" from "genuinely short by one" (`teilausfall`):
     a memory would only live as long as this page does and would have gone
     quiet on the very next reload. A historical run loaded fresh from the
     server is never the current one, so its shortfall (if any) shows
     immediately. The studio's runs are not among them: they have no row. */
  let laufAktuell = $state(null)

  /* A picture or a video the model makes while it answers (`draw_image`,
     `draw_video`) stands in the chat: a working tile while it is drawn, and
     the run row its finished pictures stand in. The server writes that row
     itself, the answer's id is its run, and every result of a drawing call
     hands the row over as it stands (`bildlauf`) — so the window only puts
     it in place, it never builds a row of its own. Only on the drawing
     chat's own list: another chat's gets nothing, the row is on the server
     and comes with the next open. */
  function drawingStarted(chatId, answerId) {
    if (zustand.aktiverChat !== chatId || zustand.nachrichtenChatId !== chatId) return
    if (!zustand.nachrichten.some((n) => n.answerId === answerId)) {
      zustand.nachrichten.push(answerDrawingTile(chatId, answerId))
    }
    // The tile joins this answer's run as its next cell once the run has a
    // row.
    laufAktuell = answerId
  }

  function drawingDone(chatId, answerId, row) {
    if (laufAktuell === answerId) laufAktuell = null
    if (zustand.aktiverChat !== chatId || zustand.nachrichtenChatId !== chatId) return
    const list = zustand.nachrichten
    const tile = list.findIndex((n) => n.answerId === answerId)
    const there = row ? list.findIndex((n) => n.id === row.id) : -1
    if (row && there !== -1) {
      list[there] = row
      if (tile !== -1) list.splice(tile, 1)
    } else if (row && tile !== -1) {
      // The run's first picture: its row takes the tile's place.
      list[tile] = row
    } else if (row) {
      list.push(row)
    } else if (tile !== -1) {
      list.splice(tile, 1)
    }
  }

  /* The arrow under the last answer (3.4), without sending the question
     again — and the window deletes nothing for it.

     Under a finished or a stopped answer a new one is written on the
     history without it. The service keeps the old answer until the new one
     is finished and stored, and only then takes it away; a new answer that
     fails or is stopped leaves the old one standing and no row of its own
     (app/answer_redo.py). It used to be deleted HERE, before the new answer
     had begun — and an answer that then failed had cost the old one, tool
     calls and all.

     Under a failed answer the model call it died in is asked again, in the
     same answer, with everything the run had already done.

     Which of the two a press means is read off how the run behind the
     answer ended, the way the arrow's own label reads it
     (lib/answerEnding.js). */
  async function neuErzeugen(messageId) {
    if (laufVon(zustand.aktiverChat)) {
      melde(t('eingabe.laeuft_schon'))
      return
    }
    // A switched-off model gives no new answer, and none is asked for.
    if (chosenModelOff()) return
    const antwort = zustand.nachrichten.find((n) => n.id === messageId)
    await antwortHolen(
      null, null, null, null, null, null, false, null,
      answerEnding(antwort) === 'fehler' ? { retries: messageId } : { replaces: messageId },
    )
  }

  /* `/compact` in the input field: the service folds the middle of the
     open chat once, with the words behind the command as the topic. The
     window waits for it like for a send — the chat counts as busy for the
     whole request, so what is typed meanwhile lines up and goes on when it
     is over — and then shows what happened: the seam where it folded, or a
     hint saying why it did not. Nothing is folded here; the window only
     asks. */
  async function compactChat(topic) {
    const chatId = zustand.aktiverChat
    // A window with no chat has nothing to fold, and says what a chat that
    // is too small to fold says.
    if (!chatId) {
      melde(t('eingabe.compact_too_short'))
      return
    }
    if (laufVon(chatId) || zustand.sendet[chatId] || compactSince[chatId]) {
      melde(t('fehler.antwort_laeuft_schon'))
      return
    }
    zustand.sendet[chatId] = true
    compactSince[chatId] = Date.now()
    try {
      const antwort = await api.chatCompact(chatId, {
        endpoint_id: zustand.modellId,
        topic: topic || null,
      })
      if (antwort.result === 'folded') {
        const frisch = await api.nachrichten(chatId)
        if (zustand.aktiverChat === chatId) {
          nachrichtenSetzen(chatId, frisch.nachrichten)
        }
      } else if (antwort.result === 'too_short') {
        melde(t('eingabe.compact_too_short'))
      } else if (antwort.result === 'no_saving') {
        melde(t('eingabe.compact_no_saving'))
      } else if (antwort.result === 'stopped') {
        // Stopped by the person: nothing folded, nothing to say — as after
        // the stop of an answer.
      } else {
        melde(t('nachricht.komprimieren_fehlgeschlagen'), 'fehler')
      }
    } catch (fehler) {
      melde(String(fehler.message || fehler), 'fehler')
    } finally {
      delete compactSince[chatId]
      delete zustand.sendet[chatId]
    }
  }

  /* The queue moves on: whenever nothing is running, the open chat gets
     the next message waiting in it.

     Deliberately NOT awaited by its caller: the next send starts a run of
     its own, and awaiting it would nest one run inside the last one's
     stack for as long as the queue is.

     It always asks about the OPEN chat, never about the one whose run just
     ended. `senden` writes into the open history, so firing into a
     conversation nobody is looking at would put the bubble in the wrong
     place — and asking about the finished chat instead would leave a queue
     standing forever in the case that matters most: a run started in one
     chat, a message typed in another, and no switch afterwards to wake
     anything up. */
  function warteschlangeWeiter() {
    const chatId = zustand.aktiverChat
    // Only THIS chat blocks its own queue now — a run in another chat does
    // not hold it back.
    if (!chatId || laufVon(chatId) || zustand.sendet[chatId]) return
    // A switched-off model holds the queue too: the message stays in line
    // and goes once a model that is on is chosen (the queue's effect wakes
    // on that switch).
    if (chosenModelOff()) return
    const eintrag = ausreihen(chatId)
    if (!eintrag) return
    senden(
      eintrag.inhalt, eintrag.bilder, eintrag.dokumente, eintrag.denken, eintrag.skill,
      false, null, eintrag.kept, eintrag,
    )
  }

  /* The ✕ on a waiting bubble: the message leaves the line and comes back
     into the field, with what was attached to it, so nothing typed is lost. */
  function takeBackQueued(eintrag) {
    entfernen(eintrag.id)
    eingabe?.takeBack(eintrag)
  }

  /* An answer stopped by hand while messages wait: they come back into the
     field of their chat, in the order they were written, in front of what
     stands there, and the line is empty. Without a field to give them to
     they stay in line and go on as after any end. */
  function giveBackQueued(chatId) {
    if (!eingabe) return
    const entries = takeAllOut(chatId)
    if (entries.length) eingabe.takeBackAll(entries, chatId)
  }

  /* By chat id, not on the run object: the run lies in a reactive list, and
     a field written through the stream's own reference is not reliably the
     one the list's copy reads. */
  const stoppedForQueued = new Set()
  /* The chats whose run the person stopped by hand (the stop button, the
     key): that stop counts even when a stop made for a waiting message is
     landing at the same time, so the waiting messages come back instead of
     going out after the press. */
  const stoppedByHand = new Set()

  /* What the stop button, the key and the phone's arrow call. */
  function abbrechenVonHand() {
    const chatId = zustand.aktiverChat
    if (chatId && (laufVon(chatId) || anspruchWarten.has(chatId))) stoppedByHand.add(chatId)
    return abbrechen()
  }

  /* A tool is going in this chat's answer: a call that was announced and has
     no result yet. The answer's own record says so, read as it stands. */
  function toolIsRunning(chatId) {
    return Boolean(
      zustand.laufenderPlatzhalter[chatId]?.werkzeuge?.some((w) => w.ergebnis === null),
    )
  }

  /* A message was typed while the open chat's answer runs: the answer is stopped
     at once and the message goes out as the next one (the queue moves on by
     itself when the run lets go). The partial text stays in the history. A
     tool call that was announced and has no result yet is not cut off — the
     message waits on its bubble and the tool's result wakes this again. */
  function interruptForQueued(chatId) {
    if (!laufVon(chatId) || toolIsRunning(chatId) || stoppedForQueued.has(chatId)) return
    // This stop is made for the waiting message, so the message is not given back.
    stoppedForQueued.add(chatId)
    markInterrupted(chatId)
    abbrechen()
  }

  /* `wiederanhang` (shape: { generationId, ab }) turns this into a resume
     instead of a new answer — used only by antwortWiederAnhaengen below.
     Everything past the very first stream source is shared: a resumed run
     drops and reconnects exactly like a freshly started one, through the
     same catch block a few lines down. */
  /* `redo` (shape: { replaces: id } or { retries: id }) names the chat's
     last answer this request is for instead of a turn of its own — see
     `neuErzeugen`. */
  async function antwortHolen(
    inhalt, bilder = null, dokumente = null, denken = null, skill = null, wiederanhang = null,
    gespraech = false, nachrichtId = null, redo = null, ausReihe = null,
  ) {
    /* The chat this run belongs to, fixed for its whole life. A fresh send
       and a visible reattachment both start with that chat on screen, so
       this is `aktiverChat` at entry — captured now because the user may
       switch away long before the run ends, and every place below that
       used to read `zustand.laeuft?.chatId ?? zustand.aktiverChat` means
       exactly this chat. */
    const zielChat = wiederanhang ? wiederanhang.chatId : zustand.aktiverChat

    /* A plain object is enough: as soon as it lies in a reactive list, it
       becomes reactive itself. Changes to it during streaming thus land
       in the window on their own. */
    /* Reattaching after a reload: the answer's row ALREADY stands in the
       list. The server writes it the moment the run starts
       (api/v1/generierung.py) and keeps it up to date WHILE the run goes,
       so `chatOeffnen`'s fetch from /messages brings it along — half
       written. Pushing a second placeholder here would put that one answer
       on screen twice: the stored half standing above the one growing out
       of the replayed stream.

       So on a resume that row is adopted instead — BY ITS ID, which the
       server now hands over with the run itself (`LaufendeGenerierung`).

       It used to be deduced, and that is what went wrong: the last row of
       the chat, of role assistant, whose stats carried no `abgebrochen`.
       The reasoning was that nothing is appended while a run lives, so the
       answer is necessarily last. Three writers append during a run — a
       finished background command, a picture from the picture window, a
       run's own picture row — and each of them matched all three tests.
       The wrong row was then adopted, blanked, and filled with the replayed
       stream, while the real answer stood untouched above it. The same text
       twice, and once more for every further reattach.

       Nothing is deduced any more: no id, no adoption. A row that cannot be
       found is not a candidate to guess at — the placeholder below is
       pushed instead, which is the same thing that happens for a run this
       window started itself.

       What IS adopted gets CLEARED, not kept: the stream is replayed from
       its very first event and delivers all of it again. The stored half is
       there for the case with no stream left to replay — a service that
       died in the middle of the run. */
    const uebernehmen = wiederanhang?.messageId
      ? zustand.nachrichten.find((n) => n.id === wiederanhang.messageId) ?? null
      : null
    if (uebernehmen) {
      uebernehmen.content = ''
      uebernehmen.reasoning = ''
      uebernehmen.werkzeuge = []
      uebernehmen.stats = {}
      uebernehmen.abschnitte = []
      uebernehmen.vision = wiederanhang ? frageTrugBild(uebernehmen) : Boolean(bilder?.length)
      /* Joined in the middle of the run: which activity it is in is not
         known until the replay says so. */
      taetigkeitUnbekannt(uebernehmen)
      uebernehmen.ziel = null
      /* Cleared too, and this one matters most: the row came from the
         server carrying `zustand: 'laeuft'`, and NOTHING in this window
         ever writes that field. Left standing, the bubble kept drawing
         itself as a running answer long after the run had ended — the
         waiting mark and its clock going, and the truncation notice
         suppressed, because that one is gated on `!laeuft`. The run this
         window is holding is known from `laufenderPlatzhalter` instead,
         which is cleared when it ends. */
      uebernehmen.zustand = null
      /* Cleared like the rest, and for the same reason: the replay hands out
         every `kontext` event of the run again, so it refills at once. Kept
         instead, a reading from before a compaction would stand as the
         current one until the next event happened to arrive. */
      uebernehmen.gesamt_tokens = null
    }
    /* The failed answer a retry goes on in (`redo.retries`): the same row,
       found by its id like an adopted one. Unlike an adopted one it is left
       as it stands until the service says the run has begun — a request the
       service turns away has then changed nothing on screen. At `start` it
       is emptied of the very fields the adoption above empties, because
       that stream opens with everything the run had done before it failed
       (app/answer_replay.py). */
    const retried = redo?.retries
      ? zustand.nachrichten.find((n) => n.id === redo.retries) ?? null
      : null
    const retriedState = retried?.zustand ?? null
    if (retried) {
      /* A stored row carries neither of the two lists a running answer is
         drawn from. Empty, they change nothing on screen — the bubble
         draws a row without them from what is stored — and the stream's
         handlers find them there from its very first event on. */
      retried.abschnitte ??= []
      retried.werkzeuge ??= []
      retried.vision = frageTrugBild(retried)
      taetigkeitSetzen(retried, 'kontext', undefined, true)
    }
    if (!uebernehmen && !retried) zustand.nachrichten.push({
      // Stable key, same reason as the picture placeholder's `bildlauf-`
      // (see zustand.svelte.js): a message keyed by its POSITION is the
      // same message as whatever stood there before it. One running answer
      // per chat, so the chat's id is enough to tell them apart.
      id: `platzhalter-${zielChat}`,
      role: 'assistant', content: '', reasoning: '', stats: {}, werkzeuge: [],
      /* How full the context is, refilled by the `kontext` event below as
         the answer runs. Declared here for the same reason `ziel` is: the
         answer should start out plainly saying that nothing has been
         reported yet, rather than gaining the field halfway through. */
      gesamt_tokens: null,
      /* The reported goal, once the `goal` tool has named one (the SSE
         event `ziel` below). Declared here rather than only being set
         later, so the answer starts out saying plainly that nothing has
         been reported yet. */
      ziel: null,
      /* The live readings of the running round — set from the stream,
         ended by `lesungenLeeren`. Declared here like `ziel` above, so the
         answer starts out plainly saying that nothing has been reported
         yet. */
      liveSpeed: null,
      liveShare: null,
      /* The order things actually happened in. `content`, `reasoning` and
         `werkzeuge` above stay exactly as they were — they are the STORE,
         read by the stats foot, the copy button and the server reconcile.
         This list is the ORDER, and only that: each entry says which kind
         came next, so a second thinking block after a first paragraph is
         drawn where it happened instead of being folded back into the one
         reasoning string at the top.
         A message without it (every chat loaded from the server) falls back
         to the old fixed order in Nachricht.svelte — old chats must not
         change. */
      abschnitte: [],
      /* If the question carried an image, the waiting line shows the eye
         mark — image recognition is recognizable as its own state. Not
         guessed from `bilder` alone: a row pushed for a REATTACH has no
         send of its own to ask, and the question it answers is the last one
         in the list. */
      vision: wiederanhang ? frageTrugBild(null) : Boolean(bilder?.length),
      /* What the run is doing right now: 'kontext' right after sending and
         again after every tool result, 'denkt', 'werkzeug', 'schreibt' as
         the stream says. `taetigkeitSeit` is when the present activity
         began — the waiting mark's clock counts from it (laufMarke). */
      taetigkeit: wiederanhang ? null : 'kontext',
      taetigkeitSeit: wiederanhang ? null : Date.now(),
    })
    const platzhalter = uebernehmen ?? retried ?? zustand.nachrichten[zustand.nachrichten.length - 1]
    /* Held here too, not just in the message list: switching chats while
       this runs replaces `zustand.nachrichten` wholesale with the server's
       fetch (zustand.svelte.js, chatOeffnen) — losing the array entry, but
       not this reference. chatOeffnen puts the SAME object back when
       reopening the chat this run belongs to. Keyed by chat so a second run
       in another chat keeps its own placeholder. */
    zustand.laufenderPlatzhalter[zielChat] = platzhalter
    /* How many files the answers before this one carry. File names count
       across the whole chat (lib/markdown.js, dateienDavor), and the list
       is the chat's only while it is the one on screen — the run itself
       goes on in the background after a switch, so the number is taken
       here, once, from the list this run began in. */
    const dateienVorher = zustand.nachrichtenChatId === zielChat
      ? dateienDavor(zustand.nachrichten, platzhalter)
      : 0
    // A row taken over (a retry, a reattach) may carry the end of an earlier run.
    platzhalter.runEnded = false

    /* Text lands in the section that is already open, or opens a new one.
       Two thinking passes separated by a paragraph therefore stay two
       sections — which is the whole point — while one uninterrupted pass
       stays one, however many chunks it arrived in. */
    const textAnhaengen = (art, text, zeitpunktMs) => {
      const letzter = platzhalter.abschnitte[platzhalter.abschnitte.length - 1]
      if (letzter && letzter.art === art) {
        letzter.text += text
        // Thinking that goes on after a passing event is still one stretch.
        delete letzter.endedAt
      } else platzhalter.abschnitte.push({ art, text, seit: zeitpunktMs ?? Date.now() })
    }
    /* A thinking stretch ends with the first event that is not thinking,
       at that event's own time — not when the next section opens. A tool
       confirmation opens no section, and a stretch measured up to the next
       one counted the whole wait on the person as thinking. */
    const endThinking = (zeitpunktMs) => {
      const letzter = platzhalter.abschnitte[platzhalter.abschnitte.length - 1]
      if (letzter?.art === 'reasoning' && letzter.endedAt == null) {
        letzter.endedAt = zeitpunktMs ?? Date.now()
      }
    }
    /* A tool is referenced by its call id, never by the object: the entry in
       `werkzeuge` is filled in later by tool_result, and a copy taken here
       would keep showing the empty result. */
    const werkzeugAnhaengen = (aufrufId, zeitpunktMs) => {
      platzhalter.abschnitte.push({ art: 'werkzeug', aufruf_id: aufrufId, seit: zeitpunktMs ?? Date.now() })
    }
    /* A call has its row from the moment the model begins to write it, not
       only once it is complete: a long argument takes the model a minute,
       and all that while the answer showed a waiting word and no call.

       Such a row is a section without a call id — the id only exists once
       the call is complete — that says under `writing` which call of the
       round it is, its name and how many characters of it are written. The
       complete call takes the row over (`rowOfCall`), so it is one row from
       the first character to the result. */
    const dropRows = (which) => {
      if (platzhalter.abschnitte.some(which)) {
        platzhalter.abschnitte = platzhalter.abschnitte.filter((a) => !which(a))
      }
    }
    /* Whether rows stand that are written out and wait for their turn. A
       round that was cut off answers only the call it was cut at; the rows
       of its other calls never begin. They go the moment the model writes
       or thinks again — only then is it certain their turn will not come. */
    let rowsWaiting = false
    const modelGoesOn = () => {
      if (!rowsWaiting) return
      rowsWaiting = false
      dropRows((a) => a.writing?.written === null)
    }
    const callBeingWritten = (index, name, written, zeitpunktMs) => {
      modelGoesOn()
      const row = platzhalter.abschnitte.find((a) => a.writing?.index === index)
      if (row) row.writing = { index, name, written }
      else {
        platzhalter.abschnitte.push({
          art: 'werkzeug',
          aufruf_id: null,
          writing: { index, name, written },
          seit: zeitpunktMs ?? Date.now(),
        })
        runter()
      }
    }
    /* A complete call says the round's stream has ended, so every call of
       the round is written: the rows still waiting for their turn stop
       counting and keep their name. The call takes the row it was written
       in — the first of its name, calls begin in the order they were
       written. Handed back, or nothing for a call that was never reported
       while it was written. */
    const writtenRow = (aufrufId, name) => {
      for (const a of platzhalter.abschnitte) if (a.writing) a.writing.written = null
      const row = platzhalter.abschnitte.find((a) => a.writing?.name === name)
      if (row) {
        row.aufruf_id = aufrufId
        delete row.writing
      }
      rowsWaiting = platzhalter.abschnitte.some((a) => a.writing)
      return row
    }
    // The row of a call that is complete: the one it was written in, or a
    // new one at the end, as before.
    const rowOfCall = (aufrufId, name, zeitpunktMs) => {
      if (!writtenRow(aufrufId, name)) werkzeugAnhaengen(aufrufId, zeitpunktMs)
    }
    /* The run is over. A call still being written never became a call, and
       one that got its row at its permission question (`asked`) and was
       never answered never ran: their rows go, no half row stays. */
    const dropRowsNeverBegun = () => {
      for (const row of platzhalter.abschnitte.filter((a) => a.asked)) {
        const at = platzhalter.werkzeuge.findLastIndex(
          (w) => w.aufruf_id === row.aufruf_id && w.ergebnis === null,
        )
        if (at >= 0) platzhalter.werkzeuge.splice(at, 1)
      }
      dropRows((a) => a.writing || a.asked)
    }
    /* A question of this run that is settled comes down — keyed by call id,
       so only the one that was actually answered goes. */
    const frageAbnehmen = (aufrufId, ...kaesten) => {
      for (const kasten of kaesten) if (kasten[zielChat]?.aufrufId === aufrufId) delete kasten[zielChat]
    }

    /* ONE notice for the whole answer, rewritten as the work moves on.

       It used to be one per call and one per phase: a notice while the model
       was still typing the arguments, that one CLOSED and a second opened
       the moment the call really started, and a third state when the result
       came back. Two tools were six notices appearing and vanishing in a few
       seconds — and with three the most that stand at once, the stack shoved
       itself through the whole time.

       Rewriting was already how the result was reported; it simply was not
       used for the step before it. Now nothing is closed and reopened:
         write_file wird geschrieben → write_file … → write_file fertig
       and the next call continues in the same notice.

       Keyed per CHAT, not per call: two chats can run at once and each
       deserves its own line, but within one answer there is one. */
    const werkzeugToast = `werkzeug:${zielChat}`
    /* `dauer` is for the one state that may not keep the kind's own clock:
       zero everywhere else, so nothing but the caller that asks for it is
       touched. Handed to both paths below, because a notice that was pushed
       out and rebuilt has to stand exactly as long as one that was
       rewritten — otherwise the same event lasts two different times by a
       circumstance nobody can see. */
    const werkzeugSagen = (pfad, werte, art, dauerhaft, dauer = 0, server = '') => {
      const vorhanden = werkzeugMeldungen.get(werkzeugToast)
      if (
        vorhanden
        && aktualisiereMeldung(vorhanden, {
          text: t(pfad, werte), art, dauerhaft, dauer,
          schluessel: pfad, werte, werkzeug: werte.name ?? '', server,
        })
      ) return
      /* Nothing to rewrite — either the first call of this answer, or the
         notice was pushed out by newer ones. Either way a fresh one, and the
         key points at it from here on.

         Silent, always. A rewrite never rings, so without this a failed tool
         would ring only when its notice happened to have been pushed out —
         the same event sounding or not by a circumstance that has nothing to
         do with it. The chat's own failure sound is unaffected; this is the
         running commentary of one answer, and a commentary does not ring. */
      werkzeugMeldungen.set(
        werkzeugToast,
        meldeText(pfad, werte, art, {
          dauerhaft, dauer, werkzeug: werte.name ?? '', server, stumm: true,
        }),
      )
    }

    const abbruch = new AbortController()
    /* The local handle every branch below writes through and reads from —
       `zustand.laeuft[zielChat]` is the same object, but going through a
       local reference keeps a chat switch (which cannot touch this closure)
       from ever pointing these reads at another chat's run. */
    const lauf = {
      abbruch, generationId: wiederanhang?.generationId ?? null, chatId: zielChat,
    }
    zustand.laeuft[zielChat] = lauf
    /* Carries this answer's files into the rail: the first sight of a file
       opens its tab, every later one only follows it (tabWriter).

       A file is a fresh occasion for the rail — but only in the
       conversation the reader is actually in. A run finishing in the
       background must not reach over and open a panel on somebody else's
       chat, which is what clearing the dismissal unconditionally did. */
    const carryFile = tabWriter(zielChat, () => {
      const onScreen = zielChat === zustand.aktiverChat
      if (onScreen && leiste.nichtAufdraengen === 'vorschau') leiste.nichtAufdraengen = ''
      return onScreen
    })
    /* Whether a file is being written right now, and whether the text
       ended in a fence that was not settled yet — what lets the next piece
       of plain text be told apart from one that needs a look at all. */
    let fileGrowing = false
    let fenceUnsettled = false
    let abgebrochen = false
    /* Whether this run ended cleanly decides whether the queue moves on.
       A stream-level error counts as failed even when text had already
       arrived: what comes after it is half an answer, and the next message
       would be asked against a state nobody has looked at. */
    let gescheitert = false
    /* The service already holds this chat — an answer it started by itself
       is going. Not a failure of this send: the words go back into the
       field, the bubble comes down, and the window attaches to the run
       that is really going. */
    let belegt = false
    /* Whether a drawing call of this run is going: its working tile goes
       with the run when the run ends without the call's result (stopped,
       or the line broke). */
    let drawing = false
    /* The id of a summary this run folded, or null. Only the server knows:
       the fold happens before the stream opens, so nothing on screen would
       otherwise change until the chat is reopened. */
    let verdichtetZu = null
    /* Whether this answer's running tool notice is still standing on its own
       clock — set while the model is writing the call or the call itself is
       going, cleared the moment a result rewrites it into "fertig" or
       "fehlgeschlagen". Read in the `finally` below: a notice still open
       here means the answer ended with no result ever arriving for it. */
    let werkzeugOffen = false
    /* The notice that said "is being written" is out of date once the call is
       complete and asks for an answer — a permission, a question, a job to
       confirm. It comes down, and the card over the chat is what says
       "waiting". Only while it is still that notice: after a finished tool it
       is the "done" line running its own clock down. */
    function schreibendeMeldungSchliessen() {
      if (!werkzeugOffen) return
      const schreibend = werkzeugMeldungen.get(werkzeugToast)
      if (schreibend) schliesseMeldung(schreibend)
      werkzeugMeldungen.delete(werkzeugToast)
      werkzeugOffen = false
    }
    let schlussZustand = null
    /* Whether the service said this run has begun (`start`). A retry that
       never got that far has not touched its answer. */
    let begun = false
    /* A new answer written in another one's place, as its `done` puts it:
       the id of the answer it took the place of, or that the new one was
       dropped because it did not finish (app/api/v1/generierung.py). Read
       off the event and not off `redo`, so a window that only attached to
       such a run — after a reload — takes the same row down. */
    let replacedId = null
    let discarded = false
    /* Whether the service's closing event (`done`) came at all. A run that
       ends without it — stopped from this window, a line that broke for good
       — has not said what became of the answer it was to replace. */
    let doneSeen = false
    let fremderLauf = null
    let heldWithoutRun = false
    /* Whether a message of the queue was turned away because another window
       holds the chat, and went back in line: the run lets go below, waits
       for the claim the way the end of a held chat does, and the queue then
       sends it again. */
    let zurueckInReihe = false
    /* Whether the stored row has to be fetched instead of replayed: a
       reattach the service refused, or a run it no longer knows. Both leave
       the window with a row and no stream behind it, and without the fetch
       that row stood empty ("nothing written") until the chat was opened
       again. Read once, in the reconcile at the foot of this `finally` —
       the one place allowed to replace the list. */
    let zeileNachladen = false

    /* A question about the run, bounded by the reconcile's deadline and
       still ended by the person's stop. Its running out is a TimeoutError,
       not an AbortError: the wait is over, nobody pressed stop. */
    function withDeadline(signal) {
      const deadline = AbortSignal.timeout(NACHLADE_FRIST_MS)
      if (!signal) return deadline
      // An engine without `AbortSignal.any` keeps the stop and goes without
      // the deadline, rather than failing every question.
      return typeof AbortSignal.any === 'function' ? AbortSignal.any([signal, deadline]) : signal
    }

    /* A pause that the person's stop cuts short. The stop's listener goes
       when the clock wins, so a wait of minutes does not pile one up on
       the signal for every tick. */
    function pauseOrStop(ms, signal) {
      if (signal?.aborted) return Promise.resolve()
      return new Promise((done) => {
        const clock = setTimeout(() => {
          signal?.removeEventListener('abort', onStop)
          done()
        }, ms)
        const onStop = () => {
          clearTimeout(clock)
          done()
        }
        signal?.addEventListener('abort', onStop, { once: true })
      })
    }

    /* Asks about the chat until a claim on it turns into a run or goes.
       Gives back the run the service names (`run`), or none — the chat is
       free — and whether the service answered at all (`reachable`). No
       clock of its own: a claim is released on every way out of the setup
       (app/generationen.py, `freigeben`), a service that stops answering
       ends the asking too, and every single question has the reconcile's
       deadline, so a proxy that holds one open cannot hold the chat with
       it. One row, not the whole page: the two flags this asks about are
       computed beside the page, and the page itself costs a JSON parse per
       row, a document lookup per document message and a count over the
       chat — twice a second, for a fold that lasts minutes
       (app/api/v1/chats.py, nachrichten_auflisten). */
    async function claimOutcome(chatId, signal) {
      while (true) {
        let answer
        try {
          answer = await api.nachrichten(chatId, { signal: withDeadline(signal), limit: 1 })
        } catch {
          return { run: null, reachable: false }
        }
        if (answer?.laufend?.generation_id) return { run: answer.laufend, reachable: true }
        if (!answer?.gehalten) return { run: null, reachable: true }
        /* Woken by the stop, not only by the clock: a wait that outlives
           the person's own stop would hold the chat with no run behind it
           (the next question then throws, and the asking ends). */
        await pauseOrStop(HALTEPRUEFUNG_MS, signal)
      }
    }

    /* Whether the row `antwortId` stands behind this send's question with no
       other question between the two — the one place an answer to this
       question can stand. Unknown where the row is not among the newest
       rows or the list cannot be read: then it is taken as the own. The
       question left out of the newest rows by nothing but the window's
       edge (the row is the oldest one) is the own as well; any other row
       without its question has none of this send. */
    async function antwortetAufEigene(chatId, antwortId, signal) {
      let recent
      try {
        recent = await api.nachrichten(chatId, { signal: withDeadline(signal), limit: 50 })
      } catch {
        return true
      }
      const reihe = recent?.nachrichten ?? []
      const antwort = reihe.findIndex((n) => n.id === antwortId)
      if (antwort < 0) return true
      const frage = reihe.findIndex((n) => n.id === nachrichtId)
      if (frage < 0) return antwort === 0
      if (antwort < frage) return false
      return !reihe
        .slice(frage + 1, antwort)
        .some((n) => n.role === 'user' && (n.art ?? 'nachricht') === 'nachricht')
    }

    /* Where the answer of a line that broke too early went. Broken BEFORE
       the service named the run, there is no id to reattach to — this is
       the stretch in which the service folds the history, and a fold costs
       a whole model request, seconds to minutes (app/chatverdichtung.py).
       Calling that a failed send was the defect: the answer came anyway,
       into a chat whose window had already written it off, and the stopped
       or broken send was drawn as failed while the service was still
       working.

       Asking about the chat answers one of three things, and each has its
       own way out: a run — "run", and the caller attaches to it from the
       first event, nothing of it has been seen here; a held chat with no
       run yet — wait, and ask again; neither — the run began and ended
       between two questions, or never began: the stored history decides.
       This send's own question stored with an answer behind it — "stored",
       and the stored history is fetched instead of a stream, with whatever
       the run left behind it and the state it ended in (the way
       `weiterZusehen` lets a run it lost stand); the question missing — the
       send never arrived — or stored with no answer behind it — the run
       broke after it stored the question (a fold that threw, a line that
       went) — and the caller fails it (false).
       Only an answer counts: a tool report or a fold's summary between the
       two is no answer to the question. The asking itself is
       `claimOutcome`'s. */
    async function nachholen(laufJetzt, chatId, signal) {
      const { run, reachable } = await claimOutcome(chatId, signal)
      if (!reachable) return false
      if (run) {
        /* A run the service names for the chat is only this send's own when
           its row answers this send's question. Another window may have sent
           since — this send ended without a run — and its answer would
           stream into this bubble with no error. A send that gave its
           question an id and a run that names its row are compared in the
           stored rows; anything else attaches as before. */
        if (nachrichtId && run.message_id && !(await antwortetAufEigene(chatId, run.message_id, signal))) {
          return false
        }
        laufJetzt.generationId = run.generation_id
        return 'run'
      }
      if (!nachrichtId && !redo?.replaces) return false
      /* The newest rows, oldest first: is this send's question among them?
         Fifty leave room for a run that filed its pictures as rows of their
         own behind it. */
      let recent
      try {
        recent = await api.nachrichten(chatId, { signal: withDeadline(signal), limit: 50 })
      } catch {
        return false
      }
      const reihe = recent?.nachrichten ?? []
      if (!nachrichtId) {
        /* A regeneration has no question of its own to look for. The service
           takes the replaced answer away in the very step that stores the new
           one as finished (app/answer_redo.py): the replaced answer gone from
           the newest rows with an answer standing last says the new one is
           stored; the replaced one still there says nothing was written. */
        const letzte = reihe[reihe.length - 1]
        const gespeichert =
          letzte != null &&
          !reihe.some((n) => n.id === redo.replaces) &&
          letzte.role === 'assistant' &&
          (letzte.art ?? 'nachricht') === 'nachricht'
        if (!gespeichert) return false
        zeileNachladen = true
        return 'stored'
      }
      const stelle = reihe.findIndex((n) => n.id === nachrichtId)
      if (stelle < 0) return false
      const beantwortet = reihe
        .slice(stelle + 1)
        .some((n) => n.role === 'assistant' && (n.art ?? 'nachricht') === 'nachricht')
      if (!beantwortet) return false
      zeileNachladen = true
      return 'stored'
    }

    try {
      const koerper = { chat_id: zielChat, endpoint_id: zustand.modellId }
      if (inhalt) koerper.content = inhalt
      // Names the row the service is about to store, before it stores it —
      // see `frageKennung` in senden() for why.
      if (nachrichtId) koerper.nachricht_id = nachrichtId
      if (bilder?.length) koerper.bilder = bilder
      if (dokumente?.length) koerper.dokumente = dokumente
      /* The thinking stage, as the key it is ("off", "low", "high" ...).
         Only sent when there is one: a model with nothing to set sends
         nothing, and the server keeps its own default. */
      if (typeof denken === 'string' && denken) koerper.thinking = denken
      // A picked skill: the service puts its instruction in front of this
      // message and keeps it with the message (app/verlaufsbau.py).
      if (skill) koerper.skill = skill
      // The spoken side of a live conversation — turns on the conversation
      // instruction server-side (app/verlaufsbau.py), never a typed chat.
      if (gespraech) koerper.gespraech = true
      // The user cut the previous spoken answer short: one line for the
      // model in this request only (app/diktatsprachewahl.py).
      if (gespraech?.unterbrochen) koerper.unterbrochen = true
      /* The arrow under the last answer: which answer this request is for
         — a new one in its place, or its failed call asked again. */
      if (redo?.replaces) koerper.replaces = redo.replaces
      if (redo?.retries) koerper.retries = redo.retries

      /* Counts every event actually handled — the position to resume from
         if the connection itself drops (below), not a byte offset. */
      let ereignisZahl = 0
      const ereignisVerarbeiten = async (strom) => {
      for await (const ereignis of strom) {
        ereignisZahl++
        // The speed reading arrives while the model thinks; it is no end.
        if (ereignis.typ !== 'reasoning' && ereignis.typ !== 'denktempo') {
          endThinking(ereignis.zeitpunkt_ms)
        }
        // The model thinks or writes again: the round before is over.
        if (ereignis.typ === 'reasoning' || ereignis.typ === 'content') modelGoesOn()
        if (ereignis.typ === 'start') {
          lauf.generationId = ereignis.generation_id
          /* A retry has begun: everything the failed run had done arrives
             again right behind this event, so the row is emptied for it
             here — and on every `start`, a stream watched anew from its
             first event brings all of it once more. */
          if (retried) {
            Object.assign(retried, {
              content: '', reasoning: '', werkzeuge: [], stats: {}, abschnitte: [],
              ziel: null, zustand: null, gesamt_tokens: null,
            })
          }
          begun = true
          platzhalter.id = ereignis.message_id
          /* The stream opens once the fold before it is over; a
             "compressing" the program's line put on this row has said its
             piece. Plain content sets no activity of its own, so it is
             taken back here rather than left standing under the answer. */
          if (platzhalter.taetigkeit === 'verdichtung') platzhalter.taetigkeit = 'kontext'
          /* The very first `kontext` stretch of a run this window sent: it
             counts from the moment the round actually began, not from the
             moment of sending. A reattached row has no activity yet and is
             left that way — claiming one here would be a guess. */
          if (ereignis.zeitpunkt_ms != null && platzhalter.taetigkeit === 'kontext') {
            platzhalter.taetigkeitSeit = ereignis.zeitpunkt_ms
          }
        } else if (ereignis.typ === 'reasoning') {
          /* The reasoning text itself carries no speed of its own — a
             separate `denktempo` event does that, only when the server
             actually names one. */
          platzhalter.reasoning += ereignis.text
          textAnhaengen('reasoning', ereignis.text, ereignis.zeitpunkt_ms)
          taetigkeitSetzen(platzhalter, 'denkt', ereignis.zeitpunkt_ms)
          runter()
        } else if (ereignis.typ === 'denktempo') {
          /* The server's own reading of how fast it is producing right now,
             while it thinks and while it writes the answer. It stands under
             the running answer (Nachricht.svelte) while the round that named
             it writes; that round ends at a tool or with the answer, and the
             reading goes with it (`lesungenLeeren`) — the finished answer's
             figure comes out of the stats. A server that names no reading
             sends none, and then nothing stands there. */
          /* Either half may be missing: a server that names a cache share but
             no usable speed has something to say under the running answer,
             and one that names only a speed says nothing about the cache. So
             each field is set when it is there and left alone when it is not
             — a reading with neither never leaves the provider at all.
             The share has its own field, like the speed beside it, and ends
             by the same rule as the speed. A stream that is picked up again
             after a dropped connection keeps it — it is the same chat and
             the same answer, and the reading belongs to them. */
          if (typeof ereignis.tokens_pro_sekunde === 'number') {
            platzhalter.liveSpeed = {
              wert: ereignis.tokens_pro_sekunde,
              quelle: ereignis.tempo_quelle,
            }
          }
          if (typeof ereignis.prompt_cache_percent === 'number') {
            platzhalter.liveShare = ereignis.prompt_cache_percent
          }
        } else if (ereignis.typ === 'content') {
          platzhalter.content += ereignis.text
          textAnhaengen('content', ereignis.text, ereignis.zeitpunkt_ms)
          /* Writing is an activity of its own: the thinking is over the
             moment the answer's text begins, bare line breaks included.
             The waiting mark stays under the text until the run ends
             (laufMarke). */
          taetigkeitSetzen(platzhalter, 'schreibt', ereignis.zeitpunkt_ms)
          /* A file opens its tab the moment its fence OPENS and grows in
             it from there — waiting for the closing fence meant the rail
             stayed empty for as long as a document was being written, and
             waiting for the whole answer meant nothing happened at all.

             The tab is opened ONCE per file. Every further piece, the
             last one included, only follows it: a tab the reader closed
             while the file was still being written stays closed, also when
             the fence closes (carryFile above).

             Only looked for when it can matter: a fence cannot open or
             close without a backtick, and a file that is growing grows
             with every piece. A fence the last piece left unsettled counts
             as well — "```" closes a file, and "bash" one piece later makes
             those same marks the opening of a block inside it, so the file
             is open again; and "markdown" behind them is where a document
             begins. Scanning the whole accumulated answer on every chunk
             of plain prose turns a long answer into quadratic work on the
             same tick that draws it. */
          const fenceMoved = ereignis.text.includes('`') || fenceUnsettled
          if (fenceMoved) {
            // A file that was open and has closed gets its last piece here;
            // one that arrived whole is seen for the first time.
            for (const file of dateienAus(platzhalter.content, dateienVorher)) carryFile(file)
          }
          if (fenceMoved || fileGrowing) {
            const unfinished = openFile(platzhalter.content, dateienVorher)
            fileGrowing = !!unfinished
            if (unfinished) carryFile(unfinished)
            fenceUnsettled = endsInFence(platzhalter.content)
          }
          runter()
        } else if (ereignis.typ === 'tool_confirm' && ereignis.settled) {
          /* A permission the service marks as settled: a reattach replays it
             long after the answer. Its call draws the line and nothing is
             waiting any more, so there is no box and no sound. */
        } else if (ereignis.typ === 'tool_confirm') {
          /* The server only ever sends this when Tor 3 itself says "fragen"
             for THIS call — a standing yes from an earlier "immer erlauben"
             (Schritt 12) is a real rule in berechtigungen.json by now, and
             Tor 3 already answered "ja" before this event could exist. No
             client-side memory left to check here. */
          /* The server halts and waits. No toast for this — the card over
             the chat is conspicuous enough, and two notices for the same
             thing is one too many. */
          /* The program is waiting for an answer — the one case where a
             sound is worth it, because nothing moves until somebody
             comes back. */
          melden({ was: 'wartet', von: 'chat' })
          schreibendeMeldungSchliessen()
          // The run stands at a tool now: the thinking is over.
          taetigkeitSetzen(platzhalter, 'werkzeug', ereignis.zeitpunkt_ms, true)
          lesungenLeeren(platzhalter)
          /* The call is complete and waits for a yes. The row it was
             written in is its row from here on, not a line that still says
             "being written" — marked `asked` until the call starts; a call
             without such a row gets its row when it starts, as before. */
          const asked = writtenRow(ereignis.aufruf_id, ereignis.name)
          if (asked) {
            asked.asked = true
            platzhalter.werkzeuge.push({
              aufruf_id: ereignis.aufruf_id,
              name: ereignis.name,
              server: '',
              argumente: ereignis.argumente,
              ergebnis: null,
              fehlgeschlagen: false,
            })
          }
          zustand.werkzeugfrage[zielChat] = {
            generationId: lauf.generationId,
            aufrufId: ereignis.aufruf_id,
            name: ereignis.name,
            argumente: ereignis.argumente,
            // The RUN's chat, not whatever is on screen: whoever switched
            // away must not find a foreign question hanging over their
            // input field.
            chatId: zielChat,
            // Why this call is being asked about — empty when the tool is
            // simply configured to always ask.
            grund: ereignis.grund || '',
            grundWert: ereignis.grund_wert || '',
          }
        } else if (ereignis.typ === 'user_ask') {
          /* The model wants a decision that belongs to the user. The run
             stands still until it gets one. A question the service marks as
             settled is only history on a reattach: its line goes into the
             answer, and nothing else — no sound, no box. */
          if (!ereignis.settled) {
            melden({ was: 'wartet', von: 'chat' })
            schreibendeMeldungSchliessen()
            // The run stands at a tool now: the thinking is over.
            taetigkeitSetzen(platzhalter, 'werkzeug', ereignis.zeitpunkt_ms, true)
            lesungenLeeren(platzhalter)
          }
          /* The question also lands in the history like any other tool
             call: the server sends no tool_call for ask_user, so the entry
             is created here — the tool_result later fills it, and question
             plus answer stay visible as a block instead of vanishing. */
          platzhalter.werkzeuge.push({
            aufruf_id: ereignis.aufruf_id,
            name: 'ask_user',
            server: '',
            argumente: { question: ereignis.frage },
            ergebnis: null,
            fehlgeschlagen: false,
          })
          rowOfCall(ereignis.aufruf_id, 'ask_user', ereignis.zeitpunkt_ms)
          if (!ereignis.settled) {
            zustand.benutzerfrage[zielChat] = {
              generationId: lauf.generationId,
              aufrufId: ereignis.aufruf_id,
              frage: ereignis.frage,
              optionen: ereignis.optionen || [],
              // The RUN's chat, not whatever is on screen — the sidebar
              // lights the right row by it, and the box only shows there.
              chatId: zielChat,
              // Which question of this run this is — the box wears the
              // count as a small pill.
              nummer: platzhalter.werkzeuge.filter((w) => w.name === 'ask_user').length,
            }
            /* The question is only ever asked once its permission was
               granted, so a permission still standing for this very call is
               one a reattach replayed from the run's start. Left standing, the
               box would show that old permission instead of the question, and
               a yes to it would land on the question's own wait. */
            frageAbnehmen(ereignis.aufruf_id, zustand.werkzeugfrage)
            runter()
          }
        } else if (ereignis.typ === 'job_confirm') {
          /* start_job: the task appears EDITABLE before the run begins —
             whatever the user confirms is what runs, and cancel starts
             nothing. Same standing-still as a user question — and, settled
             on a reattach, the same history-only line. */
          if (!ereignis.settled) {
            melden({ was: 'wartet', von: 'chat' })
            schreibendeMeldungSchliessen()
            // The run stands at a tool now: the thinking is over.
            taetigkeitSetzen(platzhalter, 'werkzeug', ereignis.zeitpunkt_ms, true)
            lesungenLeeren(platzhalter)
          }
          platzhalter.werkzeuge.push({
            aufruf_id: ereignis.aufruf_id,
            name: 'start_job',
            server: '',
            argumente: { agent: ereignis.agent, task: ereignis.task },
            ergebnis: null,
            fehlgeschlagen: false,
          })
          rowOfCall(ereignis.aufruf_id, 'start_job', ereignis.zeitpunkt_ms)
          if (!ereignis.settled) {
            zustand.jobfrage[zielChat] = {
              generationId: lauf.generationId,
              aufrufId: ereignis.aufruf_id,
              agent: ereignis.agent,
              task: ereignis.task,
              chatId: zielChat,
            }
            runter()
          }
        } else if (ereignis.typ === 'exemd_zu_gross') {
          /* A shared folder's exe.md has grown past the point where it eats
             the context of every single request. Quiet — this is a caution,
             not a failure, and the file still travels whole either way.
             Sent once per chat and folder, decided on the service side, so
             this needs no memory of its own. */
          meldeText(
            'ordnerwissen.zu_gross',
            { ordner: ereignis.ordner, zeichen: ereignis.zeichen },
            'warnung',
          )
        } else if (ereignis.typ === 'tool_call_laeuft') {
          /* The model is still WRITING the call. Nothing has run yet, so
             this is not the tool notification below — it is the answer to
             "is anything happening at all", during minutes in which the
             window otherwise shows nothing while data flows the whole time.

             Rewritten as the argument grows rather than stacked, and keyed
             by the call's index because the id only exists once the call is
             complete. The tool notification below replaces it the moment the
             call really starts. */
          werkzeugSagen(
            'werkzeug.schreibt',
            { name: ereignis.name, zeichen: ereignis.zeichen ?? 0 },
            'werkzeug',
            true,
          )
          werkzeugOffen = true
          // The same in the answer: the call's row, counting along.
          callBeingWritten(ereignis.index ?? 0, ereignis.name, ereignis.zeichen ?? 0, ereignis.zeitpunkt_ms)
          taetigkeitSetzen(platzhalter, 'werkzeug', ereignis.zeitpunkt_ms)
        } else if (ereignis.typ === 'tool_call') {
          /* The same notice moves on: it was reporting the argument being
             written, and now reports the call itself. Stays up until the
             result is in. */
          /* The server comes with the call itself — while the model was
             still writing it there was none to name, and the mark was the
             one the tool's name alone finds. */
          werkzeugSagen(
            'werkzeug.laeuft', { name: ereignis.name }, 'werkzeug', true, 0,
            ereignis.server || '',
          )
          werkzeugOffen = true
          // Also attached to the message: the notification disappears
          // again, but the history should keep a traceable record of what
          // ran.
          const asked = platzhalter.abschnitte.find(
            (a) => a.asked && a.aufruf_id === ereignis.aufruf_id,
          )
          if (asked) {
            // The row has stood since its permission was asked for.
            delete asked.asked
            const held = platzhalter.werkzeuge.findLast((w) => w.aufruf_id === ereignis.aufruf_id)
            held.server = ereignis.server || ''
            held.argumente = ereignis.argumente
          } else {
            platzhalter.werkzeuge.push({
              aufruf_id: ereignis.aufruf_id,
              name: ereignis.name,
              // Which server it came from — the catalogue picks the mark by it.
              server: ereignis.server || '',
              argumente: ereignis.argumente,
              ergebnis: null,
              fehlgeschlagen: false,
            })
            /* The row it was written in becomes its row — no second one —
               and a call that was never reported while being written gets
               its row here. */
            rowOfCall(ereignis.aufruf_id, ereignis.name, ereignis.zeitpunkt_ms)
          }
          // A picture or a video being made: the picture window's working tile.
          if (isDrawingTool(ereignis.name)) {
            drawing = true
            drawingStarted(zielChat, platzhalter.id)
          }
          /* A permission is settled once its call runs. Live the box is
             gone already (the answer took it down); on a resume the replay
             put it back with its `tool_confirm`, and it would otherwise
             stand over a running tool until the tool's result. */
          frageAbnehmen(ereignis.aufruf_id, zustand.werkzeugfrage)
          // A tool runs: the waiting mark stays on the line with a waiting
          // word and a fresh clock, under the tool's own row — fresh even
          // after the arguments were written or a permission was given.
          taetigkeitSetzen(platzhalter, 'werkzeug', ereignis.zeitpunkt_ms, true)
          lesungenLeeren(platzhalter)
          runter()
        } else if (ereignis.typ === 'tool_result') {
          /* The result belongs to the oldest call of this id that still
             waits for one, the way the service stores it: a server without
             ids of its own numbers every round from zero, so the same id
             stands for several calls, and an entry that has its result is
             never written over. */
          let eintrag = platzhalter.werkzeuge.find(
            (w) => w.aufruf_id === ereignis.aufruf_id && w.ergebnis === null,
          )
          if (!eintrag) {
            /* A call the service turned away before it announced it (an
               invalid question, a refused job) has only its result. It gets
               its own entry and its row here — the row it was written in, or
               one at this place in the answer — the row a stored answer
               shows for it after the chat is opened again
               (app/answer_sections.py). */
            platzhalter.werkzeuge.push({
              aufruf_id: ereignis.aufruf_id,
              name: ereignis.name,
              server: '',
              argumente: {},
              ergebnis: null,
              fehlgeschlagen: false,
            })
            rowOfCall(ereignis.aufruf_id, ereignis.name, ereignis.zeitpunkt_ms)
            eintrag = platzhalter.werkzeuge[platzhalter.werkzeuge.length - 1]
          }
          if (eintrag) {
            eintrag.ergebnis = ereignis.text
            eintrag.fehlgeschlagen = ereignis.fehlgeschlagen
            // Absent on an older server or mid-migration, never a made-up
            // number — the row leaves the duration out rather than show a
            // guess.
            if (ereignis.dauer_sekunden != null) eintrag.dauer_sekunden = ereignis.dauer_sekunden
            /* A command sent to the background: the number of the run it
               started, by which the terminal stream fills this very card
               with the ending later (lib/terminalfenster.svelte.js). */
            if (ereignis.lauf_nummer != null) eintrag.lauf_nummer = ereignis.lauf_nummer
            /* A job this call started: the row turns into the agent's own
               row at the line (Nachricht.svelte), fed by the job list. */
            if (ereignis.auftrag_id) eintrag.auftrag_id = ereignis.auftrag_id
          }
          // A folder the model made and shared (lib/arbeitsordner.svelte.js).
          if (ereignis.name === 'create_folder' && !ereignis.fehlgeschlagen) sharedByModel()
          /* A question whose answer has just arrived is over — take the box
             down. This matters most on a resume: the replay hands out every
             `tool_confirm`, `user_ask` and `job_confirm` of the run again,
             including the ones that were answered long before the reload.
             Without this, a settled question stands over the input field
             again and a click on it goes nowhere, because the run is far
             past it. Keyed by call id, so only the one that was actually
             answered disappears. */
          frageAbnehmen(ereignis.aufruf_id, zustand.werkzeugfrage, zustand.benutzerfrage, zustand.jobfrage)
          // The result is in; the model still has to work the grown
          // context back through before anything new arrives — exactly the
          // stretch that used to show nothing at all.
          taetigkeitSetzen(platzhalter, 'kontext', ereignis.zeitpunkt_ms, true)
          // A tool has saved an image (Recraft & co.): attach it to the
          // answer immediately — same display as in image mode.
          if (ereignis.bild) platzhalter.bild = ereignis.bild
          /* A tool has handed a file into the chat: the answer's document
             cards as the service holds them now, in the shape a stored
             answer carries them — one as `dokument`, several as
             `dokumente` — so the card stands in the bubble without the
             chat being fetched again. */
          if (Array.isArray(ereignis.dokumente)) {
            platzhalter.dokument = ereignis.dokumente.length === 1 ? ereignis.dokumente[0] : null
            platzhalter.dokumente = ereignis.dokumente.length > 1 ? ereignis.dokumente : null
            /* And into the preview, here in the handler of the event: the
               tab is filed and the preview comes forward as it does for a
               file written into a fence. */
            openDeliveredFiles(zielChat, ereignis.dokumente, {
              mayOpen: () => !wiederanhang && zielChat === zustand.aktiverChat,
              readText: (datei) => api.documentFileText(datei.id),
              addressOf: (datei) => api.documentFileAddress(datei.id),
            }).catch(() => {})
          }
          // A drawing call is over: its picture or video, if it came, stands
          // in the answer's run row the server hands over; the tile goes.
          if (isDrawingTool(ereignis.name)) {
            drawing = false
            drawingDone(zielChat, platzhalter.id, ereignis.bildlauf ?? null)
          }
          /* The end of this call, in the notice that has been reporting it
             all along. Not `dauerhaft` any more: this is the one state that
             is finished, so it may fade on its own — and if another call
             follows, it is rewritten before the clock runs out.

             The tick's clock comes from `werkzeugFertigDauer()`: the
             notice-duration setting when the user set one, the house 1.5 s
             while that field stands on "Auto". A failure does not read that
             setting at all — it always stands `WERKZEUG_FEHLER_MS` (5 s),
             on every position of that field, "Auto" included. It is the one
             line of this commentary that has to be read; the rest is
             progress. */
          if (ereignis.stopped) {
            /* The person pressed stop while the call waited: nothing failed.
               No notice of a failure — and the one standing for the call
               goes, or it would stay up as "running". The row and its
               stored result stay as they are. */
            const standing = werkzeugMeldungen.get(werkzeugToast)
            if (standing) schliesseMeldung(standing)
          } else {
            werkzeugSagen(
              ereignis.fehlgeschlagen ? 'werkzeug.fehlgeschlagen' : 'werkzeug.fertig',
              { name: ereignis.name },
              ereignis.fehlgeschlagen ? 'fehler' : 'erfolg',
              false,
              ereignis.fehlgeschlagen ? WERKZEUG_FEHLER_MS : werkzeugFertigDauer(),
              /* The result event names no server; the call's own entry does,
                 and it is what a notice pushed out meanwhile needs to come
                 back with the same mark. */
              eintrag?.server || '',
            )
          }
          werkzeugOffen = false
        } else if (ereignis.typ === 'ziel') {
          /* The model has reported a reached goal (the `goal` tool). The
             answer carries a quiet mark from this moment on — the point is
             to SEE that it is done without the model having to keep
             talking. The report itself is the mark's text: what was
             reached, not that something was.

             Set on the message, not shown as a notification: a
             notification goes away, and this is the one line of the answer
             that should still be there tomorrow. The server stores it
             alongside the tool log, so a reload shows the same mark. */
          platzhalter.ziel = ereignis.report
        } else if (ereignis.typ === 'error') {
          gescheitert = true
          melde(ereignis.text, 'fehler')
        } else if (ereignis.typ === 'kontext') {
          /* How full the context is, WHILE the answer is being written. It
             used to arrive once, in `stats`, one event before `done` — so
             the bar stood still for the whole answer and then jumped, which
             is exactly when it is least useful: the point of it is to see
             the room running out before the request that fails.

             Onto the message rather than into a variable of its own: the
             bar reads the reading off the row (zustand.svelte.js,
             `kontextStand`), and the running row is a row like any other.
             The server writes the same number into that row's column, so a
             window that opens the chat cold mid-run finds it there. */
          platzhalter.gesamt_tokens = ereignis.gesamt_tokens
        } else if (ereignis.typ === 'stats') {
          platzhalter.stats = ereignis.daten || {}
          /* The round is over and has measured itself: its figure stands
             until the next round's first live reading, not the last live
             reading of the round before. The cache share follows the same
             rule — from here on it comes out of the stats just handed in. */
          lesungenLeeren(platzhalter)
        } else if (ereignis.typ === 'done') {
          doneSeen = true
          verdichtetZu = ereignis.verdichtet ?? null
          schlussZustand = ereignis.zustand ?? null
          /* Stopped on the service — from another window, or before the
             run began — is a stop here as well: no finished dot, and the
             waiting messages come back as after a stop of this window's own.
             Stopped, failed and answered are three outcomes, not two. */
          if (ereignis.abgebrochen) abgebrochen = true
          if (ereignis.replaced) replacedId = ereignis.replaced
          if (ereignis.discarded) discarded = true
          /* The answer the run really ended with — it rides along only where
             it is NOT the one the streamed pieces spelled out, so the bubble
             that is standing there has to be lifted the same way the row
             was (see `liftAnswer` above). Without it the answer stayed in
             the thinking block until the chat was opened again. */
          if (typeof ereignis.content === 'string') {
            const reasoning = ereignis.reasoning ?? ''
            platzhalter.reasoning = reasoning
            platzhalter.content = ereignis.content
            platzhalter.abschnitte = liftAnswer(
              platzhalter.abschnitte,
              ereignis.content,
              reasoning,
            )
          }
          /* What this answer carried of each document: the word on the
             card of the question it hangs on. The service wrote the same
             words onto those rows before the answer went out, so a reload
             shows them again — this puts them there without one. Only on
             the chat on screen: any other chat is fetched afresh when it is
             opened, and its cards arrive with the word. Properties on the
             cards, nothing put into or taken out of the list.

             ROW BY ROW, by the ids the event names. It used to be one flat
             map of document id to word, laid over every card of the chat
             carrying that document — including the cards of rows this
             answer never sent. A folded row is the one that happens: the
             service leaves it out of the request, so it keeps in the table
             the word of the last answer that DID carry it, and the card
             here said what THIS answer carried until the next reload put
             the stored word back. */
          if (ereignis.dokumente && zielChat === zustand.aktiverChat) {
            /* One reading per document for the whole answer: the plan is
               made per DOCUMENT (generierung.py, `dokumentplan`), so every
               row of one request got the same word for the same document
               and the rows can be merged without anything being lost. For
               the one row below that has no server id to be named by. */
            const dieseAntwort = Object.assign({}, ...Object.values(ereignis.dokumente))
            /* The question THIS send put up a moment ago: the event names
               every OTHER row by the service's own id, and this one carries
               that same id already (see `frageKennung` in senden()) — but
               the event itself has no way to single it out among rows it
               names, so it is found here instead. Matched by the exact id
               this call was given, not merely the local `eigen-` shape:
               a reload racing the request replaces the row with the
               service's own copy of it before this ever runs, and only the
               id, not the prefix, still ties the two together. Found the
               way the bubble is found when a send fails (see below) — and
               only for a send that put a question up at all, never for a
               regenerate. */
            const eigeneFrage = inhalt != null && nachrichtId
              ? zustand.nachrichten.find(
                  (n) => n.role === 'user' && (n.id === nachrichtId || n.id === 'eigen-' + nachrichtId),
                ) ?? null
              : null
            for (const eintrag of zustand.nachrichten) {
              /* Every row but that one has to be NAMED, and that is the
                 point: a row the request left out keeps the word of the last
                 answer that did carry it. */
              const stand = eintrag === eigeneFrage
                ? dieseAntwort
                : ereignis.dokumente[eintrag.id]
              if (!stand) continue
              for (const karte of [eintrag.dokument, ...(eintrag.dokumente ?? [])]) {
                if (karte?.id && stand[karte.id]) karte.getragen = stand[karte.id]
              }
            }
          }
        }
      }
      }

      /* Watching the run again after its line broke. One attempt is not
         enough: a proxy that reaps idle connections, a laptop that wakes
         up — the run keeps going on the service, and the window has to come
         back to it instead of declaring the answer failed. Every further
         attempt waits twice as long as the one before (a stream that opens
         throws the wait away), and the loop ends where there is nothing
         left to watch: the service no longer names this run, the person
         stopped it, or the service stopped answering.
         `laufJetzt` says which run this is — the same one the requests
         above were made for, never another chat's. */
      async function weiterZusehen(laufJetzt, chatId, signal) {
        let pause = WIEDERANHANG_PAUSE_MS
        while (true) {
          const vorher = ereignisZahl
          try {
            await ereignisVerarbeiten(
              zusehenStrom(laufJetzt.generationId, ereignisZahl, signal),
            )
            return
          } catch (fehler) {
            /* Refused (a 404 for a run the service dropped between the two
               attempts): the row this window was filling stays as far as
               the stream got, and the stored one is fetched instead — for
               a fresh send as for a resume. */
            if (fehler.status) zeileNachladen = true
            if (fehler.name === 'AbortError' || fehler.status) throw fehler
          }
          /* A line that DID carry something before it broke has proved that
             the run is reachable: the wait starts over at a second instead
             of climbing on (the yardstick resets on a standing connection
             the same way). Only a run of attempts with nothing arriving
             between them keeps doubling. */
          if (ereignisZahl > vorher) pause = WIEDERANHANG_PAUSE_MS
          /* The run is written down on the service even while no window
             watches it — that is what makes coming back worth anything.
             Asks once, cheaply, and only then decides: still there, wait
             and try again; gone, the stored row is what stands; not
             answering at all, the same — a line that is gone cannot be
             waited for, and waiting on it would hold the chat for the rest
             of the session. */
          let frisch = null
          try {
            frisch = await api.nachrichten(chatId, { signal: withDeadline(signal), limit: 1 })
          } catch (fehler) {
            if (fehler.name === 'AbortError') throw fehler
          }
          if (frisch === null || (!frisch.laufend && !frisch.gehalten)) {
            /* The service does not know it any more — or does not answer:
               the stored row is the answer, with the state it ended in and
               no waiting mark. */
            zeileNachladen = true
            return
          }
          await pauseOrStop(pause, signal)
          pause = Math.min(pause * 2, WIEDERANHANG_PAUSE_MAX_MS)
        }
      }

      try {
        /* A resume never posts a new message — it attaches to the run the
           server already told us about, and from its very first event: the
           WHOLE run is replayed here, and that is deliberate. The message
           row in the database does carry the state so far these days (the
           run writes it along the way, so a service that dies leaves half
           an answer instead of none) — but that half is a fallback for
           when there is no stream left to replay, never a head start.
           Which is why the adopted row is cleared above: everything in it
           arrives here again. (`zusehenStrom` keeps its offset for the
           mid-stream reconnect below, which resumes at `ereignisZahl`
           instead of at the beginning.) */
        await ereignisVerarbeiten(
          wiederanhang
            ? zusehenStrom(wiederanhang.generationId, 0, abbruch.signal)
            : antwortStrom(koerper, abbruch.signal),
        )
      } catch (fehler) {
        /* A second attempt is for a stream that BROKE mid-answer — a dropped
           WiFi, a laptop that slept — never for a request the service itself
           refused: a refusal carries a status (404 for a run the service no
           longer has, a 401 whose page reloads itself), and asking that same
           run again would only be refused again. One refusal ends the run. A
           broken fetch carries no status while a refusal does (api.js
           errorFrom reads the number off the answer), so `fehler.status`
           separates the two. */
        if (fehler.name === 'AbortError' || fehler.status) throw fehler
        if (!lauf.generationId) {
          /* Broke before the service named this run — then the ordinary
             reattach below has nothing to attach to, and the send used to
             be declared failed on the spot. Ask where the answer went
             instead; `nachholen` waits while the service still holds the
             chat and returns false only where there is nothing left to
             wait for. */
          const found = await nachholen(lauf, zielChat, abbruch.signal)
          if (!found) throw fehler
          /* Found running: watched from its first event — nothing of it
             has been seen here — and through the same retry as any other
             line that breaks mid-answer. */
          if (found === 'run') {
            ereignisZahl = 0
            await weiterZusehen(lauf, zielChat, abbruch.signal)
          }
          return
        }
        /* The run is untouched: the server keeps working in the background
           and remembers every event since the start (api.js zusehenStrom).
           Back to it exactly where this stopped instead of declaring the
           answer failed — and back again if THIS line breaks too. */
        await weiterZusehen(lauf, zielChat, abbruch.signal)
      }
    } catch (fehler) {
      /* Stopped by hand counts as stopped, whoever ends the failure: while
         the window waits for a run that has not begun (nachholen above),
         the fetch shows up here as its own error, and a red dot with a
         failure line under a run the person just stopped would be a lie.
         A stop the service already reported (`done` above) stays a stop
         when the line breaks after it. */
      abgebrochen = abgebrochen || fehler.name === 'AbortError' || abbruch.signal.aborted
      belegt = !abgebrochen && !wiederanhang && fehler.status === 409
      gescheitert = !abgebrochen && !belegt
      /* A reattach the service refused: the run is not there any more (404
         for one it has dropped), and the row this window was about to fill
         from the stream stays empty — "nothing written", with the stored
         half answer showing only at the next open. The stored row is
         fetched instead; the refusal itself is reported as it always was. */
      if (wiederanhang && fehler.status) zeileNachladen = true
      if (gescheitert) melde(String(fehler.message || fehler), 'fehler')
    } finally {
      /* An answer that ends — finished, stopped, or failed — with a tool
         notice still standing on no clock of its own: nothing is coming
         for it any more, so it closes here instead of waiting for someone
         to notice and dismiss it, or for three later notices to push it
         out. A notice that already moved on to "fertig" or "fehlgeschlagen"
         runs its own clock down as before — this only ever touches the
         durable, still-running one. */
      if (werkzeugOffen) {
        const stehengeblieben = werkzeugMeldungen.get(werkzeugToast)
        if (stehengeblieben) schliesseMeldung(stehengeblieben)
      }
      // The same for the answer's rows of calls that never began.
      dropRowsNeverBegun()
      if (belegt) {
        /* The bubble and its placeholder come down — nothing was sent —
           and the words go back where they were typed. Then the chat is
           opened afresh: the fetch names the run that is going, and the
           reattachment shows it.

           Only while that chat is the one on screen: after a switch the
           list belongs to ANOTHER chat, and the search below would have
           taken that chat's last bubble down and the reopen dragged the
           view back here. A chat that is not on screen is fetched afresh
           when it is opened, which drops the pair by itself; its words go
           to its own draft. And only a bubble this very call put up — a
           regenerate sends no bubble, and the search would have found the
           question above instead. */
        if (zielChat === zustand.aktiverChat) {
          const eigene = inhalt != null && nachrichtId
            ? zustand.nachrichten.find(
                (n) => n.role === 'user' && (n.id === nachrichtId || n.id === 'eigen-' + nachrichtId),
              )
            : null
          /* A retry put no placeholder up: the row it names is the failed
             answer itself, and that one stays where it is. */
          zustand.nachrichten = zustand.nachrichten.filter(
            (n) => (n !== platzhalter || n === retried) && n !== eigene,
          )
          void chatOeffnen(zielChat)
        }
        /* Words AND attachments — a send without a word (two pictures and
           a document) was refused just the same, and until now it got
           nothing back at all: `if (inhalt)` skipped the whole call, so the
           pictures were gone from the bar and never in the chat. But only a
           real SEND: a regenerate (`inhalt === null`) never went through the
           bar, so the bar has nothing of its own to hand back. The message
           id tells the bar which of its sends this was. */
        if (inhalt != null) {
          if (ausReihe) {
            /* Not typed just now: it stood in the line and was on its way.
               Handed back to the field it would have left the line and
               turned into a draft; it goes back in front of its own chat's
               line instead, and leaves again once the claim is over — as
               often as the service turns it away. Only a stop by hand gives
               it back to the field. */
            zurueckEinreihen(ausReihe)
            zurueckInReihe = true
          } else {
            eingabe?.zurueckgeben(inhalt, zielChat, nachrichtId)
          }
        }
      }
      // If the answer aborts while the confirmation stands, nobody is
      // waiting for it anymore — the box has to go, otherwise it points
      // into the void. Only THIS run's own pending box, though: a run in
      // another chat may have one standing that nothing here has answered.
      delete zustand.werkzeugfrage[zielChat]
      delete zustand.benutzerfrage[zielChat]
      delete zustand.jobfrage[zielChat]
      /* A document in the answer opens as a tab in the rail by itself —
         that is what the panel is for. This used to happen here, only once
         the whole answer was done; it happens as each file's fence closes
         now (the 'content' branch above), so a long answer does not leave
         the rail silent while it is still being written. Nothing is left
         to catch up on here — every closed file already has its tab. */
      /* The finished dot: only when nobody was watching — someone sitting
         in this chat with the window in front saw the answer arrive, and
         whoever hit stop is not waiting for anything. */
      const fertigerChat = zielChat
      if (
        !abgebrochen &&
        !belegt &&
        fertigerChat &&
        (fertigerChat !== zustand.aktiverChat || !document.hasFocus())
      ) {
        /* A run that fell over earns the same afterglow as one that came
           through, in the other colour: the list should say WHICH of the
           two happened over there, not merely that something did. */
        if (gescheitert) chatFehlerMerken(fertigerChat)
        else chatFertigMerken(fertigerChat, platzhalter.content)
      }
      /* Whatever this row still says about being live, it is not any more.
         Belt as well as braces to the clearing on adoption above: a row can
         also reach this point carrying the field straight from a fetch that
         happened while the run was going. The closing state is the word
         the server put on the `done` event — the same one it wrote into
         the row's column — so a live row and a reloaded row say the same
         thing; a run that ended without a `done` (the stream broke) is
         left with no word rather than a guessed one. A run this window
         stopped itself gets no `done` either, but its word is known: it
         was stopped — not an answer in which the model wrote nothing. */
      platzhalter.zustand = schlussZustand ?? (abgebrochen ? 'abgebrochen' : null)
      // The run is over in this window, with or without a closing word.
      platzhalter.runEnded = true
      /* Stopped from here, so no `stats` came and the row still holds what
         an earlier round put there: emptied now, filled below with what the
         service stores for the answer — the line a reload shows. */
      const stoppedWithoutStats = abgebrochen && begun && !doneSeen
      if (stoppedWithoutStats) platzhalter.stats = {}
      /* A retry the service never began — turned away, or stopped before it
         started: the answer is the failed one it was. */
      if (retried && !begun) retried.zustand = retriedState
      /* A new answer written in another one's place. Finished, the answer
         it replaced is gone on the service, and its row goes here. Not
         finished — failed, stopped, or never begun — the old answer stands
         and of the attempt nothing is left, so the row this run was filling
         goes instead. The service says which on `done`; a run this window
         asked for and that ended without one (stopped from here, turned
         away) is NOT known by its request: the stop can land in the very
         moment the service stores the finished new answer and drops the old
         one, and a window that guessed "the old one stands" showed an
         answer that no longer existed and hid the one that did. Such a run
         asks the service what it stored — the reconcile below — and shows
         that. Only on the chat on screen: any other chat is fetched afresh
         when it is opened. */
      if (zielChat === zustand.aktiverChat && !belegt) {
        if (redo?.replaces && !doneSeen) {
          zeileNachladen = true
        } else {
          const gone = replacedId
            ? zustand.nachrichten.find((n) => n.id === replacedId)
            : discarded || (redo?.replaces && schlussZustand !== 'fertig')
              ? platzhalter
              : null
          const stelle = gone ? zustand.nachrichten.indexOf(gone) : -1
          if (stelle !== -1) zustand.nachrichten.splice(stelle, 1)
        }
      }
      // A drawing call this run never saw the result of: its tile goes too.
      if (drawing) drawingDone(zielChat, platzhalter.id, null)
      /* A compaction folded the middle of the history away and left a
         summary row nobody here has seen. Fetched once, so the seam appears
         at all, instead of only at the next open. Guarded on the chat still
         being the one on screen, and failure-tolerant on purpose: the row
         is safely in the database either way, and the list heals the next
         time this chat is opened (the picture window's own reconcile
         reasons the same way).

         It runs BEFORE the release below, and that ordering is the whole
         point: the reconcile replaces `zustand.nachrichten` wholesale, so it
         has to be the last thing this run does to the list — with nothing
         else allowed to have put anything into it yet. */
      if (
        (verdichtetZu || zeileNachladen) &&
        zielChat &&
        zielChat === zustand.aktiverChat
      ) {
        try {
          /* Asked for before the await, assigned only after checking again:
             the guard above was true when this started, and a chat switch
             during the fetch would otherwise write THIS chat's history into
             the window showing another one — over whatever is streaming
             there. The picture window's reconcile re-reads `aktiverChat`
             after its own await for exactly that reason; this one only ever
             looked before it. */
          /* Bounded, because the release below waits on it. Unbounded, a
             fetch that never settled — a dropped connection, a proxy that
             holds the request — kept `zustand.laeuft` set for the rest of
             the session: input greyed, Stop offered for a run that was
             over, the queue never fired. A timeout lands in the catch,
             and the catch lets the release run. */
          /* A replacing run that ended without its closing event: the stop
             went out from here as a request of its own, and until it lands
             the run is still going — a list fetched in that stretch carries
             its half-written row beside the answer it was to replace, and
             both would stay on screen. Asked until the service no longer
             names the run, bounded like the fetch itself. */
          if (redo?.replaces && !doneSeen) {
            const bis = Date.now() + NACHLADE_FRIST_MS
            while (Date.now() < bis) {
              const lage = await api.nachrichten(zielChat, {
                signal: AbortSignal.timeout(NACHLADE_FRIST_MS),
                limit: 1,
              })
              /* The run is named by its id once the stream has said it; a
                 stop before that stands in the claim the service holds. */
              const going = lauf.generationId
                ? lage?.laufend?.generation_id === lauf.generationId
                : Boolean(lage?.laufend || lage?.gehalten)
              if (!going) break
              await new Promise((frei) => setTimeout(frei, HALTEPRUEFUNG_MS))
            }
          }
          const frisch = await api.nachrichten(zielChat, {
            signal: AbortSignal.timeout(NACHLADE_FRIST_MS),
          })
          if (zielChat === zustand.aktiverChat) {
            nachrichtenSetzen(zielChat, frisch.nachrichten)
            /* A run the service reports as going NOW has a live row in
               the list just fetched. Usually it is somebody else's — the
               service releases this run before it sends `done`, and a wake
               can start on its end (app/hintergrundwecken.py) — but it can
               be this very run too, when the line to it was refused while
               the run went on. Left alone, that row was drawn as running
               with no stream behind it, nothing ever cleared it, and the
               queue sent into a chat the service had already claimed.
               Noted here, acted on once this run has let go below. */
            fremderLauf = frisch.laufend ?? null
            /* Held with no run named yet: a send that claimed the chat is
               still folding its history. As taken as a running chat — the
               queue sending into it now only ran into a 409. */
            heldWithoutRun = !frisch.laufend && Boolean(frisch.gehalten)
          }
        } catch {
          /* the answer stands; the fresh list arrives with the next open.
             A replacing run that could not ask what the service stored has
             its half-written row beside the old answer, and the stop of
             this window, where the service could not be asked, leaves
             nothing of the attempt: it goes, as it always did. */
          if (redo?.replaces && !doneSeen && zielChat === zustand.aktiverChat) {
            const stelle = zustand.nachrichten.indexOf(platzhalter)
            if (stelle !== -1) zustand.nachrichten.splice(stelle, 1)
          }
        }
      }
      /* A clean end and a failed one let the line move; a run stopped by hand
         gives the waiting messages back to the person.

         Everything from here to the end of the block is the run LETTING GO
         of the chat, and the order inside it is not cosmetic.
         `delete zustand.laeuft[zielChat]` is not bookkeeping, it is the
         signal: the effect at the foot of this file watches exactly
         `Object.keys(zustand.laeuft).length`, so that one line arms the
         queue, and the very next await is enough to fire it. Whatever the
         queue is meant to be gated on must therefore be true BEFORE it, and
         whatever this run still means to write into the chat must already be
         written.

         Both were broken from here, in two separate ways, and both are
         fixed by the order rather than by a repair afterwards. The picture
         path's rescue is not the tool for this one: it puts the placeholder
         back AFTER the list was replaced, and it can only recognise its own
         row once the run's `start` event has handed the placeholder the
         service's id — which a run begun a few milliseconds ago has not
         got. Here it would land in that blind spot every time: a second row
         pushed beside the service's own, keeping `zustand: 'laeuft'` with
         nobody left to clear it, or the answer put back without the
         question it answers. Nothing needs putting back if nothing was
         taken away.

         The give-back of a stop by hand used to stand at the bottom, past
         two awaits. So a run stopped by hand released the line on its way
         out and only then took the waiting messages back: they went out
         while the person had asked for the stop. It now takes them out of
         the line while the chat is still claimed, so the queue finds
         nothing to send instead of racing the give-back.

         And the reconcile above replaces the message list. With the release
         still at the top of this block, the queue's `senden` ran during the
         awaits — as far as its own bubble and its placeholder without ever
         yielding, since a message with no attachments in a chat that already
         has a history reaches both synchronously — and the replacement then
         threw the pair away. The second question was simply gone from the
         screen, its answer streamed into an object nothing draws any more,
         and the bar kept offering a stop button for it. A fold is what
         turned that from a rarity into the ordinary case: folds happen in
         long chats, which is where `api.nachrichten` is slowest and where a
         message gets queued in the first place.

         So the claim on the chat is held for exactly as long as this run is
         still rewriting the chat's list, and dropped the moment it is not.
         `chatsLaden` sits below the release rather than above it because it
         refreshes the sidebar and touches no message at all: kept above, it
         would make every ordinary answer — the overwhelming majority, which
         never reconciles anything — wait a whole round trip before its queue
         could move. */
      /* The service still running THIS run: the line to it was refused or
         lost while the run went on. Not stopped from here, it has not
         failed either — it is attached again below, so the queue does not
         hold for it and the failure mark goes. Once per run: a line that
         keeps refusing would otherwise turn into a loop with a notice every
         round. Not attached — stopped from here, or attached once already —
         its row does not stand as running with no stream behind it: stopped
         says so, the other keeps no word rather than a guessed one. */
      const stoppedHere = stoppedForQueued.delete(zielChat)
      const stopByHand = stoppedByHand.delete(zielChat)
      if (stoppedHere && !abgebrochen) unmarkInterrupted(zielChat)
      /* A message still waits with a stop made for it: the run may end again
         on the way (a send the service turned away attaches the window to the
         same run), and that end is the stop's too, not the person's. */
      const stopForMessage = stoppedHere || hasInterrupted(zielChat)
      const isOwnRun = fremderLauf != null && fremderLauf.generation_id === lauf.generationId
      const ownRunGoesOn = isOwnRun && !abgebrochen && !ownRunsReattached.has(lauf.generationId)
      if (isOwnRun && !ownRunGoesOn) {
        const row = zustand.nachrichten.find((n) => n.id === fremderLauf.message_id)
        if (row) row.zustand = abgebrochen ? 'abgebrochen' : null
        fremderLauf = null
      }
      if (ownRunGoesOn) {
        ownRunsReattached.add(lauf.generationId)
        chatFehlerGesehen(fertigerChat)
      }
      /* A stop made for a waiting message: the line moves on. A stop by hand
         gives the waiting messages back to the person; a failure holds
         nothing, the line moves on as after any end. */
      else if (fertigerChat && abgebrochen && (!stopForMessage || stopByHand)) giveBackQueued(fertigerChat)
      /* A held chat keeps the queue's gate shut through the release: the
         same send-in-flight mark that holds the queue while a send of this
         window's own uploads — a send of this window still holds it
         anyway, and then it is left to that send to lift. */
      const warteAufAnspruch = heldWithoutRun || zurueckInReihe
      const holdMark = warteAufAnspruch && !zustand.sendet[zielChat]
      if (holdMark) zustand.sendet[zielChat] = true
      delete zustand.laeuft[zielChat]
      if (zustand.laufenderPlatzhalter[zielChat] === platzhalter) {
        delete zustand.laufenderPlatzhalter[zielChat]
      }
      /* Straight after the release and before anything yields: the reattach
         registers the run synchronously, so the queue effect the release
         wakes finds the chat taken and holds, instead of sending into a 409.
         The same door a cold open uses (`chatOeffnen`). */
      if (fremderLauf) {
        // The list was fetched in the same breath; a row still missing is
        // no reason to fetch again, and returning without claiming the
        // chat is exactly what the release above must never see.
        void antwortWiederAnhaengen({
          chatId: zielChat,
          generationId: fremderLauf.generation_id,
          messageId: fremderLauf.message_id ?? null,
        }, { nachholen: false })
      }
      await chatsLaden()
      if (warteAufAnspruch) {
        /* The wait can be ended from the stop button: it reaches the claim
           through the chat's id (`abbrechen`) and cuts this question short. */
        const wartet = new AbortController()
        anspruchWarten.set(zielChat, wartet)
        try {
          const { run, reachable } = await claimOutcome(zielChat, wartet.signal)
          if (reachable && zielChat === zustand.aktiverChat && !laufVon(zielChat)) {
            /* The list was fetched while the chat was held: fetched again, so
               the other send's question and its answer are there — running,
               or already over — and a named run is claimed
               synchronously before the mark goes — waiting for a fetch inside
               the reattach would open the gate first. Not over a run that
               another open attached meanwhile. */
            let named = run
            try {
              const fresh = await api.nachrichten(zielChat, {
                signal: AbortSignal.timeout(NACHLADE_FRIST_MS),
              })
              // The fresher word: a run that began since the last question,
              // or none — the named one is already over, and replaying it
              // would only stream a finished answer again.
              named = fresh?.laufend?.generation_id ? fresh.laufend : null
              if (zielChat === zustand.aktiverChat && !laufVon(zielChat)) {
                nachrichtenSetzen(zielChat, fresh.nachrichten)
              }
            } catch {
              /* No fresher word: a run the claim turned into is attached as
                 it stands, a claim that simply went attaches nothing, and
                 the list heals at the next open. */
            }
            if (named) {
              void antwortWiederAnhaengen({
                chatId: zielChat,
                generationId: named.generation_id,
                messageId: named.message_id ?? null,
              }, { nachholen: false })
            }
          }
          /* A message turned away goes round again on the clock of the claim
             check and no faster: a claim that is already gone leaves nothing
             to wait for above, and asking the service in a tight circle
             would only be answered the same way. The stop wakes this too. */
          if (zurueckInReihe && !run) await pauseOrStop(HALTEPRUEFUNG_MS, wartet.signal)
        } finally {
          // Whatever happens in the wait, the gate does not stay shut.
          if (anspruchWarten.get(zielChat) === wartet) anspruchWarten.delete(zielChat)
          if (holdMark) delete zustand.sendet[zielChat]
        }
      }
      warteschlangeWeiter()
      if (stoppedWithoutStats) void abbruchZeileNachziehen(zielChat, platzhalter)
    }
  }

  /* Reattaches to a run the server said is still going for this chat — the
     case a plain reload used to leave stuck at "nothing happening" (C2):
     the generation kept working the whole time, only the window's own
     record of its id was gone. */
  /* The runs a reattachment has already reopened the chat for (see
     below). A set, not one slot: two runs naming each other in turn
     walked one slot back and forth and fetched for ever. */
  const nachgeholtFuer = new Set()

  /* The chats whose run has let go and which wait for another window's claim
     to end: the controller that cuts that wait short, by chat. Read by the
     stop button, which has no run of its own to stop in that stretch. */
  const anspruchWarten = new Map()

  /* The runs whose own end attached them again once (see the end of
     `antwortHolen`) — never a second time. */
  const ownRunsReattached = new Set()

  /* The run the LAST of those fetches was made for — whoever finds another
     name here has been overtaken and must not attach its own, older run. */
  let nachgeholtZuletzt = null

  async function antwortWiederAnhaengen(wiederanhang, { nachholen = true } = {}) {
    // The whole record is passed on, not two fields out of it. Taking them
    // apart here and putting them back together below is how `messageId`
    // went missing: the resume was rebuilt as `{ chatId, generationId }`,
    // so `antwortHolen` never saw the id the server had gone to the trouble
    // of sending, adopted nothing, and pushed a second placeholder beside
    // the stored answer — the exact doubling this was built to stop.
    const { chatId } = wiederanhang
    // Opening a second chat before this got here must not attach a stream
    // meant for the first one to whatever is now on screen — the same
    // stale-result guard the terminal window needed (B9). And not twice for
    // the same chat: `laufVon(chatId)` means one is already attached.
    if (zustand.aktiverChat !== chatId || laufVon(chatId)) return
    /* A second window on the same chat hears the start of an answer whose
       question it has not fetched: attached as it stands, the answer grew
       under no question at all. The chat is opened afresh instead — the
       fetch brings the question and names the run, and the reattachment
       follows from there through this very function, with the row in the
       list this time. Once per run: a run whose row the fetch still does
       not bring is attached as it is rather than fetched forever. And
       only for a caller that can wait: the end-of-run reconcile has just
       fetched the list itself and needs the claim on the chat made
       synchronously, so it passes `nachholen: false`. */
    if (
      nachholen
      && wiederanhang.messageId
      && !nachgeholtFuer.has(wiederanhang.generationId)
      && !zustand.nachrichten.some((n) => n.id === wiederanhang.messageId)
    ) {
      nachgeholtFuer.add(wiederanhang.generationId)
      nachgeholtZuletzt = wiederanhang.generationId
      await chatOeffnen(chatId)
      /* The fetch names the run and files the reattachment again (the
         effect above picks it up). A fetch that failed, or one that named
         no run, filed nothing — then the answer is attached as it stands
         rather than lost until the next open. Unless a LATER fetch was
         made for another run meanwhile: then this one is stale, and
         attaching it would hang a dead run on the screen. */
      if (zustand.aktiverChat !== chatId || laufVon(chatId) || zustand.wiederanhaengen[chatId]) return
      if (nachgeholtZuletzt !== wiederanhang.generationId) return
    }
    await antwortHolen(null, null, null, null, null, wiederanhang)
  }


  /* Whether the question a row answers carried a picture. The service does
     not store `vision` on a row, so a reattach — which adopts a row that
     came from there — would otherwise write `false` over a question that
     did carry one, and the eye mark of image recognition turned into an
     ordinary waiting mark. The question itself is in the list: the nearest
     row above with the role `user`, read the same way Nachricht.svelte
     reads a row's pictures (`anhaenge`, else `bild`). `null` asks for the
     question the LAST row answers — what a placeholder pushed at the end
     belongs to. */
  function frageTrugBild(zeile) {
    const liste = zustand.nachrichten ?? []
    const stelle = zeile ? liste.indexOf(zeile) : liste.length
    for (let i = (stelle === -1 ? liste.length : stelle) - 1; i >= 0; i -= 1) {
      const davor = liste[i]
      /* Only an ordinary question: a picture run writes its prompt as a
         `user` row too (app/api/v1/bild.py), and a fold's summary carries
         the same role — stopping at one of those would answer `false` for
         a question that did carry a picture. */
      if (davor?.role !== 'user') continue
      if ((davor.art ?? 'nachricht') !== 'nachricht') continue
      return Boolean(davor.anhaenge?.length || davor.bild)
    }
    return false
  }

  /* Stops a run that has no name yet, again and again, until a stop lands.
     Before the service has taken this send's claim the count it answers is
     0 and nothing is cancelled — and a moment later it takes the claim and
     begins the answer nobody wants any more. So the stop is sent again in
     the clock of the other waits, as long as this very send is going; the
     send itself is cut only once a stop has landed (or the run has been
     named, which the next round reaches by its id). */
  async function stoppWiederholen(lauf) {
    for (;;) {
      const mitKennung = Boolean(lauf.generationId)
      let getroffen = false
      try {
        const antwort = await api.abbrechen(lauf.generationId, lauf.chatId)
        getroffen = Number(antwort?.abgebrochen ?? 0) > 0
      } catch {
        /* Not answered: asked again below, while the send goes on. */
      }
      if (getroffen || mitKennung) break
      await new Promise((frei) => setTimeout(frei, HALTEPRUEFUNG_MS))
      if (laufVon(lauf.chatId) !== lauf || lauf.abbruch.signal.aborted) break
    }
    lauf.abbruch.abort()
  }

  /* Always the run of the chat on screen — never one in the background, and
     never more than one. */
  async function abbrechen() {
    const lauf = laufVon(zustand.aktiverChat)
    if (!lauf) {
      /* No run of this window, but the window waits for another one's claim
         on the chat (the end of an answer while the chat is held, or a queued
         message the service turned away): the stop reaches that claim through
         the chat's id, the wait ends at once, and the queue holds as after
         any stop. */
      const chatId = zustand.aktiverChat
      /* The window folds this chat by hand (`/compact`): the stop reaches the
         service's claim through the chat's id and closes the summary request.
         The answer of the fold itself ends the wait. */
      if (chatId && compactSince[chatId]) {
        void api.abbrechen(null, chatId).catch(() => {})
        return
      }
      const wartet = chatId ? anspruchWarten.get(chatId) : null
      if (!wartet) return
      giveBackQueued(chatId)
      void api.abbrechen(null, chatId).catch(() => {})
      wartet.abort()
      return
    }
    /* Both handles, always: the run's id where the stream has named it, the
       chat's always. Before `start` there is no run id — the service is
       still folding its history — and the chat id is what reaches the claim
       the service took for this send (app/generationen.py). Sent only with
       the run id, the press reached nothing: no run was registered yet, so
       nothing was cancelled, and the answer began into the window that had
       just stopped it. */
    if (!lauf.generationId) {
      /* Nothing named yet: the stop may arrive before the claim stands and
         count 0. It is repeated beside the button — the press itself waits
         for nothing, and a second press starts no second repetition. */
      if (lauf.stoppt) return
      lauf.stoppt = true
      void stoppWiederholen(lauf)
      return
    }
    lauf.abbruch.abort()
    /* Told, not waited for: the press must not hang on a request that may
       never settle (the route runs in the service's worker pool and carries
       no timeout of its own). Nothing below this line needs the answer. */
    void api.abbrechen(lauf.generationId, lauf.chatId).catch(() => {})
  }

  return {
    /* The page hands over its view and gets back what takes it away again;
       a page that is gone leaves nothing behind, and a newer view is not
       taken away by an older one. */
    ansicht(hand) {
      view = hand
      runter = hand.runter ?? (() => {})
      eingabe = hand.eingabe ?? null
      return () => {
        if (view !== hand) return
        view = null
        runter = () => {}
        eingabe = null
      }
    },
    senden,
    abbrechen,
    abbrechenVonHand,
    neuErzeugen,
    frageNeuSenden,
    compactChat,
    warteschlangeWeiter,
    takeBackQueued,
    interruptForQueued,
    toolIsRunning,
    antwortWiederAnhaengen,
    bildDateien,
    anspruchWarten,
    compactSince,
    get laufAktuell() {
      return laufAktuell
    },
    get letzteAntwort() {
      return letzteAntwort
    },
    get letzteFrage() {
      return letzteFrage
    },
  }
}

export const chatRun = createChatRun()
