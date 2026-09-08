"""Exercise the deployed API, asynchronous worker, persisted history and MLflow."""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path

import httpx


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:18080")
    parser.add_argument("--mlflow-url", default="http://127.0.0.1:15500")
    parser.add_argument("--strategy", choices=["random"], default="random")
    parser.add_argument("--benchmark", choices=["hartmann6"], default="hartmann6")
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    headers = {"X-API-Key": os.environ["MFBO_API_KEY"]} if os.environ.get("MFBO_API_KEY") else {}
    started = time.monotonic()
    with httpx.Client(base_url=args.url, timeout=30, headers=headers) as client:
        client.get("/ready").raise_for_status()
        config = {
            "benchmark": args.benchmark,
            "budget": 100,
            "seed": 42,
            "fidelities": [0.25, 0.5, 1.0],
            "strategy": args.strategy,
            "max_iterations": args.iterations,
        }
        submitted = client.post("/experiments", json=config)
        assert submitted.status_code == 202, submitted.text
        experiment_id = submitted.json()["experiment_id"]
        while time.monotonic() - started < args.timeout:
            state = client.get(f"/experiments/{experiment_id}").raise_for_status().json()
            if state["status"] in {"completed", "cancelled", "failed"}:
                break
            time.sleep(1)
        assert state["status"] == "completed", state
        metrics = (
            client.get(f"/experiments/{experiment_id}/metrics").raise_for_status().json()["metrics"]
        )
        recommendation = (
            client.get(f"/experiments/{experiment_id}/recommendation").raise_for_status().json()
        )
        assert metrics and recommendation["recommendation"]["candidate"]
        assert all(b["cumulative_cost"] >= a["cumulative_cost"] for a, b in pairwise(metrics))
        assert client.post("/experiments", json={**config, "budget": -1}).status_code == 422
    with httpx.Client(base_url=args.mlflow_url, timeout=30) as tracking:
        experiment = (
            tracking.get(
                "/api/2.0/mlflow/experiments/get-by-name",
                params={"experiment_name": "mfbo-platform"},
            )
            .raise_for_status()
            .json()["experiment"]
        )
        # Durable completion precedes best-effort tracking finalization. Azure
        # network latency makes that interval observable; wait within the same
        # overall timeout, without accepting a permanently RUNNING tracking run.
        runs: list[dict] = []
        while time.monotonic() - started < args.timeout:
            runs = (
                tracking.post(
                    "/api/2.0/mlflow/runs/search",
                    json={
                        "experiment_ids": [experiment["experiment_id"]],
                        "filter": f"tags.experiment_id = '{experiment_id}'",
                    },
                )
                .raise_for_status()
                .json()["runs"]
            )
            if any(run["info"]["status"] == "FINISHED" for run in runs):
                break
            time.sleep(1)
        assert any(run["info"]["status"] == "FINISHED" for run in runs), runs
    result = {
        "checked_at": datetime.now(UTC).isoformat(),
        "status": state["status"],
        "metric_points": len(metrics),
        "mlflow_finished": True,
        "elapsed_seconds": time.monotonic() - started,
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
