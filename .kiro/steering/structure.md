# Project Structure

```
.
├── src/llm_sql/              # Main application package
│   ├── __init__.py           # Exports LLMSQLService, parse_catalog
│   ├── api.py                # FastAPI HTTP API (/health, /query)
│   ├── config.py             # Pydantic settings (env vars, validation)
│   ├── core.py               # LLMSQLService — Bedrock text-to-SQL logic (direct boto3)
│   ├── runner.py             # Service builder (wires Athena connector + LLM)
│   ├── secrets.py            # Secrets Manager integration
│   └── connectors/           # Multi-connector framework
│       ├── base.py           # BaseConnector ABC (dialect, get_schema, execute_sql)
│       ├── registry.py       # Auto-discovers connectors from YAML configs
│       ├── athena.py         # AWS Athena connector
│       ├── redshift.py       # AWS Redshift connector
│       ├── rds.py            # RDS PostgreSQL + MySQL connectors
│       ├── snowflake.py      # Snowflake connector
│       └── databricks.py     # Databricks connector
├── scripts/                  # CLI tools and entrypoints
│   ├── serve.py              # ECS Fargate entrypoint (uvicorn)
│   ├── streamlit_app.py      # Streamlit chat UI
│   ├── run_query.py          # CLI query tool (supports --json-output)
│   ├── setup.sh              # Dependency installation helper
│   ├── push_ecr.sh           # Build + push Docker image to ECR
│   ├── deploy-rds.sh         # Deploy Aurora Serverless v2 stack
│   └── normalize_cars.py     # Data normalization script
├── tests/                    # Unit tests (unittest framework)
│   ├── test_config.py
│   ├── test_core.py
│   ├── test_runner.py
│   └── test_serve.py
├── config/connections/       # Data source YAML configs (one per source)
├── schema/                   # JSON Schema definitions for datasets
├── data/                     # Sample data files (CSV, JSON)
├── lambda/                   # AWS Lambda handlers
│   └── s3_trigger_crawler/   # S3 event → Glue Crawler trigger
├── POC/                      # Proof-of-concept notebooks
├── assets/                   # Static assets (logos)
├── .github/workflows/        # CI/CD pipelines
├── Makefile                  # Task runner
├── Dockerfile                # Container build (Python 3.11-slim)
├── requirements.txt          # Pinned Python dependencies
├── cloudformation-*.yml      # IaC templates
└── deploy-changeset.sh       # CloudFormation deployment script
```

## Architecture Patterns

- **Connector pattern**: All data sources implement `BaseConnector` ABC. New connectors go in `src/llm_sql/connectors/` and register in `registry.py`.
- **YAML-driven config**: Each data source has a YAML file in `config/connections/`. The registry auto-discovers enabled connections.
- **Pydantic settings**: All runtime config flows through `src/llm_sql/config.py` using `BaseSettings` with env var binding.
- **Lazy service init**: The API lazily initializes the query service so `/health` responds fast for ALB probes.
- **PYTHONPATH convention**: Always set `PYTHONPATH=src` when running code outside Docker (tests, scripts, CLI).

## Conventions

- New connectors: subclass `BaseConnector`, implement `dialect`, `get_schema()`, `execute_sql()`, add to registry.
- Tests: place in `tests/test_<module>.py`, use `unittest.TestCase`.
- Scripts: standalone CLI tools go in `scripts/`, use `if __name__ == '__main__'` guard.
- Config templates: for each `config/connections/<name>.yaml`, keep a `.yaml.template` with placeholder values.
