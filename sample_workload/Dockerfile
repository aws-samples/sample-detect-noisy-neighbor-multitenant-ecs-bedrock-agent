# syntax=docker/dockerfile:1
#
# Multi-stage build for the sample workload, on Chainguard Python bases —
# matching the AWS SaaS reference architecture for ECS
# (aws-samples/saas-reference-architecture-ecs), which runs its services on
# cgr.dev/chainguard/* images for their continuously-rebuilt, near-zero-CVE
# property.
#
#   - builder: cgr.dev/chainguard/python:latest-dev  (has pip + shell)
#   - runtime: cgr.dev/chainguard/python:latest      (minimal, distroless,
#              no shell/pip, runs as nonroot uid 65532)
#
# SECURITY: pin both bases by digest before pushing. The tags below are for
# readability; `scripts/pin-images.sh` resolves them to @sha256 digests and
# `scripts/scan-image.sh` is the blocking gate on the final image.
#
#   docker build -t noisy-neighbour-sample:local sample_workload
#
ARG PYTHON_BUILDER_IMAGE=cgr.dev/chainguard/python@sha256:b626eb5bcedda38d96dc1415d2967c007d1ea95b2d72a682c3e5ccecd222641d
ARG PYTHON_RUNTIME_IMAGE=cgr.dev/chainguard/python@sha256:1f37785e5cdb70151f36aaa15e1e3cef4571424dbefbf4b0d8a9222535cb13ff

# ---- builder ---------------------------------------------------------------
FROM ${PYTHON_BUILDER_IMAGE} AS builder

WORKDIR /app
ENV PATH="/app/venv/bin:$PATH" \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Build into a self-contained venv we copy into the distroless runtime.
RUN python -m venv /app/venv
COPY requirements.txt .
# Install app deps, then defensively pin build/packaging tools to patched
# floors (setuptools CVE-2025-47273; msgpack advisory) inside the venv.
RUN pip install -r requirements.txt \
 && pip install --upgrade "setuptools>=78.1.1" "msgpack>=1.2.1"

# ---- runtime ---------------------------------------------------------------
FROM ${PYTHON_RUNTIME_IMAGE} AS runtime

WORKDIR /app
ENV PATH="/app/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080

# Chainguard default user is 'nonroot' (uid 65532); no USER/adduser needed.
COPY --from=builder --chown=nonroot:nonroot /app/venv /app/venv
COPY --chown=nonroot:nonroot app /app/app

EXPOSE 8080

# Distroless has no shell — exec form, and probe via the venv's python.
HEALTHCHECK --interval=15s --timeout=3s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8080/health'); sys.exit(0)"]

# Single worker per task — ECS scales by task count, not in-container workers.
ENTRYPOINT ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
