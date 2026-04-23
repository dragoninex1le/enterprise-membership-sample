// Claim Mapping Config page -- PORTH-131
import { test, expect } from '@playwright/test'
import {
  mockBootstrap,
  mockClaimConfig,
  mockClaimConfigVersions,
} from '../helpers/mocks'

test.describe('Claim Mapping Config page', () => {
  test.beforeEach(async ({ page }) => {
    await mockBootstrap(page)
    await mockClaimConfig(page)
    await mockClaimConfigVersions(page)
  })

  test('renders Claim Mapping Config heading', async ({ page }) => {
    await page.goto('/admin/tenant/claim-config?tenantId=test-tenant')
    await expect(page.getByRole('heading', { name: 'Claim Mapping Config' })).toBeVisible()
  })

  test('page is accessible as platform-admin', async ({ page }) => {
    await page.goto('/admin/tenant/claim-config?tenantId=test-tenant')
    await expect(page).not.toHaveURL(/unauthorized/)
  })

  test('textarea contains the mapping JSON from the API', async ({ page }) => {
    await page.goto('/admin/tenant/claim-config?tenantId=test-tenant')
    // The editor textarea should appear once loaded
    await expect(page.locator('textarea').first()).toBeVisible()
    // The textarea content is the mapping_source JSON
    const content = await page.locator('textarea').first().inputValue()
    expect(content).toContain('resolve_roles')
  })

  test('version history table shows 2 rows', async ({ page }) => {
    await page.goto('/admin/tenant/claim-config?tenantId=test-tenant')
    await expect(page.getByRole('heading', { name: 'Version History' })).toBeVisible()
    // Two Rollback buttons -- one per version
    const rollbackButtons = page.getByRole('button', { name: 'Rollback' })
    await expect(rollbackButtons).toHaveCount(2)
  })

  test('Compile Preview button is present', async ({ page }) => {
    await page.goto('/admin/tenant/claim-config?tenantId=test-tenant')
    await expect(page.getByRole('button', { name: 'Compile Preview' })).toBeVisible()
  })

  test('Save button is present', async ({ page }) => {
    await page.goto('/admin/tenant/claim-config?tenantId=test-tenant')
    await expect(page.getByRole('button', { name: 'Save' }).first()).toBeVisible()
  })
})
