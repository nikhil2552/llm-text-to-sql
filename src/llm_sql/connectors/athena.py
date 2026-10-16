"""Athena connector — wraps the existing Athena/Glue logic into the connector interface."""
from __future__ import annotations

from typing import Any

from llm_sql.connectors.base import BaseConnector


class AthenaConnector(BaseConnector):
    """Connector for AWS Athena via Glue catalog.

    Settings:
        glue_db_name: Primary Glue database name
        glue_db_names: Comma-separated list of Glue databases (overrides glue_db_name)
        s3_bucket: S3 bucket for data and Athena results
        workgroup: Athena workgroup name
        region: AWS region
    """

    @property
    def dialect(self) -> str:
        return "athena"

    def _get_service(self):
        """Lazy-build the LLMSQLService using existing runner logic."""
        if not hasattr(self, '_service'):
            from llm_sql.runner import build_athena_service

            glue_db_names_raw = self.settings.get('glue_db_names', '')
            if glue_db_names_raw:
                glue_db_names = [n.strip() for n in glue_db_names_raw.split(',') if n.strip()]
            else:
                glue_db_names = [self.settings['glue_db_name']]

            self._service = build_athena_service(
                glue_db_names=glue_db_names,
                project_files_bucket=self.settings['s3_bucket'],
                region=self.settings.get('region', 'eu-north-1'),
                athena_workgroup=self.settings.get('workgroup', 'primary'),
            )
        return self._service

    def get_schema(self) -> tuple[str, set[str]]:
        """Get schema from Glue catalog via the existing service."""
        service = self._get_service()
        return service.glue_catalog, service.allowed_tables

    def execute_sql(self, sql: str) -> list[dict[str, Any]]:
        """Execute SQL via Athena."""
        service = self._get_service()
        result = service.db.run(sql)
        if isinstance(result, str):
            # Defensive: wrap a scalar/string result into the row-dict shape
            return [{'result': result}]
        return result

    def run_query(self, question: str) -> str:
        """Full LLM-powered query: question → SQL → execute → answer.

        This is the high-level method that uses Bedrock to generate SQL.
        """
        service = self._get_service()
        return service.run_query(question)
