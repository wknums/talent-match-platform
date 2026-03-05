# ── Module: networking (optional) ─────────────────────────────────────────────
# VNet, subnets, private DNS zones, and private endpoints.
# Toggled via `enabled` variable.

variable "enabled" {
  type        = bool
  description = "Set to true to provision networking resources."
  default     = false
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

variable "vnet_address_space" {
  type    = list(string)
  default = ["10.0.0.0/16"]
}

variable "subnet_app_prefix" {
  type    = string
  default = "10.0.1.0/24"
}

variable "subnet_sql_prefix" {
  type    = string
  default = "10.0.2.0/24"
}

variable "subnet_apim_prefix" {
  type    = string
  default = "10.0.3.0/24"
}

variable "tags" {
  type    = map(string)
  default = {}
}

resource "azurerm_virtual_network" "main" {
  count               = var.enabled ? 1 : 0
  name                = "vnet-${var.project}-${var.environment}"
  resource_group_name = var.resource_group_name
  location            = var.location
  address_space       = var.vnet_address_space
  tags                = var.tags
}

resource "azurerm_subnet" "app" {
  count                = var.enabled ? 1 : 0
  name                 = "snet-app"
  resource_group_name  = var.resource_group_name
  virtual_network_name = azurerm_virtual_network.main[0].name
  address_prefixes     = [var.subnet_app_prefix]

  delegation {
    name = "app-delegation"
    service_delegation {
      name    = "Microsoft.Web/serverFarms"
      actions = ["Microsoft.Network/virtualNetworks/subnets/action"]
    }
  }
}

resource "azurerm_subnet" "sql" {
  count                = var.enabled ? 1 : 0
  name                 = "snet-sql"
  resource_group_name  = var.resource_group_name
  virtual_network_name = azurerm_virtual_network.main[0].name
  address_prefixes     = [var.subnet_sql_prefix]
}

resource "azurerm_subnet" "apim" {
  count                = var.enabled ? 1 : 0
  name                 = "snet-apim"
  resource_group_name  = var.resource_group_name
  virtual_network_name = azurerm_virtual_network.main[0].name
  address_prefixes     = [var.subnet_apim_prefix]
}

output "vnet_id" {
  value = var.enabled ? azurerm_virtual_network.main[0].id : ""
}

output "app_subnet_id" {
  value = var.enabled ? azurerm_subnet.app[0].id : ""
}

output "sql_subnet_id" {
  value = var.enabled ? azurerm_subnet.sql[0].id : ""
}

output "apim_subnet_id" {
  value = var.enabled ? azurerm_subnet.apim[0].id : ""
}
