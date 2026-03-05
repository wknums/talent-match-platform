# PRD: Azure Resource Reuse for AWR Platform Infrastructure

> **Status**: Implemented  
> **Last updated**: 2026-02-13  
> **Owner**: Platform Team

---

## 1. Problem Statement

The AWR Platform Terraform infrastructure deploys all Azure resources fresh in every environment. In many enterprise scenarios, shared resources (e.g., a central Log Analytics workspace, a shared APIM gateway, or a pre-existing Azure SQL Server) already exist in other resource groups or subscriptions. Re-provisioning duplicates wastes cost, creates governance friction, and blocks teams that must use centrally managed infrastructure.

## 2. Goal

Allow each environment (local dev, QA/staging, production) to **selectively reuse existing Azure resources** instead of creating new ones, controlled via simple `.env` files and without changing the Terraform module interface.

## 3. Requirements

### 3.1 Functional Requirements

| ID | Requirement |
|----|-------------|
| FR-1 | Each reusable resource type has a boolean `*_REUSE` flag in the `.env` file. |
| FR-2 | When `*_REUSE=TRUE`, Terraform must **not** provision that resource; it must look up the existing resource by name and resource group using a `data` source. |
| FR-3 | When `*_REUSE=FALSE` (or not set), Terraform must provision the resource as before. |
| FR-4 | Module outputs remain identical regardless of whether the resource was created or reused, ensuring downstream modules (e.g., `app_host`, `functions_host`) work without modification. |
| FR-5 | Role assignments on shared resources are **skipped** when reusing (the shared-resource owner manages access). |
| FR-6 | Three environment-specific `.env` files control reuse: `.env_local` (local/dev), `.env_qa` (staging), `.env_prod` (production). |

### 3.2 Supported Reusable Resources

| .env Flag | Terraform Variable | Module | Data Source |
|-----------|-------------------|--------|-------------|
| `AZ_STORAGE_REUSE` | `reuse_storage` | `modules/storage` | `azurerm_storage_account` |
| `AZ_APPINSIGHTS_REUSE` | `reuse_appinsights` | `modules/application_insights` | `azurerm_application_insights` |
| `AZ_SERVICE_BUS_REUSE` | `reuse_service_bus` | `modules/service_bus` | `azurerm_servicebus_namespace` |
| `AZ_SQL_REUSE` | `reuse_sql` | `modules/sql` | `azurerm_mssql_server` + `azurerm_mssql_database` |
| `AZ_KEY_VAULT_REUSE` | `reuse_key_vault` | `modules/key_vault` | `azurerm_key_vault` |
| `AZ_APIM_REUSE` | `reuse_apim` | `modules/apim` | `azurerm_api_management` |
| `AZ_LOGANALYTICS_REUSE` | `reuse_loganalytics` | `modules/log_analytics` | `azurerm_log_analytics_workspace` |
| `AZ_IDENTITIES_REUSE` | `reuse_identities` | `modules/identities` | `azurerm_user_assigned_identity` (×2) |

### 3.3 Existing Resource Details

When a `*_REUSE` flag is `TRUE`, the corresponding resource details must be provided:

| Resource | Required .env Variables |
|----------|------------------------|
| Storage | `AZ_STORAGE_NAME`, `AZ_STORAGE_RG` |
| App Insights | `AZ_APPINSIGHTS_NAME`, `AZ_APPINSIGHTS_RG` |
| Service Bus | `AZ_SERVICE_BUS_NAME`, `AZ_SERVICE_BUS_RG` |
| SQL | `AZ_SQL_SERVER_NAME`, `AZ_SQL_DB_NAME`, `AZ_SQL_RG` |
| Key Vault | `AZ_KEY_VAULT_NAME`, `AZ_KEY_VAULT_RG` |
| APIM | `AZ_APIM_NAME`, `AZ_APIM_RG` |
| Log Analytics | `AZ_LOGANALYTICS_NAME`, `AZ_LOGANALYTICS_RG` |
| Identities | `AZ_IDENTITIES_API_NAME`, `AZ_IDENTITIES_FUNC_NAME`, `AZ_IDENTITIES_RG` |

### 3.4 Non-Functional Requirements

| ID | Requirement |
|----|-------------|
| NFR-1 | Backward compatible — all `*_REUSE` flags default to `false`; existing deployments are unaffected. |
| NFR-2 | Existing resources may live in **any resource group** (not restricted to the deployment RG). |
| NFR-3 | The Terraform service principal must have **Reader** access to the resource groups containing reused resources. |

## 4. Architecture

### 4.1 Data Flow

```
.env_local / .env_qa / .env_prod
        │
        ▼
 deploy.ps1 / deploy.sh          (wrapper script)
        │
        │  Reads AZ_*_REUSE and AZ_*_NAME/RG vars
        │  Exports TF_VAR_reuse_*, TF_VAR_existing_*
        │
        ▼
 terraform plan / apply
        │
        ├── module (reuse=false) ──▶ resource block (count=1) ──▶ creates resource
        │
        └── module (reuse=true)  ──▶ data source  (count=1)  ──▶ reads existing resource
                                     resource block (count=0) ──▶ skipped
```

### 4.2 Module Pattern

Every reusable module follows this pattern:

```hcl
# Input variables
variable "reuse"                   { type = bool, default = false }
variable "existing_name"           { type = string, default = "" }
variable "existing_resource_group" { type = string, default = "" }

# Conditional data source
data "azurerm_<resource>" "existing" {
  count               = var.reuse ? 1 : 0
  name                = var.existing_name
  resource_group_name = var.existing_resource_group
}

# Conditional resource creation
resource "azurerm_<resource>" "main" {
  count = var.reuse ? 0 : 1
  ...
}

# Unified output
output "id" {
  value = var.reuse ? data.azurerm_<resource>.existing[0].id
                     : azurerm_<resource>.main[0].id
}
```

### 4.3 Environment Mapping

| .env File | Terraform Env | Purpose |
|-----------|---------------|---------|
| `.env_local` | `envs/dev` | Local development and testing |
| `.env_qa` | `envs/test` | QA / staging on Azure |
| `.env_prod` | `envs/prod` | Production on Azure |

## 5. Usage

### 5.1 Quick Start — Reuse SQL and Log Analytics in QA

Edit `.env_qa`:
```ini
AZ_SQL_REUSE=TRUE
AZ_SQL_SERVER_NAME=sql-shared-qa
AZ_SQL_DB_NAME=awrdb
AZ_SQL_RG=rg-shared-platform

AZ_LOGANALYTICS_REUSE=TRUE
AZ_LOGANALYTICS_NAME=law-central-qa
AZ_LOGANALYTICS_RG=rg-observability
```

Deploy:
```powershell
# PowerShell (Windows)
.\infra\scripts\deploy.ps1 -EnvFile .env_qa -TfEnv test -Action plan

# Bash (Linux / CI)
./infra/scripts/deploy.sh .env_qa test plan
```

### 5.2 Deploy All Fresh (default)

Leave all `*_REUSE=FALSE` (or omit them) — identical to the original behavior.

### 5.3 Direct Terraform (without wrapper)

You can also set the variables directly in `terraform.tfvars`:
```hcl
reuse_sql                = true
existing_sql_server_name = "sql-shared"
existing_sql_db_name     = "awrdb"
existing_sql_rg          = "rg-shared"
```

## 6. Deprovisioning (Safe Destroy)

### 6.1 Overview

Deprovisioning tears down Terraform-managed infrastructure while **guaranteeing that reuse-flagged resources are never destroyed**. This is enforced at two levels:

1. **Terraform structural guarantee**: Reuse-flagged modules have `count = 0` on all managed resources, so nothing exists in Terraform state to destroy. Data sources referencing existing resources are read-only and are never deleted by `terraform destroy`.

2. **Script-level safeguards**: The dedicated deprovision scripts require an `.env` file (preventing accidental full destruction with default `reuse=false`), display a colour-coded table of `[DESTROY]` vs `[PROTECTED]` resources, and require explicit confirmation.

### 6.2 Dedicated Deprovision Scripts

| Script | Platform | Usage |
|--------|----------|-------|
| `infra/scripts/deprovision.ps1` | Windows / PowerShell | `.\infra\scripts\deprovision.ps1 -EnvFile .env_qa -TfEnv test` |
| `infra/scripts/deprovision.sh` | Linux / macOS / CI | `./infra/scripts/deprovision.sh .env_qa test` |

#### Parameters

| Parameter | PS1 Name | Bash Arg | Description |
|-----------|----------|----------|-------------|
| Env file | `-EnvFile` | `$1` | Path to `.env_local`, `.env_qa`, or `.env_prod`. **Required.** |
| TF env | `-TfEnv` | `$2` | Terraform environment: `dev`, `test`, or `prod`. **Required.** |
| Dry run | `-DryRun` | `--dry-run` | Run `terraform plan -destroy` without destroying anything. |
| Force | `-Force` | `--force` | Skip interactive confirmation (CI/CD pipelines only). |

#### Example: Dry run to see what would be destroyed

```powershell
.\infra\scripts\deprovision.ps1 -EnvFile .env_qa -TfEnv test -DryRun
```

#### Example: Destroy with confirmation prompt

```bash
./infra/scripts/deprovision.sh .env_prod prod
# Shows table, requires typing "prod" to confirm
```

#### Example: CI/CD force destroy

```bash
./infra/scripts/deprovision.sh .env_qa test --force
```

### 6.3 Safety Guarantees

| Risk | Mitigation |
|------|------------|
| Running `terraform destroy` directly (bypassing wrapper, all reuse defaults to `false`) | Deprovision scripts **require** an `.env` file; the script refuses to run without one |
| Accidentally destroying a reuse-flagged resource | Resources with `reuse=true` have `count=0`, so nothing is in Terraform state to destroy |
| No visibility into what will be destroyed | Scripts display colour-coded `[DESTROY]` / `[PROTECTED]` summary before any action |
| Fat-finger confirmation | Interactive mode requires typing the exact environment name (e.g., `prod`) to proceed |
| CI/CD pipeline accidentally destroys protected resources | Even with `--force`, TF_VAR_reuse_* flags are always set from the `.env` file |

### 6.4 Deploy Script Destroy Fallback

The `deploy.ps1` / `deploy.sh` scripts also support `Action = destroy`, but when invoked:
1. A warning banner recommends using the dedicated deprovision script instead.
2. A `[DESTROY]` / `[PROTECTED]` summary is shown inline.
3. Interactive confirmation (type the env name) is required unless `-AutoApprove` / `--auto-approve` is set.
4. All `TF_VAR_reuse_*` flags are set from the `.env` file, ensuring reused resources remain safe.

## 7. Security Considerations

| Concern | Mitigation |
|---------|------------|
| Cross-RG access | The deploying service principal needs **Reader** on the external RG to use `data` sources |
| Role assignments | Skipped for reused resources — the shared-resource owner manages RBAC |
| Secrets in .env files | `.env_*` files are git-ignored; secrets should be in Key Vault, not .env files |
| Drift detection | Terraform only reads (not manages) reused resources; drift is the external team's responsibility |

## 8. Files Changed

### New Files
| File | Purpose |
|------|---------|
| `.env_local` | Reuse config + runtime config for local dev |
| `.env_qa` | Reuse config + runtime config for QA/staging |
| `.env_prod` | Reuse config + runtime config for production |
| `infra/scripts/deploy.ps1` | PowerShell wrapper: .env → TF_VAR → terraform |
| `infra/scripts/deploy.sh` | Bash wrapper: .env → TF_VAR → terraform |
| `infra/scripts/deprovision.ps1` | PowerShell: safe destroy with reuse protection |
| `infra/scripts/deprovision.sh` | Bash: safe destroy with reuse protection |
| `PRD.md` | This document |

### Modified Terraform Modules (8)
Each module gained `reuse`, `existing_name`, `existing_resource_group` variables, a conditional `data` source, `count` guards on resources, and unified outputs:

- `modules/storage/main.tf`
- `modules/application_insights/main.tf`
- `modules/service_bus/main.tf`
- `modules/sql/main.tf`
- `modules/key_vault/main.tf`
- `modules/apim/main.tf`
- `modules/log_analytics/main.tf`
- `modules/identities/main.tf`

### Modified Environment Compositions (3 × 3 files)
- `envs/{dev,test,prod}/variables.tf` — added 8 reuse booleans + existing resource detail variables
- `envs/{dev,test,prod}/main.tf` — pass reuse flags to each module
- `envs/{dev,test,prod}/terraform.tfvars.example` — added example reuse configuration

## 9. Testing Plan

| Scenario | Expected Result |
|----------|-----------------|
| All `*_REUSE=FALSE` | All resources created fresh (no behavioral change from before) |
| Single resource reused (e.g., SQL) | SQL module uses data source; all other modules create fresh |
| Multiple resources reused | Each flagged module uses data source; others create fresh |
| `*_REUSE=TRUE` without name/RG | Terraform plan fails with clear error (data source requires name) |
| Wrapper script with invalid env file | Script exits with descriptive error |
| Deprovision with all `*_REUSE=FALSE` | All reusable resources + always-managed resources are destroyed |
| Deprovision with some `*_REUSE=TRUE` | Only non-reused resources destroyed; reused resources untouched |
| Deprovision without .env file | Script refuses to run with clear error message |
| Deprovision dry run (`-DryRun`) | Shows `terraform plan -destroy` output but destroys nothing |
| Deprovision confirmation mismatch | User types wrong env name → script aborts |
| Raw `terraform destroy` (no wrapper) | All resources destroyed (expected — no reuse flags set); documented as unsupported |

## 10. Future Enhancements

- **Validation blocks**: Add Terraform `validation` on `existing_name` to require non-empty when `reuse=true`.
- **Cross-subscription support**: Add optional `existing_subscription_id` for `provider` aliasing.
- **Import support**: `terraform import` helper script for migrating from newly-created to reused resources.
- **GitHub Actions integration**: Wire `deploy.sh` into CI workflows with environment-specific `.env` file selection.
