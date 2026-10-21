// Pairing a paper that needs a partner (the review page's Pairing block and the "Match this
// paper" popup): which papers need one, what the block shows, and the popup's search in words.
import { coverageOf } from './answerCoverage'

// A pending paper needs a partner when it is answer-only, or a question paper whose own booklet
// had no answers at all (a partly answered one is warned about instead). A paper with no questions
// can only be skipped.
export function needsPartner(paper) {
  if (!paper?.questions?.length) return false
  return paper.role === 'answer_only' || coverageOf(paper) === 'none'
}

// 'linked' (to a pending paper), 'proposed' (an answer-only paper's automatic bank paper) or 'none'.
export function pairingState({ link, proposal } = {}) {
  if (link) return 'linked'
  if (proposal?.status === 'proposed' && proposal.paper) return 'proposed'
  return 'none'
}

export const FIELDS = ['subject_id', 'stream_id', 'level_id', 'school_id', 'exam_type_id', 'year', 'paper_number']

const LABEL = {
  subject_id: 'subject', stream_id: 'stream', level_id: 'level', school_id: 'school',
  exam_type_id: 'exam type', year: 'year', paper_number: 'paper no.',
}
const LIST = { subject_id: 'subjects', stream_id: 'streams', level_id: 'levels', school_id: 'schools', exam_type_id: 'examTypes' }

const blank = v => v == null || String(v).trim() === ''

// The popup's fields as the candidates search takes them: blank fields are left out ("any"), and
// a school typed as new is searched by its name.
export function candidateQuery(fields) {
  const out = {}
  for (const f of FIELDS) {
    if (f === 'school_id' && blank(fields.school_id)) {
      if (!blank(fields.new_school_name)) out.new_school_name = fields.new_school_name.trim()
    } else if (!blank(fields[f])) {
      out[f] = f === 'year' ? Number(fields[f]) : f === 'paper_number' ? String(fields[f]).trim() : fields[f]
    }
  }
  return out
}

// The paper's fields as PUT .../metadata and the match route's `metadata` take them.
export function metadataBody(m) {
  return {
    subject_id: m.subject_id ?? null, stream_id: m.stream_id ?? null, level_id: m.level_id ?? null,
    school_id: m.school_id ?? null, exam_type_id: m.exam_type_id ?? null,
    ...(m.new_school_name && !m.school_id && { new_school_name: m.new_school_name }),
    year: blank(m.year) ? null : Number(m.year),
    paper_number: blank(m.paper_number) ? null : m.paper_number,
  }
}

function valueText(field, details, refs) {
  if (field === 'school_id' && details.school_id == null && details.new_school_name) return `${details.new_school_name} (new)`
  const v = details[field]
  if (blank(v)) return '—'
  if (LIST[field]) return refs?.[LIST[field]]?.find(o => o.id === v)?.name ?? `#${v}`
  return String(v).trim()
}

// "paper no. 2A ≠ 2" for each field the booklet differs on: its value, then the searched one.
export function differences(candidate, fields, refs) {
  return (candidate.differ ?? []).map(
    f => `${LABEL[f]} ${valueText(f, candidate.details, refs)} ≠ ${valueText(f, fields, refs)}`,
  )
}

const IN_WORDS = ['school_id', 'year', 'level_id', 'subject_id', 'exam_type_id', 'stream_id', 'paper_number']

// A booklet's details in words: "RI 2024 Sec 3 Math EOY G3 Paper 1" (unknown fields left out).
export function detailsText(details, refs) {
  return IN_WORDS
    .filter(f => !blank(details[f]) || (f === 'school_id' && details.new_school_name))
    .map(f => (f === 'paper_number' ? `Paper ${valueText(f, details, refs)}` : valueText(f, details, refs)))
    .join(' ')
}

export function locationText(c) {
  if (c.kind === 'bank') return `In the bank (paper ${c.paper_id})`
  return c.same_job ? `Same file (${c.paper_key})` : `Pending in ${c.filename} (${c.paper_key})`
}

// Answers are all or none: what a bank paper already has, or null.
export function coverageNote(c) {
  if (c.kind !== 'bank') return null
  if (c.answer_coverage === 'all') return 'Already has answers'
  if (c.answer_coverage === 'partial') {
    return `Only ${c.answer_numbers.length} of ${c.question_numbers.length} questions have answers`
  }
  return null
}

// The first rectangle of `rects` ('question_rects' or 'answer_rects') of a review paper that has
// a page image, as { number, url, page, rect }; null when there is none.
export function firstRect(paper, rects) {
  for (const q of paper?.questions ?? []) {
    for (const rect of q[rects] ?? []) {
      const page = paper.pages.find(p => p.page === rect.page)
      if (page?.url) return { number: q.number, url: page.url, page, rect }
    }
  }
  return null
}
