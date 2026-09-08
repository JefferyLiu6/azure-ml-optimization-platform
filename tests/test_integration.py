from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mfbo_platform.api import create_app
from mfbo_platform.artifacts import LocalArtifactStore
from mfbo_platform.config import Settings
from mfbo_platform.domain import ExperimentStatus
from mfbo_platform.engine import DemoEngine
from mfbo_platform.queueing import InMemoryJobQueue
from mfbo_platform.repositories import FilesystemExperimentRepository
from mfbo_platform.worker import ExperimentWorker


@pytest.mark.integration
def test_api_to_worker_to_retrieval(tmp_path: Path, valid_payload: dict[str, object]) -> None:
    settings = Settings(
        environment="test", state_path=tmp_path / "state", artifact_path=tmp_path / "artifacts"
    )
    repository = FilesystemExperimentRepository(settings.state_path)
    queue = InMemoryJobQueue()
    api = TestClient(create_app(settings, repository, queue))
    response = api.post("/experiments", json=valid_payload)
    experiment_id = response.json()["experiment_id"]

    worker = ExperimentWorker(
        settings, repository, queue, DemoEngine(), LocalArtifactStore(settings.artifact_path)
    )
    assert worker.run_once()

    state = api.get(f"/experiments/{experiment_id}").json()
    assert state["status"] == ExperimentStatus.COMPLETED
    metrics = api.get(f"/experiments/{experiment_id}/metrics").json()["metrics"]
    assert len(metrics) == 5
    recommendation = api.get(f"/experiments/{experiment_id}/recommendation").json()
    assert recommendation["recommendation"]["candidate"]
