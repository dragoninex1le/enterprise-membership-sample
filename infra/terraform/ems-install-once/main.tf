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
