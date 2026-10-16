"""Property-based tests for StackDiscoveryService.

Uses hypothesis to verify correctness properties from the design document.
Feature: auto-populate-connectors
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

from hypothesis import given, settings, assume
from hypothesis import strategies as st

# Add project root src to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(project_root, "src"))

from llm_sql.connectors.stack_discovery import StackDiscoveryService, STACK_OUTPUT_KEYS


# ─── Strategies ───────────────────────────────────────────────────────────────

# Valid stack types
stack_type_st = st.sampled_from(["main", "rds", "redshift"])

# Generate non-empty output values (simulating CloudFormation output values)
output_value_st = st.text(
    min_size=1,
    max_size=100,
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P"),
        blacklist_characters="\x00",
    ),
)

# Strategy for env-var-safe strings (no null bytes, no surrogates)
env_safe_text_st = st.text(
    min_size=1,
    alphabet=st.characters(
        blacklist_characters="\x00",
        blacklist_categories=("Cs",),  # Exclude surrogate category
    ),
)

# Generate extra output keys that are NOT in any required set
all_required_keys = set()
for keys in STACK_OUTPUT_KEYS.values():
    all_required_keys.update(keys)

extra_key_st = st.text(
    min_size=1,
    max_size=50,
    alphabet=st.characters(whitelist_categories=("L", "N")),
).filter(lambda k: k not in all_required_keys)


def build_outputs_list(output_dict: dict[str, str]) -> list[dict[str, str]]:
    """Convert a flat key->value dict into CloudFormation Outputs list format."""
    return [
        {"OutputKey": key, "OutputValue": value}
        for key, value in output_dict.items()
    ]


# ─── Property 1: Stack status classification ─────────────────────────────────


class TestProperty1StackStatusClassification(unittest.TestCase):
    """Property 1: Stack status classification

    For any CloudFormation stack status string, is_available_status SHALL return
    True if and only if the status is CREATE_COMPLETE or UPDATE_COMPLETE, and
    False for all other status values.

    Validates: Requirements 1.2, 1.3
    """

    @given(status=st.text())
    @settings(max_examples=100)
    def test_is_available_status_true_only_for_create_or_update_complete(self, status):
        """Feature: auto-populate-connectors, Property 1: Stack status classification

        For any arbitrary string, is_available_status returns True only when
        the status is exactly CREATE_COMPLETE or UPDATE_COMPLETE.

        **Validates: Requirements 1.2, 1.3**
        """
        result = StackDiscoveryService.is_available_status(status)

        if status in ("CREATE_COMPLETE", "UPDATE_COMPLETE"):
            self.assertTrue(
                result,
                f"Expected True for status '{status}', got False",
            )
        else:
            self.assertFalse(
                result,
                f"Expected False for status '{status}', got True",
            )


# ─── Property 2: Stack output extraction completeness ─────────────────────────


class TestProperty2StackOutputExtractionCompleteness(unittest.TestCase):
    """Feature: auto-populate-connectors, Property 2: Stack output extraction completeness"""

    @given(
        stack_type=stack_type_st,
        extra_outputs=st.dictionaries(
            keys=extra_key_st,
            values=output_value_st,
            min_size=0,
            max_size=5,
        ),
        output_values=st.lists(output_value_st, min_size=4, max_size=4),
    )
    @settings(max_examples=100)
    def test_all_required_keys_present_returns_complete_dict(
        self, stack_type, extra_outputs, output_values
    ):
        """Feature: auto-populate-connectors, Property 2: Stack output extraction completeness

        When all required output keys for a stack type are present in the
        CloudFormation stack outputs, _extract_outputs SHALL return a dict
        containing exactly all required keys with their corresponding values.

        **Validates: Requirements 2.1, 2.2, 2.3, 2.4**
        """
        required_keys = STACK_OUTPUT_KEYS[stack_type]

        # Build output dict with all required keys present
        output_dict = {}
        for i, key in enumerate(required_keys):
            output_dict[key] = output_values[i]

        # Add extra non-required outputs (should not affect result)
        output_dict.update(extra_outputs)

        # Build CloudFormation-style stack dict
        stack = {
            "StackName": "test-stack",
            "Outputs": build_outputs_list(output_dict),
        }

        # Create service instance (client not needed for _extract_outputs)
        service = StackDiscoveryService.__new__(StackDiscoveryService)

        result = service._extract_outputs(stack, stack_type)

        # Should return a dict (not None)
        self.assertIsNotNone(
            result,
            f"Expected dict for stack_type={stack_type} with all keys present, got None",
        )

        # Should contain exactly all required keys
        self.assertEqual(
            set(result.keys()),
            set(required_keys),
            f"Result keys {set(result.keys())} != required keys {set(required_keys)}",
        )

        # Each key should map to the correct value
        for i, key in enumerate(required_keys):
            self.assertEqual(
                result[key],
                output_values[i],
                f"Value mismatch for key '{key}': {result[key]} != {output_values[i]}",
            )

    @given(
        stack_type=stack_type_st,
        output_values=st.lists(output_value_st, min_size=4, max_size=4),
        keys_to_remove=st.integers(min_value=1, max_value=4),
    )
    @settings(max_examples=100)
    def test_missing_required_key_returns_none(
        self, stack_type, output_values, keys_to_remove
    ):
        """Feature: auto-populate-connectors, Property 2: Stack output extraction completeness

        When at least one required output key for a stack type is MISSING from
        the CloudFormation stack outputs, _extract_outputs SHALL return None.

        **Validates: Requirements 2.1, 2.2, 2.3, 2.4**
        """
        required_keys = STACK_OUTPUT_KEYS[stack_type]

        # Cap keys_to_remove to not exceed available keys
        keys_to_remove = min(keys_to_remove, len(required_keys))

        # Build output dict with some required keys removed
        output_dict = {}
        for i, key in enumerate(required_keys):
            output_dict[key] = output_values[i]

        # Remove some required keys (at least one)
        keys_removed = required_keys[:keys_to_remove]
        for key in keys_removed:
            del output_dict[key]

        # Build CloudFormation-style stack dict
        stack = {
            "StackName": "test-stack",
            "Outputs": build_outputs_list(output_dict),
        }

        # Create service instance (client not needed for _extract_outputs)
        service = StackDiscoveryService.__new__(StackDiscoveryService)

        result = service._extract_outputs(stack, stack_type)

        # Should return None when any required key is missing
        self.assertIsNone(
            result,
            f"Expected None for stack_type={stack_type} with missing keys "
            f"{keys_removed}, got {result}",
        )

    @given(
        stack_type=stack_type_st,
        extra_outputs=st.dictionaries(
            keys=extra_key_st,
            values=output_value_st,
            min_size=0,
            max_size=10,
        ),
    )
    @settings(max_examples=100)
    def test_no_required_keys_present_returns_none(
        self, stack_type, extra_outputs
    ):
        """Feature: auto-populate-connectors, Property 2: Stack output extraction completeness

        When NO required output keys are present (only unrelated keys),
        _extract_outputs SHALL return None.

        **Validates: Requirements 2.1, 2.2, 2.3, 2.4**
        """
        # Build stack dict with ONLY non-required keys
        stack = {
            "StackName": "test-stack",
            "Outputs": build_outputs_list(extra_outputs),
        }

        # Create service instance
        service = StackDiscoveryService.__new__(StackDiscoveryService)

        result = service._extract_outputs(stack, stack_type)

        # Should return None since no required keys are present
        self.assertIsNone(
            result,
            f"Expected None for stack_type={stack_type} with no required keys, "
            f"got {result}",
        )

    @given(
        stack_type=stack_type_st,
        output_values=st.lists(output_value_st, min_size=4, max_size=4),
    )
    @settings(max_examples=100)
    def test_empty_outputs_list_returns_none(self, stack_type, output_values):
        """Feature: auto-populate-connectors, Property 2: Stack output extraction completeness

        When the Outputs list is empty, _extract_outputs SHALL return None.

        **Validates: Requirements 2.1, 2.2, 2.3, 2.4**
        """
        # Build stack with empty Outputs
        stack = {
            "StackName": "test-stack",
            "Outputs": [],
        }

        # Create service instance
        service = StackDiscoveryService.__new__(StackDiscoveryService)

        result = service._extract_outputs(stack, stack_type)

        # Should return None since no outputs exist
        self.assertIsNone(
            result,
            f"Expected None for stack_type={stack_type} with empty Outputs, got {result}",
        )


# ─── Property 8: Configurable stack names with defaults ──────────────────────


class TestProperty8ConfigurableStackNamesWithDefaults(unittest.TestCase):
    """Property 8: Configurable stack names with defaults

    For any string value set as MAIN_STACK_NAME, RDS_STACK_NAME, or
    REDSHIFT_STACK_NAME environment variable, the Stack_Discovery_Service SHALL
    use that value as the stack name to query. When the environment variable is
    unset, it SHALL use the documented default value.

    Validates: Requirements 10.1, 10.2, 10.3
    """

    @given(
        main_name=env_safe_text_st,
        rds_name=env_safe_text_st,
        redshift_name=env_safe_text_st,
    )
    @settings(max_examples=100)
    def test_env_vars_override_defaults(self, main_name, rds_name, redshift_name):
        """Feature: auto-populate-connectors, Property 8: Configurable stack names with defaults

        When MAIN_STACK_NAME, RDS_STACK_NAME, REDSHIFT_STACK_NAME env vars are
        set, StackDiscoveryService uses those values as stack names.

        **Validates: Requirements 10.1, 10.2, 10.3**
        """
        env_overrides = {
            "MAIN_STACK_NAME": main_name,
            "RDS_STACK_NAME": rds_name,
            "REDSHIFT_STACK_NAME": redshift_name,
        }
        with patch.dict(os.environ, env_overrides, clear=False):
            with patch("boto3.client") as mock_client:
                mock_client.return_value = MagicMock()
                service = StackDiscoveryService()

        self.assertEqual(
            service.main_stack_name,
            main_name,
            f"Expected main_stack_name='{main_name}', got '{service.main_stack_name}'",
        )
        self.assertEqual(
            service.rds_stack_name,
            rds_name,
            f"Expected rds_stack_name='{rds_name}', got '{service.rds_stack_name}'",
        )
        self.assertEqual(
            service.redshift_stack_name,
            redshift_name,
            f"Expected redshift_stack_name='{redshift_name}', got '{service.redshift_stack_name}'",
        )

    @given(st.just(None))
    @settings(max_examples=1)
    def test_defaults_when_env_vars_unset(self, _):
        """Feature: auto-populate-connectors, Property 8: Configurable stack names with defaults

        When MAIN_STACK_NAME, RDS_STACK_NAME, REDSHIFT_STACK_NAME env vars are
        NOT set, StackDiscoveryService falls back to documented default values.

        **Validates: Requirements 10.1, 10.2, 10.3**
        """
        # Build env without the stack name vars
        env_without_stack_names = {
            k: v
            for k, v in os.environ.items()
            if k not in ("MAIN_STACK_NAME", "RDS_STACK_NAME", "REDSHIFT_STACK_NAME")
        }
        with patch.dict(os.environ, env_without_stack_names, clear=True):
            with patch("boto3.client") as mock_client:
                mock_client.return_value = MagicMock()
                service = StackDiscoveryService()

        self.assertEqual(
            service.main_stack_name,
            "cgs-ai-analyst-agent-project",
            f"Expected default main stack name, got '{service.main_stack_name}'",
        )
        self.assertEqual(
            service.rds_stack_name,
            "cgs-ai-rds-aurora",
            f"Expected default RDS stack name, got '{service.rds_stack_name}'",
        )
        self.assertEqual(
            service.redshift_stack_name,
            "cgs-ai-redshift-serverless",
            f"Expected default Redshift stack name, got '{service.redshift_stack_name}'",
        )

    @given(
        env_main=env_safe_text_st,
        env_rds=env_safe_text_st,
        env_redshift=env_safe_text_st,
        param_main=env_safe_text_st,
        param_rds=env_safe_text_st,
        param_redshift=env_safe_text_st,
    )
    @settings(max_examples=100)
    def test_constructor_params_override_env_vars(
        self, env_main, env_rds, env_redshift, param_main, param_rds, param_redshift
    ):
        """Feature: auto-populate-connectors, Property 8: Configurable stack names with defaults

        Constructor parameters override environment variables when both are set.

        **Validates: Requirements 10.1, 10.2, 10.3**
        """
        env_overrides = {
            "MAIN_STACK_NAME": env_main,
            "RDS_STACK_NAME": env_rds,
            "REDSHIFT_STACK_NAME": env_redshift,
        }
        with patch.dict(os.environ, env_overrides, clear=False):
            with patch("boto3.client") as mock_client:
                mock_client.return_value = MagicMock()
                service = StackDiscoveryService(
                    main_stack_name=param_main,
                    rds_stack_name=param_rds,
                    redshift_stack_name=param_redshift,
                )

        self.assertEqual(
            service.main_stack_name,
            param_main,
            f"Constructor param should override env var for main_stack_name",
        )
        self.assertEqual(
            service.rds_stack_name,
            param_rds,
            f"Constructor param should override env var for rds_stack_name",
        )
        self.assertEqual(
            service.redshift_stack_name,
            param_redshift,
            f"Constructor param should override env var for redshift_stack_name",
        )


if __name__ == "__main__":
    unittest.main()
