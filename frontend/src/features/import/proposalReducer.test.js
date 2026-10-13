import { describe, it, expect } from 'vitest'
import {
  deleteRect, mergeWithPrevious, renumber, renumberError, resizeRect, splitBetween, splitThrough, toEditPayload,
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
    expect(a.orphan_answers).toEqual([r(3, 100, 120), r(3, 0, 20)])
  })

  it('renumbers, refusing duplicates and non-positive or non-integer numbers', () => {
    const p = paper()
    expect(renumber(p, 0, 5).questions[0].number).toBe(5)
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

  it('builds the PUT payload from the editable parts only', () => {
    const body = toEditPayload([paper()])
    expect(Object.keys(body.papers[0]).sort()).toEqual(['orphan_answers', 'questions'])
  })
})
