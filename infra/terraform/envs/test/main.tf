# ── Test environment composition ──────────────────────────────────────────────
# Same module wiring as dev; see dev/main.tf for documentation.

locals {
  common_tags = merge(var.tags, {
    project     = var.project
    environment = var.environment
    managed_by  = "terraform"
  })

  functions_storage_resource_group = trimspace(var.existing_functions_storage_rg) != "" ? var.existing_functions_storage_rg : module.core_rg.name
}

module "core_rg" {
  source        = "../../modules/core_rg"
  project       = var.project
  environment   = var.environment
  location      = var.location
  tags          = local.common_tags
  reuse         = var.reuse_core_rg
  existing_name = var.existing_core_rg_name
}

module "identities" {
  source              = "../../modules/identities"
  resource_group_name = module.core_rg.name
  location            = module.core_rg.location
  project             = var.project
  environment         = var.environment
  tags                = local.common_tags

  reuse                   = var.reuse_identities
  existing_api_name       = var.existing_identities_api_name
  existing_functions_name = var.existing_identities_func_name
  existing_resource_group = var.existing_identities_rg
}

module "networking" {
  source              = "../../modules/networking"
  enabled             = var.use_private_endpoints
  resource_group_name = module.core_rg.name
  location            = module.core_rg.location
  project             = var.project
  environment         = var.environment
  tags                = local.common_tags
}

module "key_vault" {
  source                 = "../../modules/key_vault"
  resource_group_name    = module.core_rg.name
  location               = module.core_rg.location
  project                = var.project
  environment            = var.environment
  tenant_id              = var.tenant_id
  identity_principal_ids = [module.identities.api_principal_id, module.identities.functions_principal_id]
  tags                   = local.common_tags

  reuse                   = var.reuse_key_vault
  existing_name           = var.existing_key_vault_name
  existing_resource_group = var.existing_key_vault_rg
}

module "log_analytics" {
  source              = "../../modules/log_analytics"
  resource_group_name = module.core_rg.name
  location            = module.core_rg.location
  project             = var.project
  environment         = var.environment
  tags                = local.common_tags

  reuse                   = var.reuse_loganalytics
  existing_name           = var.existing_loganalytics_name
  existing_resource_group = var.existing_loganalytics_rg
}

module "application_insights" {
  source                     = "../../modules/application_insights"
  resource_group_name        = module.core_rg.name
  location                   = module.core_rg.location
  project                    = var.project
  environment                = var.environment
  log_analytics_workspace_id = module.log_analytics.id
  tags                       = local.common_tags

  reuse                   = var.reuse_appinsights
  existing_name           = var.existing_appinsights_name
  existing_resource_group = var.existing_appinsights_rg
}

module "service_bus" {
  source                 = "../../modules/service_bus"
  resource_group_name    = module.core_rg.name
  location               = module.core_rg.location
  project                = var.project
  environment            = var.environment
  sku                    = var.service_bus_sku
  queue_name             = var.sb_queue_name
  sender_principal_ids   = [module.identities.api_principal_id, module.identities.functions_principal_id]
  receiver_principal_ids = [module.identities.functions_principal_id]
  tags                   = local.common_tags

  reuse                   = var.reuse_service_bus
  existing_name           = var.existing_service_bus_name
  existing_resource_group = var.existing_service_bus_rg
}

module "storage" {
  source                         = "../../modules/storage"
  enabled                        = var.enable_artifact_storage
  resource_group_name            = module.core_rg.name
  location                       = module.core_rg.location
  project                        = var.project
  environment                    = var.environment
  blob_contributor_principal_ids = [module.identities.api_principal_id, module.identities.functions_principal_id]
  batch_results_retention_days   = var.batch_results_retention_days
  tags                           = local.common_tags

  reuse                   = var.reuse_storage
  existing_name           = var.existing_storage_name
  existing_resource_group = var.existing_storage_rg
}

module "signalr" {
  source                       = "../../modules/signalr"
  enabled                      = var.enable_live_progress
  resource_group_name          = module.core_rg.name
  location                     = module.core_rg.location
  project                      = var.project
  environment                  = var.environment
  sku_name                     = var.signalr_sku
  sku_capacity                 = var.signalr_capacity
  rest_api_owner_principal_ids = [module.identities.functions_principal_id]
  tags                         = local.common_tags

  reuse                   = var.reuse_signalr
  existing_name           = var.existing_signalr_name
  existing_resource_group = var.existing_signalr_rg
}

module "app_host" {
  source                     = "../../modules/app_host"
  resource_group_name        = module.core_rg.name
  location                   = module.core_rg.location
  project                    = var.project
  environment                = var.environment
  host_choice                = var.host_choice
  container_image            = var.container_image
  docker_registry_url        = var.enable_acr_pull ? "https://${var.existing_acr_name}.azurecr.io" : ""
  docker_image_name          = var.enable_acr_pull ? trimprefix(var.container_image, "${var.existing_acr_name}.azurecr.io/") : var.container_image
  acr_use_managed_identity   = var.enable_acr_pull
  api_identity_id            = module.identities.api_identity_id
  api_client_id              = module.identities.api_client_id
  app_service_sku            = var.app_service_sku
  log_analytics_workspace_id = module.log_analytics.id
  subnet_id                  = module.networking.app_subnet_id
  app_settings = {
    SB_NAMESPACE                          = module.service_bus.namespace_fqdn
    SB_QUEUE                              = var.sb_queue_name
    APPLICATIONINSIGHTS_CONNECTION_STRING = module.application_insights.connection_string
  }
  tags = local.common_tags
}

data "azurerm_storage_account" "functions_storage" {
  count               = var.reuse_functions_storage ? 1 : 0
  name                = var.existing_functions_storage_name
  resource_group_name = local.functions_storage_resource_group
}

resource "azurerm_storage_account" "functions_storage" {
  count                           = var.reuse_functions_storage ? 0 : 1
  name                            = substr(replace("st${var.project}fn${var.environment}", "-", ""), 0, 24)
  resource_group_name             = module.core_rg.name
  location                        = module.core_rg.location
  account_tier                    = "Standard"
  account_replication_type        = "LRS"
  min_tls_version                 = "TLS1_2"
  shared_access_key_enabled       = false
  allow_nested_items_to_be_public = false
  tags                            = local.common_tags
}

# Grant the Terraform caller Storage Blob Data Owner so it can create the
# deployment container via AAD (shared key auth is policy-blocked in this tenant).
data "azurerm_client_config" "current" {}

resource "azurerm_role_assignment" "tf_caller_blob_owner" {
  count                = var.reuse_functions_storage ? 0 : 1
  scope                = azurerm_storage_account.functions_storage[0].id
  role_definition_name = "Storage Blob Data Owner"
  principal_id         = data.azurerm_client_config.current.object_id
}

resource "time_sleep" "wait_for_rbac" {
  count           = var.reuse_functions_storage ? 0 : 1
  depends_on      = [azurerm_role_assignment.tf_caller_blob_owner]
  create_duration = "60s"
}

resource "azurerm_storage_container" "functions_deploy" {
  count                 = var.reuse_functions_storage ? 0 : 1
  name                  = var.functions_deployment_container_name
  storage_account_id    = azurerm_storage_account.functions_storage[0].id
  container_access_type = "private"

  depends_on = [time_sleep.wait_for_rbac]
}

module "functions_host" {
  source                                 = "../../modules/functions_host"
  resource_group_name                    = module.core_rg.name
  location                               = module.core_rg.location
  project                                = var.project
  environment                            = var.environment
  functions_identity_id                  = module.identities.functions_identity_id
  functions_client_id                    = module.identities.functions_client_id
  functions_principal_id                 = module.identities.functions_principal_id
  storage_account_id                     = var.reuse_functions_storage ? data.azurerm_storage_account.functions_storage[0].id : azurerm_storage_account.functions_storage[0].id
  storage_account_primary_blob_endpoint  = var.reuse_functions_storage ? data.azurerm_storage_account.functions_storage[0].primary_blob_endpoint : azurerm_storage_account.functions_storage[0].primary_blob_endpoint
  deployment_container_name              = var.functions_deployment_container_name
  application_insights_connection_string = module.application_insights.connection_string
  service_bus_namespace_fqdn             = module.service_bus.namespace_fqdn
  service_bus_queue_name                 = var.sb_queue_name
  service_bus_results_queue_name         = module.service_bus.results_queue_name
  blob_account_name                      = module.storage.storage_account_name
  live_progress_enabled                  = var.enable_live_progress
  signalr_service_endpoint               = module.signalr.service_endpoint
  signalr_hub_name                       = var.signalr_hub_name
  live_progress_target                   = var.live_progress_target
  live_progress_group_prefix             = var.live_progress_group_prefix
  log_analytics_workspace_id             = module.log_analytics.id
  enable_diagnostic_setting              = true
  sku_name                               = var.functions_sku
  tags                                   = local.common_tags
}

module "apim" {
  count                   = var.enable_apim ? 1 : 0
  source                  = "../../modules/apim"
  resource_group_name     = module.core_rg.name
  location                = module.core_rg.location
  project                 = var.project
  environment             = var.environment
  sku_name                = var.apim_sku
  publisher_email         = var.publisher_email
  backend_url             = module.app_host.host_url
  application_insights_id = module.application_insights.id
  tags                    = local.common_tags

  reuse                   = var.reuse_apim
  existing_name           = var.existing_apim_name
  existing_resource_group = var.existing_apim_rg
}

# ── ACR pull access for reused container registry ─────────────────────────────
data "azurerm_container_registry" "existing" {
  count               = var.enable_acr_pull ? 1 : 0
  name                = var.existing_acr_name
  resource_group_name = var.existing_acr_rg
}

resource "azurerm_role_assignment" "api_acr_pull" {
  count                = var.enable_acr_pull ? 1 : 0
  scope                = data.azurerm_container_registry.existing[0].id
  role_definition_name = "AcrPull"
  principal_id         = module.identities.api_principal_id
}

resource "azurerm_role_assignment" "functions_acr_pull" {
  count                = var.enable_acr_pull ? 1 : 0
  scope                = data.azurerm_container_registry.existing[0].id
  role_definition_name = "AcrPull"
  principal_id         = module.identities.functions_principal_id
}
