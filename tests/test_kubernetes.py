"""Deployment regressions discovered by real AKS validation."""

from pathlib import Path
from runpy import run_path

import pytest
import yaml

validate_substitutions = run_path(str(Path(__file__).parents[1] / "scripts/render_k8s.py"))[
    "validate_substitutions"
]


def test_deployments_disable_service_environment_injection() -> None:
    manifests = yaml.safe_load_all((Path(__file__).parents[1] / "k8s" / "azure.yaml").read_text())
    deployments = [item for item in manifests if item["kind"] == "Deployment"]
    assert len(deployments) == 3
    for deployment in deployments:
        # Service mfbo-api otherwise injects MFBO_API_PORT=tcp://..., which
        # shadows the application's integer setting and crashes API and worker.
        assert deployment["spec"]["template"]["spec"]["enableServiceLinks"] is False


@pytest.mark.parametrize("value", ["image\n---\nkind: Secret", 'image"', "", "image tag"])
def test_render_rejects_image_injection(value: str) -> None:
    with pytest.raises(ValueError):
        validate_substitutions({"__API_IMAGE__": value})


@pytest.mark.parametrize(
    "value",
    ["http://account.blob.core.windows.net", "https://a/?sig=secret", "https://user:pass@a/"],
)
def test_render_rejects_insecure_storage_url(value: str) -> None:
    with pytest.raises(ValueError):
        validate_substitutions({"__AZURE_STORAGE_ACCOUNT_URL__": value})


def test_render_accepts_secure_azure_values() -> None:
    validate_substitutions(
        {
            "__API_IMAGE__": "example.azurecr.io/mfbo-api@sha256:" + "a" * 64,
            "__AZURE_STORAGE_ACCOUNT_URL__": "https://example.blob.core.windows.net/",
            "__AZURE_CLIENT_ID__": "00000000-0000-0000-0000-000000000001",
            "__KEY_VAULT_NAME__": "example-vault",
        }
    )


def test_release_builds_only_this_repository() -> None:
    workflow = yaml.safe_load(
        (Path(__file__).parents[1] / ".github/workflows/ci-cd.yml").read_text()
    )
    deploy = workflow["jobs"]["deploy"]
    assert "MFBO_ENABLE_DEPLOY" in deploy["if"]
    assert deploy["environment"] == "production"
    builds = [
        step
        for step in deploy["steps"]
        if step.get("uses", "").startswith("docker/build-push-action")
    ]
    assert len(builds) == 3
    assert all(step["with"]["context"] == "." for step in builds)
    assert all(step["with"]["platforms"] == "${{ vars.TARGET_PLATFORM }}" for step in builds)
    assert "verify_aks.py" in str(deploy)
