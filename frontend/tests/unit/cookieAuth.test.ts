// PORTH-655: the browser handle on every cookie-mode call (Components docs/INSTALL.md §5).
import { describe, expect, it } from 'vitest'
import { AxiosHeaders, type InternalAxiosRequestConfig } from 'axios'
import { browserHandle } from '@estyn/porth-admin/auth'
import { applyBrowserHandle, requestUrl } from '../../src/api/cookieAuth'

const SECRET = 'csrf-secret-123'

function config(method: string, baseURL: string | undefined, url: string): InternalAxiosRequestConfig {
  return { method, baseURL, url, headers: new AxiosHeaders() } as InternalAxiosRequestConfig
}

describe('the browser handle', () => {
  it('matches Porth’s shared test vector', async () => {
    // The vector both browserHandle and the authorizer's handle.py are held to:
    // host lower-cased without its port, METHOD upper-cased, path as sent, no query.
    expect(await browserHandle(SECRET, 'https://Acme.API.porth-dau.ems.estynsoftware.cloud:443/porth/roles/?tenant_id=acme', 'GET'))
      .toBe('Miw64bqIzHpZkm5IPKFrJqtDBhWiHfAAMmp3z_3ifL4')
  })

  it('is what applyCookieAuth sends, built from baseURL + url', async () => {
    const c = await applyBrowserHandle(
      config('get', 'https://Acme.API.porth-dau.ems.estynsoftware.cloud:443/porth', '/roles/?tenant_id=acme'),
      SECRET, browserHandle)
    expect(c.headers.get('Authorization')).toBe('Bearer Miw64bqIzHpZkm5IPKFrJqtDBhWiHfAAMmp3z_3ifL4')
    expect(c.headers.has('X-CSRF-Token')).toBe(false) // a read carries no CSRF header
  })

  it('differs between two routes and between two methods', async () => {
    const base = 'https://acme.api.porth-dau.ems.estynsoftware.cloud'
    const handleOf = async (method: string, url: string) =>
      (await applyBrowserHandle(config(method, base, url), SECRET, browserHandle)).headers.get('Authorization')

    const listInvoices = await handleOf('get', '/sample/ar/invoices')
    expect(await handleOf('get', '/sample/ap/bills')).not.toBe(listInvoices)
    expect(await handleOf('post', '/sample/ar/invoices')).not.toBe(listInvoices)
  })

  it('sends X-CSRF-Token on writes', async () => {
    const c = await applyBrowserHandle(config('delete', 'https://acme.api.porth-dau.ems.estynsoftware.cloud',
      '/sample/suppliers/link/b-1'), SECRET, browserHandle)
    expect(c.headers.get('X-CSRF-Token')).toBe(SECRET)
    expect(String(c.headers.get('Authorization'))).toMatch(/^Bearer [A-Za-z0-9_-]{43}$/)
  })

  it('with no CSRF secret, sends no Authorization header at all — never an empty bearer', async () => {
    const c = config('get', 'https://acme.api.porth-dau.ems.estynsoftware.cloud', '/sample/dashboard')
    c.headers.set('Authorization', 'Bearer ')
    const out = await applyBrowserHandle(c, null, browserHandle)
    expect(out.headers.has('Authorization')).toBe(false)
    expect(out.headers.has('X-CSRF-Token')).toBe(false)
  })
})

describe('requestUrl', () => {
  it.each([
    ['https://h.example/porth', '/roles', 'https://h.example/porth/roles'],
    ['https://h.example/porth/', 'roles', 'https://h.example/porth/roles'],
    ['/porth', '/roles', '/porth/roles'],
    ['https://h.example/porth', 'https://other.example/x', 'https://other.example/x'],
    [undefined, '/sample/dashboard', '/sample/dashboard'],
  ])('%s + %s', (baseURL, url, expected) => {
    expect(requestUrl({ baseURL, url })).toBe(expected)
  })
})
