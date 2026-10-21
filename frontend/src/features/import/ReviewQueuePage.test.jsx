import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ReviewQueuePage from './ReviewQueuePage'
import { REVIEW_POLL_MS } from './useReviewQueue'
import { describeMetadata, matchState } from './reviewQueueText'
import { api } from '../../api/client'

vi.mock('../../api/client', () => ({
  api: {
    import: { listJobs: vi.fn() },
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
})
