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
      generationConfig: { get: vi.fn() },
      generate: {
        select: vi.fn(),
        paper: vi.fn(),
      },
    },
  }
})

// The page reads the viewer's role from useAuth to decide which cover controls
// to render; swap the role per test via this mutable auth state.
const authState = vi.hoisted(() => ({ user: { id: 1, role: 'public' } }))
vi.mock('../context/AuthContext', () => ({ useAuth: () => authState }))

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

const CONFIG = {
  titles: [
    { id: 1, name: 'Topical Worksheets' },
    { id: 2, name: 'Revision Pack' },
  ],
  subtitle1_placeholder: 'eg) subtitle 1',
  subtitle2_placeholder: 'eg) subtitle 2',
  cover_body: '<p>Dear students,</p><p>Practise well.</p>',
  header_text: 'Config header',
  footer_text: 'Config footer',
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

describe('GeneratePage PDF output mode (non-admin)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    authState.user = { id: 1, role: 'public' }
    api.questions.list.mockResolvedValue({ items: [item], total: 1 })
    api.generationConfig.get.mockResolvedValue(CONFIG)
    api.generate.paper.mockResolvedValue(new Blob(['%PDF'], { type: 'application/pdf' }))
    globalThis.URL.createObjectURL = vi.fn(() => 'blob:fake')
    globalThis.URL.revokeObjectURL = vi.fn()
  })

  it('defaults to the combined PDF option', async () => {
    await renderWithCartItem()
    expect(screen.getByRole('radio', { name: /1 combined pdf/i })).toBeChecked()
    expect(screen.getByRole('radio', { name: /separate question & answer/i })).not.toBeChecked()
  })

  it('makes a single combined request with only the user-editable fields', async () => {
    const user = await renderWithCartItem()
    // Wait for the config to land so the payload is deterministic.
    await screen.findByRole('option', { name: 'Topical Worksheets' })
    await user.click(screen.getByRole('button', { name: /generate pdf/i }))
    await waitFor(() => expect(api.generate.paper).toHaveBeenCalledTimes(1))
    // Body, header, footer, and include_cover are server-side presets for
    // non-admins, so the request carries none of them.
    expect(api.generate.paper).toHaveBeenCalledWith({
      question_ids: [1],
      variant: 'combined',
      cover_title: 'Topical Worksheets',
      cover_subtitle1: '',
      cover_subtitle2: '',
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

  it('omits the cover title when the config fetch fails', async () => {
    api.generationConfig.get.mockRejectedValue(new Error('network'))
    const user = await renderWithCartItem()
    await user.click(screen.getByRole('button', { name: /generate pdf/i }))
    await waitFor(() => expect(api.generate.paper).toHaveBeenCalledTimes(1))
    const [body] = api.generate.paper.mock.calls[0]
    // No title sent — the server falls back to the first configured title.
    expect(body).not.toHaveProperty('cover_title')
    expect(body).not.toHaveProperty('cover_body')
    expect(body).not.toHaveProperty('include_cover')
  })
})

describe('GeneratePage cover controls (non-admin)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    authState.user = { id: 1, role: 'public' }
    api.questions.list.mockResolvedValue({ items: [item], total: 1 })
    api.generationConfig.get.mockResolvedValue(CONFIG)
  })

  it('offers a title dropdown of configured titles, defaulting to the first', async () => {
    render(
      <MemoryRouter>
        <GeneratePage />
      </MemoryRouter>
    )
    const select = await screen.findByRole('combobox', { name: /title/i })
    await screen.findByRole('option', { name: 'Topical Worksheets' })
    expect(select).toHaveValue('Topical Worksheets')
    // Only the configured titles — no free-text ("Custom…") escape hatch.
    expect(screen.queryByRole('option', { name: /custom/i })).not.toBeInTheDocument()
  })

  it('shows the configured subtitle placeholders and hides admin-only controls', async () => {
    render(
      <MemoryRouter>
        <GeneratePage />
      </MemoryRouter>
    )
    expect(await screen.findByPlaceholderText('eg) subtitle 1')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('eg) subtitle 2')).toBeInTheDocument()
    // Cover is always included: no toggle, and no body/header/footer editors.
    expect(screen.queryByRole('checkbox', { name: /include cover page/i })).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/cover letter \/ message/i)).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/header \/ instructions/i)).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/footer/i)).not.toBeInTheDocument()
  })

  it('disables the title dropdown when no titles are configured', async () => {
    api.generationConfig.get.mockResolvedValue({ ...CONFIG, titles: [] })
    render(
      <MemoryRouter>
        <GeneratePage />
      </MemoryRouter>
    )
    await waitFor(() => expect(api.generationConfig.get).toHaveBeenCalled())
    const select = await screen.findByRole('combobox', { name: /title/i })
    await waitFor(() => expect(select).toBeDisabled())
  })
})

describe('GeneratePage cover controls (admin)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    authState.user = { id: 9, role: 'admin' }
    api.questions.list.mockResolvedValue({ items: [item], total: 1 })
    api.generationConfig.get.mockResolvedValue(CONFIG)
    api.generate.paper.mockResolvedValue(new Blob(['%PDF'], { type: 'application/pdf' }))
    globalThis.URL.createObjectURL = vi.fn(() => 'blob:fake')
    globalThis.URL.revokeObjectURL = vi.fn()
  })

  it('prefills body, header, and footer from the config', async () => {
    render(
      <MemoryRouter>
        <GeneratePage />
      </MemoryRouter>
    )
    expect(await screen.findByDisplayValue(CONFIG.cover_body)).toBeInTheDocument()
    expect(screen.getByLabelText(/header \/ instructions/i)).toHaveValue('Config header')
    expect(screen.getByLabelText(/footer/i)).toHaveValue('Config footer')
    expect(screen.getByRole('checkbox', { name: /include cover page/i })).toBeChecked()
  })

  it('sends the full payload including footer_text and include_cover', async () => {
    const user = await renderWithCartItem()
    await screen.findByDisplayValue(CONFIG.cover_body)
    await user.click(screen.getByRole('button', { name: /generate pdf/i }))
    await waitFor(() => expect(api.generate.paper).toHaveBeenCalledTimes(1))
    expect(api.generate.paper).toHaveBeenCalledWith({
      question_ids: [1],
      variant: 'combined',
      header_text: 'Config header',
      footer_text: 'Config footer',
      include_cover: true,
      cover_title: 'Topical Worksheets',
      cover_subtitle1: '',
      cover_subtitle2: '',
      cover_body: CONFIG.cover_body,
    })
  })

  it('separate mode sends the header only on the question request', async () => {
    const user = await renderWithCartItem()
    await screen.findByDisplayValue(CONFIG.cover_body)
    await user.click(screen.getByRole('radio', { name: /separate question & answer/i }))
    await user.click(screen.getByRole('button', { name: /generate pdf/i }))
    await waitFor(() => expect(api.generate.paper).toHaveBeenCalledTimes(2))
    const [[questionBody], [answerBody]] = api.generate.paper.mock.calls
    expect(questionBody.variant).toBe('question')
    expect(questionBody.header_text).toBe('Config header')
    expect(answerBody.variant).toBe('answer')
    expect(answerBody.header_text).toBe('')
  })

  it('allows a free-text title via the Custom… option', async () => {
    const user = await renderWithCartItem()
    await screen.findByDisplayValue(CONFIG.cover_body)
    await user.selectOptions(screen.getByRole('combobox', { name: /title/i }), 'Custom…')
    await user.type(screen.getByPlaceholderText('Custom title'), 'My Own Title')
    await user.click(screen.getByRole('button', { name: /generate pdf/i }))
    await waitFor(() => expect(api.generate.paper).toHaveBeenCalledTimes(1))
    const [body] = api.generate.paper.mock.calls[0]
    expect(body.cover_title).toBe('My Own Title')
  })

  it('can generate without a cover page', async () => {
    const user = await renderWithCartItem()
    await screen.findByDisplayValue(CONFIG.cover_body)
    await user.click(screen.getByRole('checkbox', { name: /include cover page/i }))
    await user.click(screen.getByRole('button', { name: /generate pdf/i }))
    await waitFor(() => expect(api.generate.paper).toHaveBeenCalledTimes(1))
    const [body] = api.generate.paper.mock.calls[0]
    expect(body.include_cover).toBe(false)
  })
})

describe('GeneratePage autocreate target & algorithm', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    authState.user = { id: 1, role: 'public' }
    api.questions.list.mockResolvedValue({ items: [item], total: 1 })
    api.generationConfig.get.mockResolvedValue(CONFIG)
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
    authState.user = { id: 1, role: 'public' }
    api.generationConfig.get.mockResolvedValue(CONFIG)
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

  it('excludes a locked (premium) item from the cart', async () => {
    const user = userEvent.setup()
    const lockedItem = { ...itemB, locked: true }
    api.questions.list.mockResolvedValue({ items: [item, lockedItem], total: 2 })
    render(
      <MemoryRouter>
        <GeneratePage />
      </MemoryRouter>
    )
    await user.click(await screen.findByRole('button', { name: /select all/i }))
    // Only the unlocked item lands in the cart; the premium one is reported as skipped.
    await waitFor(() => expect(screen.getByRole('heading', { name: /selection \(1\)/i })).toBeInTheDocument())
    expect(screen.getByText(/1 premium skipped/i)).toBeInTheDocument()
  })
})

describe('GeneratePage premium generate guard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    authState.user = { id: 1, role: 'public' }
    api.questions.list.mockResolvedValue({ items: [item], total: 1 })
    api.generationConfig.get.mockResolvedValue(CONFIG)
  })

  it('a locked question cannot be added to the cart (shows Subscribe, not Add)', async () => {
    // isLocked is deterministic per item, so a locked question never exposes an
    // Add control — the belt-and-braces guard against generating with premium
    // content. Select All also skips it, so a locked item cannot reach the cart.
    const lockedItem = { ...item, locked: true }
    api.questions.list.mockResolvedValue({ items: [lockedItem], total: 1 })
    render(
      <MemoryRouter>
        <GeneratePage />
      </MemoryRouter>
    )
    expect(await screen.findByRole('link', { name: /subscribe/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /\+ add/i })).not.toBeInTheDocument()
  })

  it('maps a 403 from generate to the premium warning and shows no crash notice', async () => {
    const user = await renderWithCartItem()
    await screen.findByRole('option', { name: 'Topical Worksheets' })
    // /generate/paper has no admin gate — a 403 there is always the premium block.
    api.generate.paper.mockRejectedValue({ status: 403, message: 'Premium content requires a premium subscription' })
    await user.click(screen.getByRole('button', { name: /generate pdf/i }))
    await waitFor(() =>
      expect(screen.getByText(/includes premium questions/i)).toBeInTheDocument()
    )
  })
})
