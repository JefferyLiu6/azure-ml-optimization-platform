# Security and publication

This export contains the engineering platform and a self-contained demo. It excludes the
research engine, its integration implementation, source inventories, research results,
source archives, and the original Git history. No remote is configured by the export.

## Before uploading

1. Review `git status` and the complete staged diff.
2. Keep generated outputs, credentials, local environments, and raw logs out of commits.
3. Run `make verify` and inspect the public API schema.
4. Review any added files and CI uploads; ignore rules are not a confidentiality guarantee.
5. Choose a license deliberately. The existing proprietary declaration is not an open-source
   license grant; publication alone does not change usage rights.

The workflow publishes only allowlisted demo readiness summaries. Recheck this boundary
whenever the workload or evidence generator changes.

## Runtime safeguards and limits

| Area | Current control | Remaining limitation |
| --- | --- | --- |
| Secrets | Key Vault CSI and Workload Identity on AKS | Rotate keys and restart pods to refresh environment values |
| API | Bounded schemas and constant-time API-key comparison | No per-user authorization, rate limiting, or TLS ingress |
| Storage | Entra credentials on Azure; no anonymous Blob access | Private endpoints are not configured |
| Containers | Non-root API/worker and restricted Kubernetes contexts | Local MLflow runs as root for volume initialization |
| Deployment | OIDC and protected environment | Cluster credential scope needs review before team use |
| Evidence | Allowlisted status summaries | Logs and screenshots still require manual review |

Compose uses an explicitly documented emulator account key, not an Azure credential.
Local services bind to loopback. Keep AKS services internal until stronger access controls
are configured. Dependency scanning is point-in-time and does not prove absence of flaws.
