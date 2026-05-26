terraform {
  backend "azurerm" {
    resource_group_name  = "rg-awr-tfstate"
    storage_account_name = "awrtfstate" # TODO: replace after bootstrap
    container_name       = "tfstate"
    key                  = "prod.terraform.tfstate"
  }
}
