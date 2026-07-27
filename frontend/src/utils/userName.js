// "First Last", or '' when neither is on file. Accounts predating the name
// fields — and Google accounts that report no given/family name — store empty
// strings.
export const fullName = (user) =>
  [user?.first_name, user?.last_name].filter(Boolean).join(' ').trim()

// Same, but falls back to the email address so there is always something to
// label the account with. Used where the email isn't already on screen.
export const displayName = (user) => {
  if (!user) return ''
  return fullName(user) || user.email || ''
}
