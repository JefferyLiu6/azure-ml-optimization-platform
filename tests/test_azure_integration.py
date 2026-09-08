from __future__ import annotations

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from mfbo_platform.domain import ExperimentConfig, ExperimentRecord
from mfbo_platform.repositories import AzureBlobExperimentRepository


@pytest.mark.integration
def test_real_blob_etag_conflict_retries_without_lost_update(valid_payload):
    connection = os.environ.get("MFBO_TEST_AZURITE")
    if not connection:
        pytest.skip("set MFBO_TEST_AZURITE to exercise the real Blob SDK against Azurite")
    from azure.storage.blob import BlobServiceClient

    client = BlobServiceClient.from_connection_string(connection)
    container = client.get_container_client(f"mfbo-test-{uuid.uuid4().hex}")
    try:
        repository = AzureBlobExperimentRepository(container)
        repository.create(
            ExperimentRecord(
                experiment_id="test",
                job_id="job",
                status="queued",
                configuration=ExperimentConfig(**valid_payload),
            )
        )
        read = threading.Event()
        proceed = threading.Event()
        calls = 0

        def paused_increment(record):
            nonlocal calls
            calls += 1
            if calls == 1:
                read.set()
                assert proceed.wait(10)
            record.attempts += 1
            return record

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(repository.mutate, "test", paused_increment)
            assert read.wait(10)
            repository.mutate("test", lambda r: r.model_copy(update={"attempts": r.attempts + 1}))
            proceed.set()
            future.result(timeout=10)
        assert calls == 2
        assert repository.get("test").attempts == 2
    finally:
        container.delete_container()
        client.close()
