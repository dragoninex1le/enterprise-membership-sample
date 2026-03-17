// Organizations
export interface IdpConfig {
  provider: string
  domain: string
  client_id: string
  audience?: string
  custom_claims?: Record<string, string>
}
export interface Organization {
  id: string; name: string; slug: string; status: 'active' | 'suspended'
  idp_config?: IdpConfig; created_at: string; updated_at: string
}
export interface CreateOrganizationRequest { name: string; slug: string; idp_config?: IdpConfig }
export interface UpdateOrganizationRequest { name?: string; idp_config?: IdpConfig }

// Tenants
export interface Tenant {
  id: string; organization_id: string; name: string
  environment_type: 'dev' | 'staging' | 'prod'; status: 'active' | 'suspended'
  idp_config_override?: IdpConfig; feature_flags?: Record<string, boolean>
  created_at: string; updated_at: string
}
export interface CreateTenantRequest {
  organization_id: string; name: string; environment_type: 'dev' | 'staging' | 'prod'
  idp_config_override?: IdpConfig; feature_flags?: Record<string, boolean>
}
export interface UpdateTenantRequest {
  name?: string; status?: 'active' | 'suspended'
  idp_config_override?: IdpConfig; feature_flags?: Record<string, boolean>
}

// Users
export interface User {
  id: string; external_id: string; email: string
  first_name?: string; last_name?: string; display_name?: string; avatar_url?: string
  organization_id: string; tenant_id: string; status: 'active' | 'suspended'
  is_org_admin: boolean; last_login_at?: string; suspended_at?: string
  created_at: string; updated_at: string
}
export interface UpsertUserRequest {
  external_id: string; email: string; organization_id: string; tenant_id: string
  first_name?: string; last_name?: string; display_name?: string; avatar_url?: string
}

// Permissions
export interface Permission {
  id: string; key: string; display_name: string; description?: string
  app_namespace: string; tenant_id: string; category?: string
  sort_order?: number; created_at: string
}

// Roles
export interface Role {
  id: string; tenant_id: string; name: string; description?: string
  is_system: boolean; created_at: string; updated_at: string
}
export interface CreateRoleRequest { tenant_id: string; name: string; description?: string }
export interface UpdateRoleRequest { name?: string; description?: string }

// Claim Role Mappings
export interface ClaimRoleMapping {
  id: string; tenant_id: string; app_namespace: string
  claim_key: string; claim_value: string; role_id: string
  priority: number; is_active: boolean; created_at: string; updated_at: string
}
export interface CreateClaimRoleMappingRequest {
  tenant_id: string; app_namespace: string; claim_key: string
  claim_value: string; role_id: string; priority: number; is_active?: boolean
}

// Claim Mapping Configs
export interface ClaimMappingConfig {
  id: string; tenant_id: string; app_namespace: string; version: number
  mapping_source: Record<string, unknown>; compiled_ops?: unknown[]
  compiled_hash?: string; example_jwt?: Record<string, unknown>
  validation_report?: string; compiled_at?: string; created_at: string
}
