# Deployment Guide — Noisy-Neighbor AI Agent

End-to-end steps to deploy and validate this solution in an AWS account, with
the **purpose** of each step. Every command assumes you run it from the
the repository root directory unless stated otherwise.

> Deploy to a **sandbox / non-production** account first. In `prod` the agent
> only *proposes* remediations (SNS approval); in `dev` it scales services
> automatically. Choose the `Environment` parameter deliberately.

---

## 0. Prerequisites

| Requirement | Why it is needed |
|---|---|
| AWS account + credentials (`aws sts get-caller-identity` works) | All resources are created here. Use least-privilege admin for the bootstrap, not long-lived keys. |
| AWS CLI v2, Docker (with buildx), Python 3.11+ | CLI deploys the stack; Docker builds the sample image; Python packages the Lambda and runs helper scripts. |
| Trivy (image scanner) | Fails the build on HIGH/CRITICAL CVEs before anything is pushed. Enforces the "latest patched images" requirement. |
| Amazon Bedrock model access enabled for the Claude model in your Region | The agent cannot invoke the model without explicit model access being granted in the Bedrock console. |
| An existing VPC with 2+ private and 2+ public subnets across AZs | The stack does **not** create networking; it consumes yours. Private subnets run the ECS tasks; public subnets host the internal ALB. |
| Amazon Managed Service for Prometheus + Bedrock available in the Region | The workload fails to attribute load without AMP; the agent cannot reason without Bedrock. Confirm both before starting. |

**Region/account safety check** — run first so you know exactly where you are deploying:

```bash
aws sts get-caller-identity          # confirm account id + principal
aws configure get region             # confirm target region
```

---

## Phase 0.5 — Bootstrap prerequisites (sandbox only)

Skip this phase if you already have a suitable VPC (2+ private and 2+ public
subnets with egress), an ECR repository, and an artifact S3 bucket.

### Step 0.5.1 — Deploy the bootstrap stack
```bash
aws cloudformation deploy \
  --template-file infra/bootstrap.yaml \
  --stack-name noisy-neighbor-bootstrap \
  --capabilities CAPABILITY_IAM
```
**Purpose:** creates every prerequisite the main stack consumes but does not
create: a VPC with 2 public + 2 private subnets across 2 AZs, an Internet
Gateway, a **NAT gateway** (so private-subnet ECS tasks can pull images and
reach AMP/Logs), an ECR repository for the workload image, and a versioned,
encrypted, TLS-only S3 bucket for the Lambda zip. One NAT gateway is used to
keep sandbox cost down (single-AZ dependency; add a second for production HA).

### Step 0.5.2 — Read the outputs
```bash
aws cloudformation describe-stacks --stack-name noisy-neighbor-bootstrap \
  --query 'Stacks[0].Outputs' --output table
```
**Purpose:** the outputs map 1:1 to `infra/params.dev.json`:

| Output | Fills param |
|---|---|
| `VpcId` | `VpcId` |
| `PrivateSubnetIds` | `PrivateSubnetIds` |
| `PublicSubnetIds` | `PublicSubnetIds` |
| `EcrRepositoryUri` | base of `AppImage` (append `@sha256:<digest>` after push) |
| `ArtifactBucketName` | `LambdaCodeBucket` |

> Not creatable in CloudFormation: **Bedrock model access** must be enabled once
> in the Bedrock console for the Claude model in your Region (see Prerequisites).

---

## Phase 1 — Base images (supply-chain hardening)

### Step 1.1 — Resolve base images to digests and scan them
```bash
scripts/pin-images.sh
```
**Purpose:** turns floating tags (`public.ecr.aws/amazonlinux/amazonlinux:2023`,
`aws-otel-collector:latest`) into immutable `@sha256:...` digests so the exact
bytes can never change under you. Both bases come from Amazon ECR Public;
Amazon Linux 2023 is AWS-owned and continuously patched (the Dockerfile also
runs `dnf update`). The base scan here is **informational**; the blocking gate
runs against the final built image in Step 2.4. Paste the `amazonlinux:2023`
digest into `sample_workload/Dockerfile` (`BASE_IMAGE`) and the ADOT digest into
`infra/params.dev.json` (`AdotImage`).

---

## Phase 2 — Build and publish the sample workload image

### Step 2.1 — Create an ECR repository
```bash
# If you ran Phase 0.5, SKIP this — use the bootstrap's EcrRepositoryUri output.
aws ecr create-repository --repository-name noisy-neighbor-sample \
  --image-scanning-configuration scanOnPush=true \
  --image-tag-mutability IMMUTABLE
```
**Purpose:** a private, scan-on-push, immutable-tag registry for the workload
image. `scanOnPush` is a second scanning layer; `IMMUTABLE` prevents a tag from
being overwritten after review. (The bootstrap stack already creates this.)

### Step 2.2 — Authenticate Docker to ECR
```bash
aws ecr get-login-password | docker login --username AWS \
  --password-stdin <ACCOUNT_ID>.dkr.ecr.<REGION>.amazonaws.com
```
**Purpose:** short-lived credential so `docker push` can write to your ECR
repo. The token expires in 12 hours — no static registry secret is stored.

### Step 2.3 — Build the image
```bash
docker build -t <ACCOUNT_ID>.dkr.ecr.<REGION>.amazonaws.com/noisy-neighbor-sample:1 \
  sample_workload
```
**Purpose:** produces the container the two tenant ECS services run. The
multi-stage, non-root Amazon Linux 2023 Dockerfile patches the OS (`dnf update`)
and pins `setuptools` to a fixed version in the app venv.

### Step 2.4 — Scan the built image (blocking gate)
```bash
scripts/scan-image.sh <ACCOUNT_ID>.dkr.ecr.<REGION>.amazonaws.com/noisy-neighbor-sample:1
```
**Purpose:** the final artifact — not just the base — must be clean. This fails
on any remaining HIGH/CRITICAL CVE or embedded secret. If it fails, bump the
offending package's floor in `sample_workload/Dockerfile` and rebuild. Do not
push an image that has not passed this gate.

### Step 2.5 — Push the image
```bash
docker push <ACCOUNT_ID>.dkr.ecr.<REGION>.amazonaws.com/noisy-neighbor-sample:1
```
**Purpose:** publishes the scanned image. Record the pushed image's **digest**
(`docker inspect` or the ECR console) — the stack requires the digest form
(`...@sha256:...`), not the `:1` tag.

---

## Phase 3 — Package the agent Lambda

### Step 3.1 — Create an artifact bucket (if you do not have one)
```bash
# If you ran Phase 0.5, SKIP this — use the bootstrap's ArtifactBucketName output.
aws s3 mb s3://<ACCOUNT_ID>-noisy-neighbor-artifacts
aws s3api put-bucket-versioning --bucket <ACCOUNT_ID>-noisy-neighbor-artifacts \
  --versioning-configuration Status=Enabled
```
**Purpose:** CloudFormation loads the Lambda code from S3. Versioning lets you
roll back to a previous code zip. (The bootstrap stack already creates a
versioned, encrypted, TLS-only bucket for this.)

### Step 3.2 — Build the deployment zip
```bash
rm -rf build && mkdir build
# Install Linux/arm64 wheels to match the Lambda runtime (Architectures: arm64,
# python3.13). Building on macOS/x86 without these flags installs the wrong
# native wheels (e.g. pydantic_core) and the function fails at import.
pip install \
  --platform manylinux2014_aarch64 \
  --implementation cp --python-version 3.13 \
  --only-binary=:all: --upgrade \
  -r lambda_invoker/requirements.txt -t build/
cp -r agent lambda_invoker build/
(cd build && zip -rqX ../agent-lambda.zip .)
```
**Purpose:** bundles the agent code, the Lambda handler, and their Python
dependencies into the single artifact Lambda expects. `agent/` and
`lambda_invoker/` sit at the zip root so the handler
`lambda_invoker.handler.handler` resolves. The `--platform`/`--python-version`
flags force manylinux aarch64 wheels so compiled deps load on Lambda; if you
switch the function to x86_64, use `manylinux2014_x86_64`.

### Step 3.3 — Upload the zip
```bash
aws s3 cp agent-lambda.zip s3://<ACCOUNT_ID>-noisy-neighbor-artifacts/agent/agent-lambda.zip
```
**Purpose:** makes the artifact available at the S3 key the stack references
(`LambdaCodeBucket` + `LambdaCodeKey`).

---

## Phase 4 — Deploy the CloudFormation stack

### Step 4.1 — Fill in the parameters
Edit `infra/params.dev.json`, replacing every `REPLACE*` value:

| Parameter | Purpose |
|---|---|
| `Environment` | `dev` = auto-scale; `prod` = SNS approval only. Governs the agent's remediation behaviour. |
| `VpcId`, `PrivateSubnetIds`, `PublicSubnetIds` | Where the ALB and ECS tasks run. Tasks in private subnets, ALB in public subnets. |
| `AlbIngressCidr` | The only CIDR allowed to reach the ALB. Never `0.0.0.0/0` (the pattern rejects that shape). |
| `CertificateArn` | ACM certificate ARN for the ALB HTTPS listener (TLS 1.2+). ALB is internal, so Route 53 / a public domain is **optional** — an ACM Private CA cert is often the simplest fit. |
| `BedrockModelId` | The Claude inference-profile the agent reasons with. |
| `AppImage` | The digest-pinned workload image from Step 2.3. |
| `AdotImage` | The digest-pinned ADOT collector image from Step 1.1. |
| `LambdaCodeBucket`, `LambdaCodeKey` | Where the Lambda zip lives (Phase 3). |
| `ApprovalEmail` | Optional; subscribes a human to the SNS proposal topic. |
| `MaxDesiredCount` | Hard ceiling the agent may scale a service to. Safety bound. |

### Step 4.2 — Validate the template
```bash
aws cloudformation validate-template --template-body file://infra/template.yaml
```
**Purpose:** catches syntax/parameter errors before a deploy attempt. (Locally
you can also run `cfn-lint infra/template.yaml` and `checkov -f infra/template.yaml`.)

### Step 4.3 — Deploy
```bash
aws cloudformation deploy \
  --template-file infra/template.yaml \
  --stack-name noisy-neighbor-dev \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides file://infra/params.dev.json
```
**Purpose:** creates every resource — KMS key, DynamoDB registry, AMP
workspace, SNS topic + DLQ, ALB + two target groups/services, ECS cluster and
task definitions, Bedrock Guardrail, the least-privilege agent Lambda, the
CloudWatch alarm, and the EventBridge rule that ties the alarm to the Lambda.
`CAPABILITY_IAM` is required because the stack creates scoped IAM roles.

### Step 4.4 — Capture the outputs
```bash
aws cloudformation describe-stacks --stack-name noisy-neighbor-dev \
  --query 'Stacks[0].Outputs' --output table
```
**Purpose:** the outputs (`ClusterName`, `AlbDnsName`, `TenantRegistryTable`,
`PrometheusEndpoint`, `ProposalTopicArn`, `AgentFunctionName`) feed the seeding,
validation, and load-generation steps below.

---

## Phase 5 — Seed the tenant registry

### Step 5.1 — Fill in the seed file
Edit `infra/seed-tenants.json`: set `cluster_name` to the `ClusterName` output
and each `service_name` to the `svc-a` / `svc-b` service names (the stack names
them `<stack>-svc-a` and `<stack>-svc-b`).

### Step 5.2 — Load the rows
```bash
python scripts/seed_registry.py \
  --table <TenantRegistryTable> --file infra/seed-tenants.json
```
**Purpose:** writes the tenant → cluster → service → tier → baseline mapping the
agent's **List Tenants** tool reads. Without this the agent has no tenant
context and refuses to act. The script refuses to write any unresolved
`REPLACE` placeholder, so a half-edited file fails safely.

---

## Phase 6 — Confirm metrics are flowing

### Step 6.1 — Check the services are running
```bash
aws ecs describe-services --cluster <ClusterName> \
  --services <stack>-svc-a <stack>-svc-b \
  --query 'services[].{name:serviceName,running:runningCount,desired:desiredCount}'
```
**Purpose:** confirms both tenant workloads are healthy before generating load;
`runningCount` should equal `desiredCount` (2 each).

### Step 6.2 — Query AMP for per-tenant metrics
Run a PromQL instant query against the `PrometheusEndpoint` (SigV4-signed — the
`awscurl` tool or the agent's own `query_metrics` path):
```
sum by (tenant_id) (rate(http_requests_total[5m]))
```
**Purpose:** proves the ADOT sidecar is remote-writing tenant-labelled metrics.
If `tenant_id` is missing here, the agent cannot attribute load — fix
instrumentation before proceeding.

---

## Phase 7 — End-to-end validation

### Step 7.1 — Generate a noisy-neighbor condition
```bash
# Target the certificate's hostname if you set up Route 53; otherwise hit the
# ALB DNS name and skip cert verification for the demo (see note).
python sample_workload/loadgen/generate_load.py \
  --url https://<alb-domain-or-alb-dns> \
  --noisy-tenant tenant-a --noisy-rps 200 \
  --quiet-tenant tenant-b --quiet-rps 10 --seconds 180
```
**Purpose:** drives disproportionate traffic at `tenant-a` so one tenant is
clearly the noisy neighbor. Run from a host with network reach to the internal
ALB. TLS notes: if the cert's domain resolves to the ALB (Route 53), clients
validate normally; if you used an ACM Private CA or are hitting the raw ALB DNS
name, the hostname won't match a public CA, so for the demo either trust the
private CA or disable verification (`curl -k`) — do this only as a manual local
step, never in shipped code. Also: the demo endpoint is I/O-bound, so it may not
push cluster CPU past the alarm threshold on its own — force the alarm in
Step 7.2 to exercise the agent.

### Step 7.2 — Watch the alarm fire and the agent run
```bash
aws logs tail /aws/lambda/noisy-neighbor-dev-agent --follow
```
**Purpose:** the CloudWatch alarm → EventBridge → Lambda chain invokes the
agent. The log shows it call List Tenants, Query Metrics, reason about the
cause, and call Take Action. Confirms the whole pipeline works.

### Step 7.3 — Verify the action
- **dev:** `describe-services` shows `tenant-a`'s `desiredCount` raised (clamped
  to `MaxDesiredCount`). **Purpose:** confirms auto-remediation.
- **prod:** a message lands on `ProposalTopicArn` (email/subscriber) and the
  service is **unchanged**. **Purpose:** confirms the human-approval guardrail.

### Step 7.4 — Validate the "stuck requests" path (optional)
Drive high latency with flat throughput (large `--work-ms`, low rps).
**Purpose:** confirms the agent chooses **alert-only** rather than scaling when
scaling would not help — the core reason this is an agent, not a static rule.

---

## Phase 8 — Teardown

### Step 8.1 — Delete the stack
```bash
aws cloudformation delete-stack --stack-name noisy-neighbor-dev
aws cloudformation wait stack-delete-complete --stack-name noisy-neighbor-dev
```
**Purpose:** removes all recurring-cost resources (ECS tasks, ALB, AMP, NAT
traffic). In `prod` the DynamoDB table has deletion protection enabled — disable
it deliberately before deleting.

### Step 8.2 — Delete the bootstrap stack (if you used Phase 0.5)
```bash
# ECR and S3 must be emptied before their stack can delete.
aws ecr batch-delete-image --repository-name noisy-neighbor-bootstrap-sample \
  --image-ids "$(aws ecr list-images --repository-name noisy-neighbor-bootstrap-sample \
    --query 'imageIds' --output json)" 2>/dev/null || true
aws s3 rm s3://noisy-neighbor-bootstrap-artifacts-<ACCOUNT> --recursive
aws cloudformation delete-stack --stack-name noisy-neighbor-bootstrap
aws cloudformation wait stack-delete-complete --stack-name noisy-neighbor-bootstrap
```
**Purpose:** removes the VPC, **NAT gateway** (the main hourly cost), ECR repo,
and artifact bucket. CloudFormation will not delete a non-empty bucket or repo,
so they are emptied first. **Confirm the account is the sandbox before running.**

> If you created the ECR repo / bucket by hand (not via Phase 0.5), delete those
> manually instead: `aws ecr delete-repository --repository-name … --force` and
> `aws s3 rb s3://… --force`.

---

## Order-of-operations summary

```
0   verify account/region
0.5 bootstrap prereqs (VPC+NAT, ECR, S3)  (sandbox only)
1   pin + scan base images                (supply chain)
2   build + push workload image           (ECR)
3   package + upload agent Lambda         (S3)
4   deploy CloudFormation stack           (all AWS resources)
5   seed tenant registry                  (agent context)
6   confirm metrics flowing               (AMP / tenant_id)
7   generate load, watch agent remediate  (end-to-end)
8   teardown                              (cost cleanup)
```

Each phase is independent once its inputs exist, so you can re-run Phase 2/3
(new image or code) and just `cloudformation deploy` again without touching the
rest.
