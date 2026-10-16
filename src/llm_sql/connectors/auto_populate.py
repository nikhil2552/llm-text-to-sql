"""Auto-Populate Orchestrator - coordinates stack discovery and config generation."""

import logging
from pathlib import Path

import yaml

from llm_sql.connectors.config_generator import ConfigGenerator, GenerationResult
from llm_sql.connectors.stack_discovery import StackDiscoveryService

logger = logging.getLogger(__name__)


class AutoPopulateOrchestrator:
    """Coordinates discovery and generation. Used by Streamlit UI."""

    def __init__(self, config_dir: Path | None = None):
        """Initialize orchestrator.

        Args:
            config_dir: Path to the directory where YAML configs are stored.
                        Defaults to config/connections/.
        """
        self.config_dir = config_dir or Path("config/connections/")

    def should_auto_run(self) -> bool:
        """Return True if no enabled YAML configs exist (startup trigger).

        Scans config_dir for *.yaml files (NOT .yaml.template).
        For each YAML file, checks if enabled: true.
        Returns True if NO files have enabled: true.
        Returns False if at least one file has enabled: true.
        If directory doesn't exist, returns True.
        """
        if not self.config_dir.exists():
            return True

        for yaml_file in self.config_dir.glob("*.yaml"):
            # Skip template files (e.g. athena.yaml.template won't match *.yaml,
            # but guard against files like something.yaml.template being caught)
            if yaml_file.name.endswith(".yaml.template"):
                continue

            try:
                content = yaml_file.read_text(encoding="utf-8")
                data = yaml.safe_load(content)
                if isinstance(data, dict) and data.get("enabled") is True:
                    return False
            except (yaml.YAMLError, OSError) as e:
                logger.warning(
                    "Could not parse %s when checking auto-run: %s",
                    yaml_file,
                    e,
                )
                # Malformed YAML - don't count it as enabled, continue checking

        return True

    def run(self) -> list[GenerationResult]:
        """Run full auto-populate: discover stacks, generate configs.

        1. Creates StackDiscoveryService (uses env vars/defaults)
        2. Calls discover_all() to get list of StackInfo
        3. Creates ConfigGenerator with same config_dir
        4. Calls generate_all(stacks, region)
        5. Returns list of GenerationResult

        Errors never propagate - always returns a list of GenerationResult,
        with action='error' on failure.
        """
        try:
            discovery = StackDiscoveryService()
            stacks = discovery.discover_all()

            generator = ConfigGenerator(config_dir=self.config_dir)
            results = generator.generate_all(stacks, region=discovery.region)

            return results
        except Exception as e:
            logger.error("Auto-populate failed: %s", e)
            return [
                GenerationResult(
                    connector_type="unknown",
                    action="error",
                    reason=str(e),
                )
            ]
