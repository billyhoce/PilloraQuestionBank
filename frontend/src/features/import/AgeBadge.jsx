import { STALE_AFTER_DAYS, waitingDays, waitingLabel } from './jobAge'
import { SETTLED } from './jobStatus'

// How long an unsettled job has waited, highlighted once it passes STALE_AFTER_DAYS.
export default function AgeBadge({ job }) {
  if (SETTLED.includes(job.status)) return null
  const days = waitingDays(job.created_at)
  if (days === null) return null
  const stale = days > STALE_AFTER_DAYS
  return (
    <span
      data-testid="age-badge"
      data-stale={stale ? 'true' : 'false'}
      className={`ml-2 inline-block rounded px-1.5 py-0.5 text-xs ${
        stale ? 'bg-amber-100 text-amber-800 font-medium' : 'bg-gray-100 text-gray-600'
      }`}
    >
      {waitingLabel(days)}
    </span>
  )
}
