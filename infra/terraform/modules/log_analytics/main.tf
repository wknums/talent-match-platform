# ── Module: log_analytics ─────────────────────────────────────────────────────

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

variable "retention_in_days" {
  type    = number
  default = 30
}

variable "tags" {
  type    = map(string)
  default = {}
}

# ── Reuse support ─────────────────────────────────────────────────────────────
variable "reuse" {
  type        = bool
  description = "If true, look up an existing Log Analytics workspace instead of creating one."
  default     = false
}

variable "existing_name" {
  type        = string
  description = "Name of the existing Log Analytics workspace (required when reuse = true)."
  default     = ""
}

variable "existing_resource_group" {
  type        = string
  description = "Resource group of the existing workspace. Defaults to resource_group_name when omitted."
  default     = ""
}

locals {
  existing_resource_group_name = trimspace(var.existing_resource_group) != "" ? var.existing_resource_group : var.resource_group_name
}

data "azurerm_log_analytics_workspace" "existing" {
  count               = var.reuse ? 1 : 0
  name                = var.existing_name
  resource_group_name = local.existing_resource_group_name
}

resource "azurerm_log_analytics_workspace" "main" {
  count               = var.reuse ? 0 : 1
  name                = "law-${var.project}-${var.environment}"
  resource_group_name = var.resource_group_name
  location            = var.location
  sku                 = "PerGB2018"
  retention_in_days   = var.retention_in_days
  tags                = var.tags
}

output "id" {
  value = var.reuse ? data.azurerm_log_analytics_workspace.existing[0].id : azurerm_log_analytics_workspace.main[0].id
}

output "workspace_id" {
  value = var.reuse ? data.azurerm_log_analytics_workspace.existing[0].workspace_id : azurerm_log_analytics_workspace.main[0].workspace_id
}

output "primary_shared_key" {
  value     = var.reuse ? data.azurerm_log_analytics_workspace.existing[0].primary_shared_key : azurerm_log_analytics_workspace.main[0].primary_shared_key
  sensitive = true
}
