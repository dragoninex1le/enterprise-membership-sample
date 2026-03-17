import { apiClient } from './client'
import type { ClaimRoleMapping, CreateClaimRoleMappingRequest } from './types'

export const claimMappingsApi = {
  listByTenant: (tenantId: string) => apiClient.get<ClaimRoleMapping[]>(`/claim-role-mappings/tenant/${tenantId}`).then(r => r.data),
  listByNamespace: (tenantId: string, ns: string) => apiClient.get<ClaimRoleMapping[]>(`/claim-role-mappings/tenant/${tenantId}/namespace/${ns}`).then(r => r.data),
  get: (tenantId: string, ns: string, id: string) => apiClient.get<ClaimRoleMapping>(`/claim-role-mappings/${tenantId}/${ns}/${id}`).then(r => r.data),
  create: (body: CreateClaimRoleMappingRequest) => apiClient.post<ClaimRoleMapping>('/claim-role-mappings/', body).then(r => r.data),
  update: (tenantId: string, ns: string, id: string, body: Partial<CreateClaimRoleMappingRequest>) => apiClient.patch<ClaimRoleMapping>(`/claim-role-mappings/${tenantId}/${ns}/${id}`, body).then(r => r.data),
  delete: (tenantId: string, ns: string, id: string) => apiClient.delete(`/claim-role-mappings/${tenantId}/${ns}/${id}`),
}
