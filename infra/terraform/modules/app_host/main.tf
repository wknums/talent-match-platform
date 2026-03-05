# ── Module: app_host ──────────────────────────────────────────────────────────
# Option A (default): App Service for Containers (Linux)
# Option B: Azure Container Apps (ACA)
# Controlled via `host_choice` variable.

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

variable "host_choice" {
  type        = string
  description = "webapp_container or container_apps"
  default     = "webapp_container"
  validation {
    condition     = contains(["webapp_container", "container_apps"], var.host_choice)
    error_message = "host_choice must be webapp_container or container_apps."
  }
}

variable "container_image" {
  type        = string
  description = "Container image for the API (e.g. ghcr.io/org/awr-platform-api:latest)."
  default     = "ghcr.io/placeholder/awr-platform-api:latest"
}

variable "api_identity_id" {
  type        = string
  description = "Resource ID of the user-assigned managed identity for the API."
}

variable "api_client_id" {
  type        = string
  description = "Client ID of the API managed identity."
}

variable "app_settings" {
  type        = map(string)
  description = "Environment variables for the API host."
  default     = {}
}

variable "app_service_sku" {
  type    = string
  default = "B1"
}

variable "log_analytics_workspace_id" {
  type    = string
  default = ""
}

variable "subnet_id" {
  type        = string
  description = "Subnet for VNet integration (optional, empty = no integration)."
  default     = ""
}

variable "tags" {
  type    = map(string)
  default = {}
}

# ── Option A: App Service for Containers ──────────────────────────────────────

resource "azurerm_service_plan" "main" {
  count               = var.host_choice == "webapp_container" ? 1 : 0
  name                = "plan-${var.project}-${var.environment}"
  resource_group_name = var.resource_group_name
  location            = var.location
  os_type             = "Linux"
  sku_name            = var.app_service_sku
  tags                = var.tags
}

resource "azurerm_linux_web_app" "main" {
  count               = var.host_choice == "webapp_container" ? 1 : 0
  name                = "app-${var.project}-${var.environment}"
  resource_group_name = var.resource_group_name
  location            = var.location
  service_plan_id     = azurerm_service_plan.main[0].id

  identity {
    type         = "UserAssigned"
    identity_ids = [var.api_identity_id]
  }

  site_config {
    always_on = true

    application_stack {
      docker_image_name   = var.container_image
    }
  }

  app_settings = merge(var.app_settings, {
    AZURE_CLIENT_ID = var.api_client_id
  })

  tags = var.tags
}

# ── Option B: Azure Container Apps ────────────────────────────────────────────

resource "azurerm_container_app_environment" "main" {
  count                      = var.host_choice == "container_apps" ? 1 : 0
  name                       = "cae-${var.project}-${var.environment}"
  resource_group_name        = var.resource_group_name
  location                   = var.location
  log_analytics_workspace_id = var.log_analytics_workspace_id
  tags                       = var.tags
}

resource "azurerm_container_app" "main" {
  count                        = var.host_choice == "container_apps" ? 1 : 0
  name                         = "ca-${var.project}-api-${var.environment}"
  container_app_environment_id = azurerm_container_app_environment.main[0].id
  resource_group_name          = var.resource_group_name
  revision_mode                = "Single"
  tags                         = var.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [var.api_identity_id]
  }

  template {
    container {
      name   = "api"
      image  = var.container_image
      cpu    = 0.5
      memory = "1Gi"

      dynamic "env" {
        for_each = merge(var.app_settings, { AZURE_CLIENT_ID = var.api_client_id })
        content {
          name  = env.key
          value = env.value
        }
      }
    }
  }

  ingress {
    target_port      = 8000
    external_enabled = true
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }
}

# ── Outputs ───────────────────────────────────────────────────────────────────

output "host_url" {
  value = var.host_choice == "webapp_container" ? (
    length(azurerm_linux_web_app.main) > 0 ? "https://${azurerm_linux_web_app.main[0].default_hostname}" : ""
  ) : (
    length(azurerm_container_app.main) > 0 ? "https://${azurerm_container_app.main[0].ingress[0].fqdn}" : ""
  )
}

output "host_name" {
  value = var.host_choice == "webapp_container" ? (
    length(azurerm_linux_web_app.main) > 0 ? azurerm_linux_web_app.main[0].name : ""
  ) : (
    length(azurerm_container_app.main) > 0 ? azurerm_container_app.main[0].name : ""
  )
}
