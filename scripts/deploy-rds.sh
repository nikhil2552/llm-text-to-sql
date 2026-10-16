#!/usr/bin/env bash
# Deploy Aurora Serverless v2 (MySQL) in the same VPC as the main stack.
#
# Usage:
#   ./scripts/deploy-rds.sh          # Review mode
#   ./scripts/deploy-rds.sh --auto   # Full auto: deploy + print connection config
set -euo pipefail

TEMPLATE_FILE="cloudformation-rds-aurora.yml"
STACK_NAME="cgs-ai-rds-aurora"
MAIN_STACK_NAME="${MAIN_STACK_NAME:-cgs-ai-analyst-agent-project}"
REGION="${AWS_REGION:-eu-north-1}"
AUTO_MODE=false

for arg in "$@"; do
  case "$arg" in
    --auto) AUTO_MODE=true ;;
  esac
done

# Verify main stack exists (we need its exports)
MAIN_STATUS="$(aws cloudformation describe-stacks \
  --stack-name "$MAIN_STACK_NAME" \
  --region "$REGION" \
  --query 'Stacks[0].StackStatus' \
  --output text 2>/dev/null || echo 'NOT_FOUND')"

if [[ "$MAIN_STATUS" == "NOT_FOUND" || "$MAIN_STATUS" == "DELETE_COMPLETE" ]]; then
  echo "ERROR: Main stack '$MAIN_STACK_NAME' not found." >&2
  echo "Deploy it first: ./deploy-changeset.sh --auto" >&2
  exit 1
fi

echo "=========================================="
echo "Aurora Serverless v2 Deployment"
echo "=========================================="
echo "RDS Stack:   $STACK_NAME"
echo "Main Stack:  $MAIN_STACK_NAME (status: $MAIN_STATUS)"
echo "Region:      $REGION"
echo "Mode:        $(if $AUTO_MODE; then echo 'AUTO'; else echo 'REVIEW'; fi)"
echo ""

# Validate
echo "Validating template..."
aws cloudformation validate-template \
  --template-body file://"$TEMPLATE_FILE" \
  --region "$REGION" > /dev/null && echo "✓ Template valid"

# Change set
CHANGE_SET_NAME="${STACK_NAME}-$(date +%s)"
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

echo "Creating change set ($CHANGE_SET_TYPE)..."
aws cloudformation create-change-set \
  --stack-name "$STACK_NAME" \
  --change-set-name "$CHANGE_SET_NAME" \
  --change-set-type "$CHANGE_SET_TYPE" \
  --template-body "file://${TEMPLATE_FILE}" \
  --capabilities CAPABILITY_IAM \
  --region "$REGION" \
  --parameters \
    "ParameterKey=MainStackName,ParameterValue=${MAIN_STACK_NAME}"

echo "Waiting for change set..."
aws cloudformation wait change-set-create-complete \
  --stack-name "$STACK_NAME" \
  --change-set-name "$CHANGE_SET_NAME" \
  --region "$REGION" 2>/dev/null || true

echo ""
aws cloudformation describe-change-set \
  --stack-name "$STACK_NAME" \
  --change-set-name "$CHANGE_SET_NAME" \
  --region "$REGION" \
  --query 'Changes[*].[Type, ResourceChange.Action, ResourceChange.LogicalResourceId, ResourceChange.ResourceType]' \
  --output table

if $AUTO_MODE; then
  echo ""
  echo "Executing change set..."
  aws cloudformation execute-change-set \
    --stack-name "$STACK_NAME" \
    --change-set-name "$CHANGE_SET_NAME" \
    --region "$REGION"

  echo "Waiting for stack (Aurora takes 5-10 minutes)..."
  if [[ "$CHANGE_SET_TYPE" == "CREATE" ]]; then
    aws cloudformation wait stack-create-complete --stack-name "$STACK_NAME" --region "$REGION"
  else
    aws cloudformation wait stack-update-complete --stack-name "$STACK_NAME" --region "$REGION"
  fi
  echo "✓ Aurora stack complete"

  echo ""
  echo "=========================================="
  echo "✅ Aurora Serverless v2 deployed"
  echo "=========================================="
  echo ""
  echo "Connection config (paste into config/connections/rds-mysql.yaml):"
  echo ""
  aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='ConnectionConfig'].OutputValue" \
    --output text
  echo ""
  echo "Secret name:"
  aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='SecretName'].OutputValue" \
    --output text
else
  echo ""
  echo "To deploy: ./scripts/deploy-rds.sh --auto"
fi
