"""Unit tests for AutoPopulateOrchestrator.

Validates: Requirements 7.2, 8.1, 8.2
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from llm_sql.connectors.auto_populate import AutoPopulateOrchestrator
from llm_sql.connectors.config_generator import GenerationResult
from llm_sql.connectors.stack_discovery import StackInfo


def _main_stack_info(available=True):
    """Return a valid main StackInfo."""
    return StackInfo(
        stack_name="cgs-ai-analyst-agent-project",
        stack_type="main",
        available=available,
        outputs={
            "ProjectfilesBucketName": "langchain-123456789012-eu-north-1",
            "AthenaWorkgroupName": "project-text-to-sql",
            "LibraryDatabaseName": "project_library_db",
            "CarsDatabaseName": "project_cars_db",
        } if available else {},
    )


def _rds_stack_info(available=True):
    """Return a valid RDS StackInfo."""
    return StackInfo(
        stack_name="cgs-ai-rds-aurora",
        stack_type="rds",
        available=available,
        outputs={
            "ClusterEndpoint": "cgs-ai-rds-aurora-cluster.cluster-abc.eu-north-1.rds.amazonaws.com",
            "ClusterPort": "3306",
            "DatabaseName": "analyst_db",
            "SecretName": "cgs-ai-rds-aurora/aurora-credentials",
        } if available else {},
    )


def _redshift_stack_info(available=True):
    """Return a valid Redshift StackInfo."""
    return StackInfo(
        stack_name="cgs-ai-redshift-serverless",
        stack_type="redshift",
        available=available,
        outputs={
            "RedshiftWorkgroupEndpoint": "cgs-ai-redshift-serverless-wg.xyz.eu-north-1.redshift-serverless.amazonaws.com",
            "RedshiftPort": "5439",
            "RedshiftDatabase": "analytics",
            "ConnectionConfig": '{"secret_name": "cgs-ai-redshift-serverless/redshift-credentials"}',
        } if available else {},
    )


class TestAutoPopulateOrchestratorShouldAutoRun(unittest.TestCase):
    """Tests for AutoPopulateOrchestrator.should_auto_run().

    Validates: Requirements 8.1, 8.2
    """

    def setUp(self):
        """Create a temporary config directory for each test."""
        self.test_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        """Remove the temporary config directory."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_should_auto_run_empty_directory(self):
        """Empty config directory -> should_auto_run returns True.

        Validates: Requirement 8.1
        """
        orchestrator = AutoPopulateOrchestrator(config_dir=self.test_dir)
        self.assertTrue(orchestrator.should_auto_run())

    def test_should_auto_run_nonexistent_directory(self):
        """Non-existent directory -> should_auto_run returns True.

        Validates: Requirement 8.1
        """
        nonexistent = self.test_dir / "does_not_exist"
        orchestrator = AutoPopulateOrchestrator(config_dir=nonexistent)
        self.assertTrue(orchestrator.should_auto_run())

    def test_should_auto_run_with_only_templates(self):
        """Only .yaml.template files in directory -> returns True.

        Validates: Requirement 8.1 (templates are excluded from check)
        """
        # Create a .yaml.template file (should be ignored)
        template_file = self.test_dir / "athena.yaml.template"
        template_file.write_text(
            "name: Athena Template\ntype: athena\nenabled: true\n",
            encoding="utf-8",
        )

        orchestrator = AutoPopulateOrchestrator(config_dir=self.test_dir)
        self.assertTrue(orchestrator.should_auto_run())

    def test_should_auto_run_with_enabled_config(self):
        """An enabled YAML config exists -> returns False.

        Validates: Requirement 8.2
        """
        config_file = self.test_dir / "athena.yaml"
        config_file.write_text(
            "name: Athena\ntype: athena\nenabled: true\nsettings:\n  region: eu-north-1\n",
            encoding="utf-8",
        )

        orchestrator = AutoPopulateOrchestrator(config_dir=self.test_dir)
        self.assertFalse(orchestrator.should_auto_run())

    def test_should_auto_run_with_disabled_config(self):
        """Only disabled YAML configs -> returns True.

        Validates: Requirement 8.1 (disabled configs do not count)
        """
        config_file = self.test_dir / "athena.yaml"
        config_file.write_text(
            "name: Athena\ntype: athena\nenabled: false\nsettings:\n  region: eu-north-1\n",
            encoding="utf-8",
        )

        orchestrator = AutoPopulateOrchestrator(config_dir=self.test_dir)
        self.assertTrue(orchestrator.should_auto_run())


class TestAutoPopulateOrchestratorRun(unittest.TestCase):
    """Tests for AutoPopulateOrchestrator.run().

    Validates: Requirements 7.2, 8.1
    """

    def setUp(self):
        """Create a temporary config directory for each test."""
        self.test_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        """Remove the temporary config directory."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    @patch("llm_sql.connectors.auto_populate.StackDiscoveryService")
    def test_run_success(self, mock_discovery_cls):
        """Mock StackDiscoveryService to return valid stacks, verify 'created' results.

        Validates: Requirement 7.2
        """
        # Set up mock discovery service
        mock_discovery = MagicMock()
        mock_discovery.region = "eu-north-1"
        mock_discovery.discover_all.return_value = [
            _main_stack_info(available=True),
            _rds_stack_info(available=True),
            _redshift_stack_info(available=True),
        ]
        mock_discovery_cls.return_value = mock_discovery

        orchestrator = AutoPopulateOrchestrator(config_dir=self.test_dir)
        results = orchestrator.run()

        # Should have results for each stack
        self.assertIsInstance(results, list)
        self.assertGreater(len(results), 0)

        # All results should be GenerationResult instances
        for result in results:
            self.assertIsInstance(result, GenerationResult)

        # Should have 'created' actions since no existing configs
        created_results = [r for r in results if r.action == "created"]
        self.assertGreater(len(created_results), 0)

        # Verify connector types were created
        created_types = {r.connector_type for r in created_results}
        self.assertIn("athena", created_types)
        self.assertIn("rds_mysql", created_types)
        self.assertIn("redshift", created_types)

    @patch("llm_sql.connectors.auto_populate.StackDiscoveryService")
    def test_run_with_unavailable_stacks(self, mock_discovery_cls):
        """Mock StackDiscoveryService returning unavailable stacks, verify 'unavailable' results.

        Validates: Requirement 7.2
        """
        mock_discovery = MagicMock()
        mock_discovery.region = "eu-north-1"
        mock_discovery.discover_all.return_value = [
            _main_stack_info(available=True),
            _rds_stack_info(available=False),
            _redshift_stack_info(available=False),
        ]
        mock_discovery_cls.return_value = mock_discovery

        orchestrator = AutoPopulateOrchestrator(config_dir=self.test_dir)
        results = orchestrator.run()

        self.assertIsInstance(results, list)
        self.assertGreater(len(results), 0)

        # Check that unavailable stacks produce 'unavailable' results
        unavailable_results = [r for r in results if r.action == "unavailable"]
        self.assertEqual(len(unavailable_results), 2)

        unavailable_types = {r.connector_type for r in unavailable_results}
        self.assertIn("rds_mysql", unavailable_types)
        self.assertIn("redshift", unavailable_types)

        # Main stack should still be created
        created_results = [r for r in results if r.action == "created"]
        self.assertEqual(len(created_results), 1)
        self.assertEqual(created_results[0].connector_type, "athena")

    @patch("llm_sql.connectors.auto_populate.StackDiscoveryService")
    def test_run_error_handling(self, mock_discovery_cls):
        """Mock StackDiscoveryService raising an exception, verify GenerationResult with action='error'.

        Validates: Requirement 7.2 (error handling - no exception propagates)
        """
        # Make StackDiscoveryService constructor raise an exception
        mock_discovery_cls.side_effect = RuntimeError("AWS credentials not configured")

        orchestrator = AutoPopulateOrchestrator(config_dir=self.test_dir)

        # Should NOT raise - errors are caught and returned as GenerationResult
        results = orchestrator.run()

        self.assertIsInstance(results, list)
        self.assertEqual(len(results), 1)

        error_result = results[0]
        self.assertIsInstance(error_result, GenerationResult)
        self.assertEqual(error_result.action, "error")
        self.assertEqual(error_result.connector_type, "unknown")
        self.assertIn("AWS credentials not configured", error_result.reason)


if __name__ == "__main__":
    unittest.main()
