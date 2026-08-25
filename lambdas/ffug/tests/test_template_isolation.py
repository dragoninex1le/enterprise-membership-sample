"""The isolation properties that live in IAM, asserted against template.yml.

Behaviour that lives in a permission does not show up in a code diff, and the
half of PORTH-587 that actually does the isolating is entirely in this file's
subject matter. Every assertion here is a property a reviewer would otherwise
have to hold in their head across a 700-line template — and each one, if it
silently regressed, would leave a service that still works and no longer
isolates. That failure mode has a track record: entry 3 of Porth's EMS upgrade
log is a session policy that matched no request path for three releases while
every install reported success.

These run in pytest rather than as a bespoke script in one workflow, so both
the PR gate and the deploy gate execute them.
"""

import json
import pathlib
import re

import pytest
import yaml

TEMPLATE = pathlib.Path(__file__).resolve().parents[3] / "template.yml"


class CfnLoader(yaml.SafeLoader):
    """Enough of CloudFormation's short forms to assert on what they point at."""


def _tag(name):
    def construct(loader, node):
        if isinstance(node, yaml.ScalarNode):
            return {name: loader.construct_scalar(node)}
        if isinstance(node, yaml.SequenceNode):
            return {name: loader.construct_sequence(node, deep=True)}
        return {name: loader.construct_mapping(node, deep=True)}

    return construct


for _short in (
    "Sub", "Ref", "GetAtt", "Equals", "If", "Join", "Select", "Split",
    "FindInMap", "Not", "And", "Or", "Base64", "Condition", "ImportValue",
):
    CfnLoader.add_constructor(f"!{_short}", _tag(_short))


@pytest.fixture(scope="module")
def template():
    return yaml.load(TEMPLATE.read_text(), Loader=CfnLoader)


@pytest.fixture(scope="module")
def resources(template):
    return template["Resources"]


def statements(role):
    """Every statement, with `Fn::If` wrappers unwrapped to the branch they emit.

    Two of these grants are conditional — IAM rejects an empty Resource, so the
    KMS statements only exist when the signing key was resolved. A conditional
    grant is still a grant, and the assertions below have to see through the
    wrapper or they would pass vacuously by finding nothing.
    """
    for policy in role["Properties"].get("Policies", []):
        for statement in policy["PolicyDocument"]["Statement"]:
            if isinstance(statement, dict) and set(statement) == {"If"}:
                _condition, when_true, _when_false = statement["If"]
                yield when_true
            else:
                yield statement


def actions(role):
    found = set()
    for statement in statements(role):
        action = statement["Action"]
        found.update([action] if isinstance(action, str) else action)
    return found


# --- ffug's execution role holds no data access whatsoever -------------------


def test_the_ffug_function_has_an_explicit_role_and_no_inline_policies(resources):
    """SAM rejects Role and Policies together, so this is also how the ambient
    DynamoDB grant is kept out: there is nowhere for it to be added."""
    props = resources["FfugFunction"]["Properties"]

    assert props["Role"] == {"GetAtt": "FfugFunctionRole.Arn"}
    assert "Policies" not in props


def test_ffug_can_reach_no_table_without_narrowing_first(resources):
    """The keystone of PORTH-587, and the assertion most worth keeping.

    ffug used to carry DynamoDBCrudPolicy on its own table. With that grant
    present, a narrowing failure degrades to full-table access and every read
    still succeeds — silently, across every tenant. With it absent, the same
    failure is an AccessDenied. Fail-closed becomes a property of the
    deployment rather than a behaviour some future change could regress.
    """
    for action in actions(resources["FfugFunctionRole"]):
        assert not action.startswith("dynamodb:"), (
            f"FfugFunctionRole grants {action}; ffug must reach data only "
            f"through the credentials it narrows for itself"
        )


def test_a_conditional_grant_is_still_visible_to_these_assertions(resources):
    """Guards the helper above. If `statements()` stopped unwrapping `Fn::If`,
    every KMS assertion here would pass by finding nothing — the vacuous-pass
    failure mode that makes a green suite worse than no suite.

    The subject moved to the UAT runner when ffug's conditional kms:Verify was
    deleted (PORTH-623, local verification). It has to be a grant that is
    ACTUALLY wrapped in `Fn::If`, or the guard stops guarding while still
    passing — which is the exact failure it exists to catch, one level up.
    """
    assert "kms:Sign" in actions(resources["PorthUatRunnerRole"])


def test_ffug_holds_no_kms_at_all_and_therefore_cannot_mint(resources):
    """Head of Security condition H1, and it got stronger.

    ffug is a receiver. It used to hold kms:Verify and never kms:Sign; as of
    porth-common 0.0.11 it verifies locally against the trust document, so it
    holds no KMS permission whatsoever. This role having nothing to sign with
    is what UAT-4 witnesses live, and granting Sign here would not merely widen
    a permission — it would delete the demonstration.

    Asserted as "no kms:* at all" rather than "no kms:Sign", because that is now
    the true property and the weaker form would pass while a Verify crept back.
    """
    granted = actions(resources["FfugFunctionRole"])

    assert not [a for a in granted if a.startswith("kms:")], sorted(granted)


def test_ffugs_only_route_to_data_is_its_tenant_role(resources):
    assumable = [
        s["Resource"]
        for s in statements(resources["FfugFunctionRole"])
        if s["Action"] == "sts:AssumeRole"
    ]

    assert assumable == [{"GetAtt": "FfugTenantRole.Arn"}]


def test_the_narrowing_names_both_an_identity_and_a_rule(resources):
    """IAM says ffug MAY assume its tenant role. These say which role, by what rule.

    Both are read inside the credentials provider and nowhere above it, so
    nothing in ffug's own code mentions either — which is precisely why they
    need asserting here. Neither has a default: lose the identity and there is
    no role to narrow, lose the scope and there is no rule to narrow by, and
    the provider raises NarrowingUnavailableError either way rather than
    running wide. Fail-closed, but a failure at runtime is not the same thing
    as one caught on the pull request.

    The scope is a NAME, and it resolves to a document THIS stack deploys
    (PORTH-600). It used to name Porth's `tenant-scoped-default`, which Porth's
    own pipeline rewrites with --overwrite on every release — a change to the
    platform's narrowing was a change to this service's, in a repo whose tests
    would not have run.
    """
    env = resources["FfugFunction"]["Properties"]["Environment"]["Variables"]

    assert env["PORTH_SERVICE_DATA_IDENTITY"] == {"GetAtt": "FfugTenantRole.Arn"}
    assert env["PORTH_SERVICE_DATA_SCOPE"] == {
        "Select": [4, {"Split": ["/", {"Ref": "FfugSessionPolicy"}]}]
    }


def test_the_scope_name_is_derived_from_the_document_not_spelled_twice(resources):
    """Guards the Select arithmetic above against the parameter path changing.

    `!Ref` on an SSM::Parameter yields its full name; the provider wants the
    last segment. Written as two literals that must agree, this is the standing
    defect shape from the EMS upgrade log — and the symptom would be a
    NarrowingUnavailableError that reads like an unprovisioned tenant.
    """
    name = resources["FfugSessionPolicy"]["Properties"]["Name"]["Sub"]
    index, _split = (
        resources["FfugFunction"]["Properties"]["Environment"]["Variables"][
            "PORTH_SERVICE_DATA_SCOPE"
        ]["Select"]
    )

    assert name.split("/")[index] == "ffug-tenant-scoped"


def test_ffug_deploys_its_own_narrowing_rule_and_does_not_borrow_porths(resources):
    """The document itself: ffug's table, both key shapes, and no Scan.

    Each half fences one axis. The session policy pins the tenant AND the
    table; the role pins the table and any tenant. Porth's shared template says
    Resource "*" deliberately — it is intersected with PorthTenantRole, which
    supplies the table — so borrowing it left the session policy carrying none
    of the isolation and the role carrying all of it.
    """
    document = resources["FfugSessionPolicy"]["Properties"]["Value"]["Sub"]

    assert "${FfugTable.Arn}" in document, "the rule must name ffug's own table"
    assert '"Resource":"*"' not in document

    statement = json.loads(document.replace("${FfugTable.Arn}", "arn:table"))["Statement"][0]
    assert "dynamodb:Scan" not in statement["Action"]

    keys = statement["Condition"]["ForAllValues:StringLike"]["dynamodb:LeadingKeys"]
    # The bare partition is the projection row — the salt lives there, and the
    # '#*' pattern alone cannot match a key with no trailing separator.
    assert keys == ["ENV#$env#TENANT#$tenant", "ENV#$env#TENANT#$tenant#*"]


def test_the_session_policy_fits_inside_the_sts_ceiling(resources):
    """STS caps an inline session policy at 2048 characters, and the render only
    grows it. Porth's template stayed simple for this reason; ffug's names a
    table ARN on top, so the headroom is worth asserting rather than assuming."""
    document = resources["FfugSessionPolicy"]["Properties"]["Value"]["Sub"]
    rendered = document.replace(
        "${FfugTable.Arn}", "arn:aws:dynamodb:eu-west-2:000000000000:table/porth-ffug-dev"
    )

    assert len(rendered) < 2048, len(rendered)


def test_ffug_can_read_the_template_its_narrowing_renders(resources):
    """The grant that makes the scope above reachable at all.

    Easy to lose, because it is a permission on a different resource than the
    one being isolated — the rule for reaching DynamoDB is fetched from the
    parameter store. Without this read the narrowing refuses before it ever
    reaches STS, and the symptom is a tenant that looks unprovisioned rather
    than a grant that is missing.
    """
    reads = [
        s for s in statements(resources["FfugFunctionRole"])
        if s["Action"] == "ssm:GetParameter"
    ]
    assert reads, "ffug cannot fetch its session-policy template"

    arns = [a["Sub"] for read in reads for a in read["Resource"]]
    assert any(arn.endswith("/auth-session-policy/*") for arn in arns), arns


# --- the tenant role's ceiling ----------------------------------------------


def test_the_tenant_role_is_bound_by_a_leading_key_condition(resources):
    """The session policy narrows to ONE tenant; this ceiling keeps the role
    from reaching anything that is not tenant-keyed at all."""
    for statement in statements(resources["FfugTenantRole"]):
        keys = statement["Condition"]["ForAllValues:StringLike"]["dynamodb:LeadingKeys"]
        assert keys == ["ENV#*#TENANT#*", "ENV#*#TENANT#*#*"]


def test_the_tenant_role_grants_no_scan(resources):
    """Scan is the one action no key condition can constrain.

    It populates no dynamodb:LeadingKeys, so ForAllValues passes vacuously
    against it — a Scan grant inside a conditioned statement reads as bounded
    and is not. Porth carries the same trap on its platform session policy
    (PORTH-580); ffug simply never scans, so it never needs one.
    """
    assert "dynamodb:Scan" not in actions(resources["FfugTenantRole"])


def test_the_tenant_role_reaches_only_ffugs_own_table(resources):
    for statement in statements(resources["FfugTenantRole"]):
        assert statement["Resource"] == {"GetAtt": "FfugTable.Arn"}


# --- the bus subscription ---------------------------------------------------


def test_the_lifecycle_rule_is_on_porths_bus_not_the_default_one(resources):
    """A rule that omits EventBusName is created against `default`, matches
    nothing, and reports no error — which is exactly how the sample app's
    EntityEvent consumer has sat inert."""
    rule = resources["FfugLifecycleFunction"]["Properties"]["Events"]["TenantLifecycle"]

    assert rule["Properties"]["EventBusName"] == {"Ref": "PorthEventBusName"}


def test_the_lifecycle_rule_matches_the_contract_channel(resources):
    """Lowercase `tenant.*` is contract v1. The capitalised `Tenant.*` domain
    events are the audit/search feed and are explicitly not this contract."""
    pattern = resources["FfugLifecycleFunction"]["Properties"]["Events"]["TenantLifecycle"][
        "Properties"
    ]["Pattern"]

    assert pattern["source"] == ["porth.user-management"]
    assert set(pattern["detail-type"]) == {
        "tenant.created",
        "tenant.updated",
        "tenant.suspended",
        "tenant.reactivated",
        "tenant.deleted",
    }


def test_the_consumer_holds_no_signing_or_narrowing_permission(resources):
    """It maintains a projection from a bus. A bus event is not an envelope,
    so there is nothing for it to verify and nothing for it to assume."""
    granted = actions(resources["FfugLifecycleFunctionRole"])

    assert not any(a.startswith(("kms:", "sts:")) for a in granted)


# --- the deletion marker is actually bounded --------------------------------


def test_the_table_expires_the_deletion_marker(resources):
    """`tenant.deleted` leaves a stripped row as the order gate against a late
    pre-deletion event, and stamps expires_at on it. Without the TTL
    specification that attribute is inert and the marker is permanent — which
    would make it residue, and residue-free teardown is a UAT-5 assertion."""
    ttl = resources["FfugTable"]["Properties"]["TimeToLiveSpecification"]

    assert ttl == {"AttributeName": "expires_at", "Enabled": True}


# --- the signer -------------------------------------------------------------


def test_the_uat_runner_can_mint_context(resources):
    """Without this grant nothing in the account can sign, the internal plane
    has no caller, and ffug's kms:Sign denial proves nothing because everything
    is denied. See Components PR #294 entries 14-15."""
    assert "kms:Sign" in actions(resources["PorthUatRunnerRole"])


# --- the guard that cost a rolled-back stack --------------------------------


LATIN1_PRINTABLE = re.compile("^[\t\n\r\x20-\x7e\xa1-\xff]*$")


def test_iam_role_descriptions_are_iam_legal(resources):
    """IAM rejects any character outside Latin-1 printable — notably the em
    dash this codebase uses freely in prose. CloudFormation only finds out
    mid-deploy and rolls the whole stack back (run 31216080066)."""
    offenders = []
    # ManagedPolicy as well as Role. IAM applies the same rule to both
    # descriptions, and the version of this test that checked only roles would
    # have passed a managed policy straight into the mid-deploy rollback it
    # exists to prevent — PORTH-586 added one and it was clean by luck.
    for name, resource in resources.items():
        if resource.get("Type") not in ("AWS::IAM::Role", "AWS::IAM::ManagedPolicy"):
            continue
        description = resource["Properties"].get("Description")
        if isinstance(description, str) and not LATIN1_PRINTABLE.match(description):
            bad = sorted({hex(ord(c)) for c in description if not LATIN1_PRINTABLE.match(c)})
            offenders.append(f"{name}: illegal {bad}")

    assert offenders == []


# --- PORTH-623: one key per minting service ----------------------------------


def _all_statements(node, path=()):
    """Every IAM statement in the template, with the resource path that holds it.

    Walks rather than indexing because the two shapes differ: an
    `AWS::IAM::Role` carries `Properties.Policies[].PolicyDocument.Statement`,
    while a SAM function's inline `Policies[].Statement` has no PolicyDocument
    wrapper. A Sign-grant audit that only understood one shape would report a
    clean sweep while missing the other — and `SampleAppFunction`, the one that
    actually mints, uses the shape the role helper above cannot see.
    """
    if isinstance(node, dict):
        if "Effect" in node and "Action" in node:
            yield path, node
        for key, value in node.items():
            yield from _all_statements(value, path + (str(key),))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _all_statements(value, path + (str(index),))


def _grants(template, action):
    """Resource names whose statements grant *action*, with the Resource given."""
    found = {}
    for path, statement in _all_statements(template.get("Resources", {})):
        actions = statement["Action"]
        actions = [actions] if isinstance(actions, str) else actions
        if action in actions:
            found.setdefault(path[0], []).append(statement.get("Resource"))
    return found


def test_every_signer_signs_with_the_key_its_direction_entitles_it_to(template):
    """The allow-list that stops the shared-key blast radius coming back.

    A new Sign grant is how it returns: one function at a time, each
    individually reasonable. So this pins WHICH KEY each signer holds, not just
    which roles appear — the name list alone would pass if the worker were
    quietly given the install key, which is the failure worth catching.

    Three signers, two keys:

    * the app and the UAT runner sign REQUESTS, on the install key. The app is
      not a service in the per-direction model, so the install key is its
      request key; the runner mints as `porth` on the same key.
    * the worker signs RESPONSES, on ffug's own key. A completing service holds
      response authority and nothing else, so it cannot originate work even as
      itself — the capability is absent rather than unused.

    ffug's REQUEST path appears nowhere, and that is what UAT-4 witnesses.
    """
    expected = {
        "SampleAppFunction": {"Ref": "PorthContextSigningKeyArn"},
        "PorthUatRunnerRole": {"Ref": "PorthContextSigningKeyArn"},
        "FfugWorkerFunctionRole": {"Ref": "FfugResponseSigningKeyArn"},
    }
    signers = _grants(template, "kms:Sign")

    assert set(signers) == set(expected), (
        f"kms:Sign holders changed: {sorted(signers)}. A new holder is a new "
        f"forgery capability for whatever that key may speak as, not a widened "
        f"permission."
    )
    for role, key in expected.items():
        assert signers[role] == [key], (
            f"{role} signs with {signers[role]}, expected {key}. Signing with "
            f"another party's key is the shared-key problem PORTH-623 removed."
        )

    assert "FfugFunctionRole" not in signers, (
        "the request path gained kms:Sign. That role holding nothing to sign "
        "with is the demonstration, not an incidental permission."
    )


def test_nothing_verifies_with_kms_because_verification_is_local(template):
    """The grant that used to be here is gone, and its absence is the design.

    porth-common 0.0.11 carries each key's public half in the trust document and
    checks ECDSA-P256 locally, so there is no KMS call at verify time. Two
    things fall out, and the second is the one that cost time before:

    * the N-by-N Verify grant matrix disappears — every receiver needed Verify
      on every key that might sign to it, and that list grew with the install;
    * a missing grant can no longer masquerade as `bad_signature`. There is no
      grant to miss, so the failure that read as forgery and was actually IAM
      cannot occur.

    Asserted as a whole-template property rather than on one role, because the
    way this regresses is someone adding Verify back "just for this service".
    """
    assert _grants(template, "kms:Verify") == {}, (
        "kms:Verify reappeared. Verification is local as of porth-common "
        "0.0.11 — a Verify grant means something is calling KMS at verify time "
        "again, which is the grant matrix and the misleading failure both back."
    )


def test_the_app_has_no_signing_key_of_its_own(template):
    """The app is not a service, and re-adding a key for it would be a
    regression that looks like symmetry.

    A second key for the same party is a second REQUEST authority, not a
    separation of concerns. What per-service keys separate is direction — and
    ffug's response key is the only one this install needs, because ffug is the
    only party that signs something other than a request.
    """
    parameters = template["Parameters"]

    assert "SampleAppSigningKeyArn" not in parameters, (
        "the sample app must sign with the install key — a key of its own would "
        "be a second request authority for the same party (PORTH-623)"
    )
    for name in ("PorthContextSigningKeyArn", "FfugResponseSigningKeyArn"):
        assert name in parameters, f"{name} is missing"
        assert parameters[name].get("Default") == "", (
            f"{name} must default to empty — absent a key the service deploys "
            f"with no signer and refuses at the boundary rather than sending "
            f"something unsigned"
        )


# --- the asynchronous half (PORTH-620) ---------------------------------------


def test_the_worker_reports_batch_item_failures(resources):
    """Without this the whole batch is deleted on a normal return, refused
    records included.

    That is the isolation failure the per-record iterator exists to prevent,
    reappearing one layer down: a record the iterator correctly refused to
    build a Director for would vanish, and the refusal it logged would be the
    only trace. The property is a single line of YAML with no runtime symptom,
    which is exactly the kind that gets dropped in a refactor.
    """
    events = resources["FfugWorkerFunction"]["Properties"]["Events"]
    source = next(e for e in events.values() if e["Type"] == "SQS")

    assert source["Properties"]["FunctionResponseTypes"] == ["ReportBatchItemFailures"]


def test_the_work_queue_is_not_fifo(resources):
    """The drainer is built for at-least-once and unordered delivery, and every
    property it holds is per record. FIFO would buy ordering nothing needs and
    charge a per-tenant group key for it."""
    queue = resources["FfugWorkQueue"]["Properties"]

    assert not queue.get("FifoQueue")
    assert not queue["QueueName"]["Sub"].endswith(".fifo")


def test_a_record_that_cannot_be_drained_ends_somewhere_visible(resources):
    """Bounded redelivery. A refused record goes back on the queue by design,
    so without a maxReceiveCount 'goes back' means forever."""
    redrive = resources["FfugWorkQueue"]["Properties"]["RedrivePolicy"]

    assert redrive["maxReceiveCount"] <= 5
    assert redrive["deadLetterTargetArn"] == {
        "GetAtt": "FfugWorkDeadLetterQueue.Arn"
    }


def test_the_queue_outlasts_one_invocations_worth_of_work(resources):
    """Visibility timeout above the function's timeout, or a slow record is
    redelivered while the first copy is still hashing it — two callbacks for one
    request, and the initiator's correlation hash matches both."""
    visibility = resources["FfugWorkQueue"]["Properties"]["VisibilityTimeout"]
    timeout = resources["FfugWorkerFunction"]["Properties"]["Timeout"]

    assert visibility >= timeout * 6


def test_the_worker_holds_no_standing_table_access(resources):
    """The same property as the request path, which is why it is asserted the
    same way rather than assumed to follow. The worker reaches data only after
    narrowing per record."""
    found = actions(resources["FfugWorkerFunctionRole"])

    assert not [a for a in found if a.startswith("dynamodb:")], found


def test_the_request_path_can_queue_work_but_not_drain_it(resources):
    """Send only.

    A role that could both enqueue and dequeue would let the ingress complete
    work under the caller's own credential, which is the crossing this design
    replaced. It stays a producer.
    """
    found = actions(resources["FfugFunctionRole"])

    assert "sqs:SendMessage" in found
    assert "sqs:ReceiveMessage" not in found
    assert "sqs:DeleteMessage" not in found
