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

## 1. Container base images — Chainguard

**Decision:** the sample workload builds on Chainguard Python
(`cgr.dev/chainguard/python:latest-dev` builder → `:latest` distroless runtime),
matching the AWS SaaS reference architecture for ECS
(`aws-samples/saas-reference-architecture-ecs`, which runs on
`cgr.dev/chainguard/node` + `nginx`).

**Why:** the general-purpose `python:3.13-slim` (Debian 13.6) base carried 54
HIGH/CRITICAL OS CVEs (util-linux, perl, sqlite, ncurses, systemd) with **no
upstream fix available**. Chainguard images are continuously rebuilt against
Wolfi and carry near-zero known CVEs, resolving those at the source rather than
chasing unfixed Debian packages.

**Controls:**
- Bases pinned by digest (`scripts/pin-images.sh` resolves them).
- Final built image is gated by `scripts/scan-image.sh` (blocking on
  HIGH/CRITICAL + secrets) before push.
- Runtime is distroless, non-root (uid 65532), read-only-friendly.

---

## 2. Bundled Python packages (setuptools, msgpack)

**Finding:** base Python images shipped `setuptools 70.3.0` (CVE-2025-47273) and
`msgpack 1.1.2` (GHSA-6v7p-g79w-8964), both HIGH.

**Resolution:** the Dockerfile builder pins both to patched floors
(`setuptools>=78.1.1`, `msgpack>=1.2.1`) inside the app venv. **Fully fixed** —
enforced by `scan-image.sh` (no `--ignore-unfixed`, so a fixable CVE cannot
ship).

**Confirmed (2026-09-06):** the pinned Chainguard **runtime** base
(`cgr.dev/chainguard/python@sha256:1f37785e…`) scans **0/0** (wolfi + python-pkg).
The two HIGH findings (`setuptools 70.3.0`, `msgpack 1.1.2`) exist **only in the
`-dev` builder** image and are build-time only — they are not copied into the
runtime image (only the app venv is), and the venv pins them to patched floors.
Pinned digests:
- builder `cgr.dev/chainguard/python@sha256:b626eb5b…` (`:latest-dev`)
- runtime `cgr.dev/chainguard/python@sha256:1f37785e…` (`:latest`)

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

## 4. CloudFormation checkov skips (4)

`checkov` reports 61 pass / 0 fail / 4 skips on `infra/template.yaml`. Each skip
is inline in the template with justification:

| Check | Resource | Why skipped |
|---|---|---|
| CKV_AWS_2, CKV_AWS_103 | ALB listener | Sample uses HTTP on an **internal** ALB to stay portable (no ACM cert/domain required to deploy the demo). Production: supply an ACM cert, switch to HTTPS, `SslPolicy: ELBSecurityPolicy-TLS13-1-2-2021-06`. |
| CKV_AWS_91 | ALB | Access logging needs a dedicated S3 log bucket with its own lifecycle. Left to the adopter; enable `access_logs.s3.*` in production. |
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
