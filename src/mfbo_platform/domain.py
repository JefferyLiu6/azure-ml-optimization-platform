from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


class ExperimentStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    FAILED = "failed"

    @property
    def terminal(self) -> bool:
        return self in {self.CANCELLED, self.COMPLETED, self.FAILED}


BenchmarkName = Literal["hartmann6"]
StrategyName = Literal["random"]


class ExperimentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    benchmark: BenchmarkName
    budget: float = Field(ge=10, le=1_000_000)
    strategy: StrategyName = "random"
    fidelities: list[float] = Field(min_length=2, max_length=5)
    seed: int = Field(ge=0, le=2**32 - 1)
    max_iterations: int = Field(default=100, ge=1, le=2_000)
    tags: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_fidelities(self) -> ExperimentConfig:
        if any(not 0 < value <= 1 for value in self.fidelities):
            raise ValueError("fidelities must be in the interval (0, 1]")
        if self.fidelities != sorted(set(self.fidelities)):
            raise ValueError("fidelities must be unique and strictly increasing")
        if self.fidelities[-1] != 1.0:
            raise ValueError("the highest fidelity must be 1.0")
        if len(self.tags) > 20 or any(len(k) > 64 or len(v) > 256 for k, v in self.tags.items()):
            raise ValueError("tags are limited to 20 entries of 64/256 characters")
        return self


class FailureInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    retryable: bool
    attempts: int = Field(ge=1)


class Recommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate: list[float]
    objective: float
    fidelity: float = Field(gt=0, le=1)
    observed_at: datetime


class MetricPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    iteration: int = Field(ge=0)
    objective: float | None
    best_objective: float
    cumulative_cost: float = Field(ge=0)
    regret: float | None = Field(default=None, ge=0)
    fidelity: float = Field(gt=0, le=1)
    strategy: str
    candidate: list[float] | None = None
    completed_evaluations: int | None = Field(default=None, ge=0)
    recorded_at: datetime = Field(default_factory=utc_now)


class ExperimentRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    experiment_id: str
    job_id: str
    status: ExperimentStatus
    configuration: ExperimentConfig
    progress: float = Field(default=0, ge=0, le=1)
    completed_evaluations: int | None = Field(default=0, ge=0)
    current_best_objective: float | None = None
    accumulated_cost: float = Field(default=0, ge=0)
    recommendation: Recommendation | None = None
    created_at: datetime = Field(default_factory=utc_now)
    queued_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    updated_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None
    cancel_requested: bool = False
    failure: FailureInfo | None = None
    result_metadata: dict[str, Any] = Field(default_factory=dict)
    mlflow_run_id: str | None = None
    version: int = Field(default=1, ge=1)
    dispatched_at: datetime | None = None
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    attempts: int = 0
    metric_history: list[MetricPoint] = Field(default_factory=list)


class EngineResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metrics: list[MetricPoint]
    recommendation: Recommendation
    metadata: dict[str, Any] = Field(default_factory=dict)


class JobMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    experiment_id: str
    enqueued_at: datetime = Field(default_factory=utc_now)
