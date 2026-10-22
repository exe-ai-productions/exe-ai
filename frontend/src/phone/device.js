/*
  The switch between the two faces of the interface.

  A device whose main input is a finger (`pointer: coarse`) shows the phone
  page, whatever its screen measures: a phone, a tablet, upright or turned
  sideways. A window without touch shows the phone page only while it is
  under 600 px wide.

  The rule is a pure function of two facts, so a test can run it without a
  window around it.
*/

/* The window width below which a window without touch shows the phone page. */
export const PHONE_WIDTH = 600

/* The media query that says the main input of the device is a finger. */
const TOUCH_QUERY = '(pointer: coarse)'

/** Whether these two facts call for the phone page. */
export function isPhone(windowWidth, touch) {
  return Boolean(touch) || windowWidth < PHONE_WIDTH
}

/* The facts of the page the code runs in. A browser that cannot answer the
   media query is judged by its window alone. */
export function isPhoneNow(win = globalThis.window) {
  if (!win) return false
  const touch = typeof win.matchMedia === 'function' && win.matchMedia(TOUCH_QUERY).matches
  return isPhone(win.innerWidth, touch)
}

/* Calls `onChange(phone)` whenever the answer changes — a window dragged
   across 600 px, a tablet whose main input changes (a trackpad attached).
   Returns the function that stops it. */
export function watchDevice(onChange, win = globalThis.window) {
  let standing = isPhoneNow(win)
  const check = () => {
    const now = isPhoneNow(win)
    if (now === standing) return
    standing = now
    onChange(now)
  }
  const touch = typeof win.matchMedia === 'function' ? win.matchMedia(TOUCH_QUERY) : null
  win.addEventListener('resize', check)
  win.addEventListener('orientationchange', check)
  touch?.addEventListener?.('change', check)
  return () => {
    win.removeEventListener('resize', check)
    win.removeEventListener('orientationchange', check)
    touch?.removeEventListener?.('change', check)
  }
}
