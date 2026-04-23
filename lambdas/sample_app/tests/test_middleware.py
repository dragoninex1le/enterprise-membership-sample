from sample_app.auth_context import parse_auth_context

def _event(ctx):
    return {"requestContext": {"authorizer": {"lambda": ctx}}}

def test_parse_full_context():
    ctx = parse_auth_context(_event({
        "tenant_id": "t-1", "user_id": "u-1", "roles": "tenant-admin,controller",
        "permissions": "dashboard.read,ar.invoices.read",
        "sts_access_key_id": "AKID", "sts_secret_access_key": "SECRET", "sts_session_token": "TOK",
    }))
    assert ctx["tenant_id"] == "t-1"
    assert ctx["roles"] == ["tenant-admin", "controller"]
    assert ctx["permissions"] == {"dashboard.read", "ar.invoices.read"}
    assert ctx["sts_access_key_id"] == "AKID"

def test_parse_empty_event():
    ctx = parse_auth_context({})
    assert ctx["tenant_id"] is None
    assert ctx["roles"] == []
    assert ctx["permissions"] == set()

def test_parse_empty_roles_string():
    ctx = parse_auth_context(_event({"tenant_id": "t-1", "roles": "", "permissions": ""}))
    assert ctx["roles"] == []
    assert ctx["permissions"] == set()
