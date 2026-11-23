// Job statuses as the import pages present and act on them (mirrors the server's rules).

export const STATUS_LABELS = {
  awaiting_upload: 'Uploading',
  queued: 'Queued',
  running: 'Running',
  review_ready: 'Ready for review',
  failed: 'Failed',
  confirmed: 'Confirmed',
  cancelled: 'Cancelled',
  expired: 'Expired',
}

// Queued jobs count as active: with a live worker they flip to running soon.
export const ACTIVE = ['queued', 'running']
// Statuses a job can still be cancelled from.
export const CANCELLABLE = ['awaiting_upload', 'queued', 'running', 'review_ready', 'failed']
// Jobs retry applies to (the server refuses cancelled/confirmed/expired).
export const RETRYABLE = ['queued', 'running', 'review_ready', 'failed']

// Whether Retry would do anything: it reopens only failed and blocked tasks, so a job with none
// (most queued, running and review-ready jobs) has nothing to retry and shows no button.
export function canRetry(job) {
  return RETRYABLE.includes(job.status) && (job.tasks_failed ?? 0) > 0
}
// Jobs still in the pipeline, or stopped in it: what the Auto import board shows.
export const IN_PIPELINE = ['awaiting_upload', 'queued', 'running', 'failed']
export const SETTLED = ['confirmed', 'cancelled', 'expired']

export function formatCreated(iso) {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleString()
}
