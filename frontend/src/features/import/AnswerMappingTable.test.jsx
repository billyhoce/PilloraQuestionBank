import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AnswerMappingTable from './AnswerMappingTable'
import { api } from '../../api/client'

vi.mock('../../api/client', () => ({ api: { import: { answerMappingTable: vi.fn() } } }))

const preview = name => ({ number: 1, url: `https://s3/${name}.webp` })
const TABLE = {
  questions: [
    { label: '1', answered: false, preview: preview('q1') },
    { label: '2', answered: false, preview: preview('q2') },
    { label: '3', answered: true, preview: null },
  ],
  answers: [{ label: '1', preview: preview('a1') }, { label: '2', preview: preview('a2') }, { label: '9', preview: null }],
  mapping: null,
}

function renderTable(props = {}) {
  const onSave = vi.fn()
  const onCancel = vi.fn()
  render(
    <AnswerMappingTable jobId="j1" paperKey="a1" target={{ ingest_paper_id: 31 }} saveLabel="Pair"
      onSave={onSave} onCancel={onCancel} {...props} />,
  )
  return { onSave, onCancel }
}

const row = label => screen.getByRole('row', { name: typeof label === 'number' ? `Q${label}` : label })

beforeEach(() => {
  vi.clearAllMocks()
  api.import.answerMappingTable.mockResolvedValue(TABLE)
})

describe('AnswerMappingTable', () => {
  it('shows each question beside the answers going onto it, pre-filled by number', async () => {
    renderTable()
    expect(await screen.findByRole('table')).toBeInTheDocument()
    expect(api.import.answerMappingTable).toHaveBeenCalledWith('j1', 'a1', { ingest_paper_id: 31 })
    expect(within(row(1)).getByAltText('Question 1')).toHaveAttribute('src', 'https://s3/q1.webp')
    expect(within(row(1)).getByAltText('Answer 1')).toHaveAttribute('src', 'https://s3/a1.webp')
    expect(within(row(2)).getByLabelText('Answer 2 goes onto')).toHaveValue('2')
    expect(within(row(3)).getByText('Has answers of its own')).toBeInTheDocument()
    expect(within(row('Not placed')).getByLabelText('Answer 9 goes onto')).toHaveValue('')
    expect(screen.getByText('Answer 9 has no question')).toBeInTheDocument()
  })

  it('updates the warnings as a row changes, and saves what is shown', async () => {
    const { onSave } = renderTable()
    await screen.findByRole('table')
    await userEvent.selectOptions(screen.getByLabelText('Answer 2 goes onto'), '1')
    await userEvent.selectOptions(screen.getByLabelText('Answer 9 goes onto'), '2')
    expect(screen.queryByText(/has no question/)).not.toBeInTheDocument()
    expect(within(row(1)).getAllByRole('combobox')).toHaveLength(2)
    await userEvent.selectOptions(screen.getByLabelText('Answer 1 goes onto'), '')
    expect(screen.getByText('Answer 1 has no question')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Pair' }))
    expect(onSave).toHaveBeenCalledWith({ 1: null, 2: '1', 9: '2' })
  })

  it('shifts all answers by N', async () => {
    renderTable()
    await screen.findByRole('table')
    const shift = screen.getByLabelText('Shift all answers by')
    await userEvent.clear(shift)
    await userEvent.type(shift, '1')
    await userEvent.click(screen.getByRole('button', { name: 'Apply' }))
    expect(screen.getByLabelText('Answer 1 goes onto')).toHaveValue('2')
    expect(screen.getByLabelText('Answer 2 goes onto')).toHaveValue('3')
    expect(screen.getByText('Q1 would get no answers')).toBeInTheDocument()
    expect(screen.getByText('Answer 9 has no question')).toBeInTheDocument()
  })

  it('starts from a stored mapping', async () => {
    api.import.answerMappingTable.mockResolvedValue({ ...TABLE, mapping: { 1: '2', 2: '1', 9: '3' } })
    renderTable()
    await screen.findByRole('table')
    expect(screen.getByLabelText('Answer 1 goes onto')).toHaveValue('2')
    expect(screen.getByLabelText('Answer 9 goes onto')).toHaveValue('3')
    expect(screen.queryByRole('row', { name: 'Not placed' })).not.toBeInTheDocument()
  })
})
