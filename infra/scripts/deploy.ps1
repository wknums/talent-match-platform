<#
.SYNOPSIS
    Reads an .env file and converts AZ_*_REUSE flags + existing resource details
    into Terraform variables, then runs terraform plan/apply.

.DESCRIPTION
    This script bridges the .env_local / .env_qa / .env_prod files to the
    Terraform reuse variables. It:
      1. Parses the specified .env file
      2. Exports TF_VAR_* environment variables for each reuse flag and resource detail
      3. Runs terraform init + plan (or apply) in the target env folder

.PARAMETER EnvFile
    Path to the .env file (e.g. .env_local, .env_qa, .env_prod).

.PARAMETER TfEnv
    Terraform environment folder name: dev, test, or prod.

.PARAMETER Action
    Terraform action: plan (default) or apply.

.PARAMETER AutoApprove
    If set, adds -auto-approve to terraform apply.

.EXAMPLE
    .\infra\scripts\deploy.ps1 -EnvFile .env_local -TfEnv dev
    .\infra\scripts\deploy.ps1 -EnvFile .env_qa   -TfEnv test -Action apply
    .\infra\scripts\deploy.ps1 -EnvFile .env_prod  -TfEnv prod -Action apply -AutoApprove
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$EnvFile,

    [Parameter(Mandatory)]
    [ValidateSet("dev", "test", "prod")]
    [string]$TfEnv,

    [ValidateSet("plan", "apply", "destroy")]
    [string]$Action = "plan",

    [switch]$AutoApprove
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ── Resolve paths ─────────────────────────────────────────────────────────────
$repoRoot = (Get-Item $PSScriptRoot).Parent.Parent.FullName
$envFilePath = Join-Path $repoRoot $EnvFile

if (-not (Test-Path $envFilePath)) {
    Write-Error "Env file not found: $envFilePath"
    exit 1
}

$tfDir = Join-Path $repoRoot "infra" "terraform" "envs" $TfEnv

if (-not (Test-Path $tfDir)) {
    Write-Error "Terraform env directory not found: $tfDir"
    exit 1
}

# ── Parse .env file ───────────────────────────────────────────────────────────
$envVars = @{}
Get-Content $envFilePath | ForEach-Object {
    $line = $_.Trim()
    if ($line -and -not $line.StartsWith("#")) {
        $parts = $line -split "=", 2
        if ($parts.Length -eq 2) {
            $envVars[$parts[0].Trim()] = $parts[1].Trim()
        }
    }
}

# ── Map .env variables to Terraform TF_VAR_* ─────────────────────────────────

function Get-BoolValue([string]$value) {
    return ($value -ieq "TRUE")
}

function Get-EnvOrDefault([hashtable]$vars, [string]$key, [string]$default = "") {
    if ($vars.ContainsKey($key)) { return $vars[$key] }
    return $default
}

# Reuse flags
$env:TF_VAR_reuse_storage      = (Get-BoolValue (Get-EnvOrDefault $envVars "AZ_STORAGE_REUSE")).ToString().ToLower()
$env:TF_VAR_reuse_appinsights  = (Get-BoolValue (Get-EnvOrDefault $envVars "AZ_APPINSIGHTS_REUSE")).ToString().ToLower()
$env:TF_VAR_reuse_service_bus  = (Get-BoolValue (Get-EnvOrDefault $envVars "AZ_SERVICE_BUS_REUSE")).ToString().ToLower()
$env:TF_VAR_reuse_sql          = (Get-BoolValue (Get-EnvOrDefault $envVars "AZ_SQL_REUSE")).ToString().ToLower()
$env:TF_VAR_reuse_key_vault    = (Get-BoolValue (Get-EnvOrDefault $envVars "AZ_KEY_VAULT_REUSE")).ToString().ToLower()
$env:TF_VAR_reuse_apim         = (Get-BoolValue (Get-EnvOrDefault $envVars "AZ_APIM_REUSE")).ToString().ToLower()
$env:TF_VAR_reuse_loganalytics = (Get-BoolValue (Get-EnvOrDefault $envVars "AZ_LOGANALYTICS_REUSE")).ToString().ToLower()
$env:TF_VAR_reuse_identities   = (Get-BoolValue (Get-EnvOrDefault $envVars "AZ_IDENTITIES_REUSE")).ToString().ToLower()

# Existing resource details
$env:TF_VAR_existing_storage_name      = Get-EnvOrDefault $envVars "AZ_STORAGE_NAME"
$env:TF_VAR_existing_storage_rg        = Get-EnvOrDefault $envVars "AZ_STORAGE_RG"

$env:TF_VAR_existing_appinsights_name  = Get-EnvOrDefault $envVars "AZ_APPINSIGHTS_NAME"
$env:TF_VAR_existing_appinsights_rg    = Get-EnvOrDefault $envVars "AZ_APPINSIGHTS_RG"

$env:TF_VAR_existing_service_bus_name  = Get-EnvOrDefault $envVars "AZ_SERVICE_BUS_NAME"
$env:TF_VAR_existing_service_bus_rg    = Get-EnvOrDefault $envVars "AZ_SERVICE_BUS_RG"

$env:TF_VAR_existing_sql_server_name   = Get-EnvOrDefault $envVars "AZ_SQL_SERVER_NAME"
$env:TF_VAR_existing_sql_db_name       = Get-EnvOrDefault $envVars "AZ_SQL_DB_NAME"
$env:TF_VAR_existing_sql_rg            = Get-EnvOrDefault $envVars "AZ_SQL_RG"

$env:TF_VAR_existing_key_vault_name    = Get-EnvOrDefault $envVars "AZ_KEY_VAULT_NAME"
$env:TF_VAR_existing_key_vault_rg      = Get-EnvOrDefault $envVars "AZ_KEY_VAULT_RG"

$env:TF_VAR_existing_apim_name         = Get-EnvOrDefault $envVars "AZ_APIM_NAME"
$env:TF_VAR_existing_apim_rg           = Get-EnvOrDefault $envVars "AZ_APIM_RG"

$env:TF_VAR_existing_loganalytics_name = Get-EnvOrDefault $envVars "AZ_LOGANALYTICS_NAME"
$env:TF_VAR_existing_loganalytics_rg   = Get-EnvOrDefault $envVars "AZ_LOGANALYTICS_RG"

$env:TF_VAR_existing_identities_api_name  = Get-EnvOrDefault $envVars "AZ_IDENTITIES_API_NAME"
$env:TF_VAR_existing_identities_func_name = Get-EnvOrDefault $envVars "AZ_IDENTITIES_FUNC_NAME"
$env:TF_VAR_existing_identities_rg        = Get-EnvOrDefault $envVars "AZ_IDENTITIES_RG"

# ── Print summary ─────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  AWR Platform - Terraform Deploy" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  Env File : $EnvFile"
Write-Host "  TF Env   : $TfEnv"
Write-Host "  Action   : $Action"
Write-Host ""

$reuseResources = @(
    @{ Name = "Storage";        Flag = $env:TF_VAR_reuse_storage },
    @{ Name = "App Insights";   Flag = $env:TF_VAR_reuse_appinsights },
    @{ Name = "Service Bus";    Flag = $env:TF_VAR_reuse_service_bus },
    @{ Name = "SQL";            Flag = $env:TF_VAR_reuse_sql },
    @{ Name = "Key Vault";      Flag = $env:TF_VAR_reuse_key_vault },
    @{ Name = "APIM";           Flag = $env:TF_VAR_reuse_apim },
    @{ Name = "Log Analytics";  Flag = $env:TF_VAR_reuse_loganalytics },
    @{ Name = "Identities";     Flag = $env:TF_VAR_reuse_identities }
)

Write-Host "  Resource Reuse:" -ForegroundColor Yellow
foreach ($r in $reuseResources) {
    $icon = if ($r.Flag -eq "true") { "[REUSE]" } else { "[NEW]  " }
    $color = if ($r.Flag -eq "true") { "Green" } else { "Gray" }
    Write-Host "    $icon $($r.Name)" -ForegroundColor $color
}
Write-Host ""

# ── Destroy safety redirect ───────────────────────────────────────────────────
if ($Action -eq "destroy") {
    Write-Host ""
    Write-Host "╔═══════════════════════════════════════════════════════════╗" -ForegroundColor Red
    Write-Host "║  DESTROY REQUESTED                                      ║" -ForegroundColor Red
    Write-Host "╠═══════════════════════════════════════════════════════════╣" -ForegroundColor Red
    Write-Host "║  For safety, use the dedicated deprovision script:       ║" -ForegroundColor Red
    Write-Host "║                                                         ║" -ForegroundColor Red
    Write-Host "║  .\infra\scripts\deprovision.ps1 \                      ║" -ForegroundColor Yellow
    Write-Host "║      -EnvFile $EnvFile -TfEnv $TfEnv                    ║" -ForegroundColor Yellow
    Write-Host "║                                                         ║" -ForegroundColor Red
    Write-Host "║  The deprovision script shows which resources will be    ║" -ForegroundColor Red
    Write-Host "║  destroyed vs. protected (reuse-flagged) and requires    ║" -ForegroundColor Red
    Write-Host "║  explicit confirmation.                                  ║" -ForegroundColor Red
    Write-Host "╚═══════════════════════════════════════════════════════════╝" -ForegroundColor Red
    Write-Host ""

    # Still proceed with destroy if user insists (all TF_VAR_reuse_* are set)
    Write-Host "Proceeding with destroy via deploy script..." -ForegroundColor Yellow
    Write-Host ""

    # Show abbreviated reuse protection status
    $destroyWarning = @()
    $protectedWarning = @()
    foreach ($r in $reuseResources) {
        if ($r.Flag -eq "true") {
            $protectedWarning += $r.Name
        } else {
            $destroyWarning += $r.Name
        }
    }

    if ($protectedWarning.Count -gt 0) {
        Write-Host "  PROTECTED (will NOT be destroyed):" -ForegroundColor Green
        foreach ($p in $protectedWarning) {
            Write-Host "    [PROTECTED] $p" -ForegroundColor Green
        }
    }
    Write-Host "  WILL DESTROY:" -ForegroundColor Red
    foreach ($d in $destroyWarning) {
        Write-Host "    [DESTROY]   $d" -ForegroundColor Red
    }
    Write-Host "    [DESTROY]   Resource Group (always managed)" -ForegroundColor Red
    Write-Host "    [DESTROY]   Networking (always managed)" -ForegroundColor Red
    Write-Host "    [DESTROY]   App Service (always managed)" -ForegroundColor Red
    Write-Host "    [DESTROY]   Functions Host (always managed)" -ForegroundColor Red
    Write-Host ""

    if (-not $AutoApprove) {
        $confirm = Read-Host "Type '$TfEnv' to confirm destruction"
        if ($confirm -ne $TfEnv) {
            Write-Host "Aborted." -ForegroundColor Yellow
            exit 0
        }
    }
}

# ── Run Terraform ─────────────────────────────────────────────────────────────
Push-Location $tfDir
try {
    Write-Host "Running terraform init..." -ForegroundColor Cyan
    terraform init -input=false
    if ($LASTEXITCODE -ne 0) { throw "terraform init failed" }

    $tfArgs = @($Action)

    if (Test-Path (Join-Path $tfDir "terraform.tfvars")) {
        $tfArgs += "-var-file=terraform.tfvars"
    }

    if ($Action -eq "apply" -and $AutoApprove) {
        $tfArgs += "-auto-approve"
    }

    if ($Action -eq "destroy" -and $AutoApprove) {
        $tfArgs += "-auto-approve"
    }

    Write-Host "Running terraform $($tfArgs -join ' ')..." -ForegroundColor Cyan
    & terraform @tfArgs
    if ($LASTEXITCODE -ne 0) { throw "terraform $Action failed" }
}
finally {
    Pop-Location
}

Write-Host ""
Write-Host "Done." -ForegroundColor Green
