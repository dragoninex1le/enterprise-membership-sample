// Claim-to-Role Mapping page -- PORTH-132
import { test, expect } from '@playwright/test'
import {
  mockBootstrap,
  mockClaimConfig,
} from '../helpers/mocks'

test.describe('Claim-to-Role Mapping page', () => {
  test.beforeEach(async ({ page }) => {
    await mockBootstrap(page)
    await mockClaimConfig(page)
  })

  test('renders Claim-to-Role Mappings heading', async ({ page }) => {
    await page.goto('/admin/tenant/claim-mappings?tenantId=test-tenant')
    await expect(page.getByRole('heading', { name: 'Claim-to-Role Mappings' })).toBeVisible()
  })

  test('page is accessible as platform-admin', async ({ page }) => {
    await page.goto('/admin/tenant/claim-mappings?tenantId=test-tenant')
    await expect(page).not.toHaveURL(/unauthorized/)
  })

  test('mapping editor textarea contains config JSON', async ({ page }) => {
    await page.goto('/admin/tenant/claim-mappings?tenantId=test-tenant')
    // The first textarea is the mapping editor -- wait for it to have content
    const mappingTextarea = page.locator('textarea').first()
    await expect(mappingTextarea).toHaveValue(/resolve_roles/, { timeout: 8000 })
  })

  test('Evaluate button is present', async ({ page }) => {
    await page.goto('/admin/tenant/claim-mappings?tenantId=test-tenant')
    await expect(page.getByRole('button', { name: 'Evaluate' })).toBeVisible()
  })

  test('JWT evaluator shows matched roles after evaluation', async ({ page }) => {
    await page.goto('/admin/tenant/claim-mappings?tenantId=test-tenant')
    // Wait for the mapping editor textarea to have content before evaluating
    await expect(page.locator('textarea').first()).toHaveValue(/resolve_roles/, { timeout: 8000 })
    // The evaluator textarea has a specific placeholder
    const evaluatorTextarea = page.getByPlaceholder('Paste decoded JWT claims as JSON')
    await evaluatorTextarea.fill('{"https://porth.io/roles": ["controller"]}')
    await page.getByRole('button', { name: 'Evaluate' }).click()
    // Matched roles section should appear
    await expect(page.getByText('Matched roles:', { exact: true })).toBeVisible()
    // The matched role 'controller' appears -- use getByRole for the badge
    await expect(page.getByText('controller', { exact: true })).toBeVisible()
  })
})
