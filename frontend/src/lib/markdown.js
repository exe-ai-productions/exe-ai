/*
Markdown rendering and syntax highlighting.

Markdown itself is still done here, by hand: nothing is fetched at runtime,
nothing leaves the machine. The syntax colouring moved out to
lib/einfaerben.js, which uses highlight.js — hand-written patterns cannot
tell a regex literal from a division, and that is where they broke.

Order matters: first the code blocks are taken out and parked, then the
rest is transformed, and at the end the blocks come back. Otherwise
Markdown inside code would be interpreted — an asterisk in a Python line
would suddenly be italic.

Everything is escaped beforehand. Untreated text never ends up in the
document.
*/

import { hervorheben } from './einfaerben.js'
import { t } from './texte.svelte.js'
import { dateiart, dateiname } from './dateiarten.js'


/* Takes the blockquote marker off each line of a fenced block that stood
   inside a quote. One optional space after the ">" — that space is the
   quote's own separator, not indentation of the code. */
function entzitieren(code) {
  return code.replace(/^[ \t]*>[ \t]?/gm, '');
}

/* Whether a block stands inside a quote. The opening fence says so when it
   starts a line of its own (`zitat` is its quote marker); a fence opened in
   the middle of a quoted line carries no marker of its own, so the code
   is asked instead — every line of it wearing the marker is a quote, and
   the marker comes off the same way. */
function imZitat(zitat, code) {
  if (zitat) return true;
  const zeilen = code.split('\n').filter((z) => z.trim() !== '');
  return zeilen.length > 0 && zeilen.every((z) => /^[ \t]*>/.test(z));
}


function maskieren(text) {
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/*
  The line numbers beside a block.

  Their own element, never part of the code: `user-select: none` keeps them
  out of a selection, and the copy button takes the raw source anyway. A
  number that lands in the clipboard turns pasted code into broken code.

  From two lines on. A single line has nothing to count.
*/
function nummernspalte(code) {
  const anzahl = code.split('\n').length;
  if (anzahl < 2) return '';
  let ziffern = '';
  for (let n = 1; n <= anzahl; n++) ziffern += n + '\n';
  return '<span class="code-nummern" aria-hidden="true">' + ziffern + '</span>';
}

/*
  An answer's code block wraps its long lines instead of letting them run off
  into the wall — and a wrapped line must still wear ONE number. A separate
  number column cannot know how many rows a line took, so each written line
  becomes a row of its own and draws its number itself (a CSS counter in
  codeblock.css: never text, so neither a selection nor the copy button can
  pick it up).

  The highlighter's spans may run across a line break (a multi-line string or
  comment). Each row closes what is still open at its end and the next one
  reopens it, so every row is well-formed HTML on its own.
*/
function zeilenReihen(html) {
  const reihen = [];
  const offen = [];
  let reihe = '';
  for (const teil of html.split(/(<[^>]+>|\n)/)) {
    if (!teil) continue;
    if (teil === '\n') {
      reihen.push(reihe + '</span>'.repeat(offen.length));
      reihe = offen.join('');
    } else if (teil.startsWith('</')) {
      offen.pop();
      reihe += teil;
    } else if (teil.startsWith('<')) {
      offen.push(teil);
      reihe += teil;
    } else {
      reihe += teil;
    }
  }
  reihen.push(reihe);
  return reihen.map((r) => '<span class="code-zeile"><span>' + r + '</span></span>').join('');
}

/* The copy mark: the same drawing the message's own copy button wears
   (Nachricht.svelte), so one action has one sign. */
const KOPIER_ZEICHEN =
  '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">' +
  '<rect x="9" y="9" width="11" height="11" rx="2" /><path d="M5 15V5a2 2 0 012-2h10" /></svg>';

/*
  One frame for every code block of an answer, finished or still being
  written. No header bar: the language, when the model named one, sits small
  in the top left corner, and the copy mark in the top right — on EVERY
  finished block, not only on one that happens to carry a language. A block
  still being written gets no copy mark: half-written code is not worth
  copying, and the mark arrives with the closing fence.
*/
function codeRahmen(roh, sprache, offen) {
  const html = hervorheben(roh, sprache);
  const zeilen = roh.split('\n').length;
  // `offen` right after `codeblock`: "codeblock offen" is how the rest of
  // the program and its tests tell a block still being written.
  const klassen = offen ? ['codeblock', 'offen', 'umbricht'] : ['codeblock', 'umbricht'];
  if (sprache) klassen.push('mit-sprache');
  if (zeilen > 1) klassen.push('nummeriert');
  const kopieren = t('nachricht.kopieren');
  const knopf = offen
    ? ''
    : `<button class="code-kopieren" title="${kopieren}" aria-label="${kopieren}">${KOPIER_ZEICHEN}</button>`;
  const kennung = sprache ? `<span class="code-sprache">${maskieren(sprache)}</span>` : '';
  // The digit count sizes the number column, so row 9 and row 10 line up.
  const breite = zeilen > 1 ? ` style="--ziffern:${String(zeilen).length}"` : '';
  const inhalt = zeilen > 1 ? zeilenReihen(html) : html;
  return `<div class="${klassen.join(' ')}">` + kennung + knopf +
    `<pre><code${breite}>` + inhalt + '</code></pre></div>';
}

/* ---------- Markdown ---------- */

function inline(text) {
  // Emphasis is done with asterisks only. Underscores are left alone on
  // purpose: this program is full of file paths, and app/__init__.py or
  // my_file_name would otherwise turn half a path bold or italic and break
  // the click-and-copy the path is there for. Standard Markdown allows both
  // markers; for a terminal that talks in paths, one of them is a liability.
  return text
    .replace(/`([^`]+)`/g, (_, c) => '<code>' + c + '</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>')
    .replace(/~~([^~]+)~~/g, '<del>$1</del>')
    .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
}

function tabelle(zeilen) {
  const zelle = (z) => z.trim().replace(/^\||\|$/g, '').split('|').map((s) => s.trim());
  const kopf = zelle(zeilen[0]);
  const koerper = zeilen.slice(2).map(zelle);
  let html = '<table><thead><tr>' + kopf.map((z) => '<th>' + inline(z) + '</th>').join('') +
    '</tr></thead><tbody>';
  koerper.forEach((reihe) => {
    html += '<tr>' + reihe.map((z) => '<td>' + inline(z) + '</td>').join('') + '</tr>';
  });
  return html + '</tbody></table>';
}

/* Wraps every block placeholder — control characters a model's own answer
   never contains, so the final substitution below can never mistake an
   ordinary number IN the text (a list, a year, a bare `42`) for one of its
   own markers. A file marker additionally carries the word "datei" so it
   survives THIS function's own substitution untouched — Nachricht.svelte
   resolves it into a live component afterwards (dateienAus, below), which
   is the whole point of leaving it standing rather than replacing it. */
const BLOCK_MARKE = /\x01(\d+)\x01/g;
function blockMarke(nummer) { return '\x01' + nummer + '\x01'; }
function dateiMarke(nummer) { return '\x01datei' + nummer + '\x01'; }

/* A closed fence pair — and the ONE place its shape is written down.

   A fence is a LINE, and so is the fence that closes it: line start, the
   quote marker if the block stands in a quote, three marks or more — and
   the closing one at least as many marks as the opening, with nothing after
   it but blanks. That is what CommonMark says, and it is what makes a fence
   safe to put around text nobody wrote by hand. Command output carries
   backticks (a grep for them, a heredoc writing Markdown), and so does the
   line a background run sets above it; while any ``` anywhere ended a
   block, such a run tore its own message apart.

   Anchoring only the OPENING left that half done, and the half left over is
   the one that hurts: an unanchored `\2` stopped at the first ``` ANYWHERE,
   mid-line included. `grep -n '```' file.md` INSIDE a block therefore closed
   it after `grep -n '`, and the rest of the run — its own output and the
   real closing fence — spilled out into the prose as text. A writer that
   makes its fence longer than anything it has to carry stayed safe, and
   hintergrundmeldung.py does exactly that; but the fence a model writes in
   an ordinary answer is three marks, and it was not safe at all.

   The `` `* `` after the backreference takes a closing fence that is LONGER
   than the opening one whole. Without it the surplus marks were left behind
   in the text, and a block closed with ```` under a ``` opening ended with a
   stray backtick sitting under the box. The closing fence is still the
   opening one repeated, so a longer fence goes on surviving everything
   shorter inside it — a ````md block keeps its ``` examples.

   Indentation stays `[ \t]*` on both halves rather than CommonMark's three
   spaces: the opening has been that lenient since it was written, and a
   closing fence stricter than the opening it belongs to would swallow
   blocks that draw correctly today.

   ONE constant, because `rendern` and `dateienAus` both read it and MUST
   agree — they were two hand-written copies once, only one of them learned
   that a fence inside a blockquote is a fence, and a document written in a
   callout vanished from the answer without a trace. Nothing left to drift.
   Sharing the object is safe because both uses are `String.replace`, which
   resets `lastIndex` itself; an `.exec` or `.test` on it would not be.

   The OPENING fence may also stand in the middle of a line. Small models
   write "Here is the fix: ```python" and put the code on the next line all
   the time, and code has to be drawn as code wherever its fence happens to
   stand. What keeps an inline span such as "run ```js``` inline" from
   opening a block is the lookahead in the mid-line branch: an opening
   fence that does not stand at a line start has to be followed by nothing
   but its info word and a line break, which is what a fence is and an
   inline span never has. The CLOSING fence stays a line of its own — that
   half is what protects command output, and it is unchanged. */
const ZAUN_PAAR = /(?:^[ \t]*(>[ \t]?)?|(?<=\S)[ \t]*(?=`{3,}[\w+-]*\n))(`{3,})([\w+-]*)\n?([\s\S]*?)^[ \t]*(?:>[ \t]?)?\2`*[ \t]*$/gm;

/* An opening fence with NO closing partner yet — the answer is still being
   written, and everything from the fence to the end of the text is already
   its content. Looked for only AFTER the closed pairs are out of the text, so
   at most one can be left over.

   One constant for the same reason ZAUN_PAAR is one: `rendern` draws what
   stands behind this fence and `openFile` names it, and the two must see
   the same fence or a card and its file drift apart.

   `$` still means the end of the whole text despite the `m` flag: the run
   before it is greedy, so it reaches the end on the first try. The flag is
   there for the `^` of the line-start branch. The mid-line branch is the
   same one ZAUN_PAAR has, for the same reason: a fence a model opened after
   a few words of prose is a block being written, and it has to be drawn as
   one while it streams and not only once its closing fence has arrived.

   The quote marker is here for the same reason it is in ZAUN_PAAR: a callout
   is written from its first line like anything else, so between the chunk
   that brings "> ```bash" and the one that brings its closing fence the
   block is open. No `g` flag — there is one such fence or none.

   The line break behind the language is a group of its own because it is
   what says the language is complete (`openDocument` below). */
const OPEN_FENCE = /(?:^[ \t]*(>[ \t]?)?|(?<=\S)[ \t]*(?=`{3,}[\w+-]*\n))(`{3,})([\w+-]*)(\n?)([\s\S]*)$/m;

/* Whether an open fence is a document ALREADY — asked by `rendern` and by
   `openFile` with the groups of OPEN_FENCE, so both give the same answer.

   The language has to stand complete first: something must follow it, the
   line break or any other character. A fence arrives letter by letter, and
   "```json" is also the beginning of "```jsonc" — taken for a document one
   piece too early, it put a file card into the answer and an empty tab into
   the rail for a file that was never going to exist. */
function openDocument(sprache, lineEnd, code) {
  return Boolean(dateiart(sprache) && (lineEnd || code))
}

function rendern(quelltext) {
  const bloecke = [];
  let dateien = 0;

  // Take out the code blocks before anything else happens. What counts as
  // one is written down at ZAUN_PAAR above, once, for this function and for
  // dateienAus() alike.
  let text = String(quelltext || '').replace(
    ZAUN_PAAR,
    function (_, zitat, zaun, sprache, code) {
      /* A fence inside a blockquote is a fence — CommonMark says so, and a
         model writing a callout ("> **Note:** run this:") writes one every
         time. Anchoring at the line start alone stopped recognising them,
         and what the reader got instead was the raw backticks with the
         whole block glued into one line.

         The quote marker comes off every line of the code. Keeping it in
         would put "> " in front of every line inside the box, and copying
         it would paste something that does not run. The closing fence's own
         marker never gets here — ZAUN_PAAR eats it together with the fence,
         now that the fence is matched as a whole line — so what is left
         over at the end is only the newline before it, and that is what the
         `\n$` takes. */
      const roh = (imZitat(zitat, code) ? entzitieren(code) : code).replace(/\n$/, '');
      const art = dateiart(sprache);

      // A document does not want to be read as source in the middle of an
      // answer — it wants to be looked at, kept, or put away. So it becomes
      // a closed box, and the source rides along inside it, hidden: the
      // preview window then needs no second channel to get at it.
      if (art) return dateiMarke(dateien++);

      bloecke.push(codeRahmen(roh, sprache, false));
      return '' + (bloecke.length - 1) + '';
    }
  );

  /* A fence that has NO closing partner yet - the answer is still being
     written (OPEN_FENCE above says what counts as one). Everything from it to
     the end is already its content, so it is drawn right away and grows with
     each chunk, instead of standing there as loose text until the last three
     backticks arrive.

     A document gets its card from the first line on, exactly as it will
     stand once the fence closes: nothing unfolds and collapses again, and
     the raw source never shows in the answer. The card is told by
     `openFile` that its file is still open. Code keeps its box and grows
     in it — while it is being written the source is what one wants to watch.

     No copy button on that box - half-written code is not worth copying, and
     the button arrives with the closing fence anyway. The `offen` class is
     what tells the stylesheet this block is still being written. */
  text = text.replace(OPEN_FENCE, function (treffer, zitat, zaun, sprache, lineEnd, code) {
    if (openDocument(sprache, lineEnd, code)) return dateiMarke(dateien++);
    const roh = (imZitat(zitat, code) ? entzitieren(code) : code).replace(/\n$/, '');
    /* Nothing behind the fence is not a block being written, it is a
       stray closing fence with no opening of its own. Drawn as an open
       block it became an empty grey box wearing the "still being written"
       style under a finished answer. Left as it stands, so the reader sees
       the stray marks rather than a box that means nothing. */
    if (!roh.trim()) return treffer;
    bloecke.push(codeRahmen(roh, sprache, true));
    return blockMarke(bloecke.length - 1);
  });

  text = maskieren(text);

  const zeilen = text.split('\n');
  const raus = [];
  let liste = null, zitat = [], absatz = [];

  const absatzSchliessen = () => {
    if (absatz.length) { raus.push('<p>' + inline(absatz.join(' ')) + '</p>'); absatz = []; }
  };
  const listeSchliessen = () => {
    if (liste) { raus.push('</' + liste + '>'); liste = null; }
  };
  const zitatSchliessen = () => {
    if (zitat.length) {
      raus.push('<blockquote>' + inline(zitat.join(' ')) + '</blockquote>');
      zitat = [];
    }
  };
  const allesSchliessen = () => { absatzSchliessen(); listeSchliessen(); zitatSchliessen(); };

  for (let i = 0; i < zeilen.length; i++) {
    const zeile = zeilen[i];
    const roh = zeile.trim();

    if (!roh) { allesSchliessen(); continue; }

    if (/^\d+$/.test(roh)) { allesSchliessen(); raus.push(roh); continue; }
    if (/^datei\d+$/.test(roh)) { allesSchliessen(); raus.push(roh); continue; }

    const ueberschrift = roh.match(/^(#{1,4})\s+(.*)$/);
    if (ueberschrift) {
      allesSchliessen();
      const stufe = ueberschrift[1].length + 1;
      raus.push('<h' + stufe + '>' + inline(ueberschrift[2]) + '</h' + stufe + '>');
      continue;
    }

    if (/^(-{3,}|\*{3,}|_{3,})$/.test(roh)) { allesSchliessen(); raus.push('<hr>'); continue; }

    if (/^&gt;\s?/.test(roh)) {
      absatzSchliessen(); listeSchliessen();
      zitat.push(roh.replace(/^&gt;\s?/, ''));
      continue;
    }

    // Table: header row plus a separator row of dashes
    if (roh.includes('|') && i + 1 < zeilen.length && /^\s*\|?[\s:-]+\|[\s|:-]*$/.test(zeilen[i + 1])) {
      allesSchliessen();
      const block = [zeilen[i], zeilen[i + 1]];
      let j = i + 2;
      while (j < zeilen.length && zeilen[j].includes('|') && zeilen[j].trim()) { block.push(zeilen[j]); j++; }
      raus.push(tabelle(block));
      i = j - 1;
      continue;
    }

    const punkt = roh.match(/^[-*+]\s+(.*)$/);
    const nummer = roh.match(/^\d+\.\s+(.*)$/);
    if (punkt || nummer) {
      absatzSchliessen(); zitatSchliessen();
      const art = punkt ? 'ul' : 'ol';
      if (liste !== art) { listeSchliessen(); raus.push('<' + art + '>'); liste = art; }
      raus.push('<li>' + inline((punkt || nummer)[1]) + '</li>');
      continue;
    }

    listeSchliessen(); zitatSchliessen();
    absatz.push(roh);
  }
  allesSchliessen();

  return raus.join('\n').replace(/(\d+)/g, (_, i) => bloecke[i]);
}

/*
  The documents in one answer, without rendering it.

  The rail beside the chat opens a tab for each of them as they arrive, and
  it must not have to read that out of the page: the answer is the source,
  the DOM is only a picture of it. Same rule as above decides what counts as
  a document — one function, not two that drift apart.
*/
function dateienAus(quelltext, versatz = 0) {
  const gefunden = [];
  let dateien = versatz;
  String(quelltext || '').replace(
    // The SAME pattern `rendern` uses — literally the same object now, not
    // a second copy of it. The comment above says one function and not two
    // that drift apart, and they did: teaching only `rendern` that a fence
    // inside a blockquote is a fence left this one counting differently, so
    // a document written in a callout vanished from the answer without a
    // trace — and where a second document followed, its card took the
    // missing one's place. Two copies is how that happened; one is why it
    // cannot happen again.
    ZAUN_PAAR,
    function (_, zitat, zaun, sprache, code) {
      const art = dateiart(sprache);
      if (art) {
        gefunden.push({
          name: dateiname(sprache, ++dateien),
          art: sprache.toLowerCase(),
          inhalt: (imZitat(zitat, code) ? entzitieren(code) : code).replace(/\n$/, ''),
        });
      }
      return '';
    },
  );
  return gefunden;
}

/*
  The document an answer is still writing, or null.

  `dateienAus` above knows closed fences only, and has to stay that way: the
  stream reads it to tell that a file is FINISHED. This is the other half —
  the one fence that has no closing partner yet (OPEN_FENCE). It carries the
  number the file will keep once its fence closes, so the card that stands
  for it now is the card that stands for it then, under the same name.

  `open` is what tells a view that the text is not all there yet. Whether
  the answer is still running is not something a text can say — a message cut
  short ends in the same open fence — so the view decides what that means.
*/
function openFile(quelltext, versatz = 0) {
  let closed = 0
  const rest = String(quelltext || '').replace(
    ZAUN_PAAR,
    function (_, zitat, zaun, sprache) {
      if (dateiart(sprache)) closed++
      // Something that is no blank stays in its place, as in `rendern`: what
      // follows must not suddenly stand at the start of a line.
      return blockMarke(0)
    },
  )
  const match = OPEN_FENCE.exec(rest)
  if (!match) return null
  const [, zitat, , sprache, lineEnd, code] = match
  if (!openDocument(sprache, lineEnd, code)) return null
  return {
    name: dateiname(sprache, versatz + closed + 1),
    art: sprache.toLowerCase(),
    inhalt: (imZitat(zitat, code) ? entzitieren(code) : code).replace(/\n$/, ''),
    open: true,
  }
}

/*
  Whether a text ends in a fence that is not settled yet: its marks, perhaps
  the beginning of a language, and nothing behind them.

  What such an end means is open until more text comes. "```" closes the
  block above it, and "```bash" — the same marks, one piece of text later —
  opens an inner one instead and the block above is open again; "```" behind
  a few words of prose is nothing, and "```markdown" with its line break is
  a document. Whoever follows an answer while it is written has to look once
  more after an end like this, even when the piece that settles it carries
  no fence mark at all.

  Wherever the marks stand, at the start of a line or behind prose: both
  open a block (OPEN_FENCE). Only the tail is read — this is asked for every
  piece of an answer.
*/
const FENCE_UNSETTLED = /`{3,}[\w+-]*$/
function endsInFence(text) {
  return FENCE_UNSETTLED.test(String(text || '').slice(-80))
}

// Matches a file marker inside rendern()'s own output — dateiTeile() below
// splits on it to put a live card where this only left a mark.
const DATEI_MARKE = new RegExp(String.fromCharCode(1) + 'datei(\\d+)' + String.fromCharCode(1), 'g')

/* An answer cut into the pieces a view has to draw: rendered HTML and, in
   between, the file a card belongs to. Alternating, so an even index is
   always HTML and an odd one always a file.

   Every view that shows rendered text goes through here, because a marker
   is INVISIBLE when nobody resolves it: a caller that hands rendern()'s
   output straight to `{@html}` drops the whole file and shows no error at
   all. Making that the shared path is what keeps the next view from
   quietly losing files the way the agents panel did.

   `dateienAus()` reads the same fences a second time for the fields the
   card needs, so the two never have to agree on anything by hand.

   `versatz` is how many files the message already carried before this
   piece of text. A message is drawn section by section, but its file names
   are numbered across the WHOLE message — without the offset the second
   section starts counting at one again, and the same message shows
   different names depending on whether it was streamed or fetched. */
function dateiTeileRoh(text, versatz = 0) {
  const dateien = dateienAus(text, versatz)
  // The file still being written is the last marker `rendern` sets, and so
  // the last entry here.
  const unfinished = openFile(text, versatz)
  if (unfinished) dateien.push(unfinished)
  return rendern(text)
    .split(DATEI_MARKE)
    .map((stueck, i) =>
      i % 2 === 0
        ? { art: 'html', wert: stueck }
        : { art: 'datei', wert: dateien[Number(stueck)] },
    )
}

/* The memo lives HERE, beside the parse it guards, not in the views.

   While an answer streams, only the growing section's text ever changes —
   every finished section keeps hitting the cache instead of being rebuilt
   on each chunk. And the agents panel re-reads an unchanged report every
   three seconds when the poll replaces the job list. Both views used to
   carry this Map themselves, each with its own key scheme, already
   drifting apart — one shared path, one shared memo.

   The cap keeps a long day from holding every intermediate state of every
   answer; clearing outright is fine, the next draw simply parses again. */
const teileSpeicher = new Map()
function dateiTeile(text, versatz = 0) {
  const schluessel = `${versatz}\0${text}`
  let stuecke = teileSpeicher.get(schluessel)
  if (stuecke === undefined) {
    stuecke = dateiTeileRoh(text, versatz)
    if (teileSpeicher.size > 40) teileSpeicher.clear()
    teileSpeicher.set(schluessel, stuecke)
  }
  return stuecke
}

/* How many files a piece of text carries — memoised on its own, because
   the count is asked for once per FINISHED section on every streamed
   chunk (Nachricht.svelte's versaetze). Counting through dateiTeile()
   would spend a big cache slot on a zero offset; a number costs nothing
   to keep, so many of them may. */
const zahlSpeicher = new Map()
function dateienZahl(text) {
  let zahl = zahlSpeicher.get(text)
  if (zahl === undefined) {
    // The one still open counts: it has taken its number, and the next
    // section must not hand that number out again.
    zahl = dateienAus(text).length + (openFile(text) ? 1 : 0)
    if (zahlSpeicher.size > 200) zahlSpeicher.clear()
    zahlSpeicher.set(text, zahl)
  }
  return zahl
}

/* The click half of the copy button rendern() draws on every code block.
   The button only exists at runtime, so views listen on their container
   and hand the event here — ONE handler for every view, because the two
   copies it replaced had already begun to drift is exactly how the file
   boxes were lost once before. */
function codeKopierKlick(ereignis, fertig) {
  const knopf = ereignis.target.closest?.('.code-kopieren')
  if (!knopf) return
  const code = knopf.closest('.codeblock').querySelector('code')
  // A numbered block holds one row per line and no line breaks of its own.
  const reihen = code.querySelectorAll('.code-zeile')
  const text = reihen.length
    ? Array.from(reihen, (reihe) => reihe.textContent).join('\n')
    : code.textContent
  navigator.clipboard.writeText(text).then(fertig)
}

export {
  rendern, hervorheben, maskieren, dateienAus, openFile, endsInFence, nummernspalte, dateiTeile,
  dateienZahl, codeKopierKlick, KOPIER_ZEICHEN,
}
