import { apiClient } from './client'
import type { Tenant, CreateTenantRequest, UpdateTenantRequest } from './types'

interface TenantListPage { tenants: Tenant[]; next_cursor?: string | null }

/**
 * One tenant of the caller's slot, read through the platform-only list (GET /tenants/, PORTH-576).
 *
 * Not GET /tenants/{id}: that is Porth's PUBLIC pre-login lookup. It runs without the authorizer, so
 * it does not know the caller's slot (ENV#{slot}#, ADR-Z8) and answers a trimmed record with no tier.
 * `q` is a substring match, so the pages are searched for the exact id.
 */
async function findTenant(id: string): Promise<Tenant | null> {
  let cursor: string | undefined
  do {
    const page = (await apiClient.get<TenantListPage>('/tenants/', { params: { q: id, limit: 200, cursor } })).data
    const found = page.tenants.find(t => t.tenant_id === id)
    if (found) return found
    cursor = page.next_cursor ?? undefined
  } while (cursor)
  return null
}

export const tenantsApi = {
  listByOrg: (orgId: string) => apiClient.get<Tenant[]>(`/tenants/organization/${orgId}`).then(r => r.data),
  /** A tenant of the caller's slot, or null when there is none. Platform admins only. */
  find: findTenant,
  /** Adds a tenant to an existing org. Uses PUT per API contract. */
  create: (body: CreateTenantRequest) => apiClient.put<Tenant>('/tenants/', body).then(r => r.data),
  update: (id: string, body: UpdateTenantRequest) => apiClient.patch<Tenant>(`/tenants/${id}`, body).then(r => r.data),
  suspend: (id: string) => apiClient.post<Tenant>(`/tenants/${id}/suspend`).then(r => r.data),
  reactivate: (id: string) => apiClient.post<Tenant>(`/tenants/${id}/reactivate`).then(r => r.data),
  decommission: (id: string) => apiClient.post<Tenant>(`/tenants/${id}/decommission`).then(r => r.data),
}
