// Shared mock helpers for Tier 1 E2E tests.
// Call mockBootstrap(page) in every test to mock the two bootstrap calls:
//   GET /tenants/test-tenant  -- tenant config (useTenantConfig)
//   POST /users/me            -- current user + roles (useCurrentUser)
// Route patterns use RegExp (not glob) so query strings are handled correctly.
// Glob patterns like "**/roles/" do NOT match "/roles/?tenant_id=x".
import type { Page } from '@playwright/test'
import type {
  Organization,
  Tenant,
  Role,
  Permission,
  User,
  ClaimMappingConfig,
} from '../../../src/api/types'

// ─── Default fixture data ──────────────────────────────────────────────────

export const DEFAULT_ORG: Organization = {
  id: 'org-1',
  name: 'Acme Corp',
  slug: 'acme',
  status: 'active',
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T00:00:00Z',
}

export const DEFAULT_ORG_2: Organization = {
  id: 'org-2',
  name: 'Beta Ltd',
  slug: 'beta',
  status: 'active',
  created_at: '2024-01-02T00:00:00Z',
  updated_at: '2024-01-02T00:00:00Z',
}

export const DEFAULT_TENANT: Tenant = {
  tenant_id: 'test-tenant',
  org_id: 'org-1',
  org_name: 'Acme Corp',
  display_name: 'Acme Production',
  environment_type: 'production',
  status: 'active',
  idp_config_override: {
    provider: 'auth0',
    domain: 'e2e.eu.auth0.com',
    client_id: 'e2e-client-id',
    audience: 'https://e2e.api',
  },
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T00:00:00Z',
}

export const DEFAULT_SUSPENDED_TENANT: Tenant = {
  ...DEFAULT_TENANT,
  tenant_id: 'test-tenant-suspended',
  display_name: 'Acme Staging',
  status: 'suspended',
}

export const DEFAULT_PLATFORM_ADMIN_USER: User = {
  id: 'user-platform-admin',
  external_id: 'auth0|e2e-platform-admin',
  email: 'platform-admin@e2e.test',
  first_name: 'Platform',
  last_name: 'Admin',
  display_name: 'Platform Admin',
  organization_id: 'org-1',
  tenant_id: 'test-tenant',
  status: 'active',
  is_org_admin: true,
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T00:00:00Z',
}

export const DEFAULT_PLATFORM_ADMIN_ROLE: Role = {
  id: 'role-platform-admin',
  tenant_id: 'test-tenant',
  name: 'platform-admin',
  is_system: true,
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T00:00:00Z',
}

export const DEFAULT_SYSTEM_ROLE: Role = {
  id: 'role-system-1',
  tenant_id: 'test-tenant',
  name: 'viewer',
  description: 'Read-only access',
  is_system: true,
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T00:00:00Z',
}

export const DEFAULT_CUSTOM_ROLE: Role = {
  id: 'role-custom-1',
  tenant_id: 'test-tenant',
  name: 'ar_clerk',
  description: 'AR data entry',
  is_system: false,
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T00:00:00Z',
}

export const DEFAULT_PERMISSIONS: Permission[] = [
  {
    id: 'perm-1',
    key: 'ar.invoices.read',
    display_name: 'View Invoices',
    app_namespace: 'sample',
    category: 'Accounts Receivable',
    sort_order: 1,
    tenant_id: 'test-tenant',
    created_at: '2024-01-01T00:00:00Z',
  },
  {
    id: 'perm-2',
    key: 'ar.invoices.write',
    display_name: 'Create/Edit Invoices',
    app_namespace: 'sample',
    category: 'Accounts Receivable',
    sort_order: 2,
    tenant_id: 'test-tenant',
    created_at: '2024-01-01T00:00:00Z',
  },
  {
    id: 'perm-3',
    key: 'ap.bills.read',
    display_name: 'View Bills',
    app_namespace: 'sample',
    category: 'Accounts Payable',
    sort_order: 1,
    tenant_id: 'test-tenant',
    created_at: '2024-01-01T00:00:00Z',
  },
  {
    id: 'perm-4',
    key: 'approvals.write',
    display_name: 'Approve/Reject',
    app_namespace: 'sample',
    category: 'Approvals',
    sort_order: 1,
    tenant_id: 'test-tenant',
    created_at: '2024-01-01T00:00:00Z',
  },
]

export const DEFAULT_ACTIVE_USER: User = {
  id: 'user-1',
  external_id: 'auth0|user-1',
  email: 'alice@acme.com',
  first_name: 'Alice',
  last_name: 'Smith',
  display_name: 'Alice Smith',
  organization_id: 'org-1',
  tenant_id: 'test-tenant',
  status: 'active',
  is_org_admin: false,
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T00:00:00Z',
}

export const DEFAULT_SUSPENDED_USER: User = {
  id: 'user-2',
  external_id: 'auth0|user-2',
  email: 'bob@acme.com',
  first_name: 'Bob',
  last_name: 'Jones',
  display_name: 'Bob Jones',
  organization_id: 'org-1',
  tenant_id: 'test-tenant',
  status: 'suspended',
  is_org_admin: false,
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T00:00:00Z',
}

// DEFAULT_CLAIM_CONFIG uses the schema the ClaimRoleMappingPage evaluator understands:
// { fields: { <name>: { claim_key: '...', ops: [{ op: 'resolve_roles' }] } } }
export const DEFAULT_CLAIM_CONFIG: ClaimMappingConfig = {
  id: 'config-1',
  tenant_id: 'test-tenant',
  app_namespace: 'sample',
  version: 2,
  mapping_source: {
    schema_version: '1',
    fields: {
      roles: {
        claim_key: 'https://porth.io/roles',
        ops: [{ op: 'resolve_roles' }],
      },
    },
    default_roles: [],
  },
  created_at: '2024-01-02T00:00:00Z',
}

export const DEFAULT_CLAIM_CONFIG_V1: ClaimMappingConfig = {
  ...DEFAULT_CLAIM_CONFIG,
  id: 'config-v1',
  version: 1,
  created_at: '2024-01-01T00:00:00Z',
}

// ─── Mock helpers ──────────────────────────────────────────────────────────

/**
 * Mocks the two bootstrap calls every page needs:
 *   GET /tenants/test-tenant  → tenant config (for useTenantConfig)
 *   POST /users/me            → current user + roles (for useCurrentUser)
 *
 * @param permissions - explicit permission keys to inject; defaults to all DEFAULT_PERMISSIONS
 */
export async function mockBootstrap(
  page: Page,
  userOverrides?: Partial<User>,
  roles?: Role[],
  permissions?: string[],
) {
  // useTenantConfig calls plain fetch() not axios -- intercept by path
  await page.route(/\/tenants\/test-tenant($|\?)/, (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(DEFAULT_TENANT),
    })
  })

  const resolvedUser = { ...DEFAULT_PLATFORM_ADMIN_USER, ...userOverrides }
  const resolvedRoles = roles ?? [DEFAULT_PLATFORM_ADMIN_ROLE]
  const resolvedPermissions = permissions ?? DEFAULT_PERMISSIONS.map(p => p.key)

  await page.route(/\/users\/me($|\?)/, (route) => {
    if (route.request().method() !== 'POST') return route.continue()
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        user: resolvedUser,
        is_new: false,
        roles: resolvedRoles,
        permissions: resolvedPermissions,
      }),
    })
  })
}

export async function mockOrgs(page: Page, orgs: Organization[] = [DEFAULT_ORG, DEFAULT_ORG_2]) {
  // Match GET /organizations/ (list endpoint).
  await page.route(/\/organizations\/(\?.*)?$/, (route) => {
    if (route.request().method() !== 'GET') return route.continue()
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(orgs),
    })
  })
}

export async function mockOrg(page: Page, org: Organization = DEFAULT_ORG) {
  await page.route(new RegExp(`/organizations/${org.id}($|\\?)`), (route) => {
    if (route.request().method() !== 'GET') return route.continue()
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(org),
    })
  })
}

export async function mockTenants(page: Page, tenants: Tenant[] = [DEFAULT_TENANT, DEFAULT_SUSPENDED_TENANT]) {
  await page.route(/\/tenants\/organization\//, (route) => {
    if (route.request().method() !== 'GET') return route.continue()
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(tenants),
    })
  })
}

export async function mockUsers(page: Page, users: User[] = [DEFAULT_ACTIVE_USER, DEFAULT_SUSPENDED_USER]) {
  await page.route(/\/users\/organization\//, (route) => {
    if (route.request().method() !== 'GET') return route.continue()
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(users),
    })
  })
}

export async function mockRoles(page: Page, roles: Role[] = [DEFAULT_SYSTEM_ROLE, DEFAULT_CUSTOM_ROLE]) {
  // Matches /roles/ and /roles/?tenant_id=... but NOT /roles/tenant/role/permissions
  await page.route(/\/roles\/($|\?)/, (route) => {
    if (route.request().method() !== 'GET') return route.continue()
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(roles),
    })
  })
}

export async function mockRolePermissions(page: Page, keys: string[] = ['ar.invoices.read']) {
  await page.route(/\/roles\/[^/]+\/[^/]+\/permissions($|\?)/, (route) => {
    if (route.request().method() !== 'GET') return route.continue()
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(keys),
    })
  })
}

export async function mockPermissions(page: Page, permissions: Permission[] = DEFAULT_PERMISSIONS) {
  await page.route(/\/permissions\/($|\?)/, (route) => {
    if (route.request().method() !== 'GET') return route.continue()
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(permissions),
    })
  })
}

export async function mockClaimConfig(page: Page, config: ClaimMappingConfig = DEFAULT_CLAIM_CONFIG) {
  await page.route(/\/claim-mapping-configs\/[^/]+\/latest($|\?)/, (route) => {
    if (route.request().method() !== 'GET') return route.continue()
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(config),
    })
  })
}

export async function mockClaimConfigVersions(page: Page, versions: ClaimMappingConfig[] = [DEFAULT_CLAIM_CONFIG, DEFAULT_CLAIM_CONFIG_V1]) {
  await page.route(/\/claim-mapping-configs\/[^/]+\/versions($|\?)/, (route) => {
    if (route.request().method() !== 'GET') return route.continue()
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(versions),
    })
  })
}

/** Mocks the sample app API calls used by Dashboard / AR / AP / Approvals pages. */
export async function mockSampleApis(page: Page) {
  await page.route(/\/sample\/dashboard($|\?)/, (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        outstanding_invoices: 5,
        total_ar: 12500.0,
        bills_due: 3,
        total_ap: 4200.0,
        pending_approvals: 1,
        cash_position: 8300.0,
      }),
    })
  })

  await page.route(/\/sample\/ar\/invoices($|\?)/, (route) => {
    if (route.request().method() !== 'GET') return route.continue()
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        { invoice_id: 'inv-0001', customer_name: 'Widgets Inc', amount: '1200.00', status: 'sent', due_date: '2025-05-01' },
        { invoice_id: 'inv-0002', customer_name: 'Gadgets Ltd', amount: '850.50', status: 'draft', due_date: '2025-06-15' },
      ]),
    })
  })

  await page.route(/\/sample\/ap\/bills($|\?)/, (route) => {
    if (route.request().method() !== 'GET') return route.continue()
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        { bill_id: 'bill-0001', vendor_name: 'Supplies Co', amount: '2300.00', status: 'pending', due_date: '2025-05-10' },
        { bill_id: 'bill-0002', vendor_name: 'Services Ltd', amount: '1900.00', status: 'approved', due_date: '2025-05-20' },
      ]),
    })
  })

  await page.route(/\/sample\/approvals($|\?)/, (route) => {
    if (route.request().method() !== 'GET') return route.continue()
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        {
          record_id: 'rec-0001',
          type: 'invoice',
          amount: '1200.00',
          submitted_by: 'alice@acme.com',
          submitted_at: '2025-04-20T10:00:00Z',
          status: 'pending',
        },
      ]),
    })
  })
}
