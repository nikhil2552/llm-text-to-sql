#!/usr/bin/env bash
# Build the API image, push to ECR, and optionally scale/start the ECS service.
set -euo pipefail

REGION="${AWS_REGION:-eu-north-1}"
STACK_NAME="${STACK_NAME:-cgs-ai-analyst-agent-project}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
DESIRED_COUNT="${DESIRED_COUNT:-1}"

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
REPO_URI="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/data-architecture-ai"
IMAGE="${REPO_URI}:${IMAGE_TAG}"

if ! aws ecr describe-repositories --repository-names data-architecture-ai --region "$REGION" >/dev/null 2>&1; then
  STACK_STATUS="$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$REGION" \
    --query 'Stacks[0].StackStatus' \
    --output text 2>/dev/null || echo 'NOT_FOUND')"
  echo "ERROR: ECR repository 'data-architecture-ai' does not exist in ${REGION}." >&2
  echo "" >&2
  echo "The repository is created by CloudFormation. Deploy the stack first:" >&2
  echo "  1. ./deploy-changeset.sh" >&2
  echo "  2. Execute the change set (command printed by the script)" >&2
  echo "  3. Wait until stack status is CREATE_COMPLETE:" >&2
  echo "     aws cloudformation wait stack-create-complete --stack-name ${STACK_NAME} --region ${REGION}" >&2
  echo "  4. Re-run: DESIRED_COUNT=1 ./scripts/push_ecr.sh" >&2
  echo "" >&2
  echo "Current stack status: ${STACK_STATUS}" >&2
  if [[ "$STACK_STATUS" == "REVIEW_IN_PROGRESS" ]]; then
    echo "Your stack is in REVIEW_IN_PROGRESS — a change set was created but not executed yet." >&2
  fi
  exit 1
fi

echo "Logging in to ECR (${REGION})..."
aws ecr get-login-password --region "$REGION" | \
  docker login --username AWS --password-stdin "${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"

# ECS Fargate runs linux/amd64. On Apple Silicon, the default build is arm64 — must cross-build.
PLATFORM="${DOCKER_PLATFORM:-linux/amd64}"
echo "Building ${IMAGE} for platform ${PLATFORM} (required for ECS Fargate)..."
docker buildx build \
  --platform "${PLATFORM}" \
  -t "$IMAGE" \
  --push \
  .

if aws cloudformation describe-stacks --stack-name "$STACK_NAME" --region "$REGION" >/dev/null 2>&1; then
  echo "Forcing ECS service redeployment (desired count=${DESIRED_COUNT})..."
  CLUSTER="$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='EcsClusterName'].OutputValue" \
    --output text)"
  SERVICE="$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='EcsServiceName'].OutputValue" \
    --output text)"

  if [[ -n "$CLUSTER" && -n "$SERVICE" && "$CLUSTER" != "None" && "$SERVICE" != "None" ]]; then
    aws ecs update-service \
      --cluster "$CLUSTER" \
      --service "$SERVICE" \
      --force-new-deployment \
      --desired-count "$DESIRED_COUNT" \
      --region "$REGION" \
      >/dev/null
    echo "ECS service ${SERVICE} redeployment started."
  fi

  # Also redeploy Streamlit service
  STREAMLIT_SERVICE="data-architecture-ai-streamlit"
  STREAMLIT_COUNT="${STREAMLIT_DESIRED_COUNT:-1}"
  STREAMLIT_STATUS="$(aws ecs describe-services \
    --cluster "$CLUSTER" \
    --services "$STREAMLIT_SERVICE" \
    --region "$REGION" \
    --query 'services[0].status' \
    --output text 2>/dev/null || echo 'NOT_FOUND')"
  if [[ "$STREAMLIT_STATUS" == "ACTIVE" ]]; then
    aws ecs update-service \
      --cluster "$CLUSTER" \
      --service "$STREAMLIT_SERVICE" \
      --force-new-deployment \
      --desired-count "$STREAMLIT_COUNT" \
      --region "$REGION" \
      >/dev/null
    echo "ECS service ${STREAMLIT_SERVICE} redeployment started (desired count=${STREAMLIT_COUNT})."
  fi
else
  echo "Stack ${STACK_NAME} not found. Deploy CloudFormation first, then re-run this script."
fi

ALB_URL="$(aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --region "$REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='LoadBalancerUrl'].OutputValue" \
  --output text 2>/dev/null || true)"

echo ""
echo "Image pushed: ${IMAGE}"
if [[ -n "$ALB_URL" && "$ALB_URL" != "None" ]]; then
  echo "API URL: ${ALB_URL}"
  echo "Health:  curl ${ALB_URL}/health"
  echo "Query:   curl -X POST ${ALB_URL}/query -H 'Content-Type: application/json' -d '{\"question\":\"How many rows?\"}'"
fi

STREAMLIT_URL="$(aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --region "$REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='StreamlitUrl'].OutputValue" \
  --output text 2>/dev/null || true)"
if [[ -n "$STREAMLIT_URL" && "$STREAMLIT_URL" != "None" ]]; then
  echo "Streamlit: ${STREAMLIT_URL}"
fi
