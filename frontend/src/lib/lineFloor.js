/*
  The floor under the line of a running answer.

  While an answer runs, its line may be rebuilt in ways that make it shorter:
  the thinking head and its line fold into the one row of a tool bundle when
  the second call comes (lib/werkzeugbuendel.js), and the next thinking opens
  again below it. Each of those would pull everything under the answer up and
  push it down again. The line keeps the greatest height it has had for as
  long as the answer runs, and grows only with what is shown; with the end of
  the run the floor is gone and the answer stands as it is.

  `running` is whether the answer runs, `height` the height the line has now,
  `floor` the floor it kept until now. Gives the floor the line keeps next.
*/
export function lineFloor(running, height, floor) {
  if (!running) return 0
  return height > floor ? height : floor
}
