#!/usr/bin/env bash
set -euo pipefail

echo "Setting up virtualenv and installing dependencies..."
python -m venv .venv || true
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

printf "Setup complete.\nVirtual environment: .venv\nActivate with: source .venv/bin/activate\n"

# Data seeding is handled automatically by `./deploy-changeset.sh --auto`
# (which calls scripts/seed_s3_data.sh). To seed manually, set BUCKET and run:
# BUCKET=my-project-bucket
# aws s3 cp POC/data/s3_cars_data_normalized.csv s3://$BUCKET/cars-data/
# aws s3 cp POC/data/s3_library_data.json s3://$BUCKET/library-data/
