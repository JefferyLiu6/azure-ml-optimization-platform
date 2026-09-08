# Operate the demo

## Local checks

```bash
docker compose ps
docker compose logs --tail=50 api worker
curl -f http://localhost:18080/ready
curl -f http://localhost:18080/metrics
make smoke
```

Find a job using its experiment ID in API state, logs, and MLflow tags.
Worker metrics are available on port 9000 inside the container.

## Failure checklist

| Symptom | What to check |
| --- | --- |
| Job stays queued | Worker health, queue access, pending dispatch, and available resources |
| Worker exits | Restart/OOM status and the attempt limit; wait for ownership/visibility expiry |
| Duplicate delivery | Completed jobs should only be acknowledged, not executed again |
| Tracking unavailable | Look for `tracking_delivery_failed`; recover tracking from persisted artifacts |
| Readiness fails | Storage/queue connectivity and API-key configuration |
| Cancel stays pending | Ensure a worker can consume the job and observe cancellation |

Default queue visibility is 120 seconds. Interrupted jobs restart rather than resume from
a checkpoint. An interrupted MLflow attempt can remain RUNNING and may need manual cleanup.

## Azure checks

```bash
kubectl get pods -n mfbo
kubectl logs -n mfbo deployment/mfbo-worker --tail=50
kubectl get events -n mfbo --sort-by=.lastTimestamp
```

Do not export secret objects or raw diagnostic bundles. Verify telemetry ingestion with a
known request before claiming operational monitoring. Scale workers only after checking
memory and node capacity. Stop the evaluation cluster after the test session.
