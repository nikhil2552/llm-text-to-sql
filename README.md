git clone https://github.com/huraisturkey-lang/Ai_Agent.git
cd Ai_Agent

aws configure

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

make prod-check

./deploy-changeset.sh --auto

aws secretsmanager get-secret-value \
  --secret-id cgs-ai-analyst-agent/streamlit-credentials \
  --region eu-north-1 --query SecretString --output text

make teardown
















# Data Architecture with Generative AI (Text-to-SQL)

Ask a question in plain English, get back an answer from your data. This service turns
natural-language questions into SQL using **AWS Bedrock** (Amazon Nova),
runs the SQL safely (read-only), and returns the result. It ships as an HTTP API
(FastAPI) and a chat UI (Streamlit), and runs on AWS ECS Fargate.

Supported data sources: **Athena, Redshift, RDS (PostgreSQL/MySQL), Snowflake, Databricks.**

---

## Deploy in one command

The entire stack deploys with a single command — fully automated, no GitHub required:

```bash
./deploy-changeset.sh --auto
```

This provisions all AWS infrastructure, builds and pushes the Docker image, seeds the
sample data, catalogs it, and starts the services. The only prerequisites are **AWS
credentials** and **Docker running locally**. See [Part 2](#part-2--deploy-to-aws) for the
full breakdown.

An optional GitHub Actions CI/CD path (push-to-deploy) is available for anyone who wants
it, but it is entirely opt-in and never runs unless you ask for it — see
[Part 4](#part-4--optional-cicd-via-github-actions).

---

## Prerequisites

Install these before you start:

1. **Python 3.11** — check with `python3 --version`.
2. **AWS account + AWS CLI** — run `aws configure` and set region `eu-north-1`.
   Verify with `aws sts get-caller-identity`.
3. **Amazon Bedrock access** — enable the Amazon Nova models in the Bedrock console
   (region `eu-north-1`).
4. **Docker Desktop** — required for the deploy (`--auto` builds the image locally).
   Make sure it is running before you deploy.
5. **(Optional) GitHub CLI `gh`** — only needed for the optional CI/CD path (Part 4):
   `brew install gh`.

---

## Part 1 — Run it locally (no AWS deploy)

Do this first to confirm everything works on your machine.

### Step 1: Get the code and create a virtual environment
```bash
git clone https://github.com/huraisturkey-lang/Ai_Agent.git
cd Ai_Agent
python3 -m venv .venv
source .venv/bin/activate
```

### Step 2: Install dependencies
```bash
pip install -r requirements-dev.txt   # prod deps + Streamlit + test tools
```
> `requirements.txt` = production deps (used by Docker). `requirements-dev.txt` includes
> everything in it, plus `hypothesis` for testing. For local work, use the `-dev` one.

### Step 3: Run the quality gate (no AWS calls)
```bash
make prod-check
```
This runs three things in order:
- `make check` — compiles all Python (catches syntax errors)
- `make test` — unit tests
- `make smoke` — loads the sample data locally (`POC/run_smoke.py`)

If all three pass, your environment is good.

### Step 4: Launch the chat UI locally
Set the required variables, then start Streamlit:
```bash
export APP_USERNAME=your-username          # login for the UI
export APP_PASSWORD=your-password
export GLUE_DB_NAME=project_library_db
export GLUE_DB_NAMES=project_library_db,project_cars_db
export PROJECT_FILES_BUCKET=langchain-<your-account-id>-eu-north-1
export ATHENA_WORKGROUP=project-text-to-sql
export ATHENA_USE_MANAGED_RESULTS=true
make ui
```
Open **http://localhost:8501** and log in with the username/password you set.

> Querying real data needs the AWS infrastructure from Part 2. The UI runs locally either
> way, but answers come from AWS (Athena/Bedrock).

Tip: copy `.env.template` to `.env` and fill it in instead of exporting variables each time:
```bash
cp .env.template .env   # then edit .env
```

---

## Part 2 — Deploy to AWS

One command deploys everything into AWS region `eu-north-1`. Make sure Docker Desktop is
**running**, then:

```bash
./deploy-changeset.sh --auto
```

This runs end-to-end with no manual steps in between. In order it:
1. Creates/updates the main CloudFormation stack (VPC, ECS, ALB, Glue, S3, Lambda), with
   the Athena workgroup `project-text-to-sql` and the Glue crawlers both created automatically.
2. Builds the Docker image on your machine (`linux/amd64`) and pushes it to ECR.
3. **Seeds the sample data** — uploads `POC/data` to S3 (`s3_cars_data_normalized.csv` →
   `cars-data/`, `s3_library_data.json` → `library-data/`) so the crawlers have data to catalog.
4. Runs the Glue crawlers, registering `project_cars_db.cars_data` and
   `project_library_db.library_data` so the query allowlist is populated.
5. Scales up the ECS services (API + Streamlit). The Streamlit login username defaults to
   `admin`; the password is auto-generated into the `cgs-ai-analyst-agent/streamlit-credentials`
   Secrets Manager secret.
6. Configures the S3 → Lambda notification.

When it finishes it prints the **API URL**, **Streamlit URL**, and the exact command to
retrieve the Streamlit password — you can query the sample data immediately. Data loading,
cataloging, the Athena workgroup, and the UI login are all handled for you. The script also
prints the logical next commands you can run (databases, CI/CD, redeploy, teardown).

Retrieve the Streamlit password any time:
```bash
aws secretsmanager get-secret-value \
  --secret-id cgs-ai-analyst-agent/streamlit-credentials \
  --region eu-north-1 --query SecretString --output text
```

> Re-running `./deploy-changeset.sh --auto` is safe — the stack updates in place and the
> data seed overwrites idempotently.

### Add the optional databases

Deploy Aurora + Redshift at the same time, or later:
```bash
./deploy-changeset.sh --auto --with-databases
```
Running the script again is safe — the main stack updates in place, and the database
stacks only deploy if they don't already exist. See [Part 3](#part-3--optional-databases)
for loading data into them.

### Review before deploying (optional)

To inspect what will change without deploying anything, run the script with no flags. It
creates a CloudFormation change set, prints a summary, and tells you the next command to
run to execute it:
```bash
./deploy-changeset.sh
```

---

## Part 3 — Optional databases

The RDS Aurora and Redshift stacks are plain CloudFormation (no Docker). Deploy them
directly whenever you want:
```bash
aws cloudformation deploy --template-file cloudformation-rds-aurora.yml \
  --stack-name cgs-ai-rds-aurora --capabilities CAPABILITY_NAMED_IAM \
  --region eu-north-1 --no-fail-on-empty-changeset

aws cloudformation deploy --template-file cloudformation-redshift-serverless.yml \
  --stack-name cgs-ai-redshift-serverless --capabilities CAPABILITY_NAMED_IAM \
  --region eu-north-1 --no-fail-on-empty-changeset
```
Then load sample data into Aurora and point the connector at it:
```bash
PYTHONPATH=src python3 scripts/load_rds_data.py
# paste the printed connection details into config/connections/rds-mysql.yaml
```

Each connector is driven by a YAML file in `config/connections/`. Copy the matching
`*.yaml.template`, fill in the values, and the registry auto-discovers it on startup.
Database passwords are stored in AWS Secrets Manager, not in the YAML (see `.env.template`
for the expected secret names).

---

## Using the API

```bash
# health check
curl <API_URL>/health

# ask a question
curl -X POST <API_URL>/query \
  -H 'Content-Type: application/json' \
  -d '{"question": "How many books are there?"}'
```

CLI version (for automation):
```bash
PYTHONPATH=src python scripts/run_query.py --question "How many books?" --json-output
```

---

## Part 4 — Optional CI/CD via GitHub Actions

This is **entirely optional**. The deploy in Part 2 is self-contained and never touches
GitHub. Set this up only if you want a push-to-deploy workflow, where GitHub's servers
build the image and redeploy on every push to `main` (no local Docker needed for those
subsequent deploys).

**Step 1 — set up the OIDC auth (opt-in).**
Re-run the deploy with the `--with-cicd` flag. It provisions the GitHub Actions OIDC role
and, if `gh` is installed and logged in, sets the repo secret `AWS_DEPLOY_ROLE_ARN`:
```bash
./deploy-changeset.sh --auto --with-cicd
```
If `gh` isn't available, the script prints the role ARN — add it manually at
**Repo → Settings → Secrets and variables → Actions → New repository secret**:
- Name: `AWS_DEPLOY_ROLE_ARN`
- Value: the printed `arn:aws:iam::<account>:role/github-actions-deploy-role`

> The OIDC role trust is scoped to a specific GitHub repo in
> `cloudformation-github-oidc.yml` (`GitHubOrg` / `GitHubRepo` parameters). If you deploy
> from your own fork, override those to match your repo.

**Step 2 — deploy by pushing.**
```bash
git push origin main
```
On every push to `main`, `.github/workflows/deploy.yml` runs the test gate → builds the
image on GitHub's servers → pushes to ECR → redeploys ECS → prints the URLs. Watch it under
the repo's **Actions** tab.

---

## Tear down

Remove all AWS resources when you're done:
```bash
make teardown
```

---

## Troubleshooting

- **Deploy fails because Docker isn't running** — `--auto` builds the image locally. Start
  Docker Desktop and wait until it's ready, then re-run `./deploy-changeset.sh --auto`.
- **Stack stuck in `REVIEW_IN_PROGRESS`** — a change set was created but never executed.
  Delete the empty stack and recreate: `aws cloudformation delete-stack --stack-name
  cgs-ai-analyst-agent-project --region eu-north-1`, then re-run `./deploy-changeset.sh --auto`.
- **Streamlit UI shows "Authentication not configured"** — the credentials secret has a
  blank username. `--auto` sets it to `admin` automatically; if you deployed differently,
  update the secret and restart the service (see
  [DEPLOYMENT.md](DEPLOYMENT.md) for the exact commands).
- **Query refused with "No allowed table list is configured"** — the Glue tables aren't
  registered. Confirm the crawlers ran and the data was seeded (`--auto` does both). Check
  `aws glue get-tables --database-name project_cars_db --region eu-north-1`.
- **Query fails with "WorkGroup is not found"** — the `project-text-to-sql` Athena workgroup
  is missing. `--auto` creates it; re-run the deploy to recreate it.
- **`make smoke` import errors (`No module named boto3`)** — dependencies aren't installed
  in the active environment. Activate the venv and `pip install -r requirements-dev.txt`.
- **Docker build fails on Apple Silicon** — ECS needs `linux/amd64`. The provided scripts
  (`./scripts/push_ecr.sh`) cross-build automatically.
- **(Optional CI/CD) GitHub deploy fails at "Configure AWS credentials"** — the
  `AWS_DEPLOY_ROLE_ARN` secret is missing or the OIDC role doesn't exist. Run
  `./deploy-changeset.sh --auto --with-cicd` (Part 4).

---

## How it fits together

```
Internet -> ALB:80   -> FastAPI  (ECS private subnet) -> Bedrock / Athena via VPC endpoints
Internet -> ALB:8501 -> Streamlit (ECS private subnet) -> Bedrock / Athena via VPC endpoints
                                                        -> RDS Aurora       (private subnet, 3306)
                                                        -> Redshift Serverless (private subnet, 5439)
```

### CloudFormation stacks

| Stack | Template | Purpose |
|-------|----------|---------|
| `cgs-ai-analyst-agent-project` | `cloudformation-template-validated.yml` | VPC, ECS, ALB, Lambda, Glue, S3, VPC endpoints |
| `github-actions-oidc` | `cloudformation-github-oidc.yml` | GitHub Actions OIDC role for CI/CD |
| `cgs-ai-rds-aurora` | `cloudformation-rds-aurora.yml` | Aurora Serverless v2 (MySQL) + Secrets Manager creds |
| `cgs-ai-redshift-serverless` | `cloudformation-redshift-serverless.yml` | Redshift Serverless + Secrets Manager creds |

### GitHub Actions workflows (optional CI/CD — see Part 4)

These run only if you opt into CI/CD. They are not needed for the Part 2 deploy.

| Workflow | Trigger | What it does |
|----------|---------|--------------|
| `.github/workflows/ci.yml` | every push / PR | compile + unit tests + smoke (quality gate) |
| `.github/workflows/deploy.yml` | push to `main` | tests → build image on GitHub → push to ECR → redeploy ECS |
| `.github/workflows/build-image.yml` | manual (`workflow_dispatch`) | build + deploy, skips tests |

### Key files

| Path | Purpose |
|------|---------|
| `src/llm_sql/` | application package (API, core text-to-SQL, config, connectors) |
| `scripts/serve.py` | FastAPI server (ECS entrypoint) |
| `scripts/streamlit_app.py` | Streamlit chat UI (`make ui`) |
| `scripts/run_query.py` | CLI query tool (`--json-output`) |
| `scripts/push_ecr.sh` | rebuild + push image + redeploy ECS |
| `scripts/seed_s3_data.sh` | upload sample data to S3 (`cars-data/`, `library-data/`) |
| `scripts/setup-github-oidc.sh` | set up GitHub Actions CI/CD auth (optional) |
| `scripts/load_rds_data.py` | load sample data into Aurora |
| `deploy-changeset.sh` | one-command deploy (`--auto`; opt-in `--with-databases`, `--with-cicd`) |
| `config/connections/*.yaml` | one file per data source (copy from `*.template`) |
| `POC/` | sample data, smoke test, notebooks |
| `.env.template` | environment variable template |
| `DEPLOYMENT.md` | detailed deployment guide |

---

## Configuration reference

Set these as environment variables or in `.env` (copy from `.env.template`):

| Variable | Required | Default | Notes |
|----------|----------|---------|-------|
| `APP_USERNAME` / `APP_PASSWORD` | Yes (UI) | — | Streamlit login; UI blocks without them. On AWS, set automatically by `--auto` (username defaults to `admin`, password auto-generated into Secrets Manager) |
| `GLUE_DB_NAME` / `GLUE_DB_NAMES` | Yes | `project_library_db` | single, or comma-separated list |
| `PROJECT_FILES_BUCKET` | Yes | — | `langchain-<account-id>-eu-north-1` |
| `ATHENA_WORKGROUP` | — | `primary` | use `project-text-to-sql` when deployed |
| `ATHENA_USE_MANAGED_RESULTS` | — | — | `true` if workgroup uses managed results |
| `AWS_REGION` | — | `eu-north-1` | |
| `BEDROCK_MODEL` | — | `eu.amazon.nova-micro-v1:0` | |
| `BEDROCK_MAX_RETRIES` | — | `4` | |
| `BEDROCK_RETRY_BASE_DELAY` | — | `1.0` | seconds |
| `MAX_RESULT_ROWS` | — | `200` | automatic `LIMIT` cap |
| `MAX_QUESTION_CHARS` | — | `1000` | question length guard |
| `PORT` | — | `8080` | HTTP API port |
| `API_KEY` | — | — | optional HTTP API auth |
| `LOG_LEVEL` | — | `INFO` | `DEBUG`/`INFO`/`WARNING`/`ERROR`/`CRITICAL` |
| `API_URL` | — | — | route Streamlit through the deployed API |
| `SECRETS_MANAGER_SECRET` | — | — | optional Secrets Manager integration |

Safety defaults built in: read-only + allowlist SQL validation, automatic `LIMIT`
enforcement, max question length, non-root container user.

---

## Not yet implemented (production hardening gaps)

HTTPS/TLS (ALB is HTTP-only), AWS WAF, structured JSON logging, request tracing,
CloudWatch alarms, auto-scaling (fixed at 1 task), response caching, rate limiting,
query audit logging, dev/staging separation, ECR vulnerability scanning.

See [DEPLOYMENT.md](DEPLOYMENT.md) for the detailed deployment reference.
