/*
  What the right-click menu offers, decided in one place — and in plain
  JavaScript, without electron, so node can run it and tests can check it.

  It used to be decided inside main.js, where every branch needs an Electron
  `params` object and a window to act on. That is why one of the rules could
  break for months without a test going red: a right click on empty page
  content with nothing selected built an empty list, and an empty list means
  no menu at all.

  This module answers ONE question: which entries does this click get, in
  which order. It answers with DESCRIPTIONS, not with Electron objects — the
  actions need a window, and a window is the caller's business:

      { art: 'rolle', role: 'selectAll' }      a menu role, label from the system
      { art: 'wort', label: 'Haus' }           a spelling suggestion
      { art: 'trenner' }                       a separator
      { art: 'bild_speichern' }                save the picture under the cursor
      { art: 'bild_kopieren' }                 copy that picture
      { art: 'link', label: '…', adresse: … }  copy the address under the cursor
      { art: 'vorlesen', label: '…', text: … } read the marked text aloud

  Every entry that acts on something outside the list (a window, a
  clipboard, a download) is named by its kind alone; `main.js` turns the
  descriptions into menu items and hangs the actions on them. So the ORDER
  and the rules live here, where they are checked, and the two things that
  need electron stay there.
*/

'use strict'

/* The one place the "and what if nothing is selected" rule is written down.
   A right click next to marked text clears the selection — that is
   Chromium's own behaviour, not ours — and the menu then had nothing to
   offer, so nothing opened. The entry that makes sense without a selection
   is the one that makes one. */
function baue(params, kann = {}, zusatz = {}) {
  const eintraege = []
  const trenner = () => {
    if (eintraege.length) eintraege.push({ art: 'trenner' })
  }
  const auswahl = String(params.selectionText || '').trim()

  if (params.isEditable) {
    for (const wort of params.dictionarySuggestions || []) {
      eintraege.push({ art: 'wort', label: wort })
    }
    trenner()
    eintraege.push(
      { art: 'rolle', role: 'undo', enabled: kann.canUndo },
      { art: 'rolle', role: 'redo', enabled: kann.canRedo },
      { art: 'trenner' },
      { art: 'rolle', role: 'cut', enabled: kann.canCut },
      { art: 'rolle', role: 'copy', enabled: kann.canCopy },
      { art: 'rolle', role: 'paste', enabled: kann.canPaste },
      { art: 'trenner' },
      { art: 'rolle', role: 'selectAll', enabled: kann.canSelectAll }
    )
  } else if (auswahl) {
    eintraege.push(
      { art: 'rolle', role: 'copy', enabled: kann.canCopy },
      { art: 'trenner' },
      { art: 'rolle', role: 'selectAll', enabled: kann.canSelectAll }
    )
  } else if (params.mediaType !== 'image' && !params.linkURL) {
    // Nothing editable, nothing selected, no picture and no link: the click
    // landed on plain page content. No `enabled` on purpose — this entry has
    // to WORK, or the menu would offer the same nothing it offered before,
    // only with a label on it.
    eintraege.push({ art: 'rolle', role: 'selectAll' })
  }

  if (params.mediaType === 'image' && params.srcURL) {
    trenner()
    eintraege.push({ art: 'bild_speichern' }, { art: 'bild_kopieren' })
  }

  if (params.linkURL) {
    trenner()
    eintraege.push({
      art: 'link',
      label: zusatz.linkLabel || 'Copy Link Address',
      adresse: zusatz.linkAdresse,
    })
  }

  /* Only with marked text, in the chat or in a field alike — and only where
     the page said what the entry is called: that page is the one that can
     read aloud, and the word comes from its catalogue. A window whose page
     never said it (the manual) gets no entry it could not act on. */
  if (auswahl && zusatz.vorlesenLabel) {
    trenner()
    eintraege.push({ art: 'vorlesen', label: zusatz.vorlesenLabel, text: auswahl })
  }

  return eintraege
}

module.exports = { baue }
