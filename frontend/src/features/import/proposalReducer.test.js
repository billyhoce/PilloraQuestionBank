import { describe, it, expect } from 'vitest'
import {
  addRect, assignAnswer, deleteRect, drawError, followSelection, mergeWithPrevious, moveRect, normalise, renumber, renumberError,
  resizeRect, splitBetween, splitThrough, toEditPayload,
} from './proposalReducer'

const r = (page, y0, y1, x0 = 10, x1 = 90) => ({ page, x0, y0, x1, y1 })

function paper() {
  return {
    label: 'q1',
    pages: [
      { page: 2, width_pt: 100, height_pt: 200 },
      { page: 3, width_pt: 100, height_pt: 200 },
    ],
    questions: [
      { number: 1, question_rects: [r(2, 10, 60)], answer_rects: [r(3, 0, 20)], flags: ['pixel_ink'] },
      { number: 2, question_rects: [r(2, 70, 120), r(3, 10, 50)], answer_rects: [r(3, 30, 50)], flags: ['pixel_ink', 'grid_page'] },
    ],
    orphan_answers: [r(3, 100, 120)],
  }
}

describe('proposalReducer', () => {
  it('resizes an edge, clamped to the page and a minimum size, without mutating', () => {
    const p = paper()
    const before = JSON.stringify(p)
    const sel = { list: 'question', q: 0, i: 0 }
    const a = resizeRect(p, sel, { y1: 80 })
    expect(a.questions[0].question_rects[0]).toEqual(r(2, 10, 80))
    expect(JSON.stringify(p)).toBe(before)
    expect(resizeRect(p, sel, { x1: 500 }).questions[0].question_rects[0].x1).toBe(100)
    expect(resizeRect(p, sel, { x0: -5 }).questions[0].question_rects[0].x0).toBe(0)
    const tiny = resizeRect(p, sel, { y0: 300 }).questions[0].question_rects[0]
    expect(tiny.y1 - tiny.y0).toBeGreaterThan(0)
    expect(tiny.y0).toBe(56)
    expect(resizeRect(p, sel, { y1: 60 })).toBe(p)
  })

  it('resizes answer and orphan rectangles', () => {
    const p = paper()
    expect(resizeRect(p, { list: 'answer', q: 1, i: 0 }, { y0: 35 }).questions[1].answer_rects[0].y0).toBe(35)
    expect(resizeRect(p, { list: 'orphan', i: 0 }, { x0: 20 }).orphan_answers[0].x0).toBe(20)
  })

  it('deletes a rectangle', () => {
    const p = paper()
    const a = deleteRect(p, { list: 'question', q: 1, i: 1 })
    expect(a.questions[1].question_rects).toEqual([r(2, 70, 120)])
    expect(deleteRect(p, { list: 'answer', q: 0, i: 0 }).questions[0].answer_rects).toEqual([])
    expect(deleteRect(p, { list: 'orphan', i: 0 }).orphan_answers).toEqual([])
  })

  it("deleting a question's last rectangle deletes the question and orphans its answers", () => {
    const a = deleteRect(paper(), { list: 'question', q: 0, i: 0 })
    expect(a.questions.map(q => q.number)).toEqual([2])
    expect(a.orphan_answers).toEqual([r(3, 0, 20), r(3, 100, 120)])  // in document order
  })

  it('renumbers, refusing duplicates and non-positive or non-integer numbers', () => {
    const p = paper()
    expect(renumber(p, 0, 5).questions.map(q => q.number)).toEqual([2, 5])  // re-sorted by number
    expect(renumber(p, 0, 2)).toBe(p)
    expect(renumber(p, 0, 0)).toBe(p)
    expect(renumber(p, 0, 1.5)).toBe(p)
    expect(renumberError(p, 0, 2)).toMatch(/already exists/)
    expect(renumberError(p, 0, 1)).toBeNull()
  })

  it('merges a question into the previous one, concatenating rects and flags', () => {
    const p = paper()
    const m = mergeWithPrevious(p, 1)
    expect(m.questions).toHaveLength(1)
    expect(m.questions[0].number).toBe(1)
    expect(m.questions[0].question_rects).toHaveLength(3)
    expect(m.questions[0].answer_rects).toHaveLength(2)
    expect(m.questions[0].flags).toEqual(['pixel_ink', 'grid_page'])
    expect(mergeWithPrevious(p, 0)).toBe(p)
  })

  it('splits between rectangles; answers stay with the first part, new number is max + 1', () => {
    const p = paper()
    const s = splitBetween(p, 1, 1)
    expect(s.questions.map(q => q.number)).toEqual([1, 2, 3])
    expect(s.questions[1].question_rects).toEqual([r(2, 70, 120)])
    expect(s.questions[1].answer_rects).toHaveLength(1)
    expect(s.questions[2].question_rects).toEqual([r(3, 10, 50)])
    expect(s.questions[2].answer_rects).toEqual([])
    expect(splitBetween(p, 1, 0)).toBe(p)
    expect(splitBetween(p, 1, 2)).toBe(p)
    expect(splitBetween(p, 0, 1)).toBe(p)
  })

  it('splits through a rectangle with a horizontal cut', () => {
    const p = paper()
    const s = splitThrough(p, 1, 0, 100)
    expect(s.questions.map(q => q.number)).toEqual([1, 2, 3])
    expect(s.questions[1].question_rects).toEqual([r(2, 70, 100)])
    expect(s.questions[2].question_rects).toEqual([r(2, 100, 120), r(3, 10, 50)])
    expect(splitThrough(p, 1, 0, 71)).toBe(p)
    expect(splitThrough(p, 1, 0, 500)).toBe(p)
  })

  it('keeps questions sorted by number and every box list in document order', () => {
    const p = {
      ...paper(),
      questions: [
        { number: 3, question_rects: [r(3, 10, 20), r(2, 50, 60), r(2, 50, 60, 0, 5)], answer_rects: [], flags: [] },
        { number: 1, question_rects: [r(2, 0, 5)], answer_rects: [r(3, 40, 50), r(3, 0, 10)], flags: [] },
      ],
      orphan_answers: [r(3, 90, 100), r(2, 0, 10)],
    }
    const n = normalise(p)
    expect(n.questions.map(q => q.number)).toEqual([1, 3])
    expect(n.questions[1].question_rects).toEqual([r(2, 50, 60, 0, 5), r(2, 50, 60), r(3, 10, 20)])  // page, top, left
    expect(n.questions[0].answer_rects).toEqual([r(3, 0, 10), r(3, 40, 50)])
    expect(n.orphan_answers).toEqual([r(2, 0, 10), r(3, 90, 100)])
    expect(normalise(n)).toBe(n)  // already in order: the same paper
  })

  it('merges into the next-lower number and keeps the merged boxes in document order', () => {
    const p = {
      ...paper(),
      questions: [
        { number: 1, question_rects: [r(3, 100, 150)], answer_rects: [], flags: [] },
        { number: 2, question_rects: [r(2, 10, 60)], answer_rects: [], flags: [] },
      ],
    }
    expect(mergeWithPrevious(p, 1).questions[0].question_rects).toEqual([r(2, 10, 60), r(3, 100, 150)])
  })

  it('follows the selected box through a re-sort, even when the edit replaced it', () => {
    const p = paper()
    const sel = { list: 'question', q: 1, i: 1 }  // Q2's box on page 3
    const moved = moveRect(p, sel, 10, 0)
    expect(followSelection(p, moved, sel)).toEqual(sel)
    const renumbered = renumber(p, 0, 9)  // Q1 becomes Q9 and moves to the end
    expect(followSelection(p, renumbered, { list: 'answer', q: 0, i: 0 })).toEqual({ list: 'answer', q: 1, i: 0 })
    // A box dragged above its question's other box on the same page becomes its first.
    const two = { ...p, questions: [p.questions[0], { ...p.questions[1], question_rects: [r(2, 70, 120), r(2, 150, 160)] }] }
    const moved2 = moveRect(two, { list: 'question', q: 1, i: 1 }, 10, 0)
    expect(moved2.questions[1].question_rects[1]).toMatchObject({ y0: 0 })  // kept in place while dragging
    const dragged = normalise(moved2)  // the drag ends
    expect(dragged.questions[1].question_rects[0]).toMatchObject({ y0: 0, y1: 10 })
    expect(followSelection(two, dragged, { list: 'question', q: 1, i: 1 })).toEqual({ list: 'question', q: 1, i: 0 })
  })

  it('builds the PUT payload from the editable parts only', () => {
    const body = toEditPayload([paper()])
    expect(Object.keys(body.papers[0]).sort()).toEqual(['orphan_answers', 'questions'])
  })
})

describe('moving, drawing and reassigning boxes', () => {
  const base = () => ({
    pages: [{ page: 1, width_pt: 600, height_pt: 800 }, { page: 2, width_pt: 600, height_pt: 800 }],
    questions: [
      { number: 1, question_rects: [{ page: 1, x0: 10, y0: 10, x1: 110, y1: 60 }], answer_rects: [{ page: 2, x0: 0, y0: 0, x1: 50, y1: 50 }], flags: [] },
      { number: 2, question_rects: [{ page: 1, x0: 10, y0: 100, x1: 110, y1: 160 }], answer_rects: [], flags: [] },
    ],
    orphan_answers: [{ page: 2, x0: 100, y0: 100, x1: 200, y1: 150 }],
  })

  it('moves a box keeping its size, stopping at the page edge', () => {
    const p = moveRect(base(), { list: 'question', q: 0, i: 0 }, 550, -20)
    expect(p.questions[0].question_rects[0]).toEqual({ page: 1, x0: 500, y0: 0, x1: 600, y1: 50 })
    const same = base()
    expect(moveRect(same, { list: 'question', q: 0, i: 0 }, 10, 10)).toBe(same)
  })

  it('adds a drawn question box to the numbered question, in document order', () => {
    const drawn = { page: 1, x0: 300, y0: 400, x1: 200, y1: 300 }
    const toQ2 = addRect(base(), 'question', 2, drawn)
    expect(toQ2.paper.questions[1].question_rects[1]).toEqual({ page: 1, x0: 200, y0: 300, x1: 300, y1: 400 })
    expect(toQ2.sel).toEqual({ list: 'question', q: 1, i: 1 })
    // Above Q2's box on the same page, or on an earlier page: it goes first.
    const above = addRect(base(), 'question', 2, { page: 1, x0: 10, y0: 70, x1: 110, y1: 90 })
    expect(above.paper.questions[1].question_rects[0]).toMatchObject({ page: 1, y0: 70 })
    expect(above.sel).toEqual({ list: 'question', q: 1, i: 0 })
    const p = { ...base(), questions: [base().questions[0], { ...base().questions[1], question_rects: [{ page: 2, x0: 10, y0: 10, x1: 110, y1: 60 }] }] }
    const earlier = addRect(p, 'question', 2, { page: 1, x0: 10, y0: 700, x1: 110, y1: 760 })
    expect(earlier.paper.questions[1].question_rects.map(x => x.page)).toEqual([1, 2])
  })

  it('starts a new question at its place in number order', () => {
    const drawn = { page: 1, x0: 10, y0: 300, x1: 100, y1: 360 }
    const ten = addRect(base(), 'question', 10, drawn)
    expect(ten.paper.questions.map(q => q.number)).toEqual([1, 2, 10])
    expect(ten.paper.questions[2]).toMatchObject({ question_rects: [{ page: 1, y0: 300 }], answer_rects: [], flags: [] })
    const p = { ...base(), questions: [base().questions[0], { ...base().questions[1], number: 5 }] }
    const three = addRect(p, 'question', 3, drawn)
    expect(three.paper.questions.map(q => q.number)).toEqual([1, 3, 5])
    expect(three.sel).toEqual({ list: 'question', q: 1, i: 0 })
  })

  it('adds an answer box only to an existing question, except in an answer-only paper', () => {
    const drawn = { page: 2, x0: 10, y0: 200, x1: 100, y1: 260 }
    const toQ2 = addRect(base(), 'answer', 2, drawn)
    expect(toQ2.paper.questions[1].answer_rects).toHaveLength(1)
    expect(toQ2.sel).toEqual({ list: 'answer', q: 1, i: 0 })
    const p = base()
    const missing = addRect(p, 'answer', 7, drawn)
    expect(missing.paper).toBe(p)
    expect(missing.error).toBe("Question 7 doesn't exist. Draw its question box first.")
    const answerOnly = addRect({ ...base(), role: 'answer_only' }, 'answer', 7, drawn)
    expect(answerOnly.paper.questions[2]).toMatchObject({ number: 7, question_rects: [], answer_rects: [{ page: 2 }] })
  })

  it('says why a number cannot be drawn for', () => {
    const p = base()
    expect(drawError(p, 'question', null)).toBe('Enter a question number')
    expect(drawError(p, 'question', 0)).toMatch(/positive whole number/)
    expect(drawError(p, 'question', 9)).toBeNull()
    expect(drawError(p, 'answer', 9)).toMatch(/doesn't exist/)
    expect(drawError(p, 'answer', 1)).toBeNull()
  })

  it('refuses a box that is too small or on a page the paper does not have', () => {
    const p = base()
    expect(addRect(p, 'question', 3, { page: 1, x0: 10, y0: 10, x1: 12, y1: 100 })).toEqual({ paper: p, sel: null, error: null })
    expect(addRect(p, 'question', 3, { page: 9, x0: 10, y0: 10, x1: 100, y1: 100 }).paper).toBe(p)
  })

  it('assigns an orphan answer to a question, moves an answer between questions, and back to orphan', () => {
    const a = assignAnswer(base(), { list: 'orphan', q: null, i: 0 }, 1)
    expect(a.paper.orphan_answers).toHaveLength(0)
    expect(a.paper.questions[1].answer_rects).toEqual([{ page: 2, x0: 100, y0: 100, x1: 200, y1: 150 }])
    expect(a.sel).toEqual({ list: 'answer', q: 1, i: 0 })
    const b = assignAnswer(a.paper, { list: 'answer', q: 0, i: 0 }, null)
    expect(b.paper.questions[0].answer_rects).toHaveLength(0)
    expect(b.paper.orphan_answers).toHaveLength(1)
    const p = base()
    expect(assignAnswer(p, { list: 'question', q: 0, i: 0 }, 1).paper).toBe(p)
    expect(assignAnswer(p, { list: 'answer', q: 0, i: 0 }, 0).paper).toBe(p)
  })
})
