# ── Module: storage (optional) ────────────────────────────────────────────────
# Blob account/containers for artifacts; role assignments for MIs.

variable "enabled" {
  type    = bool
  default = false
}

variable "resource_group_name" {
  type = string
}

variable "location" {
  type = string
}

variable "project" {
  type = string
}

variable "environment" {
  type = string
}

variable "blob_contributor_principal_ids" {
  type        = list(string)
  description = "Principal IDs that need Storage Blob Data Contributor."
  default     = []
}

variable "batch_results_container_name" {
  type    = string
  default = "batch-results"
}

variable "batch_results_retention_days" {
  type    = number
  default = 7
}

variable "containers" {
  type        = list(string)
  description = "Blob container names to create."
  default     = ["artifacts"]
}

variable "tags" {
  type    = map(string)
  default = {}
}

# ── Reuse support ─────────────────────────────────────────────────────────────
variable "reuse" {
  type        = bool
  description = "If true, look up an existing Storage Account instead of creating one."
  default     = false
}

variable "existing_name" {
  type        = string
  description = "Name of the existing Storage Account (required when reuse = true)."
  default     = ""
}

variable "existing_resource_group" {
  type        = string
  description = "Resource group of the existing Storage Account. Defaults to resource_group_name when omitted."
  default     = ""
}

locals {
  existing_resource_group_name = trimspace(var.existing_resource_group) != "" ? var.existing_resource_group : var.resource_group_name
}

data "azurerm_storage_account" "existing" {
  count               = var.reuse ? 1 : 0
  name                = var.existing_name
  resource_group_name = local.existing_resource_group_name
}

resource "azurerm_storage_account" "artifacts" {
  count                           = var.reuse ? 0 : (var.enabled ? 1 : 0)
  name                            = "st${var.project}art${var.environment}"
  resource_group_name             = var.resource_group_name
  location                        = var.location
  account_tier                    = "Standard"
  account_replication_type        = "LRS"
  min_tls_version                 = "TLS1_2"
  shared_access_key_enabled       = false
  allow_nested_items_to_be_public = false
  tags                            = var.tags
}

locals {
  have_created  = !var.reuse && var.enabled && length(azurerm_storage_account.artifacts) > 0
  have_existing = var.reuse && length(data.azurerm_storage_account.existing) > 0
  storage_account_name = local.have_existing ? data.azurerm_storage_account.existing[0].name : (
    local.have_created ? azurerm_storage_account.artifacts[0].name : ""
  )
  storage_account_id = local.have_existing ? data.azurerm_storage_account.existing[0].id : (
    local.have_created ? azurerm_storage_account.artifacts[0].id : ""
  )
  container_names = distinct(concat(var.containers, [var.batch_results_container_name]))
}

resource "azurerm_storage_container" "containers" {
  count                 = local.storage_account_id != "" ? length(local.container_names) : 0
  name                  = local.container_names[count.index]
  storage_account_id    = local.storage_account_id
  container_access_type = "private"
}

resource "azurerm_role_assignment" "blob_contributor" {
  count                = local.storage_account_id != "" ? length(var.blob_contributor_principal_ids) : 0
  scope                = local.storage_account_id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = var.blob_contributor_principal_ids[count.index]
}

resource "azurerm_storage_management_policy" "batch_results_retention" {
  count              = local.have_created && var.batch_results_retention_days > 0 ? 1 : 0
  storage_account_id = local.storage_account_id

  rule {
    name    = "delete-batch-results"
    enabled = true

    filters {
      prefix_match = [var.batch_results_container_name]
      blob_types   = ["blockBlob"]
    }

    actions {
      base_blob {
        delete_after_days_since_modification_greater_than = var.batch_results_retention_days
      }
    }
  }
}

output "storage_account_name" {
  value = local.storage_account_name
}

output "storage_account_id" {
  value = local.storage_account_id
}

output "primary_access_key" {
  value = local.have_existing ? data.azurerm_storage_account.existing[0].primary_access_key : (
    local.have_created ? azurerm_storage_account.artifacts[0].primary_access_key : ""
  )
  sensitive = true
}
