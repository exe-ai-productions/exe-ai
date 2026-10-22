/* Whether a switch row has no place at the model drawn with: its condition
   (`needs`, e.g. "high_noise") is one the model's family names but this
   model does not take, so the row is not drawn at all (the rows of a
   condition that merely is not met yet stand greyed out). The studio lists
   such conditions under `absent`. */
export const hasNoPlace = (row, conditions) =>
  Boolean(row.needs) && Array.isArray(conditions?.absent) && conditions.absent.includes(row.needs)
