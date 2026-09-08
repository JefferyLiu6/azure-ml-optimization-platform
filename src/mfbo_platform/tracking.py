from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path
from typing import Any

from mfbo_platform.domain import ExperimentConfig, MetricPoint


class ExperimentTracker:
    def __init__(self, tracking_uri: str | None, experiment_name: str):
        self.tracking_uri = tracking_uri
        self.experiment_name = experiment_name
        self._active = False
        self.run_id: str | None = None

    def start(self, experiment_id: str, config: ExperimentConfig) -> str | None:
        if not self.tracking_uri:
            return None
        import mlflow

        mlflow.set_tracking_uri(self.tracking_uri)
        mlflow.set_experiment(self.experiment_name)
        run = mlflow.start_run(run_name=experiment_id)
        self._active = True
        self.run_id = run.info.run_id
        mlflow.log_params(
            {
                "benchmark": config.benchmark,
                "strategy": config.strategy,
                "seed": config.seed,
                "budget": config.budget,
                "fidelities": json.dumps(config.fidelities),
                "max_iterations": config.max_iterations,
            }
        )
        mlflow.set_tags({**config.tags, "experiment_id": experiment_id})
        return self.run_id

    def metric(self, value: MetricPoint) -> None:
        if not self._active:
            return
        import mlflow

        metrics = {
            "best_objective": value.best_objective,
            "cumulative_cost": value.cumulative_cost,
            "fidelity": value.fidelity,
        }
        if value.objective is not None:
            metrics["objective"] = value.objective
        if value.regret is not None:
            metrics["regret"] = value.regret
        mlflow.log_metrics(metrics, step=value.iteration)

    def finish(self, *, status: str, summary: dict[str, Any], metrics: list[MetricPoint]) -> None:
        if not self._active:
            return
        import mlflow

        with tempfile.TemporaryDirectory(prefix="mfbo-mlflow-") as directory_name:
            directory = Path(directory_name)
            summary_path = directory / "summary.json"
            summary_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
            mlflow.log_artifact(str(summary_path))
            if metrics:
                mlflow.log_metric("final_best_objective", metrics[-1].best_objective)
                mlflow.log_metric("final_cumulative_cost", metrics[-1].cumulative_cost)
                count = metrics[-1].completed_evaluations
                if count is None and metrics[-1].objective is not None:
                    count = len(metrics)
                if count is not None:
                    mlflow.log_metric("completed_evaluations", count)
        mlflow.set_tag("lifecycle_status", status)
        mlflow.end_run(status="FINISHED" if status == "completed" else "FAILED")
        self._active = False

    def close(self) -> None:
        """Release MLflow's thread-local active run even after tracking outages."""
        if self._active:
            try:
                import mlflow

                mlflow.end_run(status="FAILED")
            except Exception:
                logging.getLogger(__name__).warning("tracking_close_failed")
            finally:
                self._active = False
