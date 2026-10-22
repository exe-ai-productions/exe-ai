/* Where a long file name may break: after a slash, a hyphen, an underscore
   or a dot. Without them a name breaks at the letter where the line runs
   out ("absatz6.t" over "xt"); with them it breaks between its parts, and
   only a part wider than the line breaks inside itself. The name is cut
   into its parts here and the parts are drawn with a break mark between
   them; the name itself is never changed. */
export function breakPoints(name) {
  return String(name ?? '').split(/(?<=[/\-_.])/)
}
