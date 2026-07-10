import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import TopicCombobox from './TopicCombobox'

const topics = [
  {
    id: 10,
    name: 'Algebra',
    topic_number: 1,
    subtopics: [{ id: 100, name: 'Linear Equations' }],
  },
  { id: 20, name: 'Geometry', topic_number: 2, subtopics: [] },
]

describe('TopicCombobox option labels', () => {
  it('shows topic names with their T{n} prefix', async () => {
    const user = userEvent.setup()
    render(<TopicCombobox topics={topics} selected={[]} onAdd={() => {}} />)

    await user.click(screen.getByRole('textbox'))
    expect(screen.getByText('T1: Algebra')).toBeInTheDocument()
    expect(screen.getByText('T2: Geometry')).toBeInTheDocument()
    expect(screen.getByText(/Linear Equations/)).toBeInTheDocument()
  })

  it('still filters by name keyword', async () => {
    const user = userEvent.setup()
    render(<TopicCombobox topics={topics} selected={[]} onAdd={() => {}} />)

    await user.type(screen.getByRole('textbox'), 'geo')
    expect(screen.getByText('T2: Geometry')).toBeInTheDocument()
    expect(screen.queryByText('T1: Algebra')).not.toBeInTheDocument()
  })
})
