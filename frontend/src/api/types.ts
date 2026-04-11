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

// Tenants — field names match the Porth API Tenant model (PORTH-413)
export interface Tenant {
  tenant_id: string
  org_id: string
  org_name?: string
  display_name: string
  environment_type: 'production' | 'staging' | 'development' | 'sandbox'
  status: 'active' | 'suspended' | 'decommissioning' | 'deleted'
  idp_config_override?: IdpConfig
  created_at: string
  updated_at: string
}
export interface CreateTenantRequest {
  org_id: string; display_name: string; environment_type: 'production' | 'staging' | 'development' | 'sandbox'
  idp_config_override?: IdpConfig
}
export interface UpdateTenantRequest {
  display_name?: string
  idp_config_override?: IdpConfig
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

/** Full provisioning request — syncs JWT claim-resolved roles to DynamoDB. */
export interface ProvisionRequest {
  external_id: string
  organization_id: string
  tenant_id: string
  email: string
  /** Full decoded JWT claims — used by the claim-resolver to sync Porth roles. */
  jwt_claims: Record<string, unknown>
  app_namespace?: string
  first_name?: string
  last_name?: string
  display_name?: string
  avatar_url?: string
}

export interface ProvisionResponse {
  user: User
  is_new: boolean
  /** Porth role IDs that were synced from JWT claims. */
  roles_synced: string[]
  org_unit_resolved: boolean
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
