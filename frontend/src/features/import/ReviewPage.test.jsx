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
      confirmJobPaper: vi.fn(), skipJobPaper: vi.fn(), attachJobPaper: vi.fn(), paperCandidates: vi.fn(), matchJobPaper: vi.fn(), unmatchJobPaper: vi.fn(), rejectProposedPaper: vi.fn(), answerMappingTable: vi.fn(), aiTopicsForQuestion: vi.fn(), saveTopics: vi.fn(),
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
  api.import.paperCandidates.mockResolvedValue({ exact: [], best: [] })
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

  it('lists the pages the pipeline left out, greyed with why, and opens on the first question', async () => {
    const [p] = REVIEW.proposal.papers
    api.import.review.mockResolvedValue({
      ...REVIEW,
      proposal: { ...REVIEW.proposal, papers: [{ ...p, pages: [page(1, { excluded_reason: 'cover page' }), ...p.pages] }] },
    })
    renderPage()
    expect(await screen.findByAltText('Page 2')).toBeInTheDocument()  // not the cover
    const cover = screen.getByRole('button', { name: /p1/ })
    expect(cover).toHaveAttribute('data-excluded', 'true')
    expect(cover).toHaveAttribute('title', 'cover page')
    expect(cover).toHaveTextContent('cover page')
    expect(screen.queryByText(/Not used by the pipeline/)).not.toBeInTheDocument()
    await userEvent.click(cover)
    expect(screen.getByAltText('Page 1')).toBeInTheDocument()
    expect(screen.getByText('Not used by the pipeline: cover page. Draw boxes here if it holds questions.')).toBeInTheDocument()
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

    function drag(svg, [x0, y0], [x1, y1]) {
      fireEvent.pointerDown(svg, { clientX: x0, clientY: y0, pointerId: 1 })
      fireEvent.pointerMove(svg, { clientX: x1, clientY: y1, pointerId: 1 })
      fireEvent.pointerUp(svg, { clientX: x1, clientY: y1, pointerId: 1 })
    }

    it('asks for the question number before drawing, pre-filled with the next free one', async () => {
      renderPage()
      await screen.findByAltText('Page 2')
      await userEvent.click(screen.getByRole('button', { name: 'Draw question box' }))
      expect(screen.getByLabelText('Question number for the new box')).toHaveValue('3')
      expect(screen.getByTestId('overlay')).not.toHaveAttribute('data-drawing')  // not until a number is given
      await userEvent.click(screen.getByRole('button', { name: 'Start drawing' }))
      expect(screen.getByRole('status')).toHaveTextContent('Drag on the page to draw a question box for question 3.')
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

    it('takes digits only, and slots a new number into the sorted question list', async () => {
      renderPage()
      await screen.findByAltText('Page 2')
      await userEvent.click(screen.getByRole('button', { name: 'Draw question box' }))
      const field = screen.getByLabelText('Question number for the new box')
      await userEvent.clear(field)
      await userEvent.type(field, '1x.5-')
      expect(field).toHaveValue('15')
      await userEvent.clear(field)
      await userEvent.type(field, '0')
      await userEvent.click(screen.getByRole('button', { name: 'Start drawing' }))
      expect(screen.getByRole('alert')).toHaveTextContent('A question number must be a positive whole number')
      await userEvent.clear(field)
      await userEvent.type(field, '1')
      await userEvent.click(screen.getByRole('button', { name: 'Start drawing' }))
      // An existing number: the box joins question 1, placed by its position on the page.
      drag(overlayAtOneToOne(), [20, 0], [100, 30])
      const saved = await lastSaved()
      expect(saved.questions.map(q => q.number)).toEqual([1, 2])
      expect(saved.questions[0].question_rects).toEqual([
        { page: 2, x0: 10, y0: 0, x1: 50, y1: 15 }, { page: 2, x0: 10, y0: 20, x1: 60, y1: 120 },
      ])
    })

    it('draws an answer box for the selected question, pre-filled with its number', async () => {
      renderPage()
      await screen.findByAltText('Page 2')
      await userEvent.click(screen.getByText('Question 2'))
      await userEvent.click(screen.getByRole('button', { name: 'Draw answer box' }))
      expect(screen.getByLabelText('Question number for the new box')).toHaveValue('2')
      await userEvent.click(screen.getByRole('button', { name: 'Start drawing' }))
      expect(screen.getByRole('status')).toHaveTextContent('Drag on the page to draw an answer box for question 2.')
      drag(overlayAtOneToOne(), [0, 200], [100, 260])
      const saved = await lastSaved()
      expect(saved.questions[1].answer_rects).toEqual([{ page: 3, x0: 0, y0: 100, x1: 50, y1: 130 }])
    })

    it('refuses an answer box for a question that does not exist, and Esc cancels', async () => {
      renderPage()
      await screen.findByAltText('Page 2')
      await userEvent.click(screen.getByRole('button', { name: 'Draw answer box' }))
      const field = screen.getByLabelText('Question number for the new box')
      expect(field).toHaveValue('')  // no selection: no guess
      await userEvent.click(screen.getByRole('button', { name: 'Start drawing' }))
      expect(screen.getByRole('alert')).toHaveTextContent('Enter a question number')
      await userEvent.type(field, '7')
      await userEvent.click(screen.getByRole('button', { name: 'Start drawing' }))
      expect(screen.getByRole('alert')).toHaveTextContent("Question 7 doesn't exist. Draw its question box first.")
      expect(screen.getByTestId('overlay')).not.toHaveAttribute('data-drawing')
      await userEvent.type(field, '{Escape}')
      expect(screen.queryByLabelText('Question number for the new box')).not.toBeInTheDocument()
      expect(api.import.saveProposal).not.toHaveBeenCalled()
    })

    it('lists questions by number and shows boxes in document order, without saving', async () => {
      const [p] = REVIEW.proposal.papers
      api.import.review.mockResolvedValue({
        ...REVIEW, proposal: { ...REVIEW.proposal, papers: [{ ...p, questions: [p.questions[1], p.questions[0]] }] },
      })
      renderPage()
      await screen.findByAltText('Page 2')
      const items = within(screen.getByRole('complementary', { name: 'Questions' })).getAllByRole('listitem')
      expect(items.map(li => li.textContent)).toEqual([expect.stringMatching(/^Question 1/), expect.stringMatching(/^Question 2/)])
      expect(api.import.saveProposal).not.toHaveBeenCalled()
    })

    it('renumbering re-sorts the list and keeps the question selected', async () => {
      renderPage()
      await screen.findByAltText('Page 2')
      await userEvent.click(screen.getByText('Question 1'))
      const field = screen.getByLabelText('Number of question 1')
      await userEvent.clear(field)
      await userEvent.type(field, '9{Enter}')
      const items = within(screen.getByRole('complementary', { name: 'Questions' })).getAllByRole('listitem')
      expect(items[1]).toHaveTextContent('Question 9')
      expect(within(items[1]).getByRole('button', { pressed: true })).toBeInTheDocument()
      const saved = await lastSaved()
      expect(saved.questions.map(q => q.number)).toEqual([2, 9])
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

    it('shows the linked answer job in the Pairing block and what a confirm attached', async () => {
      api.import.review.mockResolvedValue({ ...TWO, matches: { q1: { filename: 'answers.pdf', paper_key: 'a1', job_id: 'j2' } } })
      api.import.confirmJobPaper.mockResolvedValue({
        paper_id: 7, job_status: 'review_ready', questions: [],
        answers_from: { job_id: 'j2', filename: 'answers.pdf', paper_key: 'a1', attached: [1, 2] }, unmatched: [9],
      })
      renderPage()
      const block = await screen.findByRole('region', { name: 'Pairing' })
      expect(block).toHaveTextContent(/Paired with answers\.pdf \(a1\)\. Its answers are attached when you confirm/)
      expect(within(block).getByRole('button', { name: 'Unmatch' })).toBeInTheDocument()
      const button = await screen.findByRole('button', { name: /Confirm paper/ })
      await waitFor(() => expect(button).toBeEnabled())
      await userEvent.click(button)
      expect(await screen.findByText(/Attached answers for questions 1, 2 from answers\.pdf \(a1\)/)).toBeInTheDocument()
      expect(screen.getByText(/Answers for question 9 matched no question/)).toBeInTheDocument()
    })

    it('names a linked answer paper from the same booklet as "this file"', async () => {
      api.import.review.mockResolvedValue({ ...TWO, matches: { q1: { filename: 'x.pdf', paper_key: 'a1', job_id: 'j1' } } })
      api.import.confirmJobPaper.mockResolvedValue({
        paper_id: 7, job_status: 'confirmed', questions: [],
        answers_from: { job_id: 'j1', filename: 'x.pdf', paper_key: 'a1', attached: [1] }, unmatched: [],
      })
      renderPage()
      expect(await screen.findByText(/Paired with this file \(a1\)/)).toBeInTheDocument()
      const button = await screen.findByRole('button', { name: /Confirm paper/ })
      await waitFor(() => expect(button).toBeEnabled())
      await userEvent.click(button)
      expect(await screen.findByText(/Attached answers for question 1 from this file \(a1\)/)).toBeInTheDocument()
    })

    it('unmatches the linked answer job and shows whatever matching finds next', async () => {
      api.import.review.mockResolvedValue({ ...TWO, matches: { q1: { filename: 'answers.pdf', paper_key: 'a1', job_id: 'j2' } } })
      api.import.unmatchJobPaper.mockResolvedValue({ matches: { filename: 'other.pdf', paper_key: 'a1', job_id: 'j3' }, proposal: null })
      renderPage()
      await userEvent.click(await screen.findByRole('button', { name: 'Unmatch' }))
      expect(api.import.unmatchJobPaper).toHaveBeenCalledWith('j1', 'q1')
      expect(await screen.findByText(/Paired with other\.pdf \(a1\)/)).toBeInTheDocument()
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

    it('confirms with a school typed as new, which also lifts the hold on confirm', async () => {
      const extracted = { school: 'Raffles Instn', subject: null, level: null, stream: null, exam_type: null }
      api.import.review.mockResolvedValue({
        ...TWO, filename_metadata: {}, paper_metadata: { q1: { ...FILLED, school_id: null, extracted } },
      })
      api.import.confirmJobPaper.mockResolvedValue({ paper_id: 7, job_status: 'review_ready', questions: [] })
      renderPage()
      const button = await screen.findByRole('button', { name: /Confirm paper/ })
      await userEvent.type(await screen.findByRole('combobox', { name: 'School' }), 'Raffles Instn')
      await userEvent.click(screen.getByRole('option', { name: 'Use “Raffles Instn” as a new school' }))
      expect(screen.queryByText(/Pick a school/)).not.toBeInTheDocument()
      await waitFor(() => expect(button).toBeEnabled())
      await userEvent.click(button)
      expect(api.import.confirmJobPaper).toHaveBeenCalledWith('j1', {
        paper_label: 'q1', ...FILLED, school_id: null, new_school_name: 'Raffles Instn', is_premium: true,
      })
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
      await screen.findByText(/Paired with answers\.pdf/)
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

    it('offers to match a question paper with no answers, and shows the details a pair saved', async () => {
      const none = q => ({ ...q, answer_rects: [] })
      const bare = { ...TWO.proposal.papers[0], questions: TWO.proposal.papers[0].questions.map(none) }
      api.import.review.mockResolvedValue({ ...TWO, filename_metadata: {}, paper_metadata: { q1: FILLED }, proposal: { ...TWO.proposal, papers: [bare] } })
      api.import.paperCandidates.mockResolvedValue({
        exact: [{
          kind: 'pending', ingest_paper_id: 41, job_id: 'j1', filename: 'scan.pdf', paper_key: 'a9', same_job: true,
          role: 'answer_only', details: FILLED, agree: [], differ: [], partner: null, preview: null,
          question_numbers: [], answer_numbers: [1, 2], answer_coverage: 'all',
        }],
        best: [],
      })
      api.import.matchJobPaper.mockResolvedValue({
        matches: { ingest_paper_id: 41, job_id: 'j1', filename: 'scan.pdf', paper_key: 'a9', matched_by: 'admin', answer_numbers: [1, 2] },
        proposal: null,
      })
      renderPage()
      const block = await screen.findByRole('region', { name: 'Pairing' })
      expect(await within(block).findByText('1 possible match')).toBeInTheDocument()
      await userEvent.click(within(block).getByRole('button', { name: 'Match this paper…' }))
      const dialog = await screen.findByRole('dialog', { name: 'Match this paper' })
      expect(await within(dialog).findByText('Same file (a9)')).toBeInTheDocument()
      const paperNo = within(dialog).getByLabelText('Paper no.')
      await userEvent.clear(paperNo)
      await userEvent.type(paperNo, '2')
      api.import.answerMappingTable.mockResolvedValue({ questions: [{ label: '1', answered: false, preview: null }], answers: [{ label: '1', preview: null }], mapping: null })
      await userEvent.click(await within(dialog).findByRole('button', { name: 'Pair' }))
      await within(dialog).findByRole('table')  // the answer mapping table, then Pair saves
      await userEvent.click(within(dialog).getByRole('button', { name: 'Pair' }))
      expect(api.import.matchJobPaper).toHaveBeenCalledWith('j1', 'q1', 41, expect.objectContaining({ paper_number: '2' }), { 1: '1' })
      expect(await screen.findByText(/Paired with this file \(a9\)/)).toBeInTheDocument()
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
      expect(screen.getByPlaceholderText('1')).toHaveValue('2')  // the sidebar's paper no.
      await new Promise(r => setTimeout(r, 1000))
      expect(api.import.savePaperMetadata).not.toHaveBeenCalled()  // the match route saved it
    })

    it('shows no Pairing block on a partly answered question paper', async () => {
      api.import.review.mockResolvedValue(TWO)
      renderPage()
      await screen.findByRole('button', { name: /Confirm paper/ })
      expect(screen.queryByRole('region', { name: 'Pairing' })).not.toBeInTheDocument()
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

    it('lists answers by question number and offers matching and Skip instead of Confirm', async () => {
      api.import.review.mockResolvedValue(ANSWERS)
      renderPage()
      await screen.findByAltText('Page 2')
      const list = screen.getByRole('complementary', { name: 'Questions' })
      expect(within(list).getByText('Answer 1')).toBeInTheDocument()
      expect(within(list).getByText('Answer 2')).toBeInTheDocument()
      expect(screen.queryByRole('button', { name: /Confirm paper/ })).not.toBeInTheDocument()
      expect(await screen.findByText('No match found')).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Match this paper…' })).toBeEnabled()
      expect(screen.getByRole('button', { name: 'Skip this paper' })).toBeEnabled()
    })

    it('attaches to a proposed paper and moves on once the admin has read the result', async () => {
      const paper = { id: 9, school: 'Raffles', year: 2024, level: 'Sec 3', subject: 'Math', paper_number: '1', answer_coverage: 'none' }
      api.import.review.mockResolvedValue({ ...ANSWERS, proposals: { a1: { status: 'proposed', note: null, paper } } })
      api.import.attachJobPaper.mockResolvedValue({ attached: [1, 2], unmatched: [], modes: {}, job_status: 'confirmed' })
      renderPage()
      expect(await screen.findByText(/Answers match Raffles 2024 Sec 3 Math Paper 1/)).toBeInTheDocument()
      api.import.answerMappingTable.mockResolvedValue({ questions: [{ label: '1', answered: false, preview: null }], answers: [{ label: '1', preview: null }], mapping: null })
      await userEvent.click(screen.getByRole('button', { name: 'Attach…' }))
      await userEvent.click(await screen.findByRole('button', { name: 'Attach answers' }))  // from the mapping table
      await waitFor(() => expect(api.import.attachJobPaper).toHaveBeenCalledWith('j1', { key: 'a1', paper_id: 9, mapping: { 1: '1' } }))
      await userEvent.click(await screen.findByRole('button', { name: 'Continue' }))
      await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent('/admin/import/review'))
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
      api.import.rejectProposedPaper.mockResolvedValue({ matches: { filename: 'questions.pdf', paper_key: 'q1', job_id: 'j2' }, proposal: null })
      renderPage()
      await userEvent.click(await screen.findByRole('button', { name: 'Not this one' }))
      expect(await screen.findByText(/Paired with questions\.pdf \(q1\)/)).toBeInTheDocument()
      expect(screen.queryByText(/Answers match/)).not.toBeInTheDocument()
    })

    it('shows a link to a question paper of the same booklet as "this file", and unmatches it', async () => {
      api.import.review.mockResolvedValue({ ...ANSWERS, matches: { a1: { filename: 'x.pdf', paper_key: 'q1', job_id: 'j1', matched_by: 'auto' } } })
      api.import.unmatchJobPaper.mockResolvedValue({ matches: null, proposal: null })
      renderPage()
      expect(await screen.findByText(/Paired with this file \(q1\)/)).toBeInTheDocument()
      expect(screen.getByText('matched automatically')).toBeInTheDocument()
      await userEvent.click(screen.getByRole('button', { name: 'Unmatch' }))
      expect(api.import.unmatchJobPaper).toHaveBeenCalledWith('j1', 'a1')
      expect(await screen.findByText('No match found')).toBeInTheDocument()
    })
  })
})
