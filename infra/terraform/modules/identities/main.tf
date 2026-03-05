# ── Module: identities ────────────────────────────────────────────────────────
# Creates user-assigned Managed Identities and outputs principal IDs.

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

variable "tags" {
  type    = map(string)
  default = {}
}

# ── Reuse support ─────────────────────────────────────────────────────────────
variable "reuse" {
  type        = bool
  description = "If true, look up existing Managed Identities instead of creating them."
  default     = false
}

variable "existing_api_name" {
  type        = string
  description = "Name of the existing API managed identity (required when reuse = true)."
  default     = ""
}

variable "existing_functions_name" {
  type        = string
  description = "Name of the existing Functions managed identity (required when reuse = true)."
  default     = ""
}

variable "existing_resource_group" {
  type        = string
  description = "Resource group of the existing identities (required when reuse = true)."
  default     = ""
}

data "azurerm_user_assigned_identity" "existing_api" {
  count               = var.reuse ? 1 : 0
  name                = var.existing_api_name
  resource_group_name = var.existing_resource_group
}

data "azurerm_user_assigned_identity" "existing_functions" {
  count               = var.reuse ? 1 : 0
  name                = var.existing_functions_name
  resource_group_name = var.existing_resource_group
}

resource "azurerm_user_assigned_identity" "api" {
  count               = var.reuse ? 0 : 1
  name                = "id-${var.project}-api-${var.environment}"
  resource_group_name = var.resource_group_name
  location            = var.location
  tags                = var.tags
}

resource "azurerm_user_assigned_identity" "functions" {
  count               = var.reuse ? 0 : 1
  name                = "id-${var.project}-func-${var.environment}"
  resource_group_name = var.resource_group_name
  location            = var.location
  tags                = var.tags
}

output "api_identity_id" {
  value = var.reuse ? data.azurerm_user_assigned_identity.existing_api[0].id : azurerm_user_assigned_identity.api[0].id
}

output "api_principal_id" {
  value = var.reuse ? data.azurerm_user_assigned_identity.existing_api[0].principal_id : azurerm_user_assigned_identity.api[0].principal_id
}

output "api_client_id" {
  value = var.reuse ? data.azurerm_user_assigned_identity.existing_api[0].client_id : azurerm_user_assigned_identity.api[0].client_id
}

output "functions_identity_id" {
  value = var.reuse ? data.azurerm_user_assigned_identity.existing_functions[0].id : azurerm_user_assigned_identity.functions[0].id
}

output "functions_principal_id" {
  value = var.reuse ? data.azurerm_user_assigned_identity.existing_functions[0].principal_id : azurerm_user_assigned_identity.functions[0].principal_id
}

output "functions_client_id" {
  value = var.reuse ? data.azurerm_user_assigned_identity.existing_functions[0].client_id : azurerm_user_assigned_identity.functions[0].client_id
}
