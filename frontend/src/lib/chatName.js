/* The name a new chat takes from its first message: the first line, its
   white space drawn to single blanks. A longer one ends at the last word
   end that fits and carries "…" behind it; one without a word end in the
   first CHAT_NAME_LIMIT characters is cut at the limit. The window holds
   this rule here once — the message field and the picture studio both name
   the chat they open by it — and the terminal client holds the same rule
   in cli/chat.py. */
export const CHAT_NAME_LIMIT = 48

export function chatNameFrom(text) {
  const line = text.trim().split(/\r\n|\r|\n/, 1)[0]
  // By characters, not by UTF-16 units: a picture character is one.
  const chars = Array.from(line.trim().split(/\s+/).join(' '))
  if (chars.length <= CHAT_NAME_LIMIT) return chars.join('')
  const head = chars.slice(0, CHAT_NAME_LIMIT)
  // A blank right behind the limit: the head already ends at a word end.
  const end = chars[CHAT_NAME_LIMIT] === ' ' ? head.length : head.lastIndexOf(' ')
  return (end > 0 ? head.slice(0, end) : head).join('') + '…'
}
