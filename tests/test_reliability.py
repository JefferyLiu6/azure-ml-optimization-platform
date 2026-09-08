from __future__ import annotations

import threading
from datetime import timedelta
from unittest.mock import Mock

import pytest

from mfbo_platform.domain import ExperimentConfig, JobMessage, utc_now
from mfbo_platform.engine import DemoEngine
from mfbo_platform.errors import LeaseLostError
from mfbo_platform.queueing import InMemoryJobQueue
from mfbo_platform.service import ExperimentService
from mfbo_platform.tracking import ExperimentTracker
from mfbo_platform.worker import ExperimentWorker, LeaseRenewer


def test_ack_failure_preserves_completed_result(settings, repository, artifacts, valid_payload):
    class FailingAck(InMemoryJobQueue):
        def acknowledge(self, job):
            raise OSError("temporary queue error")

    queue = FailingAck()
    record = ExperimentService(repository, queue).create(ExperimentConfig(**valid_payload))
    worker = ExperimentWorker(settings, repository, queue, DemoEngine(), artifacts)
    assert worker.run_once()
    saved = repository.get(record.experiment_id)
    assert saved.status == "completed"
    assert saved.failure is None
    assert saved.result_metadata["artifacts"]
    # Redelivery only settles the message; it must not run the engine again.
    worker.engine = Mock()
    worker.process(
        type(
            "Delivery",
            (),
            {"message": JobMessage(job_id=record.job_id, experiment_id=record.experiment_id)},
        )()
    )
    worker.engine.execute.assert_not_called()


def test_tracking_finish_failure_preserves_success(
    settings, repository, queue, artifacts, valid_payload, monkeypatch
):
    record = ExperimentService(repository, queue).create(ExperimentConfig(**valid_payload))
    monkeypatch.setattr(
        ExperimentTracker, "finish", Mock(side_effect=OSError("tracking unavailable"))
    )
    assert ExperimentWorker(settings, repository, queue, DemoEngine(), artifacts).run_once()
    saved = repository.get(record.experiment_id)
    assert saved.status == "completed"
    assert saved.result_metadata["tracking_delivery_failed"] is True


def test_crash_before_enqueue_is_reconciled(repository, valid_payload):
    class CrashingQueue(InMemoryJobQueue):
        def enqueue(self, message):
            raise KeyboardInterrupt("API process stopped")

    service = ExperimentService(repository, CrashingQueue())
    with pytest.raises(KeyboardInterrupt):
        service.create(ExperimentConfig(**valid_payload), "crash-key")
    queue = InMemoryJobQueue()
    recovered = ExperimentService(repository, queue)
    assert recovered.reconcile_pending() == 1
    assert recovered.reconcile_pending() == 0
    assert queue.receive(0) is not None
    assert recovered.create(ExperimentConfig(**valid_payload), "crash-key").dispatched_at


def test_enqueue_outage_retains_dispatch_intent(repository, valid_payload):
    queue = InMemoryJobQueue()
    queue.enqueue = Mock(side_effect=OSError("offline"))
    record = ExperimentService(repository, queue).create(ExperimentConfig(**valid_payload))
    assert record.status == "queued"
    assert record.dispatched_at is None


def test_takeover_fences_stale_metrics(settings, repository, queue, artifacts, valid_payload):
    record = ExperimentService(repository, queue).create(ExperimentConfig(**valid_payload))
    worker = ExperimentWorker(settings, repository, queue, DemoEngine(), artifacts)
    worker._claim(record.experiment_id, "first")
    with pytest.raises(LeaseLostError):
        worker._claim(record.experiment_id, "duplicate")
    repository.mutate(
        record.experiment_id,
        lambda r: r.model_copy(update={"lease_expires_at": utc_now() - timedelta(seconds=1)}),
    )
    worker._claim(record.experiment_id, "second")
    result = DemoEngine().execute(
        "test", record.configuration, lambda m: None, lambda: False, lambda: False
    )
    with pytest.raises(LeaseLostError):
        worker._record_metric(
            record.experiment_id, "first", result.metrics[0], ExperimentTracker(None, "test")
        )
    assert repository.list_metrics(record.experiment_id) == []
    assert repository.get(record.experiment_id).lease_owner == "second"


def test_lease_renews_immediately_and_reports_failure():
    called = threading.Event()
    calls = 0

    def refresh():
        nonlocal calls
        calls += 1
        if calls > 1:
            called.set()
            raise OSError("lease lost")

    with LeaseRenewer(refresh, 0.03) as lease:
        assert calls >= 1
        assert called.wait(1)
        assert lease.lost.wait(1)


def test_cancel_during_artifact_upload_wins(settings, repository, queue, artifacts, valid_payload):
    service = ExperimentService(repository, queue)
    record = service.create(ExperimentConfig(**valid_payload))
    original = artifacts.put_json

    def cancel_then_upload(*args):
        service.request_cancellation(record.experiment_id)
        return original(*args)

    artifacts.put_json = cancel_then_upload
    ExperimentWorker(settings, repository, queue, DemoEngine(), artifacts).run_once()
    assert repository.get(record.experiment_id).status == "cancelled"
