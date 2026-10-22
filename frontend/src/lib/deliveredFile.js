/*
  A file the model hands into the chat with `deliver_file`.

  Two things belong to it and to nothing else: what kind the card knows it
  to be, and the moment it reaches the preview. The kind comes from the
  file's ending; the preview is filled in the handler of the event that
  brought the file (not in an effect that would read and write the same
  list round and round).

  The preview comes to the front by itself, as it does for a file the model
  writes into a fence — except where the person folded the column on the
  preview, and except where the caller says it may not open (a chat that is
  not on screen: a background chat's rail is nobody's to rearrange; an
  answer picked up again after a reload, whose whole run is replayed and
  whose files the person has seen). There the tab is only filed. A picture
  stays a picture tile and is not filed here. Opening an older chat never
  comes through here at all.
*/
import { ADDRESS_KINDS, fileKind, formatSize } from './dateiarten.js'
import { isPicture } from './media.js'
import { leiste } from './arbeitsleiste.svelte.js'
import { tabEinsortieren, tabOeffnen } from './vorschautabs.svelte.js'
import { t } from './texte.svelte.js'

/* Endings that name a kind under another word. */
const ALIASES = { htm: 'html', markdown: 'md' }

/** What a delivered file's card carries as its language, from its ending:
    the ending the file is known by (a document, code, text, a picture, a
    clip, a sound or an Office file), or empty for a file of no known kind. A PDF is drawn
    from its address, not from a language, and carries none. */
export function deliveredLanguage(typ) {
  const raw = String(typ || '').toLowerCase().trim()
  const name = ALIASES[raw] ?? raw
  const info = fileKind(name)
  return info && info.kind !== 'pdf' ? name : ''
}

/* What the file is, and stays: kind, size, pages — one page said as one. */
function pageCount(pages) {
  if (!pages) return null
  return pages === 1
    ? t('nachricht.dokument_seiten_eins')
    : t('nachricht.dokument_seiten', { zahl: pages })
}

/** The line a document card carries under its name: kind, size, pages. */
export function fileFacts(karte) {
  const size = karte.size_bytes == null ? null : formatSize(karte.size_bytes)
  return [(karte.typ || '').toUpperCase(), size, pageCount(karte.seiten)]
    .filter(Boolean)
    .join(' · ')
}

/**
 * Files the documents a tool has just handed into the chat as tabs of the
 * preview. `mayOpen` is asked when a tab is about to be filed — after the
 * text has been fetched, when the person may have gone to another chat —
 * and says whether the preview may come forward for it; `readText` and
 * `addressOf` are the service's reading of a document.
 * A picture, a file of no known kind and a file whose text cannot be read
 * as text are left alone; a PDF, a picture, a clip, a sound and an Office file are filed
 * with their address, as the card files them.
 */
export async function openDeliveredFiles(chatId, documents, { mayOpen, readText, addressOf }) {
  function file(tab) {
    if (!mayOpen()) {
      tabOeffnen(chatId, tab, false)
    } else if (leiste.nichtAufdraengen === 'vorschau') {
      tabEinsortieren(chatId, tab)
    } else {
      tabOeffnen(chatId, tab, true)
    }
  }
  for (const document of documents) {
    if (!document?.id || !document.name || isPicture(document.name)) continue
    const pfad = document.pfad || ''
    const info = fileKind(document.typ)
    if (!info) continue
    if (info.kind === 'pdf' || ADDRESS_KINDS.includes(info.kind)) {
      // Drawn or played from the file's own address; its text is never fetched.
      file({
        name: document.name,
        art: info.kind === 'pdf' ? 'pdf' : deliveredLanguage(document.typ),
        inhalt: '',
        pfad,
        adresse: addressOf(document),
        fakten: fileFacts(document),
      })
      continue
    }
    const art = deliveredLanguage(document.typ)
    let text = null
    try {
      text = await readText(document)
    } catch {
      continue
    }
    if (text == null) continue
    file({ name: document.name, art, inhalt: text, pfad })
  }
}
