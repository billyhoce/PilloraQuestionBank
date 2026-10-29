import { describe, expect, it } from 'vitest'
import { answersOn, byNumber, mappingWarnings, moveAnswer, startMapping } from './answerMapping'

const qs = (...labels) => labels.map(l => (typeof l === 'object' ? l : { label: String(l), answered: false }))
const as = (...labels) => labels.map(l => ({ label: String(l) }))

describe('byNumber', () => {
  it('puts each answer onto the question with its number, else nowhere', () => {
    expect(byNumber(qs(1, 2, 3), as(1, 2, 9, '3a'))).toEqual({ 1: '1', 2: '2', 9: null, '3a': null })
  })

  it('shifts every answer by N, for a Section B that restarts at 1', () => {
    expect(byNumber(qs(11, 12, 13), as(1, 2, 3), 10)).toEqual({ 1: '11', 2: '12', 3: '13' })
    expect(byNumber(qs(1, 2), as(3, 4), -2)).toEqual({ 3: '1', 4: '2' })
  })
})

describe('startMapping', () => {
  it('is by number until a stored mapping says otherwise', () => {
    expect(startMapping(qs(1, 2), as(1, 2), null)).toEqual({ 1: '1', 2: '2' })
    expect(startMapping(qs(1, 2), as(1, 2), { 1: '2', 7: '1' })).toEqual({ 1: '2', 2: '2' })
  })
})

describe('moveAnswer and answersOn', () => {
  it('changes one row and lists the answers going onto a question', () => {
    const m = moveAnswer({ 1: '1', 2: '2' }, '2', '1')
    expect(m).toEqual({ 1: '1', 2: '1' })
    expect(answersOn(m, as(1, 2), '1').map(a => a.label)).toEqual(['1', '2'])
    expect(moveAnswer(m, '1', null)).toEqual({ 1: null, 2: '1' })
  })
})

describe('mappingWarnings', () => {
  it('names the questions left without answers and the answers left without a question', () => {
    const questions = qs(10, 11, 12)
    expect(mappingWarnings({ 1: '10', 13: null }, questions)).toEqual([
      'Q11–Q12 would get no answers', 'Answer 13 has no question',
    ])
    expect(mappingWarnings({ 1: '10', 2: '11', 3: '12', 4: '99', 5: null }, questions)).toEqual([
      'Answers 4, 5 have no question',
    ])
  })

  it('counts a question that already has answers of its own as answered', () => {
    expect(mappingWarnings({ 1: '1' }, qs(1, { label: '2', answered: true }))).toEqual([])
  })
})
