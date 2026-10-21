import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Outlet, Route, Routes, useLocation } from 'react-router-dom'
import ReviewPage from './ReviewPage'
import { api } from '../../api/client'

vi.mock('../../api/client', () => ({
  api: {
    import: {
      review: vi.fn(), savePaperMetadata: vi.fn(), manualPages: vi.fn(), saveProposal: vi.fn(),
      confirmJobPaper: vi.fn(), skipJobPaper: vi.fn(), attachJobPaper: vi.fn(), pendingPapers: vi.fn(), matchJobPaper: vi.fn(), unmatchJobPaper: vi.fn(), rejectProposedPaper: vi.fn(), aiTopicsForQuestion: vi.fn(), saveTopics: vi.fn(),
    },
    subjects: { list: vi.fn() }, streams: { list: vi.fn() }, levels: { list: vi.fn() },
    schools: { list: vi.fn() }, examTypes: { list: vi.fn() }, schoolLevels: { list: vi.fn() },
    topics: { list: vi.fn() }, papers: { get: vi.fn(), list: vi.fn() },
  },
}))

// jsdom has no PointerEvent; without one fireEvent.pointer* drops clientX/clientY.
if (!window.PointerEvent) {
  window.PointerEvent = class PointerEvent extends MouseEvent {
    constructor(type, init = {}) {
      super(type, init)
      this.pointerId = init.pointerId ?? 0
    }
  }
}

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

// `reviewQueue` stands in for the import layout's polled queue (its outlet context).
function renderPage(reviewQueue) {
  const page = <Route path="/admin/import/jobs/:jobId/review" element={<ReviewPage />} />
  return render(
    <MemoryRouter initialEntries={['/admin/import/jobs/j1/review']}>
      <Routes>
        {reviewQueue ? <Route element={<Outlet context={{ reviewQueue }} />}>{page}</Route> : page}
        <Route path="/admin/import/jobs/:jobId/review" element={<ReviewPage />} />
        <Route path="/admin/import/manual" element={<Where />} />
        <Route path="/admin/import/review" element={<Where />} />
        <Route path="/admin/import/jobs/j7/review" element={<Where />} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  sessionStorage.clear()
  api.import.review.mockResolvedValue(REVIEW)
  api.subjects.list.mockResolvedValue([{ id: 1, name: 'Math' }])
  api.streams.list.mockResolvedValue([{ id: 2, name: 'G3' }])
  api.levels.list.mockResolvedValue([{ id: 3, name: 'Sec 3', school_level_id: 9 }])
  api.schools.list.mockResolvedValue([{ id: 4, name: 'RI' }])
  api.examTypes.list.mockResolvedValue([{ id: 5, name: 'EOY' }])
  api.schoolLevels.list.mockResolvedValue([{ id: 9, name: 'Secondary' }])
  api.topics.list.mockResolvedValue([])
  api.papers.list.mockResolvedValue({ total: 0, items: [] })
  api.import.pendingPapers.mockResolvedValue([])
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
    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent('/admin/import/manual'))
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

    // The overlay shows the 200x400 px page image at 1:1, so 2 px = 1 pt.
    const overlayAtOneToOne = () => {
      const svg = screen.getByTestId('overlay')
      svg.getBoundingClientRect = () => ({ left: 0, top: 0, width: 200, height: 400, right: 200, bottom: 400 })
      return svg
    }
    const lastSaved = async () => {
      await waitFor(() => expect(api.import.saveProposal).toHaveBeenCalled(), { timeout: 3000 })
      return api.import.saveProposal.mock.calls.at(-1)[1].papers[0]
    }

    it('draws a box that becomes a new question when none is selected', async () => {
      renderPage()
      await screen.findByAltText('Page 2')
      await userEvent.click(screen.getByRole('button', { name: 'Draw question box' }))
      expect(screen.getByRole('status')).toHaveTextContent('It becomes a new question.')
      const svg = overlayAtOneToOne()
      fireEvent.pointerDown(svg, { clientX: 120, clientY: 380, pointerId: 1 })
      fireEvent.pointerMove(svg, { clientX: 20, clientY: 300, pointerId: 1 })
      expect(screen.getByTestId('draft-rect')).toBeInTheDocument()
      fireEvent.pointerUp(svg, { clientX: 20, clientY: 300, pointerId: 1 })
      expect(screen.getByText('Question 3')).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Draw question box' })).toHaveAttribute('aria-pressed', 'false')
      const saved = await lastSaved()
      expect(saved.questions[2]).toEqual({
        number: 3, question_rects: [{ page: 2, x0: 10, y0: 150, x1: 60, y1: 190 }], answer_rects: [], flags: [],
      })
    })

    it('draws an answer box onto the selected question', async () => {
      renderPage()
      await screen.findByAltText('Page 2')
      await userEvent.click(screen.getByText('Question 2'))
      await userEvent.click(screen.getByRole('button', { name: 'Draw answer box' }))
      expect(screen.getByRole('status')).toHaveTextContent('It is added to the answers of question 2.')
      const svg = overlayAtOneToOne()
      fireEvent.pointerDown(svg, { clientX: 0, clientY: 200, pointerId: 1 })
      fireEvent.pointerMove(svg, { clientX: 100, clientY: 260, pointerId: 1 })
      fireEvent.pointerUp(svg, { clientX: 100, clientY: 260, pointerId: 1 })
      const saved = await lastSaved()
      expect(saved.questions[1].answer_rects).toEqual([{ page: 3, x0: 0, y0: 100, x1: 50, y1: 130 }])
    })

    it('drags the selected box to move it', async () => {
      renderPage()
      await screen.findByAltText('Page 2')
      await userEvent.click(document.querySelector('g[data-kind="question"] rect'))
      overlayAtOneToOne()
      const rect = screen.getByTestId('selected-rect')
      fireEvent.pointerDown(rect, { clientX: 40, clientY: 60, pointerId: 1 })
      fireEvent.pointerMove(rect, { clientX: 60, clientY: 100, pointerId: 1 })
      fireEvent.pointerUp(rect, { clientX: 60, clientY: 100, pointerId: 1 })
      expect(screen.getByTestId('selected-rect')).toHaveAttribute('x', '40')
      const saved = await lastSaved()
      expect(saved.questions[0].question_rects[0]).toEqual({ page: 2, x0: 20, y0: 40, x1: 70, y1: 140 })
    })

    it('moves an answer box to another question or leaves it unmatched', async () => {
      renderPage()
      await screen.findByAltText('Page 2')
      await userEvent.click(screen.getByRole('button', { name: /p3/ }))
      await userEvent.click(document.querySelector('g[data-kind="answer"] rect'))
      const panel = screen.getByRole('region', { name: 'Selected box' })
      expect(panel).toHaveTextContent('Answer box of question 1')
      await userEvent.selectOptions(within(panel).getByLabelText('Assign answer box to question'), 'Question 2')
      expect(screen.getByRole('region', { name: 'Selected box' })).toHaveTextContent('Answer box of question 2')
      await userEvent.selectOptions(screen.getByLabelText('Assign answer box to question'), 'No question (not imported)')
      expect(screen.getByText(/1 answer rectangle not matched to a question/)).toBeInTheDocument()
      const saved = await lastSaved()
      expect(saved.questions.map(q => q.answer_rects.length)).toEqual([0, 0])
      expect(saved.orphan_answers).toHaveLength(1)
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

  describe('confirming', () => {
    const FILLED = { subject_id: 1, stream_id: 2, level_id: 3, school_id: 4, exam_type_id: 5, year: 2024, paper_number: '1' }
    const TWO = {
      ...REVIEW,
      filename_metadata: FILLED,
      proposal: {
        ...REVIEW.proposal,
        papers: [
          { ...REVIEW.proposal.papers[0], key: 'q1', outcome: null },
          { ...REVIEW.proposal.papers[0], label: 'q2', answer_label: 'a2', key: 'q2', outcome: null },
        ],
      },
    }

    it('pre-fills the sidebar from the filename and confirms the paper, then shows topic review', async () => {
      api.import.review.mockResolvedValue(TWO)
      api.import.confirmJobPaper.mockResolvedValue({
        paper_id: 7, job_status: 'review_ready',
        questions: [{ id: 70, question_number: 1, pages: [] }],
      })
      api.import.aiTopicsForQuestion.mockResolvedValue({ parts: [] })
      renderPage()
      await screen.findByAltText('Page 2')
      const button = await screen.findByRole('button', { name: /Confirm paper/ })
      await waitFor(() => expect(button).toBeEnabled())
      await userEvent.click(button)
      expect(api.import.confirmJobPaper).toHaveBeenCalledWith('j1', {
        paper_label: 'q1', ...FILLED, year: 2024, paper_number: '1', is_premium: true,
      })
      expect(await screen.findByRole('button', { name: /Confirm & Save Topics/ })).toBeInTheDocument()
    })

    it('shows the linked answer job as a banner and what a confirm attached', async () => {
      api.import.review.mockResolvedValue({ ...TWO, matches: { q1: { filename: 'answers.pdf', paper_key: 'a1', job_id: 'j2' } } })
      api.import.confirmJobPaper.mockResolvedValue({
        paper_id: 7, job_status: 'review_ready', questions: [],
        answers_from: { job_id: 'j2', filename: 'answers.pdf', paper_key: 'a1', attached: [1, 2] }, unmatched: [9],
      })
      renderPage()
      expect(await screen.findByText(/Answers available from answers\.pdf \(a1\) — they will be attached when you confirm/)).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Unmatch' })).toBeInTheDocument()
      const button = await screen.findByRole('button', { name: /Confirm paper/ })
      await waitFor(() => expect(button).toBeEnabled())
      await userEvent.click(button)
      expect(await screen.findByText(/Attached answers for questions 1, 2 from answers\.pdf \(a1\)/)).toBeInTheDocument()
      expect(screen.getByText(/Answers for question 9 matched no question/)).toBeInTheDocument()
    })

    it('unmatches the linked answer job and shows whatever matching finds next', async () => {
      api.import.review.mockResolvedValue({ ...TWO, matches: { q1: { filename: 'answers.pdf', paper_key: 'a1', job_id: 'j2' } } })
      api.import.unmatchJobPaper.mockResolvedValue({ matches: { filename: 'other.pdf', paper_key: 'a1', job_id: 'j3' }, proposal: null })
      renderPage()
      await userEvent.click(await screen.findByRole('button', { name: 'Unmatch' }))
      expect(api.import.unmatchJobPaper).toHaveBeenCalledWith('j1', 'q1')
      expect(await screen.findByText(/Answers available from other\.pdf \(a1\)/)).toBeInTheDocument()
      expect(screen.queryByText(/answers\.pdf/)).not.toBeInTheDocument()
    })

    it('pre-fills each paper from its own cover metadata, not the filename', async () => {
      const q1 = { subject_id: 1, stream_id: 2, level_id: 3, school_id: 4, exam_type_id: 5, year: 2024, paper_number: '1' }
      const q2 = { ...q1, stream_id: 9, year: 2023, paper_number: '2' }
      api.import.review.mockResolvedValue({ ...TWO, filename_metadata: {}, paper_metadata: { q1, q2 } })
      api.import.confirmJobPaper.mockResolvedValue({ paper_id: 7, job_status: 'review_ready', questions: [] })
      renderPage()
      await screen.findByAltText('Page 2')
      await userEvent.click(screen.getByRole('tab', { name: /q2 \/ a2/ }))
      const button = await screen.findByRole('button', { name: /Confirm paper/ })
      await waitFor(() => expect(button).toBeEnabled())
      await userEvent.click(button)
      expect(api.import.confirmJobPaper).toHaveBeenCalledWith('j1', {
        paper_label: 'q2', ...q2, year: 2023, paper_number: '2', is_premium: true,
      })
    })

    it('holds confirm while the school read from the cover is not in the list, until one is picked', async () => {
      const extracted = { school: 'Raffles Instn', subject: null, level: null, stream: null, exam_type: null }
      api.import.review.mockResolvedValue({
        ...TWO, filename_metadata: {}, paper_metadata: { q1: { ...FILLED, school_id: null, extracted } },
      })
      renderPage()
      const button = await screen.findByRole('button', { name: /Confirm paper/ })
      const school = await screen.findByRole('combobox', { name: 'School' })
      expect(screen.getByText(/— not in the list/)).toHaveTextContent('Raffles Instn — not in the list')
      expect(button).toBeDisabled()
      expect(screen.getByText(/Pick a school: “Raffles Instn” is not in the list/)).toBeInTheDocument()
      await userEvent.click(school)
      await userEvent.click(screen.getByRole('option', { name: 'RI' }))
      expect(button).toBeEnabled()
      expect(screen.queryByText(/Pick a school/)).not.toBeInTheDocument()
    })

    it('an old job without the names read shows the school as before', async () => {
      api.import.review.mockResolvedValue({ ...TWO, filename_metadata: {}, paper_metadata: { q1: FILLED } })
      renderPage()
      expect(await screen.findByRole('combobox', { name: 'School' })).toHaveValue('RI')
      expect(screen.queryByText(/— not in the list/)).not.toBeInTheDocument()
      await waitFor(() => expect(screen.getByRole('button', { name: /Confirm paper/ })).toBeEnabled())
    })

    it('mirrors sidebar edits to the server, debounced', async () => {
      api.import.review.mockResolvedValue({ ...TWO, filename_metadata: {}, paper_metadata: { q1: FILLED } })
      api.import.savePaperMetadata.mockResolvedValue({ saved: true })
      renderPage()
      await screen.findByAltText('Page 2')
      const paperNo = await screen.findByPlaceholderText('1')
      fireEvent.change(paperNo, { target: { value: '2' } })
      expect(api.import.savePaperMetadata).not.toHaveBeenCalled()
      await waitFor(() => expect(api.import.savePaperMetadata).toHaveBeenCalledTimes(1), { timeout: 3000 })
      expect(api.import.savePaperMetadata).toHaveBeenCalledWith('j1', 'q1', { ...FILLED, paper_number: '2' })
    })

    it('skipping the last undecided paper leaves for the review queue', async () => {
      api.import.review.mockResolvedValue({
        ...TWO,
        proposal: { ...TWO.proposal, papers: [{ ...TWO.proposal.papers[0], outcome: 'confirmed' }, TWO.proposal.papers[1]] },
      })
      api.import.skipJobPaper.mockResolvedValue({ job_status: 'confirmed' })
      vi.spyOn(window, 'confirm').mockReturnValue(true)
      renderPage()
      // Opens on the first undecided paper, q2 / a2.
      await screen.findByAltText('Page 2')
      expect(screen.getByRole('tab', { name: /q1 \/ a1/ })).toHaveTextContent('(confirmed)')
      await userEvent.click(screen.getByRole('button', { name: 'Skip this paper' }))
      await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent('/admin/import/review'))
      expect(api.import.skipJobPaper).toHaveBeenCalledWith('j1', 'q2')
    })

    it('settling the job moves on to the oldest other job in the review queue', async () => {
      api.import.review.mockResolvedValue({
        ...TWO,
        proposal: { ...TWO.proposal, papers: [{ ...TWO.proposal.papers[0], outcome: 'confirmed' }, TWO.proposal.papers[1]] },
      })
      api.import.skipJobPaper.mockResolvedValue({ job_status: 'confirmed' })
      vi.spyOn(window, 'confirm').mockReturnValue(true)
      const refresh = vi.fn()
      renderPage({
        refresh,
        jobs: [
          { id: 'j1', filename: 'scan.pdf', created_at: '2026-10-01T00:00:00Z' },
          { id: 'j8', filename: 'newer.pdf', created_at: '2026-10-09T00:00:00Z' },
          { id: 'j7', filename: 'older.pdf', created_at: '2026-10-02T00:00:00Z' },
        ],
      })
      await screen.findByAltText('Page 2')
      expect(screen.getByRole('link', { name: /Next job: older.pdf/ })).toHaveAttribute('href', '/admin/import/jobs/j7/review')
      await userEvent.click(screen.getByRole('button', { name: 'Skip this paper' }))
      await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent('/admin/import/jobs/j7/review'))
      expect(refresh).toHaveBeenCalled()
    })

    it('warns, without blocking confirm, when the paper would be confirmed partly answered', async () => {
      api.import.review.mockResolvedValue(TWO)  // question 1 has an answer box, question 2 none
      api.import.confirmJobPaper.mockResolvedValue({ paper_id: 7, job_status: 'review_ready', questions: [] })
      renderPage()
      expect(await screen.findByText(/Q2 has no answers/)).toHaveTextContent(/answer-box editor, or confirm anyway/)
      const button = await screen.findByRole('button', { name: /Confirm paper/ })
      await waitFor(() => expect(button).toBeEnabled())
      await userEvent.click(button)
      expect(api.import.confirmJobPaper).toHaveBeenCalled()
    })

    it('counts a linked answer paper\'s answers in the warning', async () => {
      const linked = { filename: 'answers.pdf', paper_key: 'a1', job_id: 'j2' }
      api.import.review.mockResolvedValue({ ...TWO, matches: { q1: { ...linked, answer_numbers: [2] } } })
      const first = renderPage()
      await screen.findByText(/Answers available from answers\.pdf/)
      expect(screen.queryByText(/has no answers/)).not.toBeInTheDocument()
      first.unmount()
      const none = q => ({ ...q, answer_rects: [] })
      const bare = { ...TWO.proposal.papers[0], questions: TWO.proposal.papers[0].questions.map(none) }
      api.import.review.mockResolvedValue({
        ...TWO, proposal: { ...TWO.proposal, papers: [bare] }, matches: { q1: { ...linked, answer_numbers: [1, 7] } },
      })
      renderPage()
      expect(await screen.findByText(/Q2 has no answers/)).toBeInTheDocument()
    })

    it('does not warn about a question paper with no answers at all', async () => {
      const none = q => ({ ...q, answer_rects: [] })
      const bare = { ...TWO.proposal.papers[0], questions: TWO.proposal.papers[0].questions.map(none) }
      api.import.review.mockResolvedValue({ ...TWO, proposal: { ...TWO.proposal, papers: [bare] } })
      renderPage()
      await screen.findByRole('button', { name: /Confirm paper/ })
      expect(screen.queryByText(/have no answers|has no answers/)).not.toBeInTheDocument()
    })

    it('shows the server error when a confirm is refused', async () => {
      api.import.review.mockResolvedValue(TWO)
      api.import.confirmJobPaper.mockRejectedValue({ message: 'Paper q1 was already confirmed' })
      renderPage()
      await screen.findByAltText('Page 2')
      const button = await screen.findByRole('button', { name: /Confirm paper/ })
      await waitFor(() => expect(button).toBeEnabled())
      await userEvent.click(button)
      expect(await screen.findByText('Paper q1 was already confirmed')).toBeInTheDocument()
    })
  })
  describe('an answer-only paper', () => {
    const ANSWERS = {
      ...REVIEW,
      proposal: {
        ...REVIEW.proposal,
        papers: [{
          label: null, role: 'answer_only', answer_label: 'a1', key: 'a1',
          pages: [page(2)],
          questions: [
            { number: 1, question_rects: [], answer_rects: [{ page: 2, x0: 10, y0: 20, x1: 60, y1: 120 }], flags: [] },
            { number: 2, question_rects: [], answer_rects: [{ page: 2, x0: 10, y0: 120, x1: 60, y1: 180 }], flags: [] },
          ],
          orphan_answers: [], warnings: [],
        }],
      },
    }

    it('lists answers by question number and offers "Attach to paper..." (needs a paper id) instead of Confirm', async () => {
      api.import.review.mockResolvedValue(ANSWERS)
      renderPage()
      await screen.findByAltText('Page 2')
      const list = screen.getByRole('complementary', { name: 'Questions' })
      expect(within(list).getByText('Answer 1')).toBeInTheDocument()
      expect(within(list).getByText('Answer 2')).toBeInTheDocument()
      expect(screen.queryByRole('button', { name: /Confirm paper/ })).not.toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Attach to paper…' })).toBeDisabled()
      await userEvent.type(screen.getByLabelText('Paper id'), '7')
      expect(screen.getByRole('button', { name: 'Attach to paper…' })).toBeEnabled()
      expect(screen.getByRole('button', { name: 'Skip this paper' })).toBeEnabled()
    })

    it('attaches without a prompt when no target question has answers, and shows unmatched numbers', async () => {
      api.import.review.mockResolvedValue(ANSWERS)
      api.papers.get.mockResolvedValue({ questions: [{ question_number: 1, pages: [{ page_type: 'question' }] }] })
      api.import.attachJobPaper.mockResolvedValue({ attached: [1], unmatched: [2], modes: { 1: 'replace' }, job_status: 'confirmed' })
      renderPage()
      await screen.findByAltText('Page 2')
      await userEvent.type(screen.getByLabelText('Paper id'), '7')
      await userEvent.click(screen.getByRole('button', { name: 'Attach to paper…' }))
      expect(await screen.findByText(/Not attached.*: 2\./)).toBeInTheDocument()
      expect(api.import.attachJobPaper).toHaveBeenCalledWith('j1', { key: 'a1', paper_id: 7 })
    })

    it('shows a proposed paper and attaches to it with one click', async () => {
      const paper = { id: 9, school: 'Raffles', year: 2024, level: 'Sec 3', subject: 'Math', paper_number: '1' }
      api.import.review.mockResolvedValue({ ...ANSWERS, proposals: { a1: { status: 'proposed', note: null, paper } } })
      api.papers.get.mockResolvedValue({ questions: [{ question_number: 1, pages: [{ page_type: 'question' }] }] })
      api.import.attachJobPaper.mockResolvedValue({ attached: [1], unmatched: [], modes: {}, job_status: 'confirmed' })
      renderPage()
      expect(await screen.findByText(/Answers match Raffles 2024 Sec 3 Math Paper 1/)).toBeInTheDocument()
      await userEvent.click(screen.getByRole('button', { name: 'Attach' }))
      await waitFor(() => expect(api.import.attachJobPaper).toHaveBeenCalledWith('j1', { key: 'a1', paper_id: 9 }))
    })

    it('asks append or replace on a proposed paper whose questions already have answers', async () => {
      const paper = { id: 9, school: 'Raffles', year: 2024, level: 'Sec 3', subject: 'Math', paper_number: '1' }
      api.import.review.mockResolvedValue({ ...ANSWERS, proposals: { a1: { status: 'proposed', note: null, paper } } })
      api.papers.get.mockResolvedValue({ questions: [{ question_number: 1, pages: [{ page_type: 'answer' }] }] })
      renderPage()
      await userEvent.click(await screen.findByRole('button', { name: 'Attach' }))
      expect(await screen.findByLabelText('Add to the existing answers')).toBeChecked()
      expect(api.import.attachJobPaper).not.toHaveBeenCalled()
    })

    it('dismisses a wrong proposed paper with "Not this one" and shows what matching finds next', async () => {
      const paper = { id: 9, school: 'Raffles', year: 2024, level: 'Sec 3', subject: 'Math', paper_number: '1' }
      api.import.review.mockResolvedValue({ ...ANSWERS, proposals: { a1: { status: 'proposed', note: null, paper } } })
      api.import.rejectProposedPaper.mockResolvedValue({
        matches: null, proposal: { status: 'proposed', note: null, paper: { ...paper, id: 12, year: 2023 } },
      })
      renderPage()
      expect(await screen.findByText(/Answers match Raffles 2024 Sec 3 Math Paper 1/)).toBeInTheDocument()
      await userEvent.click(screen.getByRole('button', { name: 'Not this one' }))
      expect(api.import.rejectProposedPaper).toHaveBeenCalledWith('j1', 'a1')
      expect(await screen.findByText(/Answers match Raffles 2023 Sec 3 Math Paper 1 \(paper 12\)/)).toBeInTheDocument()
      expect(api.import.attachJobPaper).not.toHaveBeenCalled()
    })

    it('can be linked by "Not this one" falling through to a pending question paper', async () => {
      const paper = { id: 9, school: 'Raffles', year: 2024, level: 'Sec 3', subject: 'Math', paper_number: '1' }
      api.import.review.mockResolvedValue({ ...ANSWERS, proposals: { a1: { status: 'proposed', note: null, paper } } })
      api.import.rejectProposedPaper.mockResolvedValue({ matches: { filename: 'questions.pdf', paper_key: 'q1' }, proposal: null })
      renderPage()
      await userEvent.click(await screen.findByRole('button', { name: 'Not this one' }))
      expect(await screen.findByText(/Linked to questions\.pdf q1/)).toBeInTheDocument()
      expect(screen.queryByText(/Answers match/)).not.toBeInTheDocument()
    })

    it('hints at manual matching when several or only partial papers match', async () => {
      api.import.review.mockResolvedValue({ ...ANSWERS, proposals: { a1: { status: 'manual', note: 'partial: year differ', paper: null } } })
      renderPage()
      expect(await screen.findByText(/Partial: year differ\. Several or partial matches — pick one below/)).toBeInTheDocument()
      expect(screen.queryByRole('button', { name: 'Attach' })).not.toBeInTheDocument()
    })

    it('asks append or replace (default append) when a target question already has answers', async () => {
      api.import.review.mockResolvedValue(ANSWERS)
      api.papers.get.mockResolvedValue({ questions: [{ question_number: 1, pages: [{ page_type: 'answer' }] }] })
      api.import.attachJobPaper.mockResolvedValue({ attached: [1, 2], unmatched: [], modes: {}, job_status: 'confirmed' })
      renderPage()
      await screen.findByAltText('Page 2')
      await userEvent.type(screen.getByLabelText('Paper id'), '7')
      await userEvent.click(screen.getByRole('button', { name: 'Attach to paper…' }))
      expect(api.import.attachJobPaper).not.toHaveBeenCalled()
      expect(await screen.findByLabelText('Add to the existing answers')).toBeChecked()
      await userEvent.click(screen.getByLabelText('Replace the existing answers'))
      await userEvent.click(screen.getByRole('button', { name: 'Attach answers' }))
      await waitFor(() => expect(api.import.attachJobPaper).toHaveBeenCalledWith('j1', { key: 'a1', paper_id: 7, mode: 'replace' }))
    })

    describe('Match to paper', () => {
      const META = { subject_id: 1, stream_id: 2, level_id: 3, school_id: 4, exam_type_id: 5, year: 2024, paper_number: '1' }
      const CONFIRMED = { id: 7, year: 2024, paper_number: '1', school_name: 'RI', level_name: 'Sec 3', subject_name: 'Math' }
      const PENDING = {
        ingest_paper_id: 31, job_id: 'j2', filename: 'questions.pdf', paper_key: 'q1', metadata: META,
        preview: {
          url: 'https://s3/other-p3.webp', number: 1,
          page: { page: 3, width_pt: 100, height_pt: 200, width_px: 200, height_px: 400 },
          rect: { page: 3, x0: 10, y0: 20, x1: 60, y1: 120 },
        },
      }
      const withMeta = () => api.import.review.mockResolvedValue({ ...ANSWERS, paper_metadata: { a1: META } })

      it('lists confirmed and pending candidates for the pre-filled metadata filters', async () => {
        withMeta()
        api.papers.list.mockResolvedValue({ total: 1, items: [CONFIRMED, { ...CONFIRMED, id: 8, paper_number: '2' }] })
        api.import.pendingPapers.mockResolvedValue([PENDING])
        renderPage()
        const list = await screen.findByRole('region', { name: 'Candidates' })
        expect(await within(list).findByText('Paper 7')).toBeInTheDocument()
        expect(within(list).queryByText('Paper 8')).not.toBeInTheDocument() // other paper number
        expect(within(list).getByText('Pending: questions.pdf')).toBeInTheDocument()
        expect(api.papers.list).toHaveBeenLastCalledWith(expect.objectContaining({
          subject_id: 1, stream_id: 2, level_id: 3, school_id: 4, exam_type_id: 5, year: '2024',
        }))
        expect(api.import.pendingPapers).toHaveBeenLastCalledWith(expect.objectContaining({ subject_id: 1, year: '2024', paper_number: '1', exclude_job_id: 'j1' }))
      })

      it('previews the candidate first question beside this paper first answer, and attaches', async () => {
        withMeta()
        api.papers.list.mockResolvedValue({ total: 1, items: [CONFIRMED] })
        api.papers.get.mockResolvedValue({
          questions: [{ question_number: 1, pages: [{ page_type: 'question', page_order: 1, url: 'https://s3/q1.webp' }] }],
        })
        api.import.attachJobPaper.mockResolvedValue({ attached: [1], unmatched: [], modes: {}, job_status: 'review_ready' })
        renderPage()
        await userEvent.click(await screen.findByText('Paper 7'))
        const preview = await screen.findByRole('region', { name: 'Preview' })
        expect(await within(preview).findByAltText('Candidate first question')).toHaveAttribute('src', 'https://s3/q1.webp')
        expect(within(preview).getByAltText("This paper's first answer")).toHaveAttribute('src', 'https://s3/p2.webp')
        expect(screen.getByLabelText('Paper id')).toHaveValue(7)
        await userEvent.click(screen.getByRole('button', { name: 'Attach to paper…' }))
        await waitFor(() => expect(api.import.attachJobPaper).toHaveBeenCalledWith('j1', { key: 'a1', paper_id: 7 }))
        expect(await screen.findByText(/Attached answers for question 1 to paper 7/)).toBeInTheDocument()
      })

      it('previews a pending question paper from its review page image and links instead of attaching', async () => {
        withMeta()
        api.import.pendingPapers.mockResolvedValue([PENDING])
        api.import.matchJobPaper.mockResolvedValue({ matches: { filename: 'questions.pdf', paper_key: 'q1', ingest_paper_id: 31, job_id: 'j2' } })
        api.import.unmatchJobPaper.mockResolvedValue({ matches: null, proposal: null })
        renderPage()
        await userEvent.click(await screen.findByText('Pending: questions.pdf'))
        const preview = await screen.findByRole('region', { name: 'Preview' })
        expect(within(preview).getByAltText('Candidate first question')).toHaveAttribute('src', 'https://s3/other-p3.webp')
        expect(screen.queryByRole('button', { name: 'Attach to paper…' })).not.toBeInTheDocument()
        await userEvent.click(screen.getByRole('button', { name: 'Link to this paper' }))
        expect(api.import.matchJobPaper).toHaveBeenCalledWith('j1', 'a1', 31)
        expect(await screen.findByText(/Linked to questions\.pdf q1/)).toBeInTheDocument()
        await userEvent.click(screen.getByRole('button', { name: 'Unmatch' }))
        expect(api.import.unmatchJobPaper).toHaveBeenCalledWith('j1', 'a1')
        await waitFor(() => expect(screen.queryByText(/Linked to questions\.pdf/)).not.toBeInTheDocument())
      })

      it('shows an existing link on load', async () => {
        api.import.review.mockResolvedValue({ ...ANSWERS, matches: { a1: { filename: 'questions.pdf', paper_key: 'q1' } } })
        renderPage()
        expect(await screen.findByText(/Linked to questions\.pdf q1/)).toBeInTheDocument()
      })
    })
  })
})
