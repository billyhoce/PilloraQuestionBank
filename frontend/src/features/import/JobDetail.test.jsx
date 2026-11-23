import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
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

  it('shows no cost line for a job that made no Claude calls', async () => {
    render(<JobDetail jobId={ID} version={0} />)
    await screen.findByText(ID)
    expect(screen.queryByText(/Claude cost/)).toBeNull()
  })

  it('breaks the Claude cost down per call, tagging calls from a retry', async () => {
    const call = (id, kind, extra) => ({
      id, kind, paper_key: null, source: null, run: 0, attempt: 1, model: 'claude-haiku-4-5',
      input_tokens: 100, output_tokens: 10, cache_write: 0, cache_hit: 0, cost_usd: 0.001, ...extra,
    })
    api.import.getJob.mockResolvedValue({
      id: ID, filename: 'a.pdf', tasks: [],
      cost: {
        total_usd: 0.3849, calls: 3, input_tokens: 48310, output_tokens: 3114, cache_write: 0, cache_hit: 20, unpriced: false,
        items: [
          call(1, 'segment', { input_tokens: 48210, output_tokens: 3104, cost_usd: 0.0637, cache_hit: 20 }),
          call(2, 'segment', { model: 'claude-opus-5', cost_usd: 0.3131, run: 1 }),
          call(3, 'metadata', { paper_key: 'q1', source: 'cover', cost_usd: 0.0081, run: 1 }),
        ],
      },
    })
    render(<JobDetail jobId={ID} version={0} />)
    expect(await screen.findByText(/Claude cost:/)).toHaveTextContent('Claude cost: $0.3849 · 3 calls')
    const rows = within(screen.getByRole('table', { name: 'Claude calls' })).getAllByRole('row')
    expect(rows.map(r => [...r.cells].map(c => c.textContent))).toEqual([
      ['Call', 'Model', 'In (cached)', 'Out', 'Cost'],
      ['Find papers in booklet', 'Haiku', '48,210 (+20)', '3,104', '$0.0637'],
      ['Find papers in booklet' + 'retry 1', 'Opus', '100', '10', '$0.3131'],
      ['Paper q1 metadata (from cover)' + 'retry 1', 'Haiku', '100', '10', '$0.0081'],
      ['Total', '', '48,310 (+20)', '3,114', '$0.3849'],
    ])
  })

  it('shows only the total for a job from before calls were itemised', async () => {
    api.import.getJob.mockResolvedValue({
      id: ID, filename: 'a.pdf', tasks: [],
      cost: {
        total_usd: 0.25, calls: 0, input_tokens: 900, output_tokens: 90, cache_write: 0, cache_hit: 0, unpriced: false,
        items: [{ id: 1, kind: 'legacy', run: 0, attempt: null, model: '', input_tokens: 900, output_tokens: 90, cost_usd: 0.25 }],
      },
    })
    render(<JobDetail jobId={ID} version={0} />)
    expect(await screen.findByText(/Claude cost:/)).toHaveTextContent('Claude cost: $0.2500 · per-call breakdown not recorded')
    expect(screen.queryByRole('table', { name: 'Claude calls' })).toBeNull()
  })
})
