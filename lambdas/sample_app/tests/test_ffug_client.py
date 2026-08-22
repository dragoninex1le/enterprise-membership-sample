"""What happens when ffug cannot be reached (PORTH-603).

Both call sites make a promise about failure, and neither promise was kept.

``fingerprint`` says an approval is a business outcome that must not fail
because a fixture service on the internal plane is unreachable — it commits the
decision first and reports the fingerprint's absence on the response.

``isolation_probe`` feeds a diagnostics panel whose entire job is to explain why
things are broken, so it must render rather than raise.

Both caught ``ServiceCallError``, which covers the ways a CALL fails. It does
not cover the ways the plane fails to be RESOLVED: the D3 registry and the D7.4
endpoint map are read first, and ``ConfigurationUnavailableError`` is a
different family. A missing ``ssm:GetParameter`` therefore went past both
handlers — approve() returned 500 with the record already approved, and the
diagnostics page died instead of naming the parameter.
"""

import pytest

from sample_app import ffug_client


class ConfigGone(Exception):
    """Stands in for ConfigurationUnavailableError.

    Deliberately NOT a ServiceCallError subclass, and deliberately not imported
    from porth_common: the property under test is that the handler no longer
    depends on which family the failure belongs to.
    """


class _Boom:
    """A ServiceClient whose call() raises."""

    def __init__(self, exc):
        self._exc = exc

    def call(self, *_args, **_kwargs):
        raise self._exc


class _Director:
    tenant_id = "acme"
    trace_id = "trace-1"


def _client_raising(monkeypatch, exc):
    monkeypatch.setattr(ffug_client, "ServiceClient", lambda _d: _Boom(exc))


def test_a_configuration_failure_does_not_escape_as_a_500(monkeypatch):
    """The promise is "approved but not fingerprinted", never a 500.

    The approval is committed before this runs, so an escaping exception means
    the record changed state while the caller was told the request failed.
    """
    _client_raising(monkeypatch, ConfigGone("no ssm:GetParameter on /porth/dev/services"))

    with pytest.raises(ffug_client.FingerprintUnavailable, match="ssm:GetParameter"):
        ffug_client.fingerprint(_Director(), {"amount": "1"})


def test_the_probe_reports_a_configuration_failure_instead_of_raising(monkeypatch):
    """A diagnostic that dies in the situation it exists to diagnose is worse
    than none. Same shape as PORTH-612."""
    _client_raising(monkeypatch, ConfigGone("no ssm:GetParameter on /porth/dev/services"))

    result = ffug_client.isolation_probe(_Director())

    assert result["ok"] is False
    assert "ssm:GetParameter" in result["error"]


def test_the_reason_survives_to_the_screen(monkeypatch):
    """Rendered as-is rather than replaced with an apology. "approved, but not
    fingerprinted — could not read 'services' from /porth/dev/services" names
    the fix; "something went wrong" sends someone reading application code."""
    _client_raising(monkeypatch, ConfigGone("could not read 'services' from /porth/dev/services"))

    assert "/porth/dev/services" in ffug_client.isolation_probe(_Director())["error"]
