#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import tempfile
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from mfbo_platform.artifacts import LocalArtifactStore
from mfbo_platform.config import Settings
from mfbo_platform.domain import ExperimentConfig
from mfbo_platform.engine import DemoEngine
from mfbo_platform.queueing import InMemoryJobQueue
from mfbo_platform.repositories import FilesystemExperimentRepository
from mfbo_platform.service import ExperimentService
from mfbo_platform.worker import ExperimentWorker


def run_case(worker_count: int, experiment_count: int, evaluations: int) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="mfbo-benchmark-") as directory:
        root = Path(directory)
        settings = Settings(
            environment="test",
            state_path=root / "state",
            artifact_path=root / "artifacts",
            mlflow_tracking_uri=None,
        )
        repository = FilesystemExperimentRepository(settings.state_path)
        queue = InMemoryJobQueue()
        artifacts = LocalArtifactStore(settings.artifact_path)
        service = ExperimentService(repository, queue)
        records = [
            service.create(
                ExperimentConfig(
                    benchmark="hartmann6",
                    budget=max(10, evaluations),
                    strategy="random",
                    fidelities=[0.25, 0.5, 1.0],
                    seed=index,
                    max_iterations=evaluations,
                )
            )
            for index in range(experiment_count)
        ]
        workers = [
            ExperimentWorker(settings, repository, queue, DemoEngine(), artifacts)
            for _ in range(worker_count)
        ]
        started = time.perf_counter()
        threads = [threading.Thread(target=lambda item=worker: _drain(item)) for worker in workers]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        duration = time.perf_counter() - started
        completed = [repository.get(record.experiment_id) for record in records]
        queue_latencies = [
            (record.started_at - record.queued_at).total_seconds()
            for record in completed
            if record.started_at
        ]
        failures = sum(record.status != "completed" for record in completed)
        return {
            "workers": worker_count,
            "experiments": experiment_count,
            "evaluations_per_experiment": evaluations,
            "duration_seconds": duration,
            "experiments_per_second": experiment_count / duration,
            "mean_queue_latency_seconds": statistics.fmean(queue_latencies),
            "max_queue_latency_seconds": max(queue_latencies),
            "failures": failures,
        }


def _drain(worker: ExperimentWorker) -> None:
    while worker.run_once(wait_seconds=0):
        pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiments", type=int, default=50)
    parser.add_argument("--evaluations", type=int, default=10)
    parser.add_argument("--workers", type=int, nargs="+", default=[1, 2, 4])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = {
        "timestamp": datetime.now(UTC).isoformat(),
        "scope": "platform-only deterministic demo engine; not an MFBO quality benchmark",
        "system": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "logical_cpu_count": os.cpu_count(),
            "processor": platform.processor(),
        },
        "cases": [
            run_case(workers, args.experiments, args.evaluations) for workers in args.workers
        ],
    }
    rendered = json.dumps(result, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
