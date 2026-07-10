import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import QuestionCard from './QuestionCard'

const baseItem = {
  id: 1,
  question_number: 3,
  marks: 5,
  first_page_url: null,
  paper_info: {
    school_name: 'Raffles Institution',
    year: 2024,
    exam_type_name: 'EOY',
    paper_number: '1',
  },
  topics: [
    { topic_name: 'Algebra', topic_number: 1, subtopic_names: ['Linear Equations'] },
    { topic_name: 'Geometry', topic_number: 2, subtopic_names: [] },
  ],
}

describe('QuestionCard topic chips', () => {
  it('renders topic chips as "T{n} {name}"', () => {
    render(<QuestionCard item={baseItem} onClick={() => {}} />)
    expect(screen.getByText('T1: Algebra')).toBeInTheDocument()
    expect(screen.getByText('T2: Geometry')).toBeInTheDocument()
  })

  it('renders subtopic names', () => {
    render(<QuestionCard item={baseItem} onClick={() => {}} />)
    expect(screen.getByText(/Linear Equations/)).toBeInTheDocument()
  })

  it('dedupes repeated topics', () => {
    const item = {
      ...baseItem,
      topics: [
        { topic_name: 'Algebra', topic_number: 1, subtopic_names: [] },
        { topic_name: 'Algebra', topic_number: 1, subtopic_names: [] },
      ],
    }
    render(<QuestionCard item={item} onClick={() => {}} />)
    expect(screen.getAllByText('T1: Algebra')).toHaveLength(1)
  })
})

describe('QuestionCard tag chips', () => {
  it('renders tag chips from item.tags', () => {
    const item = {
      ...baseItem,
      tags: [{ id: 1, name: 'Challenging' }, { id: 2, name: 'Graphing' }],
    }
    render(<QuestionCard item={item} onClick={() => {}} />)
    expect(screen.getByText('Challenging')).toBeInTheDocument()
    expect(screen.getByText('Graphing')).toBeInTheDocument()
  })

  it('renders no tag chips when tags are absent', () => {
    render(<QuestionCard item={baseItem} onClick={() => {}} />)
    expect(screen.queryByText('Challenging')).not.toBeInTheDocument()
  })
})
