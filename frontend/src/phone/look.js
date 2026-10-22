/*
  Which of the three looks the phone page wears.

  The phone page is drawn in Exe (the dark grey look), Pearl (the light warm
  one) and Snow (the light neutral one) and in nothing else. The desktop may
  stand on any look; the one it stands on is read here and narrowed: Exe,
  Pearl and Snow are taken as they are, "auto" follows what the device
  reports (Exe on a dark device, Snow on a light one, as on the desktop),
  and every other look is shown as Exe.

  No imports on purpose: the rule is a pure function of two values, so a
  test can run it without a window around it.
*/

/* The attribute value each look hangs its colours on (stil/global.css):
   Exe is `dunkel`, Pearl is `hell`, Snow is `snow`. */
export const LOOK_EXE = 'dunkel'
export const LOOK_PEARL = 'hell'
export const LOOK_SNOW = 'snow'

/** The look the phone page wears for the look the desktop stands on. */
export function phoneLook(mode, deviceDark) {
  if (mode === LOOK_PEARL || mode === LOOK_SNOW) return mode
  if (mode === 'auto') return deviceDark ? LOOK_EXE : LOOK_SNOW
  return LOOK_EXE
}
