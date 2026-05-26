# ── Module: core_rg ───────────────────────────────────────────────────────────
# Creates resource groups following a consistent naming convention.

variable "project" {
  type        = string
  description = "Project short name (e.g. awr)."
}

variable "environment" {
  type        = string
  description = "Environment name (dev, test, prod)."
}

variable "location" {
  type        = string
  description = "Azure region."
  default     = "eastus2"
}

variable "tags" {
  type        = map(string)
  description = "Common tags applied to all resources."
  default     = {}
}

# ── Reuse support ─────────────────────────────────────────────────────────────
variable "reuse" {
  type        = bool
  description = "If true, look up an existing resource group instead of creating one."
  default     = false
}

variable "existing_name" {
  type        = string
  description = "Name of the existing resource group (required when reuse = true)."
  default     = ""
}

data "azurerm_resource_group" "existing" {
  count = var.reuse ? 1 : 0
  name  = var.existing_name
}

resource "azurerm_resource_group" "main" {
  count    = var.reuse ? 0 : 1
  name     = "rg-${var.project}-${var.environment}"
  location = var.location

  tags = merge(var.tags, {
    project     = var.project
    environment = var.environment
  })
}

output "name" {
  value = var.reuse ? data.azurerm_resource_group.existing[0].name : azurerm_resource_group.main[0].name
}

output "location" {
  value = var.reuse ? data.azurerm_resource_group.existing[0].location : azurerm_resource_group.main[0].location
}

output "id" {
  value = var.reuse ? data.azurerm_resource_group.existing[0].id : azurerm_resource_group.main[0].id
}
