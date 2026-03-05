# ── Test environment composition ──────────────────────────────────────────────
# Same module wiring as dev; see dev/main.tf for documentation.

locals {
  common_tags = merge(var.tags, {
    project     = var.project
    environment = var.environment
    managed_by  = "terraform"
  })
}

module "core_rg" {
  source      = "../../modules/core_rg"
  project     = var.project
  environment = var.environment
  location    = var.location
  tags        = local.common_tags
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

module "sql" {
  source                     = "../../modules/sql"
  resource_group_name        = module.core_rg.name
  location                   = module.core_rg.location
  project                    = var.project
  environment                = var.environment
  tenant_id                  = var.tenant_id
  aad_admin_object_id        = var.aad_admin_object_id
  sku_name                   = var.sql_sku
  max_size_gb                = var.sql_max_size_gb
  use_private_endpoint       = var.use_private_endpoints
  private_endpoint_subnet_id = module.networking.sql_subnet_id
  tags                       = local.common_tags

  reuse                   = var.reuse_sql
  existing_server_name    = var.existing_sql_server_name
  existing_db_name        = var.existing_sql_db_name
  existing_resource_group = var.existing_sql_rg
}

module "service_bus" {
  source                 = "../../modules/service_bus"
  resource_group_name    = module.core_rg.name
  location               = module.core_rg.location
  project                = var.project
  environment            = var.environment
  sku                    = var.service_bus_sku
  queue_name             = var.sb_queue_name
  sender_principal_ids   = [module.identities.functions_principal_id]
  receiver_principal_ids = [module.identities.functions_principal_id]
  tags                   = local.common_tags

  reuse                   = var.reuse_service_bus
  existing_name           = var.existing_service_bus_name
  existing_resource_group = var.existing_service_bus_rg
}

module "storage" {
  source                        = "../../modules/storage"
  enabled                       = var.enable_artifact_storage
  resource_group_name           = module.core_rg.name
  location                      = module.core_rg.location
  project                       = var.project
  environment                   = var.environment
  blob_contributor_principal_ids = [module.identities.api_principal_id, module.identities.functions_principal_id]
  tags                          = local.common_tags

  reuse                   = var.reuse_storage
  existing_name           = var.existing_storage_name
  existing_resource_group = var.existing_storage_rg
}

module "app_host" {
  source              = "../../modules/app_host"
  resource_group_name = module.core_rg.name
  location            = module.core_rg.location
  project             = var.project
  environment         = var.environment
  host_choice         = var.host_choice
  container_image     = var.container_image
  api_identity_id     = module.identities.api_identity_id
  api_client_id       = module.identities.api_client_id
  app_service_sku     = var.app_service_sku
  log_analytics_workspace_id = module.log_analytics.id
  subnet_id           = module.networking.app_subnet_id
  app_settings = {
    SQL_SERVER                             = module.sql.server_fqdn
    SQL_DATABASE                           = module.sql.database_name
    SB_NAMESPACE                           = module.service_bus.namespace_fqdn
    SB_QUEUE                               = var.sb_queue_name
    APPLICATIONINSIGHTS_CONNECTION_STRING   = module.application_insights.connection_string
  }
  tags = local.common_tags
}

resource "azurerm_storage_account" "functions_storage" {
  name                     = "st${var.project}fn${var.environment}"
  resource_group_name      = module.core_rg.name
  location                 = module.core_rg.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  min_tls_version          = "TLS1_2"
  tags                     = local.common_tags
}

module "functions_host" {
  source                                 = "../../modules/functions_host"
  resource_group_name                    = module.core_rg.name
  location                               = module.core_rg.location
  project                                = var.project
  environment                            = var.environment
  functions_identity_id                  = module.identities.functions_identity_id
  functions_client_id                    = module.identities.functions_client_id
  storage_account_name                   = azurerm_storage_account.functions_storage.name
  storage_account_access_key             = azurerm_storage_account.functions_storage.primary_access_key
  application_insights_connection_string = module.application_insights.connection_string
  service_bus_namespace_fqdn             = module.service_bus.namespace_fqdn
  service_bus_queue_name                 = var.sb_queue_name
  sku_name                               = var.functions_sku
  tags                                   = local.common_tags
}

module "apim" {
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
