#!/usr/bin/env bash
# Read VPC outputs from the deployed CloudFormation stack.
# The VPC is now created by the stack itself — there is no default-VPC dependency.
# This script is used by deploy-changeset.sh only to display post-deploy info.
set -euo pipefail

REGION="${AWS_REGION:-eu-north-1}"
STACK_NAME="${STACK_NAME:-cgs-ai-analyst-agent-project}"

STACK_STATUS="$(aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --region "$REGION" \
  --query 'Stacks[0].StackStatus' \
  --output text 2>/dev/null || echo 'NOT_FOUND')"

if [[ "$STACK_STATUS" == "NOT_FOUND" || "$STACK_STATUS" == "DELETE_COMPLETE" ]]; then
  echo "Stack '$STACK_NAME' not yet deployed — VPC will be created on first deploy." >&2
  echo "VPC_ID="
  echo "PUBLIC_SUBNET_IDS="
  echo "PRIVATE_SUBNET_IDS="
  exit 0
fi

get_output() {
  aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" \
    --output text 2>/dev/null || echo ""
}

VPC_ID="$(get_output VpcId)"
PUBLIC_SUBNET_IDS="$(get_output PublicSubnetIds)"
PRIVATE_SUBNET_IDS="$(get_output PrivateSubnetIds)"

echo "VPC_ID=${VPC_ID}"
echo "PUBLIC_SUBNET_IDS=${PUBLIC_SUBNET_IDS}"
echo "PRIVATE_SUBNET_IDS=${PRIVATE_SUBNET_IDS}"
echo ""
echo "Stack-managed VPC: ${VPC_ID}"
echo "  Public subnets  (ALB):       ${PUBLIC_SUBNET_IDS}"
echo "  Private subnets (ECS tasks): ${PRIVATE_SUBNET_IDS}"
