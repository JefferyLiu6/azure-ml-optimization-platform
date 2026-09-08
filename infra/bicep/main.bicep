targetScope = 'subscription'

@description('Azure region for all resources.')
param location string = 'canadacentral'

@minLength(3)
@maxLength(12)
param prefix string = 'mlopt'

param environment string = 'dev'
param kubernetesVersion string = ''
param systemNodeVmSize string = 'Standard_D4ds_v5'
@description('Use one node only for temporary evaluation, subject to Azure admission; use multiple nodes for availability.')
@minValue(1)
@maxValue(10)
param systemNodeCount int = 2

var suffix = uniqueString(subscription().subscriptionId, prefix, environment)
var resourceGroupName = '${prefix}-${environment}-rg'
var baseName = toLower('${prefix}${environment}${take(suffix, 6)}')

resource resourceGroup 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: resourceGroupName
  location: location
  tags: {
    application: 'mfbo-platform'
    environment: environment
    managedBy: 'bicep'
  }
}

module core 'modules/core.bicep' = {
  name: 'core-${environment}'
  scope: resourceGroup
  params: {
    location: location
    baseName: baseName
    environment: environment
  }
}

module aks 'modules/aks.bicep' = {
  name: 'aks-${environment}'
  scope: resourceGroup
  params: {
    location: location
    name: '${prefix}-${environment}-aks'
    kubernetesVersion: kubernetesVersion
    systemNodeVmSize: systemNodeVmSize
    systemNodeCount: systemNodeCount
    logAnalyticsWorkspaceId: core.outputs.logAnalyticsWorkspaceId
  }
}

module access 'modules/access.bicep' = {
  name: 'access-${environment}'
  scope: resourceGroup
  params: {
    storageAccountName: core.outputs.storageAccountName
    containerRegistryName: core.outputs.containerRegistryName
    keyVaultName: core.outputs.keyVaultName
    workloadIdentityName: core.outputs.workloadIdentityName
    workloadIdentityPrincipalId: core.outputs.workloadIdentityPrincipalId
    oidcIssuerUrl: aks.outputs.oidcIssuerUrl
    kubeletPrincipalId: aks.outputs.kubeletPrincipalId
  }
}

output resourceGroupName string = resourceGroup.name
output aksName string = aks.outputs.aksName
output acrLoginServer string = core.outputs.acrLoginServer
output storageAccountUrl string = core.outputs.storageAccountUrl
output keyVaultName string = core.outputs.keyVaultName
output workloadClientId string = core.outputs.workloadIdentityClientId
output applicationInsightsConnectionString string = core.outputs.applicationInsightsConnectionString
