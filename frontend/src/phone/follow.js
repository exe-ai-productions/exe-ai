/*
  Following the floor of the chat on the phone.

  While an answer is written the chat runs with it. Whoever scrolls up
  leaves it, and takes hold again only on standing at most `FOLLOW_PX` above
  the end — farther up the chat stays where the finger put it, also while an
  answer runs. A round button over the bar brings the reader back to the end,
  and the chat runs with the answer again.

  Pure: the scroll box is given in, nothing here touches the page.
*/

/** How near the end counts as the end. */
export const FOLLOW_PX = 70

/** How far the bottom edge of the box is above the end of its content. */
export function distanceToFloor(box) {
  return box.scrollHeight - box.scrollTop - box.clientHeight
}

/**
 * What one scroll event says about following. `before` is where the box
 * stood at the event before, `following` whether it followed then.
 * Moving up ends the following (the finger asked for it); the end comes back
 * only by standing within `FOLLOW_PX` of it.
 */
export function followAfterScroll(before, box, following) {
  // The rubber band past the end springs back by itself: not a finger going up.
  const beyondEnd = before > box.scrollHeight - box.clientHeight + 0.5
  if (!beyondEnd && box.scrollTop < before - 1) return false
  if (distanceToFloor(box) <= FOLLOW_PX) return true
  return following
}
