import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import GeneratePage from './GeneratePage'
import { api } from '../api/client'

vi.mock('../api/client', () => {
  const list = vi.fn().mockResolvedValue([])
  return {
    api: {
      levels: { list },
      streams: { list },
      subjects: { list },
      schools: { list },
      examTypes: { list },
      schoolLevels: { list },
      tags: { list },
      topics: { list: vi.fn().mockResolvedValue([]) },
      papers: { years: vi.fn().mockResolvedValue([]) },
      questions: { list: vi.fn() },
      generate: {
        select: vi.fn(),
        paper: vi.fn(),
      },
    },
  }
})

const item = {
  id: 1,
  question_number: 3,
  marks: 5,
  first_page_url: null,
  paper_info: { school_name: 'Raffles Institution', year: 2024, exam_type_name: 'EOY', paper_number: '1' },
  topics: [],
}

async function renderWithCartItem() {
  const user = userEvent.setup()
  render(
    <MemoryRouter>
      <GeneratePage />
    </MemoryRouter>
  )
  // Add the sole listed question to the selection cart.
  await user.click(await screen.findByRole('button', { name: /\+ add/i }))
  return user
}

describe('GeneratePage PDF output mode', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.questions.list.mockResolvedValue({ items: [item], total: 1 })
    api.generate.paper.mockResolvedValue(new Blob(['%PDF'], { type: 'application/pdf' }))
    globalThis.URL.createObjectURL = vi.fn(() => 'blob:fake')
    globalThis.URL.revokeObjectURL = vi.fn()
  })

  it('defaults to the combined PDF option', async () => {
    await renderWithCartItem()
    expect(screen.getByRole('radio', { name: /1 combined pdf/i })).toBeChecked()
    expect(screen.getByRole('radio', { name: /separate question & answer/i })).not.toBeChecked()
  })

  it('makes a single combined request by default', async () => {
    const user = await renderWithCartItem()
    await user.click(screen.getByRole('button', { name: /generate pdf/i }))
    await waitFor(() => expect(api.generate.paper).toHaveBeenCalledTimes(1))
    expect(api.generate.paper).toHaveBeenCalledWith({
      question_ids: [1],
      variant: 'combined',
      header_text: '',
    })
  })

  it('makes separate question and answer requests when selected', async () => {
    const user = await renderWithCartItem()
    await user.click(screen.getByRole('radio', { name: /separate question & answer/i }))
    await user.click(screen.getByRole('button', { name: /generate pdf/i }))
    await waitFor(() => expect(api.generate.paper).toHaveBeenCalledTimes(2))
    const variants = api.generate.paper.mock.calls.map(([body]) => body.variant)
    expect(variants).toEqual(['question', 'answer'])
  })
})
