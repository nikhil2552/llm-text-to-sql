# Tech Stack & Build System

## Language & Runtime

- Python 3.11
- Virtual environment: `.venv/`

## Key Libraries

| Library | Purpose |
|---------|---------|
| boto3 | AWS SDK (Glue, Bedrock, S3, Secrets Manager) — text-to-SQL calls Bedrock directly |
| langchain, langchain-community, langchain-experimental | Installed but **not used at runtime** (POC-only; see `POC/`) |
| pyathena | Athena JDBC-style connector |
| sqlalchemy | Database abstraction for RDS/Redshift/Snowflake |
| fastapi + uvicorn | HTTP API server |
| streamlit | Chat UI |
| pydantic (v1) | Settings validation, request/response models |
| pandas | Data manipulation |
| pyyaml | Connection config parsing |
| hypothesis | Property-based testing |
| python-dotenv | Local .env loading |

## Build & Task Runner

Uses `make` as the task runner. Key targets:

```bash
make check       # Compile-check all Python (syntax gate)
make test        # Unit tests (unittest, PYTHONPATH=src)
make smoke       # Smoke test — local data, no AWS calls
make prod-check  # All three above in sequence (CI gate)
make ui          # Start Streamlit chat UI
make deploy      # CloudFormation change set (review mode)
make deploy-all  # Full auto: deploy + build image + start ECS
make setup       # Create venv and install deps
```

## Testing

- Framework: `unittest` (stdlib)
- Test location: `tests/test_*.py`
- Run: `PYTHONPATH=src python -m unittest discover -s tests -p "test_*.py" -v`
- Smoke test: `python run_smoke.py` (no AWS calls)
- Property-based testing: `hypothesis` available

## CI/CD

- GitHub Actions: `.github/workflows/ci.yml`
- Gates on every push/PR: compile check → unit tests → smoke test
- Deployment: `deploy-changeset.sh` (CloudFormation change sets)
- Container: `scripts/push_ecr.sh` (builds linux/amd64, pushes to ECR)

## Infrastructure

- CloudFormation templates: `cloudformation-template-validated.yml` (main), `cloudformation-rds-aurora.yml` (database)
- Docker: Python 3.11-slim, non-root user, healthcheck on `/health`
- Platform: linux/amd64 (ECS Fargate)

## Configuration

- Environment variables validated via `pydantic.BaseSettings` in `src/llm_sql/config.py`
- `.env` file supported for local dev (see `.env.template`)
- Connection configs: `config/connections/*.yaml` (one file per data source)
