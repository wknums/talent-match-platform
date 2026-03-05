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
  description = "Resource group of the existing Storage Account (required when reuse = true)."
  default     = ""
}

data "azurerm_storage_account" "existing" {
  count               = var.reuse ? 1 : 0
  name                = var.existing_name
  resource_group_name = var.existing_resource_group
}

resource "azurerm_storage_account" "artifacts" {
  count                    = var.reuse ? 0 : (var.enabled ? 1 : 0)
  name                     = "st${var.project}art${var.environment}"
  resource_group_name      = var.resource_group_name
  location                 = var.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  min_tls_version          = "TLS1_2"
  tags                     = var.tags
}

resource "azurerm_storage_container" "containers" {
  count                 = var.reuse ? 0 : (var.enabled ? length(var.containers) : 0)
  name                  = var.containers[count.index]
  storage_account_id    = azurerm_storage_account.artifacts[0].id
  container_access_type = "private"
}

resource "azurerm_role_assignment" "blob_contributor" {
  count                = var.reuse ? 0 : (var.enabled ? length(var.blob_contributor_principal_ids) : 0)
  scope                = azurerm_storage_account.artifacts[0].id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = var.blob_contributor_principal_ids[count.index]
}

locals {
  have_created = !var.reuse && var.enabled && length(azurerm_storage_account.artifacts) > 0
  have_existing = var.reuse && length(data.azurerm_storage_account.existing) > 0
}

output "storage_account_name" {
  value = local.have_existing ? data.azurerm_storage_account.existing[0].name : (
    local.have_created ? azurerm_storage_account.artifacts[0].name : ""
  )
}

output "storage_account_id" {
  value = local.have_existing ? data.azurerm_storage_account.existing[0].id : (
    local.have_created ? azurerm_storage_account.artifacts[0].id : ""
  )
}

output "primary_access_key" {
  value = local.have_existing ? data.azurerm_storage_account.existing[0].primary_access_key : (
    local.have_created ? azurerm_storage_account.artifacts[0].primary_access_key : ""
  )
  sensitive = true
}
