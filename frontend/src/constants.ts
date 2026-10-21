// Role name constants — these must match what the Porth bootstrap creates and
// what the IdP Action injects into the JWT via the claim mapping.
// Centralised here to avoid duplication across router, sidebar, and hooks.

/** The Porth platform-level role assigned to Estyn operators. */
export const PLATFORM_ADMIN = 'platform-admin'

export const PERMISSIONS = {
  DASHBOARD_READ: 'dashboard.read',
  AR_INVOICES_READ: 'ar.invoices.read',
  AR_INVOICES_WRITE: 'ar.invoices.write',
  AP_BILLS_READ: 'ap.bills.read',
  AP_BILLS_WRITE: 'ap.bills.write',
  APPROVALS_READ: 'approvals.read',
  APPROVALS_WRITE: 'approvals.write',
} as const

export const SAMPLE_ROLES = {
  VIEWER: 'viewer',
  AR_CLERK: 'ar-clerk',
  AP_CLERK: 'ap-clerk',
  CONTROLLER: 'controller',
  TENANT_ADMIN: 'tenant-admin',
} as const

/** The roles-claim namespace this install's Auth0 Action writes into the JWT.
 *
 * "{audience}/roles": Auth0 namespaces custom claims with the API identifier, so
 * the value is per-install. VITE_ROLES_NAMESPACE overrides it; the fallback is
 * this install's audience-derived value.
 *
 * It lives here because two things must AGREE on it: the diagnostics panel that
 * shows it, and the claim mapping a new tenant is given. A mapping that names
 * another install's namespace saves, compiles and resolves no roles, so every
 * user lands on /unauthorized with nothing on the page to say why.
 */
export const ROLES_NAMESPACE: string =
  import.meta.env.VITE_ROLES_NAMESPACE ?? 'https://porth.ems.estynsoftware.io/roles'

/** The claim mapping a tenant needs before anyone can sign in to it.
 *
 * Porth's claim resolver loads the tenant's latest mapping and, finding none,
 * logs "roles will be empty": every user resolves no roles and is denied.
 * Creating a tenant provisions its admin role but not this mapping, so it has
 * to be created separately.
 *
 * schema_version 2.0 is the only version Porth accepts — MappingSource raises
 * "Unsupported schema_version" for anything else — and this is the shape EMS's
 * bootstrap gives the platform tenant. The previous template in both claim
 * mapping pages was version 1 with https://porth.io/roles, so saving it was
 * refused, and would not have resolved roles here even if accepted.
 */
export const DEFAULT_CLAIM_MAPPING = {
  schema_version: '2.0',
  fields: [
    {
      name: 'roles',
      source: ROLES_NAMESPACE,
      type: 'collection',
      required: false,
      ops: [{ op: 'resolve_roles' }],
    },
  ],
  default_roles: [] as string[],
}
