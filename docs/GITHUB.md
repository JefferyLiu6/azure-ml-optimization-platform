# Put this public edition on GitHub

Use the repository name **azure-ml-optimization-platform**.
Description: “Asynchronous ML optimization jobs with FastAPI, Azure, MLflow, and Kubernetes.”

## 1. Review the folder

Use this export, not the original research workspace. Read [SECURITY.md](SECURITY.md).
The export is created without Git history, credentials, generated results, or a remote.
Run `make verify` before committing.

## 2. Create an empty repository

On GitHub, create a private repository initially. Do not initialize a README, gitignore,
or license there. Choose a license separately before granting reuse rights.

## 3. Authenticate and push

With GitHub CLI installed, run `gh auth login`. Then, from this export:

```bash
git init -b main
git config user.name "YOUR_NAME"
git config user.email "YOUR_GITHUB_NOREPLY_EMAIL"
git add .
git diff --cached --stat
git diff --cached
```

Stop if the staged content includes unexpected data. Otherwise:

```bash
git commit -m "Add Azure ML optimization platform"
git remote add origin https://github.com/YOUR_USERNAME/azure-ml-optimization-platform.git
git push -u origin main
```

CI will check code, tests, images, the local demo stack, and Bicep. A configured workflow
is not evidence that it has run; inspect its actual result before claiming CI success.
Only change visibility after reviewing the uploaded files and generated artifacts.

## 4. Optional Azure releases

Leave `MFBO_ENABLE_DEPLOY` unset until a deployment is explicitly wanted.
Create a protected `production` environment restricted to main and a dedicated OIDC identity:

- Issuer: `https://token.actions.githubusercontent.com`
- Subject: `repo:OWNER/REPOSITORY:environment:production`
- Audience: `api://AzureADTokenExchange`

Set `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`,
`AZURE_DEPLOYMENT_NAME`, and `TARGET_PLATFORM` (linux/arm64 or linux/amd64).
Set repository-level `MFBO_ENABLE_DEPLOY=true` only when ready.

Grant the identity deployment-read access, ACR push, AKS credentials access, and Kubernetes
authorization for the namespace and smoke-test secret. Keep infrastructure role-assignment
privileges out of this routine release identity. The evaluation template does not configure
Entra-based cluster authorization; review this broader credential boundary before team use.

The workflow builds API, demo worker, and MLflow images from this repository. It never needs
external algorithm source or images. A stopped cluster causes deployment to fail; CI does
not start billable compute automatically. Stop the cluster yourself after evaluation.

For rollback, reapply previously verified image digests. Image rollback does not reverse
database migrations; back up persistent state before version-changing upgrades.
