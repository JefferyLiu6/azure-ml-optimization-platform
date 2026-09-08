from pathlib import Path

from fastapi.testclient import TestClient

from mfbo_platform.api import create_app
from mfbo_platform.config import Settings
from mfbo_platform.queueing import InMemoryJobQueue
from mfbo_platform.repositories import FilesystemExperimentRepository


def client(tmp_path: Path) -> TestClient:
    settings = Settings(environment="test", state_path=tmp_path / "state")
    app = create_app(
        settings,
        FilesystemExperimentRepository(settings.state_path),
        InMemoryJobQueue(),
    )
    return TestClient(app)


def test_submit_get_metrics_and_cancel(tmp_path: Path, valid_payload: dict[str, object]) -> None:
    api = client(tmp_path)
    response = api.post("/experiments", json=valid_payload)
    assert response.status_code == 202
    experiment_id = response.json()["experiment_id"]

    state = api.get(f"/experiments/{experiment_id}")
    assert state.status_code == 200
    assert state.json()["configuration"]["seed"] == 42
    assert api.get(f"/experiments/{experiment_id}/metrics").json()["metrics"] == []

    cancelled = api.post(f"/experiments/{experiment_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelling"


def test_validation_and_missing(tmp_path: Path, valid_payload: dict[str, object]) -> None:
    api = client(tmp_path)
    invalid = api.post("/experiments", json={**valid_payload, "budget": -1})
    assert invalid.status_code == 422
    assert api.get("/experiments/missing").status_code == 404
    assert api.get("/experiments/missing/metrics").status_code == 404


def test_health_and_readiness(tmp_path: Path) -> None:
    api = client(tmp_path)
    assert api.get("/health").json() == {"status": "ok"}
    assert api.get("/ready").json()["status"] == "ready"


def test_idempotency_key(tmp_path: Path, valid_payload: dict[str, object]) -> None:
    api = client(tmp_path)
    first = api.post(
        "/experiments", json=valid_payload, headers={"Idempotency-Key": "same-request"}
    )
    second = api.post(
        "/experiments", json=valid_payload, headers={"Idempotency-Key": "same-request"}
    )
    assert first.json()["experiment_id"] == second.json()["experiment_id"]
    conflict = api.post(
        "/experiments",
        json={**valid_payload, "seed": 7},
        headers={"Idempotency-Key": "same-request"},
    )
    assert conflict.status_code == 409


def test_optional_api_key_authentication(tmp_path: Path, valid_payload: dict[str, object]) -> None:
    settings = Settings(
        environment="test",
        state_path=tmp_path / "state",
        require_api_key=True,
        api_key="top-secret",
    )
    api = TestClient(
        create_app(
            settings,
            FilesystemExperimentRepository(settings.state_path),
            InMemoryJobQueue(),
        )
    )
    assert api.post("/experiments", json=valid_payload).status_code == 401
    authorized = api.post("/experiments", json=valid_payload, headers={"X-API-Key": "top-secret"})
    assert authorized.status_code == 202
