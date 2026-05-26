# ── Module: key_vault ─────────────────────────────────────────────────────────

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

variable "tenant_id" {
  type        = string
  description = "Azure AD tenant ID."
}

variable "identity_principal_ids" {
  type        = list(string)
  description = "Principal IDs that need Secret User access."
  default     = []
}

variable "tags" {
  type    = map(string)
  default = {}
}

# ── Reuse support ─────────────────────────────────────────────────────────────
variable "reuse" {
  type        = bool
  description = "If true, look up an existing Key Vault instead of creating one."
  default     = false
}

variable "existing_name" {
  type        = string
  description = "Name of the existing Key Vault (required when reuse = true)."
  default     = ""
}

variable "existing_resource_group" {
  type        = string
  description = "Resource group of the existing Key Vault. Defaults to resource_group_name when omitted."
  default     = ""
}

locals {
  existing_resource_group_name = trimspace(var.existing_resource_group) != "" ? var.existing_resource_group : var.resource_group_name
}

data "azurerm_key_vault" "existing" {
  count               = var.reuse ? 1 : 0
  name                = var.existing_name
  resource_group_name = local.existing_resource_group_name
}

resource "azurerm_key_vault" "main" {
  count                      = var.reuse ? 0 : 1
  name                       = "kv-${var.project}-${var.environment}"
  resource_group_name        = var.resource_group_name
  location                   = var.location
  tenant_id                  = var.tenant_id
  sku_name                   = "standard"
  soft_delete_retention_days = 7
  purge_protection_enabled   = false
  enable_rbac_authorization  = true
  tags                       = var.tags
}

# Grant Key Vault Secrets User to each identity (only when creating new vault)
resource "azurerm_role_assignment" "kv_secrets_user" {
  count                = var.reuse ? 0 : length(var.identity_principal_ids)
  scope                = azurerm_key_vault.main[0].id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = var.identity_principal_ids[count.index]
}

output "id" {
  value = var.reuse ? data.azurerm_key_vault.existing[0].id : azurerm_key_vault.main[0].id
}

output "vault_uri" {
  value = var.reuse ? data.azurerm_key_vault.existing[0].vault_uri : azurerm_key_vault.main[0].vault_uri
}

output "name" {
  value = var.reuse ? data.azurerm_key_vault.existing[0].name : azurerm_key_vault.main[0].name
}
