import { describe, it, expect } from 'vitest'
import { formatTopic } from './topicFormat'

describe('formatTopic', () => {
  it('prefixes the topic number as T{n}', () => {
    expect(formatTopic(1, 'Algebra')).toBe('T1 Algebra')
    expect(formatTopic(12, 'Trigonometry')).toBe('T12 Trigonometry')
  })

  it('falls back to the bare name when the number is missing', () => {
    expect(formatTopic(null, 'Algebra')).toBe('Algebra')
    expect(formatTopic(undefined, 'Algebra')).toBe('Algebra')
  })
})
