import { describe, it, expect } from 'vitest'
import { callLabel, formatInput, formatUsd, modelName, monthLabel, runTag } from './costFormat'

describe('costFormat', () => {
  it('formats dollars to cents, or to four places for a single call', () => {
    expect(formatUsd(0.384)).toBe('$0.38')
    expect(formatUsd(0.002)).toBe('<$0.01')
    expect(formatUsd(0)).toBe('$0.00')
    expect(formatUsd(0.0031, { precise: true })).toBe('$0.0031')
    expect(formatUsd(null)).toBe('—')
  })

  it('shows cache reads beside input tokens', () => {
    expect(formatInput(48210, 0)).toBe('48,210')
    expect(formatInput(48210, 1024)).toBe('48,210 (+1,024)')
  })

  it('names each kind of call', () => {
    expect(callLabel({ kind: 'segment' })).toBe('Find papers in booklet')
    expect(callLabel({ kind: 'metadata', paper_key: 'q1', source: 'cover' })).toBe('Paper q1 metadata (from cover)')
    expect(callLabel({ kind: 'metadata', paper_key: 'paper2', source: 'filename' })).toBe('Paper paper2 metadata (from filename)')
    expect(callLabel({ kind: 'legacy' })).toBe('Before per-call tracking')
  })

  it('shortens known models to their family', () => {
    expect(modelName('claude-haiku-4-5-20251001')).toBe('Haiku')
    expect(modelName('claude-opus-5')).toBe('Opus')
    expect(modelName('gpt-x')).toBe('gpt-x')
    expect(modelName('')).toBe('—')
  })

  it('tags calls from a retry or a later attempt', () => {
    expect(runTag({ run: 0, attempt: 1 })).toBe('')
    expect(runTag({ run: 2, attempt: 1 })).toBe('retry 2')
    expect(runTag({ run: 0, attempt: 2 })).toBe('attempt 2')
    expect(runTag({ run: 1, attempt: 3 })).toBe('retry 1, attempt 3')
  })

  it('labels a month', () => {
    expect(monthLabel('2026-11')).toBe('Nov 2026')
  })
})
