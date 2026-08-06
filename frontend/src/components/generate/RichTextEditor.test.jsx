import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import RichTextEditor from './RichTextEditor'

describe('RichTextEditor', () => {
  it('renders the toolbar and fills in externally-arriving defaults', async () => {
    const onChange = vi.fn()
    const { rerender } = render(
      <RichTextEditor label="Cover letter / message" value={null} onChange={onChange} />
    )
    expect(await screen.findByTitle('Bold')).toBeInTheDocument()
    expect(screen.getByTitle('Italic')).toBeInTheDocument()
    expect(screen.getByTitle('Underline')).toBeInTheDocument()
    expect(screen.getByTitle('Add link')).toBeInTheDocument()

    // Defaults arrive after mount (the config fetch resolving).
    rerender(
      <RichTextEditor
        label="Cover letter / message"
        value={'<p>Dear students,</p><p>Visit <a href="https://www.pillora.com.sg">the site</a>.</p>'}
        onChange={onChange}
      />
    )
    const editor = await screen.findByLabelText('Cover letter / message')
    await waitFor(() => expect(editor.textContent).toContain('Dear students,'))
    const link = editor.querySelector('a')
    expect(link).not.toBeNull()
    expect(link.getAttribute('href')).toBe('https://www.pillora.com.sg')
  })

  it('labels each instance from its label prop, so one page can host several', async () => {
    const onChange = vi.fn()
    render(
      <>
        <RichTextEditor label="Header" value="<p>Branding</p>" onChange={onChange} />
        <RichTextEditor label="Footer" value="<p>Small print</p>" onChange={onChange} />
      </>
    )
    expect(await screen.findByLabelText('Header')).toBeInTheDocument()
    expect(screen.getByLabelText('Footer')).toBeInTheDocument()
  })
})
