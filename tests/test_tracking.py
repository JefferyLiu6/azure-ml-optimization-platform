from __future__ import annotations

import sys
from types import SimpleNamespace

from mfbo_platform.domain import ExperimentConfig, MetricPoint
from mfbo_platform.tracking import ExperimentTracker


def test_mlflow_tracks_params_metrics_artifact_and_status(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls: list[tuple[str, object]] = []
    fake = SimpleNamespace(
        set_tracking_uri=lambda value: calls.append(("uri", value)),
        set_experiment=lambda value: calls.append(("experiment", value)),
        start_run=lambda **_kwargs: SimpleNamespace(info=SimpleNamespace(run_id="run-1")),
        log_params=lambda value: calls.append(("params", value)),
        set_tags=lambda value: calls.append(("tags", value)),
        log_metrics=lambda value, **kwargs: calls.append(("metrics", (value, kwargs))),
        log_metric=lambda name, value: calls.append((name, value)),
        log_artifact=lambda value: calls.append(("artifact", value)),
        set_tag=lambda name, value: calls.append((name, value)),
        end_run=lambda **kwargs: calls.append(("end", kwargs)),
    )
    monkeypatch.setitem(sys.modules, "mlflow", fake)
    config = ExperimentConfig(
        benchmark="hartmann6",
        budget=10,
        strategy="random",
        fidelities=[0.25, 0.5, 1.0],
        seed=42,
    )
    metric = MetricPoint(
        iteration=0,
        objective=-1,
        best_objective=-1,
        cumulative_cost=1,
        regret=2,
        fidelity=1,
        strategy="random",
    )
    tracker = ExperimentTracker("http://mlflow", "mfbo")
    assert tracker.start("experiment", config) == "run-1"
    tracker.metric(metric)
    tracker.finish(status="completed", summary={"ok": True}, metrics=[metric])
    names = [name for name, _value in calls]
    assert {"params", "metrics", "artifact", "lifecycle_status", "end"} <= set(names)
