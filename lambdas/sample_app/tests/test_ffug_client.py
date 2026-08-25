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


# --- initiating asynchronous work (PORTH-621) --------------------------------


class _Recording:
    """A ServiceClient that records the call and answers as ffug would."""

    def __init__(self, response):
        self._response = response
        self.seen = {}

    def call(self, service_id, operation, payload=None, **kwargs):
        self.seen = {"service_id": service_id, "operation": operation,
                     "payload": payload, **kwargs}
        return self._response


def _client(monkeypatch, response):
    recorder = _Recording(response)
    monkeypatch.setattr(ffug_client, "ServiceClient", lambda _d: recorder)
    return recorder


def _accepted(trace="trace-1"):
    return {"ok": True, "operation": "hash_async", "status": "queued", "trace_id": trace}


def test_the_trace_sent_is_the_trace_the_caller_hashed(monkeypatch):
    """Passed in, never minted here.

    The initiator hashes a trace into the record before this runs. If this
    function chose its own, the stored hash would name an identity the call
    never carried and every callback would arrive authentic and refuse to
    correlate — a failure that surfaces at the far end, hours later, looking
    like a mismatch rather than a disagreement here.
    """
    recorder = _client(monkeypatch, _accepted("trace-1"))

    ffug_client.fingerprint_async(_Director(), {"amount": "1"}, trace_id="trace-1")

    assert recorder.seen["trace_id"] == "trace-1"
    assert recorder.seen["operation"] == "hash_async"


def test_the_callback_is_declared_as_a_service_and_an_operation(monkeypatch):
    """Never an address. ffug resolves the endpoint from the D7.4 map at send
    time, so this app cannot hand a worker somewhere to post to — and a worker
    cannot be told to post somewhere else."""
    recorder = _client(monkeypatch, _accepted())

    ffug_client.fingerprint_async(_Director(), {"amount": "1"}, trace_id="trace-1")

    callback = recorder.seen["payload"]["callback"]
    assert callback == {"service_id": "sample-app", "operation": "fingerprint-complete"}
    assert not any(k in str(callback).lower() for k in ("http", "arn:", "://"))


def test_work_accepted_under_a_different_trace_is_a_failure_here(monkeypatch):
    """Caught where the disagreement is, not where it eventually shows.

    Every callback for this record would verify, correlate against the wrong
    trace and be refused — reported at the receiving end as a mismatch, which
    points at the wrong half of the system.
    """
    _client(monkeypatch, _accepted("some-other-trace"))

    with pytest.raises(ffug_client.FingerprintUnavailable, match="some-other-trace"):
        ffug_client.fingerprint_async(_Director(), {"amount": "1"}, trace_id="trace-1")


def test_a_configuration_failure_is_still_not_a_500_on_the_async_path(monkeypatch):
    """The same breadth as the synchronous call, for the same reason — and
    stated separately because it is a second handler that could be narrowed
    back to ServiceCallError without the first one noticing."""
    _client_raising(monkeypatch, ConfigGone("no ssm:GetParameter on /porth/dev/services"))

    with pytest.raises(ffug_client.FingerprintUnavailable):
        ffug_client.fingerprint_async(_Director(), {"amount": "1"}, trace_id="trace-1")


def test_a_refusal_from_ffug_carries_its_own_reason(monkeypatch):
    _client(monkeypatch, {"ok": False, "error": {"code": "tenant_not_provisioned",
                                                 "message": "no salt for this tenant"}})

    with pytest.raises(ffug_client.FingerprintUnavailable, match="tenant_not_provisioned"):
        ffug_client.fingerprint_async(_Director(), {"amount": "1"}, trace_id="trace-1")
