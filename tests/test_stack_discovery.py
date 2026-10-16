"""Unit tests for StackDiscoveryService.

Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.2, 2.3, 2.4
"""

import os
import unittest
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError

from llm_sql.connectors.stack_discovery import (
    STACK_OUTPUT_KEYS,
    StackDiscoveryService,
    StackInfo,
)


def _build_stack_response(stack_name, status, outputs_dict):
    """Build a mock describe_stacks response with given outputs.

    Args:
        stack_name: Name of the stack.
        status: CloudFormation stack status string.
        outputs_dict: Dict of output keys to values.
    """
    outputs_list = [
        {"OutputKey": k, "OutputValue": v} for k, v in outputs_dict.items()
    ]
    return {
        "Stacks": [
            {
                "StackName": stack_name,
                "StackStatus": status,
                "Outputs": outputs_list,
            }
        ]
    }


def _main_stack_outputs():
    """Return valid main stack outputs."""
    return {
        "ProjectfilesBucketName": "langchain-123456789012-eu-north-1",
        "AthenaWorkgroupName": "project-text-to-sql",
        "LibraryDatabaseName": "project_library_db",
        "CarsDatabaseName": "project_cars_db",
    }


def _rds_stack_outputs():
    """Return valid RDS stack outputs."""
    return {
        "ClusterEndpoint": "cgs-ai-rds-aurora-cluster.cluster-abc.eu-north-1.rds.amazonaws.com",
        "ClusterPort": "3306",
        "DatabaseName": "analyst_db",
        "SecretName": "cgs-ai-rds-aurora/aurora-credentials",
    }


def _redshift_stack_outputs():
    """Return valid Redshift stack outputs."""
    return {
        "RedshiftWorkgroupEndpoint": "cgs-ai-redshift-serverless-wg.xyz.eu-north-1.redshift-serverless.amazonaws.com",
        "RedshiftPort": "5439",
        "RedshiftDatabase": "analytics",
        "ConnectionConfig": '{"secret_name": "cgs-ai-redshift-serverless/redshift-credentials"}',
    }


def _client_error(code, message):
    """Build a ClientError with the given code and message."""
    return ClientError(
        {"Error": {"Code": code, "Message": message}},
        "DescribeStacks",
    )


class TestStackDiscoveryService(unittest.TestCase):
    """Tests for StackDiscoveryService."""

    @patch("llm_sql.connectors.stack_discovery.boto3.client")
    def test_discover_all_success(self, mock_boto_client):
        """Test successful discovery of all 3 stacks with valid outputs.

        Validates: Requirements 1.1, 1.2, 2.1, 2.2, 2.3
        """
        mock_cf = MagicMock()
        mock_boto_client.return_value = mock_cf

        # Side effects for the three describe_stacks calls
        mock_cf.describe_stacks.side_effect = [
            _build_stack_response(
                "cgs-ai-analyst-agent-project",
                "CREATE_COMPLETE",
                _main_stack_outputs(),
            ),
            _build_stack_response(
                "cgs-ai-rds-aurora",
                "UPDATE_COMPLETE",
                _rds_stack_outputs(),
            ),
            _build_stack_response(
                "cgs-ai-redshift-serverless",
                "CREATE_COMPLETE",
                _redshift_stack_outputs(),
            ),
        ]

        service = StackDiscoveryService(region="eu-north-1")
        results = service.discover_all()

        self.assertEqual(len(results), 3)
        for stack_info in results:
            self.assertIsInstance(stack_info, StackInfo)
            self.assertTrue(stack_info.available)
            self.assertGreater(len(stack_info.outputs), 0)

        # Verify main stack outputs
        main = results[0]
        self.assertEqual(main.stack_type, "main")
        self.assertEqual(main.outputs["ProjectfilesBucketName"], "langchain-123456789012-eu-north-1")
        self.assertEqual(main.outputs["AthenaWorkgroupName"], "project-text-to-sql")

        # Verify RDS stack outputs
        rds = results[1]
        self.assertEqual(rds.stack_type, "rds")
        self.assertEqual(rds.outputs["ClusterEndpoint"], "cgs-ai-rds-aurora-cluster.cluster-abc.eu-north-1.rds.amazonaws.com")

        # Verify Redshift stack outputs
        redshift = results[2]
        self.assertEqual(redshift.stack_type, "redshift")
        self.assertEqual(redshift.outputs["RedshiftDatabase"], "analytics")

    @patch("llm_sql.connectors.stack_discovery.boto3.client")
    def test_discover_non_existent_stack(self, mock_boto_client):
        """Test handling of a stack that does not exist.

        Validates: Requirement 1.3
        """
        mock_cf = MagicMock()
        mock_boto_client.return_value = mock_cf

        mock_cf.describe_stacks.side_effect = _client_error(
            "ValidationError",
            "Stack with id cgs-ai-analyst-agent-project does not exist",
        )

        service = StackDiscoveryService(region="eu-north-1")
        # Call the internal method directly for a single stack
        result = service._describe_stack("cgs-ai-analyst-agent-project", "main")

        self.assertIsInstance(result, StackInfo)
        self.assertFalse(result.available)
        self.assertEqual(result.outputs, {})

    @patch("llm_sql.connectors.stack_discovery.boto3.client")
    def test_discover_failed_status_stack(self, mock_boto_client):
        """Test that a stack with ROLLBACK_COMPLETE status is marked unavailable.

        Validates: Requirement 1.3
        """
        mock_cf = MagicMock()
        mock_boto_client.return_value = mock_cf

        mock_cf.describe_stacks.return_value = _build_stack_response(
            "cgs-ai-rds-aurora",
            "ROLLBACK_COMPLETE",
            _rds_stack_outputs(),
        )

        service = StackDiscoveryService(region="eu-north-1")
        result = service._describe_stack("cgs-ai-rds-aurora", "rds")

        self.assertIsInstance(result, StackInfo)
        self.assertFalse(result.available)

    @patch("llm_sql.connectors.stack_discovery.boto3.client")
    def test_discover_missing_output_keys(self, mock_boto_client):
        """Test that a stack missing required output keys is marked unavailable.

        Validates: Requirement 2.4
        """
        mock_cf = MagicMock()
        mock_boto_client.return_value = mock_cf

        # Missing AthenaWorkgroupName key
        incomplete_outputs = {
            "ProjectfilesBucketName": "langchain-123456789012-eu-north-1",
            "LibraryDatabaseName": "project_library_db",
            "CarsDatabaseName": "project_cars_db",
            # "AthenaWorkgroupName" is missing
        }
        mock_cf.describe_stacks.return_value = _build_stack_response(
            "cgs-ai-analyst-agent-project",
            "CREATE_COMPLETE",
            incomplete_outputs,
        )

        service = StackDiscoveryService(region="eu-north-1")
        result = service._describe_stack("cgs-ai-analyst-agent-project", "main")

        self.assertIsInstance(result, StackInfo)
        self.assertFalse(result.available)
        self.assertEqual(result.outputs, {})

    @patch("llm_sql.connectors.stack_discovery.boto3.client")
    def test_discover_permission_denied(self, mock_boto_client):
        """Test handling of AccessDenied error from CloudFormation API.

        Validates: Requirement 1.5
        """
        mock_cf = MagicMock()
        mock_boto_client.return_value = mock_cf

        mock_cf.describe_stacks.side_effect = _client_error(
            "AccessDenied",
            "User is not authorized to perform: cloudformation:DescribeStacks",
        )

        service = StackDiscoveryService(region="eu-north-1")
        result = service._describe_stack("cgs-ai-redshift-serverless", "redshift")

        self.assertIsInstance(result, StackInfo)
        self.assertFalse(result.available)
        self.assertEqual(result.outputs, {})

    def test_is_available_status(self):
        """Test static method is_available_status for all status categories.

        Validates: Requirements 1.2, 1.3
        """
        # Should return True
        self.assertTrue(StackDiscoveryService.is_available_status("CREATE_COMPLETE"))
        self.assertTrue(StackDiscoveryService.is_available_status("UPDATE_COMPLETE"))

        # Should return False for all other statuses
        false_statuses = [
            "ROLLBACK_COMPLETE",
            "DELETE_COMPLETE",
            "CREATE_FAILED",
            "UPDATE_ROLLBACK_COMPLETE",
            "DELETE_IN_PROGRESS",
            "CREATE_IN_PROGRESS",
            "UPDATE_IN_PROGRESS",
            "ROLLBACK_IN_PROGRESS",
            "UPDATE_ROLLBACK_IN_PROGRESS",
            "REVIEW_IN_PROGRESS",
            "",
        ]
        for status in false_statuses:
            self.assertFalse(
                StackDiscoveryService.is_available_status(status),
                f"Expected False for status '{status}'",
            )

    @patch("llm_sql.connectors.stack_discovery.boto3.client")
    @patch.dict(os.environ, {"AWS_REGION": "us-west-2"}, clear=False)
    def test_region_from_env_var(self, mock_boto_client):
        """Test that the service uses the AWS_REGION environment variable.

        Validates: Requirement 1.4
        """
        mock_boto_client.return_value = MagicMock()

        service = StackDiscoveryService()

        self.assertEqual(service.region, "us-west-2")
        mock_boto_client.assert_called_with("cloudformation", region_name="us-west-2")

    @patch("llm_sql.connectors.stack_discovery.boto3.client")
    @patch.dict(
        os.environ,
        {
            "MAIN_STACK_NAME": "custom-main-stack",
            "RDS_STACK_NAME": "custom-rds-stack",
            "REDSHIFT_STACK_NAME": "custom-redshift-stack",
        },
        clear=False,
    )
    def test_stack_names_from_env_vars(self, mock_boto_client):
        """Test that the service uses stack name environment variables.

        Validates: Requirements 10.1, 10.2, 10.3
        """
        mock_boto_client.return_value = MagicMock()

        service = StackDiscoveryService()

        self.assertEqual(service.main_stack_name, "custom-main-stack")
        self.assertEqual(service.rds_stack_name, "custom-rds-stack")
        self.assertEqual(service.redshift_stack_name, "custom-redshift-stack")

    @patch("llm_sql.connectors.stack_discovery.boto3.client")
    def test_extract_outputs_all_present(self, mock_boto_client):
        """Test _extract_outputs returns all keys when all are present.

        Validates: Requirements 2.1, 2.2, 2.3
        """
        mock_boto_client.return_value = MagicMock()
        service = StackDiscoveryService(region="eu-north-1")

        stack_dict = {
            "StackName": "cgs-ai-rds-aurora",
            "Outputs": [
                {"OutputKey": "ClusterEndpoint", "OutputValue": "my-cluster.abc.rds.amazonaws.com"},
                {"OutputKey": "ClusterPort", "OutputValue": "3306"},
                {"OutputKey": "DatabaseName", "OutputValue": "analyst_db"},
                {"OutputKey": "SecretName", "OutputValue": "cgs-ai-rds-aurora/aurora-credentials"},
            ],
        }

        result = service._extract_outputs(stack_dict, "rds")

        self.assertIsNotNone(result)
        self.assertEqual(len(result), 4)
        self.assertEqual(result["ClusterEndpoint"], "my-cluster.abc.rds.amazonaws.com")
        self.assertEqual(result["ClusterPort"], "3306")
        self.assertEqual(result["DatabaseName"], "analyst_db")
        self.assertEqual(result["SecretName"], "cgs-ai-rds-aurora/aurora-credentials")

    @patch("llm_sql.connectors.stack_discovery.boto3.client")
    def test_extract_outputs_missing_key(self, mock_boto_client):
        """Test _extract_outputs returns None when a required key is missing.

        Validates: Requirement 2.4
        """
        mock_boto_client.return_value = MagicMock()
        service = StackDiscoveryService(region="eu-north-1")

        # Missing ClusterPort
        stack_dict = {
            "StackName": "cgs-ai-rds-aurora",
            "Outputs": [
                {"OutputKey": "ClusterEndpoint", "OutputValue": "my-cluster.abc.rds.amazonaws.com"},
                {"OutputKey": "DatabaseName", "OutputValue": "analyst_db"},
                {"OutputKey": "SecretName", "OutputValue": "cgs-ai-rds-aurora/aurora-credentials"},
            ],
        }

        result = service._extract_outputs(stack_dict, "rds")

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
