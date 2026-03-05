# ── Variables for the prod environment ────────────────────────────────────────

variable "project" {
  type    = string
  default = "awr"
}

variable "environment" {
  type    = string
  default = "prod"
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
  default = true
}

variable "sql_sku" {
  type    = string
  default = "GP_S_Gen5_2"
}

variable "sql_max_size_gb" {
  type    = number
  default = 32
}

variable "apim_sku" {
  type    = string
  default = "Standard_1"
}

variable "app_service_sku" {
  type    = string
  default = "P1v3"
}

variable "functions_sku" {
  type    = string
  default = "EP1"
}

variable "service_bus_sku" {
  type    = string
  default = "Premium"
}

variable "sb_queue_name" {
  type    = string
  default = "engine-runs"
}

variable "tenant_id" {
  type = string
}

variable "aad_admin_object_id" {
  type = string
}

variable "publisher_email" {
  type = string
}

variable "container_image" {
  type    = string
  default = "ghcr.io/placeholder/awr-platform-api:latest"
}

variable "enable_artifact_storage" {
  type    = bool
  default = true
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

variable "reuse_sql" {
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

variable "existing_sql_server_name" {
  type    = string
  default = ""
}
variable "existing_sql_db_name" {
  type    = string
  default = ""
}
variable "existing_sql_rg" {
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
