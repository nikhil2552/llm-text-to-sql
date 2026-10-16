#!/usr/bin/env bash
# CloudFormation deployment script.
# The stack creates its own VPC, subnets, and VPC endpoints — no external
# VPC parameters are needed. No NAT gateway is used.
#
# Usage:
#   ./deploy-changeset.sh                    # Review mode: creates change set, shows summary
#   ./deploy-changeset.sh --auto             # Full auto: deploy stack + build image locally + seed data + start service
#   ./deploy-changeset.sh --auto --with-databases  # Also deploy RDS Aurora + Redshift Serverless
#   ./deploy-changeset.sh --auto --with-cicd       # GitHub Actions builds and pushes the image (no local Docker)
#
# The default --auto deploy is fully self-contained and touches NO GitHub:
# infra + locally built image + data seeding + crawlers + ECS start. It needs
# Docker running locally.
#
# --with-cicd flips the image build to GitHub Actions: it provisions AWS infra,
# seeds data, runs crawlers, and wires a GitHub OIDC role scoped to YOUR repo
# (auto-detected from the `origin` git remote), but does NOT build the image
# locally and does NOT need Docker. It requires an `origin` remote pointing at
# your own GitHub repo; after it finishes, `git push origin main` triggers
# .github/workflows/deploy.yml to build the image on GitHub, push it to ECR, and
# start the ECS services.
set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────
TEMPLATE_FILE="cloudformation-template-validated.yml"
STACK_NAME="cgs-ai-analyst-agent-project"
REGION="${AWS_REGION:-eu-north-1}"
IAM_USER="${IAM_USER:-$(aws iam get-user --query 'User.UserName' --output text 2>/dev/null || echo 'unknown')}"
DESIRED_COUNT="${DESIRED_COUNT:-1}"
STREAMLIT_DESIRED_COUNT="${STREAMLIT_DESIRED_COUNT:-1}"
STREAMLIT_USERNAME="${STREAMLIT_USERNAME:-admin}"
STREAMLIT_PASSWORD="${STREAMLIT_PASSWORD:-}"
AUTO_MODE=false
WITH_DATABASES=false
WITH_CICD=false

# Parse flags
for arg in "$@"; do
  case "$arg" in
    --auto) AUTO_MODE=true ;;
    --with-databases) WITH_DATABASES=true ;;
    --with-cicd) WITH_CICD=true ;;
  esac
done

# ── Detect the GitHub owner/repo from the `origin` git remote ───────────────
# Used by the --with-cicd path so the OIDC trust is scoped to YOUR repo instead
# of a template default. Parses both HTTPS and SSH remote URLs, tolerates a
# trailing slash and an optional `.git` suffix, and sets the globals
# GITHUB_ORG / GITHUB_REPO. Returns non-zero (leaving them empty) when there is
# no origin remote or it is not a GitHub URL. bash 3.2 compatible (no bash-4
# case-folding expansions).
GITHUB_ORG=""
GITHUB_REPO=""
detect_github_slug() {
  GITHUB_ORG=""
  GITHUB_REPO=""
  local url
  url="$(git remote get-url origin 2>/dev/null || git config --get remote.origin.url 2>/dev/null || echo '')"
  if [[ -z "$url" ]]; then
    return 1
  fi
  # Strip a trailing slash, then strip an optional trailing `.git`.
  url="${url%/}"
  url="${url%.git}"
  local slug=""
  case "$url" in
    git@github.com:*)
      slug="${url#git@github.com:}"
      ;;
    https://github.com/*)
      slug="${url#https://github.com/}"
      ;;
    http://github.com/*)
      slug="${url#http://github.com/}"
      ;;
    ssh://git@github.com/*)
      slug="${url#ssh://git@github.com/}"
      ;;
    *)
      return 1
      ;;
  esac
  # slug should now be "OWNER/REPO" (REPO must not contain another slash).
  local owner="${slug%%/*}"
  local repo="${slug#*/}"
  if [[ -z "$owner" || -z "$repo" || "$owner" == "$slug" || "$repo" == *"/"* ]]; then
    return 1
  fi
  GITHUB_ORG="$owner"
  GITHUB_REPO="$repo"
  return 0
}

# Detect which data-layer resources already exist
eval "$(bash scripts/detect_existing_resources.sh | grep -E '^[A-Z_]+=')"

# ── Reconcile Streamlit credentials secret (fail-safe, idempotent) ──────────
# The stack owns `cgs-ai-analyst-agent/streamlit-credentials` as a managed
# AWS::SecretsManager::Secret. If an UNMANAGED secret with that name already
# exists (e.g. created by hand during troubleshooting), CloudFormation would
# fail with "already exists". Here we detect that case and remove the orphan so
# the stack can create and own it cleanly. A secret already owned by THIS stack
# is left untouched — we never delete a stack-managed secret.
reconcile_streamlit_secret() {
  local secret_name="cgs-ai-analyst-agent/streamlit-credentials"
  local desc
  desc="$(aws secretsmanager describe-secret \
    --secret-id "$secret_name" \
    --region "$REGION" \
    --query '{Tags:Tags,ARN:ARN}' \
    --output json 2>/dev/null || echo '')"
  # Not found → nothing to reconcile; the template will create it.
  if [[ -z "$desc" || "$desc" == "None" ]]; then
    return 0
  fi
  # Is it already managed by this CloudFormation stack? CFN tags managed
  # resources with aws:cloudformation:stack-name.
  local owner
  owner="$(printf '%s' "$desc" \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(next((t['Value'] for t in (d.get('Tags') or []) if t['Key']=='aws:cloudformation:stack-name'), ''))" 2>/dev/null || echo '')"
  if [[ "$owner" == "$STACK_NAME" ]]; then
    echo "✓ Streamlit secret already managed by stack ${STACK_NAME} — leaving as-is."
    return 0
  fi
  echo "⚠️  Found an unmanaged secret '${secret_name}' (owner='${owner:-none}')."
  echo "    Removing it so CloudFormation can create and own it..."
  aws secretsmanager delete-secret \
    --secret-id "$secret_name" \
    --force-delete-without-recovery \
    --region "$REGION" >/dev/null 2>&1 || true
  # Wait until the name is actually free (force-delete is near-immediate, but
  # poll briefly so the subsequent change set never races the deletion).
  for _ in $(seq 1 10); do
    if ! aws secretsmanager describe-secret --secret-id "$secret_name" --region "$REGION" >/dev/null 2>&1; then
      echo "✓ Orphan secret removed — name is free for the stack."
      return 0
    fi
    sleep 2
  done
  echo "⚠️  Secret '${secret_name}' still resolving after delete — the stack may retry."
}
reconcile_streamlit_secret

# ── Change set type ────────────────────────────────────────────────────────
CHANGE_SET_NAME="${STACK_NAME}-changeset-$(date +%s)"

STACK_STATUS="$(aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --region "$REGION" \
  --query 'Stacks[0].StackStatus' \
  --output text 2>/dev/null || echo 'NOT_FOUND')"

if [[ "$STACK_STATUS" == "NOT_FOUND" || "$STACK_STATUS" == "DELETE_COMPLETE" ]]; then
  CHANGE_SET_TYPE="CREATE"
else
  CHANGE_SET_TYPE="UPDATE"
fi

# On first deploy (CREATE) in auto mode, deploy with DesiredCount=0 to avoid
# ECS service getting stuck waiting for a container image that doesn't exist yet.
# The image is pushed after stack creation, then the service is scaled up.
DEPLOY_DESIRED_COUNT="$DESIRED_COUNT"
DEPLOY_STREAMLIT_DESIRED_COUNT="$STREAMLIT_DESIRED_COUNT"
if $AUTO_MODE && [[ "$CHANGE_SET_TYPE" == "CREATE" ]]; then
  DEPLOY_DESIRED_COUNT="0"
  DEPLOY_STREAMLIT_DESIRED_COUNT="0"
fi

# Only create the Glue crawlers in --auto mode, where the deploy also seeds
# data and runs the crawlers end-to-end. Review mode leaves them off so a
# plain change set does not provision crawlers.
CREATE_CRAWLERS_PARAM="false"
if $AUTO_MODE; then
  CREATE_CRAWLERS_PARAM="true"
fi

# ── CloudFormation parameters ─────────────────────────────────────────────
CFN_PARAMETERS=$(cat <<EOF
[
  {"ParameterKey": "DesiredCount",              "ParameterValue": "${DEPLOY_DESIRED_COUNT}"},
  {"ParameterKey": "StreamlitDesiredCount",     "ParameterValue": "${DEPLOY_STREAMLIT_DESIRED_COUNT}"},
  {"ParameterKey": "StreamlitUsername",         "ParameterValue": "${STREAMLIT_USERNAME}"},
  {"ParameterKey": "StreamlitPassword",         "ParameterValue": "${STREAMLIT_PASSWORD}"},
  {"ParameterKey": "PrimaryDataBucketName",     "ParameterValue": "${PRIMARY_DATA_BUCKET_NAME}"},
  {"ParameterKey": "CreatePrimaryDataBucket",   "ParameterValue": "${CREATE_PRIMARY_DATA_BUCKET}"},
  {"ParameterKey": "AthenaWorkgroupName",       "ParameterValue": "${ATHENA_WORKGROUP_NAME}"},
  {"ParameterKey": "CreateAthenaWorkgroup",     "ParameterValue": "${CREATE_ATHENA_WORKGROUP}"},
  {"ParameterKey": "LibraryGlueDatabaseName",   "ParameterValue": "${LIBRARY_GLUE_DATABASE_NAME}"},
  {"ParameterKey": "CarsGlueDatabaseName",      "ParameterValue": "${CARS_GLUE_DATABASE_NAME}"},
  {"ParameterKey": "CreateLibraryGlueDatabase", "ParameterValue": "${CREATE_LIBRARY_GLUE_DATABASE}"},
  {"ParameterKey": "CreateCarsGlueDatabase",    "ParameterValue": "${CREATE_CARS_GLUE_DATABASE}"},
  {"ParameterKey": "CreateAppLogGroup",         "ParameterValue": "${CREATE_APP_LOG_GROUP}"},
  {"ParameterKey": "CreateCrawlers",            "ParameterValue": "${CREATE_CRAWLERS_PARAM}"}
]
EOF
)

echo "=========================================="
echo "CloudFormation Deployment"
echo "=========================================="
echo "Stack Name:      $STACK_NAME"
echo "Template:        $TEMPLATE_FILE"
echo "Region:          $REGION"
echo "IAM User:        $IAM_USER"
echo "Mode:            $(if $AUTO_MODE; then echo 'AUTO (deploy + push + start)'; else echo 'REVIEW (change set only)'; fi)"
echo "Change Set Type: $CHANGE_SET_TYPE (stack status: ${STACK_STATUS})"
echo ""

# ── Validate template ──────────────────────────────────────────────────────
echo "Validating template..."
aws cloudformation validate-template \
  --template-body file://"$TEMPLATE_FILE" \
  --region "$REGION" \
  > /dev/null && echo "✓ Template valid"

# ── Create change set ──────────────────────────────────────────────────────
echo ""
echo "Creating change set..."
if ! aws cloudformation create-change-set \
  --stack-name "$STACK_NAME" \
  --change-set-name "$CHANGE_SET_NAME" \
  --change-set-type "$CHANGE_SET_TYPE" \
  --template-body "file://${TEMPLATE_FILE}" \
  --capabilities CAPABILITY_IAM \
  --region "$REGION" \
  --parameters "$CFN_PARAMETERS" \
  --tags \
    "Key=DeployedBy,Value=${IAM_USER}" \
    "Key=DeploymentDate,Value=$(date -u +'%Y-%m-%dT%H:%M:%SZ')" \
    "Key=Environment,Value=production" 2>"${TMPDIR:-/tmp}/cfn-changeset.err"; then
  if grep -q 'Stack.*does not exist' "${TMPDIR:-/tmp}/cfn-changeset.err"; then
    echo "Stack not found — retrying with --change-set-type CREATE..."
    CHANGE_SET_TYPE="CREATE"
    aws cloudformation create-change-set \
      --stack-name "$STACK_NAME" \
      --change-set-name "$CHANGE_SET_NAME" \
      --change-set-type CREATE \
      --template-body "file://${TEMPLATE_FILE}" \
      --capabilities CAPABILITY_IAM \
      --region "$REGION" \
      --parameters "$CFN_PARAMETERS" \
      --tags \
        "Key=DeployedBy,Value=${IAM_USER}" \
        "Key=DeploymentDate,Value=$(date -u +'%Y-%m-%dT%H:%M:%SZ')" \
        "Key=Environment,Value=production"
  else
    cat "${TMPDIR:-/tmp}/cfn-changeset.err" >&2
    exit 1
  fi
fi

# ── Wait for change set ────────────────────────────────────────────────────
echo "Waiting for change set to be created..."
if ! aws cloudformation wait change-set-create-complete \
  --stack-name "$STACK_NAME" \
  --change-set-name "$CHANGE_SET_NAME" \
  --region "$REGION" \
  2>/dev/null; then
  # Check if changeset failed
  CS_STATUS="$(aws cloudformation describe-change-set \
    --stack-name "$STACK_NAME" \
    --change-set-name "$CHANGE_SET_NAME" \
    --region "$REGION" \
    --query 'Status' --output text 2>/dev/null || echo 'UNKNOWN')"
  CS_REASON="$(aws cloudformation describe-change-set \
    --stack-name "$STACK_NAME" \
    --change-set-name "$CHANGE_SET_NAME" \
    --region "$REGION" \
    --query 'StatusReason' --output text 2>/dev/null || echo '')"
  if [[ "$CS_STATUS" == "FAILED" ]]; then
    echo ""
    echo "❌ Change set FAILED: $CS_REASON"
    echo ""
    echo "Cleaning up failed change set..."
    aws cloudformation delete-change-set \
      --stack-name "$STACK_NAME" \
      --change-set-name "$CHANGE_SET_NAME" \
      --region "$REGION" 2>/dev/null || true
    # If stack is in REVIEW_IN_PROGRESS (failed CREATE), delete the empty stack
    if [[ "$CHANGE_SET_TYPE" == "CREATE" ]]; then
      echo "Deleting empty stack (was never created)..."
      aws cloudformation delete-stack --stack-name "$STACK_NAME" --region "$REGION" 2>/dev/null || true
    fi
    echo ""
    echo "Common causes:"
    echo "  - A resource already exists outside the stack (check ResourceExistenceCheck)"
    echo "  - Re-run: ./deploy-changeset.sh --auto (detection script will adapt)"
    exit 1
  fi
fi

# ── Show summary ───────────────────────────────────────────────────────────
echo ""
echo "=========================================="
echo "Change Set Summary:"
echo "=========================================="
aws cloudformation describe-change-set \
  --stack-name "$STACK_NAME" \
  --change-set-name "$CHANGE_SET_NAME" \
  --region "$REGION" \
  --query 'Changes[*].[Type, ResourceChange.Action, ResourceChange.LogicalResourceId, ResourceChange.ResourceType]' \
  --output table

# ── Auto mode: execute + push + start ──────────────────────────────────────
if $AUTO_MODE; then
  echo ""
  echo "=========================================="
  echo "AUTO MODE: Executing change set..."
  echo "=========================================="
  aws cloudformation execute-change-set \
    --stack-name "$STACK_NAME" \
    --change-set-name "$CHANGE_SET_NAME" \
    --region "$REGION"

  echo "Waiting for stack to complete (this may take 5-10 minutes)..."
  if [[ "$CHANGE_SET_TYPE" == "CREATE" ]]; then
    aws cloudformation wait stack-create-complete \
      --stack-name "$STACK_NAME" \
      --region "$REGION"
  else
    aws cloudformation wait stack-update-complete \
      --stack-name "$STACK_NAME" \
      --region "$REGION"
  fi
  echo "✓ Stack $CHANGE_SET_TYPE complete"

  echo ""
  echo "=========================================="
  echo "Seeding sample data into S3 (before crawlers run)..."
  echo "=========================================="
  # The bucket now exists; seed the datasets so the crawlers find data and
  # register tables. A seed hiccup must never abort the deploy.
  bash scripts/seed_s3_data.sh "$PRIMARY_DATA_BUCKET_NAME" \
    || echo "⚠️  Data seeding skipped/failed — crawlers may find no data"

  if $WITH_CICD; then
    echo ""
    echo "=========================================="
    echo "Skipping local image build (CI/CD mode)..."
    echo "=========================================="
    echo "ℹ️  --with-cicd: the image is built and pushed by GitHub Actions (no local Docker)."
    echo "    ECS stays at its current desired count until the GitHub build pushes an image."
  else
    echo ""
    echo "=========================================="
    echo "Building and pushing container image..."
    echo "=========================================="
    DESIRED_COUNT="$DESIRED_COUNT" STREAMLIT_DESIRED_COUNT="$STREAMLIT_DESIRED_COUNT" ./scripts/push_ecr.sh
  fi

  echo ""
  echo "=========================================="
  echo "Running Glue Crawlers (populates table catalog)..."
  echo "=========================================="
  for CRAWLER_NAME in project-library-crawler project-cars-crawler; do
    CRAWLER_STATE="$(aws glue get-crawler --name "$CRAWLER_NAME" --region "$REGION" \
      --query 'Crawler.State' --output text 2>/dev/null || echo 'NOT_FOUND')"
    if [[ "$CRAWLER_STATE" == "READY" ]]; then
      echo "Starting crawler: $CRAWLER_NAME"
      aws glue start-crawler --name "$CRAWLER_NAME" --region "$REGION" 2>/dev/null || true
    elif [[ "$CRAWLER_STATE" == "NOT_FOUND" ]]; then
      echo "⚠️  Crawler $CRAWLER_NAME not found — skipping"
    else
      echo "⚠️  Crawler $CRAWLER_NAME is in state $CRAWLER_STATE — skipping"
    fi
  done
  # Wait for crawlers to finish (up to 2 minutes)
  echo "Waiting for crawlers to complete..."
  for i in $(seq 1 12); do
    sleep 10
    LIB_STATE="$(aws glue get-crawler --name project-library-crawler --region "$REGION" \
      --query 'Crawler.State' --output text 2>/dev/null || echo 'READY')"
    CARS_STATE="$(aws glue get-crawler --name project-cars-crawler --region "$REGION" \
      --query 'Crawler.State' --output text 2>/dev/null || echo 'READY')"
    if [[ "$LIB_STATE" == "READY" && "$CARS_STATE" == "READY" ]]; then
      echo "✓ Crawlers complete — Glue tables registered"
      break
    fi
    if [[ $i -eq 12 ]]; then
      echo "⚠️  Crawlers still running after 2 min — tables may not be ready yet"
    fi
  done

  echo ""
  echo "=========================================="
  echo "Configuring S3 event notification (fail-safe)..."
  echo "=========================================="
  bash scripts/configure_s3_notification.sh || echo "⚠️  S3 notification config skipped (Lambda may not be ready yet)"

  # ── Deploy database stacks (optional) ────────────────────────────────────
  if $WITH_DATABASES; then
    echo ""
    echo "=========================================="
    echo "Deploying RDS Aurora Serverless v2..."
    echo "=========================================="
    RDS_STACK="cgs-ai-rds-aurora"
    RDS_STATUS="$(aws cloudformation describe-stacks \
      --stack-name "$RDS_STACK" \
      --region "$REGION" \
      --query 'Stacks[0].StackStatus' \
      --output text 2>/dev/null || echo 'NOT_FOUND')"

    if [[ "$RDS_STATUS" == "NOT_FOUND" || "$RDS_STATUS" == "DELETE_COMPLETE" ]]; then
      aws cloudformation deploy \
        --template-file cloudformation-rds-aurora.yml \
        --stack-name "$RDS_STACK" \
        --capabilities CAPABILITY_NAMED_IAM \
        --region "$REGION" \
        --no-fail-on-empty-changeset \
        --tags "Key=Environment,Value=production" || echo "⚠️  RDS stack deploy failed"
      echo "✓ RDS Aurora stack deployed"
    else
      echo "✓ RDS stack already exists ($RDS_STATUS)"
    fi

    echo ""
    echo "=========================================="
    echo "Deploying Redshift Serverless..."
    echo "=========================================="
    REDSHIFT_STACK="cgs-ai-redshift-serverless"
    REDSHIFT_STATUS="$(aws cloudformation describe-stacks \
      --stack-name "$REDSHIFT_STACK" \
      --region "$REGION" \
      --query 'Stacks[0].StackStatus' \
      --output text 2>/dev/null || echo 'NOT_FOUND')"

    if [[ "$REDSHIFT_STATUS" == "NOT_FOUND" || "$REDSHIFT_STATUS" == "DELETE_COMPLETE" ]]; then
      aws cloudformation deploy \
        --template-file cloudformation-redshift-serverless.yml \
        --stack-name "$REDSHIFT_STACK" \
        --capabilities CAPABILITY_NAMED_IAM \
        --region "$REGION" \
        --no-fail-on-empty-changeset \
        --tags "Key=Environment,Value=production" || echo "⚠️  Redshift stack deploy failed"
      echo "✓ Redshift Serverless stack deployed"
    else
      echo "✓ Redshift stack already exists ($REDSHIFT_STATUS)"
    fi

    # Print connection info
    echo ""
    echo "Database connection configs:"
    RDS_ENDPOINT="$(aws cloudformation describe-stacks \
      --stack-name "$RDS_STACK" --region "$REGION" \
      --query "Stacks[0].Outputs[?OutputKey=='ClusterEndpoint'].OutputValue" \
      --output text 2>/dev/null || echo 'pending')"
    REDSHIFT_ENDPOINT="$(aws cloudformation describe-stacks \
      --stack-name "$REDSHIFT_STACK" --region "$REGION" \
      --query "Stacks[0].Outputs[?OutputKey=='RedshiftWorkgroupEndpoint'].OutputValue" \
      --output text 2>/dev/null || echo 'pending')"
    echo "  RDS Aurora:   $RDS_ENDPOINT"
    echo "  Redshift:     $REDSHIFT_ENDPOINT"
  fi

  # ── GitHub Actions OIDC (opt-in CI/CD) ───────────────────────────────────
  # Pass --with-cicd when GitHub Actions should build and push the image (no
  # local Docker). This provisions a GitHub OIDC role whose trust is scoped to
  # YOUR repo, auto-detected from the `origin` git remote — never a hardcoded
  # author repo. An origin remote pointing at your own GitHub repo is required.
  if $WITH_CICD; then
    # Scope the OIDC trust to the repo you actually pushed to. If there is no
    # origin remote (or it is not a GitHub URL), stop with actionable guidance
    # — falling back to a default repo would mint a role that trusts someone
    # else's repository. This gate runs on both CREATE and UPDATE paths.
    if ! detect_github_slug; then
      echo ""
      echo "❌ --with-cicd requires an 'origin' remote pointing at your own GitHub repo."
      echo ""
      echo "   The CI/CD flow builds the image in GitHub Actions running in YOUR repo, so"
      echo "   the OIDC role must be scoped to that repo. No GitHub 'origin' remote was found."
      echo ""
      echo "   Sign in to your own GitHub, create a new empty repo, then run:"
      echo "     git remote add origin https://github.com/<you>/<repo>.git"
      echo "     git branch -M main"
      echo "     git push -u origin main"
      echo "     ./deploy-changeset.sh --auto --with-cicd"
      echo ""
      exit 1
    fi
    echo ""
    echo "=========================================="
    echo "Setting up GitHub Actions OIDC (CI/CD)..."
    echo "=========================================="
    echo "Target GitHub repo (from origin remote): $GITHUB_ORG/$GITHUB_REPO"
    OIDC_STACK="github-actions-oidc"
    OIDC_STATUS="$(aws cloudformation describe-stacks \
      --stack-name "$OIDC_STACK" \
      --region "$REGION" \
      --query 'Stacks[0].StackStatus' \
      --output text 2>/dev/null || echo 'NOT_FOUND')"

    if [[ "$OIDC_STATUS" == "NOT_FOUND" || "$OIDC_STATUS" == "DELETE_COMPLETE" ]]; then
      # Check if OIDC provider already exists in account
      EXISTING_OIDC="$(aws iam list-open-id-connect-providers \
        --query "OpenIDConnectProviderList[?ends_with(Arn, '/token.actions.githubusercontent.com')].Arn" \
        --output text 2>/dev/null || echo '')"

      # Always scope the trust to the detected repo; only pass OIDCProviderArn
      # when the account already has a GitHub OIDC provider to reuse.
      OIDC_OVERRIDES=("GitHubOrg=$GITHUB_ORG" "GitHubRepo=$GITHUB_REPO")
      if [[ -n "$EXISTING_OIDC" && "$EXISTING_OIDC" != "None" ]]; then
        OIDC_OVERRIDES+=("OIDCProviderArn=$EXISTING_OIDC")
      fi

      DEPLOY_OIDC_ARGS=(
        --template-file cloudformation-github-oidc.yml
        --stack-name "$OIDC_STACK"
        --capabilities CAPABILITY_NAMED_IAM
        --region "$REGION"
        --no-fail-on-empty-changeset
        --parameter-overrides "${OIDC_OVERRIDES[@]}"
      )

      aws cloudformation deploy "${DEPLOY_OIDC_ARGS[@]}" 2>/dev/null || echo "⚠️  OIDC stack deploy failed (non-blocking)"

      ROLE_ARN="$(aws cloudformation describe-stacks \
        --stack-name "$OIDC_STACK" \
        --region "$REGION" \
        --query "Stacks[0].Outputs[?OutputKey=='DeployRoleArn'].OutputValue" \
        --output text 2>/dev/null || echo '')"

      if [[ -n "$ROLE_ARN" && "$ROLE_ARN" != "None" ]]; then
        echo "✓ GitHub OIDC role: $ROLE_ARN"
        if command -v gh &>/dev/null; then
          gh secret set AWS_DEPLOY_ROLE_ARN --repo "$GITHUB_ORG/$GITHUB_REPO" --body "$ROLE_ARN" 2>/dev/null && \
            echo "✓ GitHub secret AWS_DEPLOY_ROLE_ARN set on $GITHUB_ORG/$GITHUB_REPO" || \
            echo "⚠️  Could not set GitHub secret (run: gh secret set AWS_DEPLOY_ROLE_ARN --repo \"$GITHUB_ORG/$GITHUB_REPO\" --body \"$ROLE_ARN\")"
        else
          echo "  Set GitHub secret manually: gh secret set AWS_DEPLOY_ROLE_ARN --repo \"$GITHUB_ORG/$GITHUB_REPO\" --body \"$ROLE_ARN\""
        fi
      fi
    else
      echo "✓ OIDC stack already exists ($OIDC_STATUS)"
    fi

    # ── NEXT STEP: trigger the GitHub build ────────────────────────────────
    # The image has NOT been built locally under --with-cicd. A push to main
    # runs .github/workflows/deploy.yml, which builds on GitHub, pushes to ECR,
    # and starts the ECS services. Print this on both CREATE and UPDATE paths.
    echo ""
    echo "=========================================="
    echo "👉 NEXT STEP — trigger the GitHub build:"
    echo "=========================================="
    echo "   The image is NOT built locally in CI/CD mode. Push to GitHub to deploy:"
    echo ""
    echo "     git push origin main"
    echo ""
    echo "   This triggers .github/workflows/deploy.yml in $GITHUB_ORG/$GITHUB_REPO, which:"
    echo "     • builds the Docker image on GitHub (linux/amd64)"
    echo "     • pushes it to ECR"
    echo "     • starts the ECS services (API + Streamlit)"
    echo "   Watch progress under the repo's Actions tab; the workflow prints the API"
    echo "   and Streamlit URLs when it finishes."
  else
    echo ""
    echo "ℹ️  Skipped GitHub Actions OIDC setup (CI/CD is opt-in)."
    echo "    To enable push-to-deploy later, re-run with:  ./deploy-changeset.sh --auto --with-cicd"
  fi

  echo ""
  echo "=========================================="
  echo "✅ DEPLOYMENT COMPLETE"
  echo "=========================================="
  ALB_URL="$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='LoadBalancerUrl'].OutputValue" \
    --output text 2>/dev/null || true)"
  STREAMLIT_URL="$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='StreamlitUrl'].OutputValue" \
    --output text 2>/dev/null || true)"
  if [[ -n "$ALB_URL" && "$ALB_URL" != "None" ]]; then
    echo "🌐 API URL:     $ALB_URL"
    echo "❤️  Health:      $ALB_URL/health"
    echo "💬 Query:       curl -X POST $ALB_URL/query -H 'Content-Type: application/json' -d '{\"question\":\"How many books?\"}'"
  fi
  if [[ -n "$STREAMLIT_URL" && "$STREAMLIT_URL" != "None" ]]; then
    echo "🖥️  Streamlit:   $STREAMLIT_URL"
    echo "🔑 Streamlit login — username: ${STREAMLIT_USERNAME}  (get password with:)"
    echo "     aws secretsmanager get-secret-value \\"
    echo "       --secret-id cgs-ai-analyst-agent/streamlit-credentials \\"
    echo "       --region $REGION --query SecretString --output text"
  fi

  # ── Logical next steps: point to the follow-on scripts ───────────────────
  echo ""
  echo "── Optional next steps ──────────────────────────────────────────────"
  if ! $WITH_DATABASES; then
    echo "  • Add Aurora + Redshift databases:   ./deploy-changeset.sh --auto --with-databases"
  fi
  if ! $WITH_CICD; then
    echo "  • Enable push-to-deploy (CI/CD):     ./deploy-changeset.sh --auto --with-cicd"
  fi
  echo "  • Rebuild/redeploy the image only:   ./scripts/push_ecr.sh"
  echo "  • Tear everything down:              ./scripts/teardown.sh"
  echo "─────────────────────────────────────────────────────────────────────"
else
  # Review mode — show next steps
  echo ""
  echo "=========================================="
  echo "Next Steps:"
  echo "=========================================="
  echo ""
  echo "  Option A — Run everything automatically:"
  echo ""
  echo "    ./deploy-changeset.sh --auto"
  echo ""
  echo "  Option B — Execute manually:"
  echo ""
  echo "    1. Execute the change set:"
  echo "       aws cloudformation execute-change-set \\"
  echo "         --stack-name $STACK_NAME \\"
  echo "         --change-set-name $CHANGE_SET_NAME \\"
  echo "         --region $REGION"
  echo ""
  echo "    2. Wait for completion:"
  CHANGE_SET_TYPE_LC="$(printf '%s' "$CHANGE_SET_TYPE" | tr '[:upper:]' '[:lower:]')"
  echo "       aws cloudformation wait stack-${CHANGE_SET_TYPE_LC}-complete \\"
  echo "         --stack-name $STACK_NAME --region $REGION"
  echo ""
  echo "    3. Push image and start:"
  echo "       DESIRED_COUNT=1 ./scripts/push_ecr.sh"
  echo ""
  echo "  To delete the change set without executing:"
  echo "    aws cloudformation delete-change-set \\"
  echo "      --stack-name $STACK_NAME \\"
  echo "      --change-set-name $CHANGE_SET_NAME \\"
  echo "      --region $REGION"
  echo ""
fi
