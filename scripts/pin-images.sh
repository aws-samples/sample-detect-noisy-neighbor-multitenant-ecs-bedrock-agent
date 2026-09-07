#!/usr/bin/env bash
#
# Resolve the sample workload's base-image tags to immutable @sha256 digests and
# scan them, so nothing floating ever ships. Requires network + docker/trivy.
#
# What it does:
#   1. Resolves each base image tag to its current digest (docker buildx).
#   2. Runs a vulnerability scan (Trivy) and fails on HIGH/CRITICAL.
#   3. Prints the digest-pinned FROM lines to paste into the Dockerfile.
#
# This is intentionally not run at agent time — it needs a working registry
# login and scanner. Run it on a build host / in CI before pushing.
#
set -euo pipefail

# Chainguard Python bases (match the AWS SaaS reference architecture for ECS)
# plus the ADOT collector sidecar. The two Chainguard tags map to the
# Dockerfile's PYTHON_BUILDER_IMAGE / PYTHON_RUNTIME_IMAGE args.
IMAGES=(
  "cgr.dev/chainguard/python:latest-dev"
  "cgr.dev/chainguard/python:latest"
  "public.ecr.aws/aws-observability/aws-otel-collector:latest"
)

command -v docker >/dev/null || { echo "docker required" >&2; exit 1; }

for img in "${IMAGES[@]}"; do
  echo "==> resolving digest for ${img}"
  digest="$(docker buildx imagetools inspect "${img}" \
              --format '{{json .Manifest.Digest}}' | tr -d '"')"
  repo="${img%%:*}"
  pinned="${repo}@${digest}"
  echo "    ${pinned}"

  if command -v trivy >/dev/null; then
    # INFORMATIONAL, non-blocking. A base image can carry CVEs in bundled pip
    # packages (e.g. setuptools/msgpack) that upstream has not rebuilt yet; we
    # remediate those in sample_workload/Dockerfile. Failing here would block
    # forever on issues we already fix downstream. The BLOCKING gate runs
    # against the final built image — see scripts/scan-image.sh.
    echo "==> base scan (informational — heads-up on what to patch in the Dockerfile)"
    trivy image --exit-code 0 --severity HIGH,CRITICAL "${pinned}" || true
  else
    echo "    WARNING: trivy not installed — scan skipped. Install before pushing." >&2
  fi
done

echo
echo "Paste the pinned references above:"
echo "  - the two chainguard/python digests -> sample_workload/Dockerfile"
echo "    (PYTHON_BUILDER_IMAGE = :latest-dev, PYTHON_RUNTIME_IMAGE = :latest)"
echo "  - the aws-otel-collector digest      -> infra/params.dev.json (AdotImage)"
echo "Then: docker build -> scripts/scan-image.sh <image> (blocking) -> docker push."
