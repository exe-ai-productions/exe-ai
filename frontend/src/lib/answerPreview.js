/* The beginning of an answer, as one plain line for a notice: the visible
   text only (a thinking block that stayed in it goes), line breaks drawn to
   single blanks, and the marks of Markdown taken off — a link keeps its
   words, a code fence goes with its marker lines. The result is cut at
   PREVIEW_LIMIT characters; the card shortens it again to the width it has. */
export const PREVIEW_LIMIT = 240
/* Only the head of a long answer is read; the card shows a line of it. */
const READ_LIMIT = 20000

export function answerPreview(text) {
  if (typeof text !== 'string' || !text) return ''
  const plain = text
    .slice(0, READ_LIMIT)
    // A thinking block, closed or still open at the end of the text.
    .replace(/<think>[\s\S]*?(<\/think>|$)/gi, ' ')
    // The marker lines of a code fence; the code between them stays.
    .replace(/^[ \t]*(```|~~~).*$/gm, ' ')
    // A horizontal rule and the separator line of a table.
    .replace(/^[ \t]*([-*_]{3,}|\|?[ \t:|-]*-[ \t:|-]*\|?)[ \t]*$/gm, ' ')
    // An image or a link keeps its words; one pair of brackets inside the address is allowed.
    .replace(/!?\[([^\]]*)\]\((?:[^()]|\([^()]*\))*\)/g, '$1')
    // Heading, quote, list and task marks at the start of a line, however deeply nested.
    .replace(/^(?:[ \t]{0,3}(?:#{1,6}[ \t]+|>[ \t]?|[-*+][ \t]+(?:\[[ xX]\][ \t]+)?|\d+[.)][ \t]+))+/gm, '')
    // Strike and code marks always; emphasis marks only where they stand at the
    // edge of a word, so a name like chat_run.py or 2*3 keeps its own signs.
    .replace(/(~~|`)/g, '')
    .replace(/(?<![A-Za-z0-9])[*_]+|[*_]+(?![A-Za-z0-9])/g, '')
    .replace(/\s+/g, ' ')
    .trim()
  const head = plain.slice(0, PREVIEW_LIMIT * 2)
  const chars = Array.from(head)
  return chars.length <= PREVIEW_LIMIT ? head : chars.slice(0, PREVIEW_LIMIT).join('')
}
