import { describe, it, expect } from 'vitest'
import { passwordFailures } from './passwordRules'

// Same cases as the server's rules in app/schemas/auth.py, so the two copies stay in step.
describe('passwordFailures', () => {
  it('passes a password meeting every rule', () => {
    expect(passwordFailures('Secure123!')).toEqual([])
  })

  it('lists each broken rule in order', () => {
    expect(passwordFailures('')).toEqual([
      'At least 8 characters',
      'An uppercase letter',
      'A lowercase letter',
      'A number',
      'A special character',
    ])
  })

  it('counts a space or symbol as a special character', () => {
    expect(passwordFailures('Secure12 ')).toEqual([])
    expect(passwordFailures('Secure12_')).toEqual([])
  })

  it('needs eight characters, not seven', () => {
    expect(passwordFailures('Secu12!')).toEqual(['At least 8 characters'])
  })
})
