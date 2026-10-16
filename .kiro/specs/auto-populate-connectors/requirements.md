# Requirements Document

## Introduction

Auto-Populate Connectors enables the Streamlit UI to automatically detect deployed CloudFormation database stacks and generate data source connector configurations without manual YAML editing. The feature queries CloudFormation stack outputs for Athena (main stack), RDS Aurora MySQL, and Redshift Serverless, then writes properly formatted YAML config files to `config/connections/`. This eliminates a manual setup step for operators deploying the Text-to-SQL service.

## Glossary

- **Stack_Discovery_Service**: The Python module responsible for querying AWS CloudFormation APIs to detect deployed database stacks and extract their outputs
- **Config_Generator**: The Python module responsible for transforming stack output data into valid YAML connection configuration files
- **Connector_Config**: A YAML file in `config/connections/` that defines a data source connection (type, settings, enabled state)
- **Main_Stack**: The CloudFormation stack named `cgs-ai-analyst-agent-project` that deploys Athena workgroup, Glue databases, and the S3 bucket
- **RDS_Stack**: The CloudFormation stack named `cgs-ai-rds-aurora` that deploys Aurora Serverless v2 with credentials in Secrets Manager
- **Redshift_Stack**: The CloudFormation stack named `cgs-ai-redshift-serverless` that deploys Redshift Serverless with credentials in Secrets Manager
- **Streamlit_App**: The Streamlit chat UI defined in `scripts/streamlit_app.py`
- **Secret_Reference**: A Secrets Manager secret name string used in YAML config (e.g. `cgs-ai-rds-aurora/aurora-credentials`) - credentials are resolved at runtime, never stored as plaintext

## Requirements

### Requirement 1: Detect Deployed CloudFormation Stacks

**User Story:** As a platform operator, I want the application to automatically detect which database stacks are deployed, so that I do not need to manually check AWS console before configuring connectors.

#### Acceptance Criteria

1. WHEN the Stack_Discovery_Service is invoked, THE Stack_Discovery_Service SHALL query the CloudFormation API for stacks matching the known stack names (cgs-ai-analyst-agent-project, cgs-ai-rds-aurora, cgs-ai-redshift-serverless)
2. WHEN a stack exists with status CREATE_COMPLETE or UPDATE_COMPLETE, THE Stack_Discovery_Service SHALL report that stack as available
3. WHEN a stack does not exist or has a failed status, THE Stack_Discovery_Service SHALL report that stack as unavailable without raising an error
4. THE Stack_Discovery_Service SHALL use the AWS_REGION environment variable to determine which region to query
5. IF the CloudFormation API call fails due to permissions or network issues, THEN THE Stack_Discovery_Service SHALL log the error and return an empty result set

### Requirement 2: Extract Connection Parameters from Stack Outputs

**User Story:** As a platform operator, I want connection parameters to be automatically extracted from stack outputs, so that I get correct endpoint addresses and secret references without copying them manually.

#### Acceptance Criteria

1. WHEN the Main_Stack is detected as available, THE Stack_Discovery_Service SHALL extract the ProjectfilesBucketName, AthenaWorkgroupName, LibraryDatabaseName, and CarsDatabaseName outputs
2. WHEN the RDS_Stack is detected as available, THE Stack_Discovery_Service SHALL extract the ClusterEndpoint, ClusterPort, DatabaseName, and SecretName outputs
3. WHEN the Redshift_Stack is detected as available, THE Stack_Discovery_Service SHALL extract the RedshiftWorkgroupEndpoint, RedshiftPort, RedshiftDatabase, and ConnectionConfig outputs
4. IF a required output key is missing from a detected stack, THEN THE Stack_Discovery_Service SHALL log a warning and skip that stack

### Requirement 3: Generate Athena Connector Configuration

**User Story:** As a platform operator, I want an Athena connector config to be auto-generated from the main stack, so that the Streamlit UI can query Athena immediately after deployment.

#### Acceptance Criteria

1. WHEN the Main_Stack outputs are available, THE Config_Generator SHALL produce a valid Connector_Config YAML file with type set to `athena`
2. THE Config_Generator SHALL set the `glue_db_names` field to a comma-separated list of all discovered Glue database names
3. THE Config_Generator SHALL set the `s3_bucket` field to the ProjectfilesBucketName output value
4. THE Config_Generator SHALL set the `workgroup` field to the AthenaWorkgroupName output value
5. THE Config_Generator SHALL set the `region` field to the current AWS_REGION value
6. THE Config_Generator SHALL set `enabled` to true in the generated configuration

### Requirement 4: Generate RDS Aurora Connector Configuration

**User Story:** As a platform operator, I want an RDS Aurora MySQL connector config to be auto-generated when the RDS stack is deployed, so that the Streamlit UI can query Aurora without manual setup.

#### Acceptance Criteria

1. WHEN the RDS_Stack outputs are available, THE Config_Generator SHALL produce a valid Connector_Config YAML file with type set to `rds_mysql`
2. THE Config_Generator SHALL set the `host` field to the ClusterEndpoint output value
3. THE Config_Generator SHALL set the `port` field to the ClusterPort output value
4. THE Config_Generator SHALL set the `database` field to the DatabaseName output value
5. THE Config_Generator SHALL set the `user_from_secret` field to the SecretName output value (a Secret_Reference)
6. THE Config_Generator SHALL set the `region` field to the current AWS_REGION value
7. THE Config_Generator SHALL set `enabled` to true in the generated configuration

### Requirement 5: Generate Redshift Serverless Connector Configuration

**User Story:** As a platform operator, I want a Redshift Serverless connector config to be auto-generated when the Redshift stack is deployed, so that the Streamlit UI can query Redshift without manual setup.

#### Acceptance Criteria

1. WHEN the Redshift_Stack outputs are available, THE Config_Generator SHALL produce a valid Connector_Config YAML file with type set to `redshift`
2. THE Config_Generator SHALL set the `host` field to the RedshiftWorkgroupEndpoint output value
3. THE Config_Generator SHALL set the `port` field to 5439
4. THE Config_Generator SHALL set the `database` field to the RedshiftDatabase output value
5. THE Config_Generator SHALL set the `schema` field to `public`
6. THE Config_Generator SHALL set the `user_from_secret` field to the Redshift stack secret name (a Secret_Reference)
7. THE Config_Generator SHALL set the `region` field to the current AWS_REGION value
8. THE Config_Generator SHALL set `enabled` to true in the generated configuration

### Requirement 6: Preserve Existing Manual Configurations

**User Story:** As a platform operator, I want auto-population to never overwrite my manually configured connectors, so that custom settings are preserved.

#### Acceptance Criteria

1. WHEN a Connector_Config YAML file already exists for a given connector type, THE Config_Generator SHALL skip writing that file
2. THE Config_Generator SHALL determine file existence by checking for a YAML file in `config/connections/` whose `type` field matches the connector type being generated
3. WHEN a file is skipped due to an existing configuration, THE Config_Generator SHALL log an informational message identifying the skipped connector type
4. THE Config_Generator SHALL treat both enabled and disabled existing configs as existing (neither shall be overwritten)

### Requirement 7: Streamlit UI Integration

**User Story:** As a platform operator, I want to trigger auto-population from the Streamlit sidebar, so that I can populate connectors on demand after deployment.

#### Acceptance Criteria

1. THE Streamlit_App SHALL display an "Auto-detect connections" button in the sidebar
2. WHEN the user clicks the "Auto-detect connections" button, THE Streamlit_App SHALL invoke the Stack_Discovery_Service and Config_Generator
3. WHEN auto-detection completes successfully, THE Streamlit_App SHALL display a summary showing which connectors were created, which were skipped, and which stacks were unavailable
4. IF auto-detection encounters an error, THEN THE Streamlit_App SHALL display an error message with the failure reason
5. WHEN new connector configs are created, THE Streamlit_App SHALL refresh the connector picker to reflect the newly available connections

### Requirement 8: Startup Auto-Detection Mode

**User Story:** As a platform operator, I want connectors to be auto-populated on application startup when no configs exist, so that the first-run experience requires zero manual configuration.

#### Acceptance Criteria

1. WHEN the Streamlit_App starts and the `config/connections/` directory contains no enabled YAML config files (excluding templates), THE Streamlit_App SHALL automatically invoke the Stack_Discovery_Service and Config_Generator
2. WHEN the `config/connections/` directory contains at least one enabled YAML config file, THE Streamlit_App SHALL skip automatic detection on startup
3. WHEN automatic startup detection creates new configs, THE Streamlit_App SHALL display an informational banner listing the auto-configured connectors

### Requirement 9: Credential Security

**User Story:** As a security engineer, I want auto-generated configs to reference Secrets Manager by name only, so that credentials are never stored in plaintext on disk.

#### Acceptance Criteria

1. THE Config_Generator SHALL store only the Secrets Manager secret name in the `user_from_secret` field of generated configs
2. THE Config_Generator SHALL never write plaintext passwords, access keys, or secret values into any generated file
3. THE Config_Generator SHALL never call Secrets Manager GetSecretValue during the auto-population process

### Requirement 10: Configurable Stack Names

**User Story:** As a platform operator deploying with non-default stack names, I want to override the expected stack names via environment variables, so that auto-detection works in custom deployments.

#### Acceptance Criteria

1. THE Stack_Discovery_Service SHALL read the main stack name from the MAIN_STACK_NAME environment variable, defaulting to `cgs-ai-analyst-agent-project`
2. THE Stack_Discovery_Service SHALL read the RDS stack name from the RDS_STACK_NAME environment variable, defaulting to `cgs-ai-rds-aurora`
3. THE Stack_Discovery_Service SHALL read the Redshift stack name from the REDSHIFT_STACK_NAME environment variable, defaulting to `cgs-ai-redshift-serverless`
