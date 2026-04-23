import { apiClient } from './client'
import type { Organization, CreateOrganizationRequest, OrganizationCreateResponse, UpdateOrganizationRequest } from './types'

export const organizationsApi = {
  list: () => apiClient.get<Organization[]>('/organizations/').then(r => r.data),
  get: (id: string) => apiClient.get<Organization>(`/organizations/${id}`).then(r => r.data),
  getBySlug: (slug: string) => apiClient.get<Organization>(`/organizations/slug/${slug}`).then(r => r.data),
  /** Creates org + first tenant atomically. Returns both in the response. */
  create: (body: CreateOrganizationRequest) => apiClient.post<OrganizationCreateResponse>('/organizations/', body).then(r => r.data),
  update: (id: string, body: UpdateOrganizationRequest) => apiClient.patch<Organization>(`/organizations/${id}`, body).then(r => r.data),
}
