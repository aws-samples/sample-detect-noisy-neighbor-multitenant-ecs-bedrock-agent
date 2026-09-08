# Security Notes

Tracked security decisions and exceptions for this reference implementation.
Written for the Security Guardian review and for adopters. Each item states the
finding, why it stands, and the trigger that clears it.

## Scope reminder

The **agent** — the actual pattern deliverable — is an AWS Lambda (a zip), not a
container. Docker is used only for the **optional** sample workload that
generates per-tenant load for the demo (see the pattern prerequisites). Items
about container images therefore concern a demo prop, not the shipped agent.

---

## 1. Container base images — Amazon Linux 2023 (Amazon ECR Public)

**Decision:** the sample workload builds on Amazon Linux 2023
(`public.ecr.aws/amazonlinux/amazonlinux:2023`), a multi-stage build that
installs Python 3.11, runs `dnf update` to apply the latest patches, and drops
to a non-root user in the runtime stage.

**Why:** the base is AWS-owned, continuously patched, and hosted on Amazon ECR
Public — satisfying the container-image guideline that images come from an
approved (non-external) registry, which an earlier Chainguard (`cgr.dev`) base
did not. AL2023 keeps CVE exposure low while remaining registry-compliant.

**Controls:**
- Base pinned by digest (`scripts/pin-images.sh` resolves it).
- Final built image is gated by `scripts/scan-image.sh` (blocking on
  HIGH/CRITICAL + secrets) before push.
- Runtime patches the OS (`dnf update`), runs as a non-root user, and copies
  only the app venv from the builder stage.

---

## 2. Bundled Python package (setuptools)

**Finding:** the venv's seeded `setuptools` can carry CVE-2025-47273 (HIGH).

**Resolution:** the Dockerfile builder pins `setuptools>=78.1.1` inside the app
venv. **Fully fixed** — enforced by `scan-image.sh` (no `--ignore-unfixed`, so
a fixable CVE cannot ship). Run `scripts/scan-image.sh <image>` after building
to confirm the final image is clean before pushing.

---

## 3. ADOT collector image — 2 Go CVEs (ACCEPTED, TRACKED)

**Finding:** `public.ecr.aws/aws-observability/aws-otel-collector` (latest
release `v0.50.0`, 2026-08-31) links:
- `golang.org/x/crypto` v0.54.0 — CVE-2026-56854 (CRITICAL, fixed in 0.55.0)
- `google.golang.org/grpc` v1.83.0 — CVE-2026-84304 (HIGH, fixed in 1.83.1)

**Why it stands:**
- These are compiled into a statically-linked Go binary; they cannot be patched
  in place (only by recompiling from source).
- No AWS-published release yet bumps them — `v0.50.0` (the newest) still pins the
  vulnerable versions. So there is no clean upstream tag to re-pin to today.
- **Reachability:** the CRITICAL is in `x/crypto/ssh` (auth bypass via
  source-address restrictions). This sidecar runs **no SSH server** — it scrapes
  Prometheus and SigV4 remote-writes to AMP. The vulnerable code path is not
  reached in this deployment. Practical risk is low.

**Trigger to clear:** re-pin to the next ADOT release whose `go.mod` shows
`golang.org/x/crypto >= 0.55.0` and `google.golang.org/grpc >= 1.83.1` (watch
`aws-observability/aws-otel-collector` releases). If a strict zero-exception
gate is required sooner, rebuild the collector from source with those two
indirect deps overridden (`go get ...@fixed && go mod tidy`), accepting the
build/patch ownership that entails.

**Status:** accepted as a tracked third-party exception pending an upstream
release.

---

## 4. CloudFormation checkov skips (2)

`checkov` reports 85 pass / 0 fail / 2 skips across `infra/`. The ALB now uses
an HTTPS listener (TLS 1.2+) with a required ACM certificate, and the bootstrap
S3 buckets have access logging enabled — so those are no longer skips. The two
remaining skips are inline with justification:

| Check | Resource | Why skipped |
|---|---|---|
| CKV_AWS_91 | ALB | Access logging needs a dedicated S3 log bucket wired cross-stack from the bootstrap stack. Left to the adopter; enable `access_logs.s3.*` in production. |
| CKV_AWS_117 | Agent Lambda | Calls Bedrock/DynamoDB/ECS/SNS/AMP over public AWS endpoints. In-VPC placement needs interface endpoints per service — a deploy-time networking decision. Add `VpcConfig` + endpoints for a locked-down prod. |

---

## 5. Agent guardrails (in-code and in-stack)

- IAM is least-privilege: scoped to the tenant table ARN, the AMP workspace ARN,
  the two ECS service ARNs, the SNS topic, and Bedrock model/inference-profile
  ARNs — no `ecs:*` or resource `*`.
- `take_action` refuses any `tenant_id` not present in the registry (guards a
  jailbroken model from fabricating a target).
- `desiredCount` is clamped to `[MIN, MAX_DESIRED_COUNT]` before any ECS call.
- Production remediation never scales directly — it publishes an SNS proposal
  for human approval.
- An Amazon Bedrock Guardrail (PROMPT_ATTACK filter) is attached to the agent.
- SNS, DynamoDB, CloudWatch Logs, and the Lambda DLQ are KMS-encrypted;
  DynamoDB has PITR.
