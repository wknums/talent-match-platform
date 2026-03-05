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

resource "azurerm_resource_group" "main" {
  name     = "rg-${var.project}-${var.environment}"
  location = var.location

  tags = merge(var.tags, {
    project     = var.project
    environment = var.environment
  })
}

output "name" {
  value = azurerm_resource_group.main.name
}

output "location" {
  value = azurerm_resource_group.main.location
}

output "id" {
  value = azurerm_resource_group.main.id
}
