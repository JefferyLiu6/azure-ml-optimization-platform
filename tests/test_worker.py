from __future__ import annotations

import threading
import time

from mfbo_platform.artifacts import LocalArtifactStore
from mfbo_platform.config import Settings
from mfbo_platform.domain import ExperimentConfig, ExperimentStatus
from mfbo_platform.engine import DemoEngine
from mfbo_platform.errors import EngineError
from mfbo_platform.queueing import InMemoryJobQueue
from mfbo_platform.repositories import FilesystemExperimentRepository
from mfbo_platform.service import ExperimentService
from mfbo_platform.worker import ExperimentWorker


def build_worker(
    settings: Settings,
    repository: FilesystemExperimentRepository,
    queue: InMemoryJobQueue,
    engine: DemoEngine,
    artifacts: LocalArtifactStore,
) -> ExperimentWorker:
    return ExperimentWorker(settings, repository, queue, engine, artifacts)


def test_worker_completes_and_persists_artifacts(
    settings: Settings,
    repository: FilesystemExperimentRepository,
    queue: InMemoryJobQueue,
    artifacts: LocalArtifactStore,
    valid_payload: dict[str, object],
) -> None:
    record = ExperimentService(repository, queue).create(
        ExperimentConfig.model_validate(valid_payload)
    )
    worker = build_worker(settings, repository, queue, DemoEngine(), artifacts)
    assert worker.run_once()
    completed = repository.get(record.experiment_id)
    assert completed.status == ExperimentStatus.COMPLETED
    assert completed.progress == 1.0
    assert completed.completed_evaluations == 5
    assert completed.recommendation is not None
    assert len(repository.list_metrics(record.experiment_id)) == 5
    assert set(completed.result_metadata["artifacts"]) == {
        "configuration",
        "result",
        "convergence_plot",
    }


def test_worker_records_failure(
    settings: Settings,
    repository: FilesystemExperimentRepository,
    queue: InMemoryJobQueue,
    artifacts: LocalArtifactStore,
    valid_payload: dict[str, object],
) -> None:
    record = ExperimentService(repository, queue).create(
        ExperimentConfig.model_validate(valid_payload)
    )
    worker = build_worker(settings, repository, queue, DemoEngine(fail=True), artifacts)
    worker.run_once()
    failed = repository.get(record.experiment_id)
    assert failed.status == ExperimentStatus.FAILED
    assert failed.failure is not None
    assert failed.failure.code == "demo_failure"


def test_cancellation_during_execution(
    settings: Settings,
    repository: FilesystemExperimentRepository,
    queue: InMemoryJobQueue,
    artifacts: LocalArtifactStore,
    valid_payload: dict[str, object],
) -> None:
    payload = {**valid_payload, "max_iterations": 100, "budget": 100}
    service = ExperimentService(repository, queue)
    record = service.create(ExperimentConfig.model_validate(payload))
    worker = build_worker(
        settings, repository, queue, DemoEngine(iteration_delay_seconds=0.01), artifacts
    )
    thread = threading.Thread(target=worker.run_once)
    thread.start()
    deadline = time.monotonic() + 2
    while repository.get(record.experiment_id).completed_evaluations == 0:
        assert time.monotonic() < deadline
        time.sleep(0.005)
    service.request_cancellation(record.experiment_id)
    thread.join(timeout=3)
    assert not thread.is_alive()
    cancelled = repository.get(record.experiment_id)
    assert cancelled.status == ExperimentStatus.CANCELLED
    assert 0 < cancelled.completed_evaluations < 100


def test_retryable_failure_is_requeued_once(
    settings: Settings,
    repository: FilesystemExperimentRepository,
    queue: InMemoryJobQueue,
    artifacts: LocalArtifactStore,
    valid_payload: dict[str, object],
) -> None:
    class RetryOnceEngine(DemoEngine):
        def __init__(self) -> None:
            super().__init__()
            self.calls = 0

        def execute(self, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
            self.calls += 1
            if self.calls == 1:
                raise EngineError("temporary", retryable=True, code="temporary")
            return super().execute(*args, **kwargs)  # type: ignore[arg-type]

    record = ExperimentService(repository, queue).create(
        ExperimentConfig.model_validate(valid_payload)
    )
    engine = RetryOnceEngine()
    worker = build_worker(settings, repository, queue, engine, artifacts)
    worker.run_once()
    assert repository.get(record.experiment_id).status == ExperimentStatus.QUEUED
    worker.run_once()
    assert repository.get(record.experiment_id).status == ExperimentStatus.COMPLETED


def test_demo_engine_is_deterministic(valid_payload: dict[str, object]) -> None:
    config = ExperimentConfig.model_validate(valid_payload)
    results = []
    for _ in range(2):
        metrics = []
        result = DemoEngine().execute("test", config, metrics.append, lambda: False, lambda: False)
        payload = result.model_dump(
            exclude={
                "metrics": {"__all__": {"recorded_at"}},
                "recommendation": {"observed_at"},
            }
        )
        results.append(payload)
    assert results[0] == results[1]
