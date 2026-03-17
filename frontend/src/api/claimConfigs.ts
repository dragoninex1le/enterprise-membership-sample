import { apiClient } from './client'
import type { ClaimMappingConfig } from './types'

export const claimConfigsApi = {
  getLatest: (tenantId: string, ns: string) => apiClient.get<ClaimMappingConfig>(`/claim-mapping-configs/${tenantId}/${ns}/latest`).then(r => r.data),
  listVersions: (tenantId: string, ns: string) => apiClient.get<ClaimMappingConfig[]>(`/claim-mapping-configs/${tenantId}/${ns}/versions`).then(r => r.data),
  getVersion: (tenantId: string, ns: string, v: number) => apiClient.get<ClaimMappingConfig>(`/claim-mapping-configs/${tenantId}/${ns}/${v}`).then(r => r.data),
  create: (body: { tenant_id: string; app_namespace: string; mapping_source: Record<string, unknown>; example_jwt?: Record<string, unknown> }) =>
    apiClient.post<ClaimMappingConfig>('/claim-mapping-configs/', body).then(r => r.data),
  rollback: (tenantId: string, ns: string, v: number) => apiClient.post<ClaimMappingConfig>(`/claim-mapping-configs/${tenantId}/${ns}/rollback/${v}`).then(r => r.data),
}
