/*
  What the small picture of each look on the appearance page is drawn with.

  A picture is a window in miniature: the frame, the column of lines at its
  left, the tile of the chat with a message, two lines of an answer and the
  input field. Each look names the frame's ground, the ink of its lines (as
  red, green, blue, the lines are that ink at a fraction), the tile and the
  input. The own gradient draws its ground from what the user set, or from
  its start.
*/

export const VORSCHAU = {
  pearl: {
    grund: '#e0d7c3',
    tinte: '32, 28, 20',
    kachel: 'rgba(255, 255, 255, 0.3)',
    eingabe: 'rgba(255, 255, 255, 0.6)',
  },
  snow: {
    grund: '#eaeaea',
    tinte: '28, 28, 28',
    kachel: 'rgba(255, 255, 255, 0.3)',
    eingabe: 'rgba(255, 255, 255, 0.6)',
  },
  dunkel: {
    grund: '#353634',
    tinte: '236, 235, 230',
    kachel: 'rgba(28, 28, 26, 0.58)',
    eingabe: 'rgba(236, 235, 230, 0.07)',
  },
  darkmatter: {
    grund: '#1a0b3a',
    tinte: '233, 230, 247',
    kachel: 'rgba(11, 8, 23, 0.58)',
    eingabe: 'rgba(236, 235, 230, 0.07)',
  },
  heaven: {
    grund:
      'linear-gradient(172deg, rgb(159, 196, 255) 11%, rgb(196, 181, 255) 50%, rgb(255, 201, 228) 89%)',
    tinte: '34, 48, 74',
    kachel: 'rgba(232, 238, 248, 0.55)',
    eingabe: 'rgba(255, 255, 255, 0.6)',
  },
  moune: {
    grund:
      'linear-gradient(170deg, rgb(215, 226, 203) 12%, rgb(189, 213, 186) 52%, rgb(189, 215, 200) 88%)',
    tinte: '31, 45, 34',
    kachel: 'rgba(243, 251, 233, 0.72)',
    eingabe: 'rgba(250, 254, 244, 0.94)',
  },
  /* The own gradient: the ground is the user's, the rest is Exe's with the
     denser glass of the dark own gradient. The light own gradient wears
     Pearl's. */
  eigen_dunkel: {
    tinte: '236, 235, 230',
    kachel: 'rgba(28, 28, 26, 0.72)',
    eingabe: 'rgba(236, 235, 230, 0.07)',
  },
  eigen_hell: {
    tinte: '32, 28, 20',
    kachel: 'rgba(255, 255, 255, 0.55)',
    eingabe: 'rgba(255, 255, 255, 0.6)',
  },
}

/* Which picture a choice of the appearance shows. */
export const VORSCHAU_ZU_LOOK = {
  hell: 'pearl',
  dunkel: 'dunkel',
  darkmatter: 'darkmatter',
  heaven: 'heaven',
  moune: 'moune',
  snow: 'snow',
}

/* The start of the own gradient: the colours, where each stands in percent,
   the hue they are turned by and the angle. The same numbers the look's
   sheet carries (stil/global.css, `:root[data-modus='eigen']`); a test holds
   the two together. */
export const EIGEN_START = {
  farben: ['#3b1280', '#7a1f8f', '#1a0b3a', '#07050f'],
  stufen: [0, 45, 80, 100],
  ton: -85,
  winkel: 0,
}

/* A colour's apparent brightness: the rule the frame's own ink follows. */
function helligkeit(farbe) {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(farbe.slice(i, i + 2), 16) / 255)
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

/** The picture of the own gradient from the user's choice (`wahl`, any of
 *  `farben`, `ton`, `winkel`) and the function that turns a colour's hue.
 *  Answers the ground and which set of ink it wears (`hell` over 0.45). */
export function eigenVorschau(wahl, farbtonDrehen) {
  const ton = wahl?.ton ?? EIGEN_START.ton
  const farben = (wahl?.farben || EIGEN_START.farben).map((farbe) => farbtonDrehen(farbe, ton))
  const winkel = wahl?.winkel ?? EIGEN_START.winkel
  const stufen = farben.map((farbe, i) => `${farbe} ${EIGEN_START.stufen[i] ?? 100}%`)
  const hell = farben.reduce((summe, farbe) => summe + helligkeit(farbe), 0) / farben.length > 0.45
  return { grund: `linear-gradient(${winkel}deg, ${stufen.join(', ')})`, hell }
}
