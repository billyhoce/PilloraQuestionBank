import { describe, it, expect } from 'vitest'
import { displayName, fullName } from './userName'

describe('fullName', () => {
  it('joins the two names', () => {
    expect(fullName({ first_name: 'Ada', last_name: 'Lovelace' })).toBe('Ada Lovelace')
  })

  it('handles a missing half', () => {
    expect(fullName({ first_name: 'Ada', last_name: '' })).toBe('Ada')
    expect(fullName({ first_name: '', last_name: 'Lovelace' })).toBe('Lovelace')
  })

  it('is empty for accounts with no name on file', () => {
    expect(fullName({ first_name: '', last_name: '', email: 'a@b.com' })).toBe('')
    expect(fullName(null)).toBe('')
  })
})

describe('displayName', () => {
  it('prefers the name', () => {
    expect(displayName({ first_name: 'Ada', last_name: 'Lovelace', email: 'a@b.com' }))
      .toBe('Ada Lovelace')
  })

  it('falls back to the email for accounts predating the name fields', () => {
    expect(displayName({ first_name: '', last_name: '', email: 'a@b.com' })).toBe('a@b.com')
  })

  it('is empty when there is no user', () => {
    expect(displayName(null)).toBe('')
  })
})
