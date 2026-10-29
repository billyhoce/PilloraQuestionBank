import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ReviewQueuePage from './ReviewQueuePage'
import { REVIEW_POLL_MS } from './useReviewQueue'
import { describeMetadata, matchState, needsPartner } from './reviewQueueText'
import { api } from '../../api/client'

vi.mock('../../api/client', () => ({
  api: {
    import: {
      listJobs: vi.fn(), paperCandidates: vi.fn(), matchJobPaper: vi.fn(), attachJobPaper: vi.fn(), answerMappingTable: vi.fn(),
      rejectSuggestion: vi.fn(), switchPaperRole: vi.fn(),
    },
    subjects: { list: vi.fn() }, streams: { list: vi.fn() }, levels: { list: vi.fn() },
    schools: { list: vi.fn() }, examTypes: { list: vi.fn() }, schoolLevels: { list: vi.fn() },
  },
}))

const paper = (key, role, extra = {}) => ({
  key, role, status: 'pending', school_id: 4, year: 2024, level_id: 3, subject_id: 1, exam_type_id: 5,
  stream_id: null, paper_number: '1', linked: false, match_status: null, ...extra,
})

const OLD = {
  id: 'old', filename: 'old.pdf', status: 'review_ready', created_at: '2026-10-01T00:00:00Z', page_count: 30,
  warnings_count: 1, needs_review: true,
  papers: [paper('q1', 'question', { status: 'confirmed' }), paper('q2', 'question', { school_id: null })],
}
const NEWER = {
  id: 'new', filename: 'answers.pdf', status: 'review_ready', created_at: '2026-10-10T00:00:00Z', page_count: 8,
  papers: [paper('a1', 'answer_only')],
}
const listing = jobs => ({ jobs, workerAlive: true, heartbeatAgeS: 1 })

beforeEach(() => {
  vi.clearAllMocks()
  api.import.listJobs.mockResolvedValue(listing([NEWER, OLD]))
  api.subjects.list.mockResolvedValue([{ id: 1, name: 'Math' }])
  api.streams.list.mockResolvedValue([])
  api.levels.list.mockResolvedValue([{ id: 3, name: 'Sec 3', school_level_id: 9 }])
  api.schools.list.mockResolvedValue([{ id: 4, name: 'RI' }])
  api.examTypes.list.mockResolvedValue([{ id: 5, name: 'EOY' }])
  api.schoolLevels.list.mockResolvedValue([{ id: 9, name: 'Secondary' }])
})
afterEach(() => vi.useRealTimers())

const renderPage = () => render(<MemoryRouter><ReviewQueuePage /></MemoryRouter>)

describe('ReviewQueuePage', () => {
  it('lists review-ready jobs oldest first with their papers, metadata and match state', async () => {
    renderPage()
    const cards = await screen.findAllByTestId('review-card')
    expect(api.import.listJobs).toHaveBeenCalledWith('review_ready')
    expect(cards.map(c => within(c).getAllByRole('link')[0].textContent)).toEqual(['old.pdf', 'answers.pdf'])
    const old = within(cards[0])
    expect(old.getByText(/30 pages · 2 papers, 1 still to decide/)).toBeInTheDocument()
    expect(old.getByText(/Pages flagged/)).toBeInTheDocument()
    expect(await old.findByText(/(missing school)/)).toBeInTheDocument()
    expect(old.getByText(/— Confirmed/)).toBeInTheDocument()
    expect(within(cards[1]).getByText(/Not matched to a question paper/)).toBeInTheDocument()
    expect(within(cards[1]).getByText(/RI · 2024 · Secondary Sec 3 · Math · EOY · P1/)).toBeInTheDocument()
    expect(old.getByRole('link', { name: 'Review' })).toHaveAttribute('href', '/admin/import/jobs/old/review')
  })

  it('filters to jobs with unmatched answers', async () => {
    renderPage()
    await screen.findAllByTestId('review-card')
    await userEvent.click(screen.getByLabelText('Only jobs with unmatched answers'))
    expect(screen.getAllByTestId('review-card')).toHaveLength(1)
    expect(screen.getByText('answers.pdf')).toBeInTheDocument()
  })

  it('polls, and tags jobs that arrive after the first load as new', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    api.import.listJobs.mockResolvedValue(listing([OLD]))
    renderPage()
    await screen.findByText('old.pdf')
    expect(screen.queryByText('New')).toBeNull()
    api.import.listJobs.mockResolvedValue(listing([NEWER, OLD]))
    await act(async () => { await vi.advanceTimersByTimeAsync(REVIEW_POLL_MS) })
    const card = (await screen.findByText('answers.pdf')).closest('li')
    expect(within(card).getByText('New')).toBeInTheDocument()
  })

  it('flags a pending question paper that is only partly answered', async () => {
    const partly = paper('q3', 'question', { answer_coverage: 'partial', unanswered: [5, 6, 7] })
    const bare = paper('q4', 'question', { answer_coverage: 'none', unanswered: [1, 2] })
    api.import.listJobs.mockResolvedValue(listing([{ ...OLD, papers: [partly, bare] }]))
    renderPage()
    const [card] = await screen.findAllByTestId('review-card')
    expect(within(card).getByText(/Q5–Q7 have no answers/)).toBeInTheDocument()
    expect(within(card).getAllByText(/no answers/)).toHaveLength(1)
  })

  it('puts a Match button only on the paper lines that need a partner', async () => {
    const bare = paper('q1', 'question', { answer_coverage: 'none', unanswered: [1, 2] })
    const answered = paper('q2', 'question', { answer_coverage: 'all', unanswered: [] })
    const linked = paper('a1', 'answer_only', { answer_coverage: 'all', unanswered: [], linked: true })
    const loose = paper('a2', 'answer_only', { answer_coverage: 'all', unanswered: [] })
    api.import.listJobs.mockResolvedValue(listing([{ ...OLD, papers: [bare, answered, linked, loose] }]))
    renderPage()
    const [card] = await screen.findAllByTestId('review-card')
    const lines = within(card).getAllByRole('listitem')
    expect(lines.map(l => within(l).queryByRole('button', { name: /Match/ }) !== null)).toEqual([true, false, false, true])
  })

  it('opens the "Match this paper" popup from the queue and refreshes the card after pairing', async () => {
    const bare = paper('q1', 'question', {
      school_id: null, extracted_school: 'Raffles Instn', answer_coverage: 'none', unanswered: [1, 2],
    })
    api.import.listJobs.mockResolvedValue(listing([{ ...OLD, papers: [bare] }]))
    api.import.paperCandidates.mockResolvedValue({ exact: [{
      kind: 'pending', ingest_paper_id: 31, paper_id: null, job_id: 'j2', filename: 'answers.pdf', paper_key: 'a1',
      same_job: false, role: 'answer_only', details: {}, agree: [], differ: [], partner: null, preview: null,
      question_numbers: [], answer_numbers: [1, 2], answer_coverage: 'all',
    }], best: [] })
    api.import.answerMappingTable.mockResolvedValue({
      questions: [{ label: '1', answered: false, preview: null }], answers: [{ label: '1', preview: null }], mapping: null,
    })
    api.import.matchJobPaper.mockResolvedValue({ matches: { filename: 'answers.pdf', paper_key: 'a1' }, proposal: null })
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: 'Match q1' }))
    expect(await screen.findByText('Match this paper')).toBeInTheDocument()
    // pre-filled from the summary, the unresolved school searched as blank
    await waitFor(() => expect(api.import.paperCandidates).toHaveBeenCalledWith('old', 'q1', {
      subject_id: 1, level_id: 3, exam_type_id: 5, year: 2024, paper_number: '1',
    }))
    expect(screen.getByText(/Raffles Instn/)).toBeInTheDocument()
    await userEvent.click(await screen.findByRole('button', { name: 'Pair' }))
    await screen.findByRole('table')
    api.import.listJobs.mockClear()
    await userEvent.click(screen.getByRole('button', { name: 'Pair' }))
    expect(api.import.matchJobPaper).toHaveBeenCalledWith('old', 'q1', 31, expect.any(Object), { 1: '1' })
    await waitFor(() => expect(screen.queryByText('Match this paper')).toBeNull())
    expect(api.import.listJobs).toHaveBeenCalledWith('review_ready')
  })

  it('refreshes the queue after attaching from it', async () => {
    api.import.listJobs.mockResolvedValue(listing([NEWER]))
    api.import.paperCandidates.mockResolvedValue({ exact: [{
      kind: 'bank', ingest_paper_id: null, paper_id: 7, job_id: null, filename: null, paper_key: null,
      same_job: false, role: 'question', details: {}, agree: [], differ: [], partner: null, preview: null,
      question_numbers: [1], answer_numbers: [], answer_coverage: 'none',
    }], best: [] })
    api.import.answerMappingTable.mockResolvedValue({
      questions: [{ label: '1', answered: false, preview: null }], answers: [{ label: '1', preview: null }], mapping: null,
    })
    api.import.attachJobPaper.mockResolvedValue({ job_status: 'review_ready', attached: 1 })
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: 'Match a1' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Attach' }))
    await screen.findByRole('table')
    api.import.listJobs.mockClear()
    await userEvent.click(screen.getByRole('button', { name: 'Attach answers' }))
    expect(api.import.attachJobPaper).toHaveBeenCalledWith('new', { key: 'a1', paper_id: 7, mapping: { 1: '1' } })
    await waitFor(() => expect(screen.queryByText('Match this paper')).toBeNull())
    expect(api.import.listJobs).toHaveBeenCalledWith('review_ready')
  })

  it('shows a linked question booklet and answer booklet as one card reviewed together', async () => {
    const qjob = { ...OLD, id: 'qj', filename: 'P1 Qns.pdf', papers: [paper('q1', 'question', {
      linked: true, partner: { job_id: 'aj', paper_key: 'a1', filename: 'P1 Soln.pdf', ingest_paper_id: 2 },
    })] }
    const ajob = { ...NEWER, id: 'aj', filename: 'P1 Soln.pdf', papers: [paper('a1', 'answer_only', {
      linked: true, partner: { job_id: 'qj', paper_key: 'q1', filename: 'P1 Qns.pdf', ingest_paper_id: 1 },
    })] }
    api.import.listJobs.mockResolvedValue(listing([ajob, qjob]))
    renderPage()
    const cards = await screen.findAllByTestId('review-card')
    expect(cards).toHaveLength(1)
    const card = within(cards[0])
    expect(card.getByText('Questions and answers, reviewed together')).toBeInTheDocument()
    expect(card.getByText('P1 Qns.pdf')).toBeInTheDocument()
    expect(card.getByText('P1 Soln.pdf')).toBeInTheDocument()
    expect(card.getByText('Questions')).toBeInTheDocument()
    expect(card.getByText('Answers')).toBeInTheDocument()
    expect(card.getByRole('link', { name: 'Review' })).toHaveAttribute('href', '/admin/import/jobs/qj/review?paper=q1')
  })

  it('offers a suggested pair, and pairs or turns it down', async () => {
    const suggested = { ...NEWER, filename: 'P2 solutions.pdf', papers: [paper('a1', 'answer_only', {
      match_status: 'suggested', match_note: 'same year; uploaded together',
      suggestion: { job_id: 'old', paper_key: 'q2', filename: 'P2 questions.pdf', ingest_paper_id: 9 },
    })] }
    api.import.listJobs.mockResolvedValue(listing([suggested, OLD]))
    api.import.matchJobPaper.mockResolvedValue({})
    api.import.rejectSuggestion.mockResolvedValue({})
    renderPage()
    const strip = within(await screen.findByRole('region', { name: 'Suggested pairs' }))
    expect(strip.getByText(/same year; uploaded together/)).toBeInTheDocument()
    expect(screen.getByText(/Looks like the answers to P2 questions.pdf/)).toBeInTheDocument()
    await userEvent.click(strip.getByRole('button', { name: 'Pair P2 solutions.pdf' }))
    expect(api.import.matchJobPaper).toHaveBeenCalledWith('new', 'a1', 9)
    await userEvent.click(strip.getByRole('button', { name: 'Not a pair: P2 solutions.pdf' }))
    expect(api.import.rejectSuggestion).toHaveBeenCalledWith('new', 'a1')
  })

  it('turns a question paper with no answers into an answer booklet after asking', async () => {
    const bare = paper('q1', 'question', { answer_coverage: 'none', unanswered: [1, 2] })
    api.import.listJobs.mockResolvedValue(listing([{ ...OLD, papers: [bare] }]))
    api.import.switchPaperRole.mockResolvedValue({ role: 'answer_only' })
    const ask = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true)
    renderPage()
    const button = await screen.findByRole('button', { name: 'q1 is an answer booklet' })
    await userEvent.click(button)
    expect(api.import.switchPaperRole).not.toHaveBeenCalled()
    await userEvent.click(button)
    expect(api.import.switchPaperRole).toHaveBeenCalledWith('old', 'q1', 'answer_only')
    ask.mockRestore()
  })

  it('says when there is nothing to review', async () => {
    api.import.listJobs.mockResolvedValue(listing([]))
    renderPage()
    expect(await screen.findByText(/Nothing to review/)).toBeInTheDocument()
  })
})

describe('reviewQueueText', () => {
  it('names the known fields and lists the missing ones', () => {
    const d = describeMetadata({ school_id: 4, year: 2024, level_id: null, subject_id: 99, exam_type_id: null, paper_number: null }, { schools: [{ id: 4, name: 'RI' }], subjects: [] })
    expect(d.text).toBe('RI · 2024 · #99')
    expect(d.missing).toEqual(['level', 'exam type', 'paper no.'])
  })

  it('labels a school typed during review as new', () => {
    const d = describeMetadata({ school_id: null, new_school_name: 'Raffles Instn', year: 2024 }, { schools: [] })
    expect(d.text).toBe('Raffles Instn (new) · 2024')
    expect(d.missing).not.toContain('school')
  })

  it('says where an answer paper stands', () => {
    expect(matchState({ role: 'answer_only', linked: true }).text).toMatch(/Linked/)
    expect(matchState({ role: 'answer_only', match_status: 'proposed' }).text).toMatch(/found/)
    expect(matchState({ role: 'answer_only', match_status: 'manual' }).tone).toBe('amber')
    expect(matchState({ role: 'question', linked: false })).toBeNull()
  })

  it('says which paper lines need a partner', () => {
    const p = (role, extra) => ({ role, status: 'pending', linked: false, answer_coverage: 'all', unanswered: [], ...extra })
    expect(needsPartner(p('answer_only'))).toBe(true)
    expect(needsPartner(p('answer_only', { match_status: 'proposed' }))).toBe(true)
    expect(needsPartner(p('question', { answer_coverage: 'none', unanswered: [1, 2] }))).toBe(true)
    expect(needsPartner(p('question'))).toBe(false)
    expect(needsPartner(p('question', { answer_coverage: 'partial', unanswered: [2] }))).toBe(false)
    // already linked, decided, or with no questions at all
    expect(needsPartner(p('answer_only', { linked: true }))).toBe(false)
    expect(needsPartner(p('question', { answer_coverage: 'none', unanswered: [1], linked: true }))).toBe(false)
    expect(needsPartner(p('answer_only', { status: 'skipped' }))).toBe(false)
    expect(needsPartner(p('question', { answer_coverage: 'none', unanswered: [] }))).toBe(false)
    expect(needsPartner(p('answer_only', { answer_coverage: 'none', unanswered: [] }))).toBe(false)
  })
})
