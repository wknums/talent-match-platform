# ── Module: service_bus ────────────────────────────────────────────────────────
# Namespace + queues (main + DLQ) + role assignments.

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

variable "sku" {
  type    = string
  default = "Standard"
}

variable "queue_name" {
  type    = string
  default = "engine-runs"
}

variable "max_delivery_count" {
  type    = number
  default = 10
}

variable "sender_principal_ids" {
  type        = list(string)
  description = "Principal IDs that need Azure Service Bus Data Sender role."
  default     = []
}

variable "receiver_principal_ids" {
  type        = list(string)
  description = "Principal IDs that need Azure Service Bus Data Receiver role."
  default     = []
}

variable "tags" {
  type    = map(string)
  default = {}
}

# ── Reuse support ─────────────────────────────────────────────────────────────
variable "reuse" {
  type        = bool
  description = "If true, look up an existing Service Bus namespace instead of creating one."
  default     = false
}

variable "existing_name" {
  type        = string
  description = "Name of the existing Service Bus namespace (required when reuse = true)."
  default     = ""
}

variable "existing_resource_group" {
  type        = string
  description = "Resource group of the existing Service Bus namespace (required when reuse = true)."
  default     = ""
}

data "azurerm_servicebus_namespace" "existing" {
  count               = var.reuse ? 1 : 0
  name                = var.existing_name
  resource_group_name = var.existing_resource_group
}

resource "azurerm_servicebus_namespace" "main" {
  count               = var.reuse ? 0 : 1
  name                = "sb-${var.project}-${var.environment}"
  resource_group_name = var.resource_group_name
  location            = var.location
  sku                 = var.sku
  tags                = var.tags
}

resource "azurerm_servicebus_queue" "main" {
  count               = var.reuse ? 0 : 1
  name                = var.queue_name
  namespace_id        = azurerm_servicebus_namespace.main[0].id
  max_delivery_count  = var.max_delivery_count
  dead_lettering_on_message_expiration = true
}

# Role: Service Bus Data Sender (only when creating new namespace)
resource "azurerm_role_assignment" "sb_sender" {
  count                = var.reuse ? 0 : length(var.sender_principal_ids)
  scope                = azurerm_servicebus_namespace.main[0].id
  role_definition_name = "Azure Service Bus Data Sender"
  principal_id         = var.sender_principal_ids[count.index]
}

# Role: Service Bus Data Receiver (only when creating new namespace)
resource "azurerm_role_assignment" "sb_receiver" {
  count                = var.reuse ? 0 : length(var.receiver_principal_ids)
  scope                = azurerm_servicebus_namespace.main[0].id
  role_definition_name = "Azure Service Bus Data Receiver"
  principal_id         = var.receiver_principal_ids[count.index]
}

output "namespace_name" {
  value = var.reuse ? data.azurerm_servicebus_namespace.existing[0].name : azurerm_servicebus_namespace.main[0].name
}

output "namespace_id" {
  value = var.reuse ? data.azurerm_servicebus_namespace.existing[0].id : azurerm_servicebus_namespace.main[0].id
}

output "namespace_fqdn" {
  value = var.reuse ? "${data.azurerm_servicebus_namespace.existing[0].name}.servicebus.windows.net" : "${azurerm_servicebus_namespace.main[0].name}.servicebus.windows.net"
}

output "queue_name" {
  value = var.queue_name
}
