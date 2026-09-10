# syntax=docker/dockerfile:1
#
# Multi-stage build for the sample workload on Amazon Linux 2023, pulled from
# Amazon ECR Public. AL2023 is AWS-owned, continuously patched, and hosted on a
# registry that satisfies the internal container-image guidelines (no external
# registries). The runtime stage runs `dnf update` and drops to a non-root user.
#
# SECURITY: pin the base by digest before pushing. The tag below is for
# readability; `scripts/pin-images.sh` resolves it to an @sha256 digest and
# `scripts/scan-image.sh` is the blocking vulnerability gate on the final image.
#
#   docker build -t noisy-neighbor-sample:local sample_workload
#
ARG BASE_IMAGE=public.ecr.aws/amazonlinux/amazonlinux:2023

# ---- builder ---------------------------------------------------------------
FROM ${BASE_IMAGE} AS builder

# Python 3.11 from the AL2023 repos; build a self-contained venv.
RUN dnf -y update \
 && dnf -y install python3.11 python3.11-pip \
 && dnf clean all

WORKDIR /app
ENV PATH="/app/venv/bin:$PATH" \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN python3.11 -m venv /app/venv
COPY requirements.txt .
# Install app deps, then pin the packaging tool to a patched floor
# (setuptools CVE-2025-47273) inside the venv.
RUN pip install -r requirements.txt \
 && pip install --upgrade "setuptools>=78.1.1"

# ---- runtime ---------------------------------------------------------------
FROM ${BASE_IMAGE} AS runtime

# Patch the OS and install only the Python runtime the venv needs.
RUN dnf -y update \
 && dnf -y install python3.11 \
 && dnf clean all \
 && rm -rf /var/cache/dnf

# Non-root, no login shell, no home writes needed.
RUN groupadd --system app && useradd --system --gid app --no-create-home app

WORKDIR /app
ENV PATH="/app/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080

COPY --from=builder --chown=app:app /app/venv /app/venv
COPY --chown=app:app app /app/app

USER app
EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=3s --retries=3 \
  CMD ["python3.11", "-c", "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8080/health'); sys.exit(0)"]

# Single worker per task — ECS scales by task count, not in-container workers.
ENTRYPOINT ["python3.11", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
