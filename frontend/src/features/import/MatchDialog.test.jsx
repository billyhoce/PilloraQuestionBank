import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import MatchDialog from './MatchDialog'
import { api } from '../../api/client'

vi.mock('../../api/client', () => ({
  api: { import: { paperCandidates: vi.fn(), matchJobPaper: vi.fn(), attachJobPaper: vi.fn(), answerMappingTable: vi.fn() } },
}))

const REFS = {
  subjects: [{ id: 1, name: 'Math' }], streams: [{ id: 2, name: 'G3' }], levels: [{ id: 3, name: 'Sec 3' }],
  schools: [{ id: 4, name: 'RI' }, { id: 6, name: 'HCI' }], examTypes: [{ id: 5, name: 'EOY' }],
}
const META = { subject_id: 1, stream_id: 2, level_id: 3, school_id: 4, exam_type_id: 5, year: '2024', paper_number: '1', is_premium: true }
const DETAILS = { subject_id: 1, stream_id: 2, level_id: 3, school_id: 4, exam_type_id: 5, year: 2024, paper_number: '1', new_school_name: null }
const PAGE = { page: 3, width_pt: 100, height_pt: 200, width_px: 200, height_px: 400 }
const RECT = { page: 3, x0: 10, y0: 20, x1: 60, y1: 120 }

const pending = over => ({
  kind: 'pending', ingest_paper_id: 31, paper_id: null, job_id: 'j2', filename: 'questions.pdf', paper_key: 'q1',
  same_job: false, role: 'question', details: DETAILS, agree: [], differ: [], partner: null,
  preview: { number: 1, url: 'https://s3/other-p3.webp', page: PAGE, rect: RECT },
  question_numbers: [1, 2], answer_numbers: [], answer_coverage: 'none', ...over,
})
const bank = over => ({
  ...pending(), kind: 'bank', ingest_paper_id: null, paper_id: 7, job_id: null, filename: null, paper_key: null,
  preview: { number: 1, url: 'https://s3/bank-q1.webp' }, ...over,
})

function renderDialog(props = {}) {
  const handlers = { onClose: vi.fn(), onPaired: vi.fn(), onAttached: vi.fn(), beforeSave: vi.fn().mockResolvedValue() }
  render(
    <MatchDialog
      jobId="j1" paperKey="a1" role="answer_only" metadata={META} refs={REFS}
      ownPreview={{ number: 1, url: 'https://s3/p2.webp', page: PAGE, rect: RECT }}
      {...handlers} {...props}
    />,
  )
  return handlers
}

// The mapping table step: questions 1 and 2 and answers 1 and 2, by number.
const TABLE = {
  questions: [{ label: '1', answered: false, preview: null }, { label: '2', answered: false, preview: null }],
  answers: [{ label: '1', preview: null }, { label: '2', preview: null }],
  mapping: null,
}
const BY_NUMBER = { 1: '1', 2: '2' }

// Choose a booklet (its Pair / Attach button), then save from the mapping table.
async function choose(name, save) {
  await userEvent.click(await screen.findByRole('button', { name }))
  await screen.findByRole('table')
  await userEvent.click(screen.getByRole('button', { name: save }))
}

beforeEach(() => {
  vi.clearAllMocks()
  api.import.paperCandidates.mockResolvedValue({ exact: [], best: [] })
  api.import.answerMappingTable.mockResolvedValue(TABLE)
})

describe('MatchDialog', () => {
  it('searches with the paper\'s own details, an unresolved school counting as blank', async () => {
    renderDialog({ metadata: { ...META, school_id: null }, extractedSchool: 'Raffles Instn' })
    await waitFor(() => expect(api.import.paperCandidates).toHaveBeenCalledWith('j1', 'a1', {
      subject_id: 1, stream_id: 2, level_id: 3, exam_type_id: 5, year: 2024, paper_number: '1',
    }))
    expect(screen.getByText(/— not in the list/)).toHaveTextContent('Raffles Instn — not in the list')
    expect(await screen.findByText('No booklet matches these details.')).toBeInTheDocument()
  })

  it('lists exact matches with where they are, their details, previews and an existing partner', async () => {
    api.import.paperCandidates.mockResolvedValue({
      exact: [pending({ partner: { filename: 'old-answers.pdf', paper_key: 'a1', job_id: 'j3' } }), bank()], best: [],
    })
    renderDialog()
    const list = await screen.findByRole('list', { name: 'Exact matches' })
    const [first, second] = within(list).getAllByRole('listitem')
    expect(within(first).getByText('Pending in questions.pdf (q1)')).toBeInTheDocument()
    expect(within(first).getByText('RI 2024 Sec 3 Math EOY G3 Paper 1')).toBeInTheDocument()
    expect(within(first).getByAltText('Candidate first question')).toHaveAttribute('src', 'https://s3/other-p3.webp')
    expect(within(first).getByAltText("This paper's first answer")).toHaveAttribute('src', 'https://s3/p2.webp')
    expect(within(first).getByText('This will unpair it from old-answers.pdf')).toBeInTheDocument()
    expect(within(first).getByRole('button', { name: 'Pair' })).toBeEnabled()
    expect(within(second).getByText('In the bank (paper 7)')).toBeInTheDocument()
    expect(within(second).getByAltText('Candidate first question')).toHaveAttribute('src', 'https://s3/bank-q1.webp')
    expect(within(second).getByRole('button', { name: 'Attach' })).toBeEnabled()
  })

  it('searches again as the fields change, and shows the best matches with what differs', async () => {
    renderDialog()
    await waitFor(() => expect(api.import.paperCandidates).toHaveBeenCalled())
    api.import.paperCandidates.mockResolvedValue({
      exact: [], best: [pending({ differ: ['paper_number'], details: { ...DETAILS, paper_number: '2A' } })],
    })
    const paperNo = screen.getByLabelText('Paper no.')
    await userEvent.clear(paperNo)
    await userEvent.type(paperNo, '2')
    await waitFor(() => expect(api.import.paperCandidates).toHaveBeenLastCalledWith('j1', 'a1', expect.objectContaining({ paper_number: '2' })))
    const list = await screen.findByRole('list', { name: 'Best matches' })
    expect(within(list).getByText('paper no. 2A ≠ 2')).toBeInTheDocument()
  })

  it('pairs after the mapping table, saving the paper\'s details when ticked and the mapping', async () => {
    api.import.paperCandidates.mockResolvedValue({ exact: [pending()], best: [] })
    const state = { matches: { filename: 'questions.pdf', paper_key: 'q1' }, proposal: null }
    api.import.matchJobPaper.mockResolvedValue(state)
    const { onPaired, beforeSave } = renderDialog()
    expect(await screen.findByLabelText("Also update this paper's details")).toBeChecked()
    await userEvent.click(screen.getByRole('button', { name: 'Pair' }))
    expect(await screen.findByRole('table')).toBeInTheDocument()
    expect(api.import.answerMappingTable).toHaveBeenCalledWith('j1', 'a1', { ingest_paper_id: 31 })
    expect(api.import.matchJobPaper).not.toHaveBeenCalled() // nothing is saved before the table
    await userEvent.selectOptions(screen.getByLabelText('Answer 2 goes onto'), '1')
    await userEvent.click(screen.getByRole('button', { name: 'Pair' }))
    expect(beforeSave).toHaveBeenCalled()
    expect(api.import.matchJobPaper).toHaveBeenCalledWith('j1', 'a1', 31, {
      subject_id: 1, stream_id: 2, level_id: 3, school_id: 4, exam_type_id: 5, year: 2024, paper_number: '1',
    }, { 1: '1', 2: '1' })
    expect(onPaired).toHaveBeenCalledWith(state, expect.objectContaining({ school_id: 4, year: '2024' }))
  })

  it('pairs without touching the paper\'s details when unticked', async () => {
    api.import.paperCandidates.mockResolvedValue({ exact: [pending()], best: [] })
    api.import.matchJobPaper.mockResolvedValue({ matches: {}, proposal: null })
    const { onPaired } = renderDialog()
    await userEvent.click(await screen.findByLabelText("Also update this paper's details"))
    await choose('Pair', 'Pair')
    expect(api.import.matchJobPaper).toHaveBeenCalledWith('j1', 'a1', 31, undefined, BY_NUMBER)
    expect(onPaired).toHaveBeenCalledWith({ matches: {}, proposal: null }, null)
  })

  it('greys out a bank paper that already has answers', async () => {
    api.import.paperCandidates.mockResolvedValue({ exact: [bank({ answer_coverage: 'all', answer_numbers: [1, 2] })], best: [] })
    renderDialog()
    const row = (await screen.findByText('Already has answers')).closest('li')
    expect(row).toHaveAttribute('aria-disabled', 'true')
    expect(within(row).queryByRole('button')).not.toBeInTheDocument()
  })

  it('greys out a pending question paper that has answers of its own, even partly', async () => {
    api.import.paperCandidates.mockResolvedValue({ exact: [pending({ answer_coverage: 'partial', answer_numbers: [1] })], best: [] })
    renderDialog()
    const row = (await screen.findByText('Already has answers')).closest('li')
    expect(row).toHaveAttribute('aria-disabled', 'true')
    expect(within(row).queryByRole('button')).not.toBeInTheDocument()
  })

  it('attaches to a bank paper without answers after the mapping table', async () => {
    api.import.paperCandidates.mockResolvedValue({ exact: [bank()], best: [] })
    const result = { attached: [1], unmatched: [], modes: {}, job_status: 'confirmed' }
    api.import.attachJobPaper.mockResolvedValue(result)
    const { onAttached } = renderDialog()
    await screen.findByRole('button', { name: 'Attach' })
    expect(screen.queryByLabelText("Also update this paper's details")).not.toBeInTheDocument() // nothing to pair
    await choose('Attach', 'Attach answers')
    expect(api.import.answerMappingTable).toHaveBeenCalledWith('j1', 'a1', { paper_id: 7 })
    expect(screen.queryByLabelText('Add to the existing answers')).not.toBeInTheDocument()
    expect(api.import.attachJobPaper).toHaveBeenCalledWith('j1', { key: 'a1', paper_id: 7, mapping: BY_NUMBER })
    expect(onAttached).toHaveBeenCalledWith({ ...result, paper_id: 7 })
  })

  it('asks append or replace (default append) for a partly answered bank paper', async () => {
    api.import.paperCandidates.mockResolvedValue({ exact: [bank({ answer_coverage: 'partial', answer_numbers: [1] })], best: [] })
    api.import.attachJobPaper.mockResolvedValue({ attached: [2], unmatched: [], modes: {}, job_status: 'review_ready' })
    renderDialog()
    expect(await screen.findByText('Only 1 of 2 questions have answers')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Attach' }))
    await screen.findByRole('table')
    expect(screen.getByLabelText('Add to the existing answers')).toBeChecked()
    await userEvent.click(screen.getByLabelText('Replace the existing answers'))
    await userEvent.click(screen.getByRole('button', { name: 'Attach answers' }))
    expect(api.import.attachJobPaper).toHaveBeenCalledWith('j1', { key: 'a1', paper_id: 7, mode: 'replace', mapping: BY_NUMBER })
  })

  it('goes back from the mapping table to the list without saving', async () => {
    api.import.paperCandidates.mockResolvedValue({ exact: [pending()], best: [] })
    renderDialog()
    await userEvent.click(await screen.findByRole('button', { name: 'Pair' }))
    await screen.findByRole('table')
    await userEvent.click(screen.getByRole('button', { name: 'Back' }))
    expect(await screen.findByRole('list', { name: 'Exact matches' })).toBeInTheDocument()
    expect(api.import.matchJobPaper).not.toHaveBeenCalled()
  })

  it('shows a refused pair and stays open', async () => {
    api.import.paperCandidates.mockResolvedValue({ exact: [pending()], best: [] })
    api.import.matchJobPaper.mockRejectedValue({ message: 'That is not a pending question paper awaiting review' })
    const { onPaired } = renderDialog()
    await choose('Pair', 'Pair')
    expect(await screen.findByText('That is not a pending question paper awaiting review')).toBeInTheDocument()
    expect(onPaired).not.toHaveBeenCalled()
  })
})
