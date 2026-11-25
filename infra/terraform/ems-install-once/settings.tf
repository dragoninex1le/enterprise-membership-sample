# ── The application's settings table (PORTH-669 ruling 3) ────────────────────
#
# Richard, 2026-11-24: "The application deploys the settings table, and the
# Porth install writes Porth's values into it." EMS is the application, so the
# table and its key secret are EMS's, and they live here: created once, updated
# rarely, destroyed never — the same reason the signing keys are not in
# template.yml.
#
# Porth 0.4.30 reads every setting it used to hard-code (and the /porth/auth
# blob's keys) from this table. Its stack takes the name as the
# SettingsTableName parameter, which porth-install.yml passes; `porth-install
# settings apply` writes component `porth` into it.
#
# Shape: estyn-settings spec/REQUIREMENTS.md (Components,
# packages/estyn-settings). PK/SK plus three sparse indexes keyed on PK,
# projection ALL; one empty secret, which ensure_table fills with the private
# key on the first install.

resource "aws_dynamodb_table" "settings" {
  name         = var.settings_table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "PK"
  range_key    = "SK"

  # Settings outlive every deploy. A table dropped by mistake takes the install's
  # whole configuration with it.
  deletion_protection_enabled = true

  point_in_time_recovery {
    enabled = true
  }

  attribute {
    name = "PK"
    type = "S"
  }
  attribute {
    name = "SK"
    type = "S"
  }
  attribute {
    name = "container_pk"
    type = "S"
  }
  attribute {
    name = "component"
    type = "S"
  }
  attribute {
    name = "environment"
    type = "S"
  }

  global_secondary_index {
    name            = "by-container"
    hash_key        = "container_pk"
    range_key       = "PK"
    projection_type = "ALL"
  }
  global_secondary_index {
    name            = "by-component"
    hash_key        = "component"
    range_key       = "PK"
    projection_type = "ALL"
  }
  global_secondary_index {
    name            = "by-environment"
    hash_key        = "environment"
    range_key       = "PK"
    projection_type = "ALL"
  }

  tags = local.common_tags
}

# Created EMPTY. `ensure_table` (run by `porth-install settings apply --apply`)
# puts the private key with PutSecretValue; the installer can never read it
# back. Porth's runtime does not read it either: it declares no encrypted items.
resource "aws_secretsmanager_secret" "settings_key" {
  name        = var.settings_secret_name
  description = "Private key of ${var.settings_table_name} (PKCS#8 PEM), put by estyn-settings ensure_table."
  tags        = local.common_tags
}

# ── porth-install-role's settings grants ─────────────────────────────────────
#
# Attached rather than owned, like deploy_role_async_work: the role is Porth's
# receiving-account bootstrap's, and the table is EMS's, so the grant is too.
#
# The installer set from REQUIREMENTS.md, and never secretsmanager:GetSecretValue.
# Plus read access to estyn-platform-py, where estyn-settings is published: the
# publisher side already admits any principal in the Estyn Organization, so
# only the identity half is needed (as with porth-py, PORTH-590).
resource "aws_iam_role_policy" "porth_install_settings" {
  count = var.porth_install_role_name == "" ? 0 : 1

  name = "ems-settings-install"
  role = var.porth_install_role_name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "SettingsTableInstall"
        Effect = "Allow"
        Action = [
          "dynamodb:Query",
          "dynamodb:BatchGetItem",
          "dynamodb:GetItem",
          "dynamodb:TransactWriteItems",
          "dynamodb:PutItem",
          "dynamodb:DeleteItem",
          "dynamodb:ConditionCheckItem",
          "dynamodb:DescribeTable",
        ]
        Resource = [
          aws_dynamodb_table.settings.arn,
          "${aws_dynamodb_table.settings.arn}/index/*",
        ]
      },
      {
        Sid      = "SettingsKeyPut"
        Effect   = "Allow"
        Action   = ["secretsmanager:PutSecretValue", "secretsmanager:DescribeSecret"]
        Resource = aws_secretsmanager_secret.settings_key.arn
      },
      {
        Sid      = "CodeArtifactAuthEstynPlatformPy"
        Effect   = "Allow"
        Action   = "codeartifact:GetAuthorizationToken"
        Resource = "arn:aws:codeartifact:us-east-1:${var.codeartifact_owner}:domain/estyn-platform"
      },
      {
        Sid    = "CodeArtifactReadEstynPlatformPy"
        Effect = "Allow"
        Action = [
          "codeartifact:ReadFromRepository",
          "codeartifact:GetRepositoryEndpoint",
          "codeartifact:DescribePackageVersion",
          "codeartifact:ListPackages",
          "codeartifact:ListPackageVersions",
        ]
        Resource = "arn:aws:codeartifact:us-east-1:${var.codeartifact_owner}:repository/estyn-platform/estyn-platform-py"
      },
    ]
  })
}
