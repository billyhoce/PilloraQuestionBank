import { describe, it, expect } from 'vitest'
import { coverageOf, partlyAnsweredWarning, unansweredNumbers, unansweredWarning } from './answerCoverage'

const box = { page: 1, x0: 0, y0: 0, x1: 1, y1: 1 }
const paper = (...answered) => ({
  questions: answered.map((a, i) => ({ number: i + 1, question_rects: [box], answer_rects: a ? [box] : [] })),
})

describe('answer coverage', () => {
  it('is none, partial or all by how many questions have an answer box', () => {
    expect(coverageOf(paper(false, false))).toBe('none')
    expect(coverageOf(paper(true, false))).toBe('partial')
    expect(coverageOf(paper(true, true))).toBe('all')
    expect(coverageOf(paper())).toBe('none')
  })

  it('counts the answers a linked answer paper brings in by number', () => {
    expect(unansweredNumbers(paper(false, false, false), [1, 3, 9])).toEqual([2])
    expect(coverageOf(paper(false, false), [1, 2])).toBe('all')
    expect(unansweredNumbers({ questions: [{ number: '2', answer_rects: [] }] }, [2])).toEqual([])
  })

  it('words the unanswered questions as ranges', () => {
    expect(unansweredWarning([5, 6, 7])).toBe('Q5–Q7 have no answers')
    expect(unansweredWarning([2])).toBe('Q2 has no answers')
    expect(unansweredWarning([1, 3, 4, 9])).toBe('Q1, Q3–Q4, Q9 have no answers')
    expect(unansweredWarning([])).toBeNull()
  })

  it('warns only for a partly answered paper', () => {
    expect(partlyAnsweredWarning(paper(true, false, false))).toBe('Q2–Q3 have no answers')
    expect(partlyAnsweredWarning(paper(false, false))).toBeNull()
    expect(partlyAnsweredWarning(paper(true, true))).toBeNull()
    expect(partlyAnsweredWarning(paper(false, false), [1])).toBe('Q2 has no answers')
  })
})
