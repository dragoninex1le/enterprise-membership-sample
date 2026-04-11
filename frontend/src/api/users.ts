import { apiClient } from './client'
import type { User, UpsertUserRequest, ProvisionRequest, ProvisionResponse, UserMeRequest, UserMeResponse } from './types'

export const usersApi = {
  listByTenant: (orgId: string, tenantId: string) =>
    apiClient.get<User[]>(`/users/organization/${orgId}/tenant/${tenantId}`).then(r => r.data),
  get: (id: string) => apiClient.get<User>(`/users/${id}`).then(r => r.data),
  getByEmail: (email: string, tenantId: string) =>
    apiClient.get<User>(`/users/email/${encodeURIComponent(email)}/tenant/${tenantId}`).then(r => r.data),
  upsert: (body: UpsertUserRequest) => apiClient.post<User>('/users/upsert', body).then(r => r.data),
  /** Full JIT provisioning — syncs JWT claim-resolved roles to DynamoDB. */
  provision: (body: ProvisionRequest) =>
    apiClient.post<ProvisionResponse>('/users/provision', body).then(r => r.data),
  /**
   * PORTH-413: Single call that provisions (or updates) the user and returns
   * their full Porth context — user record, resolved roles, and effective
   * permission keys — replacing the previous provision + getUserRoles two-step.
   */
  me: (body: UserMeRequest) =>
    apiClient.post<UserMeResponse>('/users/me', body).then(r => r.data),
  update: (id: string, body: Partial<UpsertUserRequest>) => apiClient.patch<User>(`/users/${id}`, body).then(r => r.data),
  suspend: (id: string) => apiClient.post<User>(`/users/${id}/suspend`).then(r => r.data),
  reactivate: (id: string) => apiClient.post<User>(`/users/${id}/reactivate`).then(r => r.data),
}
