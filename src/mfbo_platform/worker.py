from __future__ import annotations

import logging
import signal
import threading
import time
import uuid
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from mfbo_platform.artifacts import ArtifactStore, convergence_svg
from mfbo_platform.config import Settings
from mfbo_platform.domain import (
    ExperimentRecord,
    ExperimentStatus,
    FailureInfo,
    MetricPoint,
    utc_now,
)
from mfbo_platform.engine import ExperimentEngine
from mfbo_platform.errors import CancelledError, EngineError, LeaseLostError, WorkerShutdownError
from mfbo_platform.logging import experiment_id_context, job_id_context
from mfbo_platform.queueing import JobQueue, ReceivedJob
from mfbo_platform.repositories import ExperimentRepository
from mfbo_platform.service import ExperimentService
from mfbo_platform.telemetry import worker_metrics
from mfbo_platform.tracking import ExperimentTracker

logger = logging.getLogger(__name__)


class LeaseRenewer:
    """Renew both ownership and message visibility; fail closed on uncertainty."""

    def __init__(self, refresh: Callable[[], None], timeout: int):
        self.refresh = refresh
        self.timeout = timeout
        self.stop_event = threading.Event()
        self.lost = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self.stop_event.wait(self.timeout / 3):
            try:
                self.refresh()
            except Exception:
                self.lost.set()
                logger.warning("queue_lease_lost")
                return

    def __enter__(self) -> LeaseRenewer:
        self.refresh()
        self.thread.start()
        return self

    def __exit__(self, *_args: Any) -> None:
        self.stop_event.set()
        self.thread.join()


class ExperimentWorker:
    def __init__(
        self,
        settings: Settings,
        repository: ExperimentRepository,
        queue: JobQueue,
        engine: ExperimentEngine,
        artifacts: ArtifactStore,
    ):
        self.settings = settings
        self.repository = repository
        self.queue = queue
        self.engine = engine
        self.artifacts = artifacts
        self.stop_event = threading.Event()
        self.metrics = worker_metrics()

    def request_shutdown(self) -> None:
        self.stop_event.set()

    def _owned(
        self, experiment_id: str, owner: str, change: Callable[[ExperimentRecord], ExperimentRecord]
    ) -> ExperimentRecord:
        def guarded(record: ExperimentRecord) -> ExperimentRecord:
            if (
                record.lease_owner != owner
                or record.status.terminal
                or record.lease_expires_at is None
                or record.lease_expires_at <= utc_now()
            ):
                raise LeaseLostError("experiment ownership expired or changed")
            return change(record)

        return self.repository.mutate(experiment_id, guarded)

    def _claim(self, experiment_id: str, owner: str) -> ExperimentRecord:
        def claim(record: ExperimentRecord) -> ExperimentRecord:
            now = utc_now()
            if record.status.terminal or (
                record.lease_expires_at and record.lease_expires_at > now
            ):
                raise LeaseLostError("experiment already owned or terminal")
            record.lease_owner = owner
            record.lease_expires_at = now + timedelta(
                seconds=self.settings.queue_visibility_timeout_seconds
            )
            record.attempts += 1
            record.started_at = now
            record.status = ExperimentStatus.RUNNING
            record.failure = None
            # Preserve interrupted progress until the first observation of a new attempt.
            return record

        return self.repository.mutate(experiment_id, claim)

    def _record_metric(
        self, experiment_id: str, owner: str, metric: MetricPoint, tracker: ExperimentTracker
    ) -> None:
        def update(record: ExperimentRecord) -> ExperimentRecord:
            if metric.iteration == 0:
                record.metric_history = []
                record.recommendation = None
            points = {point.iteration: point for point in record.metric_history}
            points[metric.iteration] = metric
            record.metric_history = sorted(points.values(), key=lambda point: point.iteration)
            record.completed_evaluations = (
                metric.completed_evaluations
                if metric.completed_evaluations is not None
                else (metric.iteration + 1 if metric.objective is not None else None)
            )
            record.current_best_objective = metric.best_objective
            record.accumulated_cost = metric.cumulative_cost
            record.progress = min(0.99, metric.cumulative_cost / record.configuration.budget)
            if (
                metric.candidate
                and metric.objective is not None
                and metric.fidelity == 1.0
                and (
                    record.recommendation is None
                    or metric.objective < record.recommendation.objective
                )
            ):
                from mfbo_platform.domain import Recommendation

                record.recommendation = Recommendation(
                    candidate=metric.candidate,
                    objective=metric.objective,
                    fidelity=1.0,
                    observed_at=metric.recorded_at,
                )
            return record

        self._owned(experiment_id, owner, update)
        self._track(experiment_id, owner, lambda: tracker.metric(metric))

    def _track(self, experiment_id: str, owner: str, operation: Callable[[], Any]) -> Any:
        try:
            return operation()
        except Exception:
            logger.warning("tracking_delivery_failed", extra={"experiment_id": experiment_id})

            def mark(record: ExperimentRecord) -> ExperimentRecord:
                if record.lease_owner == owner:
                    record.result_metadata["tracking_delivery_failed"] = True
                return record

            self.repository.mutate(experiment_id, mark)
            return None

    def process(self, job: ReceivedJob) -> None:
        experiment_id = job.message.experiment_id
        owner = str(uuid.uuid4())
        experiment_token = experiment_id_context.set(experiment_id)
        job_token = job_id_context.set(job.message.job_id)
        tracker = ExperimentTracker(
            self.settings.mlflow_tracking_uri, self.settings.mlflow_experiment_name
        )
        action: str | None = None
        started = time.perf_counter()
        try:
            record = self.repository.get(experiment_id)
            if record.status.terminal:
                action = "ack"
            else:
                record = self._claim(experiment_id, owner)

                def refresh() -> None:
                    self.queue.renew(job, self.settings.queue_visibility_timeout_seconds)
                    self._owned(
                        experiment_id,
                        owner,
                        lambda current: current.model_copy(
                            update={
                                "lease_expires_at": utc_now()
                                + timedelta(seconds=self.settings.queue_visibility_timeout_seconds)
                            }
                        ),
                    )

                with LeaseRenewer(refresh, self.settings.queue_visibility_timeout_seconds) as lease:
                    try:
                        if record.cancel_requested:
                            raise CancelledError("cancellation requested")
                        if record.attempts > self.settings.worker_max_attempts:
                            raise EngineError("worker attempt limit reached", code="attempt_limit")
                        run_id = self._track(
                            experiment_id,
                            owner,
                            lambda: tracker.start(experiment_id, record.configuration),
                        )
                        if run_id:
                            self._owned(
                                experiment_id,
                                owner,
                                lambda current: current.model_copy(
                                    update={"mlflow_run_id": run_id}
                                ),
                            )
                        if self.metrics and record.started_at:
                            self.metrics["queue"].observe(
                                max(0.0, (record.started_at - record.queued_at).total_seconds())
                            )

                        def cancelled() -> bool:
                            if lease.lost.is_set():
                                raise LeaseLostError("queue visibility renewal failed")
                            current = self.repository.get(experiment_id)
                            if (
                                current.lease_owner != owner
                                or current.lease_expires_at is None
                                or current.lease_expires_at <= utc_now()
                            ):
                                raise LeaseLostError("experiment ownership changed")
                            return current.cancel_requested

                        result = self.engine.execute(
                            experiment_id,
                            record.configuration,
                            lambda point: self._record_metric(experiment_id, owner, point, tracker),
                            cancelled,
                            self.stop_event.is_set,
                        )
                        if cancelled():
                            raise CancelledError("cancellation requested")
                        prefix = f"attempts/{owner}/"
                        artifact_uris = {
                            "configuration": self.artifacts.put_json(
                                experiment_id,
                                prefix + "configuration.json",
                                record.configuration.model_dump(mode="json"),
                            ),
                            "result": self.artifacts.put_json(
                                experiment_id,
                                prefix + "result.json",
                                result.model_dump(mode="json"),
                            ),
                            "convergence_plot": self.artifacts.put_bytes(
                                experiment_id,
                                prefix + "convergence.svg",
                                convergence_svg(
                                    [(m.cumulative_cost, m.best_objective) for m in result.metrics]
                                ),
                            ),
                        }
                        duration = time.perf_counter() - started

                        def complete(current: ExperimentRecord) -> ExperimentRecord:
                            if current.cancel_requested:
                                raise CancelledError("cancellation requested")
                            current.status = ExperimentStatus.COMPLETED
                            current.progress = 1.0
                            current.completed_at = utc_now()
                            current.recommendation = result.recommendation
                            current.result_metadata.update(result.metadata)
                            current.result_metadata.update(
                                {"artifacts": artifact_uris, "runtime_seconds": duration}
                            )
                            return current

                        self._owned(experiment_id, owner, complete)
                        action = "ack"
                        self._track(
                            experiment_id,
                            owner,
                            lambda: tracker.finish(
                                status="completed",
                                summary={
                                    **result.metadata,
                                    "runtime_seconds": duration,
                                    "artifacts": artifact_uris,
                                },
                                metrics=result.metrics,
                            ),
                        )
                        if self.metrics:
                            self.metrics["jobs"].labels("completed").inc()
                            self.metrics["duration"].observe(duration)
                        logger.info(
                            "experiment_completed",
                            extra={
                                "status": "completed",
                                "duration_ms": duration * 1000,
                                "strategy": record.configuration.strategy,
                                "worker": self.settings.worker_id,
                            },
                        )
                    except LeaseLostError:
                        raise
                    except Exception as exc:
                        if lease.lost.is_set():
                            raise LeaseLostError("lease lost during execution") from exc
                        retry = isinstance(exc, WorkerShutdownError) or (
                            isinstance(exc, EngineError)
                            and exc.retryable
                            and record.attempts < self.settings.worker_max_attempts
                        )
                        status = (
                            ExperimentStatus.CANCELLED
                            if isinstance(exc, CancelledError)
                            else (ExperimentStatus.QUEUED if retry else ExperimentStatus.FAILED)
                        )

                        failure_code = getattr(exc, "code", "worker_error")
                        failure_message = (
                            str(exc)
                            if isinstance(exc, EngineError)
                            else "experiment execution failed"
                        )

                        def finish(current: ExperimentRecord) -> ExperimentRecord:
                            current.status = status
                            current.lease_expires_at = None
                            current.completed_at = utc_now() if status.terminal else None
                            if status == ExperimentStatus.FAILED:
                                current.failure = FailureInfo(
                                    code=failure_code,
                                    message=failure_message,
                                    retryable=False,
                                    attempts=current.attempts,
                                )
                            return current

                        self._owned(experiment_id, owner, finish)
                        action = "abandon" if retry else "ack"
                        self._track(
                            experiment_id,
                            owner,
                            lambda: tracker.finish(status=status.value, summary={}, metrics=[]),
                        )
                        if self.metrics:
                            self.metrics["jobs"].labels(status.value).inc()
        except LeaseLostError:
            logger.warning("experiment_ownership_lost")
        except Exception:
            logger.exception("worker_delivery_failed")
        finally:
            tracker.close()
            try:
                if action == "ack":
                    self.queue.acknowledge(job)
                elif action == "abandon":
                    self.queue.abandon(job)
            except Exception:
                logger.warning("queue_settlement_failed")
            experiment_id_context.reset(experiment_token)
            job_id_context.reset(job_token)

    def run_once(self, wait_seconds: int = 0) -> bool:
        job = self.queue.receive(wait_seconds)
        if job is None:
            return False
        self.process(job)
        return True

    def run_forever(self) -> None:
        logger.info("worker_started", extra={"worker": self.settings.worker_id})
        reconciled = 0.0
        while not self.stop_event.is_set():
            try:
                if time.monotonic() - reconciled > 30:
                    ExperimentService(self.repository, self.queue).reconcile_pending()
                    reconciled = time.monotonic()
                if self.run_once(self.settings.worker_poll_seconds):
                    continue
            except Exception:
                logger.exception("worker_poll_failed")
            self.stop_event.wait(self.settings.worker_poll_seconds)
        logger.info("worker_stopped", extra={"worker": self.settings.worker_id})


def install_signal_handlers(worker: ExperimentWorker) -> None:
    def stop(_signum: int, _frame: Any) -> None:
        worker.request_shutdown()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
