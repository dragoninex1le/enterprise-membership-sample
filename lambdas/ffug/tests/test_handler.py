from unittest.mock import MagicMock

import pytest

import ffug.handler as h


@pytest.fixture(autouse=True)
def table():
    """Substitute the module-level table handle (sample_app_events convention)."""
    mock = MagicMock()
    h._table = mock
    yield mock
    h._table = None


def test_echo_stores_under_env_and_tenant_keys(table):
    result = h.handler(
        {
            "environment": "dev",
            "tenant_id": "acme",
            "op": "echo",
            "item_id": "i-1",
            "payload": {"hello": "world"},
        }
    )

    assert result == {
        "ok": True,
        "op": "echo",
        "item_id": "i-1",
        "payload": {"hello": "world"},
    }
    item = table.put_item.call_args[1]["Item"]
    assert item["pk"] == "ENV#dev#TENANT#acme"
    assert item["sk"] == "ITEM#i-1"
    assert item["payload"] == {"hello": "world"}


def test_echo_is_the_default_op(table):
    h.handler({"environment": "dev", "tenant_id": "acme", "item_id": "i-1", "payload": 1})
    assert table.put_item.called


def test_get_reads_back_under_the_same_keys(table):
    table.get_item.return_value = {"Item": {"payload": {"hello": "world"}}}

    result = h.handler(
        {"environment": "dev", "tenant_id": "acme", "op": "get", "item_id": "i-1"}
    )

    assert result["ok"] is True
    assert result["payload"] == {"hello": "world"}
    assert table.get_item.call_args[1]["Key"] == {
        "pk": "ENV#dev#TENANT#acme",
        "sk": "ITEM#i-1",
    }


def test_get_missing_item_is_a_typed_rejection(table):
    table.get_item.return_value = {}

    result = h.handler(
        {"environment": "dev", "tenant_id": "acme", "op": "get", "item_id": "nope"}
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "not_found"


# --- fail-closed context resolution (the Phase B swap point) -----------------


@pytest.mark.parametrize(
    "event,code",
    [
        ({"tenant_id": "acme", "item_id": "i-1", "payload": 1}, "missing_environment"),
        ({"environment": "dev", "item_id": "i-1", "payload": 1}, "missing_tenant"),
        ({"environment": "  ", "tenant_id": "acme"}, "missing_environment"),
        ({"environment": "dev", "tenant_id": "  "}, "missing_tenant"),
    ],
)
def test_missing_context_is_refused_never_defaulted(table, event, code):
    result = h.handler(event)

    assert result["ok"] is False
    assert result["error"]["code"] == code
    # The point of the assertion: nothing was written under a fallback tenant.
    assert not table.put_item.called


def test_unknown_op_is_refused(table):
    result = h.handler({"environment": "dev", "tenant_id": "acme", "op": "delete_everything"})

    assert result["ok"] is False
    assert result["error"]["code"] == "unknown_op"
    assert not table.put_item.called


def test_echo_requires_item_id_and_payload(table):
    assert h.handler({"environment": "dev", "tenant_id": "acme", "payload": 1})["error"][
        "code"
    ] == "missing_item_id"
    assert h.handler({"environment": "dev", "tenant_id": "acme", "item_id": "i-1"})["error"][
        "code"
    ] == "missing_payload"
    assert not table.put_item.called


def test_empty_invocation_is_refused(table):
    assert h.handler({})["error"]["code"] == "missing_environment"
    assert h.handler(None)["error"]["code"] == "missing_environment"
