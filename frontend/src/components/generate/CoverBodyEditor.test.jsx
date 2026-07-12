import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import CoverBodyEditor from './CoverBodyEditor'

describe('CoverBodyEditor', () => {
  it('renders the toolbar and fills in externally-arriving defaults', async () => {
    const onChange = vi.fn()
    const { rerender } = render(<CoverBodyEditor value={null} onChange={onChange} />)
    expect(await screen.findByTitle('Bold')).toBeInTheDocument()
    expect(screen.getByTitle('Italic')).toBeInTheDocument()
    expect(screen.getByTitle('Underline')).toBeInTheDocument()
    expect(screen.getByTitle('Add link')).toBeInTheDocument()

    // Defaults arrive after mount (the cover-defaults fetch resolving).
    rerender(
      <CoverBodyEditor
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
})
