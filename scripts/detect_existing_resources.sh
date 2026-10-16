#!/usr/bin/env bash
# Detect existing AWS resources and emit shell exports for CloudFormation parameters.
set -euo pipefail

REGION="${AWS_REGION:-eu-north-1}"
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"

PRIMARY_BUCKET="langchain-${ACCOUNT_ID}-eu-north-1"
ATHENA_WORKGROUP="project-text-to-sql"
LIBRARY_DB="project_library_db"
CARS_DB="project_cars_db"
LOG_GROUP="/ecs/data-architecture-ai"

resource_exists() {
  "$@" >/dev/null 2>&1
}

if resource_exists aws s3api head-bucket --bucket "$PRIMARY_BUCKET"; then
  CREATE_PRIMARY="false"
else
  CREATE_PRIMARY="true"
fi

# Reuse the Athena workgroup ONLY when it exists AND is still ENABLED. A
# deleted workgroup lingers in the API with State=DELETED (and get-work-group
# may fail); either case must report CREATE=true so the stack recreates it.
# The `|| echo ''` keeps `set -e` happy when the workgroup is absent.
WG_STATE="$(aws athena get-work-group --work-group "$ATHENA_WORKGROUP" --region "$REGION" \
  --query 'WorkGroup.State' --output text 2>/dev/null || echo '')"
if [[ "$WG_STATE" == "ENABLED" ]]; then
  CREATE_ATHENA="false"
else
  CREATE_ATHENA="true"
fi

if resource_exists aws glue get-database --name "$LIBRARY_DB" --region "$REGION"; then
  CREATE_LIBRARY_DB="false"
else
  CREATE_LIBRARY_DB="true"
fi

if resource_exists aws glue get-database --name "$CARS_DB" --region "$REGION"; then
  CREATE_CARS_DB="false"
else
  CREATE_CARS_DB="true"
fi

# Check if CloudWatch log group already exists (prevents ResourceExistenceCheck failure)
if aws logs describe-log-groups --log-group-name-prefix "$LOG_GROUP" --region "$REGION" \
     --query "logGroups[?logGroupName=='$LOG_GROUP'].logGroupName" --output text 2>/dev/null | grep -q "$LOG_GROUP"; then
  CREATE_LOG_GROUP="false"
else
  CREATE_LOG_GROUP="true"
fi

echo "PRIMARY_DATA_BUCKET_NAME=$PRIMARY_BUCKET"
echo "CREATE_PRIMARY_DATA_BUCKET=$CREATE_PRIMARY"
echo "CREATE_ATHENA_WORKGROUP=$CREATE_ATHENA"
echo "ATHENA_WORKGROUP_NAME=$ATHENA_WORKGROUP"
echo "CREATE_LIBRARY_GLUE_DATABASE=$CREATE_LIBRARY_DB"
echo "CREATE_CARS_GLUE_DATABASE=$CREATE_CARS_DB"
echo "LIBRARY_GLUE_DATABASE_NAME=$LIBRARY_DB"
echo "CARS_GLUE_DATABASE_NAME=$CARS_DB"
echo "CREATE_APP_LOG_GROUP=$CREATE_LOG_GROUP"
echo ""
echo "Reuse summary:"
echo "  Primary bucket:   create=$CREATE_PRIMARY  name=$PRIMARY_BUCKET"
echo "  Athena workgroup: create=$CREATE_ATHENA  name=$ATHENA_WORKGROUP"
echo "  Library Glue DB:  create=$CREATE_LIBRARY_DB"
echo "  Cars Glue DB:     create=$CREATE_CARS_DB"
echo "  Log group:        create=$CREATE_LOG_GROUP  name=$LOG_GROUP"
