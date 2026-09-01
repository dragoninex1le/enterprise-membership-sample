# EMS's install-once infrastructure.
#
# One thing lives here today: the per-service context-signing keys (PORTH-623).
# They are in Terraform rather than template.yml for the reason Porth's own keys
# are — these are created once and destroyed never, and sharing a destruction
# blast radius with code that is redeployed on every release is what cost EMS
# its Porth stack on 2026-08-15 (Components docs/porth-0.2.0-ems-upgrade-log.md).
#
# CloudFormation could retain them with DeletionPolicy, but retention is not
# management: a retained key survives a stack delete *unaliased and orphaned*,
# which is the state the upgrade log's standing note describes as "the keys look
# absent — they are not, find them by description".
#
# Deliberately NOT in Porth's install-once module. ffug and the sample app are
# EMS's services; Components has no business knowing they exist, and an
# empty-by-default variable over there would still be the shape of this install
# leaking into the shared module. Same ruling as the shipped services-config
# documents: nothing is set upstream, it is entirely down to the application.

# Explicitly configured, not inherited from the environment. Terraform's
# `validate` does not check that a provider CAN be configured, so a module
# without this passes validation and then fails at plan with
# `Error: invalid AWS Region:` — an empty value and no indication of where it
# was supposed to come from.
provider "aws" {
  region = var.aws_region

  default_tags {
    tags = local.common_tags
  }
}

data "aws_caller_identity" "current" {}

locals {
  # Keyed "service/direction" — unique per pair, and readable in plan output.
  signing_keys = { for k in var.signing_keys : "${k.service_id}/${k.direction}" => k }

  common_tags = merge(
    {
      Project     = "enterprise-membership-sample"
      PorthBranch = var.porth_branch
      ManagedBy   = "terraform"
      Module      = "ems-install-once"
    },
    var.tags,
  )
}

# ADR-Z11 D7 / PORTH-547 — asymmetric, not a symmetric MAC. With
# GenerateMac/VerifyMac every verifier would hold the permission a signer needs,
# so a compromised receiving service could mint context for any tenant and the
# defence-in-depth layer would become the attack surface.
#
# The policy is copied from Porth's key rather than abstracted, and that is on
# purpose. The two statements ARE the per-install containment (HoS M3): the
# account-root Allow alone leaves cross-account access to whatever a future
# key-policy edit permits, while the explicit Deny refuses it for every
# principal outside the account regardless of what else is added. A key created
# here that quietly lacked the second statement would look identical in the
# console.
resource "aws_kms_key" "service_signing" {
  for_each = local.signing_keys

  description              = "EMS ${each.value.direction} signing key for ${each.value.service_id} (${var.porth_branch})"
  key_usage                = "SIGN_VERIFY"
  customer_master_key_spec = "ECC_NIST_P256"
  enable_key_rotation      = false # not supported for asymmetric keys
  deletion_window_in_days  = var.kms_deletion_window_days
  tags = merge(local.common_tags, {
    Component = "ContextSigning"
    Service   = each.value.service_id
    Direction = each.value.direction
  })

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AccountRootFullAccess"
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root" }
        Action    = "kms:*"
        Resource  = "*"
      },
      {
        Sid       = "SameAccountOnly"
        Effect    = "Deny"
        Principal = "*"
        Action    = "kms:*"
        Resource  = "*"
        Condition = {
          StringNotEquals = {
            "aws:PrincipalAccount" = data.aws_caller_identity.current.account_id
          }
        }
      },
    ]
  })
}

# For humans, and for M2 rotation. NOT what goes in the trust list: `kid` there
# is the concrete key ARN, because an alias is a moving pointer and a trust list
# pointing at one would trust whatever it was moved to.
resource "aws_kms_alias" "service_signing" {
  for_each = local.signing_keys

  name          = "alias/porth-context-${each.value.service_id}-${each.value.direction}-${var.porth_branch}"
  target_key_id = aws_kms_key.service_signing[each.key].key_id
}

# ── The trust documents (PORTH-625) ───────────────────────────────────────
#
# One document per service, and each has exactly ONE owner — which is what
# makes writing them from here correct rather than a shortcut. The merge
# behaviour `porth-install signing-key register` provides exists for a shared
# document with several writers; under the per-service shape there is no other
# writer for this one to merge with.
#
# ONE document, and that is the whole shape now (Richard, 2026-08-27). ffug is
# the service; the sample app is not a second one, it is ffug's front half.
#
# The callback ingress is NOT described here, and that is the later correction
# (PORTH-624). This document says where ffug is called, what it signs with, and
# whether it is active. Where a requester receives its answers is supplied by
# that requester at request time — see `local.endpoints`.
#
# There used to be a hand-written `sample-app` document merged in beside this,
# holding Porth's install key as "the app's request key". It existed because a
# token's signer is looked up by the service it claims to be from, and the app
# claimed to be someone else. It no longer does, so the document has no reader
# and is removed — `terraform apply` destroys the parameter.
#
# Nothing is validated away by doing it here either. That command refuses a key
# that is not SIGN_VERIFY/ECC_NIST_P256 — a check for a CLI handed an arbitrary
# ARN, and one this module cannot fail, because it CREATES the key with that
# spec. What it does that Terraform cannot is validate the result through the
# runtime's own loader; test_signing_key_document_shape.py covers that instead,
# in CI, which is earlier than the CLI would have.
#
# The alternative was a manual step run beside `terraform apply`, and this is
# better on the thing that matters: the document cannot drift from the keys,
# because the same apply produces both.

# `public_key` is base64-encoded DER SubjectPublicKeyInfo, which is exactly what
# SigningKeyEntry.public_key wants — nothing re-encodes it in between. Called
# once here, at provisioning, which is the whole reason verification can be
# local and no kms:Verify grant exists anywhere.
#
# Porth's install key is no longer read here. It was fetched to describe the app
# as a service of its own, and the app is not one — see the `trust_documents`
# comment below.
data "aws_kms_public_key" "service_signing" {
  for_each = local.signing_keys

  key_id = aws_kms_key.service_signing[each.key].arn
}

locals {
  # Where each service is reached, per direction. Named here rather than inline
  # so the two places a target appears — the document and the IAM grant that
  # lets the caller invoke it — cannot disagree about a function name.
  #
  # Where each service is CALLED. That is all the registry holds about
  # addresses now (PORTH-624, Richard 2026-08-27).
  #
  # There was a `response` entry here naming this app's callback ingress. It is
  # gone, and not because it moved: a requester supplies its own callback
  # address when it asks for work, being the one participant that certainly
  # knows where it listens. Porth does not need a copy.
  #
  # A copy could only ever name ONE requester. Keying it by callee collided on
  # the second caller; keying it by requester merely moved the collision into a
  # document somebody other than its subject has to keep current. Not holding
  # it removes the problem rather than relocating it.
  #
  # What a callback still takes from here is the KEY — ffug signs a completion
  # with its response key, below — and the requester's status. The address is
  # the only part that left.
  # `$${environment}` is written LITERALLY into the document; porth-common
  # substitutes it at resolve time from the Director's verified environment
  # claim (porth-common 0.0.17, EndpointDefinition.for_environment).
  #
  # It has to be the placeholder rather than a value. EMS now deploys one stack
  # per environment and both declare PORTH_SERVICE_ID: ffug, so they share this
  # one services/ffug document — a literal name here would send porth-dau's
  # requests to porth-sample's function. This module runs once and cannot know
  # which environment is calling; the caller does (PORTH-627).
  endpoints = {
    ffug = {
      request = "ems-ffug-$${environment}"
    }
  }

  # service_id -> the whole of services/{service_id}.
  #
  # Built from the pairs rather than hardcoded, so adding a (service, direction)
  # to the variable produces its binding without editing this. No `merge()`
  # around it any more: the second argument was the hand-written `sample-app`
  # document, and generating every document from one rule is the point.
  trust_documents = {
    for service in distinct([for k in var.signing_keys : k.service_id]) :
    service => {
      contract_version = 1
      service_id       = service
      # One document per service now carries everything the internal plane
      # asks about a callee (PORTH-623): may I call it, where is it, whose
      # signature should I expect. It replaced three documents — the services
      # registry, the endpoint map and the per-service key list — two of which
      # were monoliths every participant had to merge into.
      status = "active"
      # No `directions` map. A callback address is supplied by the party that
      # receives it, so there is nothing here to point at one.
      endpoints = {
        default = { mode = "invoke", target = local.endpoints[service].request }
      }
      keys = [
        for key, pair in local.signing_keys : {
          # The ALIAS, not the key ARN (PORTH-623, Richard 2026-08-25). This
          # field answers "what does this service sign with", and an alias is
          # the right answer precisely because it moves: rotation repoints it
          # and the signer follows with no document edit.
          #
          # NOT the kid. The kid identifies which key produced a signature and
          # already travels in the envelope header — storing a copy here would
          # duplicate what the token carries.
          alias       = aws_kms_alias.service_signing[key].name
          direction   = pair.direction
          public_key  = data.aws_kms_public_key.service_signing[key].public_key
          description = "EMS ${pair.service_id} ${pair.direction}"
        } if pair.service_id == service
      ]
    }
  }
}

resource "aws_ssm_parameter" "signing_keys" {
  for_each = local.trust_documents

  name        = "/porth/${var.porth_branch}/services/${each.key}"
  description = "Everything the internal plane knows about ${each.key}: status, endpoints, signing keys (PORTH-623)."
  type        = "String"
  value       = jsonencode(each.value)
  overwrite   = true
  tags        = merge(local.common_tags, { Service = each.key })
}

# A KMS key has no deterministic identifier — only its alias is predictable, and
# an alias ARN cannot be the Resource of an IAM policy for key operations. So
# the ARN is published where the deploy can read it.
#
# The path matches the one Porth's module uses for its own key, keyed by
# service_id: Porth publishes `porth`'s, EMS publishes ffug's and sample-app's.
# One convention, different owners, no collision — an operator sees the same
# shape whichever service they are looking at.
#
# Two readers: deploy.yml, which passes the ARN as a stack parameter so the
# template can grant Sign or Verify on it, and the step that merges this
# service's binding into /porth/{branch}/signing-keys.
resource "aws_ssm_parameter" "service_signing_key_arn" {
  for_each = local.signing_keys

  name        = "/porth/${var.porth_branch}/infra/signing-key-arn/${each.value.service_id}/${each.value.direction}"
  description = "EMS ${each.value.direction} signing key ARN for ${each.value.service_id}. Read by the EMS deploy."
  type        = "String"
  value       = aws_kms_key.service_signing[each.key].arn
  overwrite   = true
  tags = merge(local.common_tags, {
    Service   = each.value.service_id
    Direction = each.value.direction
  })
}

# ── The deploy role's app-specific grants (PORTH-620/621) ────────────────────
#
# Attached rather than owned. The role itself is CloudFormation's, from Porth's
# receiving-account bootstrap; this is a separately-named inline policy beside
# it, so a bootstrap update does not remove it and this module does not claim a
# resource it did not create.
#
# Why these are not upstream: that template is instantiated for ANY receiving
# product, parameterised by repo owner and name. It grants what every receiving
# app needs. A work queue is not that — it exists because ffug, EMS's fixture,
# has asynchronous work. Adding SQS there would widen a shared artifact for one
# consumer, in the same way an empty-by-default `signing_keys` variable would
# have. Same ruling as the keys above.
#
# Each statement below is here because a deploy failed without it, EXCEPT where
# noted — and the noted one is the lesson: reasoning that a grant was "probably
# covered by the existing prefix" is what made this two deploys instead of one.
resource "aws_iam_role_policy" "deploy_role_async_work" {
  count = var.deploy_role_name == "" ? 0 : 1

  # ems-, not porth-: this policy is EMS's, on EMS's deploy role. The prefix is
  # the demarcation — porth- is what Porth deploys (PORTH-627).
  name = "ems-async-work"
  role = var.deploy_role_name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # CONFIRMED by run 32806570360: `sqs:createqueue` denied on
        # porth-ffug-work-dlq-dev. SQS was a resource type this stack had never
        # used, so nothing covered it even partially.
        #
        # Every action a lifecycle needs, not only Create. The redrive policy and
        # visibility timeout are applied AFTER creation, an update reads tags
        # back, and without DeleteQueue a rollback strands the stack in
        # DELETE_FAILED — a worse place than the failure being fixed.
        Sid    = "WorkQueuesForStack"
        Effect = "Allow"
        Action = [
          "sqs:CreateQueue",
          "sqs:DeleteQueue",
          "sqs:GetQueueUrl",
          "sqs:GetQueueAttributes",
          "sqs:SetQueueAttributes",
          "sqs:ListQueueTags",
          "sqs:TagQueue",
          "sqs:UntagQueue",
        ]
        # NOT the stack prefix. These queues follow the FUNCTION naming
        # convention in this stack — ems-ffug-work-{env} beside ems-ffug-{env} —
        # so enterprise-membership-sample-* would match nothing.
        #
        # BOTH prefixes, and the old one is not dead yet (PORTH-627). Renaming a
        # queue is a REPLACEMENT: CloudFormation creates ems-ffug-work-{env} and
        # then deletes porth-ffug-work-dev, so a grant covering only the new name
        # strands the stack in DELETE_FAILED on the way past — the same failure
        # mode the DeleteQueue action above was added for. Drop the porth-* entry
        # once no queue answers to it.
        Resource = [
          "arn:aws:sqs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:ems-*",
          "arn:aws:sqs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:porth-*",
        ]
      },
      {
        # A SAM `Type: SQS` event compiles to an AWS::Lambda::EventSourceMapping,
        # and those actions are a different family from the lambda:* a function
        # needs. Resource "*" because a mapping is identified by a UUID that
        # cannot be known when this policy is written; the reachable blast radius
        # is bounded by CreateEventSourceMapping additionally requiring
        # permission on the target function.
        #
        # CONFIRMED LOAD-BEARING by run 32810298045 attempt 2:
        # FfugWorkerFunctionWorkEventSourceMapping reached CREATE_COMPLETE, which
        # is this grant being exercised. Reasoned before it was observed; do not
        # read the reasoning as speculation and trim it.
        Sid    = "EventSourceMappings"
        Effect = "Allow"
        Action = [
          "lambda:CreateEventSourceMapping",
          "lambda:GetEventSourceMapping",
          "lambda:UpdateEventSourceMapping",
          "lambda:DeleteEventSourceMapping",
          "lambda:ListEventSourceMappings",
        ]
        Resource = "*"
      },
      {
        # CONFIRMED by run 32807678711: PutParameter denied on
        # SampleAppCallbackSessionPolicy.
        #
        # This is the one that was reasoned rather than observed, and the
        # reasoning was wrong. The stack already writes FfugSessionPolicy under
        # this same prefix, so "same prefix, therefore covered" looked safe — the
        # live grant is evidently scoped to the exact ffug-tenant-scoped NAME, so
        # a sibling document under the same prefix was a new resource entirely.
        #
        # A prefix here, deliberately: the next service that narrows on the
        # internal plane adds a third document, and rediscovering this one
        # AccessDenied at a time is the cost being removed.
        Sid    = "SessionPolicyDocuments"
        Effect = "Allow"
        Action = [
          "ssm:PutParameter",
          "ssm:DeleteParameter",
          "ssm:GetParameters",
          "ssm:AddTagsToResource",
          "ssm:RemoveTagsFromResource",
          "ssm:ListTagsForResource",
        ]
        Resource = "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter/porth/${var.porth_branch}/auth-session-policy/*"
      },
      {
        # PORTH-621 gives SampleAppTenantRole a second trust statement so the
        # internal plane can narrow the same data identity a person's request
        # narrows. iam:CreateRole covers writing a trust policy ONCE and never
        # covers amending one.
        #
        # CONFIRMED LOAD-BEARING by run 32810298045 attempt 2: SampleAppTenantRole
        # reached UPDATE_COMPLETE, which is exactly this action succeeding.
        #
        # It was added on reasoning alone — two rollbacks had cancelled the
        # resource before CloudFormation ever attempted it, so there was no
        # denial to point at. Recorded because a comment saying "never observed"
        # invites a reader to trim a grant that turns out to be required.
        Sid    = "AmendStackRoleTrust"
        Effect = "Allow"
        Action = "iam:UpdateAssumeRolePolicy"
        Resource = [
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/ems-sample-app-tenant-*",
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/enterprise-membership-sample-*",
        ]
      },
    ]
  })
}
