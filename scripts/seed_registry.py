"""Seed the DynamoDB tenant registry from infra/seed-tenants.json.

    python scripts/seed_registry.py --table <table-name> --file infra/seed-tenants.json

Requires AWS credentials with dynamodb:PutItem on the target table.
"""

from __future__ import annotations

import argparse
import json
import sys

import boto3


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table", required=True)
    parser.add_argument("--file", required=True)
    parser.add_argument("--region", default=None)
    args = parser.parse_args()

    with open(args.file, encoding="utf-8") as fh:
        tenants = json.load(fh)["TENANT_REGISTRY_TABLE"]["tenants"]

    ddb = boto3.client("dynamodb", region_name=args.region)
    for t in tenants:
        if any(str(v).startswith("REPLACE") for v in t.values()):
            print(f"Refusing to seed unresolved row: {t}", file=sys.stderr)
            return 1
        ddb.put_item(
            TableName=args.table,
            Item={
                "tenant_id": {"S": t["tenant_id"]},
                "cluster_name": {"S": t["cluster_name"]},
                "service_name": {"S": t["service_name"]},
                "tier": {"S": t["tier"]},
                "baseline_share": {"N": str(t["baseline_share"])},
            },
        )
        print(f"seeded {t['tenant_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
