import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { api } from './client'

// Exercises the real error mapping in `request` (nothing mocked but fetch),
// since that is what decides whether the backend's message reaches the user.
function mockResponse(status, body) {
  globalThis.fetch = vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  })
}

describe('api.auth.login error mapping', () => {
  beforeEach(() => vi.clearAllMocks())
  afterEach(() => { delete globalThis.fetch })

  it('replaces a 401 with generic copy, so a bad password reveals nothing', async () => {
    mockResponse(401, { detail: 'Invalid credentials' })
    await expect(api.auth.login('a@b.com', 'wrong')).rejects.toMatchObject({
      status: 401,
      message: expect.stringContaining('Unknown email or incorrect password'),
    })
  })

  it('passes a 409 through verbatim, so the Google hint reaches the user', async () => {
    const detail = 'This account was created with Google. Use "Sign in with Google" instead.'
    mockResponse(409, { detail })
    await expect(api.auth.login('a@b.com', 'anything')).rejects.toMatchObject({
      status: 409,
      message: detail,
    })
  })
})

describe('api.auth.providers', () => {
  afterEach(() => { delete globalThis.fetch })

  it('reads the google flag', async () => {
    mockResponse(200, { google: true })
    await expect(api.auth.providers()).resolves.toEqual({ google: true })
    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/auth/providers',
      expect.objectContaining({ method: 'GET', credentials: 'include' }),
    )
  })
})
