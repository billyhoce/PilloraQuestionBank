import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import ImportPage from './ImportPage'

function Where() {
  return <div data-testid="where">{useLocation().pathname}</div>
}

const renderAt = () => render(
  <MemoryRouter initialEntries={['/admin/import']}>
    <Routes>
      <Route path="/admin/import" element={<ImportPage />} />
      <Route path="/admin/import/*" element={<Where />} />
    </Routes>
  </MemoryRouter>,
)

beforeEach(() => sessionStorage.clear())

describe('ImportPage (/admin/import)', () => {
  it('opens Auto import by default', () => {
    renderAt()
    expect(screen.getByTestId('where')).toHaveTextContent('/admin/import/auto')
  })

  it('reopens Manual import when one is in progress', () => {
    sessionStorage.setItem('pillora_import_session', '{"step":"review"}')
    renderAt()
    expect(screen.getByTestId('where')).toHaveTextContent('/admin/import/manual')
  })
})
