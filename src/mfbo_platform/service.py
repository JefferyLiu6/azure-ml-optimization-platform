from __future__ import annotations

import hashlib
import json
import logging
import uuid

from mfbo_platform.domain import (
    ExperimentConfig,
    ExperimentRecord,
    ExperimentStatus,
    JobMessage,
    utc_now,
)
from mfbo_platform.errors import ConflictError
from mfbo_platform.queueing import JobQueue
from mfbo_platform.repositories import ExperimentRepository

IDEMPOTENCY_NAMESPACE = uuid.UUID("aa985b79-bc2c-4780-bdf8-01c5b1953e28")
logger = logging.getLogger(__name__)


class ExperimentService:
    def __init__(self, repository: ExperimentRepository, queue: JobQueue):
        self.repository = repository
        self.queue = queue

    def create(
        self, configuration: ExperimentConfig, idempotency_key: str | None = None
    ) -> ExperimentRecord:
        canonical = json.dumps(
            configuration.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        )
        fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        experiment_id = (
            str(uuid.uuid5(IDEMPOTENCY_NAMESPACE, idempotency_key))
            if idempotency_key
            else str(uuid.uuid4())
        )
        job_id = str(uuid.uuid4())
        record = ExperimentRecord(
            experiment_id=experiment_id,
            job_id=job_id,
            status=ExperimentStatus.QUEUED,
            configuration=configuration,
            result_metadata={"request_fingerprint": fingerprint},
        )
        try:
            self.repository.create(record)
        except ConflictError:
            existing = self.repository.get(experiment_id)
            if existing.result_metadata.get("request_fingerprint") != fingerprint:
                raise ConflictError(
                    "idempotency key was already used with a different request"
                ) from None
            self.dispatch(existing)
            return self.repository.get(experiment_id)
        self.dispatch(record)
        return self.repository.get(experiment_id)

    def dispatch(self, record: ExperimentRecord) -> bool:
        """Persist dispatch intent until send succeeds; duplicates require worker fencing."""
        if record.dispatched_at or record.status.terminal:
            return False
        try:
            self.queue.enqueue(JobMessage(job_id=record.job_id, experiment_id=record.experiment_id))
            self.repository.mutate(
                record.experiment_id,
                lambda current: current.model_copy(update={"dispatched_at": utc_now()}),
            )
        except Exception:
            logger.warning("dispatch_pending", extra={"experiment_id": record.experiment_id})
            return False
        return True

    def reconcile_pending(self) -> int:
        return sum(self.dispatch(record) for record in self.repository.iter_records())

    def request_cancellation(self, experiment_id: str) -> ExperimentRecord:
        def cancel(record: ExperimentRecord) -> ExperimentRecord:
            if record.status.terminal:
                return record
            record.cancel_requested = True
            record.status = ExperimentStatus.CANCELLING
            return record

        return self.repository.mutate(experiment_id, cancel)
