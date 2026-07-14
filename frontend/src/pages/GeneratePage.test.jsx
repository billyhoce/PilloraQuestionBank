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
        coverDefaults: vi.fn(),
        select: vi.fn(),
        paper: vi.fn(),
      },
    },
  }
})

// The TipTap editor doesn't run reliably under jsdom; these tests target the
// page's request behavior, so stand in a plain textarea with the same contract.
vi.mock('../components/generate/CoverBodyEditor', () => ({
  default: ({ value, onChange }) => (
    <textarea
      aria-label="Cover letter / message"
      value={value ?? ''}
      onChange={e => onChange(e.target.value)}
    />
  ),
}))

const COVER_DEFAULTS = {
  cover_title: 'Topical Worksheets',
  cover_body: '<p>Dear students,</p><p>Practise well.</p>',
}

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
    api.generate.coverDefaults.mockResolvedValue(COVER_DEFAULTS)
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
    // Wait for the fetched cover defaults to land so the payload is deterministic.
    await screen.findByDisplayValue(COVER_DEFAULTS.cover_body)
    await user.click(screen.getByRole('button', { name: /generate pdf/i }))
    await waitFor(() => expect(api.generate.paper).toHaveBeenCalledTimes(1))
    expect(api.generate.paper).toHaveBeenCalledWith({
      question_ids: [1],
      variant: 'combined',
      header_text: '',
      include_cover: true,
      cover_title: COVER_DEFAULTS.cover_title,
      cover_subtitle1: '',
      cover_subtitle2: '',
      cover_body: COVER_DEFAULTS.cover_body,
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

  it('omits cover title/body when the defaults fetch fails', async () => {
    api.generate.coverDefaults.mockRejectedValue(new Error('network'))
    const user = await renderWithCartItem()
    await user.click(screen.getByRole('button', { name: /generate pdf/i }))
    await waitFor(() => expect(api.generate.paper).toHaveBeenCalledTimes(1))
    const [body] = api.generate.paper.mock.calls[0]
    expect(body).not.toHaveProperty('cover_title')
    expect(body).not.toHaveProperty('cover_body')
    expect(body.include_cover).toBe(true)
  })
})

describe('GeneratePage autocreate target & algorithm', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.questions.list.mockResolvedValue({ items: [item], total: 1 })
    api.generate.coverDefaults.mockResolvedValue(COVER_DEFAULTS)
    api.generate.select.mockResolvedValue({ items: [item], total_marks: 5, count: 1, exact: true, warning: null })
  })

  it('defaults to Random + selecting by number of questions', async () => {
    render(
      <MemoryRouter>
        <GeneratePage />
      </MemoryRouter>
    )
    expect(await screen.findByRole('radio', { name: /^random$/i })).toBeChecked()
    expect(screen.getByRole('radio', { name: /^in-order$/i })).not.toBeChecked()
    expect(screen.getByLabelText(/select by/i)).toHaveValue('count')
    expect(screen.getByLabelText(/number of questions/i)).toBeInTheDocument()
  })

  it('sends target_type "count" and algorithm "random" by default', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <GeneratePage />
      </MemoryRouter>
    )
    await user.type(await screen.findByLabelText(/number of questions/i), '5')
    await user.click(screen.getByRole('button', { name: /autocreate paper/i }))
    await waitFor(() => expect(api.generate.select).toHaveBeenCalledTimes(1))
    const [body] = api.generate.select.mock.calls[0]
    expect(body.target_type).toBe('count')
    expect(body.target_value).toBe(5)
    expect(body.algorithm).toBe('random')
  })

  it('sends target_type "marks" and algorithm "in-order" when chosen', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <GeneratePage />
      </MemoryRouter>
    )
    await user.selectOptions(await screen.findByLabelText(/select by/i), 'marks')
    await user.click(screen.getByRole('radio', { name: /^in-order$/i }))
    await user.type(screen.getByLabelText(/target marks/i), '20')
    await user.click(screen.getByRole('button', { name: /autocreate paper/i }))
    await waitFor(() => expect(api.generate.select).toHaveBeenCalledTimes(1))
    const [body] = api.generate.select.mock.calls[0]
    expect(body.target_type).toBe('marks')
    expect(body.target_value).toBe(20)
    expect(body.algorithm).toBe('in-order')
  })
})

describe('GeneratePage Select All', () => {
  const itemB = { ...item, id: 2, question_number: 4 }

  beforeEach(() => {
    vi.clearAllMocks()
    api.generate.coverDefaults.mockResolvedValue(COVER_DEFAULTS)
  })

  it('adds matching questions to the cart', async () => {
    const user = userEvent.setup()
    api.questions.list.mockResolvedValue({ items: [item, itemB], total: 2 })
    render(
      <MemoryRouter>
        <GeneratePage />
      </MemoryRouter>
    )
    await user.click(await screen.findByRole('button', { name: /select all/i }))
    await waitFor(() => expect(screen.getByRole('heading', { name: /selection \(2\)/i })).toBeInTheDocument())
    expect(screen.getByText(/added 2 questions/i)).toBeInTheDocument()
  })

  it('warns when there are more matches than the limit', async () => {
    const user = userEvent.setup()
    api.questions.list.mockResolvedValue({ items: [item, itemB], total: 120 })
    render(
      <MemoryRouter>
        <GeneratePage />
      </MemoryRouter>
    )
    await user.click(await screen.findByRole('button', { name: /select all/i }))
    await waitFor(() => expect(screen.getByText(/select all limit/i)).toBeInTheDocument())
  })
})
