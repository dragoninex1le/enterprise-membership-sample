import { apiClient } from './client'
import type { Role, CreateRoleRequest, UpdateRoleRequest } from './types'

export const rolesApi = {
  list: (tenantId: string) => apiClient.get<Role[]>('/roles/', { params: { tenant_id: tenantId } }).then(r => r.data),
  search: (tenantId: string, q?: string, isSystem?: boolean) =>
    apiClient.get<Role[]>('/roles/search', { params: { tenant_id: tenantId, q, is_system: isSystem } }).then(r => r.data),
  get: (tenantId: string, roleId: string) => apiClient.get<Role>(`/roles/${tenantId}/${roleId}`).then(r => r.data),
  create: (body: CreateRoleRequest) => apiClient.post<Role>('/roles/', body).then(r => r.data),
  update: (tenantId: string, roleId: string, body: UpdateRoleRequest) => apiClient.patch<Role>(`/roles/${tenantId}/${roleId}`, body).then(r => r.data),
  delete: (tenantId: string, roleId: string) => apiClient.delete(`/roles/${tenantId}/${roleId}`),
  /** Returns permission keys (strings), not Permission objects. */
  getPermissions: (tenantId: string, roleId: string) =>
    apiClient.get<string[]>(`/roles/${tenantId}/${roleId}/permissions`).then(r => r.data),
  /** Body is a raw string[] of permission keys — not a wrapped object. */
  setPermissions: (tenantId: string, roleId: string, keys: string[]) =>
    apiClient.put<{ message: string; role_id: string; permission_keys: string[] }>(`/roles/${tenantId}/${roleId}/permissions`, keys).then(r => r.data),
  assignToUser: (userId: string, tenantId: string, roleId: string) => apiClient.post(`/roles/users/${userId}/tenant/${tenantId}/roles/${roleId}`),
  removeFromUser: (userId: string, tenantId: string, roleId: string) => apiClient.delete(`/roles/users/${userId}/tenant/${tenantId}/roles/${roleId}`),
  getUserRoles: (userId: string, tenantId: string) => apiClient.get<Role[]>(`/roles/users/${userId}/tenant/${tenantId}/roles`).then(r => r.data),
}
