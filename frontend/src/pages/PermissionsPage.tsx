// PORTH-130 — Build Role and Permission management screens
import { useParams } from 'react-router-dom'
export default function PermissionsPage() {
  const { tenantId } = useParams()
  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900 mb-2">Permissions</h1>
      <p className="text-gray-400 text-sm">Tenant: {tenantId} &mdash; implementation pending (PORTH-130)</p>
    </div>
  )
}
