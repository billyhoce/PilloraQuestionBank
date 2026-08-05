import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import PartsEditor from './PartsEditor'
import { buildTopicLookup } from '../features/import/topicUtils'

const topics = [
  { id: 10, name: 'Algebra', topic_number: 1, subtopics: [{ id: 100, name: 'Linear Equations' }] },
  { id: 20, name: 'Geometry', topic_number: 2, subtopics: [] },
]
const lookup = buildTopicLookup(topics)

function setup(parts) {
  const onChange = vi.fn()
  render(<PartsEditor parts={parts} topics={topics} lookup={lookup} onChange={onChange} />)
  return { onChange, user: userEvent.setup() }
}

const partA = { label: '(a)', marks: 2, selected: [{ topic_id: 10, subtopic_id: 100 }] }
const partB = { label: '(b)', marks: 5, selected: [{ topic_id: 20, subtopic_id: null }] }

describe('PartsEditor rendering', () => {
  it('shows each part with its label, marks and topics', () => {
    setup([partA, partB])

    expect(screen.getByLabelText('Part 1 label')).toHaveValue('(a)')
    expect(screen.getByLabelText('Part 1 marks')).toHaveValue(2)
    expect(screen.getByLabelText('Part 2 label')).toHaveValue('(b)')
    expect(screen.getByText(/Linear Equations/)).toBeInTheDocument()
    expect(screen.getByText('T2: Geometry')).toBeInTheDocument()
  })

  it('shows the summed total', () => {
    setup([partA, partB])
    expect(screen.getByText('Total 7 marks')).toBeInTheDocument()
  })

  it('shows an em dash total when no part carries marks', () => {
    setup([{ label: '', marks: null, selected: [] }])
    expect(screen.getByText('Total —')).toBeInTheDocument()
  })
})

describe('PartsEditor editing', () => {
  it('adds a blank part', async () => {
    const { onChange, user } = setup([partA])

    await user.click(screen.getByRole('button', { name: '+ Add part' }))

    expect(onChange).toHaveBeenCalledWith([partA, { label: '', marks: null, selected: [] }])
  })

  it('removes a part', async () => {
    const { onChange, user } = setup([partA, partB])

    await user.click(screen.getByLabelText('Remove part 1'))

    expect(onChange).toHaveBeenCalledWith([partB])
  })

  it('keeps one blank part when the last one is removed', async () => {
    const { onChange, user } = setup([partA])

    await user.click(screen.getByLabelText('Remove part 1'))

    expect(onChange).toHaveBeenCalledWith([{ label: '', marks: null, selected: [] }])
  })

  it('edits a part label', async () => {
    const { onChange, user } = setup([partA])

    await user.type(screen.getByLabelText('Part 1 label'), 'x')

    expect(onChange).toHaveBeenCalledWith([{ ...partA, label: '(a)x' }])
  })

  it('edits a part’s marks', async () => {
    const { onChange, user } = setup([{ label: '(a)', marks: null, selected: [] }])

    await user.type(screen.getByLabelText('Part 1 marks'), '3')

    expect(onChange).toHaveBeenCalledWith([{ label: '(a)', marks: 3, selected: [] }])
  })

  it('adds a topic to the part it was picked on, not the first part', async () => {
    const { onChange, user } = setup([partA, { label: '(b)', marks: 5, selected: [] }])

    // Second part's combobox.
    await user.click(screen.getAllByRole('textbox', { name: '' })[1])
    await user.click(screen.getByText('T2: Geometry'))

    expect(onChange).toHaveBeenCalledWith([
      partA,
      { label: '(b)', marks: 5, selected: [{ topic_id: 20, subtopic_id: null }] },
    ])
  })

  it('removes a topic from a part', async () => {
    const { onChange, user } = setup([partA])

    await user.click(screen.getByLabelText('Remove topic'))

    expect(onChange).toHaveBeenCalledWith([{ ...partA, selected: [] }])
  })

  it('lets the same subtopic be selected on two different parts', async () => {
    const { onChange, user } = setup([partA, { label: '(b)', marks: 5, selected: [] }])

    await user.click(screen.getAllByRole('textbox', { name: '' })[1])
    // Scope to the dropdown — "Linear Equations" also appears as part (a)'s chip.
    const option = screen.getAllByRole('listitem').find(li => /Linear Equations/.test(li.textContent))
    await user.click(option)

    expect(onChange).toHaveBeenCalledWith([
      partA,
      { label: '(b)', marks: 5, selected: [{ topic_id: 10, subtopic_id: 100 }] },
    ])
  })
})
