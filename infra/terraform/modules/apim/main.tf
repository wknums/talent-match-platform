# ── Module: apim ──────────────────────────────────────────────────────────────
# API Management (Developer or higher) + product + API import + policy attachments.

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
  type        = string
  description = "APIM SKU: Developer_1, Basic_1, Standard_1, Premium_1, Consumption_0."
  default     = "Developer_1"
}

variable "publisher_name" {
  type    = string
  default = "AWR Platform"
}

variable "publisher_email" {
  type = string
}

variable "backend_url" {
  type        = string
  description = "Backend URL of the Platform API (e.g. https://app-awr-dev.azurewebsites.net)."
}

variable "application_insights_id" {
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
  description = "If true, look up an existing APIM instance instead of creating one."
  default     = false
}

variable "existing_name" {
  type        = string
  description = "Name of the existing APIM instance (required when reuse = true)."
  default     = ""
}

variable "existing_resource_group" {
  type        = string
  description = "Resource group of the existing APIM instance. Defaults to resource_group_name when omitted."
  default     = ""
}

locals {
  existing_resource_group_name = trimspace(var.existing_resource_group) != "" ? var.existing_resource_group : var.resource_group_name
}

data "azurerm_api_management" "existing" {
  count               = var.reuse ? 1 : 0
  name                = var.existing_name
  resource_group_name = local.existing_resource_group_name
}

resource "azurerm_api_management" "main" {
  count               = var.reuse ? 0 : 1
  name                = "apim-${var.project}-${var.environment}"
  resource_group_name = var.resource_group_name
  location            = var.location
  publisher_name      = var.publisher_name
  publisher_email     = var.publisher_email
  sku_name            = var.sku_name
  tags                = var.tags
}

# ── Product ───────────────────────────────────────────────────────────────────

resource "azurerm_api_management_product" "platform" {
  count                 = var.reuse ? 0 : 1
  product_id            = "${var.project}-platform"
  resource_group_name   = var.resource_group_name
  api_management_name   = azurerm_api_management.main[0].name
  display_name          = "AWR Platform"
  description           = "AWR Platform API product"
  subscription_required = true
  approval_required     = false
  published             = true
}

# ── API (OpenAPI import placeholder) ──────────────────────────────────────────

resource "azurerm_api_management_api" "platform_api" {
  count               = var.reuse ? 0 : 1
  name                = "${var.project}-platform-api"
  resource_group_name = var.resource_group_name
  api_management_name = azurerm_api_management.main[0].name
  revision            = "1"
  display_name        = "AWR Platform API"
  path                = "platform"
  protocols           = ["https"]
  service_url         = var.backend_url
  subscription_key_parameter_names {
    header = "Ocp-Apim-Subscription-Key"
    query  = "subscription-key"
  }
}

resource "azurerm_api_management_product_api" "platform" {
  count               = var.reuse ? 0 : 1
  resource_group_name = var.resource_group_name
  api_management_name = azurerm_api_management.main[0].name
  product_id          = azurerm_api_management_product.platform[0].product_id
  api_name            = azurerm_api_management_api.platform_api[0].name
}

# ── Policy attachment (rate limit + correlation-id) ───────────────────────────

resource "azurerm_api_management_api_policy" "platform_policy" {
  count               = var.reuse ? 0 : 1
  resource_group_name = var.resource_group_name
  api_management_name = azurerm_api_management.main[0].name
  api_name            = azurerm_api_management_api.platform_api[0].name

  xml_content = <<-XML
    <policies>
      <inbound>
        <base />
        <set-header name="X-Correlation-Id" exists-action="skip">
          <value>@(context.RequestId.ToString())</value>
        </set-header>
        <rate-limit calls="100" renewal-period="60" />
        <quota calls="10000" renewal-period="86400" />
      </inbound>
      <backend>
        <retry condition="@(context.Response.StatusCode >= 500)" count="3"
               interval="1" max-interval="10" delta="2" first-fast-retry="false">
          <forward-request buffer-request-body="true" />
        </retry>
      </backend>
      <outbound>
        <base />
        <set-header name="X-Correlation-Id" exists-action="override">
          <value>@(context.Request.Headers.GetValueOrDefault("X-Correlation-Id", context.RequestId.ToString()))</value>
        </set-header>
        <set-header name="Authorization" exists-action="delete" />
      </outbound>
      <on-error>
        <base />
      </on-error>
    </policies>
  XML
}

output "gateway_url" {
  value = var.reuse ? data.azurerm_api_management.existing[0].gateway_url : azurerm_api_management.main[0].gateway_url
}

output "management_api_url" {
  value = var.reuse ? data.azurerm_api_management.existing[0].management_api_url : azurerm_api_management.main[0].management_api_url
}

output "apim_name" {
  value = var.reuse ? data.azurerm_api_management.existing[0].name : azurerm_api_management.main[0].name
}
