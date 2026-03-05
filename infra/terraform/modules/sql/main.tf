# ── Module: sql ───────────────────────────────────────────────────────────────
# Azure SQL Server + Database with AAD admin and optional private endpoint.

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

variable "aad_admin_object_id" {
  type        = string
  description = "Object ID of the AAD principal to set as SQL Server admin."
}

variable "aad_admin_login" {
  type        = string
  description = "Display name for the AAD admin login."
  default     = "awr-sql-admins"
}

variable "tenant_id" {
  type = string
}

variable "sku_name" {
  type        = string
  description = "Azure SQL Database SKU (e.g. S0, GP_S_Gen5_1)."
  default     = "S0"
}

variable "max_size_gb" {
  type    = number
  default = 2
}

variable "use_private_endpoint" {
  type    = bool
  default = false
}

variable "private_endpoint_subnet_id" {
  type    = string
  default = ""
}

variable "tags" {
  type    = map(string)
  default = {}
}

# ── Reuse support ─────────────────────────────────────────────────────────────
variable "reuse" {
  type        = bool
  description = "If true, look up an existing Azure SQL server + database instead of creating them."
  default     = false
}

variable "existing_server_name" {
  type        = string
  description = "Name of the existing SQL Server (required when reuse = true)."
  default     = ""
}

variable "existing_db_name" {
  type        = string
  description = "Name of the existing SQL Database (required when reuse = true)."
  default     = ""
}

variable "existing_resource_group" {
  type        = string
  description = "Resource group of the existing SQL Server (required when reuse = true)."
  default     = ""
}

data "azurerm_mssql_server" "existing" {
  count               = var.reuse ? 1 : 0
  name                = var.existing_server_name
  resource_group_name = var.existing_resource_group
}

data "azurerm_mssql_database" "existing" {
  count     = var.reuse ? 1 : 0
  name      = var.existing_db_name
  server_id = data.azurerm_mssql_server.existing[0].id
}

resource "azurerm_mssql_server" "main" {
  count                        = var.reuse ? 0 : 1
  name                         = "sql-${var.project}-${var.environment}"
  resource_group_name          = var.resource_group_name
  location                     = var.location
  version                      = "12.0"
  minimum_tls_version          = "1.2"
  public_network_access_enabled = var.use_private_endpoint ? false : true

  azuread_administrator {
    login_username              = var.aad_admin_login
    object_id                   = var.aad_admin_object_id
    tenant_id                   = var.tenant_id
    azuread_authentication_only = true
  }

  tags = var.tags
}

resource "azurerm_mssql_database" "main" {
  count     = var.reuse ? 0 : 1
  name      = "${var.project}db${var.environment}"
  server_id = azurerm_mssql_server.main[0].id
  sku_name  = var.sku_name
  max_size_gb = var.max_size_gb

  tags = var.tags
}

# Allow Azure services (when not using private endpoints and not reusing)
resource "azurerm_mssql_firewall_rule" "allow_azure" {
  count            = var.reuse ? 0 : (var.use_private_endpoint ? 0 : 1)
  name             = "AllowAzureServices"
  server_id        = azurerm_mssql_server.main[0].id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "0.0.0.0"
}

# Optional private endpoint (only when creating new server)
resource "azurerm_private_endpoint" "sql" {
  count               = var.reuse ? 0 : (var.use_private_endpoint ? 1 : 0)
  name                = "pe-sql-${var.project}-${var.environment}"
  resource_group_name = var.resource_group_name
  location            = var.location
  subnet_id           = var.private_endpoint_subnet_id
  tags                = var.tags

  private_service_connection {
    name                           = "psc-sql"
    private_connection_resource_id = azurerm_mssql_server.main[0].id
    is_manual_connection           = false
    subresource_names              = ["sqlServer"]
  }
}

output "server_fqdn" {
  value = var.reuse ? data.azurerm_mssql_server.existing[0].fully_qualified_domain_name : azurerm_mssql_server.main[0].fully_qualified_domain_name
}

output "database_name" {
  value = var.reuse ? data.azurerm_mssql_database.existing[0].name : azurerm_mssql_database.main[0].name
}

output "server_id" {
  value = var.reuse ? data.azurerm_mssql_server.existing[0].id : azurerm_mssql_server.main[0].id
}
