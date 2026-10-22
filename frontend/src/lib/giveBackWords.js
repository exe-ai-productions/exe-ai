/*
  The words of messages that come back out of the line (a stop by hand, or
  the ✕ on a bubble): in the order they were written, standing in front of
  whatever has been typed since. Nothing typed is lost and nothing stands
  twice; an empty message adds no empty line.
*/

export function wordsInFront(entries, typed) {
  const front = entries
    .map((entry) => entry.inhalt ?? '')
    .filter((words) => words.trim())
    .join('\n')
  return front && typed.trim() ? `${front}\n${typed}` : front || typed
}
