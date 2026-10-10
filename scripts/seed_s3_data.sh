#!/usr/bin/env bash
# Seed the primary data bucket with the sample datasets the Glue crawlers
# expect. Uploads POC/data/s3_cars_data_normalized.csv → cars-data/ and
# POC/data/s3_library_data.json → library-data/ so the crawlers register
# tables (otherwise the allowlist stays empty and queries are refused).
#
# Idempotent: `aws s3 cp` safely overwrites, so re-running is harmless.
# Missing local files produce a warning but do NOT fail the deploy.
#
# Usage:
#   ./scripts/seed_s3_data.sh <bucket-name>
#   PRIMARY_DATA_BUCKET_NAME=<bucket> ./scripts/seed_s3_data.sh
set -euo pipefail

REGION="${AWS_REGION:-eu-north-1}"

# Resolve the bucket from the first arg, falling back to the env var.
BUCKET="${1:-${PRIMARY_DATA_BUCKET_NAME:-}}"
if [[ -z "$BUCKET" ]]; then
  echo "❌ seed_s3_data.sh: no bucket provided (pass as \$1 or set PRIMARY_DATA_BUCKET_NAME)" >&2
  exit 1
fi

# Resolve repo root relative to this script so it works from any CWD.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"

CARS_FILE="$ROOT/POC/data/s3_cars_data_normalized.csv"
LIBRARY_FILE="$ROOT/POC/data/s3_library_data.json"

echo "Seeding sample data into s3://${BUCKET}/ (region ${REGION})..."

if [[ -f "$CARS_FILE" ]]; then
  echo "  cars-data/    ← $CARS_FILE"
  aws s3 cp "$CARS_FILE" "s3://${BUCKET}/cars-data/" --region "$REGION"
else
  echo "⚠️  Missing $CARS_FILE — skipping cars-data/ seed"
fi

if [[ -f "$LIBRARY_FILE" ]]; then
  echo "  library-data/ ← $LIBRARY_FILE"
  aws s3 cp "$LIBRARY_FILE" "s3://${BUCKET}/library-data/" --region "$REGION"
else
  echo "⚠️  Missing $LIBRARY_FILE — skipping library-data/ seed"
fi

echo "✓ Data seeding complete"
