#!/usr/bin/env bash
# Configure S3 event notification on a pre-existing bucket to trigger the
# crawler Lambda. Only needed when CreatePrimaryDataBucket=false (bucket
# already existed before the stack was deployed).
#
# Usage: ./scripts/configure_s3_notification.sh
set -euo pipefail

REGION="${AWS_REGION:-eu-north-1}"
STACK_NAME="${STACK_NAME:-cgs-ai-analyst-agent-project}"

# Resolve values from stack outputs/resources
LAMBDA_ARN="$(aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --region "$REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='CrawlerTriggerLambdaArn'].OutputValue" \
  --output text)"

BUCKET_NAME="$(aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --region "$REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='ProjectfilesBucketName'].OutputValue" \
  --output text)"

if [[ -z "$LAMBDA_ARN" || "$LAMBDA_ARN" == "None" ]]; then
  echo "ERROR: Could not resolve CrawlerTriggerLambdaArn from stack outputs." >&2
  echo "Deploy the stack first: ./deploy-changeset.sh" >&2
  exit 1
fi

echo "Bucket:  $BUCKET_NAME"
echo "Lambda:  $LAMBDA_ARN"
echo ""

# Apply the notification configuration
NOTIFICATION_CONFIG=$(cat <<EOF
{
  "LambdaFunctionConfigurations": [
    {
      "Id": "S3CrawlerTrigger",
      "LambdaFunctionArn": "${LAMBDA_ARN}",
      "Events": ["s3:ObjectCreated:*"]
    }
  ]
}
EOF
)

echo "Applying S3 event notification..."
aws s3api put-bucket-notification-configuration \
  --bucket "$BUCKET_NAME" \
  --notification-configuration "$NOTIFICATION_CONFIG" \
  --region "$REGION"

echo "✓ S3 notification configured. Any file upload to s3://${BUCKET_NAME}/ will trigger the crawler Lambda."
