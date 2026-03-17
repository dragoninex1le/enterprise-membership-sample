import { apiClient } from './client'
import type { Tenant, CreateTenantRequest, UpdateTenantRequest } from './types'

export const tenantsApi = {
  listByOrg: (orgId: string) => apiClient.get<Tenant[]>(`/tenants/organization/${orgId}`).then(r => r.data),
  get: (id: string) => apiClient.get<Tenant>(`/tenants/${id}`).then(r => r.data),
  create: (body: CreateTenantRequest) => apiClient.post<Tenant>('/tenants/', body).then(r => r.data),
  update: (id: string, body: UpdateTenantRequest) => apiClient.patch<Tenant>(`/tenants/${id}`, body).then(r => r.data),
}
