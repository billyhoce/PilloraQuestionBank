import { describe, it, expect } from 'vitest'
import { isLocked } from './premium'

describe('isLocked', () => {
  it('honours an explicit locked flag from the backend', () => {
    expect(isLocked({ locked: true, paper_info: { is_premium: false }, first_page_url: 'x' })).toBe(true)
    expect(isLocked({ locked: false, paper_info: { is_premium: true }, first_page_url: null })).toBe(false)
  })

  it('infers locked for a premium paper with no image url', () => {
    expect(isLocked({ paper_info: { is_premium: true }, first_page_url: null })).toBe(true)
  })

  it('is unlocked when the paper is not premium', () => {
    expect(isLocked({ paper_info: { is_premium: false }, first_page_url: 'x' })).toBe(false)
  })

  it('is unlocked for a premium paper the viewer can see (url present)', () => {
    expect(isLocked({ paper_info: { is_premium: true }, first_page_url: 'x' })).toBe(false)
  })
})
