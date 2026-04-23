import { test, expect } from '@playwright/test'
import {
  mockBootstrap,
  mockOrgs,
  mockTenants,
  DEFAULT_TENANT,
  DEFAULT_SUSPENDED_TENANT,
} from '../helpers/mocks'

test.describe('Tenants page', () => {
  test.beforeEach(async ({ page }) => {
    await mockBootstrap(page)
    await mockOrgs(page)
    await mockTenants(page)
  })

  test('renders tenants list', async ({ page }) => {
    await page.goto('/admin/platform/tenants')
    await expect(page.getByRole('heading', { name: 'Tenants' })).toBeVisible()
    // mock returns same tenants for both orgs — use .first() to avoid strict mode violation
    await expect(page.getByRole('cell', { name: DEFAULT_TENANT.display_name }).first()).toBeVisible()
    await expect(page.getByRole('cell', { name: DEFAULT_SUSPENDED_TENANT.display_name }).first()).toBeVisible()
  })

  test('New Tenant button is visible', async ({ page }) => {
    await page.goto('/admin/platform/tenants')
    await expect(page.getByRole('button', { name: '+ New Tenant' })).toBeVisible()
  })

  test('active tenant shows active status badge', async ({ page }) => {
    await page.goto('/admin/platform/tenants')
    await expect(page.locator('text=active').first()).toBeVisible()
  })

  test('suspended tenant shows suspended status badge', async ({ page }) => {
    await page.goto('/admin/platform/tenants')
    await expect(page.getByText('suspended', { exact: true }).first()).toBeVisible()
  })
})
