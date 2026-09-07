# Detect and remediate noisy-neighbor conditions in multi-tenant Amazon ECS with an AI agent on Amazon Bedrock

## Name

`sample-detect-noisy-neighbor-multitenant-ecs-bedrock-agent`

Reference implementation for the APG pattern *Detect and remediate
noisy-neighbor conditions in multi-tenant Amazon ECS using an AI agent with
Amazon Bedrock*.

## Description

In a multi-tenant SaaS platform where several tenants share one Amazon ECS
cluster, a traffic surge or a stuck workload from one tenant can consume a
disproportionate share of cluster resources and degrade every other tenant.
CloudWatch alarms can tell you that cluster CPU or request volume is high, but
not *which tenant* is responsible — so an on-call engineer has to investigate
per-tenant metrics by hand, which is slow while other tenants are degraded.

This project deploys an AI agent (built with the [Strands Agents SDK](https://strandsagents.com/)
on Amazon Bedrock) that automates that investigation and first-line
remediation:

1. A CloudWatch alarm on a shared-cluster signal breaches its threshold and
   delivers the state change to Amazon EventBridge.
2. EventBridge invokes an AWS Lambda function, which invokes the agent.
3. The agent runs three tools — **List Tenants** (DynamoDB registry),
   **Query Metrics** (Amazon Managed Service for Prometheus, PromQL scoped by
   `tenant_id`), and **Take Action** — to identify the noisy tenant, reason
   about the cause (traffic spike vs. stuck requests vs. scaling failure), and
   remediate.
4. In non-production it scales the affected ECS service directly; in production
   it publishes a structured proposal to Amazon SNS for human approval.

**What makes it different:** it treats `tenant_id` as a first-class dimension
and takes *per-tenant* operational action on shared infrastructure — combining
agentic AI, multi-tenancy, per-tenant observability, and automated remediation.

### Features

- Per-tenant load attribution from AMP via PromQL.
- Dev-vs-prod guardrail: auto-remediate in dev, SNS approval in prod.
- Least-privilege IAM, KMS encryption, a Bedrock Guardrail, and digest-pinned,
  near-zero-CVE Chainguard container images.
- A self-contained sample two-tenant workload and load generator to demonstrate
  the flow end to end.

## Visuals

```
CloudWatch Alarm (CPU / request-count breach)
        │
        ▼
EventBridge Rule ──► AWS Lambda (agent invoker)
        │
        ▼
  Bedrock Agent (Strands Agents SDK)
   ├── Tool 1: List Tenants   (DynamoDB tenant registry)
   ├── Tool 2: Query Metrics  (Amazon Managed Prometheus, PromQL by tenant_id)
   └── Tool 3: Take Action    (ECS UpdateService  |  SNS Publish)
        │
        ▼
  "tenant-a is at 73% of shared cluster CPU vs a 50% baseline.
   Cause: ~5x steady request-rate spike. Action: scaled svc-a to 8 tasks."
```

Add the rendered architecture diagram (PNG) and its editable source under
`docs/` and reference it here before publishing.

## Badges

No CI badges yet. When wired to a pipeline, add build/test and image-scan
(Trivy) status badges here.

## Installation

### Requirements

- Python 3.11+ (local development and packaging).
- AWS CLI v2 and Docker with buildx (to deploy and build the sample image).
- [Trivy](https://trivy.dev/) (blocking image vulnerability scan).
- An AWS account with Amazon Bedrock **model access enabled** for the Claude
  model in the profile's Regions, and Amazon Managed Service for Prometheus
  available in your Region.

### Local install

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
pytest -q          # runs the unit + offline end-to-end tests (no AWS calls)
```

## Usage

Full, step-by-step deployment (with the purpose of every step) is in
[`DEPLOYMENT.md`](DEPLOYMENT.md). The phases:

```
0.5 bootstrap prereqs (VPC + NAT, ECR, S3)   infra/bootstrap.yaml   (sandbox only)
1   pin + scan base images                   scripts/pin-images.sh
2   build + scan + push workload image       scripts/scan-image.sh
3   package + upload agent Lambda            (Linux/arm64 wheels)
4   deploy CloudFormation stack              infra/template.yaml + params.dev.json
5   seed tenant registry                     scripts/seed_registry.py
6   confirm per-tenant metrics in AMP
7   generate load, exercise the agent
8   teardown
```

Trigger the agent end to end (the trivial demo endpoint won't move cluster CPU,
so force the alarm to exercise the pipeline):

```bash
aws cloudwatch set-alarm-state \
  --alarm-name <stack>-shared-cluster-cpu-high \
  --state-value ALARM --state-reason "end-to-end agent test"
aws logs tail /aws/lambda/<stack>-agent --follow --since 5m
```

### Configuration (agent Lambda environment variables)

| Variable | Purpose | Default |
|----------|---------|---------|
| `ENV` | `dev` (auto-remediate) or `prod` (SNS approval) | `dev` |
| `AWS_REGION` | Region for all AWS calls | — |
| `BEDROCK_MODEL_ID` | Claude on Bedrock (inference-profile ID recommended) | `us.anthropic.claude-sonnet-4-5-20250929-v1:0` |
| `TENANT_REGISTRY_TABLE` | DynamoDB registry table name | — |
| `AMP_WORKSPACE_URL` | Full `https://aps-workspaces…` endpoint | — |
| `SNS_TOPIC_ARN` | Remediation-proposal topic (required in `prod`) | — |
| `MAX_DESIRED_COUNT` | Hard cap on `UpdateService` desiredCount | `20` |

## Support

Open an issue in this repository. For the pattern narrative and background, see
the corresponding APG pattern. Security decisions and tracked exceptions are
documented in [`SECURITY-NOTES.md`](SECURITY-NOTES.md).

## Roadmap

- Add per-tenant rate limiting as a fourth action (AWS WAF / API Gateway usage
  plans) for cases where scaling is not the right response.
- Add incident memory (persist events + resolutions in DynamoDB) so the agent
  can reference similar past incidents.
- Re-pin the ADOT collector image once an upstream release ships the fixed
  `golang.org/x/crypto` and `grpc` versions (see `SECURITY-NOTES.md`).
- Add a CI pipeline (lint, tests, cfn-lint/checkov, image scan) with status
  badges.

## Contributing

Contributions are welcome. Before opening a merge request:

```bash
pip install -e '.[dev]'
ruff check agent lambda_invoker tests sample_workload scripts
pytest -q
cfn-lint infra/*.yaml
checkov -f infra/template.yaml
```

Keep IAM least-privilege, pin container images by digest, and do not weaken the
blocking image scan (`scripts/scan-image.sh`). New tenant-facing behavior should
come with a test in `tests/`.

## Authors and acknowledgment

Created by AWS Professional Services. Derived from a multi-tenant ECS
transformation engagement; generalized and sanitized (no customer-specific
content). Built on the [Strands Agents SDK](https://strandsagents.com/) and the
AWS SaaS reference architecture for ECS container-image conventions.

## License

Licensed under the MIT-0 License. See the [`LICENSE`](LICENSE) file.

## Project status

Active. Deploys via CloudFormation and has been exercised on a sandbox account
through the metrics pipeline and agent invocation; unit and offline end-to-end
tests pass locally. This is reference/sample code, not a production service.
