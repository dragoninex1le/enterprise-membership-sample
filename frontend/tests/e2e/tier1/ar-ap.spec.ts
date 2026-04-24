/**
 * AR / AP / Dashboard / Approvals screens
 *
 * These pages call the sample app API (/sample/*). We mock those endpoints
 * alongside the Porth bootstrap calls.
 */
import { test, expect } from '@playwright/test'
import {
  mockBootstrap,
  mockSampleApis,
  DEFAULT_PLATFORM_ADMIN_ROLE,
  DEFAULT_SYSTEM_ROLE,
} from '../helpers/mocks'
import type { Role } from '../../../src/api/types'

// A viewer role -- not in the allowed list for /approvals (controller only)
const VIEWER_ROLE: Role = {
  id: 'role-viewer',
  tenant_id: 'test-tenant',
  name: 'viewer',
  is_system: true,
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T00:00:00Z',
}

test.describe('Dashboard', () => {
  test('renders dashboard heading', async ({ page }) => {
    await mockBootstrap(page)
    await mockSampleApis(page)
    await page.goto('/dashboard')
    await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible()
  })

  test('renders summary cards once API responds', async ({ page }) => {
    await mockBootstrap(page)
    await mockSampleApis(page)
    await page.goto('/dashboard')
    // Card labels -- use exact match to avoid matching the subtitle text
    await expect(page.getByText('Outstanding Invoices', { exact: true })).toBeVisible()
    await expect(page.getByText('Bills Due', { exact: true })).toBeVisible()
    await expect(page.getByText('Net Balance', { exact: true })).toBeVisible()
  })
})

test.describe('AR page', () => {
  test('renders Accounts Receivable heading', async ({ page }) => {
    await mockBootstrap(page)
    await mockSampleApis(page)
    await page.goto('/ar')
    await expect(page.getByRole('heading', { name: 'Accounts Receivable' })).toBeVisible()
  })

  test('renders invoice table with mocked data', async ({ page }) => {
    await mockBootstrap(page)
    await mockSampleApis(page)
    await page.goto('/ar')
    await expect(page.getByText('Widgets Inc')).toBeVisible()
    await expect(page.getByText('Gadgets Ltd')).toBeVisible()
  })

  test('New Invoice button visible when user has ar.invoices.write permission', async ({ page }) => {
    // mockBootstrap injects DEFAULT_PERMISSIONS which includes ar.invoices.write
    await mockBootstrap(page)
    await mockSampleApis(page)
    await page.goto('/ar')
    await expect(page.getByRole('button', { name: 'New Invoice' })).toBeVisible()
  })

  test('New Invoice button hidden when user lacks ar.invoices.write permission', async ({ page }) => {
    // Pass empty permissions -- user cannot write invoices
    await mockBootstrap(page, undefined, [DEFAULT_PLATFORM_ADMIN_ROLE], [])
    await mockSampleApis(page)
    await page.goto('/ar')
    await expect(page.getByRole('button', { name: 'New Invoice' })).not.toBeVisible()
  })
})

test.describe('AP page', () => {
  test('renders Accounts Payable heading', async ({ page }) => {
    await mockBootstrap(page)
    await mockSampleApis(page)
    await page.goto('/ap')
    await expect(page.getByRole('heading', { name: 'Accounts Payable' })).toBeVisible()
  })

  test('renders bills table with mocked data', async ({ page }) => {
    await mockBootstrap(page)
    await mockSampleApis(page)
    await page.goto('/ap')
    await expect(page.getByText('Supplies Co')).toBeVisible()
    await expect(page.getByText('Services Ltd')).toBeVisible()
  })
})

test.describe('Approvals page', () => {
  test('renders Approvals heading', async ({ page }) => {
    await mockBootstrap(page)
    await mockSampleApis(page)
    await page.goto('/approvals')
    await expect(page.getByRole('heading', { name: 'Approvals' })).toBeVisible()
  })

  test('renders Approve and Reject buttons for pending approval when user has approvals.write', async ({ page }) => {
    // DEFAULT_PERMISSIONS includes approvals.write
    await mockBootstrap(page)
    await mockSampleApis(page)
    await page.goto('/approvals')
    await expect(page.getByRole('button', { name: 'Approve' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Reject' })).toBeVisible()
  })

  test('Approve/Reject buttons hidden when user lacks approvals.write', async ({ page }) => {
    await mockBootstrap(page, undefined, [DEFAULT_PLATFORM_ADMIN_ROLE], [])
    await mockSampleApis(page)
    await page.goto('/approvals')
    await expect(page.getByRole('button', { name: 'Approve' })).not.toBeVisible()
    await expect(page.getByRole('button', { name: 'Reject' })).not.toBeVisible()
  })
})

test.describe('Role-based route protection', () => {
  test('viewer role is redirected from /approvals (controller-only route)', async ({ page }) => {
    await mockBootstrap(page, undefined, [VIEWER_ROLE])
    await page.goto('/approvals')
    await expect(page).toHaveURL(/unauthorized/)
  })

  test('platform-admin can reach /approvals', async ({ page }) => {
    await mockBootstrap(page, undefined, [DEFAULT_PLATFORM_ADMIN_ROLE])
    await mockSampleApis(page)
    await page.goto('/approvals')
    await expect(page.getByRole('heading', { name: 'Approvals' })).toBeVisible()
  })

  test('viewer role can see /dashboard', async ({ page }) => {
    await mockBootstrap(page, undefined, [
      { ...DEFAULT_SYSTEM_ROLE, name: 'viewer' },
    ])
    await mockSampleApis(page)
    await page.goto('/dashboard')
    await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible()
  })
})
