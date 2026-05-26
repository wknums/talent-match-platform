# ── Module: functions_host ─────────────────────────────────────────────────────
# Azure Functions on Flex Consumption (FC1) with managed-identity storage.

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

variable "functions_principal_id" {
  type        = string
  description = "Principal (object) ID of the Functions managed identity."
}

variable "storage_account_id" {
  type        = string
  description = "Resource ID of the storage account used for the Function App deployment package."
}

variable "storage_account_primary_blob_endpoint" {
  type        = string
  description = "Primary blob endpoint of the storage account (e.g. https://xxx.blob.core.windows.net/)."
}

variable "deployment_container_name" {
  type    = string
  default = "app-package"
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

variable "service_bus_results_queue_name" {
  type    = string
  default = "engine-results"
}

variable "blob_account_name" {
  type        = string
  description = "Storage account name for batch result artifacts (BLOB_ACCOUNT)."
  default     = ""
}

variable "blob_results_container" {
  type    = string
  default = "batch-results"
}

variable "live_progress_enabled" {
  type    = bool
  default = false
}

variable "signalr_service_endpoint" {
  type    = string
  default = ""
}

variable "signalr_hub_name" {
  type    = string
  default = "batch-progress"
}

variable "live_progress_target" {
  type    = string
  default = "batchProgress"
}

variable "live_progress_group_prefix" {
  type    = string
  default = "submission"
}

variable "log_analytics_workspace_id" {
  type        = string
  description = "Log Analytics workspace ID for the Function App diagnostic setting."
  default     = ""
}

variable "enable_diagnostic_setting" {
  type        = bool
  description = "Whether to create the Function App diagnostic setting."
  default     = false
}

variable "app_settings" {
  type    = map(string)
  default = {}
}

variable "sku_name" {
  type    = string
  default = "FC1"
}

variable "runtime_name" {
  type    = string
  default = "python"
}

variable "runtime_version" {
  type    = string
  default = "3.11"
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

resource "azurerm_role_assignment" "functions_storage_blob_owner" {
  scope                = var.storage_account_id
  role_definition_name = "Storage Blob Data Owner"
  principal_id         = var.functions_principal_id
}

resource "azurerm_role_assignment" "functions_storage_queue_contrib" {
  scope                = var.storage_account_id
  role_definition_name = "Storage Queue Data Contributor"
  principal_id         = var.functions_principal_id
}

resource "azurerm_role_assignment" "functions_storage_table_contrib" {
  scope                = var.storage_account_id
  role_definition_name = "Storage Table Data Contributor"
  principal_id         = var.functions_principal_id
}

resource "azurerm_function_app_flex_consumption" "main" {
  name                = "func-${var.project}-${var.environment}"
  resource_group_name = var.resource_group_name
  location            = var.location
  service_plan_id     = azurerm_service_plan.functions.id

  storage_container_type            = "blobContainer"
  storage_container_endpoint        = "${var.storage_account_primary_blob_endpoint}${var.deployment_container_name}"
  storage_authentication_type       = "UserAssignedIdentity"
  storage_user_assigned_identity_id = var.functions_identity_id

  runtime_name    = var.runtime_name
  runtime_version = var.runtime_version

  identity {
    type         = "UserAssigned"
    identity_ids = [var.functions_identity_id]
  }

  site_config {
    application_insights_connection_string = var.application_insights_connection_string
  }

  app_settings = merge(var.app_settings, {
    AZURE_CLIENT_ID            = var.functions_client_id
    SB_NAMESPACE               = var.service_bus_namespace_fqdn
    SB_QUEUE                   = var.service_bus_queue_name
    SB_RUNS_QUEUE              = var.service_bus_queue_name
    SB_RESULTS_QUEUE           = var.service_bus_results_queue_name
    BLOB_ACCOUNT               = var.blob_account_name
    BLOB_RESULTS_CONTAINER     = var.blob_results_container
    LIVE_PROGRESS_ENABLED      = tostring(var.live_progress_enabled)
    SIGNALR_SERVICE_ENDPOINT   = var.signalr_service_endpoint
    SIGNALR_HUB_NAME           = var.signalr_hub_name
    LIVE_PROGRESS_TARGET       = var.live_progress_target
    LIVE_PROGRESS_GROUP_PREFIX = var.live_progress_group_prefix
    AzureWebJobsFeatureFlags   = "EnableWorkerIndexing"
    # AzureWebJobsStorage (Durable Functions backend) — MI auth, no shared key.
    AzureWebJobsStorage__accountName = element(reverse(split("/", var.storage_account_id)), 0)
    AzureWebJobsStorage__credential  = "managedidentity"
    AzureWebJobsStorage__clientId    = var.functions_client_id
    # Service Bus trigger binding (connection="SbConnection") – MI auth.
    SbConnection__fullyQualifiedNamespace = var.service_bus_namespace_fqdn
    SbConnection__credential              = "managedidentity"
    SbConnection__clientId                = var.functions_client_id
  })

  tags = var.tags

  depends_on = [
    azurerm_role_assignment.functions_storage_blob_owner,
    azurerm_role_assignment.functions_storage_queue_contrib,
    azurerm_role_assignment.functions_storage_table_contrib,
  ]
}

resource "azurerm_monitor_diagnostic_setting" "functions" {
  count                      = var.enable_diagnostic_setting ? 1 : 0
  name                       = "diag-func-${var.project}-${var.environment}"
  target_resource_id         = azurerm_function_app_flex_consumption.main.id
  log_analytics_workspace_id = var.log_analytics_workspace_id

  enabled_log {
    category = "FunctionAppLogs"
  }

  metric {
    category = "AllMetrics"
  }
}

output "function_app_name" {
  value = azurerm_function_app_flex_consumption.main.name
}

output "function_app_default_hostname" {
  value = azurerm_function_app_flex_consumption.main.default_hostname
}

output "function_app_id" {
  value = azurerm_function_app_flex_consumption.main.id
}
