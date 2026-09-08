import logging
import re
import secrets
from datetime import datetime
from typing import Annotated, Any, Self, cast

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from mfbo_platform.config import Settings, get_settings
from mfbo_platform.domain import (
    ExperimentConfig,
    ExperimentRecord,
    ExperimentStatus,
    MetricPoint,
    Recommendation,
)
from mfbo_platform.errors import ConflictError, NotFoundError
from mfbo_platform.factory import queue_from_settings, repository_from_settings
from mfbo_platform.queueing import JobQueue
from mfbo_platform.repositories import ExperimentRepository
from mfbo_platform.service import ExperimentService
from mfbo_platform.telemetry import configure_azure_monitor, install_http_telemetry

logger = logging.getLogger(__name__)
IDEMPOTENCY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class CreateExperimentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    experiment_id: str
    status: ExperimentStatus
    created_at: datetime


class ExperimentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    experiment_id: str
    status: ExperimentStatus
    configuration: ExperimentConfig
    progress: float
    completed_evaluations: int | None
    attempts: int
    current_best_objective: float | None
    accumulated_cost: float
    created_at: datetime
    queued_at: datetime
    started_at: datetime | None
    updated_at: datetime
    completed_at: datetime | None
    cancel_requested: bool
    failure: dict[str, Any] | None

    @classmethod
    def from_record(cls, record: ExperimentRecord) -> Self:
        return cls.model_validate(record.model_dump(include=set(cls.model_fields)))


class MetricsResponse(BaseModel):
    experiment_id: str
    metrics: list[MetricPoint]


class RecommendationResponse(BaseModel):
    experiment_id: str
    status: ExperimentStatus
    recommendation: Recommendation | None


class ReadinessResponse(BaseModel):
    status: str
    dependencies: dict[str, str]


def create_app(
    settings: Settings | None = None,
    repository: ExperimentRepository | None = None,
    queue: JobQueue | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_azure_monitor(settings)
    repository = repository or repository_from_settings(settings)
    queue = queue or queue_from_settings(settings)
    service = ExperimentService(repository, queue)
    app = FastAPI(
        title="Azure ML Optimization Platform",
        version="0.1.0",
        description="Asynchronous optimization jobs with a reproducible random-search demo.",
    )
    app.state.settings = settings
    app.state.repository = repository
    app.state.queue = queue
    app.state.service = service
    install_http_telemetry(app)

    def get_repository() -> ExperimentRepository:
        return cast(ExperimentRepository, app.state.repository)

    def get_service() -> ExperimentService:
        return cast(ExperimentService, app.state.service)

    def authorize(x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None) -> None:
        if not settings.require_api_key:
            return
        configured = settings.api_key.get_secret_value() if settings.api_key else ""
        if not configured or not x_api_key or not secrets.compare_digest(configured, x_api_key):
            raise HTTPException(status_code=401, detail="invalid or missing API key")

    @app.exception_handler(NotFoundError)
    async def not_found_handler(_request: Any, exc: NotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc), "code": "not_found"})

    @app.exception_handler(ConflictError)
    async def conflict_handler(_request: Any, exc: ConflictError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc), "code": "conflict"})

    @app.post(
        "/experiments",
        response_model=CreateExperimentResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def create_experiment(
        configuration: ExperimentConfig,
        experiment_service: Annotated[ExperimentService, Depends(get_service)],
        _authorization: Annotated[None, Depends(authorize)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> CreateExperimentResponse:
        if idempotency_key and not IDEMPOTENCY_PATTERN.fullmatch(idempotency_key):
            raise HTTPException(status_code=400, detail="invalid Idempotency-Key")
        record = experiment_service.create(configuration, idempotency_key)
        return CreateExperimentResponse(
            experiment_id=record.experiment_id,
            status=record.status,
            created_at=record.created_at,
        )

    @app.get("/experiments/{experiment_id}", response_model=ExperimentResponse)
    def get_experiment(
        experiment_id: str,
        experiment_repository: Annotated[ExperimentRepository, Depends(get_repository)],
        _authorization: Annotated[None, Depends(authorize)],
    ) -> ExperimentResponse:
        return ExperimentResponse.from_record(experiment_repository.get(experiment_id))

    @app.get("/experiments/{experiment_id}/metrics", response_model=MetricsResponse)
    def get_metrics(
        experiment_id: str,
        experiment_repository: Annotated[ExperimentRepository, Depends(get_repository)],
        _authorization: Annotated[None, Depends(authorize)],
    ) -> MetricsResponse:
        return MetricsResponse(
            experiment_id=experiment_id,
            metrics=experiment_repository.list_metrics(experiment_id),
        )

    @app.get("/experiments/{experiment_id}/recommendation", response_model=RecommendationResponse)
    def get_recommendation(
        experiment_id: str,
        experiment_repository: Annotated[ExperimentRepository, Depends(get_repository)],
        _authorization: Annotated[None, Depends(authorize)],
    ) -> RecommendationResponse:
        record = experiment_repository.get(experiment_id)
        return RecommendationResponse(
            experiment_id=experiment_id,
            status=record.status,
            recommendation=record.recommendation,
        )

    @app.post("/experiments/{experiment_id}/cancel", response_model=ExperimentResponse)
    def cancel_experiment(
        experiment_id: str,
        experiment_service: Annotated[ExperimentService, Depends(get_service)],
        _authorization: Annotated[None, Depends(authorize)],
    ) -> ExperimentResponse:
        record = experiment_service.request_cancellation(experiment_id)
        return ExperimentResponse.from_record(record)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready", response_model=ReadinessResponse)
    def ready() -> ReadinessResponse:
        dependencies: dict[str, str] = {}
        failures = []
        for name, dependency in (("repository", repository), ("queue", queue)):
            try:
                dependency.health()
                dependencies[name] = "ok"
            except Exception:
                logger.exception("readiness_dependency_failed", extra={"status": name})
                dependencies[name] = "failed"
                failures.append(name)
        if settings.require_api_key and not settings.api_key:
            dependencies["api_key"] = "failed"
            failures.append("api_key")
        if failures:
            raise HTTPException(status_code=503, detail={"dependencies": dependencies})
        return ReadinessResponse(status="ready", dependencies=dependencies)

    return app
