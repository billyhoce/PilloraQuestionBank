// Pure edits of one proposal paper ({questions, orphan_answers, pages, ...}), in PDF points.
// Every function returns a new paper and never mutates its input; a refused edit returns the
// paper unchanged (identical reference) so callers can tell nothing happened.
//
// A rectangle is addressed by a selection {list, q, i}: list is 'question' | 'answer' (the
// q-th question's question_rects / answer_rects) or 'orphan' (paper.orphan_answers, q unused),
// i the index within that list.
//
// Rules (documented in docs/features/auto-import.md):
// - order: every edit returns the paper normalised (see normalise): questions by number, each
//   list of rectangles in source-document order. A selection is an index, so after an edit the
//   caller finds its rectangle again with followSelection / selectionOf. Moving and resizing are
//   the exception: they keep the rectangle's index so a drag can go on, and the caller
//   normalises when the drag ends.
// - delete: removing a question's last question rectangle deletes the question; its answer
//   rectangles are kept as orphan answers.
// - merge with previous: the question with the next-lower number keeps its number; question
//   rects, answer rects and flags are joined.
// - split: the first part keeps the number and all answer rects; the second part gets
//   max(number) + 1 and no answers.
// - draw: a box is drawn for a question number chosen first (see drawError).

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

// Source-document order: by page, then top edge, then left edge.
const byPosition = (a, b) => a.page - b.page || a.y0 - b.y0 || a.x0 - b.x0

// `list` sorted (stably), or `list` itself when it already is.
function sortedOrSame(list, compare) {
  const sorted = [...list].sort(compare)
  return sorted.every((x, k) => x === list[k]) ? list : sorted
}

// The paper in canonical order: questions by number (stable), and each question's
// question_rects and answer_rects, and the orphan answers, by (page, y0, x0). Rectangle objects
// are kept, not copied, so a caller can find one again (selectionOf). The paper itself is
// returned when nothing moves.
export function normalise(paper) {
  let moved = false
  const questions = paper.questions.map(q => {
    const question_rects = sortedOrSame(q.question_rects, byPosition)
    const answer_rects = sortedOrSame(q.answer_rects, byPosition)
    if (question_rects === q.question_rects && answer_rects === q.answer_rects) return q
    moved = true
    return { ...q, question_rects, answer_rects }
  })
  const ordered = sortedOrSame(questions, (a, b) => a.number - b.number)
  const orphans = paper.orphan_answers ?? []
  const orphan_answers = sortedOrSame(orphans, byPosition)
  if (!moved && ordered === questions && orphan_answers === orphans) return paper
  return { ...paper, questions: ordered, orphan_answers }
}

// Where rectangle object `rect` sits in `paper`, as a selection; null when it is not there.
export function selectionOf(paper, rect) {
  if (!rect) return null
  for (let q = 0; q < paper.questions.length; q++) {
    const { question_rects, answer_rects } = paper.questions[q]
    if (question_rects.includes(rect)) return { list: 'question', q, i: question_rects.indexOf(rect) }
    if (answer_rects.includes(rect)) return { list: 'answer', q, i: answer_rects.indexOf(rect) }
  }
  const i = (paper.orphan_answers ?? []).indexOf(rect)
  return i >= 0 ? { list: 'orphan', q: null, i } : null
}

// The selection `sel` (of `before`) after an edit produced `after`: its rectangle wherever the
// re-sort put it, or, when the edit replaced that rectangle (moved, resized), the one rectangle
// `after` has that `before` did not. Null when it cannot be told.
export function followSelection(before, after, sel) {
  const rect = getRect(before, sel)
  if (!rect) return null
  const same = selectionOf(after, rect)
  if (same) return same
  const old = new Set(allRects(before))
  const fresh = allRects(after).filter(r => !old.has(r))
  return fresh.length === 1 ? selectionOf(after, fresh[0]) : null
}

function allRects(paper) {
  return [
    ...paper.questions.flatMap(q => [...q.question_rects, ...q.answer_rects]),
    ...(paper.orphan_answers ?? []),
  ]
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
    return normalise({
      ...paper,
      questions: paper.questions.filter((_, k) => k !== sel.q),
      orphan_answers: [...paper.orphan_answers, ...q.answer_rects],
    })
  }
  return normalise(withRects(paper, sel, rest))
}

// A number must be a positive whole number not used by another question of the paper.
export function renumberError(paper, q, number) {
  if (!Number.isInteger(number) || number < 1) return 'A question number must be a positive whole number'
  if (paper.questions.some((o, k) => k !== q && o.number === number)) return `Question ${number} already exists`
  return null
}

export function renumber(paper, q, number) {
  if (!paper.questions[q] || renumberError(paper, q, number) || paper.questions[q].number === number) return paper
  return normalise({ ...paper, questions: paper.questions.map((o, k) => (k === q ? { ...o, number } : o)) })
}

// Question q joins question q - 1: in a normalised paper, the one with the next-lower number.
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
  return normalise({
    ...paper,
    questions: [...paper.questions.slice(0, q - 1), merged, ...paper.questions.slice(q + 1)],
  })
}

function splitInto(paper, q, firstRects, secondRects) {
  const cur = paper.questions[q]
  const first = { ...cur, question_rects: firstRects }
  const second = { number: nextNumber(paper), question_rects: secondRects, answer_rects: [], flags: [...cur.flags] }
  return normalise({ ...paper, questions: [...paper.questions.slice(0, q), first, second, ...paper.questions.slice(q + 1)] })
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

// Why a box of `kind` ('question' or 'answer') cannot be drawn for question `number` (null or
// NaN when the field is blank), or null when it can. Checked before drawing starts:
// - a question box may name any positive number: an existing question gets the box, a new
//   number starts a question;
// - an answer box must name an existing question, except in an answer-only paper, where a new
//   number starts a new answer (its answers are its questions).
export function drawError(paper, kind, number) {
  if (number == null || Number.isNaN(number)) return 'Enter a question number'
  if (!Number.isInteger(number) || number < 1) return 'A question number must be a positive whole number'
  if (kind === 'answer' && paper.role !== 'answer_only' && !paper.questions.some(q => q.number === number)) {
    return `Question ${number} doesn't exist. Draw its question box first.`
  }
  return null
}

// Add a drawn rectangle of `kind` to question `number` (see drawError): to that question at its
// place in document order, or as a new question in number order. Returns { paper, sel, error }
// with the new rectangle selected; a refused draw returns the paper unchanged, with the reason
// in `error` (null for a box too small or off the paper's pages).
export function addRect(paper, kind, number, drawn) {
  const error = drawError(paper, kind, number)
  if (error) return { paper, sel: null, error }
  const rect = normaliseRect(paper, drawn)
  if (!rect) return { paper, sel: null, error: null }
  const key = kind === 'answer' ? 'answer_rects' : 'question_rects'
  const at = paper.questions.findIndex(q => q.number === number)
  const questions = at >= 0
    ? paper.questions.map((q, k) => (k === at ? { ...q, [key]: [...q[key], rect] } : q))
    : [...paper.questions, {
        number,
        question_rects: kind === 'answer' ? [] : [rect],
        answer_rects: kind === 'answer' ? [rect] : [],
        flags: [],
      }]
  const next = normalise({ ...paper, questions })
  return { paper: next, sel: selectionOf(next, rect), error: null }
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
  const target = { list: 'answer', q: toQ }
  const next = normalise(toQ == null
    ? { ...without, orphan_answers: [...without.orphan_answers, rect] }
    : withRects(without, target, [...rectsOf(without, target), rect]))
  return { paper: next, sel: selectionOf(next, rect) }
}
