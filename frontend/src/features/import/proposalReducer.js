// Pure edits of one proposal paper ({questions, orphan_answers, pages, ...}), in PDF points.
// Every function returns a new paper and never mutates its input; a refused edit returns the
// paper unchanged (identical reference) so callers can tell nothing happened.
//
// A rectangle is addressed by a selection {list, q, i}: list is 'question' | 'answer' (the
// q-th question's question_rects / answer_rects) or 'orphan' (paper.orphan_answers, q unused),
// i the index within that list.
//
// Rules (documented in docs/features/auto-import.md):
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

// Move a rectangle so its top-left corner is at (x0, y0) points, keeping its size and keeping it
// on its page (it stops at the edges).
export function moveRect(paper, sel, x0, y0) {
  const rect = getRect(paper, sel)
  const page = rect && pageOf(paper, rect.page)
  if (!page) return paper
  const w = rect.x1 - rect.x0
  const h = rect.y1 - rect.y0
  const nx = Math.min(Math.max(0, x0), page.width_pt - w)
  const ny = Math.min(Math.max(0, y0), page.height_pt - h)
  if (nx === rect.x0 && ny === rect.y0) return paper
  const next = { ...rect, x0: nx, y0: ny, x1: nx + w, y1: ny + h }
  return withRects(paper, sel, rectsOf(paper, sel).map((r, k) => (k === sel.i ? next : r)))
}

// A rectangle drawn by the admin, normalised (corners in either order) and clamped to its page;
// null when it is off the paper's pages or smaller than MIN_SIZE_PT either way.
export function normaliseRect(paper, { page, x0, y0, x1, y1 }) {
  const p = pageOf(paper, page)
  if (!p) return null
  const clampX = v => Math.min(p.width_pt, Math.max(0, v))
  const clampY = v => Math.min(p.height_pt, Math.max(0, v))
  const r = {
    page,
    x0: clampX(Math.min(x0, x1)), x1: clampX(Math.max(x0, x1)),
    y0: clampY(Math.min(y0, y1)), y1: clampY(Math.max(y0, y1)),
  }
  return r.x1 - r.x0 >= MIN_SIZE_PT && r.y1 - r.y0 >= MIN_SIZE_PT ? r : null
}

// Add a drawn rectangle. `kind` is 'question' or 'answer'; `q` the question it goes to, or null:
// - a question box with no question becomes a new question (numbered max + 1); in an
//   answer-only paper an answer box with no question does too (its answers are its questions);
// - an answer box with no question becomes an orphan answer.
// Returns { paper, sel } with the new rectangle selected ({ paper } unchanged if refused).
export function addRect(paper, kind, q, drawn) {
  const rect = normaliseRect(paper, drawn)
  if (!rect) return { paper, sel: null }
  if (q != null && paper.questions[q]) {
    const list = kind === 'answer' ? 'answer' : 'question'
    const sel = { list, q, i: rectsOf(paper, { list, q }).length }
    return { paper: withRects(paper, sel, [...rectsOf(paper, sel), rect]), sel }
  }
  const answerOnly = paper.role === 'answer_only'
  if (kind === 'answer' && !answerOnly) {
    return {
      paper: { ...paper, orphan_answers: [...paper.orphan_answers, rect] },
      sel: { list: 'orphan', q: null, i: paper.orphan_answers.length },
    }
  }
  const question = {
    number: nextNumber(paper),
    question_rects: kind === 'answer' ? [] : [rect],
    answer_rects: kind === 'answer' ? [rect] : [],
    flags: [],
  }
  return {
    paper: { ...paper, questions: [...paper.questions, question] },
    sel: { list: kind === 'answer' ? 'answer' : 'question', q: paper.questions.length, i: 0 },
  }
}

// Give an answer rectangle (a question's, or an orphan) to question `toQ`, or make it an orphan
// with toQ = null. Question rectangles are not moved this way. Returns { paper, sel }.
export function assignAnswer(paper, sel, toQ) {
  if (!sel || (sel.list !== 'answer' && sel.list !== 'orphan')) return { paper, sel }
  const rect = getRect(paper, sel)
  if (!rect) return { paper, sel }
  if (toQ == null && sel.list === 'orphan') return { paper, sel }
  if (toQ != null && (!paper.questions[toQ] || (sel.list === 'answer' && sel.q === toQ))) return { paper, sel }
  const without = withRects(paper, sel, rectsOf(paper, sel).filter((_, k) => k !== sel.i))
  if (toQ == null) {
    return {
      paper: { ...without, orphan_answers: [...without.orphan_answers, rect] },
      sel: { list: 'orphan', q: null, i: without.orphan_answers.length },
    }
  }
  const target = { list: 'answer', q: toQ }
  const i = rectsOf(without, target).length
  return { paper: withRects(without, target, [...rectsOf(without, target), rect]), sel: { ...target, i } }
}
