import { apiClient } from './client'
import type { Permission } from './types'

export const permissionsApi = {
  list: (tenantId: string, appNamespace?: string, category?: string) =>
    apiClient.get<Permission[]>('/permissions/', { params: { tenant_id: tenantId, app_namespace: appNamespace, category } }).then(r => r.data),
  get: (tenantId: string, ns: string, key: string) =>
    apiClient.get<Permission>(`/permissions/${tenantId}/${ns}/${key}`).then(r => r.data),
  register: (perms: Omit<Permission, 'id' | 'created_at'>[]) =>
    apiClient.post<Permission[]>('/permissions/', perms).then(r => r.data),
}
