import { describe, it, expect } from 'vitest'
import { hasSchoolLevel, isLocked, requiredSchoolLevel, subscribeHref } from './premium'

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

describe('requiredSchoolLevel', () => {
  it('names the premium group the item belongs to', () => {
    expect(requiredSchoolLevel({ paper_info: { school_level_name: 'Secondary' } }))
      .toBe('Secondary')
  })

  it('is null when the item carries no school level', () => {
    expect(requiredSchoolLevel({ paper_info: {} })).toBeNull()
    expect(requiredSchoolLevel(undefined)).toBeNull()
  })
})

describe('subscribeHref', () => {
  it('deep-links to the plan the item needs', () => {
    expect(subscribeHref({ paper_info: { school_level_name: 'Primary' } }))
      .toBe('/subscribe?school_level=Primary')
  })

  it('encodes a school level name with spaces', () => {
    expect(subscribeHref({ paper_info: { school_level_name: 'Junior College' } }))
      .toBe('/subscribe?school_level=Junior%20College')
  })

  it('falls back to the plain page with no school level', () => {
    expect(subscribeHref({ paper_info: {} })).toBe('/subscribe')
  })
})

describe('hasSchoolLevel', () => {
  const user = { role: 'public', premium_school_levels: [{ id: 1, name: 'Secondary' }] }

  it('is true for a level the user holds', () => {
    expect(hasSchoolLevel(user, 'Secondary')).toBe(true)
  })

  it('is false for a level the user does not hold', () => {
    expect(hasSchoolLevel(user, 'Primary')).toBe(false)
  })

  it('is true for any level when the user is an admin', () => {
    expect(hasSchoolLevel({ role: 'admin', premium_school_levels: [] }, 'Primary')).toBe(true)
  })

  it('is false for an anonymous viewer', () => {
    expect(hasSchoolLevel(null, 'Secondary')).toBe(false)
  })
})
