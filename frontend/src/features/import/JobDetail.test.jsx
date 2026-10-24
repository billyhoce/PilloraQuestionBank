import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import JobDetail from './JobDetail'
import { api } from '../../api/client'

vi.mock('../../api/client', () => ({ api: { import: { getJob: vi.fn() } } }))

const ID = '0b1c2d3e-0000-4000-8000-000000000001'

beforeEach(() => {
  vi.clearAllMocks()
  api.import.getJob.mockResolvedValue({ id: ID, filename: 'a.pdf', tasks: [] })
})

describe('JobDetail', () => {
  it('shows the job id and copies it', async () => {
    const writeText = vi.fn().mockResolvedValue()
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    render(<JobDetail jobId={ID} version={0} />)
    expect(await screen.findByText(ID)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Copy' }))
    expect(writeText).toHaveBeenCalledWith(ID)
    expect(await screen.findByRole('button', { name: 'Copied' })).toBeInTheDocument()
  })
})
