"""Property-based tests for ConfigGenerator.

Uses hypothesis to verify correctness properties from the design document.
Feature: auto-populate-connectors
"""

from __future__ import annotations

import os
import sys
import unittest

from hypothesis import given, settings, assume
from hypothesis import strategies as st

# Add project root src to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(project_root, "src"))

from llm_sql.connectors.config_generator import ConfigGenerator
from llm_sql.connectors.stack_discovery import StackInfo


# ─── Strategies ───────────────────────────────────────────────────────────────

# Non-empty strings for stack output values (no null bytes)
output_value_st = st.text(
    min_size=1,
    max_size=100,
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P"),
        blacklist_characters="\x00",
    ),
)

# Region strings (non-empty, alphanumeric with hyphens like real AWS regions)
region_st = st.text(
    min_size=1,
    max_size=30,
    alphabet=st.characters(
        whitelist_categories=("L", "N"),
        whitelist_characters="-",
    ),
)

# Secret name references: format "stack-name/secret-name" with a "/" character
# These simulate ConnectionConfig values that look like secret references
secret_reference_st = st.builds(
    lambda prefix, suffix: f"{prefix}/{suffix}",
    prefix=st.text(
        min_size=1,
        max_size=40,
        alphabet=st.characters(
            whitelist_categories=("L", "N"),
            whitelist_characters="-_",
        ),
    ),
    suffix=st.text(
        min_size=1,
        max_size=40,
        alphabet=st.characters(
            whitelist_categories=("L", "N"),
            whitelist_characters="-_",
        ),
    ),
)


# ─── Strategies for RDS config ────────────────────────────────────────────────

# Generate valid port numbers as strings (1-65535)
port_string_st = st.integers(min_value=1, max_value=65535).map(str)


# Strategy for Glue database names: non-empty strings without commas
# (commas are used as the delimiter in glue_db_names, so names cannot contain them)
glue_db_name_st = st.text(
    min_size=1,
    max_size=100,
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P"),
        blacklist_characters="\x00,",
    ),
)


# ─── Property 3: Athena config generation correctness ─────────────────────────


class TestProperty3AthenaConfigGenerationCorrectness(unittest.TestCase):
    """Property 3: Athena config generation correctness

    For any valid main stack outputs (containing ProjectfilesBucketName,
    AthenaWorkgroupName, LibraryDatabaseName, CarsDatabaseName) and any valid
    AWS region string, the generated Athena config SHALL have type=athena,
    enabled=true, settings.s3_bucket equal to the ProjectfilesBucketName value,
    settings.workgroup equal to the AthenaWorkgroupName value,
    settings.glue_db_names containing all discovered database names as a
    comma-separated list, and settings.region equal to the provided region.

    Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6
    """

    @given(
        bucket_name=output_value_st,
        workgroup_name=output_value_st,
        library_db_name=glue_db_name_st,
        cars_db_name=glue_db_name_st,
        region=region_st,
    )
    @settings(max_examples=100)
    def test_athena_config_generation_correctness(
        self, bucket_name, workgroup_name, library_db_name, cars_db_name, region
    ):
        """Feature: auto-populate-connectors, Property 3: Athena config generation correctness

        For any valid main stack outputs and region string, the generated Athena
        config has type=athena, enabled=true, and settings fields mapped
        correctly from corresponding output values.

        **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6**
        """
        # Arrange: Build a StackInfo with main stack outputs
        stack_info = StackInfo(
            stack_name="test-main-stack",
            stack_type="main",
            available=True,
            outputs={
                "ProjectfilesBucketName": bucket_name,
                "AthenaWorkgroupName": workgroup_name,
                "LibraryDatabaseName": library_db_name,
                "CarsDatabaseName": cars_db_name,
            },
        )

        # Act: Generate the Athena config
        generator = ConfigGenerator()
        config = generator.generate_athena_config(stack_info, region)

        # Assert: type is athena (Req 3.1)
        self.assertEqual(
            config["type"],
            "athena",
            f"Expected type='athena', got '{config['type']}'",
        )

        # Assert: enabled is True (Req 3.6)
        self.assertTrue(
            config["enabled"],
            f"Expected enabled=True, got {config['enabled']}",
        )

        # Assert: settings.s3_bucket maps to ProjectfilesBucketName (Req 3.3)
        self.assertEqual(
            config["settings"]["s3_bucket"],
            bucket_name,
            f"Expected settings.s3_bucket='{bucket_name}', "
            f"got '{config['settings']['s3_bucket']}'",
        )

        # Assert: settings.workgroup maps to AthenaWorkgroupName (Req 3.4)
        self.assertEqual(
            config["settings"]["workgroup"],
            workgroup_name,
            f"Expected settings.workgroup='{workgroup_name}', "
            f"got '{config['settings']['workgroup']}'",
        )

        # Assert: settings.glue_db_names contains both db names comma-separated (Req 3.2)
        glue_db_names = config["settings"]["glue_db_names"]
        db_names_list = [name.strip() for name in glue_db_names.split(",")]
        self.assertIn(
            library_db_name,
            db_names_list,
            f"Expected LibraryDatabaseName '{library_db_name}' in "
            f"glue_db_names '{glue_db_names}'",
        )
        self.assertIn(
            cars_db_name,
            db_names_list,
            f"Expected CarsDatabaseName '{cars_db_name}' in "
            f"glue_db_names '{glue_db_names}'",
        )

        # Assert: settings.region matches provided region (Req 3.5)
        self.assertEqual(
            config["settings"]["region"],
            region,
            f"Expected settings.region='{region}', "
            f"got '{config['settings']['region']}'",
        )


# ─── Property 4: RDS config generation correctness ───────────────────────────


class TestProperty4RDSConfigGenerationCorrectness(unittest.TestCase):
    """Property 4: RDS config generation correctness

    For any valid RDS stack outputs (containing ClusterEndpoint, ClusterPort,
    DatabaseName, SecretName) and any valid AWS region string, the generated
    RDS config SHALL have type=rds_mysql, enabled=true, and settings fields
    mapped exactly from the corresponding output values, with settings.region
    equal to the provided region.

    Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7
    """

    @given(
        cluster_endpoint=output_value_st,
        cluster_port=port_string_st,
        database_name=output_value_st,
        secret_name=output_value_st,
        region=region_st,
    )
    @settings(max_examples=100)
    def test_rds_config_generation_correctness(
        self, cluster_endpoint, cluster_port, database_name, secret_name, region
    ):
        """Feature: auto-populate-connectors, Property 4: RDS config generation correctness

        For any valid RDS stack outputs and region string, the generated config
        has type=rds_mysql, enabled=true, and settings fields mapped correctly
        from corresponding output values.

        **Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7**
        """
        # Arrange: Build a StackInfo with RDS stack outputs
        stack_info = StackInfo(
            stack_name="test-rds-stack",
            stack_type="rds",
            available=True,
            outputs={
                "ClusterEndpoint": cluster_endpoint,
                "ClusterPort": cluster_port,
                "DatabaseName": database_name,
                "SecretName": secret_name,
            },
        )

        # Act: Generate the RDS config
        generator = ConfigGenerator()
        config = generator.generate_rds_config(stack_info, region)

        # Assert: type is rds_mysql
        self.assertEqual(
            config["type"],
            "rds_mysql",
            f"Expected type='rds_mysql', got '{config['type']}'",
        )

        # Assert: enabled is True
        self.assertTrue(
            config["enabled"],
            f"Expected enabled=True, got {config['enabled']}",
        )

        # Assert: settings.host maps to ClusterEndpoint
        self.assertEqual(
            config["settings"]["host"],
            cluster_endpoint,
            f"Expected settings.host='{cluster_endpoint}', "
            f"got '{config['settings']['host']}'",
        )

        # Assert: settings.port maps to int(ClusterPort)
        self.assertEqual(
            config["settings"]["port"],
            int(cluster_port),
            f"Expected settings.port={int(cluster_port)}, "
            f"got {config['settings']['port']}",
        )

        # Assert: settings.database maps to DatabaseName
        self.assertEqual(
            config["settings"]["database"],
            database_name,
            f"Expected settings.database='{database_name}', "
            f"got '{config['settings']['database']}'",
        )

        # Assert: settings.user_from_secret maps to SecretName
        self.assertEqual(
            config["settings"]["user_from_secret"],
            secret_name,
            f"Expected settings.user_from_secret='{secret_name}', "
            f"got '{config['settings']['user_from_secret']}'",
        )

        # Assert: settings.region matches provided region
        self.assertEqual(
            config["settings"]["region"],
            region,
            f"Expected settings.region='{region}', "
            f"got '{config['settings']['region']}'",
        )


# ─── Property 5: Redshift config generation correctness ──────────────────────


class TestProperty5RedshiftConfigGenerationCorrectness(unittest.TestCase):
    """Property 5: Redshift config generation correctness

    For any valid Redshift stack outputs (containing RedshiftWorkgroupEndpoint,
    RedshiftDatabase, and a secret name) and any valid AWS region string, the
    generated Redshift config SHALL have type=redshift, enabled=true,
    settings.port=5439, settings.schema=public, and all other settings fields
    mapped from the corresponding output values, with settings.region equal to
    the provided region.

    Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8
    """

    @given(
        endpoint=output_value_st,
        port_value=output_value_st,
        database=output_value_st,
        connection_config=secret_reference_st,
        region=region_st,
    )
    @settings(max_examples=100)
    def test_redshift_config_has_correct_type_and_enabled(
        self, endpoint, port_value, database, connection_config, region
    ):
        """Feature: auto-populate-connectors, Property 5: Redshift config generation correctness

        Generated Redshift config has type=redshift and enabled=true.

        **Validates: Requirements 5.1, 5.8**
        """
        stack_info = StackInfo(
            stack_name="test-redshift-stack",
            stack_type="redshift",
            available=True,
            outputs={
                "RedshiftWorkgroupEndpoint": endpoint,
                "RedshiftPort": port_value,
                "RedshiftDatabase": database,
                "ConnectionConfig": connection_config,
            },
        )

        config = ConfigGenerator().generate_redshift_config(stack_info, region)

        self.assertEqual(
            config["type"],
            "redshift",
            f"Expected type='redshift', got '{config['type']}'",
        )
        self.assertTrue(
            config["enabled"],
            f"Expected enabled=True, got {config['enabled']}",
        )

    @given(
        endpoint=output_value_st,
        port_value=output_value_st,
        database=output_value_st,
        connection_config=secret_reference_st,
        region=region_st,
    )
    @settings(max_examples=100)
    def test_redshift_config_host_maps_from_endpoint(
        self, endpoint, port_value, database, connection_config, region
    ):
        """Feature: auto-populate-connectors, Property 5: Redshift config generation correctness

        Generated Redshift config settings.host equals RedshiftWorkgroupEndpoint value.

        **Validates: Requirements 5.2**
        """
        stack_info = StackInfo(
            stack_name="test-redshift-stack",
            stack_type="redshift",
            available=True,
            outputs={
                "RedshiftWorkgroupEndpoint": endpoint,
                "RedshiftPort": port_value,
                "RedshiftDatabase": database,
                "ConnectionConfig": connection_config,
            },
        )

        config = ConfigGenerator().generate_redshift_config(stack_info, region)

        self.assertEqual(
            config["settings"]["host"],
            endpoint,
            f"Expected settings.host='{endpoint}', got '{config['settings']['host']}'",
        )

    @given(
        endpoint=output_value_st,
        port_value=output_value_st,
        database=output_value_st,
        connection_config=secret_reference_st,
        region=region_st,
    )
    @settings(max_examples=100)
    def test_redshift_config_port_is_hardcoded_5439(
        self, endpoint, port_value, database, connection_config, region
    ):
        """Feature: auto-populate-connectors, Property 5: Redshift config generation correctness

        Generated Redshift config settings.port is always 5439 (hardcoded, NOT from output).

        **Validates: Requirements 5.3**
        """
        stack_info = StackInfo(
            stack_name="test-redshift-stack",
            stack_type="redshift",
            available=True,
            outputs={
                "RedshiftWorkgroupEndpoint": endpoint,
                "RedshiftPort": port_value,
                "RedshiftDatabase": database,
                "ConnectionConfig": connection_config,
            },
        )

        config = ConfigGenerator().generate_redshift_config(stack_info, region)

        self.assertEqual(
            config["settings"]["port"],
            5439,
            f"Expected settings.port=5439, got {config['settings']['port']}",
        )

    @given(
        endpoint=output_value_st,
        port_value=output_value_st,
        database=output_value_st,
        connection_config=secret_reference_st,
        region=region_st,
    )
    @settings(max_examples=100)
    def test_redshift_config_database_maps_from_output(
        self, endpoint, port_value, database, connection_config, region
    ):
        """Feature: auto-populate-connectors, Property 5: Redshift config generation correctness

        Generated Redshift config settings.database equals RedshiftDatabase value.

        **Validates: Requirements 5.4**
        """
        stack_info = StackInfo(
            stack_name="test-redshift-stack",
            stack_type="redshift",
            available=True,
            outputs={
                "RedshiftWorkgroupEndpoint": endpoint,
                "RedshiftPort": port_value,
                "RedshiftDatabase": database,
                "ConnectionConfig": connection_config,
            },
        )

        config = ConfigGenerator().generate_redshift_config(stack_info, region)

        self.assertEqual(
            config["settings"]["database"],
            database,
            f"Expected settings.database='{database}', got '{config['settings']['database']}'",
        )

    @given(
        endpoint=output_value_st,
        port_value=output_value_st,
        database=output_value_st,
        connection_config=secret_reference_st,
        region=region_st,
    )
    @settings(max_examples=100)
    def test_redshift_config_schema_is_public(
        self, endpoint, port_value, database, connection_config, region
    ):
        """Feature: auto-populate-connectors, Property 5: Redshift config generation correctness

        Generated Redshift config settings.schema is always 'public'.

        **Validates: Requirements 5.5**
        """
        stack_info = StackInfo(
            stack_name="test-redshift-stack",
            stack_type="redshift",
            available=True,
            outputs={
                "RedshiftWorkgroupEndpoint": endpoint,
                "RedshiftPort": port_value,
                "RedshiftDatabase": database,
                "ConnectionConfig": connection_config,
            },
        )

        config = ConfigGenerator().generate_redshift_config(stack_info, region)

        self.assertEqual(
            config["settings"]["schema"],
            "public",
            f"Expected settings.schema='public', got '{config['settings']['schema']}'",
        )

    @given(
        endpoint=output_value_st,
        port_value=output_value_st,
        database=output_value_st,
        connection_config=secret_reference_st,
        region=region_st,
    )
    @settings(max_examples=100)
    def test_redshift_config_user_from_secret_is_nonempty(
        self, endpoint, port_value, database, connection_config, region
    ):
        """Feature: auto-populate-connectors, Property 5: Redshift config generation correctness

        Generated Redshift config settings.user_from_secret is a non-empty string
        (a secret reference).

        **Validates: Requirements 5.6**
        """
        stack_info = StackInfo(
            stack_name="test-redshift-stack",
            stack_type="redshift",
            available=True,
            outputs={
                "RedshiftWorkgroupEndpoint": endpoint,
                "RedshiftPort": port_value,
                "RedshiftDatabase": database,
                "ConnectionConfig": connection_config,
            },
        )

        config = ConfigGenerator().generate_redshift_config(stack_info, region)

        secret_ref = config["settings"]["user_from_secret"]
        self.assertIsInstance(
            secret_ref,
            str,
            f"Expected user_from_secret to be a string, got {type(secret_ref)}",
        )
        self.assertTrue(
            len(secret_ref) > 0,
            "Expected user_from_secret to be non-empty",
        )

    @given(
        endpoint=output_value_st,
        port_value=output_value_st,
        database=output_value_st,
        connection_config=secret_reference_st,
        region=region_st,
    )
    @settings(max_examples=100)
    def test_redshift_config_region_maps_from_provided_region(
        self, endpoint, port_value, database, connection_config, region
    ):
        """Feature: auto-populate-connectors, Property 5: Redshift config generation correctness

        Generated Redshift config settings.region equals the provided region string.

        **Validates: Requirements 5.7**
        """
        stack_info = StackInfo(
            stack_name="test-redshift-stack",
            stack_type="redshift",
            available=True,
            outputs={
                "RedshiftWorkgroupEndpoint": endpoint,
                "RedshiftPort": port_value,
                "RedshiftDatabase": database,
                "ConnectionConfig": connection_config,
            },
        )

        config = ConfigGenerator().generate_redshift_config(stack_info, region)

        self.assertEqual(
            config["settings"]["region"],
            region,
            f"Expected settings.region='{region}', got '{config['settings']['region']}'",
        )


# ─── Strategies for Property 7 ────────────────────────────────────────────────

# Generate strings that look like credentials (passwords, API keys, tokens)
credential_like_st = st.one_of(
    # Random strings that could be passwords
    st.text(min_size=8, max_size=64, alphabet=st.characters(
        whitelist_categories=("L", "N", "P"),
        blacklist_characters="\x00\n\r",
    )),
    # Strings that look like API keys
    st.from_regex(r"AKIA[A-Z0-9]{16}", fullmatch=True),
    # Strings that look like secret keys
    st.from_regex(r"[A-Za-z0-9/+=]{40}", fullmatch=True),
    # Strings with password-like patterns
    st.from_regex(r"[A-Za-z0-9!@#$%^&*]{12,32}", fullmatch=True),
    # Connection strings that might contain credentials
    st.from_regex(r"mysql://user:[a-z0-9]{8}@host/db", fullmatch=True),
)

# Generate secret name references (these look like paths/ARNs, not actual secrets)
secret_name_ref_st = st.one_of(
    # Simple path-like names
    st.from_regex(r"[a-z][a-z0-9-]{3,30}/[a-z-]{3,20}", fullmatch=True),
    # ARN-like patterns
    st.from_regex(r"arn:aws:secretsmanager:[a-z]{2}-[a-z]+-[0-9]:[0-9]{12}:secret:[a-z-]+", fullmatch=True),
    # General non-empty strings
    output_value_st,
)

# Sensitive key names that should never appear in generated configs
SENSITIVE_KEY_NAMES = {
    "password", "access_key", "secret_key", "token",
    "secret_access_key", "api_key", "private_key",
}


# ─── Property 7: Credential security invariant ───────────────────────────────


class TestProperty7CredentialSecurityInvariant(unittest.TestCase):
    """Property 7: Credential security invariant

    For ANY input string as SecretName/ConnectionConfig output, the generated
    config stores it as a reference in `user_from_secret`. The ConfigGenerator
    never resolves/fetches secrets - it only stores the name. Generated YAML
    never contains sensitive key names (password, access_key, secret_key, token).

    Validates: Requirements 9.1, 9.2
    """

    @given(
        cluster_endpoint=output_value_st,
        cluster_port=st.integers(min_value=1, max_value=65535).map(str),
        database_name=output_value_st,
        secret_name=credential_like_st,
        region=region_st,
    )
    @settings(max_examples=100)
    def test_rds_config_yaml_never_contains_sensitive_keys(
        self, cluster_endpoint, cluster_port, database_name, secret_name, region
    ):
        """Feature: auto-populate-connectors, Property 7: Credential security invariant

        For any arbitrary string (including credential-like strings) as the
        SecretName output, the generated RDS config YAML never contains keys
        named 'password', 'access_key', 'secret_key', or 'token'.

        **Validates: Requirements 9.1, 9.2**
        """
        stack_info = StackInfo(
            stack_name="test-rds-stack",
            stack_type="rds",
            available=True,
            outputs={
                "ClusterEndpoint": cluster_endpoint,
                "ClusterPort": cluster_port,
                "DatabaseName": database_name,
                "SecretName": secret_name,
            },
        )

        generator = ConfigGenerator()
        config = generator.generate_rds_config(stack_info, region)
        yaml_output = generator.config_to_yaml(config)

        # Verify no sensitive key names appear in the YAML output
        yaml_lower = yaml_output.lower()
        for sensitive_key in SENSITIVE_KEY_NAMES:
            # Check that sensitive_key does not appear as a YAML key
            # (i.e., at the start of a line or after whitespace, followed by colon)
            self.assertNotIn(
                f"{sensitive_key}:",
                yaml_lower,
                f"Sensitive key '{sensitive_key}' found as a YAML key in output:\n{yaml_output}",
            )

    @given(
        cluster_endpoint=output_value_st,
        cluster_port=st.integers(min_value=1, max_value=65535).map(str),
        database_name=output_value_st,
        secret_name=secret_name_ref_st,
        region=region_st,
    )
    @settings(max_examples=100)
    def test_rds_user_from_secret_stores_only_reference_name(
        self, cluster_endpoint, cluster_port, database_name, secret_name, region
    ):
        """Feature: auto-populate-connectors, Property 7: Credential security invariant

        For any arbitrary SecretName value, the RDS config user_from_secret
        field contains EXACTLY the SecretName reference string - never expanded
        or resolved credential data.

        **Validates: Requirements 9.1, 9.2**
        """
        stack_info = StackInfo(
            stack_name="test-rds-stack",
            stack_type="rds",
            available=True,
            outputs={
                "ClusterEndpoint": cluster_endpoint,
                "ClusterPort": cluster_port,
                "DatabaseName": database_name,
                "SecretName": secret_name,
            },
        )

        generator = ConfigGenerator()
        config = generator.generate_rds_config(stack_info, region)

        # user_from_secret must equal exactly the input secret name reference
        self.assertEqual(
            config["settings"]["user_from_secret"],
            secret_name,
            f"Expected user_from_secret='{secret_name}', "
            f"got '{config['settings']['user_from_secret']}'",
        )

    @given(
        endpoint=output_value_st,
        database=output_value_st,
        connection_config=credential_like_st,
        region=region_st,
    )
    @settings(max_examples=100)
    def test_redshift_config_yaml_never_contains_sensitive_keys(
        self, endpoint, database, connection_config, region
    ):
        """Feature: auto-populate-connectors, Property 7: Credential security invariant

        For any arbitrary string (including credential-like strings) as the
        ConnectionConfig output, the generated Redshift config YAML never
        contains keys named 'password', 'access_key', 'secret_key', or 'token'.

        **Validates: Requirements 9.1, 9.2**
        """
        stack_info = StackInfo(
            stack_name="test-redshift-stack",
            stack_type="redshift",
            available=True,
            outputs={
                "RedshiftWorkgroupEndpoint": endpoint,
                "RedshiftPort": "5439",
                "RedshiftDatabase": database,
                "ConnectionConfig": connection_config,
            },
        )

        generator = ConfigGenerator()
        config = generator.generate_redshift_config(stack_info, region)
        yaml_output = generator.config_to_yaml(config)

        # Verify no sensitive key names appear as YAML keys
        yaml_lower = yaml_output.lower()
        for sensitive_key in SENSITIVE_KEY_NAMES:
            self.assertNotIn(
                f"{sensitive_key}:",
                yaml_lower,
                f"Sensitive key '{sensitive_key}' found as a YAML key in output:\n{yaml_output}",
            )

    @given(
        endpoint=output_value_st,
        database=output_value_st,
        connection_config=secret_name_ref_st,
        region=region_st,
    )
    @settings(max_examples=100)
    def test_redshift_user_from_secret_stores_only_reference(
        self, endpoint, database, connection_config, region
    ):
        """Feature: auto-populate-connectors, Property 7: Credential security invariant

        For any arbitrary ConnectionConfig value that looks like a secret name
        reference (path-like, with slash), the Redshift config user_from_secret
        field contains only the reference name - never actual credential data.

        **Validates: Requirements 9.1, 9.2**
        """
        stack_info = StackInfo(
            stack_name="test-redshift-stack",
            stack_type="redshift",
            available=True,
            outputs={
                "RedshiftWorkgroupEndpoint": endpoint,
                "RedshiftPort": "5439",
                "RedshiftDatabase": database,
                "ConnectionConfig": connection_config,
            },
        )

        generator = ConfigGenerator()
        config = generator.generate_redshift_config(stack_info, region)

        # user_from_secret must be a string (reference name), never None
        self.assertIsInstance(
            config["settings"]["user_from_secret"],
            str,
            "user_from_secret should be a string reference",
        )
        # It should never be empty
        self.assertTrue(
            len(config["settings"]["user_from_secret"]) > 0,
            "user_from_secret should not be empty",
        )

    @given(
        cluster_endpoint=output_value_st,
        cluster_port=st.integers(min_value=1, max_value=65535).map(str),
        database_name=output_value_st,
        secret_name=credential_like_st,
        region=region_st,
    )
    @settings(max_examples=100)
    def test_rds_yaml_does_not_contain_raw_output_values_as_secrets(
        self, cluster_endpoint, cluster_port, database_name, secret_name, region
    ):
        """Feature: auto-populate-connectors, Property 7: Credential security invariant

        The generated YAML never contains raw stack output values in unexpected
        positions. The secret_name appears ONLY as the value of user_from_secret,
        not duplicated elsewhere or embedded in other fields.

        **Validates: Requirements 9.1, 9.2**
        """
        stack_info = StackInfo(
            stack_name="test-rds-stack",
            stack_type="rds",
            available=True,
            outputs={
                "ClusterEndpoint": cluster_endpoint,
                "ClusterPort": cluster_port,
                "DatabaseName": database_name,
                "SecretName": secret_name,
            },
        )

        generator = ConfigGenerator()
        config = generator.generate_rds_config(stack_info, region)
        yaml_output = generator.config_to_yaml(config)

        # Verify the config dict has no keys with sensitive names
        all_keys = set()
        self._collect_keys(config, all_keys)

        for sensitive_key in SENSITIVE_KEY_NAMES:
            self.assertNotIn(
                sensitive_key,
                all_keys,
                f"Sensitive key '{sensitive_key}' found in config dict keys: {all_keys}",
            )

    @given(
        endpoint=output_value_st,
        database=output_value_st,
        connection_config=credential_like_st,
        region=region_st,
    )
    @settings(max_examples=100)
    def test_redshift_yaml_does_not_contain_raw_output_values_as_secrets(
        self, endpoint, database, connection_config, region
    ):
        """Feature: auto-populate-connectors, Property 7: Credential security invariant

        The generated Redshift config dict has no keys with sensitive names
        (password, access_key, secret_key, token).

        **Validates: Requirements 9.1, 9.2**
        """
        stack_info = StackInfo(
            stack_name="test-redshift-stack",
            stack_type="redshift",
            available=True,
            outputs={
                "RedshiftWorkgroupEndpoint": endpoint,
                "RedshiftPort": "5439",
                "RedshiftDatabase": database,
                "ConnectionConfig": connection_config,
            },
        )

        generator = ConfigGenerator()
        config = generator.generate_redshift_config(stack_info, region)

        # Verify the config dict has no keys with sensitive names
        all_keys = set()
        self._collect_keys(config, all_keys)

        for sensitive_key in SENSITIVE_KEY_NAMES:
            self.assertNotIn(
                sensitive_key,
                all_keys,
                f"Sensitive key '{sensitive_key}' found in config dict keys: {all_keys}",
            )

    def test_config_generator_module_does_not_import_secretsmanager(self):
        """Feature: auto-populate-connectors, Property 7: Credential security invariant

        The config_generator module never imports or calls Secrets Manager.
        This verifies requirement 9.2 - no secret resolution happens during
        config generation.

        **Validates: Requirements 9.2**
        """
        import inspect
        import llm_sql.connectors.config_generator as cg_module

        source = inspect.getsource(cg_module)

        # Check that the module source does not contain secretsmanager references
        self.assertNotIn(
            "secretsmanager",
            source.lower(),
            "config_generator module should not reference secretsmanager",
        )
        self.assertNotIn(
            "get_secret_value",
            source,
            "config_generator module should not call get_secret_value",
        )
        self.assertNotIn(
            "GetSecretValue",
            source,
            "config_generator module should not call GetSecretValue",
        )

    def _collect_keys(self, obj: dict | list, keys: set) -> None:
        """Recursively collect all dictionary keys from a nested structure."""
        if isinstance(obj, dict):
            for key, value in obj.items():
                keys.add(key)
                self._collect_keys(value, keys)
        elif isinstance(obj, list):
            for item in obj:
                self._collect_keys(item, keys)


# ─── Strategies for Property 6 ────────────────────────────────────────────────

# Connector types that ConfigGenerator handles
connector_type_st = st.sampled_from(["athena", "rds_mysql", "redshift"])

# Boolean strategy for enabled field
enabled_st = st.booleans()


# ─── Helper: Build stacks that would generate a given connector type ─────────


def build_stack_for_type(connector_type: str) -> StackInfo:
    """Build a StackInfo with valid outputs that would produce the given connector type."""
    if connector_type == "athena":
        return StackInfo(
            stack_name="main",
            stack_type="main",
            available=True,
            outputs={
                "ProjectfilesBucketName": "test-bucket",
                "AthenaWorkgroupName": "test-workgroup",
                "LibraryDatabaseName": "lib_db",
                "CarsDatabaseName": "cars_db",
            },
        )
    elif connector_type == "rds_mysql":
        return StackInfo(
            stack_name="rds",
            stack_type="rds",
            available=True,
            outputs={
                "ClusterEndpoint": "test-host.rds.amazonaws.com",
                "ClusterPort": "3306",
                "DatabaseName": "test_db",
                "SecretName": "rds/test-secret",
            },
        )
    elif connector_type == "redshift":
        return StackInfo(
            stack_name="redshift",
            stack_type="redshift",
            available=True,
            outputs={
                "RedshiftWorkgroupEndpoint": "test-host.redshift.amazonaws.com",
                "RedshiftPort": "5439",
                "RedshiftDatabase": "test_analytics",
                "ConnectionConfig": "redshift/test-secret",
            },
        )
    else:
        raise ValueError(f"Unknown connector type: {connector_type}")


# ─── Property 6: Existing config preservation ────────────────────────────────


class TestProperty6ExistingConfigPreservation(unittest.TestCase):
    """Property 6: Existing config preservation

    For any config directory containing YAML files with various type fields
    (both enabled and disabled), the ConfigGenerator SHALL never write a file
    for a connector type that already has a matching type field in any existing
    YAML file in the directory.

    Validates: Requirements 6.1, 6.2, 6.4
    """

    @given(
        connector_type=connector_type_st,
        enabled=enabled_st,
    )
    @settings(max_examples=100)
    def test_has_existing_config_detects_matching_type(self, connector_type, enabled):
        """Feature: auto-populate-connectors, Property 6: Existing config preservation

        When a YAML file with a matching type field exists in the config
        directory, _has_existing_config SHALL return True regardless of the
        enabled state.

        **Validates: Requirements 6.1, 6.2, 6.4**
        """
        import tempfile
        from pathlib import Path
        import yaml

        with tempfile.TemporaryDirectory() as temp_dir:
            # Create a YAML file with the generated connector type and enabled state
            existing_config = {
                "name": "Existing",
                "type": connector_type,
                "enabled": enabled,
            }
            yaml_path = Path(temp_dir) / f"existing_{connector_type}.yaml"
            yaml_path.write_text(yaml.dump(existing_config), encoding="utf-8")

            # Create ConfigGenerator pointing to this temp directory
            gen = ConfigGenerator(config_dir=Path(temp_dir))

            # Verify _has_existing_config returns True
            result = gen._has_existing_config(connector_type)

            self.assertTrue(
                result,
                f"Expected _has_existing_config('{connector_type}') to return True "
                f"when a file with type='{connector_type}' and enabled={enabled} exists, "
                f"but got False",
            )

    @given(
        connector_type=connector_type_st,
        enabled=enabled_st,
    )
    @settings(max_examples=100)
    def test_generate_all_skips_existing_config(self, connector_type, enabled):
        """Feature: auto-populate-connectors, Property 6: Existing config preservation

        When a YAML file with a matching type field exists, generate_all SHALL
        return action='skipped' for that connector type (not 'created'), and
        the original file content SHALL remain unchanged.

        **Validates: Requirements 6.1, 6.2, 6.4**
        """
        import tempfile
        from pathlib import Path
        import yaml

        with tempfile.TemporaryDirectory() as temp_dir:
            # Create an existing YAML config
            existing_config = {
                "name": "Existing",
                "type": connector_type,
                "enabled": enabled,
            }
            yaml_path = Path(temp_dir) / f"existing_{connector_type}.yaml"
            original_content = yaml.dump(existing_config)
            yaml_path.write_text(original_content, encoding="utf-8")

            # Create ConfigGenerator pointing to this temp directory
            gen = ConfigGenerator(config_dir=Path(temp_dir))

            # Build a stack that would normally produce a config for this type
            stack = build_stack_for_type(connector_type)

            # Call generate_all
            results = gen.generate_all([stack], "eu-north-1")

            # Should have exactly one result for this connector type
            matching_results = [
                r for r in results if r.connector_type == connector_type
            ]
            self.assertEqual(
                len(matching_results),
                1,
                f"Expected exactly 1 result for '{connector_type}', got {len(matching_results)}",
            )

            # The action should be 'skipped', not 'created'
            result = matching_results[0]
            self.assertEqual(
                result.action,
                "skipped",
                f"Expected action='skipped' for existing config "
                f"type='{connector_type}' enabled={enabled}, got '{result.action}'",
            )

            # Verify the original file content is unchanged
            current_content = yaml_path.read_text(encoding="utf-8")
            self.assertEqual(
                current_content,
                original_content,
                f"Original YAML file was modified! "
                f"Expected:\n{original_content}\nGot:\n{current_content}",
            )

    @given(
        connector_type=connector_type_st,
        enabled=enabled_st,
    )
    @settings(max_examples=100)
    def test_no_new_files_created_when_config_exists(self, connector_type, enabled):
        """Feature: auto-populate-connectors, Property 6: Existing config preservation

        When a config already exists for a connector type, generate_all SHALL
        not create any new YAML files for that type in the config directory.

        **Validates: Requirements 6.1, 6.2, 6.4**
        """
        import tempfile
        from pathlib import Path
        import yaml

        with tempfile.TemporaryDirectory() as temp_dir:
            # Create an existing YAML config
            existing_config = {
                "name": "Existing",
                "type": connector_type,
                "enabled": enabled,
            }
            yaml_path = Path(temp_dir) / f"existing_{connector_type}.yaml"
            yaml_path.write_text(yaml.dump(existing_config), encoding="utf-8")

            # Record files before generate_all
            files_before = set(os.listdir(temp_dir))

            # Create ConfigGenerator and run generate_all
            gen = ConfigGenerator(config_dir=Path(temp_dir))
            stack = build_stack_for_type(connector_type)
            gen.generate_all([stack], "eu-north-1")

            # Record files after generate_all
            files_after = set(os.listdir(temp_dir))

            # No new files should have been created
            new_files = files_after - files_before
            self.assertEqual(
                new_files,
                set(),
                f"New files were created when config for '{connector_type}' "
                f"already existed (enabled={enabled}): {new_files}",
            )


if __name__ == "__main__":
    unittest.main()
