/*
  The sign of the program in the menu bar (macOS) or the notification area
  (Windows).

  It stays when the window is closed: the program then runs on with the sign
  alone, and the service with it. The sign is drawn in full while the service
  answers its port and dimmed while it does not, and its menu has three
  entries — open the window, end the service (the service and its model
  server), end the program (the service runs on, as it does when the window
  closes). The words are English until the page has said them in the
  interface's language (`setWords`), and for every word it left out.

  The images are template images on macOS: black on transparent, named
  `...Template`, so the system draws them in the colour of the bar, light or
  dark. The dimmed one is the same shape with less alpha. Windows has no
  template images; there the mark is a mid grey that shows on a light and on a
  dark bar.

  Everything electron gives is handed in (`Tray`, `Menu`, `nativeImage`), so
  tests run this module in plain node with stand-ins for them, and main.js
  gives it the real ones.
*/

const path = require('path')

// How often the service's port is looked at while the sign stands.
const LOOK_EVERY_MS = 2000

// The words of the three entries and of the sign's tool tip, in English: the
// shell has no catalogue, so the page hands over the interface's own.
const WORDS = Object.freeze({
  tip: 'Exe AI',
  openWindow: 'Open Window',
  endService: 'Stop Service',
  endProgram: 'Quit Exe AI',
})

// What a page sent, reduced to the words above: only the known ones, only
// text, trimmed, none empty. Anything else leaves the English word.
function wordsFrom(sent) {
  const words = { ...WORDS }
  if (!sent || typeof sent !== 'object') return words
  for (const name of Object.keys(WORDS)) {
    const word = typeof sent[name] === 'string' ? sent[name].trim() : ''
    if (word) words[name] = word
  }
  return words
}

// The image file of the sign for a state, on a system.
function imageFile(active, platform) {
  if (platform === 'darwin') return active ? 'menueleisteTemplate.png' : 'menueleisteDimTemplate.png'
  return active ? 'notificationArea.png' : 'notificationAreaDim.png'
}

// The three entries of the menu, in the order they stand in.
function menuTemplate({ words = WORDS, openWindow, endService, endProgram }) {
  return [
    { label: words.openWindow, click: openWindow },
    { label: words.endService, click: endService },
    { label: words.endProgram, click: endProgram },
  ]
}

/**
 * Puts the sign up and keeps it true to the service.
 *
 * `answers()` says whether the service answers its port. `openWindow`,
 * `endService` and `endProgram` are what the three entries do; a failing
 * `endService` is written to `log`, handed to `endFailed` (which tells the
 * user) and does not stand in the way of the next look at the service.
 * Returns `{ look, remove, setWords, tray }`: `look` asks the service now
 * and sets the image, `remove` takes the sign down, `setWords` sets the
 * menu anew in the words a page sent.
 */
function start({
  Tray, Menu, nativeImage, folder, platform, answers, openWindow, endService, endProgram,
  words = WORDS, every = LOOK_EVERY_MS, timers = { setInterval, clearInterval }, log = () => {},
  endFailed = () => {},
}) {
  const imageFor = (active) => nativeImage.createFromPath(path.join(folder, imageFile(active, platform)))
  // The sign is first up dimmed, so that is the state it stands in.
  let active = false
  let gone = false

  // Up at once; the first look below makes it true.
  const tray = new Tray(imageFor(false))
  tray.setToolTip(words.tip)

  // Looks overlap: a probe that began before the service ended can come back
  // after the one that began after it. Only the newest look counts.
  let newest = 0
  async function look() {
    const mine = ++newest
    let now = false
    try {
      now = Boolean(await answers())
    } catch (failure) {
      log(`Menu bar: looking at the service failed: ${failure && failure.message}`)
    }
    if (gone || mine !== newest || now === active) return
    active = now
    tray.setImage(imageFor(now))
  }

  async function endTheService() {
    try {
      await endService()
    } catch (failure) {
      log(`Menu bar: ending the service failed: ${failure && failure.message}`)
      try {
        await endFailed()
      } catch (second) {
        log(`Menu bar: telling about the failure failed: ${second && second.message}`)
      }
    }
    await look()
  }

  // The menu is built anew whenever the words change: a built menu keeps the
  // labels it was built with.
  function setMenu() {
    tray.setContextMenu(
      Menu.buildFromTemplate(menuTemplate({ words, openWindow, endService: endTheService, endProgram })),
    )
  }
  setMenu()

  function setWords(sent) {
    if (gone) return
    const next = wordsFrom(sent)
    // The same words again leave the menu as it is: one that stands open is
    // not replaced under the hand.
    if (JSON.stringify(next) === JSON.stringify(words)) return
    words = next
    setMenu()
  }
  // Windows opens the window with a plain click; macOS shows the menu.
  if (platform !== 'darwin') tray.on('click', openWindow)

  const timer = timers.setInterval(look, every)
  look()

  function remove() {
    gone = true
    timers.clearInterval(timer)
    if (!tray.isDestroyed()) tray.destroy()
  }

  return { look, remove, setWords, tray }
}

module.exports = { WORDS, LOOK_EVERY_MS, imageFile, menuTemplate, wordsFrom, start }
