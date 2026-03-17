import { createBrowserRouter, Navigate } from 'react-router-dom'
import Layout from './components/Layout'
import OrganizationsPage from './pages/OrganizationsPage'
import TenantsPage from './pages/TenantsPage'
import UsersPage from './pages/UsersPage'
import RolesPage from './pages/RolesPage'
import PermissionsPage from './pages/PermissionsPage'
import ClaimMappingConfigPage from './pages/ClaimMappingConfigPage'
import ClaimRoleMappingPage from './pages/ClaimRoleMappingPage'

export const router = createBrowserRouter([
  {
    path: '/',
    element: <Layout />,
    children: [
      { index: true, element: <Navigate to="/organizations" replace /> },
      { path: 'organizations', element: <OrganizationsPage /> },
      { path: 'organizations/:orgId/tenants', element: <TenantsPage /> },
      { path: 'organizations/:orgId/tenants/:tenantId/users', element: <UsersPage /> },
      { path: 'organizations/:orgId/tenants/:tenantId/roles', element: <RolesPage /> },
      { path: 'organizations/:orgId/tenants/:tenantId/permissions', element: <PermissionsPage /> },
      { path: 'organizations/:orgId/tenants/:tenantId/claim-config', element: <ClaimMappingConfigPage /> },
      { path: 'organizations/:orgId/tenants/:tenantId/claim-mappings', element: <ClaimRoleMappingPage /> },
    ],
  },
])
