# Recreate the public demo: local setup to Azure

This guide deploys only the public demo. No external engine or source archive is needed.
Use a new evaluation resource group, not an existing research deployment. Commands assume
Bash/zsh. Replace placeholders, stop at failed checks, and review cost before provisioning.
This public edition has not yet been deployed to Azure.

## Before you begin

- **Learn locally:** complete steps 1–2. No Azure charges.
- **Recreate from scratch:** complete steps 1–12. Provisioning starts billing.
- **Reopen the existing deployment:** skip provisioning and builds; use step 13.
- **Set up GitHub releases:** finish the manual path first, then follow [GITHUB.md](GITHUB.md).

Keep credentials and generated outputs out of Git.

## 1. Install tools and enter the project

Install Docker Desktop and start it. Install Python 3.12, uv 0.7.5, Azure CLI, and
kubectl using their official installers. On macOS with Homebrew already installed:

```bash
brew install azure-cli kubectl
python3 -m pip install --user uv==0.7.5
cd /path/to/MFBO_Public
docker version
az version
kubectl version --client
uv --version
uv sync --frozen --all-extras
```

If `uv` is not on PATH, use its official installer instead of changing system Python.
On another machine, enter your checkout directory. The demo is self-contained.

## 2. Start and test the local demo

```bash
make verify
docker compose up -d --build --wait --wait-timeout 180
curl -f http://127.0.0.1:18080/ready
uv run python scripts/smoke_stack.py --output benchmark-results/local-public.json
```

Expected: readiness HTTP 200 and smoke `status: completed`, `mlflow_finished: true`.
Open API docs at http://127.0.0.1:18080/docs and MLflow at http://127.0.0.1:15500.
This tests the demo, not research quality. The optional live Azurite test requires its
environment variable; the Compose smoke also exercises Azure adapters.

## 3. Check deployment scope

Use the included demo worker. Do not reuse another project's images, storage, or secrets.
The parameter files use a separate resource prefix. Check quota and cost first.

## 4. Authenticate to Azure and inspect the account

```bash
az login --use-device-code
az account list --query '[].{name:name,id:id,state:state}' -o table
export MFBO_SUBSCRIPTION_ID=REPLACE_WITH_YOUR_SUBSCRIPTION_ID
az account set --subscription "$MFBO_SUBSCRIPTION_ID"
az account show --query '{name:name,id:id,state:state}' -o table
export MFBO_REGION=canadacentral
export MFBO_DEPLOYMENT=mlopt-public
```

The code is entered only on Microsoft's device-login page. Never share a token/cache.
Provisioning requires resource creation and role-assignment privileges. If these are
missing, ask the subscription administrator; do not disable security to work around it.

## 5. Register providers, check quota, and preview

Provider registration enables APIs; it does not create a VM.

```bash
for provider in Microsoft.Compute Microsoft.ContainerService Microsoft.ContainerRegistry Microsoft.Storage Microsoft.KeyVault Microsoft.ManagedIdentity Microsoft.Network Microsoft.OperationalInsights Microsoft.Insights; do
  az provider register --namespace "$provider" --wait
done
az vm list-usage --location "$MFBO_REGION" --query "[?name.value=='cores' || name.value=='standardDPSv5Family']" -o table
az vm list-skus --location "$MFBO_REGION" --size Standard_D4ps_v5 --all --query '[].{name:name,restrictions:restrictions}' -o json
az deployment sub what-if --name "$MFBO_DEPLOYMENT" --location "$MFBO_REGION" \
  --template-file infra/bicep/main.bicep --parameters infra/bicep/evidence.bicepparam
```

The evidence profile is one **ARM64** Standard_D4ps_v5 node with no node autoscaling,
Free AKS control plane, and Basic ACR. It is not highly available. It needs a live preflight
in your subscription. Do not blindly retry with
larger machines or paid tiers. Read [COSTS.md](COSTS.md) and current pricing first.
Check the current node price and supporting-service costs before provisioning.
Azure budgets alert; they do not impose a hard spending cap.

## 6. Provision — billing begins here

```bash
az deployment sub create --name "$MFBO_DEPLOYMENT" --location "$MFBO_REGION" \
  --template-file infra/bicep/main.bicep --parameters infra/bicep/evidence.bicepparam \
  --query properties.provisioningState -o tsv
```

Expected: `Succeeded`. This can take several minutes. If deployment fails, inspect
the resource group for partially created, billable resources before abandoning it.
Read only the outputs needed below, rather than printing all telemetry configuration:

```bash
export MFBO_RG=$(az deployment sub show -n "$MFBO_DEPLOYMENT" --query properties.outputs.resourceGroupName.value -o tsv)
export MFBO_AKS=$(az deployment sub show -n "$MFBO_DEPLOYMENT" --query properties.outputs.aksName.value -o tsv)
export MFBO_ACR=$(az deployment sub show -n "$MFBO_DEPLOYMENT" --query properties.outputs.acrLoginServer.value -o tsv)
export MFBO_VAULT=$(az deployment sub show -n "$MFBO_DEPLOYMENT" --query properties.outputs.keyVaultName.value -o tsv)
export MFBO_STORAGE=$(az deployment sub show -n "$MFBO_DEPLOYMENT" --query properties.outputs.storageAccountUrl.value -o tsv)
export MFBO_CLIENT=$(az deployment sub show -n "$MFBO_DEPLOYMENT" --query properties.outputs.workloadClientId.value -o tsv)
export MFBO_TENANT=$(az account show --query tenantId -o tsv)
export MFBO_INSIGHTS=$(az resource list -g "$MFBO_RG" --resource-type Microsoft.Insights/components --query '[0].name' -o tsv)
```

## 7. Initialize secrets with temporary, scoped access

This explicitly grants your account secret-management access to **this vault only**.
Record the returned assignment ID and remove that exact assignment afterward. If you
already have an equivalent permanent role, skip creating/deleting a temporary one.

```bash
export MFBO_DEPLOYER=$(az ad signed-in-user show --query id -o tsv)
export MFBO_VAULT_SCOPE=$(az keyvault show -n "$MFBO_VAULT" --query id -o tsv)
export MFBO_TEMP_ROLE=$(az role assignment create --assignee-object-id "$MFBO_DEPLOYER" \
  --assignee-principal-type User --role 'Key Vault Secrets Officer' \
  --scope "$MFBO_VAULT_SCOPE" --query id -o tsv)
uv run python scripts/initialize_azure_secrets.py --vault "$MFBO_VAULT" \
  --resource-group "$MFBO_RG" --insights "$MFBO_INSIGHTS"
az role assignment delete --ids "$MFBO_TEMP_ROLE"
```

RBAC propagation can take time: if initialization returns Forbidden, wait and rerun only
initialization, then remove the role. Always remove it even if setup is abandoned.
The initializer preserves existing keys and never prints values. Do not use `--value`
with a literal API key in terminal history. Runtime pods use Workload Identity instead
of your account. No Azure storage connection string is needed in production.

For an existing installation, back up the MLflow SQLite database consistently before
upgrading the server image: stop experiment submission, let workers finish, and use the
SQLite backup API or a stopped-volume backup. Do not merely copy a live database file.
Also retain its artifacts. Version migrations may prevent a simple image-only rollback.

## 8. Build and push demo images

Use your approved ACR with admin access disabled. Build all three images from this folder.

```bash
az acr show -n "${MFBO_ACR%%.*}" --query '{server:loginServer,admin:adminUserEnabled}'
az acr login -n "${MFBO_ACR%%.*}"
export MFBO_TAG=recreated-v1
export MFBO_PLATFORM=linux/arm64
docker buildx build --platform "$MFBO_PLATFORM" --load -f Dockerfile.api -t "$MFBO_ACR/mfbo-api:$MFBO_TAG" .
docker buildx build --platform "$MFBO_PLATFORM" --load -f Dockerfile.worker --target public-worker -t "$MFBO_ACR/mfbo-tracking:$MFBO_TAG" .
docker buildx build --platform "$MFBO_PLATFORM" --load -f Dockerfile.worker --target public-worker -t "$MFBO_ACR/mfbo-worker:$MFBO_TAG" .
docker push "$MFBO_ACR/mfbo-api:$MFBO_TAG"
docker push "$MFBO_ACR/mfbo-tracking:$MFBO_TAG"
docker push "$MFBO_ACR/mfbo-worker:$MFBO_TAG"
```

Use a new tag for each release. ARM64 is mandatory for this node; emulation on x86 may
be slow. Check that every build uses this public folder. Resolve immutable digests after successful pushes:

```bash
export MFBO_API_DIGEST=$(az acr repository show -n "${MFBO_ACR%%.*}" --image "mfbo-api:$MFBO_TAG" --query digest -o tsv)
export MFBO_WORKER_DIGEST=$(az acr repository show -n "${MFBO_ACR%%.*}" --image "mfbo-worker:$MFBO_TAG" --query digest -o tsv)
export MFBO_TRACKING_DIGEST=$(az acr repository show -n "${MFBO_ACR%%.*}" --image "mfbo-tracking:$MFBO_TAG" --query digest -o tsv)
```

## 9. Deploy and wait for Ready

```bash
export MFBO_SESSION=$(mktemp -d /tmp/mfbo-session.XXXXXX)
export KUBECONFIG="$MFBO_SESSION/kubeconfig"
az aks get-credentials -g "$MFBO_RG" -n "$MFBO_AKS" --file "$KUBECONFIG"
uv run python scripts/render_k8s.py \
  --api-image "$MFBO_ACR/mfbo-api@$MFBO_API_DIGEST" \
  --worker-image "$MFBO_ACR/mfbo-worker@$MFBO_WORKER_DIGEST" \
  --tracking-image "$MFBO_ACR/mfbo-tracking@$MFBO_TRACKING_DIGEST" \
  --storage-url "$MFBO_STORAGE" --client-id "$MFBO_CLIENT" \
  --tenant-id "$MFBO_TENANT" --key-vault "$MFBO_VAULT" --output "$MFBO_SESSION/azure.yaml"
kubectl apply --dry-run=server -f "$MFBO_SESSION/azure.yaml"
kubectl apply -f "$MFBO_SESSION/azure.yaml"
kubectl rollout status -n mfbo deployment/mfbo-api --timeout=5m
kubectl rollout status -n mfbo deployment/mfbo-worker --timeout=10m
kubectl rollout status -n mfbo deployment/mfbo-mlflow --timeout=5m
kubectl get nodes
kubectl get pods -n mfbo
```

On a brand-new namespace, server dry-run may report missing namespace because dry-run
does not persist it. In that case create only the namespace with `kubectl create namespace
mfbo`, then repeat dry-run. Expected: one Ready node, two API pods, one worker, one MLflow.
Do not remove `enableServiceLinks: false`; injected service variables previously broke startup.

## 10. Verify the cloud demo and save evidence

Open two additional terminals, setting KUBECONFIG to the same **actual** path from step 9.
Do not rerun `mktemp` in these terminals.

```bash
# Terminal A
kubectl --kubeconfig /actual/session/path/kubeconfig -n mfbo port-forward service/mfbo-api 18000:80
# Terminal B
kubectl --kubeconfig /actual/session/path/kubeconfig -n mfbo port-forward service/mfbo-mlflow 15501:5000
```

Back in the original terminal:

```bash
curl -f http://127.0.0.1:18000/ready
uv run python scripts/verify_aks.py --kubeconfig "$KUBECONFIG" \
  --mlflow-url http://127.0.0.1:15501 --output benchmark-results/my-aks-run
```

Expected: `AKS workload evidence and end-to-end smoke passed`. Outputs are allowlisted
readiness and demo-completion summaries. They omit configuration, image references, and
credentials. Review evidence before sharing. One smoke duration is not a scaling benchmark.

## 11. Inspect operations without exposing secrets

```bash
kubectl get events -n mfbo --sort-by=.lastTimestamp
kubectl logs -n mfbo deployment/mfbo-api --tail=50
kubectl logs -n mfbo deployment/mfbo-worker --tail=50
curl -f http://127.0.0.1:18000/metrics
```

In Azure Portal, open this project's Application Insights and Log Analytics workspace.
Filter application traces by experiment ID and Container Insights by namespace `mfbo`.
Provisioning a monitoring resource does not itself prove ingestion; see the verification
guide for scope. Do not export secrets or private diagnostic bundles.

## 12. Stop compute after saving evidence

Stop tunnels with Ctrl-C. After all jobs finish:

```bash
az aks stop -g "$MFBO_RG" -n "$MFBO_AKS"
az aks show -g "$MFBO_RG" -n "$MFBO_AKS" --query '{power:powerState.code,state:provisioningState}'
```

Expected: `Stopped` and `Succeeded`. A stopped cluster retains disks, ACR, Blob results,
and monitoring data: those may still bill. For complete teardown, export required data,
inspect both the project and AKS-managed resource groups, and deliberately delete the
project resource group through Azure Portal. Deletion destroys cloud experiments and
images; Key Vault purge protection delays permanent vault deletion. Do not automate
resource-group deletion while learning this workflow.

## 13. Resume the existing deployment instead of rebuilding

For an existing public demo environment, use `MFBO_DEPLOYMENT=mlopt-public` and read outputs
using step 6. This avoids creating duplicate resources. Starting it resumes charges:

```bash
az aks start -g "$MFBO_RG" -n "$MFBO_AKS"
```

Create a private session/kubeconfig as in step 9, wait for the existing deployments,
then follow steps 10–12. Do not recreate secrets or repush images just to show evidence.

## Troubleshooting checkpoints

| Symptom | Check/action |
| --- | --- |
| VM SKU not allowed | Read the actual AKS preflight alternatives; match quota, architecture, and budget. |
| ImagePullBackOff | Check exact ACR digest and kubelet AcrPull role; do not enable ACR admin credentials. |
| Secret mount Forbidden | Check Workload Identity federation subject, client ID and vault role; allow RBAC propagation. |
| API port validation error | Ensure the pod spec has `enableServiceLinks: false`. |
| Exec format error | Image architecture does not match the node. Rebuild for the correct platform. |
| Readiness fails | Check Blob/Queue access and demo-engine configuration; don't weaken readiness. |
| MLflow briefly RUNNING after job completion | Use the bounded smoke checker; investigate persistent tracking failures. |
| Pod Pending on the single node | Inspect CPU/memory requests and events; don't raise node count without checking cost/quota. |
| Old experiment missing after reinstall | Verify account/container names and retained MLflow disk; do not substitute a fresh backend. |
