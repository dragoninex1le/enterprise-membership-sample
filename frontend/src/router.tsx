import { createBrowserRouter, Navigate } from 'react-router-dom'
import Layout from './components/Layout'
import ProtectedRoute from './components/ProtectedRoute'
import DashboardPage from './pages/DashboardPage'
import ARPage from './pages/ARPage'
import APPage from './pages/APPage'
import ApprovalsPage from './pages/ApprovalsPage'
import UnauthorizedPage from './pages/UnauthorizedPage'
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
      { index: true, element: <Navigate to="/dashboard" replace /> },

      // ── Functional areas ──────────────────────────────────────────────────
      {
        element: <ProtectedRoute roles={['viewer', 'ar_clerk', 'ap_clerk', 'controller', 'admin']} />,
        children: [
          { path: 'dashboard', element: <DashboardPage /> },
        ],
      },
      {
        element: <ProtectedRoute roles={['ar_clerk', 'controller', 'admin']} />,
        children: [
          { path: 'ar', element: <ARPage /> },
        ],
      },
      {
        element: <ProtectedRoute roles={['ap_clerk', 'controller', 'admin']} />,
        children: [
          { path: 'ap', element: <APPage /> },
        ],
      },
      {
        element: <ProtectedRoute roles={['controller', 'admin']} />,
        children: [
          { path: 'approvals', element: <ApprovalsPage /> },
        ],
      },

      // ── Platform admin (Estyn employees — org/tenant onboarding) ──────────
      {
        path: 'admin/platform',
        element: <ProtectedRoute roles={['admin']} />,
        children: [
          { index: true, element: <Navigate to="organizations" replace /> },
          { path: 'organizations', element: <OrganizationsPage /> },
          { path: 'organizations/:orgId/tenants', element: <TenantsPage /> },
        ],
      },

      // ── Tenant admin (local admin — users, roles, permissions) ────────────
      {
        path: 'admin/tenant',
        element: <ProtectedRoute roles={['admin']} />,
        children: [
          { index: true, element: <Navigate to="users" replace /> },
          { path: 'users', element: <UsersPage /> },
          { path: 'roles', element: <RolesPage /> },
          { path: 'permissions', element: <PermissionsPage /> },
          { path: 'claim-config', element: <ClaimMappingConfigPage /> },
          { path: 'claim-mappings', element: <ClaimRoleMappingPage /> },
        ],
      },
    ],
  },
  { path: '/unauthorized', element: <UnauthorizedPage /> },
])
