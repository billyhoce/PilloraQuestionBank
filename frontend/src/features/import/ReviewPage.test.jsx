import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import ReviewPage from './ReviewPage'
import { api } from '../../api/client'

vi.mock('../../api/client', () => ({
  api: { import: { review: vi.fn(), manualPages: vi.fn(), saveProposal: vi.fn() } },
}))

const page = (n, extra = {}) => ({
  page: n, image: `pages/p${n}.webp`, url: `https://s3/p${n}.webp`,
  width_pt: 100, height_pt: 200, width_px: 200, height_px: 400,
  needs_review: false, review_reason: null, ...extra,
})

const REVIEW = {
  job_id: 'j1', filename: 'scan.pdf', edited: false,
  proposal: {
    papers: [{
      label: 'q1', answer_label: 'a1',
      pages: [page(2), page(3, { needs_review: true, review_reason: 'dense' })],
      questions: [
        { number: 1, question_rects: [{ page: 2, x0: 10, y0: 20, x1: 60, y1: 120 }],
          answer_rects: [{ page: 3, x0: 0, y0: 0, x1: 10, y1: 10 }], flags: [] },
        { number: 2, question_rects: [{ page: 3, x0: 0, y0: 0, x1: 10, y1: 10 }], answer_rects: [], flags: ['pixel_ink'] },
      ],
      orphan_answers: [], warnings: [],
    }],
    unrouted: [{ label: 'q2', status: 'not_routed', first_page: 12, last_page: 21, reason: 'a scanned paper needs OCR' }],
    warnings: [],
  },
}

function Where() {
  return <div data-testid="where">{useLocation().pathname}</div>
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/admin/import/jobs/j1/review']}>
      <Routes>
        <Route path="/admin/import/jobs/:jobId/review" element={<ReviewPage />} />
        <Route path="/admin/import" element={<Where />} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  sessionStorage.clear()
  api.import.review.mockResolvedValue(REVIEW)
})

describe('ReviewPage', () => {
  it('draws the question rectangle scaled to pixels and lists questions with flags', async () => {
    renderPage()
    expect(await screen.findByAltText('Page 2')).toHaveAttribute('src', 'https://s3/p2.webp')
    const rect = screen.getByTestId('overlay').querySelector('g[data-kind="question"] rect')
    expect(rect).toHaveAttribute('x', '20')
    expect(rect).toHaveAttribute('width', '100')
    expect(screen.getByTestId('overlay')).toHaveAttribute('viewBox', '0 0 200 400')
    const list = screen.getByRole('complementary', { name: 'Questions' })
    expect(within(list).getByText('pixel_ink')).toBeInTheDocument()
    expect(within(list).getByRole('button', { name: /Question 2/ })).toHaveAttribute('data-flagged', 'true')
  })

  it('highlights flagged pages and jumps to a question\'s page', async () => {
    renderPage()
    await screen.findByAltText('Page 2')
    const strip = screen.getByRole('navigation', { name: 'Pages' })
    expect(within(strip).getByTitle('dense')).toHaveAttribute('data-flagged', 'true')
    await userEvent.click(screen.getByRole('button', { name: /Question 2/ }))
    expect(await screen.findByAltText('Page 3')).toBeInTheDocument()
    expect(screen.getByText(/Page 3 needs review: dense/)).toBeInTheDocument()
  })

  it('shows the unrouted reason and opens the manual flow on its page range', async () => {
    api.import.manualPages.mockResolvedValue({
      pages: [{ temp_key: 'tmp/x/page_0.webp', url: 'u', dimensions: { width: 1, height: 2 } }],
      suggested_metadata: { year: 2024, paper_number: '1', school_id: 3 },
    })
    renderPage()
    expect(await screen.findByText(/a scanned paper needs OCR/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Handle manually' }))
    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent('/admin/import'))
    expect(api.import.manualPages).toHaveBeenCalledWith('j1', 12, 21)
    const session = JSON.parse(sessionStorage.getItem('pillora_import_session'))
    expect(session.step).toBe('review')
    expect(session.pages[0].mergeWithPrev).toBe(false)
    expect(session.metadata).toMatchObject({ year: '2024', paper_number: '1', school_id: 3 })
  })

  it('shows a paper without questions', async () => {
    api.import.review.mockResolvedValue({
      ...REVIEW,
      proposal: { ...REVIEW.proposal, papers: [{ ...REVIEW.proposal.papers[0], questions: [], orphan_answers: [{ page: 2, x0: 0, y0: 0, x1: 5, y1: 5 }] }] },
    })
    renderPage()
    expect(await screen.findByText('No questions were found for this paper.')).toBeInTheDocument()
    expect(screen.getByText(/not matched to a question/)).toBeInTheDocument()
  })

  it('shows an error when the review cannot load', async () => {
    api.import.review.mockRejectedValue({ message: 'This job has no proposal to review yet' })
    renderPage()
    expect(await screen.findByText('This job has no proposal to review yet')).toBeInTheDocument()
  })

  describe('editing', () => {
    beforeEach(() => {
      api.import.saveProposal.mockResolvedValue({ saved: true })
    })

    it('deletes the selected rectangle with the keyboard and saves once, debounced', async () => {
      renderPage()
      await screen.findByAltText('Page 2')
      const rect = document.querySelector('g[data-kind="question"] rect')
      await userEvent.click(rect)
      await userEvent.keyboard('{Delete}')
      // Question 1 lost its only rectangle, so it is gone and its answer is unmatched.
      expect(screen.queryByText('Question 1')).toBeNull()
      expect(screen.getByRole('status')).toHaveTextContent('Saving')
      expect(api.import.saveProposal).not.toHaveBeenCalled()
      await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Saved'), { timeout: 3000 })
      expect(api.import.saveProposal).toHaveBeenCalledTimes(1)
      const [id, body] = api.import.saveProposal.mock.calls[0]
      expect(id).toBe('j1')
      expect(body.papers[0].questions.map(q => q.number)).toEqual([2])
      expect(body.papers[0].orphan_answers).toHaveLength(1)
      expect(body.papers[0]).not.toHaveProperty('pages')
    })

    it('does not delete while typing in a number field', async () => {
      renderPage()
      await screen.findByAltText('Page 2')
      await userEvent.click(document.querySelector('g[data-kind="question"] rect'))
      await userEvent.click(screen.getByLabelText('Number of question 2'))
      await userEvent.keyboard('{Backspace}')
      expect(screen.getByText('Question 1')).toBeInTheDocument()
    })

    it('renumbers a question and refuses a duplicate number', async () => {
      renderPage()
      await screen.findByAltText('Page 2')
      const field = screen.getByLabelText('Number of question 2')
      fireEvent.change(field, { target: { value: '1' } })
      await userEvent.type(field, '{Enter}')
      expect(screen.getByRole('alert')).toHaveTextContent('Question 1 already exists')
      fireEvent.change(field, { target: { value: '5' } })
      await userEvent.type(field, '{Enter}')
      expect(screen.getByText('Question 5')).toBeInTheDocument()
      await waitFor(() => expect(api.import.saveProposal).toHaveBeenCalled(), { timeout: 3000 })
      expect(api.import.saveProposal.mock.calls[0][1].papers[0].questions[1].number).toBe(5)
    })

    it('merges a question with the previous one', async () => {
      renderPage()
      await screen.findByAltText('Page 2')
      await userEvent.click(screen.getByRole('button', { name: /Question 2/ }))
      await userEvent.click(screen.getByRole('button', { name: 'Merge with previous' }))
      expect(screen.queryByText('Question 2')).toBeNull()
      await waitFor(() => expect(api.import.saveProposal).toHaveBeenCalled(), { timeout: 3000 })
      expect(api.import.saveProposal.mock.calls[0][1].papers[0].questions[0].question_rects).toHaveLength(2)
    })

    it('splits a question through its rectangle', async () => {
      renderPage()
      await screen.findByAltText('Page 2')
      await userEvent.click(screen.getByRole('button', { name: /Question 1/ }))
      await userEvent.click(screen.getByRole('button', { name: 'Split selected rectangle in half' }))
      expect(screen.getAllByText(/^Question \d$/)).toHaveLength(3)
    })

    it('shows the server message when a save is rejected', async () => {
      api.import.saveProposal.mockRejectedValue({ message: 'a rectangle lies outside page 2' })
      renderPage()
      await screen.findByAltText('Page 2')
      await userEvent.click(screen.getByRole('button', { name: /Page 3 thumbnail/ }))
      await userEvent.click(document.querySelector('g[data-kind="answer"] rect'))
      await userEvent.keyboard('{Delete}')
      await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Not saved'), { timeout: 3000 })
      expect(screen.getByText('a rectangle lies outside page 2')).toBeInTheDocument()
    })
  })
})
