"""Sample two-tenant workload.

A minimal FastAPI service that stands in for a per-tenant microservice on the
shared ECS cluster. Each running task is pinned to one tenant via the
``TENANT_ID`` environment variable (the IaC stack runs one service per tenant,
matching the tenant registry's ``tenant_id -> service_name`` mapping).

The service exposes:

- ``GET  /health``   liveness/readiness probe.
- ``POST /orders``   simulated work; sleeps to model request duration.
- ``GET  /metrics``  Prometheus exposition, scraped by the ADOT collector.

Every metric carries a ``tenant_id`` label so the agent can attribute load per
tenant with PromQL. High-cardinality labels (user id, order id) are
deliberately never used as metric labels.
"""

from __future__ import annotations

import os
import time

from fastapi import FastAPI, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)
from pydantic import BaseModel

# One tenant per task. Defaults keep local runs working without env wiring.
TENANT_ID = os.environ.get("TENANT_ID", "tenant-local")
SERVICE_NAME = os.environ.get("SERVICE_NAME", "svc-local")

# A per-process registry keeps the exposition clean (no default GC/process
# collectors) which makes the sample's PromQL examples predictable.
registry = CollectorRegistry()

REQUESTS = Counter(
    "http_requests_total",
    "Total HTTP requests handled.",
    labelnames=("tenant_id", "service", "endpoint", "status"),
    registry=registry,
)
LATENCY = Histogram(
    "http_request_duration_seconds",
    "Request duration in seconds.",
    labelnames=("tenant_id", "service", "endpoint"),
    registry=registry,
    # Buckets tuned for a sub-second QSR-style order API.
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

app = FastAPI(title="noisy-neighbor sample workload", version="1.0.0")


class OrderRequest(BaseModel):
    items: int = 1
    # Optional artificial work, capped so a caller can't hang a task.
    work_ms: int = 20


class OrderResponse(BaseModel):
    tenant_id: str
    accepted_items: int


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "tenant_id": TENANT_ID}


@app.post("/orders", response_model=OrderResponse)
def create_order(req: OrderRequest) -> OrderResponse:
    endpoint = "/orders"
    start = time.perf_counter()
    # Simulate bounded downstream work.
    work_ms = max(0, min(req.work_ms, 2000))
    time.sleep(work_ms / 1000.0)
    LATENCY.labels(TENANT_ID, SERVICE_NAME, endpoint).observe(time.perf_counter() - start)
    REQUESTS.labels(TENANT_ID, SERVICE_NAME, endpoint, "200").inc()
    return OrderResponse(tenant_id=TENANT_ID, accepted_items=max(1, req.items))


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)
