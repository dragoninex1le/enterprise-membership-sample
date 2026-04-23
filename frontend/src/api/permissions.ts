import { apiClient } from './client'
import type { Permission, BatchPermissionRequest, BatchPermissionResponse } from './types'

export const permissionsApi = {
  list: (tenantId: string, appNamespace?: string, category?: string) =>
    apiClient.get<Permission[]>('/permissions/', { params: { tenant_id: tenantId, app_namespace: appNamespace, category } }).then(r => r.data),
  get: (tenantId: string, ns: string, key: string) =>
    apiClient.get<Permission>(`/permissions/${tenantId}/${ns}/${key}`).then(r => r.data),
  /** Batch-register permissions. Body must include tenant_id, app_namespace, and permissions[]. */
  register: (body: BatchPermissionRequest) =>
    apiClient.post<BatchPermissionResponse>('/permissions/', body).then(r => r.data),
}
