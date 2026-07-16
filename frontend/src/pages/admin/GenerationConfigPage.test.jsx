import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import GenerationConfigPage from './GenerationConfigPage'
import { api } from '../../api/client'

vi.mock('../../api/client', () => ({
  api: {
    generationConfig: { get: vi.fn(), update: vi.fn() },
    coverTitles: {
      list: vi.fn(),
      create: vi.fn(),
      update: vi.fn(),
      delete: vi.fn(),
    },
  },
}))

// Same stand-in as the GeneratePage tests — TipTap doesn't run under jsdom.
vi.mock('../../components/generate/CoverBodyEditor', () => ({
  default: ({ value, onChange }) => (
    <textarea
      aria-label="Cover letter / message"
      value={value ?? ''}
      onChange={e => onChange(e.target.value)}
    />
  ),
}))

const CONFIG = {
  titles: [{ id: 1, name: 'Topical Worksheets' }],
  subtitle1_placeholder: 'eg) subtitle 1',
  subtitle2_placeholder: 'eg) subtitle 2',
  cover_body: '<p>Dear students,</p>',
  header_text: 'Answer all questions.',
  footer_text: 'Pillora 2026',
}

function renderPage() {
  render(
    <MemoryRouter>
      <GenerationConfigPage />
    </MemoryRouter>
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  api.generationConfig.get.mockResolvedValue(CONFIG)
  api.generationConfig.update.mockResolvedValue(CONFIG)
})

describe('GenerationConfigPage', () => {
  it('loads and prefills the presets form and title list', async () => {
    renderPage()
    expect(await screen.findByDisplayValue('eg) subtitle 1')).toBeInTheDocument()
    expect(screen.getByDisplayValue('eg) subtitle 2')).toBeInTheDocument()
    expect(screen.getByDisplayValue(CONFIG.cover_body)).toBeInTheDocument()
    expect(screen.getByDisplayValue('Answer all questions.')).toBeInTheDocument()
    expect(screen.getByDisplayValue('Pillora 2026')).toBeInTheDocument()
    expect(screen.getByText('Topical Worksheets')).toBeInTheDocument()
  })

  it('saves the edited presets via PUT and shows a success notice', async () => {
    const user = userEvent.setup()
    renderPage()
    const footer = await screen.findByLabelText(/footer/i)
    await user.clear(footer)
    await user.type(footer, 'New footer')
    await user.click(screen.getByRole('button', { name: /save presets/i }))
    await waitFor(() => expect(api.generationConfig.update).toHaveBeenCalledTimes(1))
    expect(api.generationConfig.update).toHaveBeenCalledWith({
      subtitle1_placeholder: 'eg) subtitle 1',
      subtitle2_placeholder: 'eg) subtitle 2',
      cover_body: CONFIG.cover_body,
      header_text: 'Answer all questions.',
      footer_text: 'New footer',
    })
    expect(await screen.findByText(/generation config saved/i)).toBeInTheDocument()
  })

  it('shows a warning notice when saving fails', async () => {
    const user = userEvent.setup()
    api.generationConfig.update.mockRejectedValue({ message: 'Admin access required.' })
    renderPage()
    await screen.findByLabelText(/footer/i)
    await user.click(screen.getByRole('button', { name: /save presets/i }))
    expect(await screen.findByText(/admin access required/i)).toBeInTheDocument()
  })

  it('creates a cover title and refreshes the list', async () => {
    const user = userEvent.setup()
    api.coverTitles.create.mockResolvedValue({ id: 2, name: 'Revision Pack' })
    api.coverTitles.list.mockResolvedValue([...CONFIG.titles, { id: 2, name: 'Revision Pack' }])
    renderPage()
    await user.click(await screen.findByRole('button', { name: /\+ add cover title/i }))
    // The modal's Name input autofocuses, so keyboard input lands in it.
    await user.keyboard('Revision Pack')
    await user.click(screen.getByRole('button', { name: /^save$/i }))
    await waitFor(() => expect(api.coverTitles.create).toHaveBeenCalledWith('Revision Pack'))
    expect(await screen.findByText('Revision Pack')).toBeInTheDocument()
  })

  it('deletes a cover title after confirmation', async () => {
    const user = userEvent.setup()
    api.coverTitles.delete.mockResolvedValue(null)
    api.coverTitles.list.mockResolvedValue([])
    renderPage()
    await screen.findByText('Topical Worksheets')
    await user.click(screen.getByRole('button', { name: /delete/i }))
    // ConfirmDialog opens; confirm the deletion.
    const dialogButtons = await screen.findAllByRole('button', { name: /delete/i })
    await user.click(dialogButtons[dialogButtons.length - 1])
    await waitFor(() => expect(api.coverTitles.delete).toHaveBeenCalledWith(1))
  })
})
