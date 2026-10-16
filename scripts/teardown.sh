#!/usr/bin/env bash
# Teardown script - deletes all CloudFormation stacks and cleans up ECR images.
#
# Usage:
#   ./scripts/teardown.sh          # Interactive - asks for confirmation
#   ./scripts/teardown.sh --force  # Skip confirmation (CI/automation)
#
# What it does:
#   1. Scales ECS services to 0 (stops running tasks immediately)
#   2. Deletes the RDS Aurora stack (if exists) - takes a final snapshot
#   3. Deletes the main stack (VPC, ECS, ALB, Lambda)
#   4. Cleans up all ECR images and repository
#   5. Deletes S3 data buckets (empties first, then removes)
#   6. Deletes Athena workgroup
#   7. Deletes Glue crawlers and databases
#   8. Deletes CloudWatch log groups
#   9. Force-deletes stack-managed Secrets Manager secrets (no 30-day recovery
#      window), so a later redeploy can recreate them under the same names.
#
# After teardown, NOTHING remains - clean slate for redeployment.
set -euo pipefail

REGION="${AWS_REGION:-eu-north-1}"
MAIN_STACK="cgs-ai-analyst-agent-project"
RDS_STACK="cgs-ai-rds-aurora"
REDSHIFT_STACK="cgs-ai-redshift-serverless"
ECR_REPO="data-architecture-ai"
FORCE=false

for arg in "$@"; do
  case "$arg" in
    --force) FORCE=true ;;
  esac
done

echo "=========================================="
echo "TEARDOWN - CloudAge Data Architecture"
echo "=========================================="
echo "Region:     $REGION"
echo "Main stack: $MAIN_STACK"
echo "RDS stack:  $RDS_STACK"
echo "Redshift:   $REDSHIFT_STACK"
echo ""

# ── Check what exists ──────────────────────────────────────────────────────
MAIN_STATUS="$(aws cloudformation describe-stacks \
  --stack-name "$MAIN_STACK" \
  --region "$REGION" \
  --query 'Stacks[0].StackStatus' \
  --output text 2>/dev/null || echo 'NOT_FOUND')"

RDS_STATUS="$(aws cloudformation describe-stacks \
  --stack-name "$RDS_STACK" \
  --region "$REGION" \
  --query 'Stacks[0].StackStatus' \
  --output text 2>/dev/null || echo 'NOT_FOUND')"

REDSHIFT_STATUS="$(aws cloudformation describe-stacks \
  --stack-name "$REDSHIFT_STACK" \
  --region "$REGION" \
  --query 'Stacks[0].StackStatus' \
  --output text 2>/dev/null || echo 'NOT_FOUND')"

echo "Main stack status:     $MAIN_STATUS"
echo "RDS stack status:      $RDS_STATUS"
echo "Redshift stack status: $REDSHIFT_STATUS"
echo ""

if [[ "$MAIN_STATUS" == "NOT_FOUND" && "$RDS_STATUS" == "NOT_FOUND" && "$REDSHIFT_STATUS" == "NOT_FOUND" ]]; then
  echo "Nothing to tear down - no stacks found."
  exit 0
fi

# ── Confirmation ───────────────────────────────────────────────────────────
if ! $FORCE; then
  echo "⚠️  This will DELETE ALL infrastructure including:"
  echo "   - ECS services (API + Streamlit)"
  echo "   - Application Load Balancer"
  echo "   - VPC and all networking"
  echo "   - Lambda functions"
  echo "   - ECR images and repository"
  echo "   - S3 data buckets (all data will be lost)"
  echo "   - Athena workgroup"
  echo "   - Glue crawlers and databases"
  echo "   - CloudWatch log groups"
  echo "   - Secrets Manager secrets (streamlit / aurora / redshift credentials)"
  if [[ "$RDS_STATUS" != "NOT_FOUND" ]]; then
    echo "   - Aurora database (final snapshot will be taken)"
  fi
  echo ""
  echo "   ⚠️  THIS IS IRREVERSIBLE - all data will be deleted"
  echo ""
  read -p "Type 'destroy' to confirm: " confirmation
  if [[ "$confirmation" != "destroy" ]]; then
    echo "Cancelled."
    exit 0
  fi
  echo ""
fi

# ── Step 1: Scale ECS to 0 (stop tasks fast) ──────────────────────────────
if [[ "$MAIN_STATUS" != "NOT_FOUND" && "$MAIN_STATUS" != "DELETE_COMPLETE" ]]; then
  echo "Scaling ECS services to 0..."
  aws ecs update-service \
    --cluster data-architecture-ai \
    --service data-architecture-ai \
    --desired-count 0 \
    --region "$REGION" >/dev/null 2>&1 || true
  aws ecs update-service \
    --cluster data-architecture-ai \
    --service data-architecture-ai-streamlit \
    --desired-count 0 \
    --region "$REGION" >/dev/null 2>&1 || true
  echo "✓ ECS services scaled to 0"
fi

# ── Step 2: Delete RDS stack (if exists) ───────────────────────────────────
if [[ "$RDS_STATUS" != "NOT_FOUND" && "$RDS_STATUS" != "DELETE_COMPLETE" ]]; then
  echo ""
  echo "Deleting RDS stack ($RDS_STACK)..."
  echo "  (A final snapshot will be created automatically)"
  aws cloudformation delete-stack \
    --stack-name "$RDS_STACK" \
    --region "$REGION"
  echo "  Waiting for RDS deletion (this takes 5-10 minutes)..."
  aws cloudformation wait stack-delete-complete \
    --stack-name "$RDS_STACK" \
    --region "$REGION" 2>/dev/null || true
  echo "✓ RDS stack deleted"
fi

# ── Step 2b: Delete Redshift stack (if exists) ─────────────────────────────
if [[ "$REDSHIFT_STATUS" != "NOT_FOUND" && "$REDSHIFT_STATUS" != "DELETE_COMPLETE" ]]; then
  echo ""
  echo "Deleting Redshift stack ($REDSHIFT_STACK)..."
  aws cloudformation delete-stack \
    --stack-name "$REDSHIFT_STACK" \
    --region "$REGION"
  echo "  Waiting for Redshift deletion..."
  aws cloudformation wait stack-delete-complete \
    --stack-name "$REDSHIFT_STACK" \
    --region "$REGION" 2>/dev/null || true
  echo "✓ Redshift stack deleted"
fi

# ── Step 3: Delete main stack ──────────────────────────────────────────────
if [[ "$MAIN_STATUS" != "NOT_FOUND" && "$MAIN_STATUS" != "DELETE_COMPLETE" ]]; then
  echo ""
  echo "Deleting main stack ($MAIN_STACK)..."
  aws cloudformation delete-stack \
    --stack-name "$MAIN_STACK" \
    --region "$REGION"
  echo "  Waiting for deletion (this takes 5-10 minutes)..."
  aws cloudformation wait stack-delete-complete \
    --stack-name "$MAIN_STACK" \
    --region "$REGION" 2>/dev/null || true
  echo "✓ Main stack deleted"
fi

# ── Step 4: Clean up ECR images and repository ────────────────────────────
echo ""
echo "Cleaning up ECR repository..."
if aws ecr describe-repositories --repository-names "$ECR_REPO" --region "$REGION" >/dev/null 2>&1; then
  # --force deletes all images AND the repository in one call
  aws ecr delete-repository \
    --repository-name "$ECR_REPO" \
    --region "$REGION" \
    --force >/dev/null 2>&1
  echo "✓ ECR repository '$ECR_REPO' deleted (including all images)"
else
  echo "  ECR repository not found (already deleted)"
fi

# ── Step 4b: Delete GitHub OIDC stack ──────────────────────────────────────
OIDC_STACK="github-actions-oidc"
OIDC_STATUS="$(aws cloudformation describe-stacks \
  --stack-name "$OIDC_STACK" \
  --region "$REGION" \
  --query 'Stacks[0].StackStatus' \
  --output text 2>/dev/null || echo 'NOT_FOUND')"
if [[ "$OIDC_STATUS" != "NOT_FOUND" && "$OIDC_STATUS" != "DELETE_COMPLETE" ]]; then
  echo ""
  echo "Deleting GitHub OIDC stack..."
  aws cloudformation delete-stack \
    --stack-name "$OIDC_STACK" \
    --region "$REGION"
  aws cloudformation wait stack-delete-complete \
    --stack-name "$OIDC_STACK" \
    --region "$REGION" 2>/dev/null || true
  echo "✓ OIDC stack deleted"
fi

# ── Step 5: Delete S3 data buckets ─────────────────────────────────────────
echo ""
echo "Cleaning up S3 buckets..."
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
for BUCKET in "langchain-${ACCOUNT_ID}-eu-north-1" "langchain-${ACCOUNT_ID}-eu-central-1"; do
  if aws s3api head-bucket --bucket "$BUCKET" --region "$REGION" 2>/dev/null; then
    echo "  Emptying $BUCKET..."
    aws s3 rm "s3://${BUCKET}" --recursive --region "$REGION" 2>/dev/null || true
    # Also delete versioned objects
    aws s3api list-object-versions \
      --bucket "$BUCKET" \
      --region "$REGION" \
      --query '{Objects: Versions[].{Key:Key,VersionId:VersionId}}' \
      --output json 2>/dev/null | \
      aws s3api delete-objects --bucket "$BUCKET" --delete file:///dev/stdin --region "$REGION" 2>/dev/null || true
    aws s3api list-object-versions \
      --bucket "$BUCKET" \
      --region "$REGION" \
      --query '{Objects: DeleteMarkers[].{Key:Key,VersionId:VersionId}}' \
      --output json 2>/dev/null | \
      aws s3api delete-objects --bucket "$BUCKET" --delete file:///dev/stdin --region "$REGION" 2>/dev/null || true
    aws s3api delete-bucket --bucket "$BUCKET" --region "$REGION" 2>/dev/null || true
    echo "  ✓ $BUCKET deleted"
  else
    echo "  $BUCKET not found - skipping"
  fi
done

# ── Step 6: Delete Athena workgroup ────────────────────────────────────────
echo ""
echo "Cleaning up Athena workgroup..."
WORKGROUP="project-text-to-sql"
if aws athena get-work-group --work-group "$WORKGROUP" --region "$REGION" >/dev/null 2>&1; then
  # Delete any named queries in the workgroup first
  NAMED_QUERIES="$(aws athena list-named-queries \
    --work-group "$WORKGROUP" \
    --region "$REGION" \
    --query 'NamedQueryIds' \
    --output text 2>/dev/null || echo '')"
  if [[ -n "$NAMED_QUERIES" ]]; then
    for QID in $NAMED_QUERIES; do
      aws athena delete-named-query --named-query-id "$QID" --region "$REGION" 2>/dev/null || true
    done
  fi
  # Delete the workgroup with recursive option (removes saved queries and history)
  aws athena delete-work-group \
    --work-group "$WORKGROUP" \
    --recursive-delete-option \
    --region "$REGION" 2>/dev/null || \
  # Retry without recursive if flag not supported in this CLI version
  aws athena delete-work-group \
    --work-group "$WORKGROUP" \
    --region "$REGION" 2>/dev/null || true
  echo "✓ Athena workgroup '$WORKGROUP' deleted"
else
  echo "  Workgroup not found - skipping"
fi

# ── Step 7: Delete Glue crawlers and databases ─────────────────────────────
echo ""
echo "Cleaning up Glue crawlers..."
# Delete all project crawlers (including auto-created ones by Lambda)
ALL_CRAWLERS="$(aws glue list-crawlers --region "$REGION" \
  --query "CrawlerNames[?starts_with(@, 'project-')]" \
  --output text 2>/dev/null || echo '')"
if [[ -n "$ALL_CRAWLERS" ]]; then
  for CRAWLER_NAME in $ALL_CRAWLERS; do
    aws glue stop-crawler --name "$CRAWLER_NAME" --region "$REGION" 2>/dev/null || true
    aws glue delete-crawler --name "$CRAWLER_NAME" --region "$REGION" 2>/dev/null || true
    echo "  ✓ Crawler '$CRAWLER_NAME' deleted"
  done
else
  echo "  No project crawlers found"
fi

echo "Cleaning up Glue databases..."
# Delete all project_ prefixed databases (includes auto-created ones by Lambda)
ALL_GLUE_DBS="$(aws glue get-databases --region "$REGION" \
  --query "DatabaseList[?starts_with(Name, 'project_')].Name" \
  --output text 2>/dev/null || echo '')"
if [[ -n "$ALL_GLUE_DBS" ]]; then
  for DB_NAME in $ALL_GLUE_DBS; do
    aws glue delete-database --name "$DB_NAME" --region "$REGION" 2>/dev/null || true
    echo "  ✓ Glue database '$DB_NAME' deleted"
  done
else
  echo "  No project Glue databases found"
fi

# ── Step 8: Delete CloudWatch log groups ───────────────────────────────────
echo ""
echo "Cleaning up CloudWatch log groups..."
for LOG_GROUP in "/ecs/data-architecture-ai" "/ecs/data-architecture-ai-streamlit"; do
  if aws logs describe-log-groups --log-group-name-prefix "$LOG_GROUP" --region "$REGION" \
    --query "logGroups[?logGroupName=='${LOG_GROUP}']" --output text 2>/dev/null | grep -q "$LOG_GROUP"; then
    aws logs delete-log-group --log-group-name "$LOG_GROUP" --region "$REGION" 2>/dev/null || true
    echo "  ✓ Log group '$LOG_GROUP' deleted"
  else
    echo "  $LOG_GROUP not found - skipping"
  fi
done

# ── Step 9: Force-delete stack-managed Secrets Manager secrets ─────────────
# Deleting a CloudFormation stack schedules its AWS::SecretsManager::Secret
# resources for deletion with a 30-day recovery window rather than removing
# them immediately. That leaves the secret "marked for deletion", which blocks
# a later redeploy from recreating a secret with the same name. Force-delete
# them here (no recovery window) for a true clean slate.
echo ""
echo "Cleaning up Secrets Manager secrets..."
for SECRET in \
  "cgs-ai-analyst-agent/streamlit-credentials" \
  "cgs-ai-rds-aurora/aurora-credentials" \
  "cgs-ai-redshift-serverless/redshift-credentials"; do
  if aws secretsmanager describe-secret --secret-id "$SECRET" --region "$REGION" >/dev/null 2>&1; then
    aws secretsmanager delete-secret \
      --secret-id "$SECRET" \
      --force-delete-without-recovery \
      --region "$REGION" >/dev/null 2>&1 || true
    echo "  ✓ Secret '$SECRET' deleted (no recovery window)"
  else
    echo "  $SECRET not found - skipping"
  fi
done

# ── Done ───────────────────────────────────────────────────────────────────
echo ""
echo "=========================================="
echo "✅ TEARDOWN COMPLETE - ALL RESOURCES DELETED"
echo "=========================================="
echo ""
echo "Everything has been removed. To redeploy from scratch:"
echo "  ./deploy-changeset.sh --auto"
