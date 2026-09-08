# Keep Azure costs under control

Use Docker Compose for everyday development. Start AKS only when you need to validate a
deployment or run an agreed cloud test, then stop it when the session ends.

## Choose the right profile

| Option | Configuration | When to use it | Cost consideration |
| --- | --- | --- | --- |
| Local development | Docker Compose on your machine | Everyday development and testing | No Azure resources required |
| Cloud evaluation: `evidence.bicepparam` | One ARM64 Standard_D4ps_v5 node | Short deployment checks | One billable node while running, plus supporting services |
| Multi-node development: `dev.bicepparam` | Two fixed Standard_D4ds_v5 nodes | Tests that need more than one node | Two billable nodes while running, plus supporting services |

Both cloud profiles use the Free AKS control-plane tier and Basic ACR. Node autoscaling is disabled.
The API autoscaler changes the number of pods, not the number of nodes.

The single-node profile is provided for bounded evaluation. It requires ARM64 images
and does not provide high availability. Availability and quota vary by subscription;
check them again before deploying. Do not increase machine size just to bypass an error.

## Estimate the full cost

Check current rates with the
[Azure retail pricing API](https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices)
for your region, VM size, operating system, and billing currency. No fixed price is quoted
here because rates and account discounts can change.

| Budget item | What to include | How to control it |
| --- | --- | --- |
| AKS worker nodes | Node count × hourly node price × running hours | Use the single-node profile for bounded checks; stop after testing |
| AKS control plane | The configured Free tier | Do not confuse a free control plane with free compute |
| Container registry | Basic ACR service and retained images | Keep required release images; review unused images before removal |
| Persistent disks | Provisioned capacity retained by the deployment | Include disks in the estimate even when AKS is stopped |
| Blob and Queue Storage | Stored data and storage operations | Retain needed evidence; review unnecessary outputs |
| Monitoring | Log ingestion and retained monitoring data | Keep logging appropriate to the test and review retention |
| Networking | Applicable data-transfer and networking charges | Include these separately from the VM estimate |
| Taxes and account adjustments | Applicable taxes, credits, and discounts | Check the estimate against your own billing account |

The total is compute **plus** supporting services and account-specific adjustments.
Quota limits resource allocation; it is neither a reservation nor a spending cap.

## Before starting a session

| Check | What to confirm |
| --- | --- |
| Account and capacity | Correct subscription, region, quota, and available VM size |
| Deployment preview | Expected resources and the intended parameter file |
| Session limit | Planned test duration and a named person responsible for stopping AKS |
| Billing alerts | Notifications are configured; a budget is not a hard spending cap |

See [budget setup](https://learn.microsoft.com/en-us/azure/cost-management-billing/costs/tutorial-acm-create-budgets).
The templates do not install a budget or automatic shutdown.

## End the session

Let jobs finish and save required evidence privately. Replace the placeholders below
with the resource group and cluster you intend to stop:

```bash
az aks stop --resource-group RESOURCE_GROUP --name AKS_NAME
az aks show --resource-group RESOURCE_GROUP --name AKS_NAME --query powerState
```

Check that the cluster reports `Stopped`.

| After the session | What it means for cost |
| --- | --- |
| Stop AKS and verify its state | Stops the cluster's compute; it does not remove the deployment |
| Retain disks, registry, storage, and monitoring data | These resources may continue billing |
| Fully tear down the environment | Removes the resources selected for deletion and destroys their data |

When the environment is no longer needed, follow the
[teardown guidance](RECREATE.md#12-stop-compute-after-saving-evidence).
Export needed data first: deleting a resource group destroys its resources.
