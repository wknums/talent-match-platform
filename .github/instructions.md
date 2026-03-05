security policy prohibits use of SAS tokens for Blob Storage. Do not create code the uses SAS for BLOB

always ensure that you activate the virtual python environment .venv in the root folder before executing any python scripts

All code and resources are intended to be deployed on Azure

Ensure that all azure apis are using the latest GA versions available. and keep the requirements.txt file updated

Each deployment version must include a full date and time stamp

default shell to git bash

use terraform for infrastructure as code provisioning, and ensure that no secrets or resource identifiers are exposed in any code. - use variables instead.

use entra authentication and RBAC only - no keyauth is permitted.

maintain a valid requirements.txt file