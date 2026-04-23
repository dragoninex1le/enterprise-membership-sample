import { test, expect } from '@playwright/test'
import {
  mockBootstrap,
  mockOrgs,
  DEFAULT_ORG,
  DEFAULT_ORG_2,
} from '../helpers/mocks'

test.describe('Organizations page', () => {
  test.beforeEach(async ({ page }) => {
    await mockBootstrap(page)
    await mockOrgs(page)
  })

  test('renders org list with names and slugs', async ({ page }) => {
    await page.goto('/admin/platform/organizations')
    await expect(page.getByRole('heading', { name: 'Organizations' })).toBeVisible()
    // Wait for org rows to appear (API response loaded)
    await expect(page.getByRole('cell', { name: DEFAULT_ORG.name })).toBeVisible()
    await expect(page.getByRole('cell', { name: DEFAULT_ORG_2.name })).toBeVisible()
    // Slug column renders the raw slug value (exact to avoid partial match with org name)
    await expect(page.getByRole('cell', { name: DEFAULT_ORG.slug, exact: true })).toBeVisible()
  })

  test('New Organization button is visible', async ({ page }) => {
    await page.goto('/admin/platform/organizations')
    await expect(page.getByRole('button', { name: '+ New Organization' })).toBeVisible()
  })

  test('clicking an org row navigates to its tenants page', async ({ page }) => {
    await page.goto('/admin/platform/organizations')
    // Each org is a Link -- click on the first org name
    await page.getByText(DEFAULT_ORG.name).click()
    await expect(page).toHaveURL(new RegExp(`/admin/platform/organizations/${DEFAULT_ORG.id}/tenants`))
  })
})
