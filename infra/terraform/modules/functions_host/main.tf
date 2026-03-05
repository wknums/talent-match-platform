# ── Module: functions_host ─────────────────────────────────────────────────────
# Azure Functions for Durable Functions (Consumption / Premium / Container).

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

variable "functions_identity_id" {
  type        = string
  description = "Resource ID of the user-assigned managed identity for Functions."
}

variable "functions_client_id" {
  type        = string
  description = "Client ID of the Functions managed identity."
}

variable "storage_account_name" {
  type        = string
  description = "Storage account for Azure Functions runtime."
}

variable "storage_account_access_key" {
  type      = string
  sensitive = true
}

variable "application_insights_connection_string" {
  type      = string
  sensitive = true
  default   = ""
}

variable "service_bus_namespace_fqdn" {
  type    = string
  default = ""
}

variable "service_bus_queue_name" {
  type    = string
  default = "engine-runs"
}

variable "app_settings" {
  type    = map(string)
  default = {}
}

variable "sku_name" {
  type        = string
  description = "Functions plan SKU: Y1 (Consumption), EP1-EP3 (Premium), B1/S1 etc."
  default     = "Y1"
}

variable "tags" {
  type    = map(string)
  default = {}
}

resource "azurerm_service_plan" "functions" {
  name                = "plan-func-${var.project}-${var.environment}"
  resource_group_name = var.resource_group_name
  location            = var.location
  os_type             = "Linux"
  sku_name            = var.sku_name
  tags                = var.tags
}

resource "azurerm_linux_function_app" "main" {
  name                       = "func-${var.project}-${var.environment}"
  resource_group_name        = var.resource_group_name
  location                   = var.location
  service_plan_id            = azurerm_service_plan.functions.id
  storage_account_name       = var.storage_account_name
  storage_account_access_key = var.storage_account_access_key

  identity {
    type         = "UserAssigned"
    identity_ids = [var.functions_identity_id]
  }

  site_config {
    application_stack {
      python_version = "3.11"
    }
  }

  app_settings = merge(var.app_settings, {
    AZURE_CLIENT_ID                        = var.functions_client_id
    APPLICATIONINSIGHTS_CONNECTION_STRING   = var.application_insights_connection_string
    SB_NAMESPACE                           = var.service_bus_namespace_fqdn
    SB_QUEUE                               = var.service_bus_queue_name
    AzureWebJobsFeatureFlags               = "EnableWorkerIndexing"
  })

  tags = var.tags
}

output "function_app_name" {
  value = azurerm_linux_function_app.main.name
}

output "function_app_default_hostname" {
  value = azurerm_linux_function_app.main.default_hostname
}

output "function_app_id" {
  value = azurerm_linux_function_app.main.id
}
