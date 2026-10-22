/*
  The ISO 8601 week number of a day given as 'YYYY-MM-DD': weeks begin on
  Monday, and week 1 is the one that holds the year's first Thursday — so
  1 January can still belong to week 52 or 53 of the year before, and 31
  December to week 1 of the next. Plain, with nothing reactive in it, so the
  calendar's state and a test can both run it on its own.
*/
export function isoWeek(day) {
  const [year, month, date] = day.split('-').map(Number)
  const thursday = new Date(Date.UTC(year, month - 1, date))
  // Move to the Thursday of the same week: it names the year the week is in.
  thursday.setUTCDate(thursday.getUTCDate() + 4 - (thursday.getUTCDay() || 7))
  const january = Date.UTC(thursday.getUTCFullYear(), 0, 1)
  return Math.ceil(((thursday - january) / 86400000 + 1) / 7)
}
