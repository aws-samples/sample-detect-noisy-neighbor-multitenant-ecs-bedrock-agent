#!/usr/bin/env bash
#
# Blocking vulnerability gate for the FINAL built workload image — the artifact
# that actually ships to ECR/ECS. Run after `docker build`, before `docker push`.
#
# This complements scripts/pin-images.sh (which resolves/scans the base image).
# Base images can carry CVEs in bundled pip packages that upstream has not yet
# rebuilt; the Dockerfile patches those (setuptools/msgpack). This scan proves
# the patched result is clean and fails the build on any remaining HIGH/CRITICAL.
#
# Usage:
#   scripts/scan-image.sh <image-ref>
# Example:
#   scripts/scan-image.sh noisy-neighbor-sample:local
#
set -euo pipefail

IMAGE="${1:?usage: scan-image.sh <image-ref>}"

command -v trivy >/dev/null || { echo "trivy required" >&2; exit 1; }

echo "==> scanning built image ${IMAGE} (FAIL on HIGH,CRITICAL)"
# No --ignore-unfixed: if a HIGH/CRITICAL has a fix, we must apply it (bump the
# floor in the Dockerfile) rather than ship it.
trivy image --exit-code 1 --severity HIGH,CRITICAL "${IMAGE}"

echo "==> secret scan (FAIL on any finding)"
trivy image --exit-code 1 --scanners secret "${IMAGE}"

echo "OK: ${IMAGE} passed the vulnerability and secret gates."
