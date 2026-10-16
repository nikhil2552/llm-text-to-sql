from __future__ import annotations

from functools import lru_cache
from typing import Iterable
from urllib.parse import quote

import boto3
from sqlalchemy import create_engine, text

from .config import get_settings
from .core import LLMSQLService, parse_catalog


@lru_cache(maxsize=32)
def workgroup_uses_managed_results(workgroup: str, region: str) -> bool:
    """Return True when the workgroup stores results in Athena managed storage."""
    if not workgroup:
        return False
    client = boto3.client('athena', region_name=region)
    response = client.get_work_group(WorkGroup=workgroup)
    configuration = response.get('WorkGroup', {}).get('Configuration', {})
    managed = configuration.get('ManagedQueryResultsConfiguration') or {}
    return bool(managed.get('Enabled'))


def should_omit_s3_staging_dir(workgroup: str, region: str) -> bool:
    """Decide whether to skip S3 ResultConfiguration for this workgroup.

    Resolution order:
    1. ATHENA_USE_MANAGED_RESULTS env var — explicit operator override (True/False).
    2. Live athena:GetWorkGroup API call — source of truth for the workgroup config.
    3. False as safe default if the API call fails (staging dir is included).
    """
    settings = get_settings()
    if settings.athena_use_managed_results is not None:
        return settings.athena_use_managed_results
    try:
        return workgroup_uses_managed_results(workgroup, region)
    except Exception:
        return False


def make_athena_connection_string(
    glue_db_name: str,
    project_files_bucket: str,
    region: str | None = None,
    athena_workgroup: str = 'primary',
    *,
    s3_staging_dir: str | None = None,
) -> str:
    """Build a SQLAlchemy connection URL for PyAthena.

    When the workgroup uses Athena managed query results, pass an empty
    s3_staging_dir so PyAthena does not send ResultConfiguration (conflicts
    with ManagedQueryResultsConfiguration).
    """
    runtime_settings = get_settings()
    region = region or runtime_settings.region or 'eu-north-1'
    connathena = f'athena.{region}.amazonaws.com'
    port = '443'

    query_parts = [f'work_group={quote(athena_workgroup, safe="")}']

    if s3_staging_dir is None:
        if should_omit_s3_staging_dir(athena_workgroup, region):
            # Explicit empty value disables AWS_ATHENA_S3_STAGING_DIR fallback in PyAthena.
            query_parts.insert(0, 's3_staging_dir=')
        else:
            staging = f's3://{project_files_bucket}/athenaresults/'
            query_parts.insert(0, f's3_staging_dir={quote(staging, safe="")}')
    elif s3_staging_dir == '':
        query_parts.insert(0, 's3_staging_dir=')
    else:
        query_parts.insert(0, f's3_staging_dir={quote(s3_staging_dir, safe="")}')

    query = '&'.join(query_parts)
    return f'awsathena+rest://@{connathena}:{port}/{glue_db_name}?{query}'


def create_athena_engine(
    glue_db_name: str,
    project_files_bucket: str,
    region: str | None = None,
    athena_workgroup: str = 'primary',
):
    connection_string = make_athena_connection_string(
        glue_db_name=glue_db_name,
        project_files_bucket=project_files_bucket,
        region=region,
        athena_workgroup=athena_workgroup,
    )
    return create_engine(connection_string, echo=False, pool_pre_ping=True)


class AthenaDB:
    """Minimal SQL executor over a PyAthena SQLAlchemy engine.

    Avoids any ORM/metadata introspection on init (e.g. athena:ListTableMetadata).
    The schema is already loaded from Glue in parse_catalog(), so only run() is
    needed to execute a validated, read-only query and return rows.
    """

    def __init__(self, engine):
        self._engine = engine

    def run(self, sql: str):
        with self._engine.connect() as conn:
            result = conn.execute(text(sql))
            try:
                return [dict(row._mapping) for row in result]
            except Exception:
                return []


def build_athena_service(
    glue_db_names: Iterable[str],
    project_files_bucket: str,
    *,
    region: str | None = None,
    athena_workgroup: str = 'primary',
    bedrock_model: str | None = None,
    max_retries: int | None = None,
    retry_base_delay: float | None = None,
    secrets_manager_secret: str | None = None,
) -> LLMSQLService:
    glue_db_names = list(glue_db_names)
    if not glue_db_names:
        raise ValueError('At least one Glue database name must be provided.')
    runtime_settings = get_settings()
    region = region or runtime_settings.region or 'eu-north-1'
    glue_db_name = glue_db_names[0]
    engine = create_athena_engine(
        glue_db_name=glue_db_name,
        project_files_bucket=project_files_bucket,
        region=region,
        athena_workgroup=athena_workgroup,
    )
    db = AthenaDB(engine)
    glue_catalog, allowed_tables = parse_catalog(glue_db_names, region=region)

    return LLMSQLService(
        db=db,
        glue_catalog=glue_catalog,
        allowed_tables=allowed_tables,
        bedrock_model=bedrock_model or runtime_settings.bedrock_model,
        region=region,
        max_retries=max_retries if max_retries is not None else runtime_settings.bedrock_max_retries,
        retry_base_delay=(
            retry_base_delay
            if retry_base_delay is not None
            else runtime_settings.bedrock_retry_base_delay
        ),
        secrets_manager_secret=(
            secrets_manager_secret
            if secrets_manager_secret is not None
            else runtime_settings.secrets_manager_secret
        ),
        max_result_rows=runtime_settings.max_result_rows,
        max_question_chars=runtime_settings.max_question_chars,
    )
