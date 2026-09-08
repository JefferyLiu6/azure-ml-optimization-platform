from __future__ import annotations

import uvicorn

from mfbo_platform.config import get_settings
from mfbo_platform.factory import (
    artifacts_from_settings,
    engine_from_settings,
    queue_from_settings,
    repository_from_settings,
)
from mfbo_platform.logging import configure_logging
from mfbo_platform.telemetry import configure_azure_monitor, start_worker_metrics_server
from mfbo_platform.worker import ExperimentWorker, install_signal_handlers


def api() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    uvicorn.run(
        "mfbo_platform.api:create_app",
        factory=True,
        host=settings.api_host,
        port=settings.api_port,
        proxy_headers=True,
    )


def worker() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    configure_azure_monitor(settings)
    start_worker_metrics_server(settings.worker_metrics_port)
    instance = ExperimentWorker(
        settings,
        repository_from_settings(settings),
        queue_from_settings(settings),
        engine_from_settings(settings),
        artifacts_from_settings(settings),
    )
    install_signal_handlers(instance)
    instance.run_forever()
