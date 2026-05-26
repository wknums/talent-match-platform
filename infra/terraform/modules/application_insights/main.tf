# ── Module: application_insights ──────────────────────────────────────────────

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

variable "log_analytics_workspace_id" {
  type        = string
  description = "Log Analytics workspace to wire into."
}

variable "tags" {
  type    = map(string)
  default = {}
}

# ── Reuse support ─────────────────────────────────────────────────────────────
variable "reuse" {
  type        = bool
  description = "If true, look up an existing Application Insights instance instead of creating one."
  default     = false
}

variable "existing_name" {
  type        = string
  description = "Name of the existing Application Insights resource (required when reuse = true)."
  default     = ""
}

variable "existing_resource_group" {
  type        = string
  description = "Resource group of the existing Application Insights. Defaults to resource_group_name when omitted."
  default     = ""
}

locals {
  existing_resource_group_name = trimspace(var.existing_resource_group) != "" ? var.existing_resource_group : var.resource_group_name
}

data "azurerm_application_insights" "existing" {
  count               = var.reuse ? 1 : 0
  name                = var.existing_name
  resource_group_name = local.existing_resource_group_name
}

resource "azurerm_application_insights" "main" {
  count               = var.reuse ? 0 : 1
  name                = "appi-${var.project}-${var.environment}"
  resource_group_name = var.resource_group_name
  location            = var.location
  workspace_id        = var.log_analytics_workspace_id
  application_type    = "web"
  tags                = var.tags
}

output "id" {
  value = var.reuse ? data.azurerm_application_insights.existing[0].id : azurerm_application_insights.main[0].id
}

output "instrumentation_key" {
  value     = var.reuse ? data.azurerm_application_insights.existing[0].instrumentation_key : azurerm_application_insights.main[0].instrumentation_key
  sensitive = true
}

output "connection_string" {
  value     = var.reuse ? data.azurerm_application_insights.existing[0].connection_string : azurerm_application_insights.main[0].connection_string
  sensitive = true
}
