using './main.bicep'

// Temporary, non-HA deployment evidence. Validate subscription admission first.
param location = 'canadacentral'
param prefix = 'mlopt'
param environment = 'dev'
param systemNodeVmSize = 'Standard_D4ps_v5'
param systemNodeCount = 1
