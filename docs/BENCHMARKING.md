# Measure infrastructure, not research quality

The included workloads use the public random-search demo. Results measure platform overhead
and concurrency, not Bayesian optimization quality or model-training performance.

## Local scripts

```bash
uv run python benchmarks/api_latency.py --url http://127.0.0.1:18080 \
  --requests 500 --concurrency 10 --output benchmark-results/api.json
uv run python benchmarks/worker_scaling.py --experiments 12 --evaluations 10 \
  --workers 1 2 4 --output benchmark-results/workers.json
```

The worker script uses threads, an in-memory queue, and filesystem storage. It does not
measure separate containers or AKS pods. The API script fails on HTTP errors; a failed run
does not establish a successful latency distribution.

| Measurement | Required context |
| --- | --- |
| API p50/p95 | Endpoint, warm-up, request count, concurrency, client location, and failures |
| Queue wait | Same workload and arrival pattern across comparisons |
| Throughput | Successful completions, failures, elapsed time, replicas, and node resources |
| Recovery | Failure injection, lease settings, final status, and duplicate-output checks |

Use repeated trials, report variation, and keep failed runs. Record software versions and
hardware. No measured scaling gain is claimed in this export.
