import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import TagCombobox from './TagCombobox'

const tags = [
  { id: 1, name: 'Challenging' },
  { id: 2, name: 'Graphing' },
  { id: 3, name: 'Exam-Favourite' },
]

describe('TagCombobox', () => {
  it('lists all tag names on focus', async () => {
    const user = userEvent.setup()
    render(<TagCombobox tags={tags} selectedIds={[]} onAdd={() => {}} />)

    await user.click(screen.getByRole('textbox'))
    expect(screen.getByText('Challenging')).toBeInTheDocument()
    expect(screen.getByText('Graphing')).toBeInTheDocument()
    expect(screen.getByText('Exam-Favourite')).toBeInTheDocument()
  })

  it('filters by typed keyword', async () => {
    const user = userEvent.setup()
    render(<TagCombobox tags={tags} selectedIds={[]} onAdd={() => {}} />)

    await user.type(screen.getByRole('textbox'), 'graph')
    expect(screen.getByText('Graphing')).toBeInTheDocument()
    expect(screen.queryByText('Challenging')).not.toBeInTheDocument()
  })

  it('excludes already-selected tags', async () => {
    const user = userEvent.setup()
    render(<TagCombobox tags={tags} selectedIds={[1]} onAdd={() => {}} />)

    await user.click(screen.getByRole('textbox'))
    expect(screen.queryByText('Challenging')).not.toBeInTheDocument()
    expect(screen.getByText('Graphing')).toBeInTheDocument()
  })

  it('calls onAdd with the picked tag on click', async () => {
    const user = userEvent.setup()
    const onAdd = vi.fn()
    render(<TagCombobox tags={tags} selectedIds={[]} onAdd={onAdd} />)

    await user.click(screen.getByRole('textbox'))
    await user.click(screen.getByText('Graphing'))
    expect(onAdd).toHaveBeenCalledWith({ id: 2, name: 'Graphing' })
  })

  it('picks the active option on Enter', async () => {
    const user = userEvent.setup()
    const onAdd = vi.fn()
    render(<TagCombobox tags={tags} selectedIds={[]} onAdd={onAdd} />)

    await user.type(screen.getByRole('textbox'), 'exam')
    await user.keyboard('{Enter}')
    expect(onAdd).toHaveBeenCalledWith({ id: 3, name: 'Exam-Favourite' })
  })
})
