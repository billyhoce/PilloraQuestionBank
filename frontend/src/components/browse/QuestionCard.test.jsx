import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
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

describe('QuestionCard premium lock', () => {
  const lockedItem = {
    ...baseItem,
    first_page_url: null,
    locked: true,
    paper_info: { ...baseItem.paper_info, is_premium: true },
  }

  const renderWithRouter = (props) =>
    render(<MemoryRouter><QuestionCard {...props} /></MemoryRouter>)

  it('shows the placeholder image (not the real preview) for a locked premium question', () => {
    renderWithRouter({ item: lockedItem, onClick: () => {} })
    const img = screen.getByRole('img', { name: /premium content/i })
    expect(img).toBeInTheDocument()
    expect(img.getAttribute('src')).not.toBe('https://example.com/img.webp')
  })

  it('stays clickable when locked (opens the detail view)', async () => {
    const onClick = vi.fn()
    const user = userEvent.setup()
    renderWithRouter({ item: lockedItem, onClick })
    await user.click(screen.getByRole('img', { name: /premium content/i }))
    expect(onClick).toHaveBeenCalled()
  })

  it('shows a Subscribe link instead of an Add button in selectable mode', () => {
    renderWithRouter({ item: lockedItem, onClick: () => {}, selectable: true })
    const subscribe = screen.getByRole('link', { name: /subscribe/i })
    expect(subscribe).toHaveAttribute('href', '/subscribe')
    expect(screen.queryByRole('button', { name: /add/i })).not.toBeInTheDocument()
  })

  it('renders the real image and an Add button when not locked', () => {
    const item = {
      ...baseItem,
      locked: false,
      first_page_url: 'https://example.com/img.webp',
      paper_info: { ...baseItem.paper_info, is_premium: false },
    }
    renderWithRouter({ item, onClick: () => {}, selectable: true })
    expect(screen.getByRole('img')).toHaveAttribute('src', 'https://example.com/img.webp')
    expect(screen.getByRole('button', { name: /add/i })).toBeInTheDocument()
    expect(screen.queryByRole('img', { name: /premium content/i })).not.toBeInTheDocument()
  })
})
