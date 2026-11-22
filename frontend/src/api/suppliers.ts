import { apiClient } from './client'
import { sampleApiClient } from './sampleApp'
import type { ClaimMappingConfig } from './types'

/** The supplier network EMS accepts suppliers from (supplier_portal/). */
export const NETWORK = 'supplierlink'

/** Where Porth puts the network's role for a delegated session (Porth docs/delegated-mint.md). */
const DELEGATED_ROLE_SOURCE = 'https://porth.io/delegated/role'
/** Where Porth puts the network's permissions (Porth >= 0.4.26). */
const DELEGATED_PERMISSIONS_SOURCE = 'https://porth.io/delegated/permissions'
const ROLE_TABLE = 'supplierlink_roles'
const PERMISSION_TABLE = 'supplierlink_permissions'

/**
 * The two ways Porth can map a supplier contact to an EMS role. Both are Porth's and both
 * stay tested here: by the contact's SupplierLink role (looked up in a table), or by the
 * contact's SupplierLink permissions (expanded to EMS permissions, then the role holding
 * exactly that set). A tenant's mapping for this network reads one of the two.
 */
export type MappingMethod = 'role' | 'permissions'

export interface BuyerLink {
  buyer: string
  linked_by: string
  linked_at: string
}

/**
 * Porth's claim mapping for this network's sessions in one tenant, built from a table of
 * SupplierLink role -> EMS role registry key.
 *
 * The network's word is trimmed and lower-cased, looked up in the table, and resolved
 * against the tenant's roles. A word the table does not have resolves to no role, and
 * Porth refuses the session (`unmapped_role_claim`). No default roles: a default would
 * reach every supplier contact whatever their role.
 */
export function supplierRoleMapping(table: Record<string, string>): Record<string, unknown> {
  const entries = Object.entries(table)
    .map(([network, ems]) => [network.trim().toLowerCase(), ems] as const)
    .filter(([network, ems]) => network !== '' && ems !== '')
  return {
    schema_version: '2.0',
    default_roles: [],
    lookup_tables: { [ROLE_TABLE]: Object.fromEntries(entries) },
    fields: [
      {
        name: 'roles',
        source: DELEGATED_ROLE_SOURCE,
        type: 'collection',
        ops: [{ op: 'trim' }, { op: 'lowercase' }, { op: 'lookup', table: ROLE_TABLE }, { op: 'resolve_roles' }],
      },
    ],
  }
}

export function roleTableOf(mapping: Record<string, unknown> | undefined): Record<string, string> {
  const tables = (mapping?.lookup_tables ?? {}) as Record<string, Record<string, string>>
  return { ...(tables[ROLE_TABLE] ?? {}) }
}

/**
 * Porth's claim mapping that grants the role whose permissions are exactly what a
 * contact's SupplierLink permissions mean. Each SupplierLink permission maps to one or
 * more EMS permission keys (`expand`, 1:n); one the table does not list means nothing.
 * No role holding exactly the result: Porth refuses the session (`no_role_for_permissions`).
 */
export function supplierPermissionMapping(table: Record<string, string[]>): Record<string, unknown> {
  const entries = Object.entries(table)
    .map(([network, ems]) => [network.trim(), ems.filter(e => e !== '')] as const)
    .filter(([network, ems]) => network !== '' && ems.length > 0)
    .map(([network, ems]) => [network, ems.length === 1 ? ems[0] : [...ems]] as const)
  return {
    schema_version: '2.0',
    default_roles: [],
    lookup_tables: { [PERMISSION_TABLE]: Object.fromEntries(entries) },
    fields: [
      {
        name: 'permissions',
        source: DELEGATED_PERMISSIONS_SOURCE,
        type: 'collection',
        ops: [{ op: 'expand', table: PERMISSION_TABLE }, { op: 'resolve_role_by_permissions' }],
      },
    ],
  }
}

export function permissionTableOf(mapping: Record<string, unknown> | undefined): Record<string, string[]> {
  const tables = (mapping?.lookup_tables ?? {}) as Record<string, Record<string, string | string[]>>
  return Object.fromEntries(
    Object.entries(tables[PERMISSION_TABLE] ?? {}).map(([k, v]) => [k, Array.isArray(v) ? [...v] : [v]]),
  )
}

/** Which method a saved mapping uses: by permissions when it reads the permissions claim. */
export function methodOf(mapping: Record<string, unknown> | undefined): MappingMethod {
  const fields = (mapping?.fields ?? []) as Array<{ source?: string }>
  return fields.some(f => f.source === DELEGATED_PERMISSIONS_SOURCE) ? 'permissions' : 'role'
}

export const suppliersApi = {
  links: () => sampleApiClient.get<BuyerLink[]>('/sample/suppliers/link').then(r => r.data),
  link: (buyer: string) => sampleApiClient.put<BuyerLink>('/sample/suppliers/link', { buyer }).then(r => r.data),
  unlink: (buyer: string) => sampleApiClient.delete(`/sample/suppliers/link/${encodeURIComponent(buyer)}`),

  /** The tenant's mapping for this network — its own lineage, apart from the login mapping. */
  roleMapping: (tenantId: string) =>
    apiClient
      .get<ClaimMappingConfig>(`/claim-mapping-configs/${tenantId}/latest`, { params: { connector_type: NETWORK } })
      .then(r => r.data),
  saveRoleMapping: (tenantId: string, table: Record<string, string>) => saveMapping(tenantId, supplierRoleMapping(table)),
  savePermissionMapping: (tenantId: string, table: Record<string, string[]>) =>
    saveMapping(tenantId, supplierPermissionMapping(table)),
}

function saveMapping(tenantId: string, mapping: Record<string, unknown>) {
  return apiClient
    .post<ClaimMappingConfig>(
      '/claim-mapping-configs/',
      { tenant_id: tenantId, mapping_source: mapping },
      { params: { tenant_id: tenantId, connector_type: NETWORK } },
    )
    .then(r => r.data)
}
