# CloudFormation Deployment Guide

This guide shows how to deploy the `cloudformation-template-validated.yml` template using AWS CloudFormation change sets.

## Quick Redeployment Cheat Sheet

After making code changes, use these commands to update the running stack:

```bash
# Build image via GitHub Actions (no Docker Desktop needed) — recommended
gh workflow run build-and-push-image

# Or rebuild image locally + redeploy both ECS services (requires Docker Desktop)
./scripts/push_ecr.sh

# Redeploy only the Streamlit UI service (no rebuild, uses existing image)
aws ecs update-service --cluster data-architecture-ai \
  --service data-architecture-ai-streamlit \
  --force-new-deployment --region eu-north-1

# Redeploy only the FastAPI service (no rebuild, uses existing image)
aws ecs update-service --cluster data-architecture-ai \
  --service data-architecture-ai \
  --force-new-deployment --region eu-north-1

# Full deploy (CloudFormation + image + CI/CD setup)
./deploy-changeset.sh --auto

# Full deploy + RDS Aurora + Redshift Serverless
./deploy-changeset.sh --auto --with-databases

# Tear down everything (all stacks, buckets, databases)
make teardown

# Or via make
make deploy-all
```

### Services Overview

| Service | Port | Entrypoint | Purpose |
|---------|------|-----------|---------|
| `data-architecture-ai` | 8080 | `scripts/serve.py` | FastAPI REST API (`/health`, `/query`) |
| `data-architecture-ai-streamlit` | 8501 | `streamlit run scripts/streamlit_app.py` | Browser chat UI |

Both use the same Docker image with different entrypoints. The Streamlit UI calls AWS directly via VPC endpoints (local mode) and requires `APP_USERNAME`/`APP_PASSWORD` for authentication. The API service is available externally for programmatic access (optionally secured with `API_KEY`).

### CloudFormation Stacks

| Stack | Template | Deployed by |
|-------|----------|-------------|
| `cgs-ai-analyst-agent-project` | `cloudformation-template-validated.yml` | `--auto` (always) |
| `github-actions-oidc` | `cloudformation-github-oidc.yml` | `--auto` (always) |
| `cgs-ai-rds-aurora` | `cloudformation-rds-aurora.yml` | `--with-databases` |
| `cgs-ai-redshift-serverless` | `cloudformation-redshift-serverless.yml` | `--with-databases` |

### Architecture

```
Internet → ALB:80   → FastAPI (ECS private subnet) → Bedrock/Athena via VPC endpoints
Internet → ALB:8501 → Streamlit (ECS private subnet) → Bedrock/Athena via VPC endpoints
                                                     → RDS Aurora (private subnet, port 3306)
                                                     → Redshift Serverless (private subnet, port 5439)
```

---

## Prerequisites

- AWS CLI installed and configured with credentials
- IAM permissions to create CloudFormation stacks, IAM roles, EC2 (VPC/subnets/endpoints), S3, Glue, Athena, ECS, ECR resources
- A deployed AWS region (default: `eu-north-1`)
- **Docker Desktop** — required only for building/pushing container images (see below)

### Docker Desktop Requirements

Docker Desktop is **only needed** when building and pushing container images locally. For most workflows, use GitHub Actions instead:

| Task | Docker Desktop Required? |
|------|:------------------------:|
| Build image via GitHub Actions (`gh workflow run build-and-push-image`) | No |
| Push to main (auto-deploys via `deploy.yml`) | No |
| Building images locally (`./scripts/push_ecr.sh`) | Yes |
| Full auto deploy locally (`./deploy-changeset.sh --auto`) | Yes |
| `make deploy-all` | Yes |

**Recommended:** Use `gh workflow run build-and-push-image` to build and deploy without Docker Desktop.

> **No VPC required beforehand.** The stack creates its own VPC (10.0.0.0/16), public subnets
> (ALB), private subnets (ECS tasks), and all VPC endpoints. No NAT gateway is used — AWS
> service traffic (ECR, Bedrock, Athena, Glue, Secrets Manager, S3, CloudWatch Logs) flows
> through VPC interface/gateway endpoints at no NAT cost.

## Quick Start

### Option 1: Fully automated (one command)

Deploys the stack, builds the Docker image, pushes to ECR, and starts the ECS service:

```bash
chmod +x deploy-changeset.sh scripts/push_ecr.sh
./deploy-changeset.sh --auto
```

Or using make:

```bash
make deploy-all
```

This does everything end-to-end: validate → create stack → wait → build image → push to ECR → start service → print API URL.

### Option 2: Review first, then deploy

```bash
./deploy-changeset.sh        # Shows what will change (review mode)
./deploy-changeset.sh --auto # Execute after reviewing
```

Or step by step with make:

```bash
make deploy      # Review mode — shows change set summary
make deploy-all  # Full auto — deploys everything
```

**S3 Buckets created:**
- `langchain-<account-id>-eu-north-1` — primary data bucket
- `langchain-<account-id>-eu-central-1` — secondary data bucket

### Option 2: Manual AWS CLI commands

#### 1. Set environment variables
```bash
export AWS_REGION="eu-north-1"
export STACK_NAME="cgs-ai-analyst-agent-project"
```

#### 2. Validate template
```bash
aws cloudformation validate-template \
  --template-body file://cloudformation-template-validated.yml \
  --region "$AWS_REGION"
```

#### 3. Create a change set

No VPC parameters needed — the stack manages its own network.

```bash
CHANGE_SET_NAME="${STACK_NAME}-changeset-$(date +%s)"

eval "$(bash scripts/detect_existing_resources.sh | grep -E '^[A-Z_]+=')"

CFN_PARAMETERS=$(cat <<EOF
[
  {"ParameterKey": "DesiredCount",            "ParameterValue": "0"},
  {"ParameterKey": "PrimaryDataBucketName",   "ParameterValue": "${PRIMARY_DATA_BUCKET_NAME}"},
  {"ParameterKey": "CentralDataBucketName",   "ParameterValue": "${CENTRAL_DATA_BUCKET_NAME}"},
  {"ParameterKey": "CreatePrimaryDataBucket", "ParameterValue": "${CREATE_PRIMARY_DATA_BUCKET}"},
  {"ParameterKey": "CreateCentralDataBucket", "ParameterValue": "${CREATE_CENTRAL_DATA_BUCKET}"}
]
EOF
)

# First deploy: CREATE. Later updates: UPDATE.
if aws cloudformation describe-stacks --stack-name "$STACK_NAME" --region "$AWS_REGION" >/dev/null 2>&1; then
  CHANGE_SET_TYPE="UPDATE"
else
  CHANGE_SET_TYPE="CREATE"
fi

aws cloudformation create-change-set \
  --stack-name "$STACK_NAME" \
  --change-set-name "$CHANGE_SET_NAME" \
  --change-set-type "$CHANGE_SET_TYPE" \
  --template-body file://cloudformation-template-validated.yml \
  --capabilities CAPABILITY_IAM \
  --region "$AWS_REGION" \
  --parameters "$CFN_PARAMETERS" \
  --tags \
    "Key=DeployedBy,Value=$(aws iam get-user --query 'User.UserName' --output text)" \
    "Key=Environment,Value=production"
```

> **Troubleshooting:** If you see `Stack [...] does not exist`, add `--change-set-type CREATE`.
> Or use `./deploy-changeset.sh`, which sets this automatically.

#### 4. Review the change set
```bash
aws cloudformation describe-change-set \
  --stack-name "$STACK_NAME" \
  --change-set-name "$CHANGE_SET_NAME" \
  --region "$AWS_REGION" \
  --output table
```

#### 5. Execute the change set
```bash
aws cloudformation execute-change-set \
  --stack-name "$STACK_NAME" \
  --change-set-name "$CHANGE_SET_NAME" \
  --region "$AWS_REGION"
```

#### 6. Monitor stack creation
```bash
aws cloudformation wait stack-create-complete \
  --stack-name "$STACK_NAME" \
  --region "$AWS_REGION"
```

#### 7. View stack outputs
```bash
aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --region "$AWS_REGION" \
  --query 'Stacks[0].Outputs'
```

## Understanding Change Sets

A **change set** is a preview of changes that will be applied to your CloudFormation stack. Benefits:

- **Review before applying**: See exactly what will be created, modified, or deleted
- **Safe deployments**: Catch unintended changes before they're applied
- **Audit trail**: Track who deployed what and when (via tags)
- **Rollback capability**: Revert if needed

## Parameters Explained
The stack creates its own VPC and subnets — no `VpcId` or `PublicSubnetIds` parameters are needed. The deployment script auto-detects existing data-layer resources (S3 buckets, Glue DBs, Athena workgroup, CloudWatch log group) and passes the appropriate `Create*` flags.

## Capabilities

This template requires **CAPABILITY_IAM** because it creates IAM roles and policies. Pass this via `--capabilities CAPABILITY_IAM`.

## Tagging for Audit and Governance

The deployment script automatically tags the stack with:

- `DeployedBy`: IAM user who deployed it (auto-detected)
- `DeploymentDate`: UTC timestamp of deployment
- `Environment`: Tag to indicate environment (prod/dev/staging)

Add custom tags in the script or via AWS CLI:
```bash
--tags "Key=CostCenter,Value=engineering" "Key=Owner,Value=team@example.com"
```

## Cleanup

To tear down all infrastructure at once:

```bash
make teardown
# or: ./scripts/teardown.sh --force  (skip confirmation)
```

This deletes everything in sequence:
1. Scales ECS services to 0
2. Deletes RDS Aurora stack (takes a final snapshot)
3. Deletes Redshift Serverless stack
4. Deletes the main stack (VPC, ECS, ALB, Lambda, VPC endpoints)
5. Deletes GitHub OIDC stack
6. Deletes ECR repository and all images
7. Empties and deletes S3 data buckets
8. Deletes Athena workgroup
9. Deletes all Glue crawlers and databases
10. Deletes CloudWatch log groups

Takes 10-15 minutes total (Aurora snapshot is the slowest step).

To delete only the main stack:

```bash
aws cloudformation delete-stack \
  --stack-name "$STACK_NAME" \
  --region "$AWS_REGION"

aws cloudformation wait stack-delete-complete \
  --stack-name "$STACK_NAME" \
  --region "$AWS_REGION"
```

## Troubleshooting

### Resource name conflict (bucket, Athena workgroup, Glue DB already exists)

If stack creation fails with errors like:

```text
Resource of type 'AWS::S3::Bucket' with identifier 'langchain-...' already exists.
Resource of type 'AWS::Athena::WorkGroup' with identifier 'project-text-to-sql' already exists.
Resource of type 'AWS::Logs::LogGroup' with identifier '/ecs/data-architecture-ai' already exists.
```

Those resources were created outside this stack (or by a previous failed deploy). The deploy script now **detects and reuses** them automatically:

```bash
bash scripts/detect_existing_resources.sh   # preview what will be reused vs created
./deploy-changeset.sh                       # passes Create*=false for existing resources
```

You should **not** see `ProjectDataBucketNorth` or `ProjectAthenaWorkgroup` in the change set summary when reuse is working.

### Stuck stack (`REVIEW_IN_PROGRESS` or `ROLLBACK_COMPLETE`)

Delete the failed stack, then redeploy:

```bash
aws cloudformation delete-stack \
  --stack-name cgs-ai-analyst-agent-project \
  --region eu-north-1

aws cloudformation wait stack-delete-complete \
  --stack-name cgs-ai-analyst-agent-project \
  --region eu-north-1

./deploy-changeset.sh
```

### CannotPullContainerError: platform linux/amd64

ECS Fargate requires **linux/amd64** images. If you built on an **Apple Silicon Mac** without cross-compilation, the image in ECR is **arm64** only.

Rebuild and push with the project script (it builds for amd64 automatically):

```bash
DESIRED_COUNT=1 ./scripts/push_ecr.sh
```

Or manually:

```bash
docker buildx build --platform linux/amd64 -t <ecr-uri>:latest --push .
```

### Athena: ManagedQueryResultsConfiguration and ResultConfiguration

If you see:

```text
ManagedQueryResultsConfiguration and ResultConfiguration cannot be set together
```

Your Athena workgroup (`project-text-to-sql`) uses **managed query results**. The app now detects this and does not send an S3 staging path. **Redeploy the ECS image** after pulling the latest code:

```bash
DESIRED_COUNT=1 ./scripts/push_ecr.sh
```

For local Streamlit/API testing, restart the app after `git pull`.

### API error 500: Bedrock inference profile required

If logs show:

```text
Invocation of model ID amazon.nova-micro-v1:0 with on-demand throughput isn't supported.
Retry your request with the ID or ARN of an inference profile
```

Set:

```bash
export BEDROCK_MODEL=eu.amazon.nova-micro-v1:0
```

Redeploy ECS (`./scripts/push_ecr.sh`) or restart local Streamlit. The app auto-maps legacy model IDs to `eu.amazon.nova-micro-v1:0` in EU regions.

### Athena AccessDenied: ListTableMetadata

The PyAthena/SQLAlchemy driver can call `athena:ListTableMetadata` when connecting. The ECS task role must include metadata permissions (added in the template).

Update the stack, then restart ECS tasks:

```bash
./deploy-changeset.sh
# execute the change set, wait for UPDATE_COMPLETE

aws ecs update-service \
  --cluster data-architecture-ai \
  --service data-architecture-ai \
  --force-new-deployment \
  --region eu-north-1
```

Or attach the missing actions to role `cgs-ai-analyst-agent-project-EcsTaskRole-*` in IAM Console:
`athena:ListTableMetadata`, `athena:GetTableMetadata`, `athena:ListDatabases`, `athena:GetDatabase`, `athena:GetDataCatalog` on `arn:aws:athena:REGION:ACCOUNT:datacatalog/*` and `database/*`.

### Change set shows no changes
- If the change set has no changes, the stack either already exists with identical parameters, or there's a syntax issue. Review the template.

### Insufficient permissions
- Ensure your IAM user has `cloudformation:*`, `iam:*`, `s3:*`, and `glue:*` permissions.

### Template format error
- Validate the YAML syntax: `aws cloudformation validate-template --template-body file://cloudformation-template-validated.yml`

### Stack creation timeout
- If the stack creation takes too long, check CloudFormation events for errors: `aws cloudformation describe-stack-events --stack-name "$STACK_NAME" --region "$AWS_REGION"`

### Streamlit UI credentials (stack-managed)

The CloudFormation stack creates and owns the `cgs-ai-analyst-agent/streamlit-credentials`
Secrets Manager secret — you do not create it manually before deploying. At create time,
`APP_USERNAME` is seeded from the `StreamlitUsername` parameter (default `admin`) and
`APP_PASSWORD` is auto-generated (24 characters). The generated password is set only on
create; CloudFormation does not overwrite it on later stack updates. Retrieve the login with:

```bash
aws secretsmanager get-secret-value \
  --secret-id "cgs-ai-analyst-agent/streamlit-credentials" \
  --query SecretString --output text --region eu-north-1
```

To set your own password, rotate it out-of-band with `aws secretsmanager put-secret-value`
(see below) and force a new Streamlit deployment.

**Fail-safe reconciliation:** `deploy-changeset.sh` auto-heals a common edge case. If a
secret named `cgs-ai-analyst-agent/streamlit-credentials` already exists but is *not* owned
by the stack (e.g. created by hand during troubleshooting), the script removes that orphan
before creating the change set so CloudFormation can create and own it — a secret already
managed by the stack is never touched. This makes repeated deploys idempotent regardless of
starting state.

### Streamlit 503: secret marked for deletion

If the Streamlit ECS service fails with:

```text
unable to retrieve secret ... InvalidRequestException: You can't perform this operation on the secret because it was marked for deletion.
```

A previous teardown scheduled the secret for deletion (30-day retention). Restore it:

```bash
aws secretsmanager restore-secret \
  --secret-id "cgs-ai-analyst-agent/streamlit-credentials" \
  --region eu-north-1

aws secretsmanager put-secret-value \
  --secret-id "cgs-ai-analyst-agent/streamlit-credentials" \
  --secret-string '{"APP_USERNAME":"admin","APP_PASSWORD":"your-password"}' \
  --region eu-north-1

aws ecs update-service --cluster data-architecture-ai \
  --service data-architecture-ai-streamlit \
  --force-new-deployment --region eu-north-1
```

The secret JSON keys must be `APP_USERNAME` and `APP_PASSWORD` (matching the ECS task definition's secret references).

### Streamlit 503: secret JSON key mismatch

If the service fails with:

```text
retrieved secret from Secrets Manager did not contain json key APP_USERNAME
```

The secret exists but uses wrong keys (e.g., `username` instead of `APP_USERNAME`). Fix:

```bash
aws secretsmanager put-secret-value \
  --secret-id "cgs-ai-analyst-agent/streamlit-credentials" \
  --secret-string '{"APP_USERNAME":"admin","APP_PASSWORD":"your-password"}' \
  --region eu-north-1
```

Then force redeploy the Streamlit service.

### Data source not configured (empty Glue tables)

After a fresh deploy, Athena queries fail because Glue databases have no tables. You need to:

1. Upload sample data to S3:
   ```bash
   BUCKET="langchain-$(aws sts get-caller-identity --query Account --output text)-eu-north-1"
   aws s3 cp POC/data/s3_library_data.json "s3://${BUCKET}/library/" --region eu-north-1
   aws s3 cp POC/data/s3_cars_data_normalized.csv "s3://${BUCKET}/cars/" --region eu-north-1
   ```

2. The Lambda trigger should auto-start crawlers. If not, start them manually:
   ```bash
   aws glue start-crawler --name project-library-crawler --region eu-north-1
   aws glue start-crawler --name project-cars-crawler --region eu-north-1
   ```

3. Wait 1-2 minutes, then verify tables exist:
   ```bash
   aws glue get-tables --database-name project_library_db --region eu-north-1 --query 'TableList[*].Name'
   aws glue get-tables --database-name project_cars_db --region eu-north-1 --query 'TableList[*].Name'
   ```

### Glue crawler fails: AccessDenied on sts:AssumeRole

After redeployment, crawlers may reference an old IAM role ARN from a previous stack. Fix by updating the crawler role:

```bash
ROLE_NAME=$(aws iam list-roles --query 'Roles[?contains(RoleName, `LibraryCrawler`)].RoleName' --output text)
ROLE_ARN="arn:aws:iam::$(aws sts get-caller-identity --query Account --output text):role/${ROLE_NAME}"

aws glue update-crawler --name project-library-crawler --role "$ROLE_ARN" --region eu-north-1
aws glue update-crawler --name project-cars-crawler --role "$ROLE_ARN" --region eu-north-1
```

Then re-run the crawlers.

### Glue crawler succeeds but creates no tables

The crawler's S3 target path doesn't match where data was uploaded. Check and fix:

```bash
# Check current target
aws glue get-crawler --name project-library-crawler --region eu-north-1 \
  --query 'Crawler.Targets.S3Targets[0].Path'

# Update if wrong (e.g., targets library-data/ but data is in library/)
aws glue update-crawler --name project-library-crawler \
  --targets '{"S3Targets":[{"Path":"s3://YOUR-BUCKET/library/"}]}' \
  --region eu-north-1
```

### Permission denied writing config in container

If the Streamlit UI shows:

```text
[Errno 13] Permission denied: '/app/config/connections/rds-mysql.yaml'
```

The Docker image needs rebuilding. The Dockerfile now includes `RUN chown -R app:app /app/config` to make the config directory writable at runtime. Trigger a rebuild:

```bash
gh workflow run build-and-push-image
```

## Streamlit UI (chat)

Browser interface for asking questions (local AWS or remote ECS API).

### Local mode (your laptop uses Bedrock + Athena directly)

```bash
export GLUE_DB_NAME=project_library_db
export GLUE_DB_NAMES=project_library_db,project_cars_db
export PROJECT_FILES_BUCKET=langchain-015337708931-eu-north-1
export ATHENA_WORKGROUP=project-text-to-sql
export ATHENA_USE_MANAGED_RESULTS=true
export APP_USERNAME=your-username
export APP_PASSWORD=your-password
pip install -r requirements-dev.txt   # hypothesis is in dev deps
make ui
# or: PYTHONPATH=src streamlit run scripts/streamlit_app.py
```

Opens at **http://localhost:8501**

> **Authentication:** The Streamlit UI requires `APP_USERNAME` and `APP_PASSWORD` environment variables.
> Without these, the login screen blocks access.

### Remote mode (calls ECS API behind the load balancer)

```bash
export API_URL=http://<your-alb-dns>
export API_KEY=your-key   # only if you set ApiKey in CloudFormation
export APP_USERNAME=your-username
export APP_PASSWORD=your-password
streamlit run scripts/streamlit_app.py
```

## ECS Fargate API (production serving layer)

The stack provisions an **ECS Fargate** service behind an **Application Load Balancer** running the Text-to-SQL HTTP API.

### Resources added

| Resource | Purpose |
|----------|---------|
| VPC + subnets | Stack-managed network (public for ALB, private for ECS) |
| Internet Gateway | Outbound internet for ALB only |
| VPC Interface Endpoints | ECR, Bedrock, Athena, Glue, Secrets Manager, CloudWatch Logs |
| S3 Gateway Endpoint | Free S3 access from private subnets (no NAT) |
| ECR repository | `data-architecture-ai` container images |
| ECS cluster + Fargate service | Runs the API in private subnets |
| Application Load Balancer | Public HTTP endpoint on port 80 (public subnets) |
| IAM task role | Bedrock, Glue, Athena, S3, Secrets Manager access (scoped) |
| Athena workgroup | `project-text-to-sql` with 1 GB scan limit |

### Deploy workflow

#### Automated (recommended)

```bash
./deploy-changeset.sh --auto
```

This single command: validates template → deploys stack → waits for completion → builds Docker image → pushes to ECR → starts ECS service → prints the API URL.

### Post-Deploy: Load Sample Data

After a fresh deploy, the Glue databases are empty. Upload sample data to populate Athena tables:

```bash
BUCKET="langchain-$(aws sts get-caller-identity --query Account --output text)-eu-north-1"
aws s3 cp POC/data/s3_library_data.json "s3://${BUCKET}/library/" --region eu-north-1
aws s3 cp POC/data/s3_cars_data_normalized.csv "s3://${BUCKET}/cars/" --region eu-north-1
```

The S3 upload triggers a Lambda which auto-creates Glue crawlers and databases. Wait 1-2 minutes for crawlers to finish, then the app can query data.

If crawlers don't auto-start (check `aws glue get-crawler --name project-library-crawler --query 'Crawler.State'`), start manually:

```bash
aws glue start-crawler --name project-library-crawler --region eu-north-1
aws glue start-crawler --name project-cars-crawler --region eu-north-1
```

#### Manual (step by step)

##### 1. Deploy infrastructure

```bash
./deploy-changeset.sh          # Review what will change
./deploy-changeset.sh --auto   # Or go straight to full deploy
```

##### 2. Build, push, and start the API

```bash
chmod +x scripts/push_ecr.sh
DESIRED_COUNT=1 ./scripts/push_ecr.sh
```

##### 3. Get the API URL

```bash
aws cloudformation describe-stacks \
  --stack-name cgs-ai-analyst-agent-project \
  --region eu-north-1 \
  --query "Stacks[0].Outputs[?OutputKey=='LoadBalancerUrl'].OutputValue" \
  --output text
```

#### 4. Call the API

```bash
ALB_URL="http://your-alb-dns.amazonaws.com"

curl "${ALB_URL}/health"

curl -X POST "${ALB_URL}/query" \
  -H "Content-Type: application/json" \
  -d '{"question": "How many books are in the library?"}'
```

If you set the `ApiKey` stack parameter, include the header:

```bash
curl -X POST "${ALB_URL}/query" \
  -H "Content-Type: application/json" \
  -H "X-Api-Key: your-secret-key" \
  -d '{"question": "How many books are in the library?"}'
```

### Stack parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `VpcCidr` | `10.0.0.0/16` | CIDR for the stack-managed VPC |
| `PublicSubnet1Cidr` | `10.0.0.0/24` | Public subnet 1 (ALB) — AZ a |
| `PublicSubnet2Cidr` | `10.0.1.0/24` | Public subnet 2 (ALB) — AZ b |
| `PrivateSubnet1Cidr` | `10.0.2.0/24` | Private subnet 1 (ECS tasks) — AZ a |
| `PrivateSubnet2Cidr` | `10.0.3.0/24` | Private subnet 2 (ECS tasks) — AZ b |
| `DesiredCount` | `0` | Set to `1` after pushing the container image |
| `ContainerImage` | ECR `:latest` | Override with a specific image URI |
| `ApiKey` | empty | Optional `X-Api-Key` header value |
| `AlbIngressCidr` | `0.0.0.0/0` | Restrict in production |
| `CertificateArn` | empty | ACM certificate ARN for HTTPS (recommended for production) |
| `CreateAppLogGroup` | `true` | Set `false` if the CloudWatch log group `/ecs/data-architecture-ai` already exists |
| `GlueDatabaseForQueries` | `project_library_db` | Primary Glue DB for Athena connection |

> **Multi-database querying:** At runtime, the app reads `GLUE_DB_NAMES` (comma-separated) from the
> ECS task environment. This allows querying across multiple Glue databases (e.g., library + cars).
> Falls back to `GLUE_DB_NAME` (single value) if `GLUE_DB_NAMES` is not set.

> **No VpcId or PublicSubnetIds parameters.** The stack creates and owns the entire network.
> ECS tasks run in private subnets with `AssignPublicIp: DISABLED`. All AWS API calls
> (ECR, Bedrock, Athena, Glue, Secrets Manager, CloudWatch Logs) use VPC interface endpoints.
> S3 uses a free Gateway endpoint. No NAT gateway is provisioned.

### Local API development

```bash
export GLUE_DB_NAME=project_library_db
export GLUE_DB_NAMES=project_library_db,project_cars_db
export PROJECT_FILES_BUCKET=langchain-<account-id>-eu-north-1
export ATHENA_WORKGROUP=project-text-to-sql
export ATHENA_USE_MANAGED_RESULTS=true
PYTHONPATH=src python scripts/serve.py
# curl http://localhost:8080/health
```

> **Multi-database support:** Set `GLUE_DB_NAMES` (comma-separated) to query across multiple Glue databases.
> Falls back to `GLUE_DB_NAME` if `GLUE_DB_NAMES` is not set.

### CLI mode (Docker)

The default Docker entrypoint runs the HTTP API. For one-off CLI queries:

```bash
docker run --rm \
  -e GLUE_DB_NAME=project_library_db \
  -e PROJECT_FILES_BUCKET=langchain-<account-id>-eu-north-1 \
  --entrypoint python \
  data-architecture-ai /app/scripts/run_query.py --question "How many books?"
```

## References

- [AWS CloudFormation User Guide](https://docs.aws.amazon.com/cloudformation/)
- [Change Sets Documentation](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/using-cfn-updating-stacks-changesets.html)
- [IAM Best Practices](https://docs.aws.amazon.com/IAM/latest/UserGuide/best-practices.html)

## Environment Variables Reference

All runtime configuration is loaded via pydantic `BaseSettings` from environment variables (or `.env` file).

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `GLUE_DB_NAME` | - | Yes* | Primary Glue database name |
| `GLUE_DB_NAMES` | - | No | Comma-separated Glue databases (overrides `GLUE_DB_NAME`) |
| `PROJECT_FILES_BUCKET` | - | Yes | S3 bucket for data and Athena results |
| `AWS_REGION` | `eu-north-1` | No | AWS region |
| `ATHENA_WORKGROUP` | `primary` | No | Athena workgroup name |
| `ATHENA_USE_MANAGED_RESULTS` | - | No | Set `true` if workgroup uses managed results |
| `BEDROCK_MODEL` | `eu.amazon.nova-micro-v1:0` | No | Bedrock model ID or inference profile |
| `BEDROCK_MAX_RETRIES` | `4` | No | Max retry attempts for Bedrock calls |
| `BEDROCK_RETRY_BASE_DELAY` | `1.0` | No | Base delay (seconds) between retries |
| `MAX_RESULT_ROWS` | `200` | No | Maximum rows returned per query |
| `MAX_QUESTION_CHARS` | `1000` | No | Maximum question length |
| `LOG_LEVEL` | `INFO` | No | Logging level (DEBUG/INFO/WARNING/ERROR/CRITICAL) |
| `PORT` | `8080` | No | HTTP API listen port |
| `API_KEY` | - | No | Optional `X-Api-Key` header for API auth |
| `API_URL` | - | No | ECS API URL (for remote-mode Streamlit) |
| `APP_USERNAME` | - | Yes** | Streamlit UI login username |
| `APP_PASSWORD` | - | Yes** | Streamlit UI login password |
| `SECRETS_MANAGER_SECRET` | - | No | Secrets Manager secret name |

\* At least one of `GLUE_DB_NAME` or `GLUE_DB_NAMES` must be set.
\** Required for the Streamlit UI. Not needed for the FastAPI service.

## CI/CD — Automated Docker Build & Deploy to Fargate

Two GitHub Actions workflows handle CI/CD:

### 1. `deploy.yml` — Full Pipeline (automatic)

**Trigger:** every push to `main` (after tests pass), or manual dispatch

**What it does:**
1. Runs compile check + unit tests + smoke test (gate)
2. Builds `linux/amd64` Docker image
3. Pushes to ECR with both `:latest` and `:<commit-sha>` tags
4. Forces ECS service redeployment with `desired_count=1`
5. Waits for service stability
6. Prints the ALB URL

### 2. `build-image.yml` — Build & Deploy Only (manual)

**Trigger:** manual dispatch only (`gh workflow run build-and-push-image`)

**What it does:**
1. Builds `linux/amd64` Docker image (skips tests)
2. Pushes to ECR with both `:latest` and `:<commit-sha>` tags
3. Forces ECS service redeployment
4. Waits for service stability
5. Prints the ALB URL

**Use this when:**
- Docker Desktop is unavailable locally
- You need to rebuild the image without waiting for tests
- You want to deploy a specific commit quickly

**Trigger from CLI:**
```bash
gh workflow run build-and-push-image --field desired_count=1 --field streamlit_desired_count=1
```

### Setup required

1. Deploy the OIDC stack (done automatically by `./deploy-changeset.sh --auto`):
   ```bash
   aws cloudformation deploy \
     --template-file cloudformation-github-oidc.yml \
     --stack-name github-actions-oidc \
     --capabilities CAPABILITY_NAMED_IAM \
     --region eu-north-1
   ```
2. Set the GitHub secret:
   ```bash
   ROLE_ARN=$(aws cloudformation describe-stacks --stack-name github-actions-oidc --region eu-north-1 \
     --query "Stacks[0].Outputs[?OutputKey=='DeployRoleArn'].OutputValue" --output text)
   gh secret set AWS_DEPLOY_ROLE_ARN --body "$ROLE_ARN"
   ```
3. The OIDC role grants: ECR push, ECS update, CloudFormation read (scoped to this project)

## Lambda — Auto-Trigger Glue Crawlers on S3 Upload

A Lambda function fires on any file upload to the primary S3 bucket. It:

1. Extracts the top-level folder (prefix) from the S3 key
2. If no Glue database exists for that prefix → creates one (`project_{prefix}_db`)
3. If no Glue crawler exists → creates one (`project-{prefix}-crawler`)
4. Starts the crawler → Glue discovers the schema → tables appear in Athena

**Known vs. unknown prefixes.** The two known seed prefixes are pinned to the
CloudFormation-managed names (CloudFormation is the single source of truth). For these,
the Lambda starts the existing CFN crawler instead of creating a duplicate database/crawler:

| Prefix | Database | Crawler |
|--------|----------|---------|
| `library-data/` | `project_library_db` | `project-library-crawler` |
| `cars-data/` | `project_cars_db` | `project-cars-crawler` |

Any other (unknown) prefix keeps the generic sanitize-based behavior above, creating the
database and crawler on demand.

### Example

Upload `s3://your-bucket/sales/2024.csv` (unknown prefix):
- Creates DB `project_sales_db`
- Creates crawler `project-sales-crawler`
- Crawler runs → creates table in Athena

### For pre-existing buckets

If your S3 bucket existed before the stack (common case), run:

```bash
./scripts/configure_s3_notification.sh
```

This wires the S3 event notification to the Lambda. For buckets created by the stack (`CreatePrimaryDataBucket=true`), the notification is configured automatically.

## Multi-Connector Framework

The app supports multiple data sources beyond Athena. Each connector is configured via a YAML file in `config/connections/`.

### Supported connectors

| Type | Package required | Config template |
|------|-----------------|-----------------|
| Athena | (built-in) | `athena.yaml.template` |
| Redshift | `redshift-connector` | `redshift.yaml.template` |
| RDS PostgreSQL | `psycopg2-binary` | `rds-postgres.yaml.template` |
| RDS MySQL | `pymysql` | (use rds-postgres template, change type to `rds_mysql`) |
| Snowflake | `snowflake-connector-python` | `snowflake.yaml.template` |
| Databricks | `databricks-sql-connector` | `databricks.yaml.template` |

### Adding a data source

```bash
# 1. Copy the template
cp config/connections/redshift.yaml.template config/connections/redshift.yaml

# 2. Edit with your values (credentials go in Secrets Manager, not the file)
vim config/connections/redshift.yaml

# 3. Install the connector package
pip install redshift-connector

# 4. Restart the UI — the new source appears in the sidebar dropdown
make ui
```

### Credentials

Never put passwords in YAML files. Use `user_from_secret` or `token_from_secret` to reference an AWS Secrets Manager secret:

```yaml
settings:
  host: my-cluster.xxxx.redshift.amazonaws.com
  user_from_secret: redshift/prod-creds  # Secret with {"username":"...", "password":"..."}
```

## Aurora Serverless v2 (RDS MySQL)

A separate CloudFormation stack deploys Aurora Serverless v2 in the same VPC. It scales to near-zero when idle (0.5 ACU minimum) — cost-efficient for training and dev.

### Deploy

```bash
./scripts/deploy-rds.sh --auto
```

This takes 5-10 minutes. After completion, it prints the connection config.

### Connect the app

Paste the printed output into `config/connections/rds-mysql.yaml`:

```yaml
name: RDS MySQL
type: rds_mysql
enabled: true
settings:
  host: <cluster-endpoint-printed-by-script>
  port: 3306
  database: analyst_db
  user_from_secret: cgs-ai-rds-aurora/aurora-credentials
  region: eu-north-1
```

### Load sample data

After the Aurora stack is deployed and the connection config is in place, load the sample datasets (library + cars) into the database:

```bash
PYTHONPATH=src python3 scripts/load_rds_data.py
```

The script fetches credentials from Secrets Manager, creates the `library` and `cars` tables, and bulk-inserts data from `data/s3_library_data.json` and `data/s3_cars_data.csv`.

Override defaults with environment variables if needed:

| Variable | Default | Description |
|----------|---------|-------------|
| `RDS_SECRET` | `cgs-ai-rds-aurora/aurora-credentials` | Secrets Manager secret name |
| `RDS_DATABASE` | `analyst_db` | Target database |
| `AWS_REGION` | `eu-north-1` | Region for Secrets Manager calls |

### Architecture

- **Template:** `cloudformation-rds-aurora.yml`
- **Stack name:** `cgs-ai-rds-aurora`
- **Engine:** Aurora MySQL 8.0 (Serverless v2)
- **Scaling:** 0.5–4 ACU (configurable via parameters)
- **Network:** Same VPC + private subnets as the main stack
- **Security:** Only ECS tasks can connect (port 3306 restricted to `ServiceSecurityGroup`)
- **Credentials:** Auto-generated, stored in Secrets Manager, rotatable
- **Deletion:** Takes a snapshot before deletion (`DeletionPolicy: Snapshot`)

### Delete

```bash
aws cloudformation delete-stack \
  --stack-name cgs-ai-rds-aurora \
  --region eu-north-1
```

A final snapshot is created automatically before deletion.

## Redshift Serverless

A separate CloudFormation stack deploys Redshift Serverless in the same VPC for analytics workloads.

### Deploy

```bash
aws cloudformation deploy \
  --template-file cloudformation-redshift-serverless.yml \
  --stack-name cgs-ai-redshift-serverless \
  --capabilities CAPABILITY_NAMED_IAM \
  --region eu-north-1 \
  --no-fail-on-empty-changeset
```

Or use the full deploy script which includes Redshift:

```bash
./deploy-changeset.sh --auto --with-databases
```

### Connect the app

Paste into `config/connections/redshift.yaml`:

```yaml
name: Redshift Serverless
type: redshift
enabled: true
settings:
  host: cgs-ai-redshift-serverless-wg.015337708931.eu-north-1.redshift-serverless.amazonaws.com
  port: 5439
  database: analytics
  schema: public
  user_from_secret: cgs-ai-redshift-serverless/redshift-credentials
  region: eu-north-1
```

### Architecture

- **Template:** `cloudformation-redshift-serverless.yml`
- **Stack name:** `cgs-ai-redshift-serverless`
- **Engine:** Redshift Serverless
- **Base capacity:** 8 RPU (configurable)
- **Network:** Same VPC + private subnets as the main stack
- **Security:** Only ECS tasks can connect (port 5439 restricted to `ServiceSecurityGroup`)
- **Credentials:** Auto-generated, stored in Secrets Manager

### Delete

```bash
aws cloudformation delete-stack \
  --stack-name cgs-ai-redshift-serverless \
  --region eu-north-1
```

## Production Readiness Checklist

The following items are recommended before serving real production traffic:

### Security (critical)
- [ ] Enable HTTPS — add ACM certificate, configure HTTPS listener on ALB (set `CertificateArn` parameter)
- [ ] Enforce API authentication — set the `API_KEY` environment variable in ECS task definition
- [ ] Add AWS WAF — attach WAF WebACL to the ALB for DDoS protection and rate limiting
- [ ] Restrict ALB ingress — change `AlbIngressCidr` from `0.0.0.0/0` to known IP ranges or use CloudFront
- [ ] Add a custom domain — Route 53 alias record pointing to ALB, with HTTPS

### Observability (high priority)
- [ ] Structured JSON logging — use `python-json-logger` for CloudWatch Insights queries
- [ ] Request tracing — enable AWS X-Ray on ECS tasks for end-to-end trace visibility
- [ ] CloudWatch alarms — 5xx error rate, ECS task health, Bedrock throttle count, Athena query failures
- [ ] Operational dashboard — CloudWatch dashboard with key metrics

### Reliability
- [ ] Auto-scaling — add ECS Service Auto Scaling policy (target CPU/memory or request count)
- [ ] Request timeouts — configure uvicorn worker timeout and Bedrock call deadline
- [ ] Circuit breaker — add fallback when Bedrock is throttled (e.g., cached response or graceful error)
- [ ] Multi-AZ validation — verify tasks distribute across both private subnets

### Performance & Cost
- [ ] Response caching — cache common question/answer pairs (reduces 3 LLM calls to 0)
- [ ] Rate limiting — per-user request throttle to protect Bedrock quota
- [ ] Right-size Bedrock model — evaluate `nova-pro` vs `nova-micro` for accuracy/cost tradeoff

### Compliance & Audit
- [ ] Query audit log — log every question, generated SQL, and response to a dedicated log group
- [ ] PII filtering — scan query results before returning to user
- [ ] Data access control — row-level or database-level permissions per user/role

### CI/CD & Testing
- [ ] Fix broken tests (`test_runner`, `test_sidebar_properties`) so `deploy.yml` gates work
- [ ] Add integration tests that verify Athena queries end-to-end
- [ ] Add load testing baseline (k6, locust, or similar)
- [ ] Enable ECR image scanning for CVE detection
- [ ] Add staging environment (separate stack with `Environment=staging` tag)
