import { apiClient } from './client'
import type { Tenant, CreateTenantRequest, UpdateTenantRequest } from './types'

export const tenantsApi = {
  listByOrg: (orgId: string) => apiClient.get<Tenant[]>(`/tenants/organization/${orgId}`).then(r => r.data),
  get: (id: string) => apiClient.get<Tenant>(`/tenants/${id}`).then(r => r.data),
  /** Adds a tenant to an existing org. Uses PUT per API contract. */
  create: (body: CreateTenantRequest) => apiClient.put<Tenant>('/tenants/', body).then(r => r.data),
  update: (id: string, body: UpdateTenantRequest) => apiClient.patch<Tenant>(`/tenants/${id}`, body).then(r => r.data),
  suspend: (id: string) => apiClient.post<Tenant>(`/tenants/${id}/suspend`).then(r => r.data),
  reactivate: (id: string) => apiClient.post<Tenant>(`/tenants/${id}/reactivate`).then(r => r.data),
  decommission: (id: string) => apiClient.post<Tenant>(`/tenants/${id}/decommission`).then(r => r.data),
}
