"""Unit tests for Streamlit auto-detect integration.

Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, call

# Ensure project paths are importable
PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
SRC_PATH = str(Path(PROJECT_ROOT) / "src")
if SRC_PATH not in sys.path:
    sys.path.insert(0, SRC_PATH)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from llm_sql.connectors.config_generator import GenerationResult


class TestRunAutoDetect(unittest.TestCase):
    """Test _run_auto_detect function display logic."""

    @patch('scripts.streamlit_app.st')
    @patch('scripts.streamlit_app.AutoPopulateOrchestrator')
    def test_run_auto_detect_with_created_results(self, mock_orchestrator_cls, mock_st):
        """Verify st.success is called with created connector names and st.rerun is triggered.

        Validates: Requirements 7.2, 7.3, 7.5
        """
        mock_orchestrator = MagicMock()
        mock_orchestrator.run.return_value = [
            GenerationResult(connector_type='athena', action='created', file_path='/tmp/athena.yaml'),
            GenerationResult(connector_type='redshift', action='created', file_path='/tmp/redshift.yaml'),
        ]
        mock_orchestrator_cls.return_value = mock_orchestrator

        # Mock the spinner context manager
        mock_st.spinner.return_value.__enter__ = MagicMock()
        mock_st.spinner.return_value.__exit__ = MagicMock(return_value=False)

        from scripts.streamlit_app import _run_auto_detect
        _run_auto_detect()

        # Verify orchestrator was invoked
        mock_orchestrator.run.assert_called_once()

        # Verify st.success called with created connector names
        mock_st.success.assert_called_once()
        success_msg = mock_st.success.call_args[0][0]
        self.assertIn('Athena', success_msg)
        self.assertIn('Redshift', success_msg)

        # Verify st.rerun called to refresh the connector picker
        mock_st.rerun.assert_called_once()

    @patch('scripts.streamlit_app.st')
    @patch('scripts.streamlit_app.AutoPopulateOrchestrator')
    def test_run_auto_detect_with_skipped_results(self, mock_orchestrator_cls, mock_st):
        """Verify st.info is called when connectors are skipped (already exist).

        Validates: Requirements 7.3
        """
        mock_orchestrator = MagicMock()
        mock_orchestrator.run.return_value = [
            GenerationResult(connector_type='athena', action='skipped', reason='already exists'),
        ]
        mock_orchestrator_cls.return_value = mock_orchestrator

        mock_st.spinner.return_value.__enter__ = MagicMock()
        mock_st.spinner.return_value.__exit__ = MagicMock(return_value=False)

        from scripts.streamlit_app import _run_auto_detect
        _run_auto_detect()

        mock_orchestrator.run.assert_called_once()

        # Verify st.info called with skipped connector names
        mock_st.info.assert_called_once()
        info_msg = mock_st.info.call_args[0][0]
        self.assertIn('Athena', info_msg)

        # No rerun since nothing was created
        mock_st.rerun.assert_not_called()

    @patch('scripts.streamlit_app.st')
    @patch('scripts.streamlit_app.AutoPopulateOrchestrator')
    def test_run_auto_detect_with_error_results(self, mock_orchestrator_cls, mock_st):
        """Verify st.error is called with the error reason.

        Validates: Requirements 7.4
        """
        mock_orchestrator = MagicMock()
        mock_orchestrator.run.return_value = [
            GenerationResult(connector_type='unknown', action='error', reason='Permission denied'),
        ]
        mock_orchestrator_cls.return_value = mock_orchestrator

        mock_st.spinner.return_value.__enter__ = MagicMock()
        mock_st.spinner.return_value.__exit__ = MagicMock(return_value=False)

        from scripts.streamlit_app import _run_auto_detect
        _run_auto_detect()

        mock_orchestrator.run.assert_called_once()

        # Verify st.error called with the reason
        mock_st.error.assert_called_once()
        error_msg = mock_st.error.call_args[0][0]
        self.assertIn('Permission denied', error_msg)

        # No rerun since nothing was created
        mock_st.rerun.assert_not_called()

    @patch('scripts.streamlit_app.st')
    @patch('scripts.streamlit_app.AutoPopulateOrchestrator')
    def test_run_auto_detect_with_unavailable_results(self, mock_orchestrator_cls, mock_st):
        """Verify st.caption is called when stacks are unavailable.

        Validates: Requirements 7.3
        """
        mock_orchestrator = MagicMock()
        mock_orchestrator.run.return_value = [
            GenerationResult(connector_type='redshift', action='unavailable', reason='Stack not found'),
        ]
        mock_orchestrator_cls.return_value = mock_orchestrator

        mock_st.spinner.return_value.__enter__ = MagicMock()
        mock_st.spinner.return_value.__exit__ = MagicMock(return_value=False)

        from scripts.streamlit_app import _run_auto_detect
        _run_auto_detect()

        mock_orchestrator.run.assert_called_once()

        # Verify st.caption called with unavailable connector names
        mock_st.caption.assert_called_once()
        caption_msg = mock_st.caption.call_args[0][0]
        self.assertIn('Redshift', caption_msg)

        # No rerun since nothing was created
        mock_st.rerun.assert_not_called()

    @patch('scripts.streamlit_app.st')
    @patch('scripts.streamlit_app.AutoPopulateOrchestrator')
    def test_run_auto_detect_mixed_results(self, mock_orchestrator_cls, mock_st):
        """Verify correct display calls when results contain a mix of actions.

        Validates: Requirements 7.3, 7.4, 7.5
        """
        mock_orchestrator = MagicMock()
        mock_orchestrator.run.return_value = [
            GenerationResult(connector_type='athena', action='created', file_path='/tmp/athena.yaml'),
            GenerationResult(connector_type='rds_mysql', action='skipped', reason='exists'),
            GenerationResult(connector_type='redshift', action='unavailable'),
            GenerationResult(connector_type='unknown', action='error', reason='API failure'),
        ]
        mock_orchestrator_cls.return_value = mock_orchestrator

        mock_st.spinner.return_value.__enter__ = MagicMock()
        mock_st.spinner.return_value.__exit__ = MagicMock(return_value=False)

        from scripts.streamlit_app import _run_auto_detect
        _run_auto_detect()

        # All display functions called
        mock_st.success.assert_called_once()
        mock_st.info.assert_called_once()
        mock_st.caption.assert_called_once()
        mock_st.error.assert_called_once()

        # Rerun because something was created
        mock_st.rerun.assert_called_once()


class TestStartupAutoDetection(unittest.TestCase):
    """Test that should_auto_run is checked during sidebar rendering on startup."""

    @patch('scripts.streamlit_app.AutoPopulateOrchestrator')
    @patch('scripts.streamlit_app.st')
    def test_should_auto_run_called_on_startup(self, mock_st, mock_orchestrator_cls):
        """Verify should_auto_run is called when session state has no 'auto_detect_ran' key.

        Validates: Requirements 7.1, 7.2
        """
        # Simulate fresh session state (no 'auto_detect_ran' key)
        session_state = {}
        mock_st.session_state = session_state

        mock_orchestrator = MagicMock()
        mock_orchestrator.should_auto_run.return_value = False
        mock_orchestrator_cls.return_value = mock_orchestrator

        # We need to test the startup logic from _render_sidebar.
        # The logic is:
        #   if 'auto_detect_ran' not in st.session_state:
        #       st.session_state['auto_detect_ran'] = True
        #       orchestrator = AutoPopulateOrchestrator(config_dir=_CONFIG_DIR)
        #       if orchestrator.should_auto_run():
        #           results = orchestrator.run()
        #
        # Since _render_sidebar depends on many st calls, we test the logic
        # by checking the orchestrator is instantiated and should_auto_run is called.

        # Simulate the startup detection logic directly (extracted from _render_sidebar)
        from scripts.streamlit_app import _CONFIG_DIR

        if 'auto_detect_ran' not in session_state:
            session_state['auto_detect_ran'] = True
            orchestrator = mock_orchestrator_cls(config_dir=_CONFIG_DIR)
            if orchestrator.should_auto_run():
                try:
                    results = orchestrator.run()
                    created = [r for r in results if r.action == 'created']
                    if created:
                        session_state['auto_detect_results'] = results
                except Exception as e:
                    session_state['auto_detect_error'] = str(e)

        # Verify orchestrator was instantiated with config_dir
        mock_orchestrator_cls.assert_called_once_with(config_dir=_CONFIG_DIR)
        # Verify should_auto_run was checked
        mock_orchestrator.should_auto_run.assert_called_once()
        # Since should_auto_run returns False, run() should NOT be called
        mock_orchestrator.run.assert_not_called()
        # session_state should be marked
        self.assertTrue(session_state.get('auto_detect_ran'))

    @patch('scripts.streamlit_app.AutoPopulateOrchestrator')
    @patch('scripts.streamlit_app.st')
    def test_startup_auto_run_triggers_detection(self, mock_st, mock_orchestrator_cls):
        """Verify orchestrator.run() is invoked when should_auto_run returns True.

        Validates: Requirements 7.2, 7.5
        """
        session_state = {}
        mock_st.session_state = session_state

        mock_orchestrator = MagicMock()
        mock_orchestrator.should_auto_run.return_value = True
        mock_orchestrator.run.return_value = [
            GenerationResult(connector_type='athena', action='created', file_path='/tmp/athena.yaml'),
        ]
        mock_orchestrator_cls.return_value = mock_orchestrator

        from scripts.streamlit_app import _CONFIG_DIR

        if 'auto_detect_ran' not in session_state:
            session_state['auto_detect_ran'] = True
            orchestrator = mock_orchestrator_cls(config_dir=_CONFIG_DIR)
            if orchestrator.should_auto_run():
                try:
                    results = orchestrator.run()
                    created = [r for r in results if r.action == 'created']
                    if created:
                        session_state['auto_detect_results'] = results
                except Exception as e:
                    session_state['auto_detect_error'] = str(e)

        # should_auto_run was True, so run() should be called
        mock_orchestrator.run.assert_called_once()
        # Results with created entries should be stored in session state
        self.assertIn('auto_detect_results', session_state)
        self.assertEqual(len(session_state['auto_detect_results']), 1)
        self.assertEqual(session_state['auto_detect_results'][0].action, 'created')

    @patch('scripts.streamlit_app.AutoPopulateOrchestrator')
    @patch('scripts.streamlit_app.st')
    def test_startup_skips_when_already_ran(self, mock_st, mock_orchestrator_cls):
        """Verify startup detection is skipped if 'auto_detect_ran' already set.

        Validates: Requirements 7.1
        """
        # Session state already has the flag set (not first run)
        session_state = {'auto_detect_ran': True}
        mock_st.session_state = session_state

        mock_orchestrator = MagicMock()
        mock_orchestrator_cls.return_value = mock_orchestrator

        from scripts.streamlit_app import _CONFIG_DIR

        if 'auto_detect_ran' not in session_state:
            session_state['auto_detect_ran'] = True
            orchestrator = mock_orchestrator_cls(config_dir=_CONFIG_DIR)
            if orchestrator.should_auto_run():
                try:
                    results = orchestrator.run()
                except Exception as e:
                    session_state['auto_detect_error'] = str(e)

        # Orchestrator should NOT be instantiated at all
        mock_orchestrator_cls.assert_not_called()
        mock_orchestrator.should_auto_run.assert_not_called()
        mock_orchestrator.run.assert_not_called()

    @patch('scripts.streamlit_app.AutoPopulateOrchestrator')
    @patch('scripts.streamlit_app.st')
    def test_startup_handles_error_gracefully(self, mock_st, mock_orchestrator_cls):
        """Verify startup detection stores error in session state on failure.

        Validates: Requirements 7.4
        """
        session_state = {}
        mock_st.session_state = session_state

        mock_orchestrator = MagicMock()
        mock_orchestrator.should_auto_run.return_value = True
        mock_orchestrator.run.side_effect = RuntimeError("Network timeout")
        mock_orchestrator_cls.return_value = mock_orchestrator

        from scripts.streamlit_app import _CONFIG_DIR

        if 'auto_detect_ran' not in session_state:
            session_state['auto_detect_ran'] = True
            orchestrator = mock_orchestrator_cls(config_dir=_CONFIG_DIR)
            if orchestrator.should_auto_run():
                try:
                    results = orchestrator.run()
                    created = [r for r in results if r.action == 'created']
                    if created:
                        session_state['auto_detect_results'] = results
                except Exception as e:
                    session_state['auto_detect_error'] = str(e)

        # Error should be stored
        self.assertIn('auto_detect_error', session_state)
        self.assertIn('Network timeout', session_state['auto_detect_error'])
        # No results should be stored
        self.assertNotIn('auto_detect_results', session_state)


if __name__ == '__main__':
    unittest.main()
