"""Unit tests for ConfigGenerator."""

import os
import tempfile
import unittest
from pathlib import Path

import yaml

from llm_sql.connectors.config_generator import ConfigGenerator, GenerationResult
from llm_sql.connectors.stack_discovery import StackInfo


class TestGenerationResult(unittest.TestCase):
    """Tests for the GenerationResult dataclass."""

    def test_creation_with_defaults(self):
        result = GenerationResult(connector_type="athena", action="created")
        self.assertEqual(result.connector_type, "athena")
        self.assertEqual(result.action, "created")
        self.assertIsNone(result.file_path)
        self.assertIsNone(result.reason)

    def test_creation_with_all_fields(self):
        result = GenerationResult(
            connector_type="rds_mysql",
            action="error",
            file_path="/tmp/test.yaml",
            reason="Permission denied",
        )
        self.assertEqual(result.connector_type, "rds_mysql")
        self.assertEqual(result.action, "error")
        self.assertEqual(result.file_path, "/tmp/test.yaml")
        self.assertEqual(result.reason, "Permission denied")


class TestConfigGeneratorInit(unittest.TestCase):
    """Tests for ConfigGenerator initialization."""

    def test_default_config_dir(self):
        gen = ConfigGenerator()
        self.assertEqual(gen.config_dir, Path("config/connections/"))

    def test_custom_config_dir(self):
        custom_path = Path("/tmp/custom_configs")
        gen = ConfigGenerator(config_dir=custom_path)
        self.assertEqual(gen.config_dir, custom_path)


class TestGenerateAthenaConfig(unittest.TestCase):
    """Tests for Athena config generation."""

    def setUp(self):
        self.gen = ConfigGenerator()
        self.stack_info = StackInfo(
            stack_name="cgs-ai-analyst-agent-project",
            stack_type="main",
            available=True,
            outputs={
                "ProjectfilesBucketName": "langchain-123456789012-eu-north-1",
                "AthenaWorkgroupName": "project-text-to-sql",
                "LibraryDatabaseName": "project_library_db",
                "CarsDatabaseName": "project_cars_db",
            },
        )

    def test_generates_correct_structure(self):
        config = self.gen.generate_athena_config(self.stack_info, "eu-north-1")
        self.assertEqual(config["name"], "Athena (Auto-detected)")
        self.assertEqual(config["type"], "athena")
        self.assertTrue(config["enabled"])
        self.assertIn("settings", config)

    def test_maps_s3_bucket(self):
        config = self.gen.generate_athena_config(self.stack_info, "eu-north-1")
        self.assertEqual(
            config["settings"]["s3_bucket"], "langchain-123456789012-eu-north-1"
        )

    def test_maps_workgroup(self):
        config = self.gen.generate_athena_config(self.stack_info, "eu-north-1")
        self.assertEqual(config["settings"]["workgroup"], "project-text-to-sql")

    def test_maps_glue_db_names_comma_separated(self):
        config = self.gen.generate_athena_config(self.stack_info, "eu-north-1")
        self.assertEqual(
            config["settings"]["glue_db_names"],
            "project_library_db,project_cars_db",
        )

    def test_maps_region(self):
        config = self.gen.generate_athena_config(self.stack_info, "us-east-1")
        self.assertEqual(config["settings"]["region"], "us-east-1")


class TestGenerateRdsConfig(unittest.TestCase):
    """Tests for RDS MySQL config generation."""

    def setUp(self):
        self.gen = ConfigGenerator()
        self.stack_info = StackInfo(
            stack_name="cgs-ai-rds-aurora",
            stack_type="rds",
            available=True,
            outputs={
                "ClusterEndpoint": "cgs-ai-rds-aurora-auroracluster-xxx.cluster-yyy.eu-north-1.rds.amazonaws.com",
                "ClusterPort": "3306",
                "DatabaseName": "analyst_db",
                "SecretName": "cgs-ai-rds-aurora/aurora-credentials",
            },
        )

    def test_generates_correct_structure(self):
        config = self.gen.generate_rds_config(self.stack_info, "eu-north-1")
        self.assertEqual(config["name"], "RDS Aurora MySQL (Auto-detected)")
        self.assertEqual(config["type"], "rds_mysql")
        self.assertTrue(config["enabled"])
        self.assertIn("settings", config)

    def test_maps_host(self):
        config = self.gen.generate_rds_config(self.stack_info, "eu-north-1")
        self.assertEqual(
            config["settings"]["host"],
            "cgs-ai-rds-aurora-auroracluster-xxx.cluster-yyy.eu-north-1.rds.amazonaws.com",
        )

    def test_maps_port_as_integer(self):
        config = self.gen.generate_rds_config(self.stack_info, "eu-north-1")
        self.assertEqual(config["settings"]["port"], 3306)
        self.assertIsInstance(config["settings"]["port"], int)

    def test_maps_database(self):
        config = self.gen.generate_rds_config(self.stack_info, "eu-north-1")
        self.assertEqual(config["settings"]["database"], "analyst_db")

    def test_maps_secret_reference(self):
        config = self.gen.generate_rds_config(self.stack_info, "eu-north-1")
        self.assertEqual(
            config["settings"]["user_from_secret"],
            "cgs-ai-rds-aurora/aurora-credentials",
        )

    def test_maps_region(self):
        config = self.gen.generate_rds_config(self.stack_info, "eu-north-1")
        self.assertEqual(config["settings"]["region"], "eu-north-1")


class TestGenerateRedshiftConfig(unittest.TestCase):
    """Tests for Redshift config generation."""

    def setUp(self):
        self.gen = ConfigGenerator()
        self.stack_info = StackInfo(
            stack_name="cgs-ai-redshift-serverless",
            stack_type="redshift",
            available=True,
            outputs={
                "RedshiftWorkgroupEndpoint": "cgs-ai-redshift-serverless-wg.xxx.eu-north-1.redshift-serverless.amazonaws.com",
                "RedshiftPort": "5439",
                "RedshiftDatabase": "analytics",
                "ConnectionConfig": "cgs-ai-redshift-serverless/redshift-credentials",
            },
        )

    def test_generates_correct_structure(self):
        config = self.gen.generate_redshift_config(self.stack_info, "eu-north-1")
        self.assertEqual(config["name"], "Redshift Serverless (Auto-detected)")
        self.assertEqual(config["type"], "redshift")
        self.assertTrue(config["enabled"])
        self.assertIn("settings", config)

    def test_maps_host(self):
        config = self.gen.generate_redshift_config(self.stack_info, "eu-north-1")
        self.assertEqual(
            config["settings"]["host"],
            "cgs-ai-redshift-serverless-wg.xxx.eu-north-1.redshift-serverless.amazonaws.com",
        )

    def test_port_hardcoded_5439(self):
        config = self.gen.generate_redshift_config(self.stack_info, "eu-north-1")
        self.assertEqual(config["settings"]["port"], 5439)

    def test_maps_database(self):
        config = self.gen.generate_redshift_config(self.stack_info, "eu-north-1")
        self.assertEqual(config["settings"]["database"], "analytics")

    def test_schema_defaults_to_public(self):
        config = self.gen.generate_redshift_config(self.stack_info, "eu-north-1")
        self.assertEqual(config["settings"]["schema"], "public")

    def test_maps_secret_from_connection_config(self):
        config = self.gen.generate_redshift_config(self.stack_info, "eu-north-1")
        self.assertEqual(
            config["settings"]["user_from_secret"],
            "cgs-ai-redshift-serverless/redshift-credentials",
        )

    def test_secret_fallback_from_stack_name(self):
        stack_info = StackInfo(
            stack_name="my-redshift-stack",
            stack_type="redshift",
            available=True,
            outputs={
                "RedshiftWorkgroupEndpoint": "host.example.com",
                "RedshiftPort": "5439",
                "RedshiftDatabase": "mydb",
                "ConnectionConfig": "",
            },
        )
        config = self.gen.generate_redshift_config(stack_info, "eu-north-1")
        self.assertEqual(
            config["settings"]["user_from_secret"],
            "my-redshift-stack/redshift-credentials",
        )

    def test_secret_from_json_connection_config(self):
        import json

        stack_info = StackInfo(
            stack_name="cgs-ai-redshift-serverless",
            stack_type="redshift",
            available=True,
            outputs={
                "RedshiftWorkgroupEndpoint": "host.example.com",
                "RedshiftPort": "5439",
                "RedshiftDatabase": "mydb",
                "ConnectionConfig": json.dumps(
                    {"secret_name": "my-custom/secret-ref"}
                ),
            },
        )
        config = self.gen.generate_redshift_config(stack_info, "eu-north-1")
        self.assertEqual(
            config["settings"]["user_from_secret"], "my-custom/secret-ref"
        )

    def test_maps_region(self):
        config = self.gen.generate_redshift_config(self.stack_info, "eu-north-1")
        self.assertEqual(config["settings"]["region"], "eu-north-1")


class TestHasExistingConfig(unittest.TestCase):
    """Tests for _has_existing_config method."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.gen = ConfigGenerator(config_dir=Path(self.temp_dir))

    def test_returns_false_for_empty_directory(self):
        self.assertFalse(self.gen._has_existing_config("athena"))

    def test_returns_true_when_type_matches(self):
        config = {"name": "My Athena", "type": "athena", "enabled": True}
        yaml_path = Path(self.temp_dir) / "my_athena.yaml"
        yaml_path.write_text(yaml.dump(config), encoding="utf-8")
        self.assertTrue(self.gen._has_existing_config("athena"))

    def test_returns_true_for_disabled_config(self):
        config = {"name": "Disabled Athena", "type": "athena", "enabled": False}
        yaml_path = Path(self.temp_dir) / "disabled.yaml"
        yaml_path.write_text(yaml.dump(config), encoding="utf-8")
        self.assertTrue(self.gen._has_existing_config("athena"))

    def test_returns_false_when_type_does_not_match(self):
        config = {"name": "RDS MySQL", "type": "rds_mysql", "enabled": True}
        yaml_path = Path(self.temp_dir) / "rds.yaml"
        yaml_path.write_text(yaml.dump(config), encoding="utf-8")
        self.assertFalse(self.gen._has_existing_config("athena"))

    def test_returns_false_for_nonexistent_directory(self):
        gen = ConfigGenerator(config_dir=Path("/tmp/nonexistent_dir_xyz"))
        self.assertFalse(gen._has_existing_config("athena"))


class TestConfigToYaml(unittest.TestCase):
    """Tests for config_to_yaml static method."""

    def test_serializes_dict_to_yaml(self):
        config = {"name": "Test", "type": "athena", "enabled": True}
        result = ConfigGenerator.config_to_yaml(config)
        parsed = yaml.safe_load(result)
        self.assertEqual(parsed, config)

    def test_preserves_key_order(self):
        config = {"name": "First", "type": "second", "enabled": True}
        result = ConfigGenerator.config_to_yaml(config)
        lines = result.strip().split("\n")
        self.assertTrue(lines[0].startswith("name:"))
        self.assertTrue(lines[1].startswith("type:"))

    def test_handles_nested_settings(self):
        config = {
            "name": "Test",
            "settings": {"host": "localhost", "port": 3306},
        }
        result = ConfigGenerator.config_to_yaml(config)
        parsed = yaml.safe_load(result)
        self.assertEqual(parsed["settings"]["host"], "localhost")
        self.assertEqual(parsed["settings"]["port"], 3306)


class TestGenerateAll(unittest.TestCase):
    """Tests for the generate_all orchestration method."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.gen = ConfigGenerator(config_dir=Path(self.temp_dir))

    def test_creates_athena_config_file(self):
        stacks = [
            StackInfo(
                stack_name="cgs-ai-analyst-agent-project",
                stack_type="main",
                available=True,
                outputs={
                    "ProjectfilesBucketName": "my-bucket",
                    "AthenaWorkgroupName": "my-workgroup",
                    "LibraryDatabaseName": "lib_db",
                    "CarsDatabaseName": "cars_db",
                },
            ),
        ]
        results = self.gen.generate_all(stacks, "eu-north-1")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].action, "created")
        self.assertEqual(results[0].connector_type, "athena")
        # Verify file was written
        written_file = Path(results[0].file_path)
        self.assertTrue(written_file.exists())
        content = yaml.safe_load(written_file.read_text())
        self.assertEqual(content["type"], "athena")

    def test_skips_unavailable_stacks(self):
        stacks = [
            StackInfo(
                stack_name="cgs-ai-rds-aurora",
                stack_type="rds",
                available=False,
                outputs={},
            ),
        ]
        results = self.gen.generate_all(stacks, "eu-north-1")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].action, "unavailable")
        self.assertEqual(results[0].connector_type, "rds_mysql")

    def test_skips_existing_configs(self):
        # Write an existing athena config
        existing = {"name": "Manual Athena", "type": "athena", "enabled": True}
        (Path(self.temp_dir) / "existing.yaml").write_text(
            yaml.dump(existing), encoding="utf-8"
        )
        stacks = [
            StackInfo(
                stack_name="cgs-ai-analyst-agent-project",
                stack_type="main",
                available=True,
                outputs={
                    "ProjectfilesBucketName": "bucket",
                    "AthenaWorkgroupName": "wg",
                    "LibraryDatabaseName": "db1",
                    "CarsDatabaseName": "db2",
                },
            ),
        ]
        results = self.gen.generate_all(stacks, "eu-north-1")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].action, "skipped")

    def test_generates_all_three_types(self):
        stacks = [
            StackInfo(
                stack_name="cgs-ai-analyst-agent-project",
                stack_type="main",
                available=True,
                outputs={
                    "ProjectfilesBucketName": "bucket",
                    "AthenaWorkgroupName": "wg",
                    "LibraryDatabaseName": "db1",
                    "CarsDatabaseName": "db2",
                },
            ),
            StackInfo(
                stack_name="cgs-ai-rds-aurora",
                stack_type="rds",
                available=True,
                outputs={
                    "ClusterEndpoint": "host.rds.amazonaws.com",
                    "ClusterPort": "3306",
                    "DatabaseName": "mydb",
                    "SecretName": "rds/secret",
                },
            ),
            StackInfo(
                stack_name="cgs-ai-redshift-serverless",
                stack_type="redshift",
                available=True,
                outputs={
                    "RedshiftWorkgroupEndpoint": "host.redshift.amazonaws.com",
                    "RedshiftPort": "5439",
                    "RedshiftDatabase": "analytics",
                    "ConnectionConfig": "cgs-ai-redshift-serverless/redshift-credentials",
                },
            ),
        ]
        results = self.gen.generate_all(stacks, "eu-north-1")
        self.assertEqual(len(results), 3)
        actions = {r.connector_type: r.action for r in results}
        self.assertEqual(actions["athena"], "created")
        self.assertEqual(actions["rds_mysql"], "created")
        self.assertEqual(actions["redshift"], "created")

    def test_creates_config_dir_if_missing(self):
        new_dir = Path(self.temp_dir) / "subdir" / "configs"
        gen = ConfigGenerator(config_dir=new_dir)
        stacks = [
            StackInfo(
                stack_name="cgs-ai-analyst-agent-project",
                stack_type="main",
                available=True,
                outputs={
                    "ProjectfilesBucketName": "bucket",
                    "AthenaWorkgroupName": "wg",
                    "LibraryDatabaseName": "db1",
                    "CarsDatabaseName": "db2",
                },
            ),
        ]
        results = gen.generate_all(stacks, "eu-north-1")
        self.assertEqual(results[0].action, "created")
        self.assertTrue(new_dir.exists())


if __name__ == "__main__":
    unittest.main()
