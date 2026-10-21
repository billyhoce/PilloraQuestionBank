// Answers are all or none: a paper has answers on every question or on none, and anything in
// between is warned about (never blocked). Coverage is 'none', 'partial' or 'all'; the job list
// summary carries the same values (`answer_coverage`, `unanswered`) for a paper's own booklet.

const asNumber = n => {
  const v = Number(String(n).trim())
  return Number.isInteger(v) ? v : null
}

// The numbers of `paper`'s questions with no answer box, counting `linkedAnswers` (the answer
// numbers a linked answer paper brings in on confirm, matched by number) as answered.
export function unansweredNumbers(paper, linkedAnswers = []) {
  const linked = new Set(linkedAnswers.map(asNumber).filter(n => n != null))
  return (paper?.questions ?? [])
    .filter(q => q.answer_rects.length === 0 && !linked.has(asNumber(q.number)))
    .map(q => q.number)
}

export function coverageOf(paper, linkedAnswers = []) {
  const total = paper?.questions?.length ?? 0
  const missing = unansweredNumbers(paper, linkedAnswers).length
  if (missing === total) return 'none'
  return missing === 0 ? 'all' : 'partial'
}

// "Q5–Q7, Q9 have no answers"; null when every question has answers.
export function unansweredWarning(numbers) {
  if (!numbers?.length) return null
  const parts = []
  let run = null
  for (const n of numbers) {
    const v = asNumber(n)
    if (run && v != null && run.last + 1 === v) {
      run.last = v
      continue
    }
    if (run) parts.push(run)
    run = v != null ? { first: v, last: v } : { label: n }
  }
  parts.push(run)
  const text = parts
    .map(r => (r.label != null ? `Q${r.label}` : r.first === r.last ? `Q${r.first}` : `Q${r.first}–Q${r.last}`))
    .join(', ')
  return `${text} ${numbers.length === 1 ? 'has' : 'have'} no answers`
}

// The warning for a paper that would be confirmed partly answered, else null (all answered, or
// none — a paper with no answers needs a partner instead).
export function partlyAnsweredWarning(paper, linkedAnswers = []) {
  if (coverageOf(paper, linkedAnswers) !== 'partial') return null
  return unansweredWarning(unansweredNumbers(paper, linkedAnswers))
}
