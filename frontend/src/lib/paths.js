/*
  How a path is shown and how its last part is read, wherever the program
  runs.

  Windows hands out `C:\Users\name\folder`, a network share as
  `\\server\share\folder`, and the model writes `notes\today.txt`; the house
  shows every path with forward slashes, in chips, tiles, tab names and
  lines of the terminal alike. Only a place that hands the path back to the
  system keeps the form the system gave (copy buttons, "show in the file
  manager", commands for the shell) — those never pass through here.

  A path counts as a Windows one when it starts with a drive letter or with
  two backslashes, or when it has a backslash and no slash at all. A path
  that starts with a slash is read as it is: on a Mac a backslash can be a
  letter of a file's name, and showing it as a slash would name a folder
  that is not there.

  No imports on purpose: werkzeughistorie.js uses it and runs in a test
  without the interface around it.
*/

export function isWindowsPath(path) {
  const text = String(path ?? '')
  if (/^[A-Za-z]:/.test(text) || text.startsWith('\\\\')) return true
  return text.includes('\\') && !text.includes('/')
}

/* The path as it is shown: slashes only. Text that is not a Windows path
   comes back unchanged. */
export function displayPath(path) {
  const text = String(path ?? '')
  return isWindowsPath(text) ? text.replace(/\\/g, '/') : text
}

/* The last part of a path, the folder's name. A drive alone has no name of
   its own and stands as `C:/`; the root of a Mac as `/`. */
export function lastPart(path) {
  const text = String(path ?? '')
  const parts = text.split(isWindowsPath(text) ? /[\\/]/ : '/').filter(Boolean)
  const last = parts[parts.length - 1]
  if (!last) return '/'
  return /^[A-Za-z]:$/.test(last) ? `${last}/` : last
}
