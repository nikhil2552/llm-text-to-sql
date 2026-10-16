# Product Summary

CloudAge Data Architecture with Generative AI — a Text-to-SQL service that converts natural language questions into SQL queries using AWS Bedrock (Amazon Nova models).

## Core Capabilities

- Natural language to SQL translation via LLM (Bedrock)
- Multi-connector framework supporting Athena, Redshift, RDS (PostgreSQL/MySQL), Snowflake, and Databricks
- Read-only query execution with safety guardrails (allowlist validation, automatic LIMIT enforcement, max question length)
- HTTP API (FastAPI) deployed on ECS Fargate
- Streamlit chat UI for interactive querying
- AWS Glue catalog integration for schema discovery
- Infrastructure as Code via CloudFormation (VPC, ECS, Lambda, Glue, S3, Aurora Serverless v2)

## Target Environment

- AWS region: eu-north-1 (primary)
- Deployment: ECS Fargate behind ALB, Docker containers (linux/amd64)
- Data sources configured via YAML files in `config/connections/`
