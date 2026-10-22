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

/* The tick the copy button shows once the text is on the clipboard: the
   house's `haken` drawing (Hauszeichen.svelte) at the copy mark's size and
   stroke. It lies over the copy mark and the two cross-fade (codeblock.css). */
export const TICK_SIGN =
  '<svg class="code-tick" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
  '<path d="M4 12.5 L9.5 18 L20 6.5" /></svg>';
// How long the tick stays before the copy mark comes back.
const TICK_MS = 1000;

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
    : `<button class="code-kopieren" title="${kopieren}" aria-label="${kopieren}">${KOPIER_ZEICHEN}${TICK_SIGN}</button>`;
  const kennung = sprache ? `<span class="code-sprache">${maskieren(sprache)}</span>` : '';
  // The digit count sizes the number column, so row 9 and row 10 line up.
  const breite = zeilen > 1 ? ` style="--ziffern:${String(zeilen).length}"` : '';
  const inhalt = zeilen > 1 ? zeilenReihen(html) : html;
  return `<div class="${klassen.join(' ')}">` + kennung + knopf +
    `<pre><code${breite}>` + inhalt + '</code></pre></div>';
}

/* ---------- Markdown ---------- */

/* A markdown image, as far as the program draws one.

   Only what the page may load anyway (the content policy lists `'self'`,
   `data:` and `blob:` for images): a path of the program's own service
   (`/…`, never `//…`), a full address of its own origin, or an inline
   `data:image/`. Any other `http(s)` address becomes a link, the way every
   other address in the answer does — the alt text is its text, the address
   itself when there is none. Everything else stays text.

   `adresse` and `alt` arrive masked (`maskieren`), so they go into the
   attributes as they are. */
function bildAdresseErlaubt(adresse) {
  if (/^\/(?!\/)/.test(adresse)) return true;
  if (/^data:image\/[a-z0-9.+-]+[;,]/i.test(adresse)) return true;
  const eigene = typeof location !== 'undefined' && location.origin ? location.origin : '';
  return Boolean(eigene) && adresse.startsWith(eigene + '/');
}

// One attribute, its value already masked (`maskieren`).
const attribut = (name, wert) => name + '="' + wert + '"';

function bildOderLink(alt, adresse) {
  if (bildAdresseErlaubt(adresse)) {
    return '<img ' + [
      attribut('class', 'md-bild'), attribut('src', adresse), attribut('alt', alt),
      attribut('loading', 'lazy'),
    ].join(' ') + '>';
  }
  if (/^https?:/.test(adresse)) {
    return '<a href="' + adresse + '" target="_blank" rel="noopener noreferrer">' +
      (alt || adresse) + '</a>';
  }
  return null;
}

function inline(text) {
  // Emphasis is done with asterisks only. Underscores are left alone on
  // purpose: this program is full of file paths, and app/__init__.py or
  // my_file_name would otherwise turn half a path bold or italic and break
  // the click-and-copy the path is there for. Standard Markdown allows both
  // markers; for a terminal that talks in paths, one of them is a liability.
  //
  // A finished image is set aside and put back at the very end: its
  // attributes must not be read by the emphasis and link rules below, which
  // would write markup into them. A code span is set aside the same way:
  // what stands between backticks is written character for character, so no
  // rule below may reach into it — a command with `2*3*4` or `x**2` in it
  // would otherwise be copied out wrong.
  const beiseite = [];
  return text
    // A code span is taken out whole, so an image written in backticks stays
    // the text it was written as. In the same pass as the images, so that an
    // alt text with backticks in it is not already markup when it is read.
    .replace(/`([^`]+)`|!\[([^\]]*)\]\(([^)\s]+)\)/g,
      (alles, code, alt, adresse) => {
        if (code !== undefined) {
          beiseite.push('<code>' + code + '</code>');
          return '\x02' + (beiseite.length - 1) + '\x02';
        }
        const html = bildOderLink(alt, adresse);
        if (html === null) return alles;
        beiseite.push(html);
        return '\x02' + (beiseite.length - 1) + '\x02';
      })
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>')
    .replace(/~~([^~]+)~~/g, '<del>$1</del>')
    .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>')
    // A bare address is a link too. What is already markup — a code span, a
    // finished link, any tag — is left as it stands; only the text between
    // is read, and an address in it is cut by the rule of the own message.
    .replace(/(<code>.*?<\/code>|<a [^>]*>.*?<\/a>|<[^>]+>)|([^<]+)/gs,
      (alles, markup, text) => (markup ? markup : adressenVerlinken(text)))
    .replace(/\x02(\d+)\x02/g, (_, i) => beiseite[i]);
}

/* The bare addresses of one stretch of text that is already masked
   (`maskieren`), as links. The stretch is unmasked for the cut — `&lt;`,
   `&gt;` and `&quot;` end an address like the marks themselves do, a `;` of
   an entity is no sentence mark — and every piece is masked again on the
   way out. */
function adressenVerlinken(maskiert) {
  if (!/https?:\/\//i.test(maskiert)) return maskiert;
  const roh = maskiert.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"')
    .replace(/&amp;/g, '&');
  return adressTeile(roh).map((teil) => (teil.href
    ? '<a href="' + maskieren(teil.href) + '" target="_blank" rel="noopener noreferrer">' +
      maskieren(teil.text) + '</a>'
    : maskieren(teil.text))).join('');
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

   ONE constant, because `rendern`, `dateienAus` and `openFile` all read it
   and MUST agree — they were two hand-written copies once, only one of them learned
   that a fence inside a blockquote is a fence, and a document written in a
   callout vanished from the answer without a trace. Nothing left to drift.
   The readers go through `zaeuneErsetzen`, which works on a copy of this
   pattern, so no caller's `lastIndex` is ever shared.

   The OPENING fence may also stand in the middle of a line. Small models
   write "Here is the fix: ```python" and put the code on the next line all
   the time, and code has to be drawn as code wherever its fence happens to
   stand. What keeps an inline span such as "run ```js``` inline" from
   opening a block is the lookahead in the mid-line branch: an opening
   fence that does not stand at a line start has to be followed by nothing
   but its info word and a line break, which is what a fence is and an
   inline span never has. The CLOSING fence stays a line of its own — that
   half is what protects command output, and it is unchanged. */
const ZAUN_PAAR = /(?:^[ \t]*(>[ \t]?)?|(?<=\S)[ \t]*(?=`{3,}[\w+-]*\n))(`{3,})([\w+-]*)\n?([\s\S]*?)^[ \t]*(?:>[ \t]?)?\2`*[ \t]*$/gmd;

/* A line that is a fence and nothing else but its language: the marks, the
   word behind them, the end of the line. The quote marker may stand in
   front, as it may in ZAUN_PAAR. */
const ZAUN_ZEILE = /^[ \t]*(?:>[ \t]?)?(`{3,})([\w+-]*)[ \t]*$/;

/* Whether a document's content opens a block of its own: a fence line with a
   language, at least as long as the document's own fence. CommonMark closes
   a block at the first bare fence and knows no document inside it; this is
   the one place the reader departs from it, and only INSIDE a document —
   its source would otherwise run on into the answer as raw text. */
function hatInnerenBlock(code, laenge) {
  return code.split('\n').some((zeile) => {
    const treffer = ZAUN_ZEILE.exec(zeile);
    return Boolean(treffer && treffer[2] && treffer[1].length >= laenge);
  });
}

/* Where a document really ends, read from the start of its content: the
   first bare fence line that does not close a block of its own. A fence with
   a language opens such a block, and its closing fence is the first bare one
   at least as long as the block's opening; inside it a language fence is
   plain content. `null` while no closing fence of the document has come
   yet — the document is still being written. */
function dokumentEnde(text, ab, laenge) {
  let innen = 0;
  let pos = ab;
  for (;;) {
    const umbruch = text.indexOf('\n', pos);
    const zeileEnde = umbruch === -1 ? text.length : umbruch;
    const treffer = ZAUN_ZEILE.exec(text.slice(pos, zeileEnde));
    if (treffer && treffer[1].length >= laenge) {
      if (treffer[2]) {
        if (!innen) innen = treffer[1].length;
      } else if (innen) {
        if (treffer[1].length >= innen) innen = 0;
      } else {
        return { inhaltEnde: pos, ende: zeileEnde };
      }
    }
    if (umbruch === -1) return null;
    pos = umbruch + 1;
  }
}

/* `text.replace(ZAUN_PAAR, ersatz)` with the one departure above: a
   document whose content opens an inner block ends at ITS closing fence, not
   at the inner block's. `rendern`, `dateienAus` and `openFile` all read
   fences through here, so what is a document is decided once. A document
   that has not closed yet is left in the text as it stands, together with
   everything behind it — it is still being written, and OPEN_FENCE takes it
   from its first fence on. */
function zaeuneErsetzen(text, ersatz) {
  const paar = new RegExp(ZAUN_PAAR.source, ZAUN_PAAR.flags);
  let aus = '';
  let stand = 0;
  let treffer;
  while ((treffer = paar.exec(text)) !== null) {
    let [alles, zitat, zaun, sprache, code] = treffer;
    let ende = treffer.index + alles.length;
    if (dateiart(sprache) && hatInnerenBlock(code, zaun.length)) {
      const echt = dokumentEnde(text, treffer.indices[4][0], zaun.length);
      if (echt === null) break;
      code = text.slice(treffer.indices[4][0], echt.inhaltEnde);
      ende = echt.ende;
      alles = text.slice(treffer.index, ende);
    }
    aus += text.slice(stand, treffer.index) + ersatz(alles, zitat, zaun, sprache, code);
    stand = ende;
    paar.lastIndex = ende;
  }
  return aus + text.slice(stand);
}


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
  let text = zaeuneErsetzen(
    String(quelltext || ''),
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

  return zeilenRendern(text.split('\n')).replace(BLOCK_MARKE, (_, i) => bloecke[i]);
}

/* The blocks of a run of lines. A quote hands its own lines (the marker
   taken off) back to this function, so what stands in a quote is read by the
   same rules as what stands outside it: paragraphs, lists, headings. */
function zeilenRendern(zeilen) {
  const raus = [];
  let zitat = [], absatz = [];

  /* The lists that stand open, the outermost first. A level knows where its
     marker stands (`rand`) and where the text of its item begins (`inhalt`,
     the marker, its blanks and the margin): a line indented to that column
     belongs to the item, a marker indented to it opens a list inside the
     item, a marker left of it is the item's sibling or an outer list's.
     `text` is the item still being written, `kopfGeschrieben` whether its
     opening tag and first text are already out (a list inside it has to come
     after them). */
  const listen = [];
  /* The box in front of the text of a task item (`- [ ] text`, `- [x] text`):
     the browser's own box, locked, ticked for an `x`. */
  const kasten = (ebene) => {
    if (ebene.aufgabe === undefined) return '';
    return '<input type="checkbox" disabled' + (ebene.aufgabe ? ' checked' : '') + '> ';
  };
  const punktKopf = (ebene) => {
    if (!ebene.kopfGeschrieben) {
      raus.push('<li>' + kasten(ebene) + inline(ebene.text.join(' ')));
      ebene.kopfGeschrieben = true;
    }
  };
  const punktSchliessen = (ebene) => {
    if (!ebene.punktOffen) return;
    if (ebene.kopfGeschrieben) raus.push('</li>');
    else raus.push('<li>' + kasten(ebene) + inline(ebene.text.join(' ')) + '</li>');
    ebene.punktOffen = false;
  };
  const ebeneSchliessen = () => {
    const ebene = listen.pop();
    punktSchliessen(ebene);
    raus.push('</' + ebene.art + '>');
  };
  const listeSchliessen = () => { while (listen.length) ebeneSchliessen(); };
  const absatzSchliessen = () => {
    if (absatz.length) { raus.push('<p>' + inline(absatz.join(' ')) + '</p>'); absatz = []; }
  };
  const zitatSchliessen = () => {
    if (!zitat.length) return;
    /* One paragraph stands in the quote as bare text, as it always did; more
       blocks stand as they are. */
    const innen = zeilenRendern(zitat);
    const einzeln = innen.match(/^<p>((?:(?!<\/?p>)[\s\S])*)<\/p>$/);
    raus.push('<blockquote>' + (einzeln ? einzeln[1] : innen) + '</blockquote>');
    zitat = [];
  };
  const allesSchliessen = () => { absatzSchliessen(); listeSchliessen(); zitatSchliessen(); };

  /* How far a line is indented, a tab counting as four blanks. */
  const einzugVon = (zeile) => zeile.match(/^[ \t]*/)[0].replace(/\t/g, '    ').length;
  const PUNKT_MARKE = /^([ \t]*)([-*+]|\d+\.)([ \t]+)(\S.*)$/;

  for (let i = 0; i < zeilen.length; i++) {
    const zeile = zeilen[i];
    const roh = zeile.trim();

    if (!roh) {
      /* A blank line does not end a list that goes on: the next line is
         another item, or indented to the open item's text. */
      let weiter = i + 1;
      while (weiter < zeilen.length && !zeilen[weiter].trim()) weiter++;
      const folgt = zeilen[weiter];
      const geht = listen.length && folgt !== undefined && (
        PUNKT_MARKE.test(folgt) ||
        einzugVon(folgt) >= listen[0].inhalt
      );
      if (geht) { i = weiter - 1; continue; }
      allesSchliessen();
      continue;
    }

    if (/^\d+$/.test(roh)) { allesSchliessen(); raus.push(roh); continue; }
    if (/^datei\d+$/.test(roh)) { allesSchliessen(); raus.push(roh); continue; }

    // Six hashes are the deepest heading; the fourth level and below look alike.
    const ueberschrift = roh.match(/^(#{1,6})\s+(.*)$/);
    if (ueberschrift) {
      allesSchliessen();
      const stufe = Math.min(ueberschrift[1].length, 4) + 1;
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

    const punkt = zeile.match(PUNKT_MARKE);
    if (punkt) {
      absatzSchliessen(); zitatSchliessen();
      const rand = einzugVon(punkt[1]);
      const marke = punkt[2];
      const art = /^\d/.test(marke) ? 'ol' : 'ul';
      // The text starts after the marker and its blanks; five blanks or
      // more are the start of a code block in CommonMark, so one counts.
      const inhalt = rand + marke.length + (punkt[3].length > 4 ? 1 : punkt[3].length);
      while (listen.length && rand < listen[listen.length - 1].rand) ebeneSchliessen();
      let oben = listen[listen.length - 1];
      if (oben && rand >= oben.inhalt) {
        // Inside the open item: its text first, then the list.
        punktKopf(oben);
        oben = null;
      } else if (oben && oben.art !== art) {
        ebeneSchliessen();
        oben = null;
      }
      if (oben) {
        punktSchliessen(oben);
      } else {
        const start = art === 'ol' ? parseInt(marke, 10) : 1;
        raus.push('<' + art + (start !== 1 ? ' start="' + start + '"' : '') + '>');
        listen.push({ art, rand, inhalt, text: [], kopfGeschrieben: false, punktOffen: false });
        oben = listen[listen.length - 1];
      }
      oben.inhalt = inhalt;
      const aufgabe = punkt[4].match(/^\[([ xX])\][ \t]+(\S.*)$/);
      if (aufgabe) oben.aufgabe = aufgabe[1] !== ' ';
      else delete oben.aufgabe;
      oben.text = [(aufgabe ? aufgabe[2] : punkt[4]).trim()];
      oben.kopfGeschrieben = false;
      oben.punktOffen = true;
      continue;
    }

    /* A line indented to the text of an open item continues that item: the
       item it reaches, the lists inside it closed. Anything not indented
       that far ends the lists and is a paragraph of its own. */
    if (listen.length && einzugVon(zeile) >= listen[0].inhalt) {
      absatzSchliessen(); zitatSchliessen();
      const einzug = einzugVon(zeile);
      while (listen.length > 1 && einzug < listen[listen.length - 1].inhalt) ebeneSchliessen();
      const oben = listen[listen.length - 1];
      if (oben.kopfGeschrieben) raus.push(inline(roh));
      else oben.text.push(roh);
      continue;
    }

    listeSchliessen(); zitatSchliessen();
    absatz.push(roh);
  }
  allesSchliessen();

  return raus.join('\n');
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
  zaeuneErsetzen(
    String(quelltext || ''),
    // The SAME reading `rendern` uses — literally the same function now,
    // not a second copy of it. The comment above says one function and not
    // two that drift apart, and they did: teaching only `rendern` that a
    // fence inside a blockquote is a fence left this one counting
    // differently, so a document written in a callout vanished from the
    // answer without a trace — and where a second document followed, its
    // card took the missing one's place. Two copies is how that happened;
    // one is why it cannot happen again.
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
  const rest = zaeuneErsetzen(
    String(quelltext || ''),
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

/* How many files one row of a chat carries, for the numbering that runs
   across the whole chat: the rows of the person take no number, and neither
   does a finished background command's report — the card of its call
   already carries what it says. Counted with `dateienZahl`, memoised, so a
   long chat pays a lookup per message. */
function dateienInNachricht(nachricht) {
  return nachricht.role === 'assistant' && nachricht.art !== 'werkzeugmeldung' && nachricht.content
    ? dateienZahl(nachricht.content)
    : 0
}

/* How many files the answers BEFORE a message carry — what its own count
   goes on from, so that file names run across the whole chat and two
   answers never both hand out "markdown-1.md" (and so share one tab).
   `bis` is the message itself, or its id. */
function dateienDavor(nachrichten, bis) {
  const kennung = bis && typeof bis === 'object' ? bis.id : bis
  let summe = 0
  for (const n of nachrichten || []) {
    if (n === bis || (kennung != null && n.id === kennung)) break
    summe += dateienInNachricht(n)
  }
  return summe
}

/* The same number for every message at once, by id: one pass over the chat
   instead of one per message. The LAST message is the one that may still be
   growing and nobody stands after it, so it is not counted — scanning the
   answer that is being written on every piece would be quadratic work for a
   number nothing reads. */
function dateienVorherJeNachricht(nachrichten) {
  const karte = new Map()
  const liste = nachrichten || []
  let bisher = 0
  for (let i = 0; i < liste.length; i++) {
    karte.set(liste[i].id, bisher)
    if (i < liste.length - 1) bisher += dateienInNachricht(liste[i])
  }
  return karte
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
  // The tick comes only once the text is on the clipboard; a refused write
  // leaves the copy mark as it is and says nothing.
  navigator.clipboard.writeText(text).then(() => {
    showTick(knopf)
    fertig()
  }, () => {})
}

/* The button wears the tick for a second. A second press while it shows
   copies again and starts the second over: the timer lives on the button. */
export function showTick(knopf) {
  clearTimeout(knopf.tickTimer)
  knopf.classList.add('copied')
  knopf.tickTimer = setTimeout(() => knopf.classList.remove('copied'), TICK_MS)
}

/* The own message is plain text, not markup — only an address with `http://`
   or `https://` in it stands as a link, like a link in an answer. Cut into
   pieces, not into HTML: every piece is text the page draws itself, so
   nothing a person typed is ever read as markup. The pieces, put together,
   are the message character for character.

   A sentence mark behind the address is not part of it: `.` `,` `;` `:`
   `!` `?` and quotes, and a closing bracket unless the address itself has
   the opening one (a wiki address ending in `_(film)`). */
function adressTeile(inhalt) {
  const text = String(inhalt ?? '')
  const teile = []
  let ab = 0
  const zaehle = (s, zeichen) => s.split(zeichen).length - 1
  for (const treffer of text.matchAll(/https?:\/\/[^\s<>"'`]+/gi)) {
    let adresse = treffer[0]
    while (adresse) {
      const letztes = adresse.at(-1)
      if (!'.,;:!?)]}'.includes(letztes)) break
      if (letztes === ')' && zaehle(adresse, '(') >= zaehle(adresse, ')')) break
      if (letztes === ']' && zaehle(adresse, '[') >= zaehle(adresse, ']')) break
      if (letztes === '}' && zaehle(adresse, '{') >= zaehle(adresse, '}')) break
      adresse = adresse.slice(0, -1)
    }
    if (/^https?:\/\/$/i.test(adresse)) continue
    if (treffer.index > ab) teile.push({ text: text.slice(ab, treffer.index) })
    teile.push({ text: adresse, href: adresse })
    ab = treffer.index + adresse.length
  }
  if (ab < text.length) teile.push({ text: text.slice(ab) })
  return teile
}

export {
  rendern, hervorheben, maskieren, dateienAus, adressTeile, openFile, endsInFence, nummernspalte, zeilenReihen, dateiTeile,
  dateienZahl, dateienDavor, dateienVorherJeNachricht, codeKopierKlick, KOPIER_ZEICHEN,
}
