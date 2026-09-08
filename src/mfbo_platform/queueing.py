from __future__ import annotations

import json
import queue
from abc import ABC, abstractmethod
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from mfbo_platform.domain import JobMessage


@dataclass
class ReceivedJob:
    message: JobMessage
    receipt: Any
    dequeue_count: int = 1


class JobQueue(ABC):
    @abstractmethod
    def enqueue(self, message: JobMessage) -> None: ...

    @abstractmethod
    def receive(self, wait_seconds: int) -> ReceivedJob | None: ...

    @abstractmethod
    def acknowledge(self, job: ReceivedJob) -> None: ...

    @abstractmethod
    def abandon(self, job: ReceivedJob) -> None: ...

    @abstractmethod
    def renew(self, job: ReceivedJob, visibility_timeout: int) -> ReceivedJob: ...

    @abstractmethod
    def health(self) -> None: ...


class InMemoryJobQueue(JobQueue):
    def __init__(self) -> None:
        self._queue: queue.Queue[ReceivedJob] = queue.Queue()

    def enqueue(self, message: JobMessage) -> None:
        self._queue.put(ReceivedJob(message=message, receipt=None))

    def receive(self, wait_seconds: int) -> ReceivedJob | None:
        try:
            job = self._queue.get(timeout=wait_seconds)
            job.dequeue_count += int(job.receipt is not None)
            job.receipt = object()
            return job
        except queue.Empty:
            return None

    def acknowledge(self, job: ReceivedJob) -> None:
        self._queue.task_done()

    def abandon(self, job: ReceivedJob) -> None:
        self._queue.task_done()
        self._queue.put(job)

    def renew(self, job: ReceivedJob, visibility_timeout: int) -> ReceivedJob:
        return job

    def health(self) -> None:
        return None


class AzureStorageJobQueue(JobQueue):
    def __init__(self, queue_client: Any, visibility_timeout: int = 120):
        from azure.core.exceptions import ResourceExistsError

        self.client = queue_client
        self.visibility_timeout = visibility_timeout
        with suppress(ResourceExistsError):
            self.client.create_queue()

    def enqueue(self, message: JobMessage) -> None:
        self.client.send_message(message.model_dump_json(), time_to_live=-1)

    def receive(self, wait_seconds: int) -> ReceivedJob | None:
        messages = self.client.receive_messages(
            messages_per_page=1,
            visibility_timeout=self.visibility_timeout,
        )
        item = next(iter(messages), None)
        if item is None:
            return None
        return ReceivedJob(
            message=JobMessage.model_validate(json.loads(item.content)),
            receipt=(item.id, item.pop_receipt),
            dequeue_count=item.dequeue_count or 1,
        )

    def acknowledge(self, job: ReceivedJob) -> None:
        message_id, pop_receipt = job.receipt
        self.client.delete_message(message_id, pop_receipt)

    def abandon(self, job: ReceivedJob) -> None:
        message_id, pop_receipt = job.receipt
        self.client.update_message(message_id, pop_receipt, visibility_timeout=0)

    def renew(self, job: ReceivedJob, visibility_timeout: int) -> ReceivedJob:
        message_id, pop_receipt = job.receipt
        updated = self.client.update_message(
            message_id, pop_receipt, visibility_timeout=visibility_timeout
        )
        job.receipt = (message_id, updated.pop_receipt)
        return job

    def health(self) -> None:
        self.client.get_queue_properties()
