import { apiClient } from './client'
import type { ClaimMappingConfig } from './types'

export const claimConfigsApi = {
  getLatest: (tenantId: string) =>
    apiClient.get<ClaimMappingConfig>(`/claim-mapping-configs/${tenantId}/latest`).then(r => r.data),
  listVersions: (tenantId: string) =>
    apiClient.get<ClaimMappingConfig[]>(`/claim-mapping-configs/${tenantId}/versions`).then(r => r.data),
  getVersion: (tenantId: string, v: number) =>
    apiClient.get<ClaimMappingConfig>(`/claim-mapping-configs/${tenantId}/${v}`).then(r => r.data),
  /** Creates a new config version. tenant_id is a query param per API contract. */
  create: (body: { tenant_id: string; mapping_source: Record<string, unknown>; example_jwt?: Record<string, unknown> }) =>
    apiClient.post<ClaimMappingConfig>(`/claim-mapping-configs/`, body, { params: { tenant_id: body.tenant_id } }).then(r => r.data),
  rollback: (tenantId: string, v: number) =>
    apiClient.post<ClaimMappingConfig>(`/claim-mapping-configs/${tenantId}/rollback/${v}`).then(r => r.data),
}
