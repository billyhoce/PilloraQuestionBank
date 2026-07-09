import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'

describe('test infrastructure', () => {
  it('renders a component into jsdom', () => {
    render(<div>hello</div>)
    expect(screen.getByText('hello')).toBeInTheDocument()
  })
})
