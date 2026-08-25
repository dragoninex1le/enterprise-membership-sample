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
# writer for these two to merge with.
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

# The app is not a service in the per-direction model — the install key IS its
# request key — so its ARN comes from Porth's module rather than from here.
data "aws_ssm_parameter" "install_signing_key_arn" {
  name = "/porth/${var.porth_branch}/infra/context-signing-key-arn"
}

# `public_key` is base64-encoded DER SubjectPublicKeyInfo, which is exactly what
# SigningKeyEntry.public_key wants — nothing re-encodes it in between. Called
# once here, at provisioning, which is the whole reason verification can be
# local and no kms:Verify grant exists anywhere.
data "aws_kms_public_key" "install_signing_key" {
  key_id = data.aws_ssm_parameter.install_signing_key_arn.value
}

data "aws_kms_public_key" "service_signing" {
  for_each = local.signing_keys

  key_id = aws_kms_key.service_signing[each.key].arn
}

locals {
  # service_id -> the whole of signing-keys/{service_id}.
  #
  # Built from the pairs rather than hardcoded, so adding a (service, direction)
  # to the variable produces its binding without editing this.
  trust_documents = merge(
    {
      for service in distinct([for k in var.signing_keys : k.service_id]) :
      service => {
        contract_version = 1
        service_id       = service
        keys = [
          for key, pair in local.signing_keys : {
            kid         = aws_kms_key.service_signing[key].arn
            direction   = pair.direction
            public_key  = data.aws_kms_public_key.service_signing[key].public_key
            description = "EMS ${pair.service_id} ${pair.direction}"
          } if pair.service_id == service
        ]
      }
    },
    {
      # The app's request key is the install key. Its binding still has to exist
      # under `sample-app`, because verification fetches the document of the
      # service the token CLAIMS to be from — without it every crossing fails
      # with UnknownSigningServiceError, which reads as a signing problem and is
      # a missing document.
      "sample-app" = {
        contract_version = 1
        service_id       = "sample-app"
        keys = [{
          kid         = data.aws_ssm_parameter.install_signing_key_arn.value
          direction   = "request"
          public_key  = data.aws_kms_public_key.install_signing_key.public_key
          description = "EMS sample-app request (the install key)"
        }]
      }
    },
  )
}

resource "aws_ssm_parameter" "signing_keys" {
  for_each = local.trust_documents

  name        = "/porth/${var.porth_branch}/signing-keys/${each.key}"
  description = "Signing keys ${each.key} may speak with, by direction (PORTH-623/625)."
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
