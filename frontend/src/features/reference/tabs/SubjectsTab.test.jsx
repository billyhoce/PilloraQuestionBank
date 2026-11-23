import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import SubjectsTab from './SubjectsTab'

const ROWS = [{ id: 1, name: 'E Math', code: '4052' }, { id: 2, name: 'Art', code: null }]

function renderTab() {
  const handlers = { onCreate: vi.fn().mockResolvedValue(), onUpdate: vi.fn().mockResolvedValue(), onDelete: vi.fn() }
  render(<SubjectsTab rows={ROWS} loading={false} {...handlers} />)
  return handlers
}

describe('SubjectsTab', () => {
  it('lists each subject with its code', () => {
    renderTab()
    expect(screen.getByRole('row', { name: /E Math 4052/ })).toBeInTheDocument()
    expect(screen.getByRole('row', { name: /Art —/ })).toBeInTheDocument()
  })

  it('adds a subject with a code', async () => {
    const { onCreate } = renderTab()
    await userEvent.click(screen.getByRole('button', { name: '+ Add Subject' }))
    await userEvent.type(screen.getByLabelText('Name'), 'A Math')
    await userEvent.type(screen.getByLabelText('Code (optional)'), ' 4049 ')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(onCreate).toHaveBeenCalledWith('A Math', '4049')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('edits a subject, pre-filled, and a cleared code is sent as none', async () => {
    const { onUpdate } = renderTab()
    await userEvent.click(screen.getAllByRole('button', { name: 'Edit' })[0])
    expect(screen.getByLabelText('Name')).toHaveValue('E Math')
    expect(screen.getByLabelText('Code (optional)')).toHaveValue('4052')
    await userEvent.clear(screen.getByLabelText('Code (optional)'))
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(onUpdate).toHaveBeenCalledWith(1, 'E Math', null)
  })
})
