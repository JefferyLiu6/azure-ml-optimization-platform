import uuid

import pytest

from mfbo_platform.domain import (
    ExperimentConfig,
    ExperimentRecord,
    ExperimentStatus,
    MetricPoint,
)
from mfbo_platform.errors import ConflictError, NotFoundError
from mfbo_platform.repositories import FilesystemExperimentRepository


def record(valid_payload: dict[str, object]) -> ExperimentRecord:
    return ExperimentRecord(
        experiment_id=str(uuid.uuid4()),
        job_id=str(uuid.uuid4()),
        status=ExperimentStatus.QUEUED,
        configuration=ExperimentConfig.model_validate(valid_payload),
    )


def test_create_get_and_mutate(
    repository: FilesystemExperimentRepository, valid_payload: dict[str, object]
) -> None:
    value = record(valid_payload)
    repository.create(value)
    loaded = repository.get(value.experiment_id)
    assert loaded == value

    updated = repository.mutate(
        value.experiment_id,
        lambda current: current.model_copy(update={"status": ExperimentStatus.RUNNING}),
    )
    assert updated.status == ExperimentStatus.RUNNING
    assert updated.version == 2


def test_duplicate_and_missing(
    repository: FilesystemExperimentRepository, valid_payload: dict[str, object]
) -> None:
    value = record(valid_payload)
    repository.create(value)
    with pytest.raises(ConflictError):
        repository.create(value)
    with pytest.raises(NotFoundError):
        repository.get("missing")


def test_metrics_are_idempotent_by_iteration(
    repository: FilesystemExperimentRepository, valid_payload: dict[str, object]
) -> None:
    value = record(valid_payload)
    repository.create(value)
    metric = MetricPoint(
        iteration=0,
        objective=1.0,
        best_objective=1.0,
        cumulative_cost=1.0,
        fidelity=1.0,
        strategy="random",
    )
    repository.append_metric(value.experiment_id, metric)
    repository.append_metric(value.experiment_id, metric.model_copy(update={"objective": 0.5}))
    metrics = repository.list_metrics(value.experiment_id)
    assert len(metrics) == 1
    assert metrics[0].objective == 0.5
