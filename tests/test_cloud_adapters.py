from __future__ import annotations

import json
from types import SimpleNamespace

from mfbo_platform.domain import JobMessage
from mfbo_platform.queueing import AzureStorageJobQueue


class FakeQueueClient:
    def __init__(self) -> None:
        self.created = False
        self.sent: list[str] = []
        self.deleted: list[tuple[str, str]] = []
        self.updated: list[tuple[str, str, int]] = []
        self.items: list[SimpleNamespace] = []

    def create_queue(self) -> None:
        self.created = True

    def send_message(self, content: str, *, time_to_live: int) -> None:
        assert time_to_live == -1
        self.sent.append(content)

    def receive_messages(self, **_kwargs: object) -> list[SimpleNamespace]:
        return self.items[:1]

    def delete_message(self, message_id: str, receipt: str) -> None:
        self.deleted.append((message_id, receipt))

    def update_message(
        self, message_id: str, receipt: str, *, visibility_timeout: int
    ) -> SimpleNamespace:
        self.updated.append((message_id, receipt, visibility_timeout))
        return SimpleNamespace(pop_receipt="renewed")

    def get_queue_properties(self) -> dict[str, object]:
        return {}


def test_azure_queue_message_lifecycle() -> None:
    client = FakeQueueClient()
    adapter = AzureStorageJobQueue(client)
    message = JobMessage(job_id="job", experiment_id="experiment")
    adapter.enqueue(message)
    assert json.loads(client.sent[0])["experiment_id"] == "experiment"

    client.items = [
        SimpleNamespace(
            content=message.model_dump_json(), id="id", pop_receipt="receipt", dequeue_count=2
        )
    ]
    received = adapter.receive(1)
    assert received is not None
    assert received.dequeue_count == 2
    adapter.renew(received, 120)
    assert received.receipt == ("id", "renewed")
    adapter.abandon(received)
    adapter.acknowledge(received)
    adapter.health()
    assert client.updated[-1] == ("id", "renewed", 0)
    assert client.deleted[-1] == ("id", "renewed")
