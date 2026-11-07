import { apiClient } from './client'
import { sampleApiClient } from './sampleApp'
import type { ClaimMappingConfig } from './types'

/** The supplier network EMS accepts suppliers from (supplier_portal/). */
export const NETWORK = 'supplierlink'

/** Where Porth puts the network's role for a delegated session (Porth docs/delegated-mint.md). */
const DELEGATED_ROLE_SOURCE = 'https://porth.io/delegated/role'
const ROLE_TABLE = 'supplierlink_roles'

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

export const suppliersApi = {
  links: () => sampleApiClient.get<BuyerLink[]>('/sample/suppliers/link').then(r => r.data),
  link: (buyer: string) => sampleApiClient.put<BuyerLink>('/sample/suppliers/link', { buyer }).then(r => r.data),
  unlink: (buyer: string) => sampleApiClient.delete(`/sample/suppliers/link/${encodeURIComponent(buyer)}`),

  /** The tenant's mapping for this network — its own lineage, apart from the login mapping. */
  roleMapping: (tenantId: string) =>
    apiClient
      .get<ClaimMappingConfig>(`/claim-mapping-configs/${tenantId}/latest`, { params: { connector_type: NETWORK } })
      .then(r => r.data),
  saveRoleMapping: (tenantId: string, table: Record<string, string>) =>
    apiClient
      .post<ClaimMappingConfig>(
        '/claim-mapping-configs/',
        { tenant_id: tenantId, mapping_source: supplierRoleMapping(table) },
        { params: { tenant_id: tenantId, connector_type: NETWORK } },
      )
      .then(r => r.data),
}
