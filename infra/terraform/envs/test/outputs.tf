output "apim_base_url" {
  value = length(module.apim) > 0 ? module.apim[0].gateway_url : ""
}

output "acr_login_server" {
  value = length(data.azurerm_container_registry.existing) > 0 ? data.azurerm_container_registry.existing[0].login_server : ""
}

output "api_host_url" {
  value = module.app_host.host_url
}

output "functions_name" {
  value = module.functions_host.function_app_name
}

output "service_bus_namespace" {
  value = module.service_bus.namespace_fqdn
}

output "signalr_service_endpoint" {
  value = module.signalr.service_endpoint
}

output "api_principal_id" {
  value = module.identities.api_principal_id
}

output "functions_principal_id" {
  value = module.identities.functions_principal_id
}

output "application_insights_connection_string" {
  value     = module.application_insights.connection_string
  sensitive = true
}

output "key_vault_uri" {
  value = module.key_vault.vault_uri
}
