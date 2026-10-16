"""Stack Discovery Service - queries CloudFormation for deployed database stacks."""

import logging
import os
from dataclasses import dataclass, field

import boto3
from botocore.exceptions import ClientError, BotoCoreError

logger = logging.getLogger(__name__)

# Output keys required per stack type
STACK_OUTPUT_KEYS: dict[str, list[str]] = {
    "main": [
        "ProjectfilesBucketName",
        "AthenaWorkgroupName",
        "LibraryDatabaseName",
        "CarsDatabaseName",
    ],
    "rds": [
        "ClusterEndpoint",
        "ClusterPort",
        "DatabaseName",
        "SecretName",
    ],
    "redshift": [
        "RedshiftWorkgroupEndpoint",
        "RedshiftPort",
        "RedshiftDatabase",
        "ConnectionConfig",
    ],
}


@dataclass
class StackInfo:
    """Represents a discovered CloudFormation stack and its extracted outputs."""

    stack_name: str
    stack_type: str  # 'main', 'rds', 'redshift'
    available: bool
    outputs: dict[str, str] = field(default_factory=dict)


class StackDiscoveryService:
    """Queries CloudFormation for known database stacks and extracts outputs."""

    # Default stack names (used when env vars are not set)
    DEFAULT_MAIN_STACK = "cgs-ai-analyst-agent-project"
    DEFAULT_RDS_STACK = "cgs-ai-rds-aurora"
    DEFAULT_REDSHIFT_STACK = "cgs-ai-redshift-serverless"

    def __init__(
        self,
        region: str | None = None,
        main_stack_name: str | None = None,
        rds_stack_name: str | None = None,
        redshift_stack_name: str | None = None,
    ):
        """Initialize with optional overrides; defaults from env vars.

        Args:
            region: AWS region override. Defaults to AWS_REGION env var or 'eu-north-1'.
            main_stack_name: Override for main stack name. Defaults to MAIN_STACK_NAME env var.
            rds_stack_name: Override for RDS stack name. Defaults to RDS_STACK_NAME env var.
            redshift_stack_name: Override for Redshift stack name. Defaults to REDSHIFT_STACK_NAME env var.
        """
        self.region = region or os.environ.get("AWS_REGION", "eu-north-1")
        self.main_stack_name = main_stack_name or os.environ.get(
            "MAIN_STACK_NAME", self.DEFAULT_MAIN_STACK
        )
        self.rds_stack_name = rds_stack_name or os.environ.get(
            "RDS_STACK_NAME", self.DEFAULT_RDS_STACK
        )
        self.redshift_stack_name = redshift_stack_name or os.environ.get(
            "REDSHIFT_STACK_NAME", self.DEFAULT_REDSHIFT_STACK
        )

        try:
            self._client = boto3.client(
                "cloudformation", region_name=self.region
            )
        except (BotoCoreError, Exception) as e:
            logger.error("Failed to create CloudFormation client: %s", e)
            self._client = None

    def discover_all(self) -> list[StackInfo]:
        """Discover all known stacks and return their info.

        Returns:
            List of StackInfo objects for each known stack. Stacks that
            cannot be reached are marked as unavailable.
        """
        if self._client is None:
            logger.error(
                "boto3 CloudFormation client not available. Returning empty result set."
            )
            return []

        stacks_to_check = [
            (self.main_stack_name, "main"),
            (self.rds_stack_name, "rds"),
            (self.redshift_stack_name, "redshift"),
        ]

        results: list[StackInfo] = []
        for stack_name, stack_type in stacks_to_check:
            stack_info = self._describe_stack(stack_name, stack_type)
            if stack_info is not None:
                results.append(stack_info)
            else:
                # API failure - mark as unavailable
                results.append(
                    StackInfo(
                        stack_name=stack_name,
                        stack_type=stack_type,
                        available=False,
                        outputs={},
                    )
                )

        return results

    def _describe_stack(self, stack_name: str, stack_type: str) -> StackInfo | None:
        """Query a single stack. Returns None on API failure.

        Args:
            stack_name: CloudFormation stack name to describe.
            stack_type: Type identifier ('main', 'rds', 'redshift').

        Returns:
            StackInfo if stack was successfully queried, None on API failure.
        """
        try:
            response = self._client.describe_stacks(StackName=stack_name)
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            if "does not exist" in str(e) or error_code == "ValidationError":
                logger.info("Stack '%s' does not exist.", stack_name)
            elif error_code == "AccessDenied" or "AccessDenied" in error_code:
                logger.warning(
                    "Access denied when describing stack '%s': %s",
                    stack_name,
                    e,
                )
            else:
                logger.warning(
                    "ClientError describing stack '%s': %s", stack_name, e
                )
            return StackInfo(
                stack_name=stack_name,
                stack_type=stack_type,
                available=False,
                outputs={},
            )
        except (BotoCoreError, Exception) as e:
            logger.error(
                "Error describing stack '%s': %s", stack_name, e
            )
            return None

        stacks = response.get("Stacks", [])
        if not stacks:
            return StackInfo(
                stack_name=stack_name,
                stack_type=stack_type,
                available=False,
                outputs={},
            )

        stack = stacks[0]
        status = stack.get("StackStatus", "")
        available = self.is_available_status(status)

        if not available:
            return StackInfo(
                stack_name=stack_name,
                stack_type=stack_type,
                available=False,
                outputs={},
            )

        outputs = self._extract_outputs(stack, stack_type)
        if outputs is None:
            # Required outputs missing - stack is not usable
            return StackInfo(
                stack_name=stack_name,
                stack_type=stack_type,
                available=False,
                outputs={},
            )

        return StackInfo(
            stack_name=stack_name,
            stack_type=stack_type,
            available=True,
            outputs=outputs,
        )

    def _extract_outputs(self, stack: dict, stack_type: str) -> dict[str, str] | None:
        """Extract relevant output keys for the given stack type.

        Args:
            stack: CloudFormation stack description dict (from describe_stacks).
            stack_type: Type identifier to determine which keys to extract.

        Returns:
            Dict mapping output keys to values, or None if any required key is missing.
        """
        required_keys = STACK_OUTPUT_KEYS.get(stack_type, [])
        if not required_keys:
            return None

        # Build lookup from stack outputs
        raw_outputs = stack.get("Outputs", [])
        output_map = {
            item["OutputKey"]: item.get("OutputValue", "")
            for item in raw_outputs
            if "OutputKey" in item
        }

        # Extract required keys
        extracted: dict[str, str] = {}
        for key in required_keys:
            if key not in output_map:
                logger.warning(
                    "Stack '%s' (type=%s) is missing required output key '%s'. Skipping.",
                    stack.get("StackName", "unknown"),
                    stack_type,
                    key,
                )
                return None
            extracted[key] = output_map[key]

        return extracted

    @staticmethod
    def is_available_status(status: str) -> bool:
        """Return True if the stack status indicates availability.

        Only CREATE_COMPLETE and UPDATE_COMPLETE are considered available.
        All other statuses (failed, deleted, in-progress, rollback) return False.
        """
        return status in ("CREATE_COMPLETE", "UPDATE_COMPLETE")
