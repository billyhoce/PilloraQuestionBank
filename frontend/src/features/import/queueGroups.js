// The review queue reviews a question booklet and its answer booklet as one: jobs whose papers are
// linked across jobs share one card, and answer papers with a suggested partner are offered as
// "Looks like a pair".

// The jobs as cards: [{ id, jobs, created_at, pair }], oldest first. Jobs joined by a link (a
// paper's `partner` in another job of the list) share a card, its jobs oldest first. `pair` names
// the card's linked question paper, { jobId, key }, where Review opens; null for a lone job.
export function groupJobs(jobs) {
  const ids = new Set(jobs.map(j => j.id))
  const parent = new Map(jobs.map(j => [j.id, j.id]))
  const find = id => {
    while (parent.get(id) !== id) id = parent.get(id)
    return id
  }
  for (const job of jobs) {
    for (const p of job.papers ?? []) {
      const other = p.partner?.job_id
      if (p.status === 'pending' && other && other !== job.id && ids.has(other)) parent.set(find(job.id), find(other))
    }
  }
  const byRoot = new Map()
  for (const job of jobs) {
    const root = find(job.id)
    byRoot.set(root, [...(byRoot.get(root) ?? []), job])
  }
  const time = j => new Date(j.created_at).getTime()
  return [...byRoot.values()]
    .map(members => {
      const sorted = [...members].sort((a, b) => time(a) - time(b))
      return { id: sorted.map(j => j.id).join('+'), jobs: sorted, created_at: sorted[0].created_at, pair: pairOf(sorted) }
    })
    .sort((a, b) => new Date(a.created_at) - new Date(b.created_at))
}

function pairOf(jobs) {
  if (jobs.length < 2) return null
  for (const job of jobs) {
    const q = (job.papers ?? []).find(p => p.role !== 'answer_only' && p.status === 'pending' && p.partner)
    if (q) return { jobId: job.id, key: q.key }
  }
  return null
}

// What each job is in a card: 'Questions' when it holds the card's question papers, 'Answers'
// when all its papers are answer-only, else nothing.
export function jobRole(job) {
  const papers = job.papers ?? []
  if (papers.length && papers.every(p => p.role === 'answer_only')) return 'Answers'
  if (papers.some(p => p.role !== 'answer_only')) return 'Questions'
  return null
}

// "Looks like a pair" offers, one per suggested answer paper: [{ id, answers: { jobId, key,
// filename }, questions: { jobId, key, filename }, note }].
export function suggestedPairs(jobs) {
  const out = []
  for (const job of jobs) {
    for (const p of job.papers ?? []) {
      if (p.role !== 'answer_only' || p.status !== 'pending' || p.linked || !p.suggestion) continue
      out.push({
        id: `${job.id}:${p.key}`,
        answers: { jobId: job.id, key: p.key, filename: job.filename },
        questions: { jobId: p.suggestion.job_id, key: p.suggestion.paper_key, filename: p.suggestion.filename, ingestPaperId: p.suggestion.ingest_paper_id },
        note: p.match_note ?? '',
      })
    }
  }
  return out
}
