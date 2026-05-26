# ── Module: signalr ───────────────────────────────────────────────────────────
# Optional Azure SignalR Service with REST API Owner assignments for publishers.

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

variable "sku_name" {
  type    = string
  default = "Standard_S1"
}

variable "sku_capacity" {
  type    = number
  default = 1
}

variable "public_network_access_enabled" {
  type    = bool
  default = true
}

variable "local_auth_enabled" {
  type    = bool
  default = false
}

variable "aad_auth_enabled" {
  type    = bool
  default = true
}

variable "service_mode" {
  type    = string
  default = "Default"
}

variable "rest_api_owner_principal_ids" {
  type        = list(string)
  description = "Principal IDs that need SignalR REST API Owner on the service."
  default     = []
}

variable "tags" {
  type    = map(string)
  default = {}
}

variable "reuse" {
  type        = bool
  description = "If true, look up an existing SignalR service instead of creating one."
  default     = false
}

variable "existing_name" {
  type        = string
  description = "Name of the existing SignalR service (required when reuse = true)."
  default     = ""
}

variable "existing_resource_group" {
  type        = string
  description = "Resource group of the existing SignalR service. Defaults to resource_group_name when omitted."
  default     = ""
}

locals {
  existing_resource_group_name = trimspace(var.existing_resource_group) != "" ? var.existing_resource_group : var.resource_group_name
}

data "azurerm_signalr_service" "existing" {
  count               = var.enabled && var.reuse ? 1 : 0
  name                = var.existing_name
  resource_group_name = local.existing_resource_group_name
}

resource "azurerm_signalr_service" "main" {
  count               = var.enabled && !var.reuse ? 1 : 0
  name                = "signalr-${var.project}-${var.environment}"
  resource_group_name = var.resource_group_name
  location            = var.location

  sku {
    name     = var.sku_name
    capacity = var.sku_capacity
  }

  service_mode                  = var.service_mode
  public_network_access_enabled = var.public_network_access_enabled
  local_auth_enabled            = var.local_auth_enabled
  aad_auth_enabled              = var.aad_auth_enabled
  connectivity_logs_enabled     = true
  messaging_logs_enabled        = true
  http_request_logs_enabled     = true
  tags                          = var.tags
}

locals {
  have_created  = var.enabled && !var.reuse && length(azurerm_signalr_service.main) > 0
  have_existing = var.enabled && var.reuse && length(data.azurerm_signalr_service.existing) > 0
  signalr_id = local.have_existing ? data.azurerm_signalr_service.existing[0].id : (
    local.have_created ? azurerm_signalr_service.main[0].id : ""
  )
  signalr_hostname = local.have_existing ? data.azurerm_signalr_service.existing[0].hostname : (
    local.have_created ? azurerm_signalr_service.main[0].hostname : ""
  )
}

resource "azurerm_role_assignment" "signalr_rest_api_owner" {
  count                = local.signalr_id != "" ? length(var.rest_api_owner_principal_ids) : 0
  scope                = local.signalr_id
  role_definition_name = "SignalR REST API Owner"
  principal_id         = var.rest_api_owner_principal_ids[count.index]
}

output "service_id" {
  value = local.signalr_id
}

output "service_endpoint" {
  value = local.signalr_hostname != "" ? "https://${local.signalr_hostname}" : ""
}

output "service_hostname" {
  value = local.signalr_hostname
}