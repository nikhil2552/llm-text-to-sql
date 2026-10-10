# Data Architecture with Generative AI (Text-to-SQL)

Ask a question in plain English, get back an answer from your data. This service turns
natural-language questions into SQL using **AWS Bedrock** (Amazon Nova),
runs the SQL safely (read-only), and returns the result. It ships as an HTTP API
(FastAPI) and a chat UI (Streamlit), and runs on AWS ECS Fargate.

Supported data sources: **Athena, Redshift, RDS (PostgreSQL/MySQL), Snowflake, Databricks.**

---

## Two deploy paths

**CI/CD path (recommended — no local Docker).** GitHub Actions, running in your own repo
and your own AWS account, builds the Docker image, pushes it to ECR, and starts ECS Fargate.
You open the project, push it to a repo under your GitHub account, run the deploy with the
`--with-cicd` flag to wire up AWS infra and OIDC auth, then push to deploy. See
[Part 2 — Deploy via GitHub CI/CD](#part-2--deploy-via-github-cicd).

```bash
./deploy-changeset.sh --auto --with-cicd   # provisions AWS infra + OIDC, no local Docker
git push origin main                        # GitHub builds the image, pushes ECR, starts ECS
```

**Local Docker path (alternative).** A single command provisions everything and builds the
image on your own machine. This one requires Docker running locally. See
[Part 2B — Deploy with a local Docker build](#part-2b--deploy-with-a-local-docker-build).

```bash
./deploy-changeset.sh --auto               # requires Docker running locally
```

---

## Prerequisites

Install these before you start:

1. **Python 3.11** — check with `python3 --version`.
2. **AWS account + AWS CLI** — run `aws configure` and set region `eu-north-1`.
   Verify with `aws sts get-caller-identity`.
3. **Amazon Bedrock access** — enable the Amazon Nova models in the Bedrock console
   (region `eu-north-1`).

For the **CI/CD path** (recommended) you also need:

4. **A GitHub account** — the code is pushed to a repo under your account and GitHub
   Actions builds the image there. No local Docker is needed.
5. **(Optional) GitHub CLI `gh`** — `brew install gh`, then `gh auth login`. When present,
   the deploy sets the `AWS_DEPLOY_ROLE_ARN` repo secret for you; when absent, it prints
   the value for you to paste in manually.

For the **local Docker path** (alternative) you instead need:

6. **Docker Desktop** — `./deploy-changeset.sh --auto` (without `--with-cicd`) builds the
   image locally, so Docker must be running. The CI/CD path does not use Docker locally.

---

## Part 1 — Run it locally (no AWS deploy)

Do this first to confirm everything works on your machine.

### Step 1: Open the project and create a virtual environment
Open this project folder in your IDE, then from its root:
```bash
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

## Part 2 — Deploy via GitHub CI/CD

GitHub Actions builds the image and deploys ECS from your own repo and AWS account. No
local Docker is required. The flow is five steps, plus a verification check:

```
1. Open project          2. Sign in to          3. Create repo +
   in your IDE      ──►      your GitHub    ──►      git push
                                                         │
                                                         ▼
5. git push origin main  ◄── 4. ./deploy-changeset.sh --auto --with-cicd
   (GitHub builds image,        (provisions AWS infra + OIDC, no local Docker)
    pushes ECR, starts ECS)
```

### Step 1 — open the project in your IDE
Open this project folder in your IDE. Everything below runs from the project root.

### Step 2 — sign in to your own GitHub
Sign in to your GitHub account in the IDE (or `gh auth login` on the CLI). The repo you
deploy to must be under your account, because the image is built by GitHub Actions running
in that repo.

### Step 3 — create a new empty repo and push the code
Create a new empty repository under your GitHub account, then point this project at it and
push:
```bash
git remote add origin https://github.com/<you>/<repo>.git
git branch -M main
git push -u origin main
```
Replace `<you>/<repo>` with your account and the repo you just created. The deploy reads
this `origin` remote to scope AWS access to exactly your repo.

### Step 4 — provision AWS infra and OIDC auth
```bash
./deploy-changeset.sh --auto --with-cicd
```
With `--with-cicd` this command:
- **does not build the image locally and does not need Docker** — the build happens in
  GitHub Actions;
- creates/updates the main CloudFormation stack (VPC, ECS, ALB, Glue, S3, Lambda), with the
  Athena workgroup `project-text-to-sql` and the Glue crawlers;
- seeds the sample data to S3 and runs the crawlers, registering `project_cars_db.cars_data`
  and `project_library_db.library_data`;
- creates a GitHub OIDC role whose trust is scoped to **your** repo, auto-detected from the
  `origin` git remote you set in Step 3;
- sets the `AWS_DEPLOY_ROLE_ARN` secret in your repo (via `gh` when available; otherwise it
  prints the role ARN for you to add at **Repo → Settings → Secrets and variables →
  Actions → New repository secret**, name `AWS_DEPLOY_ROLE_ARN`);
- leaves the ECS services at desired count 0 — they start when the first image is pushed in
  Step 5.

If no `origin` remote is set, the command stops and tells you to add one (Step 3) before
re-running — it never falls back to any other repo.

### Step 5 — push to deploy
```bash
git push origin main
```
This triggers `.github/workflows/deploy.yml` in your repo, which runs the test gate, builds
the image on GitHub (`linux/amd64`), pushes it to ECR, and starts the ECS services. Watch
progress under your repo's **Actions** tab; the workflow prints the **API URL** and
**Streamlit URL** when it finishes.

The Streamlit login username defaults to `admin`; the password is auto-generated into the
`cgs-ai-analyst-agent/streamlit-credentials` Secrets Manager secret. Retrieve it any time:
```bash
aws secretsmanager get-secret-value \
  --secret-id cgs-ai-analyst-agent/streamlit-credentials \
  --region eu-north-1 --query SecretString --output text
```

### Step 6 — verify it worked
Once the Actions run finishes, grab the API URL from the workflow log (or from the stack
output) and confirm the service is live:
```bash
# API URL from the CloudFormation stack output
API_URL=$(aws cloudformation describe-stacks \
  --stack-name cgs-ai-analyst-agent-project --region eu-north-1 \
  --query "Stacks[0].Outputs[?OutputKey=='LoadBalancerUrl'].OutputValue" --output text)

# health check — expect {"status":"ok"}
curl "$API_URL/health"

# ask a question
curl -X POST "$API_URL/query" -H 'Content-Type: application/json' \
  -d '{"question": "How many books are there?"}'
```
Then open the **Streamlit URL** (stack output `StreamlitUrl`, port `8501`) in a browser and
log in with `admin` and the password retrieved above.

### Add the optional databases
Deploy Aurora + Redshift at the same time, or later:
```bash
./deploy-changeset.sh --auto --with-cicd --with-databases
```
Re-running is safe — the main stack updates in place, and the database stacks only deploy
if they don't already exist. See [Part 3](#part-3--optional-databases) for loading data.

---

## Part 2B — Deploy with a local Docker build

Alternative to Part 2 for when you want the image built on your own machine instead of in
GitHub Actions. **This path requires Docker running locally.** It touches no GitHub.

Make sure Docker Desktop is **running**, then:
```bash
./deploy-changeset.sh --auto
```

Without `--with-cicd` this runs end-to-end with no manual steps in between. In order it:
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
retrieve the Streamlit password — you can query the sample data immediately.

Add the databases at the same time with `./deploy-changeset.sh --auto --with-databases`.

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

## Part 4 — How the CI/CD build works

Once Part 2 is set up, every push to `main` redeploys automatically:
```bash
git push origin main
```
`.github/workflows/deploy.yml` runs the test gate, builds the image on GitHub's servers,
pushes it to ECR, redeploys ECS, and prints the URLs. Watch it under your repo's **Actions**
tab. `.github/workflows/build-image.yml` does the same on demand (`workflow_dispatch`),
skipping the test gate.

Both workflows authenticate to AWS with the OIDC role created in Part 2 via the
`AWS_DEPLOY_ROLE_ARN` repo secret. The role's trust is scoped to your repo through the
`GitHubOrg` / `GitHubRepo` parameters of `cloudformation-github-oidc.yml`, which the deploy
sets automatically from your `origin` remote — you never edit them by hand. (The template
ships with placeholder defaults that the deploy overrides.)

---

## Tear down

Remove all AWS resources when you're done:
```bash
make teardown
```

---

## Troubleshooting

- **Deploy fails because Docker isn't running** — only the local path
  (`./deploy-changeset.sh --auto` without `--with-cicd`) builds the image locally. Start
  Docker Desktop and re-run, or use the CI/CD path (`--with-cicd`), which needs no local Docker.
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
- **(CI/CD) GitHub deploy fails at "Configure AWS credentials" / "Not authorized to perform
  sts:AssumeRoleWithWebIdentity"** — the `AWS_DEPLOY_ROLE_ARN` secret is missing or the OIDC
  role's trust doesn't match the repo the workflow runs in. The deploy auto-detects your
  repo from the `origin` remote, so the usual causes are: no `origin` remote was set when you
  ran `--with-cicd`, or you pushed to a different repo than the one you deployed from. Confirm
  `git remote get-url origin` points at the repo running the workflow, then re-run
  `./deploy-changeset.sh --auto --with-cicd` and push again.
- **(CI/CD) `--with-cicd` stops with "requires an 'origin' remote"** — you haven't pushed the
  project to your own GitHub repo yet. Follow Part 2 Step 3 (`git remote add origin …`,
  `git branch -M main`, `git push -u origin main`), then re-run.

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

### GitHub Actions workflows (CI/CD path — see Part 2)

These run in your own repo and drive the CI/CD deploy. The local Docker path (Part 2B) does
not use them.

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
| `deploy-changeset.sh` | deploy driver (`--auto` local Docker; `--with-cicd` GitHub builds the image; `--with-databases`) |
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
