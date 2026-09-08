"""Capture real AKS workload evidence and run the existing end-to-end smoke test.

Requires localhost port-forwards to API and MLflow. Runtime API key is read into
memory from the deployed secret and passed only through the child environment.
Only allowlisted readiness summaries are written to evidence.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kubeconfig", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--api-url", default="http://127.0.0.1:18000")
    parser.add_argument("--mlflow-url", default="http://127.0.0.1:15500")
    args = parser.parse_args()

    def get(kind: str, *extra: str) -> dict:
        return json.loads(
            subprocess.check_output(
                [
                    "kubectl",
                    "--kubeconfig",
                    args.kubeconfig,
                    "-n",
                    "mfbo",
                    "get",
                    kind,
                    *extra,
                    "-o",
                    "json",
                ],
                text=True,
            )
        )

    nodes = get("nodes")["items"]
    deployments = get("deployments")["items"]
    assert nodes, "No cluster nodes found"
    assert all(
        any(c["type"] == "Ready" and c["status"] == "True" for c in n["status"]["conditions"])
        for n in nodes
    )
    assert {d["metadata"]["name"] for d in deployments} == {
        "mfbo-api",
        "mfbo-worker",
        "mfbo-mlflow",
    }
    assert all(
        d["status"].get("availableReplicas", 0) >= d["spec"]["replicas"] for d in deployments
    )
    secret = get("secret", "mfbo-runtime-secrets")
    env = {**os.environ, "MFBO_API_KEY": base64.b64decode(secret["data"]["api-key"]).decode()}
    args.output.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            sys.executable,
            str(Path(__file__).with_name("smoke_stack.py")),
            "--url",
            args.api_url,
            "--mlflow-url",
            args.mlflow_url,
            "--benchmark",
            "hartmann6",
            "--iterations",
            "2",
            "--timeout",
            "600",
            "--output",
            str(args.output / "smoke.json"),
        ],
        env=env,
        check=True,
    )
    result = {
        "checked_at": datetime.now(UTC).isoformat(),
        "nodes": [
            {
                "version": n["status"]["nodeInfo"]["kubeletVersion"],
                "architecture": n["status"]["nodeInfo"]["architecture"],
            }
            for n in nodes
        ],
        "deployments": [
            {
                "name": d["metadata"]["name"],
                "desired": d["spec"]["replicas"],
                "available": d["status"].get("availableReplicas", 0),
            }
            for d in deployments
        ],
        "end_to_end_smoke_passed": True,
    }
    (args.output / "workloads.json").write_text(json.dumps(result, indent=2) + "\n")
    print("AKS workload evidence and end-to-end smoke passed; no secrets saved.")


if __name__ == "__main__":
    main()
