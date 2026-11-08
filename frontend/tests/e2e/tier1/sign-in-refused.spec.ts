// PORTH-654 — a sign-in the identity provider refused comes back with login_error and
// login_error_description (Porth 0.4.14, Components docs/INSTALL.md §5). The SPA asks
// whether to sign out, and never starts another sign-in on its own.
import { test, expect, type Page } from '@playwright/test'
import { mockBootstrap } from '../helpers/mocks'

const REFUSED = 'Not authorised for the platform console.'

function refusedUrl(description: string, path = '/dashboard') {
  const q = new URLSearchParams({ login_error: 'access_denied', login_error_description: description, keep: 'me' })
  return `${path}?${q.toString()}`
}

/** Record every navigation to Porth's logout and answer it, so the test stays on a page. */
async function captureLogout(page: Page): Promise<string[]> {
  const seen: string[] = []
  await page.route(/\/auth\/logout(\?|$)/, async (route) => {
    seen.push(route.request().url())
    await route.fulfill({ status: 200, contentType: 'text/html', body: '<p>signed out</p>' })
  })
  return seen
}

test.describe('Sign-in refused by the identity provider', () => {
  test.beforeEach(async ({ page }) => {
    await mockBootstrap(page)
  })

  test('the parameters show the question, and leave the address bar', async ({ page }) => {
    await page.goto(refusedUrl(REFUSED))
    await expect(page.getByRole('heading', { name: "You're signed in with another account" })).toBeVisible()
    await expect(page.getByText("This account can't use this console. Sign out and sign in as someone else?")).toBeVisible()
    await expect(page.getByTestId('sign-in-refused-description')).toHaveText(REFUSED)
    // Cleaned, so a reload does not ask again — and the page's other parameters survive.
    await expect(page).toHaveURL(/\/dashboard\?keep=me$/)
  })

  test('"Sign out" goes to Porth\'s logout, returning to this page without the refusal', async ({ page }) => {
    const logouts = await captureLogout(page)
    await page.goto(refusedUrl(REFUSED))
    await page.getByRole('button', { name: 'Sign out and use another account' }).click()
    await expect.poll(() => logouts.length).toBe(1)

    const logout = new URL(logouts[0])
    expect(logout.pathname).toMatch(/\/auth\/logout$/)
    const returnTo = logout.searchParams.get('return_to') ?? ''
    expect(logouts[0]).toContain(`return_to=${encodeURIComponent(returnTo)}`)
    const back = new URL(returnTo)
    expect(back.pathname).toBe('/dashboard')
    expect(back.searchParams.get('login_error')).toBeNull()
    expect(back.searchParams.get('login_error_description')).toBeNull()
    expect(back.searchParams.get('keep')).toBe('me')
  })

  test('"Stay signed in" shows the error and starts no sign-in', async ({ page }) => {
    const signIns: string[] = []
    page.on('request', (r) => { if (/\/auth\/login/.test(r.url())) signIns.push(r.url()) })
    await page.goto(refusedUrl(REFUSED))
    await page.getByRole('button', { name: 'Stay signed in' }).click()

    await expect(page.getByRole('heading', { name: 'Sign-in was refused' })).toBeVisible()
    await expect(page.getByTestId('sign-in-refused-description')).toHaveText(REFUSED)
    await expect(page.getByRole('button', { name: 'Sign out and use another account' })).toHaveCount(0)
    await page.waitForTimeout(1500)
    expect(signIns).toEqual([])
    await expect(page).toHaveURL(/\/dashboard\?keep=me$/)
  })

  test('a description with markup is shown as text and never run', async ({ page }) => {
    const hostile = '<script>window.__refusalRan = true</script><b>bold</b> <img src=x onerror="window.__refusalRan=true">'
    await page.goto(refusedUrl(hostile))
    await expect(page.getByTestId('sign-in-refused-description')).toHaveText(hostile)
    await expect(page.locator('[data-testid="sign-in-refused-description"] b')).toHaveCount(0)
    await expect(page.locator('[data-testid="sign-in-refused-description"] img')).toHaveCount(0)
    expect(await page.evaluate(() => (window as unknown as { __refusalRan?: boolean }).__refusalRan)).toBeUndefined()
  })

  test('without the parameters the app renders as usual', async ({ page }) => {
    await page.goto('/dashboard')
    await expect(page.getByRole('heading', { name: "You're signed in with another account" })).toHaveCount(0)
  })
})
