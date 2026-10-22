// The top bar of the main window.
//
// On the Mac the system draws it itself — grey, darker than the frame under
// it, in no look's colour. So there the system's bar is left out and the page
// has no strip of its own either: the three window buttons stand in the first
// row of the sidebar, in front of the mark, and when the sidebar is folded
// over the signs of the narrow bar. The system puts the buttons over the page,
// at the place named here; the page marks the first row of the sidebar and
// the head of the right column as the window's drag region, where a double
// click does what the system does on its own bar.
//
// Its own file, and not a block inside main.js, for the reason adressregel.js
// is one: main.js requires electron, so nothing in it can be run outside a
// packaged window. Here the options are a function of the platform name, and
// node runs it (tests/test_top_bar.py). No electron, no window, no state.
//
// The file is listed in package.json under build.files. Left out, the
// packaged program starts and dies on the first require.

// Where the middle of the sidebar's first row lies below the window's top
// edge, in px: the 8 of the window body, the 14 of the row's padding and half
// of the 40 px of its button. The window buttons are centred on it.
const FIRST_ROW_CENTRE = 42

// A window button is 12 px tall.
const BUTTON_HEIGHT = 12

// The command-line argument that tells the page's bridge (preload.js) that
// the window buttons stand in the page. The bridge is sandboxed and can read
// no file of this folder, so the shell passes the fact instead of the bridge
// asking for the platform on its own.
const TOP_BAR_ARGUMENT = '--exe-top-bar'

// The window buttons' top left corner. Open, they stand right in front of the
// mark, which moves right to make room; folded, the three of them are centred
// over the 72 px of the narrow bar (they are 52 px wide together).
const BUTTONS_OPEN_X = 18
const BUTTONS_FOLDED_X = 10

function buttonsAt(folded) {
  return {
    x: folded ? BUTTONS_FOLDED_X : BUTTONS_OPEN_X,
    y: FIRST_ROW_CENTRE - BUTTON_HEIGHT / 2,
  }
}

// What the main window is built with, beside its other options. Empty where
// the system's bar stays as it is (every system but the Mac, for now).
// `folded` is the state the sidebar had when the program last ran.
function topBarOptions(platform, folded = false) {
  if (platform !== 'darwin') return {}
  return { titleBarStyle: 'hidden', trafficLightPosition: buttonsAt(Boolean(folded)) }
}

// The arguments the page's bridge reads, for the same platform.
function topBarArguments(platform) {
  return platform === 'darwin' ? [TOP_BAR_ARGUMENT] : []
}

module.exports = {
  FIRST_ROW_CENTRE, BUTTON_HEIGHT, TOP_BAR_ARGUMENT, buttonsAt, topBarOptions, topBarArguments,
}
