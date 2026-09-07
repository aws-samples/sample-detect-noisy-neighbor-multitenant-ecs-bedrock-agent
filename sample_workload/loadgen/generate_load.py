"""Load generator to simulate a noisy-neighbor condition.

Drives disproportionate traffic at one tenant's endpoint so the CloudWatch
alarm fires and the agent has a real per-tenant imbalance to attribute.

Usage:
    python generate_load.py --url http://<alb-dns> \\
        --noisy-tenant tenant-a --noisy-rps 200 --quiet-rps 10 --seconds 120

The script sends the tenant id as a header so a single ALB/target can be used
in the sample; in the real workload each tenant has its own service.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import contextlib
import time
import urllib.request


def _fire(url: str, tenant_id: str, work_ms: int) -> None:
    body = f'{{"items": 1, "work_ms": {work_ms}}}'.encode()
    req = urllib.request.Request(
        f"{url.rstrip('/')}/orders",
        data=body,
        headers={"Content-Type": "application/json", "X-Tenant-Id": tenant_id},
        method="POST",
    )
    # Best-effort: a dropped request under load is expected and uninteresting.
    with contextlib.suppress(Exception):
        urllib.request.urlopen(req, timeout=5).read()


def _run_tenant(url: str, tenant_id: str, rps: int, seconds: int, work_ms: int) -> None:
    deadline = time.time() + seconds
    interval = 1.0 / max(rps, 1)
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(rps, 64)) as pool:
        while time.time() < deadline:
            pool.submit(_fire, url, tenant_id, work_ms)
            time.sleep(interval)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="Base URL of the ALB/service")
    parser.add_argument("--noisy-tenant", default="tenant-a")
    parser.add_argument("--quiet-tenant", default="tenant-b")
    parser.add_argument("--noisy-rps", type=int, default=200)
    parser.add_argument("--quiet-rps", type=int, default=10)
    parser.add_argument("--seconds", type=int, default=120)
    parser.add_argument("--work-ms", type=int, default=30)
    args = parser.parse_args()

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(
                _run_tenant, args.url, args.noisy_tenant, args.noisy_rps, args.seconds, args.work_ms
            ),
            pool.submit(
                _run_tenant, args.url, args.quiet_tenant, args.quiet_rps, args.seconds, args.work_ms
            ),
        ]
        for f in futures:
            f.result()
    print(f"Done. {args.noisy_tenant} at {args.noisy_rps} rps, "
          f"{args.quiet_tenant} at {args.quiet_rps} rps for {args.seconds}s.")


if __name__ == "__main__":
    main()
