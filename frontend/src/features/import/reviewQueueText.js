// Words for the review queue's paper lines.

// The paper's identity in words — "Raffles · 2024 · Sec 4 · E Maths · Prelim · P1" — from the
// ids on its ingest_paper row (or its new school's name); `missing` lists what is not known yet.
export function describeMetadata(p, refs) {
  const name = (list, id) => (id == null ? null : refs?.[list]?.find(o => o.id === id)?.name ?? `#${id}`)
  const fields = [
    // A school typed during review is only created on confirm (#87).
    ['school', name('schools', p.school_id) ?? (p.new_school_name ? `${p.new_school_name} (new)` : null)],
    ['year', p.year != null ? String(p.year) : null],
    ['level', name('levels', p.level_id)],
    ['subject', name('subjects', p.subject_id)],
    ['exam type', name('examTypes', p.exam_type_id)],
    ['paper no.', p.paper_number ? `P${p.paper_number}` : null],
  ]
  return {
    text: fields.map(([, v]) => v).filter(Boolean).join(' · '),
    missing: fields.filter(([, v]) => !v).map(([k]) => k),
  }
}

// Where an answer-only paper stands in being paired with its questions (and a question paper,
// whether answers from another job are lined up for it).
export function matchState(p) {
  if (p.role === 'answer_only') {
    if (p.linked) return { text: 'Linked to a question paper', tone: 'green' }
    if (p.match_status === 'proposed') return { text: 'Matching paper found', tone: 'green' }
    if (p.match_status === 'manual') return { text: 'Needs matching — several candidates', tone: 'amber' }
    return { text: 'Not matched to a question paper', tone: 'amber' }
  }
  return p.linked ? { text: 'Answers linked from another upload', tone: 'green' } : null
}

// Whether a queue line gets a Match button: the summary's version of pairing.js's needsPartner. A
// pending, unlinked paper with questions that is answer-only, or a question paper whose own
// booklet had no answers at all. A paper has questions when it has coverage or unanswered numbers.
export function needsPartner(p) {
  if (p.status !== 'pending' || p.linked) return false
  if (p.answer_coverage === 'none' && !p.unanswered?.length) return false
  return p.role === 'answer_only' || p.answer_coverage === 'none'
}
