# Porth's install-once infrastructure, held in THIS state.
#
# Porth ships `infra/terraform/porth-install-once` (Components) as a root module,
# and EMS used to apply it on its own, from a Components checkout, with a
# gitignored ems.tfvars. That left the one value that decides who may mint a
# delegated session — `delegated_mint_caller_role_arns` — on a laptop: not
# reviewed, not reproducible, and empty, so Porth refused every supplier session
# (KMS AccessDenied on Sign for ems-supplier-portal-porth-dau, 2026-11-08).
#
# So it is called here instead, as a child module, and its inputs are committed.
# Referenced at a pinned Components commit rather than copied: this repository is
# public and Components is not. Terraform ignores the module's own `backend` block
# when it is a child. Moving to a newer Porth install-once is a change of `ref`,
# reviewed like any other, and the plan shows exactly what it changes.
#
# Adopting it (once): adopt-porth-install-once.sh moves Porth's resources out of
# their old state (porth-install-once/dev) into this one, under
# module.porth_install_once. README.md "Porth's install-once, in this state".
locals {
  delegated_mint_callers = [
    for slot in lookup(var.delegated_mint_caller_slots, var.porth_branch, []) :
    "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/ems-supplier-portal-${slot}"
  ]
}

# Porth's resources are Porth's, tagged by Porth's module (Project=Porth,
# Module=porth-install-once). Without its own provider the module would inherit
# this one's default_tags and every Porth table, key and certificate would be
# re-tagged as EMS's on the first apply.
provider "aws" {
  alias  = "porth_install_once"
  region = var.aws_region
}

module "porth_install_once" {
  providers = { aws = aws.porth_install_once }

  source = "git::https://github.com/dragoninex1le/Components.git//infra/terraform/porth-install-once?ref=7e1ec2ed57a659abfb6c46a6b00f5dc88d7d94f8"

  # Porth's DEPLOYMENT axis, `dev` on EMS — the stack's Environment parameter. A
  # mismatch deploys cleanly and then cannot find its tables.
  environment = var.porth_branch

  # What ems.tfvars held, now reviewed. A testbed: disposable keys and tables.
  enable_deletion_protection = false
  kms_deletion_window_days   = 7
  alert_email                = ""

  # PORTH-656: one tenant-host certificate per slot.
  tenant_host_zone  = var.porth_tenant_host_zone
  tenant_host_slots = var.porth_tenant_host_slots

  # Who may mint a delegated principal (ADR-Z12). THE CONTROL: Porth's key policy
  # grants kms:Sign to these roles by name and to nobody else, whatever the
  # caller's own IAM says (template.yml SignMintRequests is only the caller's
  # half). Named as SLOTS; the role name is template.yml's own convention
  # (SupplierPortalRole: ems-supplier-portal-{EnvironmentSlot}), so the two cannot
  # drift apart. An environment the map does not name gets an empty list —
  # minting off, which is how Porth ships an install.
  #
  # Each role must exist before an apply: a key policy refuses an unknown
  # principal. If a stack ever REPLACES the role, the key policy is left holding
  # its old unique id, signing fails the same way, and the fix is to apply this
  # again. deploy-sample-app.yml checks for exactly that after every deploy.
  delegated_mint_caller_role_arns = local.delegated_mint_callers
}

# The deploy reads the mint key's policy to check the slot's portal is a named
# caller (deploy-sample-app.yml, "Check the supplier portal may mint"). Read only:
# the key policy gives the account root kms:GetKeyPolicy, so IAM can pass it on.
resource "aws_iam_role_policy" "deploy_role_mint_caller_check" {
  count = var.deploy_role_name == "" ? 0 : 1

  name = "ems-mint-caller-check"
  role = var.deploy_role_name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ReadMintKeyPolicy"
        Effect   = "Allow"
        Action   = ["kms:GetKeyPolicy"]
        Resource = module.porth_install_once.delegated_mint_request_key_arn
      },
    ]
  })
}

output "porth_delegated_mint_callers" {
  description = "The roles Porth's key policy lets sign a delegated-mint request."
  value       = local.delegated_mint_callers
}
