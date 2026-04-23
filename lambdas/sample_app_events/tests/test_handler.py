from unittest.mock import MagicMock
import sample_app_events.handler as h

def run(event):
    mock_table = MagicMock()
    h._table = mock_table
    h.handler(event, None)
    return mock_table

def test_user_created():
    table = run({"detail": {
        "entity_type": "User", "action": "created", "entity_id": "u-1",
        "timestamp": "2026-04-22T00:00:00Z", "metadata": {"tenant_id": "t-1"},
        "after": {"display_name": "Alice", "email": "alice@example.com", "status": "active"},
    }})
    item = table.put_item.call_args[1]["Item"]
    assert item["pk"] == "TENANT#t-1"
    assert item["sk"] == "USER_CACHE#u-1"
    assert item["display_name"] == "Alice"

def test_tenant_created():
    table = run({"detail": {
        "entity_type": "Tenant", "action": "created", "entity_id": "t-1",
        "timestamp": "2026-04-22T00:00:00Z", "metadata": {"tenant_id": "t-1"},
        "after": {"display_name": "Acme Dev", "status": "active"},
    }})
    item = table.put_item.call_args[1]["Item"]
    assert item["pk"] == "PLATFORM"
    assert item["sk"] == "TENANT_CACHE#t-1"

def test_unknown_entity_ignored():
    table = run({"detail": {"entity_type": "Permission", "action": "created", "metadata": {}, "after": {}}})
    table.put_item.assert_not_called()
