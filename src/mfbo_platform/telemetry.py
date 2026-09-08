from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, Request, Response

from mfbo_platform.config import Settings
from mfbo_platform.logging import request_id_context

logger = logging.getLogger(__name__)

HTTP_REQUESTS: Any = None
HTTP_DURATION: Any = None
WORKER_JOBS: Any = None
WORKER_DURATION: Any = None
WORKER_QUEUE: Any = None

try:
    from prometheus_client import Counter, Histogram

    HTTP_REQUESTS = Counter(
        "mfbo_http_requests_total", "HTTP requests", ["method", "route", "status"]
    )
    HTTP_DURATION = Histogram(
        "mfbo_http_request_duration_seconds", "HTTP request duration", ["method", "route"]
    )
    WORKER_JOBS = Counter("mfbo_worker_jobs_total", "Worker jobs", ["status"])
    WORKER_DURATION = Histogram("mfbo_worker_job_duration_seconds", "Worker job duration")
    WORKER_QUEUE = Histogram("mfbo_worker_queue_duration_seconds", "Queue wait duration")
except ImportError:
    pass


def configure_azure_monitor(settings: Settings) -> None:
    if not settings.applicationinsights_connection_string:
        return
    from azure.monitor.opentelemetry import configure_azure_monitor as configure

    configure(
        connection_string=settings.applicationinsights_connection_string.get_secret_value(),
        logger_name="mfbo_platform",
    )


def install_http_telemetry(app: FastAPI) -> None:
    try:
        from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

        @app.get("/metrics", include_in_schema=False)
        def metrics() -> Response:
            return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
    except ImportError:
        pass

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))[:128]
        token = request_id_context.set(request_id)
        started = time.perf_counter()
        response: Response | None = None
        try:
            response = await call_next(request)
            return response
        finally:
            duration = time.perf_counter() - started
            route = getattr(request.scope.get("route"), "path", "unmatched")
            status = response.status_code if response else 500
            if response:
                response.headers["X-Request-ID"] = request_id
            if HTTP_REQUESTS is not None and HTTP_DURATION is not None:
                HTTP_REQUESTS.labels(request.method, route, str(status)).inc()
                HTTP_DURATION.labels(request.method, route).observe(duration)
            logger.info(
                "request_complete",
                extra={"status": status, "duration_ms": round(duration * 1000, 3)},
            )
            request_id_context.reset(token)


def worker_metrics() -> dict[str, Any]:
    if WORKER_JOBS is not None and WORKER_DURATION is not None and WORKER_QUEUE is not None:
        return {
            "jobs": WORKER_JOBS,
            "duration": WORKER_DURATION,
            "queue": WORKER_QUEUE,
        }
    return {}


def start_worker_metrics_server(port: int) -> None:
    if port <= 0 or WORKER_JOBS is None:
        return
    from prometheus_client import start_http_server

    start_http_server(port)
