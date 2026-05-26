terraform {
  # Local backend for QA smoke deploy. Switch to azurerm backend once the
  # shared tfstate storage account is bootstrapped in this subscription.
  backend "local" {}
}
