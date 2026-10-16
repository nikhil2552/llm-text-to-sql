# Implementation Plan: Auto-Populate Connectors

## Overview

Implement automatic connector configuration by querying deployed CloudFormation stacks and generating YAML config files. Three new modules are created (`stack_discovery.py`, `config_generator.py`, `auto_populate.py`) in the existing connector framework, plus Streamlit UI integration for on-demand and startup auto-detection.

## Tasks

- [x] 1. Implement StackDiscoveryService
  - [x] 1.1 Create `src/llm_sql/connectors/stack_discovery.py` with StackInfo dataclass and StackDiscoveryService class
    - Define `StackInfo` dataclass with fields: stack_name, stack_type, available, outputs
    - Implement `__init__` reading region from `AWS_REGION` env var (default `eu-north-1`), stack names from `MAIN_STACK_NAME`, `RDS_STACK_NAME`, `REDSHIFT_STACK_NAME` env vars with documented defaults
    - Implement `is_available_status` static method returning True only for `CREATE_COMPLETE` and `UPDATE_COMPLETE`
    - Implement `_describe_stack` using boto3 CloudFormation client, catching ClientError for non-existent or permission-denied stacks, returning None on failure
    - Implement `_extract_outputs` mapping output keys per stack type (main: ProjectfilesBucketName, AthenaWorkgroupName, LibraryDatabaseName, CarsDatabaseName; rds: ClusterEndpoint, ClusterPort, DatabaseName, SecretName; redshift: RedshiftWorkgroupEndpoint, RedshiftPort, RedshiftDatabase, ConnectionConfig)
    - Implement `discover_all` iterating all known stacks, logging warnings for missing outputs and API errors
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.2, 2.3, 2.4, 10.1, 10.2, 10.3_

  - [x] 1.2 Write property test for stack status classification (Property 1)
    - **Property 1: Stack status classification**
    - Use hypothesis to generate arbitrary status strings and verify `is_available_status` returns True only for CREATE_COMPLETE and UPDATE_COMPLETE
    - **Validates: Requirements 1.2, 1.3**

  - [x] 1.3 Write property test for stack output extraction completeness (Property 2)
    - **Property 2: Stack output extraction completeness**
    - Use hypothesis to generate stack output dictionaries with varying key presence and verify extraction returns all required keys when present, None when any required key is missing
    - **Validates: Requirements 2.1, 2.2, 2.3, 2.4**

  - [x] 1.4 Write property test for configurable stack names with defaults (Property 8)
    - **Property 8: Configurable stack names with defaults**
    - Use hypothesis to generate arbitrary string values for stack name env vars and verify StackDiscoveryService uses them when set, falls back to defaults when unset
    - **Validates: Requirements 10.1, 10.2, 10.3**

  - [x] 1.5 Write unit tests for StackDiscoveryService
    - Create `tests/test_stack_discovery.py` with unittest.TestCase
    - Mock boto3 CloudFormation client for successful discovery, non-existent stacks (ClientError), failed status stacks, missing output keys, and permission errors
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.2, 2.3, 2.4_

- [x] 2. Implement ConfigGenerator
  - [x] 2.1 Create `src/llm_sql/connectors/config_generator.py` with GenerationResult dataclass and ConfigGenerator class
    - Define `GenerationResult` dataclass with fields: connector_type, action, file_path, reason
    - Implement `__init__` accepting optional `config_dir` Path (defaults to `config/connections/`)
    - Implement `_has_existing_config` scanning YAML files for matching `type` field (both enabled and disabled)
    - Implement `generate_athena_config` mapping main stack outputs to Athena YAML dict (type=athena, enabled=true, glue_db_names comma-separated, s3_bucket, workgroup, region)
    - Implement `generate_rds_config` mapping RDS stack outputs to RDS MySQL YAML dict (type=rds_mysql, enabled=true, host, port, database, user_from_secret, region)
    - Implement `generate_redshift_config` mapping Redshift stack outputs to Redshift YAML dict (type=redshift, enabled=true, host, port=5439, database, schema=public, user_from_secret, region)
    - Implement `config_to_yaml` static method for YAML serialization
    - Implement `generate_all` orchestrating generation for all stacks, skipping existing configs, writing YAML files, returning list of GenerationResult
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 6.1, 6.2, 6.3, 6.4, 9.1, 9.2, 9.3_

  - [x] 2.2 Write property test for Athena config generation (Property 3)
    - **Property 3: Athena config generation correctness**
    - Use hypothesis to generate valid main stack outputs and region strings, verify generated config has type=athena, enabled=true, correct field mappings
    - **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6**

  - [x] 2.3 Write property test for RDS config generation (Property 4)
    - **Property 4: RDS config generation correctness**
    - Use hypothesis to generate valid RDS stack outputs and region strings, verify generated config has type=rds_mysql, enabled=true, correct field mappings
    - **Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7**

  - [x] 2.4 Write property test for Redshift config generation (Property 5)
    - **Property 5: Redshift config generation correctness**
    - Use hypothesis to generate valid Redshift stack outputs and region strings, verify generated config has type=redshift, enabled=true, port=5439, schema=public, correct field mappings
    - **Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8**

  - [x] 2.5 Write property test for existing config preservation (Property 6)
    - **Property 6: Existing config preservation**
    - Use hypothesis with temp directories containing generated YAML files with various type fields, verify ConfigGenerator never overwrites existing configs regardless of enabled state
    - **Validates: Requirements 6.1, 6.2, 6.4**

  - [x] 2.6 Write property test for credential security invariant (Property 7)
    - **Property 7: Credential security invariant**
    - Use hypothesis to generate arbitrary stack output strings (including strings that look like credentials), verify generated YAML never contains secret values and only stores secret name references in user_from_secret
    - **Validates: Requirements 9.1, 9.2**

  - [x] 2.7 Write unit tests for ConfigGenerator
    - Create `tests/test_config_generator.py` with unittest.TestCase
    - Test Athena, RDS, Redshift config generation with known inputs
    - Test skip behavior when config already exists (enabled and disabled)
    - Test YAML serialization round-trip
    - Test config directory creation when missing
    - _Requirements: 3.1, 4.1, 5.1, 6.1, 6.2, 6.3, 6.4, 9.1, 9.2, 9.3_

- [x] 3. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Implement AutoPopulateOrchestrator
  - [x] 4.1 Create `src/llm_sql/connectors/auto_populate.py` with AutoPopulateOrchestrator class
    - Implement `__init__` accepting optional `config_dir` Path
    - Implement `should_auto_run` checking if `config/connections/` has no enabled YAML configs (excluding `.yaml.template` files)
    - Implement `run` method coordinating StackDiscoveryService and ConfigGenerator, returning list of GenerationResult
    - Ensure errors never propagate to caller - always return GenerationResult list with action='error' and reason
    - _Requirements: 7.2, 8.1, 8.2_

  - [x] 4.2 Write unit tests for AutoPopulateOrchestrator
    - Create `tests/test_auto_populate.py` with unittest.TestCase
    - Test `should_auto_run` with empty directory, with existing enabled configs, with only templates
    - Test full `run` with mocked StackDiscoveryService
    - Test error handling produces GenerationResult with action='error'
    - _Requirements: 7.2, 8.1, 8.2_

- [x] 5. Integrate with Streamlit UI
  - [x] 5.1 Add auto-detect button and startup logic to `scripts/streamlit_app.py`
    - Add "Auto-detect connections" button in the sidebar below the connector picker
    - On button click, invoke AutoPopulateOrchestrator.run() and display results summary (created, skipped, unavailable)
    - On startup, call `orchestrator.should_auto_run()` and trigger auto-detection if True
    - Display informational banner listing auto-configured connectors on startup detection
    - Display error message with failure reason if auto-detection encounters errors
    - Refresh connector picker (rerun) when new configs are created
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 8.1, 8.2, 8.3_

  - [x] 5.2 Write unit tests for Streamlit integration
    - Test that `should_auto_run` is called on startup
    - Test result display logic for created, skipped, and error states
    - Mock AutoPopulateOrchestrator to verify invocation
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_

- [x] 6. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document (8 properties total)
- Unit tests validate specific examples and edge cases
- All property-based tests use the `hypothesis` library
- Run tests with: `PYTHONPATH=src python -m unittest discover -s tests -p "test_*.py" -v`
- The implementation uses Python 3.11 with boto3 for AWS interactions

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "1.3", "1.4", "1.5", "2.1"] },
    { "id": 2, "tasks": ["2.2", "2.3", "2.4", "2.5", "2.6", "2.7"] },
    { "id": 3, "tasks": ["4.1"] },
    { "id": 4, "tasks": ["4.2", "5.1"] },
    { "id": 5, "tasks": ["5.2"] }
  ]
}
```
