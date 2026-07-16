import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import PapersList from './PapersList'
import { api } from '../../api/client'

vi.mock('../../api/client', () => ({
  api: {
    papers: { list: vi.fn(), setPremium: vi.fn(), remove: vi.fn() },
  },
}))

const papers = [
  {
    id: 7, subject_name: 'Math', stream_name: 'G3', level_name: 'Sec 3',
    school_name: 'RI', exam_type_name: 'EOY', year: 2024, paper_number: '1',
    question_count: 5, is_premium: false,
  },
]

function renderList() {
  return render(
    <MemoryRouter>
      <PapersList />
    </MemoryRouter>
  )
}

describe('PapersList premium checkbox', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.papers.list.mockResolvedValue({ items: papers, total: 1 })
  })

  it('toggling the checkbox calls setPremium and updates the row', async () => {
    const user = userEvent.setup()
    api.papers.setPremium.mockResolvedValue({ id: 7, is_premium: true })
    renderList()

    const checkbox = await screen.findByRole('checkbox', { name: /premium/i })
    expect(checkbox).not.toBeChecked()

    await user.click(checkbox)
    await waitFor(() => expect(api.papers.setPremium).toHaveBeenCalledWith(7, true))
    expect(screen.getByRole('checkbox', { name: /premium/i })).toBeChecked()
  })

  it('reverts and shows an error when setPremium fails', async () => {
    const user = userEvent.setup()
    api.papers.setPremium.mockRejectedValue({ message: 'Update failed.' })
    renderList()

    const checkbox = await screen.findByRole('checkbox', { name: /premium/i })
    await user.click(checkbox)

    await waitFor(() => expect(screen.getByText('Update failed.')).toBeInTheDocument())
    expect(screen.getByRole('checkbox', { name: /premium/i })).not.toBeChecked()
  })
})
