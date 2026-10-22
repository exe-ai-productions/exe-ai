/*
  The menu of one picture on the phone page, opened by a long press on a
  picture — in the studio's row of pictures and in the reader. The reader is
  the program's one place that shows every picture, and the sheet that lists
  what can be done with one is the phone page's; this is the word between
  them: which picture, and whether the reader stands behind it.
*/
export const pictureMenu = $state({ name: '', fromReader: false })

export function openPictureMenu(name, fromReader = false) {
  pictureMenu.name = name
  pictureMenu.fromReader = fromReader
}

export function closePictureMenu() {
  pictureMenu.name = ''
  pictureMenu.fromReader = false
}
