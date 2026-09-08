from __future__ import annotations

import math
import random
import time
from abc import ABC, abstractmethod
from collections.abc import Callable

from mfbo_platform.domain import (
    EngineResult,
    ExperimentConfig,
    MetricPoint,
    Recommendation,
    utc_now,
)
from mfbo_platform.errors import CancelledError, EngineError, WorkerShutdownError

MetricCallback = Callable[[MetricPoint], None]
SignalCheck = Callable[[], bool]


class ExperimentEngine(ABC):
    @abstractmethod
    def execute(
        self,
        experiment_id: str,
        config: ExperimentConfig,
        on_metric: MetricCallback,
        is_cancelled: SignalCheck,
        should_stop: SignalCheck,
    ) -> EngineResult: ...

    @abstractmethod
    def health(self) -> None: ...


class DemoEngine(ExperimentEngine):
    """Deterministic platform exerciser; intentionally not an MFBO implementation."""

    _HARTMANN_ALPHA = (1.0, 1.2, 3.0, 3.2)
    _HARTMANN_A = (
        (10.0, 3.0, 17.0, 3.5, 1.7, 8.0),
        (0.05, 10.0, 17.0, 0.1, 8.0, 14.0),
        (3.0, 3.5, 1.7, 10.0, 17.0, 8.0),
        (17.0, 8.0, 0.05, 10.0, 0.1, 14.0),
    )
    _HARTMANN_P = (
        (0.1312, 0.1696, 0.5569, 0.0124, 0.8283, 0.5886),
        (0.2329, 0.4135, 0.8307, 0.3736, 0.1004, 0.9991),
        (0.2348, 0.1451, 0.3522, 0.2883, 0.3047, 0.6650),
        (0.4047, 0.8828, 0.8732, 0.5743, 0.1091, 0.0381),
    )

    def __init__(self, *, iteration_delay_seconds: float = 0.0, fail: bool = False):
        self.iteration_delay_seconds = iteration_delay_seconds
        self.fail = fail

    @classmethod
    def _hartmann6(cls, x: list[float]) -> float:
        outer = 0.0
        for alpha, row_a, row_p in zip(
            cls._HARTMANN_ALPHA, cls._HARTMANN_A, cls._HARTMANN_P, strict=True
        ):
            inner = sum(a * (value - p) ** 2 for a, value, p in zip(row_a, x, row_p, strict=True))
            outer += alpha * math.exp(-inner)
        return -outer

    def execute(
        self,
        experiment_id: str,
        config: ExperimentConfig,
        on_metric: MetricCallback,
        is_cancelled: SignalCheck,
        should_stop: SignalCheck,
    ) -> EngineResult:
        if self.fail:
            raise EngineError("injected demo-engine failure", retryable=False, code="demo_failure")
        if config.benchmark != "hartmann6":
            raise EngineError(
                "the demo engine supports hartmann6",
                retryable=False,
                code="demo_benchmark_unsupported",
            )

        rng = random.Random(config.seed)
        best = math.inf
        best_candidate: list[float] = []
        best_fidelity = 1.0
        cumulative_cost = 0.0
        metrics: list[MetricPoint] = []
        optimum = -3.322368011415515
        iterations = min(config.max_iterations, max(1, int(config.budget)))
        for iteration in range(iterations):
            if is_cancelled():
                raise CancelledError("cancellation requested")
            if should_stop():
                raise WorkerShutdownError("worker is shutting down")
            fidelity = config.fidelities[iteration % len(config.fidelities)]
            cost = fidelity
            if cumulative_cost + cost > config.budget:
                break
            candidate = [rng.random() for _ in range(6)]
            target = self._hartmann6(candidate)
            # A deterministic fidelity bias makes lifecycle metrics realistic without
            # claiming that random search is Bayesian optimization.
            objective = target + (1.0 - fidelity) * 0.1
            cumulative_cost += cost
            if objective < best:
                best = objective
                best_candidate = candidate
                best_fidelity = fidelity
            metric = MetricPoint(
                iteration=iteration,
                objective=objective,
                best_objective=best,
                cumulative_cost=cumulative_cost,
                regret=max(0.0, best - optimum),
                fidelity=fidelity,
                strategy=config.strategy,
                candidate=candidate,
            )
            metrics.append(metric)
            on_metric(metric)
            if self.iteration_delay_seconds:
                time.sleep(self.iteration_delay_seconds)

        if not metrics:
            raise EngineError("budget was insufficient for one evaluation", code="budget_exhausted")
        recommendation = Recommendation(
            candidate=best_candidate,
            objective=best,
            fidelity=best_fidelity,
            observed_at=utc_now(),
        )
        return EngineResult(
            metrics=metrics,
            recommendation=recommendation,
            metadata={
                "engine": "deterministic_platform_demo",
                "research_engine": False,
                "warning": "Not an MFBO quality or performance result.",
            },
        )

    def health(self) -> None:
        return None
