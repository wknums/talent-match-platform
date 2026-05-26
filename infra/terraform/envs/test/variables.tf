# ── Variables for the test environment ────────────────────────────────────────

variable "project" {
  type    = string
  default = "awr"
}

variable "subscription_id" {
  type    = string
  default = ""
}

variable "environment" {
  type    = string
  default = "test"
}

variable "location" {
  type    = string
  default = "eastus2"
}

variable "host_choice" {
  type    = string
  default = "webapp_container"
}

variable "use_private_endpoints" {
  type    = bool
  default = false
}

variable "apim_sku" {
  type    = string
  default = "Developer_1"
}

variable "app_service_sku" {
  type    = string
  default = "B2"
}

variable "functions_sku" {
  type    = string
  default = "Y1"
}

variable "service_bus_sku" {
  type    = string
  default = "Standard"
}

variable "sb_queue_name" {
  type    = string
  default = "engine-runs"
}

variable "tenant_id" {
  type    = string
  default = ""
}

variable "publisher_email" {
  type    = string
  default = ""
}

variable "container_image" {
  type    = string
  default = "ghcr.io/placeholder/awr-platform-api:latest"
}

variable "enable_artifact_storage" {
  type    = bool
  default = true
}

variable "batch_results_retention_days" {
  type    = number
  default = 7
}

variable "enable_live_progress" {
  type    = bool
  default = false
}

variable "signalr_sku" {
  type    = string
  default = "Standard_S1"
}

variable "signalr_capacity" {
  type    = number
  default = 1
}

variable "signalr_hub_name" {
  type    = string
  default = "batch-progress"
}

variable "live_progress_target" {
  type    = string
  default = "batchProgress"
}

variable "live_progress_group_prefix" {
  type    = string
  default = "submission"
}

variable "tags" {
  type    = map(string)
  default = {}
}

# ── Resource Reuse Flags ──────────────────────────────────────────────────────
# Set to true to reference an existing resource instead of provisioning a new one.
# When true, the corresponding existing_* variables must also be set.

variable "reuse_storage" {
  type    = bool
  default = false
}

variable "reuse_appinsights" {
  type    = bool
  default = false
}

variable "reuse_service_bus" {
  type    = bool
  default = false
}

variable "reuse_key_vault" {
  type    = bool
  default = false
}

variable "reuse_apim" {
  type    = bool
  default = false
}

variable "reuse_loganalytics" {
  type    = bool
  default = false
}

variable "reuse_identities" {
  type    = bool
  default = false
}

variable "reuse_core_rg" {
  type    = bool
  default = false
}

variable "reuse_functions_storage" {
  type    = bool
  default = false
}

variable "reuse_signalr" {
  type    = bool
  default = false
}

variable "existing_core_rg_name" {
  type    = string
  default = ""
}

variable "existing_functions_storage_name" {
  type    = string
  default = ""
}

variable "existing_functions_storage_rg" {
  type    = string
  default = ""
}

variable "existing_signalr_name" {
  type    = string
  default = ""
}

variable "existing_signalr_rg" {
  type    = string
  default = ""
}

variable "functions_deployment_container_name" {
  type    = string
  default = "app-package"
}

variable "enable_apim" {
  type        = bool
  description = "Provision/reuse APIM. Set false to skip APIM entirely (QA/dev)."
  default     = false
}

variable "enable_acr_pull" {
  type        = bool
  description = "Grant AcrPull on an existing ACR to api+functions identities."
  default     = false
}

variable "existing_acr_name" {
  type    = string
  default = ""
}

variable "existing_acr_rg" {
  type    = string
  default = ""
}

# ── Existing Resource Details (used when reuse_* = true) ──────────────────────

variable "existing_storage_name" {
  type    = string
  default = ""
}
variable "existing_storage_rg" {
  type    = string
  default = ""
}

variable "existing_appinsights_name" {
  type    = string
  default = ""
}
variable "existing_appinsights_rg" {
  type    = string
  default = ""
}

variable "existing_service_bus_name" {
  type    = string
  default = ""
}
variable "existing_service_bus_rg" {
  type    = string
  default = ""
}

variable "existing_key_vault_name" {
  type    = string
  default = ""
}
variable "existing_key_vault_rg" {
  type    = string
  default = ""
}

variable "existing_apim_name" {
  type    = string
  default = ""
}
variable "existing_apim_rg" {
  type    = string
  default = ""
}

variable "existing_loganalytics_name" {
  type    = string
  default = ""
}
variable "existing_loganalytics_rg" {
  type    = string
  default = ""
}

variable "existing_identities_api_name" {
  type    = string
  default = ""
}
variable "existing_identities_func_name" {
  type    = string
  default = ""
}
variable "existing_identities_rg" {
  type    = string
  default = ""
}
