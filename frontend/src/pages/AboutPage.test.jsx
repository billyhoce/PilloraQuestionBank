import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AboutPage from './AboutPage'
import { api } from '../api/client'
import { useAuth } from '../context/AuthContext'
import { useSiteConfig } from '../context/SiteConfigContext'

vi.mock('../api/client', () => ({ api: { siteConfig: { update: vi.fn() } } }))
vi.mock('../context/AuthContext', () => ({ useAuth: vi.fn() }))
vi.mock('../context/SiteConfigContext', () => ({ useSiteConfig: vi.fn() }))
// The TipTap editor needs a real ProseMirror view; the page's own behaviour is
// what's under test, so stand it in with a textarea exposing the same contract.
vi.mock('../components/RichContentEditor', () => ({
  default: ({ value, onChange, label }) => (
    <textarea aria-label={label} value={value} onChange={(e) => onChange(e.target.value)} />
  ),
}))

const setConfig = vi.fn()

function setup({ role = 'public', aboutContent = '<p>Hello there</p>', loading = false } = {}) {
  useAuth.mockReturnValue({ user: role ? { role } : null })
  useSiteConfig.mockReturnValue({ aboutContent, loading, setConfig })
  return render(<AboutPage />)
}

beforeEach(() => vi.clearAllMocks())

describe('AboutPage rendering', () => {
  it('renders the stored HTML as markup, not as text', () => {
    const { container } = setup({ aboutContent: '<h2>Who we are</h2><ul><li>One</li></ul>' })
    // Sanitized server-side on write, so rendering it as HTML is the point.
    expect(container.querySelector('h2')).toHaveTextContent('Who we are')
    expect(container.querySelector('li')).toHaveTextContent('One')
  })

  it('shows a placeholder when nothing has been written', () => {
    setup({ aboutContent: '' })
    expect(screen.getByText('Nothing here yet.')).toBeInTheDocument()
  })

  it('is readable signed out', () => {
    setup({ role: null })
    expect(screen.getByText('Hello there')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /edit page/i })).not.toBeInTheDocument()
  })
})

describe('AboutPage editing', () => {
  it('hides the Edit button from non-admins', () => {
    setup({ role: 'public' })
    expect(screen.queryByRole('button', { name: /edit page/i })).not.toBeInTheDocument()
  })

  it('lets an admin edit and save, storing what the server returned', async () => {
    const user = userEvent.setup()
    // The server sanitizes on write, so the response — not the draft — is truth.
    api.siteConfig.update.mockResolvedValue({
      about_content: '<p>Clean</p>',
      protect_images: false,
    })
    setup({ role: 'admin', aboutContent: '<p>Before</p>' })

    await user.click(screen.getByRole('button', { name: /edit page/i }))
    const editor = screen.getByLabelText('About page content')
    expect(editor).toHaveValue('<p>Before</p>') // seeded from the loaded config

    await user.clear(editor)
    await user.type(editor, 'After')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(api.siteConfig.update).toHaveBeenCalledWith({
      about_content: 'After',
    }))
    // Only about_content is sent — the image toggle lives on another page and
    // must not be overwritten from here.
    expect(setConfig).toHaveBeenCalledWith({ about_content: '<p>Clean</p>', protect_images: false })
    expect(await screen.findByText('About page saved.')).toBeInTheDocument()
  })

  it('keeps the editor open and reports the error when saving fails', async () => {
    const user = userEvent.setup()
    api.siteConfig.update.mockRejectedValue({ message: 'Server unavailable' })
    setup({ role: 'admin' })

    await user.click(screen.getByRole('button', { name: /edit page/i }))
    await user.click(screen.getByRole('button', { name: 'Save' }))

    expect(await screen.findByText('Server unavailable')).toBeInTheDocument()
    expect(screen.getByLabelText('About page content')).toBeInTheDocument()
  })

  it('discards the draft on cancel', async () => {
    const user = userEvent.setup()
    setup({ role: 'admin', aboutContent: '<p>Original</p>' })

    await user.click(screen.getByRole('button', { name: /edit page/i }))
    await user.type(screen.getByLabelText('About page content'), ' edited')
    await user.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(api.siteConfig.update).not.toHaveBeenCalled()
    expect(screen.getByText('Original')).toBeInTheDocument()

    // Re-opening seeds from the config again, not from the abandoned draft.
    await user.click(screen.getByRole('button', { name: /edit page/i }))
    expect(screen.getByLabelText('About page content')).toHaveValue('<p>Original</p>')
  })
})
