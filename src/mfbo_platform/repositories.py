from __future__ import annotations

import os
import tempfile
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator
from contextlib import suppress
from pathlib import Path
from typing import Any

from mfbo_platform.domain import ExperimentRecord, MetricPoint, utc_now
from mfbo_platform.errors import ConflictError, NotFoundError


class ExperimentRepository(ABC):
    @abstractmethod
    def create(self, record: ExperimentRecord) -> None: ...

    @abstractmethod
    def get(self, experiment_id: str) -> ExperimentRecord: ...

    @abstractmethod
    def mutate(
        self, experiment_id: str, change: Callable[[ExperimentRecord], ExperimentRecord]
    ) -> ExperimentRecord: ...

    def append_metric(self, experiment_id: str, metric: MetricPoint) -> None:
        def append(record: ExperimentRecord) -> ExperimentRecord:
            points = {point.iteration: point for point in record.metric_history}
            points[metric.iteration] = metric
            record.metric_history = sorted(points.values(), key=lambda point: point.iteration)
            return record

        self.mutate(experiment_id, append)

    def list_metrics(self, experiment_id: str) -> list[MetricPoint]:
        return self.get(experiment_id).metric_history

    @abstractmethod
    def iter_records(self) -> Iterator[ExperimentRecord]: ...

    @abstractmethod
    def health(self) -> None: ...


class FilesystemExperimentRepository(ExperimentRepository):
    """Atomic, flock-serialized JSON persistence for local and single-node deployments."""

    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _directory(self, experiment_id: str) -> Path:
        return self.root / experiment_id

    def _state_path(self, experiment_id: str) -> Path:
        return self._directory(experiment_id) / "state.json"

    def _lock_path(self, experiment_id: str) -> Path:
        return self._directory(experiment_id) / ".lock"

    def _locked(self, experiment_id: str) -> Any:
        import fcntl

        directory = self._directory(experiment_id)
        directory.mkdir(parents=True, exist_ok=True)
        handle = self._lock_path(experiment_id).open("a+")
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        return handle

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def create(self, record: ExperimentRecord) -> None:
        lock = self._locked(record.experiment_id)
        try:
            path = self._state_path(record.experiment_id)
            if path.exists():
                raise ConflictError(f"experiment {record.experiment_id} already exists")
            self._atomic_write(path, record.model_dump_json(indent=2))
        finally:
            lock.close()

    def get(self, experiment_id: str) -> ExperimentRecord:
        path = self._state_path(experiment_id)
        if not path.exists():
            raise NotFoundError(f"experiment {experiment_id} was not found")
        return ExperimentRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def mutate(
        self, experiment_id: str, change: Callable[[ExperimentRecord], ExperimentRecord]
    ) -> ExperimentRecord:
        lock = self._locked(experiment_id)
        try:
            current = self.get(experiment_id)
            expected_version = current.version
            updated = change(current.model_copy(deep=True))
            if updated.version != expected_version:
                raise ConflictError("mutation callbacks must not alter the record version")
            updated.version += 1
            updated.updated_at = utc_now()
            self._atomic_write(self._state_path(experiment_id), updated.model_dump_json(indent=2))
            return updated
        finally:
            lock.close()

    def iter_records(self) -> Iterator[ExperimentRecord]:
        for path in self.root.glob("*/state.json"):
            yield ExperimentRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def health(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        if not os.access(self.root, os.R_OK | os.W_OK):
            raise OSError(f"repository path is not readable and writable: {self.root}")


class AzureBlobExperimentRepository(ExperimentRepository):
    """Shared state repository using blob ETags for optimistic concurrency."""

    def __init__(self, container_client: Any):
        from azure.core.exceptions import ResourceExistsError

        self.container = container_client
        with suppress(ResourceExistsError):
            self.container.create_container()

    def _state_name(self, experiment_id: str) -> str:
        return f"experiments/{experiment_id}/state.json"

    def create(self, record: ExperimentRecord) -> None:
        from azure.core.exceptions import ResourceExistsError

        try:
            self.container.upload_blob(
                self._state_name(record.experiment_id), record.model_dump_json(), overwrite=False
            )
        except ResourceExistsError as exc:
            raise ConflictError(f"experiment {record.experiment_id} already exists") from exc

    def _get_with_etag(self, experiment_id: str) -> tuple[ExperimentRecord, str]:
        from azure.core.exceptions import ResourceNotFoundError

        blob = self.container.get_blob_client(self._state_name(experiment_id))
        try:
            download = blob.download_blob()
            data = download.readall()
            etag = download.properties.etag
        except ResourceNotFoundError as exc:
            raise NotFoundError(f"experiment {experiment_id} was not found") from exc
        return ExperimentRecord.model_validate_json(data), str(etag)

    def get(self, experiment_id: str) -> ExperimentRecord:
        return self._get_with_etag(experiment_id)[0]

    def mutate(
        self, experiment_id: str, change: Callable[[ExperimentRecord], ExperimentRecord]
    ) -> ExperimentRecord:
        from azure.core import MatchConditions
        from azure.core.exceptions import ResourceModifiedError

        for _ in range(5):
            current, etag = self._get_with_etag(experiment_id)
            expected_version = current.version
            updated = change(current.model_copy(deep=True))
            if updated.version != expected_version:
                raise ConflictError("mutation callbacks must not alter the record version")
            updated.version += 1
            updated.updated_at = utc_now()
            try:
                self.container.get_blob_client(self._state_name(experiment_id)).upload_blob(
                    updated.model_dump_json(),
                    overwrite=True,
                    etag=etag,
                    match_condition=MatchConditions.IfNotModified,
                )
                return updated
            except ResourceModifiedError:
                continue
        raise ConflictError(f"concurrent updates did not converge for {experiment_id}")

    def iter_records(self) -> Iterator[ExperimentRecord]:
        for item in self.container.list_blobs(name_starts_with="experiments/"):
            if item.name.endswith("/state.json"):
                yield self.get(item.name.split("/")[1])

    def health(self) -> None:
        next(iter(self.container.list_blobs(results_per_page=1).by_page()), None)


def set_fields(**fields: Any) -> Callable[[ExperimentRecord], ExperimentRecord]:
    def change(record: ExperimentRecord) -> ExperimentRecord:
        for name, value in fields.items():
            setattr(record, name, value)
        return record

    return change
