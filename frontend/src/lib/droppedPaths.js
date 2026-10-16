/*
  What a terminal of the computer types for a file dropped on it: its path,
  written so the shell — here, the client `exe` — reads it back as one word.
  A blank in the path takes a backslash; on Windows the path stands in
  quotation marks. Several files are told apart by one blank.

  Pure, so it can be tried without a window or a terminal.
*/

/** One path, as a terminal of this system writes it. */
export function pathForShell(path, platform) {
  if (platform === 'windows') return `"${path}"`
  // A blank, a quotation mark, a backslash: each would end or bend the word
  // the client reads the path back as.
  return path.replace(/([\\ '"])/g, '\\$1')
}

/** The text for the files dropped, in the order they were dropped. */
export function droppedText(paths, platform) {
  return paths.filter(Boolean).map((path) => pathForShell(path, platform)).join(' ')
}
