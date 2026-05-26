<#
.SYNOPSIS
    Safely deprovisions AWR Platform infrastructure, protecting reuse-flagged resources.

.DESCRIPTION
    This script reads the specified .env file, identifies which Azure resources are
    managed (will be destroyed) vs. reused (will be protected), displays a clear
    summary, and requires explicit confirmation before running terraform destroy.

    Safety guarantees:
      - Reuse-flagged resources (AZ_*_REUSE=TRUE) are NEVER destroyed.
        They have count=0 in Terraform state and are referenced via read-only data sources.
      - A colour-coded summary table shows [DESTROY] vs [PROTECTED] for every resource.
      - Interactive confirmation is required unless -Force is specified.
      - The script refuses to run if the .env file is missing (prevents accidentally
        destroying everything with default reuse=false).

.PARAMETER EnvFile
    Path to the .env file (e.g. .env_local, .env_qa, .env_prod). REQUIRED.

.PARAMETER TfEnv
    Terraform environment folder name: dev, test, or prod. REQUIRED.

.PARAMETER Force
    Skip interactive confirmation. Use in CI/CD pipelines only.

.PARAMETER DryRun
    Show the destroy plan without actually destroying anything.

.EXAMPLE
    # Preview what would be destroyed in dev
    .\infra\scripts\deprovision.ps1 -EnvFile .env_local -TfEnv dev -DryRun

    # Destroy non-reused resources in QA (interactive confirmation)
    .\infra\scripts\deprovision.ps1 -EnvFile .env_qa -TfEnv test

    # Force destroy in CI (no prompt)
    .\infra\scripts\deprovision.ps1 -EnvFile .env_prod -TfEnv prod -Force
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$EnvFile,

    [Parameter(Mandatory)]
    [ValidateSet("dev", "test", "prod")]
    [string]$TfEnv,

    [switch]$Force,

    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ── Resolve paths ─────────────────────────────────────────────────────────────
$repoRoot = (Get-Item $PSScriptRoot).Parent.Parent.FullName
$envFilePath = Join-Path $repoRoot $EnvFile

if (-not (Test-Path $envFilePath)) {
    Write-Host ""
    Write-Host "ERROR: Env file not found: $envFilePath" -ForegroundColor Red
    Write-Host ""
    Write-Host "A .env file is REQUIRED for deprovisioning to ensure reuse-flagged" -ForegroundColor Red
    Write-Host "resources are protected. Running terraform destroy without reuse" -ForegroundColor Red
    Write-Host "flags would destroy ALL resources, including shared ones." -ForegroundColor Red
    Write-Host ""
    Write-Host "Available env files:" -ForegroundColor Yellow
    Write-Host "  .env_local  ->  dev  (local development)" -ForegroundColor Gray
    Write-Host "  .env_qa     ->  test (QA / staging)" -ForegroundColor Gray
    Write-Host "  .env_prod   ->  prod (production)" -ForegroundColor Gray
    Write-Host ""
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

function Get-BoolValue([string]$value) {
    return ($value -ieq "TRUE")
}

function Get-EnvOrDefault([hashtable]$vars, [string]$key, [string]$default = "") {
    if ($vars.ContainsKey($key)) { return $vars[$key] }
    return $default
}

# ── Map .env variables to Terraform TF_VAR_* ─────────────────────────────────

# Reuse flags
$env:TF_VAR_reuse_storage      = (Get-BoolValue (Get-EnvOrDefault $envVars "AZ_STORAGE_REUSE")).ToString().ToLower()
$env:TF_VAR_reuse_appinsights  = (Get-BoolValue (Get-EnvOrDefault $envVars "AZ_APPINSIGHTS_REUSE")).ToString().ToLower()
$env:TF_VAR_reuse_service_bus  = (Get-BoolValue (Get-EnvOrDefault $envVars "AZ_SERVICE_BUS_REUSE")).ToString().ToLower()
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

$env:TF_VAR_existing_key_vault_name    = Get-EnvOrDefault $envVars "AZ_KEY_VAULT_NAME"
$env:TF_VAR_existing_key_vault_rg      = Get-EnvOrDefault $envVars "AZ_KEY_VAULT_RG"

$env:TF_VAR_existing_apim_name         = Get-EnvOrDefault $envVars "AZ_APIM_NAME"
$env:TF_VAR_existing_apim_rg           = Get-EnvOrDefault $envVars "AZ_APIM_RG"

$env:TF_VAR_existing_loganalytics_name = Get-EnvOrDefault $envVars "AZ_LOGANALYTICS_NAME"
$env:TF_VAR_existing_loganalytics_rg   = Get-EnvOrDefault $envVars "AZ_LOGANALYTICS_RG"

$env:TF_VAR_existing_identities_api_name  = Get-EnvOrDefault $envVars "AZ_IDENTITIES_API_NAME"
$env:TF_VAR_existing_identities_func_name = Get-EnvOrDefault $envVars "AZ_IDENTITIES_FUNC_NAME"
$env:TF_VAR_existing_identities_rg        = Get-EnvOrDefault $envVars "AZ_IDENTITIES_RG"

# ── Build resource disposition table ──────────────────────────────────────────
$resources = @(
    @{ Name = "Storage Account";      EnvFlag = "AZ_STORAGE_REUSE";      TfVar = $env:TF_VAR_reuse_storage;      Module = "storage" },
    @{ Name = "Application Insights"; EnvFlag = "AZ_APPINSIGHTS_REUSE";  TfVar = $env:TF_VAR_reuse_appinsights;  Module = "application_insights" },
    @{ Name = "Service Bus";          EnvFlag = "AZ_SERVICE_BUS_REUSE";  TfVar = $env:TF_VAR_reuse_service_bus;  Module = "service_bus" },
    @{ Name = "Key Vault";            EnvFlag = "AZ_KEY_VAULT_REUSE";    TfVar = $env:TF_VAR_reuse_key_vault;    Module = "key_vault" },
    @{ Name = "API Management";       EnvFlag = "AZ_APIM_REUSE";        TfVar = $env:TF_VAR_reuse_apim;         Module = "apim" },
    @{ Name = "Log Analytics";        EnvFlag = "AZ_LOGANALYTICS_REUSE"; TfVar = $env:TF_VAR_reuse_loganalytics; Module = "log_analytics" },
    @{ Name = "Managed Identities";   EnvFlag = "AZ_IDENTITIES_REUSE";  TfVar = $env:TF_VAR_reuse_identities;   Module = "identities" }
)

# Always-managed modules (no reuse flag — always provisioned, always destroyed)
$alwaysManaged = @(
    @{ Name = "Resource Group";   Module = "core_rg" },
    @{ Name = "Networking (VNet)"; Module = "networking" },
    @{ Name = "App Service (API)"; Module = "app_host" },
    @{ Name = "Functions Host";    Module = "functions_host" }
)

$destroyList  = @()
$protectList  = @()

foreach ($r in $resources) {
    if ($r.TfVar -eq "true") {
        $protectList += $r
    } else {
        $destroyList += $r
    }
}

# ── Display summary ──────────────────────────────────────────────────────────
Write-Host ""
Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Red
Write-Host "  AWR Platform - DEPROVISION" -ForegroundColor Red
Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Red
Write-Host ""
Write-Host "  Env File : $EnvFile" -ForegroundColor White
Write-Host "  TF Env   : $TfEnv" -ForegroundColor White
if ($DryRun) {
    Write-Host "  Mode     : DRY RUN (plan only, no resources will be destroyed)" -ForegroundColor Yellow
} else {
    Write-Host "  Mode     : LIVE DESTROY" -ForegroundColor Red
}
Write-Host ""

# Destruction section
Write-Host "  ┌─────────────────────────────────────────────────────────┐" -ForegroundColor Red
Write-Host "  │  RESOURCES TO BE DESTROYED                             │" -ForegroundColor Red
Write-Host "  └─────────────────────────────────────────────────────────┘" -ForegroundColor Red

foreach ($r in $destroyList) {
    Write-Host "    [DESTROY]   $($r.Name)" -ForegroundColor Red
}
foreach ($r in $alwaysManaged) {
    Write-Host "    [DESTROY]   $($r.Name)  (always managed)" -ForegroundColor Red
}

$totalDestroy = $destroyList.Count + $alwaysManaged.Count

Write-Host ""

# Protection section
Write-Host "  ┌─────────────────────────────────────────────────────────┐" -ForegroundColor Green
Write-Host "  │  PROTECTED RESOURCES (reuse-flagged, will NOT be       │" -ForegroundColor Green
Write-Host "  │  touched by destroy)                                   │" -ForegroundColor Green
Write-Host "  └─────────────────────────────────────────────────────────┘" -ForegroundColor Green

if ($protectList.Count -eq 0) {
    Write-Host "    (none — all optionally-reusable resources are managed)" -ForegroundColor Gray
} else {
    foreach ($r in $protectList) {
        $extName = Get-EnvOrDefault $envVars $r.EnvFlag.Replace("_REUSE", "_NAME") ""
        $extRg   = Get-EnvOrDefault $envVars $r.EnvFlag.Replace("_REUSE", "_RG") ""
        $detail  = if ($extName) { " -> $extName in $extRg" } else { "" }
        Write-Host "    [PROTECTED] $($r.Name)$detail" -ForegroundColor Green
    }
}

Write-Host ""
Write-Host "  Summary: $totalDestroy resource(s) to DESTROY, $($protectList.Count) resource(s) PROTECTED" -ForegroundColor Yellow
Write-Host ""

# ── Safety: why reused resources are safe ─────────────────────────────────────
if ($protectList.Count -gt 0) {
    Write-Host "  How protection works:" -ForegroundColor DarkGray
    Write-Host "    Reuse-flagged modules have count=0 on all managed resources," -ForegroundColor DarkGray
    Write-Host "    so nothing exists in Terraform state to destroy. The data" -ForegroundColor DarkGray
    Write-Host "    sources that reference the existing resources are read-only" -ForegroundColor DarkGray
    Write-Host "    and are never deleted by terraform destroy." -ForegroundColor DarkGray
    Write-Host ""
}

# ── Confirmation gate ─────────────────────────────────────────────────────────
if (-not $DryRun -and -not $Force) {
    Write-Host "  WARNING: This action is IRREVERSIBLE for the resources listed above." -ForegroundColor Red
    Write-Host ""
    $confirmation = Read-Host "  Type the environment name '$TfEnv' to confirm destruction"
    if ($confirmation -ne $TfEnv) {
        Write-Host ""
        Write-Host "  Confirmation failed. Aborting." -ForegroundColor Yellow
        exit 0
    }
    Write-Host ""
}

# ── Run Terraform ─────────────────────────────────────────────────────────────
Push-Location $tfDir
try {
    Write-Host "Running terraform init..." -ForegroundColor Cyan
    terraform init -input=false
    if ($LASTEXITCODE -ne 0) { throw "terraform init failed" }

    if ($DryRun) {
        # Plan a destroy without executing
        $tfArgs = @("plan", "-destroy")
    } else {
        $tfArgs = @("destroy")
    }

    if (Test-Path (Join-Path $tfDir "terraform.tfvars")) {
        $tfArgs += "-var-file=terraform.tfvars"
    }

    if (-not $DryRun -and $Force) {
        $tfArgs += "-auto-approve"
    }

    Write-Host "Running terraform $($tfArgs -join ' ')..." -ForegroundColor Cyan
    & terraform @tfArgs
    if ($LASTEXITCODE -ne 0) { throw "terraform $($tfArgs[0]) failed" }
}
finally {
    Pop-Location
}

Write-Host ""
if ($DryRun) {
    Write-Host "Dry run complete. No resources were destroyed." -ForegroundColor Yellow
} else {
    Write-Host "Deprovisioning complete." -ForegroundColor Green
    if ($protectList.Count -gt 0) {
        Write-Host "$($protectList.Count) reuse-flagged resource(s) were protected and remain intact." -ForegroundColor Green
    }
}
