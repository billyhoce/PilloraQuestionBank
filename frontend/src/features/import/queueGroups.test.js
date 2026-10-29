import { describe, it, expect } from 'vitest'
import { groupJobs, jobRole, suggestedPairs } from './queueGroups'

const paper = (key, role, extra = {}) => ({ key, role, status: 'pending', linked: false, partner: null, suggestion: null, ...extra })
const job = (id, day, papers, filename = `${id}.pdf`) => ({ id, filename, created_at: `2026-10-${day}T00:00:00Z`, papers })
const link = (jobId, key) => ({ job_id: jobId, paper_key: key, filename: `${jobId}.pdf`, ingest_paper_id: 1 })

describe('groupJobs', () => {
  it('puts linked jobs on one card, oldest first, opening at the question paper', () => {
    const answers = job('a', '02', [paper('a1', 'answer_only', { linked: true, partner: link('q', 'q1') })])
    const questions = job('q', '05', [paper('q1', 'question', { linked: true, partner: link('a', 'a1') })])
    const lone = job('x', '01', [paper('q1', 'question')])
    const groups = groupJobs([questions, lone, answers])
    expect(groups.map(g => g.jobs.map(j => j.id))).toEqual([['x'], ['a', 'q']])
    expect(groups[0].pair).toBeNull()
    expect(groups[1].pair).toEqual({ jobId: 'q', key: 'q1' })
    expect(groups[1].created_at).toBe(answers.created_at)
  })

  it('leaves a link to a job not in the list, and a same-job link, on a card of its own', () => {
    const elsewhere = job('a', '02', [paper('a1', 'answer_only', { linked: true, partner: link('gone', 'q1') })])
    const self = job('b', '03', [
      paper('q1', 'question', { linked: true, partner: link('b', 'a1') }),
      paper('a1', 'answer_only', { linked: true, partner: link('b', 'q1') }),
    ])
    const groups = groupJobs([elsewhere, self])
    expect(groups.map(g => g.jobs.length)).toEqual([1, 1])
    expect(groups.every(g => g.pair === null)).toBe(true)
  })

  it('joins a booklet of two papers with both answer booklets', () => {
    const qs = job('q', '01', [
      paper('q1', 'question', { partner: link('a1job', 'a1') }), paper('q2', 'question', { partner: link('a2job', 'a1') }),
    ])
    const a1 = job('a1job', '02', [paper('a1', 'answer_only', { partner: link('q', 'q1') })])
    const a2 = job('a2job', '03', [paper('a1', 'answer_only', { partner: link('q', 'q2') })])
    const [group] = groupJobs([a2, qs, a1])
    expect(group.jobs.map(j => j.id)).toEqual(['q', 'a1job', 'a2job'])
    expect(group.pair).toEqual({ jobId: 'q', key: 'q1' })
  })

  it('ignores a decided paper’s link', () => {
    const a = job('a', '01', [paper('a1', 'answer_only', { status: 'attached', partner: link('q', 'q1') })])
    const q = job('q', '02', [paper('q1', 'question', { status: 'confirmed' })])
    expect(groupJobs([a, q])).toHaveLength(2)
  })
})

describe('jobRole', () => {
  it('names a job by what it holds', () => {
    expect(jobRole(job('a', '01', [paper('a1', 'answer_only')]))).toBe('Answers')
    expect(jobRole(job('q', '01', [paper('q1', 'question'), paper('a1', 'answer_only')]))).toBe('Questions')
    expect(jobRole(job('e', '01', []))).toBeNull()
  })
})

describe('suggestedPairs', () => {
  it('offers each pending, unlinked answer paper with a suggestion', () => {
    const suggestion = { job_id: 'q', paper_key: 'q1', filename: 'P2 questions.pdf', ingest_paper_id: 7 }
    const jobs = [
      job('a', '01', [
        paper('a1', 'answer_only', { suggestion, match_note: 'uploaded together' }),
        paper('a2', 'answer_only', { suggestion, linked: true }),
        paper('a3', 'answer_only', { suggestion, status: 'skipped' }),
      ], 'P2 solutions.pdf'),
    ]
    expect(suggestedPairs(jobs)).toEqual([{
      id: 'a:a1',
      answers: { jobId: 'a', key: 'a1', filename: 'P2 solutions.pdf' },
      questions: { jobId: 'q', key: 'q1', filename: 'P2 questions.pdf', ingestPaperId: 7 },
      note: 'uploaded together',
    }])
  })
})
