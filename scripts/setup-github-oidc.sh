#!/usr/bin/env bash
# Setup GitHub Actions OIDC role for CI/CD deployments.
#
# Usage:
#   ./scripts/setup-github-oidc.sh
#
# What it does:
#   1. Deploys the cloudformation-github-oidc.yml stack
#   2. Gets the role ARN
#   3. Sets it as a GitHub secret (requires gh CLI)
#
# Prerequisites:
#   - AWS CLI configured with admin permissions
#   - gh CLI installed and authenticated (brew install gh && gh auth login)
set -euo pipefail

REGION="${AWS_REGION:-eu-north-1}"
STACK_NAME="github-actions-oidc"
TEMPLATE_FILE="cloudformation-github-oidc.yml"

echo "=========================================="
echo "GitHub Actions OIDC Setup"
echo "=========================================="
echo "Region: $REGION"
echo "Stack:  $STACK_NAME"
echo ""

# ── Check prerequisites ────────────────────────────────────────────────────
if ! command -v gh &>/dev/null; then
  echo "⚠️  'gh' CLI not found. Install with: brew install gh"
  echo "   After this script deploys the stack, you'll need to set the secret manually:"
  echo "   gh secret set AWS_DEPLOY_ROLE_ARN --body <role-arn>"
  GH_AVAILABLE=false
else
  GH_AVAILABLE=true
fi

# ── Check if OIDC provider already exists ──────────────────────────────────
EXISTING_OIDC="$(aws iam list-open-id-connect-providers \
  --query "OpenIDConnectProviderList[?ends_with(Arn, '/token.actions.githubusercontent.com')].Arn" \
  --output text 2>/dev/null || echo '')"

OIDC_PARAM=""
if [[ -n "$EXISTING_OIDC" && "$EXISTING_OIDC" != "None" ]]; then
  echo "Found existing GitHub OIDC provider: $EXISTING_OIDC"
  OIDC_PARAM="OIDCProviderArn=$EXISTING_OIDC"
fi

# ── Deploy the stack ───────────────────────────────────────────────────────
echo ""
echo "Deploying OIDC role stack..."
DEPLOY_ARGS=(
  --template-file "$TEMPLATE_FILE"
  --stack-name "$STACK_NAME"
  --capabilities CAPABILITY_NAMED_IAM
  --region "$REGION"
  --no-fail-on-empty-changeset
)

if [[ -n "$OIDC_PARAM" ]]; then
  DEPLOY_ARGS+=(--parameter-overrides "$OIDC_PARAM")
fi

aws cloudformation deploy "${DEPLOY_ARGS[@]}"
echo "✓ Stack deployed"

# ── Get the role ARN ───────────────────────────────────────────────────────
ROLE_ARN="$(aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --region "$REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='DeployRoleArn'].OutputValue" \
  --output text)"

echo ""
echo "=========================================="
echo "✅ OIDC Role Created"
echo "=========================================="
echo ""
echo "Role ARN: $ROLE_ARN"
echo ""

# ── Set GitHub secret ──────────────────────────────────────────────────────
if $GH_AVAILABLE; then
  echo "Setting GitHub secret AWS_DEPLOY_ROLE_ARN..."
  gh secret set AWS_DEPLOY_ROLE_ARN --body "$ROLE_ARN"
  echo "✓ GitHub secret set"
  echo ""
  echo "Done! Push to main to trigger a deployment:"
  echo "  git push origin main"
else
  echo "Set the secret manually:"
  echo "  gh secret set AWS_DEPLOY_ROLE_ARN --body \"$ROLE_ARN\""
  echo ""
  echo "Then push to main:"
  echo "  git push origin main"
fi
