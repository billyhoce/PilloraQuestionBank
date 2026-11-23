// Formatting for a job's Claude cost (GET /api/import/jobs/{id} `cost`, the list's `cost_usd`
// and `spend`). Shared by the job detail breakdown, the job rows and the Job History header.

// A dollar amount. `precise` keeps four decimals (a single call is often a fraction of a cent);
// otherwise cents, with anything under a cent shown as "<$0.01".
export function formatUsd(usd, { precise = false } = {}) {
  if (usd == null) return '—'
  if (precise) return `$${usd.toFixed(4)}`
  if (usd > 0 && usd < 0.005) return '<$0.01'
  return `$${usd.toFixed(2)}`
}

export const formatTokens = n => (n ?? 0).toLocaleString('en-US')

// Input tokens with the cache reads beside them: "48,210 (+1,024)".
export function formatInput(input, cacheHit) {
  return cacheHit ? `${formatTokens(input)} (+${formatTokens(cacheHit)})` : formatTokens(input)
}

// What a call was for, in words.
export function callLabel(item) {
  switch (item.kind) {
    case 'segment':
      return 'Find papers in booklet'
    case 'metadata':
      return `Paper ${item.paper_key ?? '?'} metadata${item.source ? ` (from ${item.source})` : ''}`
    case 'legacy':
      return 'Before per-call tracking'
    default:
      return item.kind
  }
}

// The model family ("Haiku", "Opus") for a known model id, else the id itself.
export function modelName(model) {
  if (!model) return '—'
  const family = ['opus', 'sonnet', 'haiku'].find(f => model.includes(f))
  return family ? family[0].toUpperCase() + family.slice(1) : model
}

// "retry 1" for a call made after the job was retried once; "attempt 2" for a task's second try
// within one run (its lease expired); both when both apply; "" for a first-run first try.
export function runTag(item) {
  const tags = []
  if (item.run > 0) tags.push(`retry ${item.run}`)
  if (item.attempt > 1) tags.push(`attempt ${item.attempt}`)
  return tags.join(', ')
}

// "2026-11" -> "Nov 2026".
export function monthLabel(month) {
  const [y, m] = month.split('-').map(Number)
  return new Date(Date.UTC(y, m - 1, 1)).toLocaleString('en-US', { month: 'short', year: 'numeric', timeZone: 'UTC' })
}
