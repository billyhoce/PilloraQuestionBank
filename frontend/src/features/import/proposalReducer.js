// Pure edits of one proposal paper ({questions, orphan_answers, pages, ...}), in PDF points.
// Every function returns a new paper and never mutates its input; a refused edit returns the
// paper unchanged (identical reference) so callers can tell nothing happened.
//
// A rectangle is addressed by a selection {list, q, i}: list is 'question' | 'answer' (the
// q-th question's question_rects / answer_rects) or 'orphan' (paper.orphan_answers, q unused),
// i the index within that list.
//
// Rules (documented in docs/features/ingestion.md):
// - delete: removing a question's last question rectangle deletes the question; its answer
//   rectangles are kept as orphan answers.
// - merge with previous: the previous question keeps its number; question rects, answer rects
//   and flags are concatenated.
// - split: the first part keeps the number and all answer rects; the second part gets
//   max(number) + 1 and no answers.

export const MIN_SIZE_PT = 4

const EDGES = ['x0', 'y0', 'x1', 'y1']

function rectsOf(paper, sel) {
  if (sel.list === 'orphan') return paper.orphan_answers
  const q = paper.questions[sel.q]
  return q ? q[sel.list === 'answer' ? 'answer_rects' : 'question_rects'] : undefined
}

function withRects(paper, sel, rects) {
  if (sel.list === 'orphan') return { ...paper, orphan_answers: rects }
  const key = sel.list === 'answer' ? 'answer_rects' : 'question_rects'
  return {
    ...paper,
    questions: paper.questions.map((q, k) => (k === sel.q ? { ...q, [key]: rects } : q)),
  }
}

export function getRect(paper, sel) {
  return sel ? rectsOf(paper, sel)?.[sel.i] : undefined
}

export function pageOf(paper, pageNumber) {
  return paper.pages.find(p => p.page === pageNumber)
}

export function nextNumber(paper) {
  return paper.questions.reduce((m, q) => Math.max(m, q.number), 0) + 1
}

// Set some edges ({x0,y0,x1,y1} subset, in points) of a rectangle, clamped to its page and
// kept at least MIN_SIZE_PT wide/high. An edge that cannot move any further stops there.
export function resizeRect(paper, sel, edges) {
  const rect = getRect(paper, sel)
  const page = rect && pageOf(paper, rect.page)
  if (!page) return paper
  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v))
  const next = { ...rect }
  if (edges.x0 != null) next.x0 = clamp(edges.x0, 0, rect.x1 - MIN_SIZE_PT)
  if (edges.x1 != null) next.x1 = clamp(edges.x1, rect.x0 + MIN_SIZE_PT, page.width_pt)
  if (edges.y0 != null) next.y0 = clamp(edges.y0, 0, rect.y1 - MIN_SIZE_PT)
  if (edges.y1 != null) next.y1 = clamp(edges.y1, rect.y0 + MIN_SIZE_PT, page.height_pt)
  if (EDGES.every(k => next[k] === rect[k])) return paper
  return withRects(paper, sel, rectsOf(paper, sel).map((r, k) => (k === sel.i ? next : r)))
}

export function deleteRect(paper, sel) {
  const rects = rectsOf(paper, sel)
  if (!rects || !rects[sel.i]) return paper
  const rest = rects.filter((_, k) => k !== sel.i)
  if (sel.list === 'question' && rest.length === 0) {
    const q = paper.questions[sel.q]
    return {
      ...paper,
      questions: paper.questions.filter((_, k) => k !== sel.q),
      orphan_answers: [...paper.orphan_answers, ...q.answer_rects],
    }
  }
  return withRects(paper, sel, rest)
}

// A number must be a positive whole number not used by another question of the paper.
export function renumberError(paper, q, number) {
  if (!Number.isInteger(number) || number < 1) return 'A question number must be a positive whole number'
  if (paper.questions.some((o, k) => k !== q && o.number === number)) return `Question ${number} already exists`
  return null
}

export function renumber(paper, q, number) {
  if (!paper.questions[q] || renumberError(paper, q, number) || paper.questions[q].number === number) return paper
  return { ...paper, questions: paper.questions.map((o, k) => (k === q ? { ...o, number } : o)) }
}

export function mergeWithPrevious(paper, q) {
  if (q < 1 || !paper.questions[q]) return paper
  const prev = paper.questions[q - 1]
  const cur = paper.questions[q]
  const merged = {
    ...prev,
    question_rects: [...prev.question_rects, ...cur.question_rects],
    answer_rects: [...prev.answer_rects, ...cur.answer_rects],
    flags: [...prev.flags, ...cur.flags.filter(f => !prev.flags.includes(f))],
  }
  return {
    ...paper,
    questions: [...paper.questions.slice(0, q - 1), merged, ...paper.questions.slice(q + 1)],
  }
}

function splitInto(paper, q, firstRects, secondRects) {
  const cur = paper.questions[q]
  const first = { ...cur, question_rects: firstRects }
  const second = { number: nextNumber(paper), question_rects: secondRects, answer_rects: [], flags: [...cur.flags] }
  return { ...paper, questions: [...paper.questions.slice(0, q), first, second, ...paper.questions.slice(q + 1)] }
}

// Split question q between its rectangles: rectangles [0, at) stay, [at, n) become a new question.
export function splitBetween(paper, q, at) {
  const cur = paper.questions[q]
  if (!cur || !Number.isInteger(at) || at < 1 || at >= cur.question_rects.length) return paper
  return splitInto(paper, q, cur.question_rects.slice(0, at), cur.question_rects.slice(at))
}

// Split question q by a horizontal cut at `y` (points) through its i-th rectangle: the part above
// the cut ends the first question, the part below starts the new one, later rectangles follow it.
export function splitThrough(paper, q, i, y) {
  const cur = paper.questions[q]
  const r = cur?.question_rects[i]
  if (!r || !(y >= r.y0 + MIN_SIZE_PT && y <= r.y1 - MIN_SIZE_PT)) return paper
  return splitInto(
    paper,
    q,
    [...cur.question_rects.slice(0, i), { ...r, y1: y }],
    [{ ...r, y0: y }, ...cur.question_rects.slice(i + 1)],
  )
}

// What the PUT route takes: only the editable part of each paper.
export function toEditPayload(papers) {
  return { papers: papers.map(p => ({ questions: p.questions, orphan_answers: p.orphan_answers })) }
}
