import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import PairingBlock from './PairingBlock'
import { api } from '../../api/client'

vi.mock('../../api/client', () => ({
  api: {
    import: {
      paperCandidates: vi.fn(), matchJobPaper: vi.fn(), attachJobPaper: vi.fn(), unmatchJobPaper: vi.fn(), rejectProposedPaper: vi.fn(),
      answerMappingTable: vi.fn(), saveAnswerMap: vi.fn(), rejectSuggestion: vi.fn(),
    },
  },
}))

const REFS = {
  subjects: [{ id: 1, name: 'Math' }], streams: [{ id: 2, name: 'G3' }], levels: [{ id: 3, name: 'Sec 3' }],
  schools: [{ id: 4, name: 'RI' }], examTypes: [{ id: 5, name: 'EOY' }],
}
const META = { subject_id: 1, stream_id: 2, level_id: 3, school_id: 4, exam_type_id: 5, year: '2024', paper_number: '1' }
const PAPER = {
  key: 'a1', role: 'answer_only', pages: [{ page: 2, url: 'https://s3/p2.webp', width_pt: 100, height_pt: 200, width_px: 200, height_px: 400 }],
  questions: [{ number: 1, question_rects: [], answer_rects: [{ page: 2, x0: 0, y0: 0, x1: 10, y1: 10 }] }],
}
const BANK = { id: 9, school: 'Raffles', year: 2024, level: 'Sec 3', subject: 'Math', paper_number: '1', answer_coverage: 'none' }
const LINK = {
  ingest_paper_id: 31, job_id: 'j2', filename: 'questions.pdf', paper_key: 'q1', matched_by: 'auto',
  details: { school_id: 4, year: 2024, level_id: 3, subject_id: 1, exam_type_id: 5, stream_id: 2, paper_number: '1' },
}

function renderBlock(props = {}) {
  const handlers = { onMatched: vi.fn(), onAttached: vi.fn(), beforeSave: vi.fn().mockResolvedValue() }
  render(<PairingBlock jobId="j1" paper={PAPER} metadata={META} refs={REFS} link={null} proposal={null} {...handlers} {...props} />)
  return handlers
}

// What the answer mapping table loads: answers 1 and 2 onto questions 1 and 2.
const TABLE = {
  questions: [{ label: '1', answered: false, preview: null }, { label: '2', answered: false, preview: null }],
  answers: [{ label: '1', preview: null }, { label: '2', preview: null }],
  mapping: null,
}

beforeEach(() => {
  vi.clearAllMocks()
  api.import.paperCandidates.mockResolvedValue({ exact: [], best: [] })
  api.import.answerMappingTable.mockResolvedValue(TABLE)
})

describe('PairingBlock', () => {
  it('with no partner, says how many booklets match its details and opens the Match dialog', async () => {
    api.import.paperCandidates.mockResolvedValue({ exact: [{}, {}], best: [] })
    renderBlock()
    expect(await screen.findByText('2 possible matches')).toBeInTheDocument()
    expect(api.import.paperCandidates).toHaveBeenCalledWith('j1', 'a1', expect.objectContaining({ year: 2024, school_id: 4 }))
    await userEvent.click(screen.getByRole('button', { name: 'Match this paper…' }))
    expect(screen.getByRole('dialog', { name: 'Match this paper' })).toBeInTheDocument()
  })

  it('offers a suggested question paper: Pair saves first and pairs, Not a pair turns it down', async () => {
    const suggestion = { ingest_paper_id: 31, job_id: 'j2', filename: 'P2 questions.pdf', paper_key: 'q1' }
    const proposal = { status: 'suggested', note: 'same year; uploaded together', paper: null, suggestion }
    api.import.matchJobPaper.mockResolvedValue({ matches: LINK, proposal: null })
    api.import.rejectSuggestion.mockResolvedValue({ matches: null, proposal: null })
    const { onMatched, beforeSave } = renderBlock({ proposal })
    expect(screen.getByText(/Looks like the answers to P2 questions\.pdf \(q1\)/)).toHaveTextContent('same year; uploaded together')
    await userEvent.click(screen.getByRole('button', { name: 'Pair' }))
    expect(beforeSave).toHaveBeenCalled()
    expect(api.import.matchJobPaper).toHaveBeenCalledWith('j1', 'a1', 31)
    expect(onMatched).toHaveBeenCalledWith({ matches: LINK, proposal: null })
    await userEvent.click(screen.getByRole('button', { name: 'Not a pair' }))
    expect(api.import.rejectSuggestion).toHaveBeenCalledWith('j1', 'a1')
  })

  it('says when nothing matches', async () => {
    renderBlock()
    expect(await screen.findByText('No match found')).toBeInTheDocument()
  })

  it('when linked, names the partner and how it was matched, and can unmatch', async () => {
    api.import.unmatchJobPaper.mockResolvedValue({ matches: null, proposal: null })
    const { onMatched } = renderBlock({ link: LINK })
    expect(screen.getByText(/Paired with questions\.pdf \(q1\)/)).toBeInTheDocument()
    expect(screen.getByText('RI 2024 Sec 3 Math EOY G3 Paper 1')).toBeInTheDocument()
    expect(screen.getByText('matched automatically')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Change match…' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Check answers…' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Unmatch' }))
    expect(api.import.unmatchJobPaper).toHaveBeenCalledWith('j1', 'a1')
    expect(onMatched).toHaveBeenCalledWith({ matches: null, proposal: null })
  })

  it('"Check answers…" opens the mapping table for the pair and saves an edited mapping', async () => {
    const state = { matches: { ...LINK, answer_map: { 1: '2', 2: '2' } }, proposal: null }
    api.import.answerMappingTable.mockResolvedValue({ ...TABLE, mapping: { 1: '2' } })
    api.import.saveAnswerMap.mockResolvedValue(state)
    const { onMatched } = renderBlock({ link: LINK })
    await userEvent.click(screen.getByRole('button', { name: 'Check answers…' }))
    expect(await screen.findByRole('dialog', { name: 'Check answers' })).toBeInTheDocument()
    expect(api.import.answerMappingTable).toHaveBeenCalledWith('j1', 'a1', null)
    expect(await screen.findByLabelText('Answer 1 goes onto')).toHaveValue('2') // the stored mapping
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(api.import.saveAnswerMap).toHaveBeenCalledWith('j1', 'a1', { 1: '2', 2: '2' })
    expect(onMatched).toHaveBeenCalledWith(state)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('names a partner in the same booklet "this file", matched by an admin', () => {
    renderBlock({ link: { ...LINK, job_id: 'j1', matched_by: 'admin' } })
    expect(screen.getByText(/Paired with this file \(q1\)/)).toBeInTheDocument()
    expect(screen.getByText('matched by an admin')).toBeInTheDocument()
  })

  it('with a proposed bank paper, attaches to it through the mapping table and reports what was attached', async () => {
    api.import.attachJobPaper.mockResolvedValue({ attached: [1], unmatched: [2], modes: {}, job_status: 'confirmed' })
    const { onAttached, beforeSave } = renderBlock({ proposal: { status: 'proposed', note: null, paper: BANK } })
    expect(screen.getByText(/Answers match Raffles 2024 Sec 3 Math Paper 1 \(paper 9\)/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Change match…' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Attach…' }))
    expect(api.import.answerMappingTable).toHaveBeenCalledWith('j1', 'a1', { paper_id: 9 })
    expect(screen.queryByLabelText('Add to the existing answers')).not.toBeInTheDocument()
    await userEvent.selectOptions(await screen.findByLabelText('Answer 2 goes onto'), '')
    await userEvent.click(screen.getByRole('button', { name: 'Attach answers' }))
    expect(beforeSave).toHaveBeenCalled()
    expect(api.import.attachJobPaper).toHaveBeenCalledWith('j1', { key: 'a1', paper_id: 9, mapping: { 1: '1', 2: null } })
    expect(await screen.findByText(/Attached answers for question 1 to paper 9/)).toBeInTheDocument()
    expect(screen.getByText(/Not attached \(no such question in the paper\): 2/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }))
    expect(onAttached).toHaveBeenCalledWith('confirmed')
  })

  it('asks append or replace only for a partly answered proposed paper', async () => {
    api.import.attachJobPaper.mockResolvedValue({ attached: [1], unmatched: [], modes: {}, job_status: 'review_ready' })
    renderBlock({ proposal: { status: 'proposed', note: null, paper: { ...BANK, answer_coverage: 'partial' } } })
    await userEvent.click(screen.getByRole('button', { name: 'Attach…' }))
    await screen.findByRole('table')
    expect(api.import.attachJobPaper).not.toHaveBeenCalled()
    expect(screen.getByLabelText('Add to the existing answers')).toBeChecked()
    await userEvent.click(screen.getByRole('button', { name: 'Attach answers' }))
    expect(api.import.attachJobPaper).toHaveBeenCalledWith('j1', { key: 'a1', paper_id: 9, mode: 'append', mapping: { 1: '1', 2: '2' } })
  })

  it('"Not this one" rejects the proposed paper and passes on what matching finds next', async () => {
    const next = { matches: null, proposal: null }
    api.import.rejectProposedPaper.mockResolvedValue(next)
    const { onMatched } = renderBlock({ proposal: { status: 'proposed', note: null, paper: BANK } })
    await userEvent.click(screen.getByRole('button', { name: 'Not this one' }))
    expect(api.import.rejectProposedPaper).toHaveBeenCalledWith('j1', 'a1')
    expect(onMatched).toHaveBeenCalledWith(next)
  })

  it('passes on a pair made in the dialog, with the details it saved', async () => {
    api.import.paperCandidates.mockResolvedValue({
      exact: [{
        kind: 'pending', ingest_paper_id: 31, job_id: 'j2', filename: 'questions.pdf', paper_key: 'q1', same_job: false,
        details: LINK.details, agree: [], differ: [], partner: null, preview: null, question_numbers: [1], answer_numbers: [],
        answer_coverage: 'none',
      }],
      best: [],
    })
    const state = { matches: { ...LINK, matched_by: 'admin' }, proposal: null }
    api.import.matchJobPaper.mockResolvedValue(state)
    const { onMatched } = renderBlock()
    await userEvent.click(await screen.findByRole('button', { name: 'Match this paper…' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Pair' }))
    await screen.findByRole('table')
    await userEvent.click(screen.getByRole('button', { name: 'Pair' }))
    await waitFor(() => expect(onMatched).toHaveBeenCalledWith(state, expect.objectContaining({ year: '2024' })))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})
