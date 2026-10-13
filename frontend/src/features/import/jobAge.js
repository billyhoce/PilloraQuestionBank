// Jobs waiting on the admin: a proposal to review, or a failure to retry or cancel.
export const AWAITING_STATUSES = ['review_ready', 'failed']
export const AWAITING_QUERY = AWAITING_STATUSES.join(',')
// Past this many days an unsettled job is highlighted.
export const STALE_AFTER_DAYS = 14
const DAY_MS = 24 * 60 * 60 * 1000

// Whole days a job has waited since it was created (null if the date is unreadable).
export function waitingDays(iso, now = Date.now()) {
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return null
  return Math.max(0, Math.floor((now - t) / DAY_MS))
}

export function waitingLabel(days) {
  if (days === 0) return 'waiting today'
  return `waiting ${days} day${days === 1 ? '' : 's'}`
}

