/*
  What the voice reads, and in which pieces.

  An answer is written as Markdown for the eye. Read out as it stands, the
  voice speaks asterisks, backticks and whole code blocks. So the text is
  first turned into a spoken script: code blocks and thinking blocks go,
  a link keeps only its words, emphasis and list marks disappear.

  And it is cut while it is still being written. Waiting for the whole
  answer before the first word meant sitting through the model's writing
  AND the voice's rendering of everything, one after the other. Cut at
  each finished sentence, the first one can already be spoken while the
  model is still writing the rest.

  A piece ends at a sentence boundary, with a floor of 20 characters: a
  shorter piece is carried into the next one rather than spoken alone.
*/

// A block of code or of thinking, closed, anywhere in the text.
const CODEBLOCK = /(`{3,})[^\n]*\n(?:[\s\S]*?\n)?[ \t]*\1[ \t]*(?=\n|$)/g;
const DENKBLOCK = /<think[\s>][\s\S]*?<\/think>/g;

/* Turns Markdown into a spoken script.

   A code fence or a thinking tag that is still open is the answer being
   written: everything from it on is held back — its closing mark has not
   arrived, and whatever sits inside it is not to be spoken. The text
   before it stays exactly as it was, so a piece already cut from it never
   shifts. */
export function sprechtextPutzen(text) {
  let s = String(text || '').replace(/\r\n?/g, '\n');
  s = s.replace(DENKBLOCK, '\n\n');
  const offenesDenken = s.search(/<think[\s>]/);
  if (offenesDenken >= 0) s = s.slice(0, offenesDenken);
  s = s.replace(CODEBLOCK, '\n\n');
  // Any fence mark left over after the closed blocks are gone is an open
  // one — also one a model opened after a few words on the same line.
  const offenerZaun = s.search(/`{3,}/);
  if (offenerZaun >= 0) s = s.slice(0, offenerZaun);
  return s
    // Pictures keep their description, links their words.
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/`([^`\n]+)`/g, '$1')
    .replace(/\*\*([^*\n]+)\*\*/g, '$1')
    .replace(/(^|[^*])\*([^*\n]+)\*/g, '$1$2')
    .replace(/~~([^~\n]+)~~/g, '$1')
    .replace(/<[^>\n]+>/g, '')
    // Line marks: headings, quotes, list bullets and numbers. A numbered
    // item's "1." would otherwise also end a sentence on the spot.
    .replace(/^[ \t]*#{1,6}[ \t]+/gm, '')
    .replace(/^[ \t]*>[ \t]?/gm, '')
    .replace(/^[ \t]*(?:[-*+]|\d+[.)])[ \t]+/gm, '')
    // A rule is nothing to say; a table row is its cells, one after another.
    .replace(/^[ \t]*(?:[-*_][ \t]*){3,}$/gm, '')
    .replace(/^[ \t]*\|?[ \t]*:?-{3,}:?[ \t]*(?:\|[ \t]*:?-{3,}:?[ \t]*)*\|?[ \t]*$/gm, '')
    .replace(/^[ \t]*\|(.*)\|[ \t]*$/gm, (_, zellen) =>
      zellen.split('|').map((z) => z.trim()).filter(Boolean).join(', '));
}

/* How far a new script has already been cut, given the old one and its count.

   The count points into the script as it stood when it was cut. The script
   can change behind that point — an emphasis closed later, the finished
   answer read back after the run's end — and a stale count would then read
   a piece twice or start in the middle of a word. So the count is set again
   on the end of what was already cut; with no such anchor to be found, the
   old script keeps being read. */
export function neuAusrichten(alt, gelesen, neu) {
  const bisher = alt.slice(0, gelesen);
  if (neu.startsWith(bisher)) return { script: neu, gelesen };
  // Longest anchor first; a shorter one still holds when the change sits
  // close to where the cutting stopped.
  for (const laenge of [40, 20, 10]) {
    const anker = bisher.slice(-laenge);
    if (anker.trim().length < 6) break;
    const stelle = neu.indexOf(anker);
    if (stelle >= 0) return { script: neu, gelesen: stelle + anker.length };
  }
  return { script: alt, gelesen };
}

// After a sentence's end mark and some whitespace, or at a blank line.
const SATZGRENZE = /(?<=[.!?])\s|\n\n/g;
// The same, and after a comma as well: where the first piece of an answer may
// end, so the voice starts on the first clause instead of the first sentence.
const FIRST_PIECE_BOUNDARY = /(?<=[.!?,])\s|\n\n/g;
// A piece shorter than this is carried into the next one: "Yes." or "1." on
// their own are no sentence worth a start of the voice.
export const MINDESTLAENGE = 20;

/* The pieces that are finished in a spoken script, counted from `ab` (how
   much of it has already been handed out). Returns the new pieces and how
   far they reach. With `fertig` the answer is complete and whatever is left
   goes out as the last piece.

   The first piece of an answer (nothing handed out yet) may end at a comma,
   every further one ends at a sentence's end. */
export function stueckeSchneiden(script, ab, fertig) {
  const stuecke = [];
  let start = ab;
  let grenze = ab === 0 ? FIRST_PIECE_BOUNDARY : SATZGRENZE;
  grenze.lastIndex = ab;
  let treffer;
  while ((treffer = grenze.exec(script)) !== null) {
    const ende = treffer.index + treffer[0].length;
    const stueck = script.slice(start, ende);
    if (stueck.trim().length < MINDESTLAENGE) continue;
    stuecke.push(stueck.trim());
    start = ende;
    if (grenze !== SATZGRENZE) {
      grenze = SATZGRENZE;
      grenze.lastIndex = ende;
    }
  }
  if (fertig) {
    const rest = script.slice(start).trim();
    if (rest) stuecke.push(rest);
    start = script.length;
  }
  return { stuecke, bis: start };
}
