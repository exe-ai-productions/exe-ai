/* The shortcuts the program has besides the microphone key, to look up:
   the page's own (frontend/src/App.svelte) and those of the shell's menu
   (fenster-electron/main.js). Neither place has a list to read, so the rows
   are written out here; the names are the ones the Mac menu shows.

   Each row: its name, its keys the way the Mac has them, and — only where
   the shell's menu answers differently off the Mac — what it answers to
   there, by system. `null` says the menu has no such entry on that system,
   and the row is left out: a row naming keys that do nothing would be
   untrue. The roles of the menu carry their keys per system: the developer
   tools open with Control + Shift + I off the Mac, Redo is Control + Y on
   Windows, and Quit stands in the program's own menu, which only a Mac has.
   A fourth entry is the name the row has off the Mac, where the Mac's name
   speaks of something only a Mac has: a window is laid into the Dock there
   and minimised everywhere else.
   No imports besides the one module the tests run in node as well. */
import { showKeys } from './microphoneKey.js'

const GROUPS = [
  {
    title: 'shortcuts.group_window',
    rows: [
      ['shortcuts.new_chat', [['Mod'], 'N']],
      ['shortcuts.settings', [['Mod'], ',']],
      ['shortcuts.sidebar', [['Mod'], 'B']],
      ['shortcuts.tools', [['Mod'], 'J']],
      ['shortcuts.cli', [['Control'], '`']],
      ['shortcuts.search', [['Mod'], 'K']],
      ['shortcuts.close', [[], 'Esc']],
    ],
  },
  {
    title: 'shortcuts.group_app',
    rows: [
      ['shortcuts.reload', [['Mod'], 'R']],
      [
        'shortcuts.devtools',
        [['Mod', 'Alt'], 'I'],
        { windows: [['Mod', 'Shift'], 'I'], other: [['Mod', 'Shift'], 'I'] },
      ],
      ['shortcuts.zoom_in', [['Mod'], '+']],
      ['shortcuts.zoom_out', [['Mod'], '−']],
      ['shortcuts.actual_size', [['Mod'], '0']],
      ['shortcuts.minimize', [['Mod'], 'M'], {}, 'shortcuts.minimize_windows'],
      ['shortcuts.close_window', [['Mod'], 'W']],
      ['shortcuts.quit', [['Mod'], 'Q'], { windows: null, other: null }],
    ],
  },
  {
    title: 'shortcuts.group_edit',
    rows: [
      ['shortcuts.undo', [['Mod'], 'Z']],
      ['shortcuts.redo', [['Shift', 'Mod'], 'Z'], { windows: [['Mod'], 'Y'] }],
      ['shortcuts.cut', [['Mod'], 'X']],
      ['shortcuts.copy', [['Mod'], 'C']],
      ['shortcuts.paste', [['Mod'], 'V']],
      ['shortcuts.select_all', [['Mod'], 'A']],
    ],
  },
]

/** The groups with the rows `system` ('mac', 'windows' or 'other') has,
    each row as its name and its keys as shown: with `names` in the words on
    the modifier keys, without them in the Mac's signs (showKeys). */
export function shortcutList(system, names = null) {
  return GROUPS.map(({ title, rows }) => ({
    title,
    rows: rows
      .map(([name, keys, elsewhere = {}, nameOffMac = name]) => [
        system === 'mac' ? name : nameOffMac,
        system in elsewhere ? elsewhere[system] : keys,
      ])
      .filter(([, keys]) => keys)
      .map(([name, [mods, key]]) => [name, showKeys(mods, key, names)]),
  }))
}
