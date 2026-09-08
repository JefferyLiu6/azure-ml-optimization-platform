#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import math
import platform
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx


def percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, math.ceil(quantile * len(ordered)) - 1)
    return ordered[index]


async def main_async(args: argparse.Namespace) -> dict[str, object]:
    semaphore = asyncio.Semaphore(args.concurrency)
    latencies: list[float] = []
    headers = {"X-API-Key": args.api_key} if args.api_key else {}

    async with httpx.AsyncClient(base_url=args.url, timeout=10, headers=headers) as client:
        for _ in range(args.warmup):
            response = await client.get(args.path)
            response.raise_for_status()

        async def request() -> None:
            async with semaphore:
                started = time.perf_counter_ns()
                response = await client.get(args.path)
                elapsed = (time.perf_counter_ns() - started) / 1_000_000
                response.raise_for_status()
                latencies.append(elapsed)

        started = time.perf_counter()
        await asyncio.gather(*(request() for _ in range(args.requests)))
        duration = time.perf_counter() - started
    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "target": args.url + args.path,
        "requests": args.requests,
        "concurrency": args.concurrency,
        "duration_seconds": duration,
        "requests_per_second": args.requests / duration,
        "latency_ms": {
            "min": min(latencies),
            "mean": statistics.fmean(latencies),
            "p50": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
            "p99": percentile(latencies, 0.99),
            "max": max(latencies),
        },
        "system": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "processor": platform.processor(),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--path", default="/health")
    parser.add_argument("--requests", type=int, default=500)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--warmup", type=int, default=20)
    parser.add_argument("--api-key")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = asyncio.run(main_async(args))
    rendered = json.dumps(result, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
