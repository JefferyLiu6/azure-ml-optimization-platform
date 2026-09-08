from __future__ import annotations

from typing import Any

from mfbo_platform.artifacts import ArtifactStore, AzureBlobArtifactStore, LocalArtifactStore
from mfbo_platform.config import Settings
from mfbo_platform.engine import DemoEngine, ExperimentEngine
from mfbo_platform.queueing import AzureStorageJobQueue, InMemoryJobQueue, JobQueue
from mfbo_platform.repositories import (
    AzureBlobExperimentRepository,
    ExperimentRepository,
    FilesystemExperimentRepository,
)


def _credential(settings: Settings) -> Any:
    from azure.identity import DefaultAzureCredential

    return DefaultAzureCredential()


def _blob_service(settings: Settings) -> Any:
    from azure.storage.blob import BlobServiceClient

    if settings.azure_storage_connection_string:
        return BlobServiceClient.from_connection_string(
            settings.azure_storage_connection_string.get_secret_value()
        )
    if not settings.azure_storage_account_url:
        raise ValueError("MFBO_AZURE_STORAGE_ACCOUNT_URL is required")
    return BlobServiceClient(settings.azure_storage_account_url, credential=_credential(settings))


def repository_from_settings(settings: Settings) -> ExperimentRepository:
    if settings.repository_backend == "filesystem":
        return FilesystemExperimentRepository(settings.state_path)
    return AzureBlobExperimentRepository(
        _blob_service(settings).get_container_client(settings.azure_state_container)
    )


def artifacts_from_settings(settings: Settings) -> ArtifactStore:
    if settings.artifact_backend == "filesystem":
        return LocalArtifactStore(settings.artifact_path)
    return AzureBlobArtifactStore(
        _blob_service(settings).get_container_client(settings.azure_artifact_container)
    )


def queue_from_settings(settings: Settings) -> JobQueue:
    if settings.queue_backend == "memory":
        return InMemoryJobQueue()
    from azure.storage.queue import QueueClient

    if settings.azure_storage_connection_string:
        client = QueueClient.from_connection_string(
            settings.azure_storage_connection_string.get_secret_value(),
            queue_name=settings.azure_queue_name,
        )
    else:
        if not settings.azure_storage_account_url:
            raise ValueError("MFBO_AZURE_STORAGE_ACCOUNT_URL is required")
        queue_url = settings.azure_storage_account_url.replace(".blob.", ".queue.")
        client = QueueClient(
            account_url=queue_url,
            queue_name=settings.azure_queue_name,
            credential=_credential(settings),
        )
    return AzureStorageJobQueue(client, settings.queue_visibility_timeout_seconds)


def engine_from_settings(settings: Settings) -> ExperimentEngine:
    if settings.environment == "production" and not settings.allow_demo_engine:
        raise ValueError("the demo engine is disabled in production")
    return DemoEngine()
