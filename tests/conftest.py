from pathlib import Path

import pytest

from mfbo_platform.artifacts import LocalArtifactStore
from mfbo_platform.config import Settings
from mfbo_platform.queueing import InMemoryJobQueue
from mfbo_platform.repositories import FilesystemExperimentRepository


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        environment="test",
        state_path=tmp_path / "state",
        artifact_path=tmp_path / "artifacts",
        worker_poll_seconds=1,
        mlflow_tracking_uri=None,
    )


@pytest.fixture
def repository(settings: Settings) -> FilesystemExperimentRepository:
    return FilesystemExperimentRepository(settings.state_path)


@pytest.fixture
def queue() -> InMemoryJobQueue:
    return InMemoryJobQueue()


@pytest.fixture
def artifacts(settings: Settings) -> LocalArtifactStore:
    return LocalArtifactStore(settings.artifact_path)


@pytest.fixture
def valid_payload() -> dict[str, object]:
    return {
        "benchmark": "hartmann6",
        "budget": 10,
        "strategy": "random",
        "fidelities": [0.25, 0.5, 1.0],
        "seed": 42,
        "max_iterations": 5,
    }
