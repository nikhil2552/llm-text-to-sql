#!/usr/bin/env python3
"""CloudAge Data Intelligence — AI-powered analytics chat interface.

Spotter-inspired conversational UI for natural-language data queries.
Powered by AWS Bedrock + Athena.

Local mode (default): uses AWS credentials and env vars directly.
Remote mode: set API_URL to your ECS load balancer.

Example:
  export GLUE_DB_NAME=project_library_db
  export PROJECT_FILES_BUCKET=langchain-<account-id>-eu-north-1
  export ATHENA_WORKGROUP=project-text-to-sql
  streamlit run scripts/streamlit_app.py
"""
from __future__ import annotations

import base64
import os
import sys
from pathlib import Path
from typing import Optional

import hashlib
import hmac

import requests
import streamlit as st
import yaml

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_PATH = os.path.join(PROJECT_ROOT, 'src')
if SRC_PATH not in sys.path:
    sys.path.insert(0, SRC_PATH)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from llm_sql.config import SettingsError, get_settings, require_runtime_settings
from llm_sql.runner import build_athena_service
from llm_sql.connectors.registry import (
    get_connector,
    get_connector_from_env,
    list_connections,
    load_connections,
)
from llm_sql.connectors.auto_populate import AutoPopulateOrchestrator
from scripts.sidebar_helpers import (
    CONNECTOR_ORDER,
    CONNECTOR_ICONS,
    DIALECT_LABELS,
    group_connectors,
    get_status_icon,
    resolve_active_selection,
    get_connector_metadata,
    get_connector_display_name,
    get_config_filename,
    extract_status_panel_data,
    extract_template_fields,
    validate_form_data,
    build_yaml_config,
    format_test_success,
    format_test_failure,
)

# ── Logo path ────────────────────────────────────────────────────────────────
LOGO_PATH = Path(PROJECT_ROOT) / "assets" / "cloudage-logo.svg"


def _get_logo_b64() -> str:
    """Read the SVG logo and return a base64 data URI."""
    if LOGO_PATH.exists():
        svg_content = LOGO_PATH.read_text()
        b64 = base64.b64encode(svg_content.encode()).decode()
        return f"data:image/svg+xml;base64,{b64}"
    return ""


def _inject_custom_css():
    """Inject custom CSS — white background, CloudAge blue branding, moving clouds."""
    st.markdown("""
    <style>
    /* ── Global Reset ───────────────────────────────────────────────────── */
    .stApp {
        background-color: #FFFFFF;
    }
    [data-testid="stHeader"] {
        background-color: #FFFFFF;
        border-bottom: 1px solid #E8EDF2;
    }
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #F0F7FF 0%, #FFFFFF 100%);
        border-right: 1px solid #E8EDF2;
    }

    /* ── Moving Clouds Animation ────────────────────────────────────────── */
    @keyframes drift {
        from { transform: translateX(-100%); }
        to   { transform: translateX(100vw); }
    }
    .clouds-container {
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 220px;
        overflow: hidden;
        pointer-events: none;
        z-index: 0;
        opacity: 0.45;
    }
    .cloud {
        position: absolute;
        background: #E3F2FD;
        border-radius: 50px;
        animation: drift linear infinite;
    }
    .cloud::before, .cloud::after {
        content: '';
        position: absolute;
        background: #E3F2FD;
        border-radius: 50%;
    }
    .cloud-1 {
        width: 120px; height: 40px;
        top: 30px;
        animation-duration: 35s;
        animation-delay: 0s;
    }
    .cloud-1::before {
        width: 50px; height: 50px;
        top: -20px; left: 20px;
    }
    .cloud-1::after {
        width: 60px; height: 45px;
        top: -18px; left: 50px;
    }
    .cloud-2 {
        width: 160px; height: 50px;
        top: 80px;
        animation-duration: 45s;
        animation-delay: -10s;
    }
    .cloud-2::before {
        width: 65px; height: 60px;
        top: -28px; left: 30px;
    }
    .cloud-2::after {
        width: 75px; height: 55px;
        top: -22px; left: 70px;
    }
    .cloud-3 {
        width: 100px; height: 35px;
        top: 50px;
        animation-duration: 55s;
        animation-delay: -20s;
    }
    .cloud-3::before {
        width: 45px; height: 42px;
        top: -18px; left: 15px;
    }
    .cloud-3::after {
        width: 50px; height: 38px;
        top: -15px; left: 45px;
    }
    .cloud-4 {
        width: 140px; height: 45px;
        top: 130px;
        animation-duration: 40s;
        animation-delay: -5s;
    }
    .cloud-4::before {
        width: 55px; height: 52px;
        top: -24px; left: 25px;
    }
    .cloud-4::after {
        width: 65px; height: 48px;
        top: -20px; left: 60px;
    }
    .cloud-5 {
        width: 90px; height: 30px;
        top: 160px;
        animation-duration: 50s;
        animation-delay: -15s;
    }
    .cloud-5::before {
        width: 40px; height: 38px;
        top: -16px; left: 12px;
    }
    .cloud-5::after {
        width: 45px; height: 35px;
        top: -14px; left: 38px;
    }

    /* Ensure main content sits above clouds */
    [data-testid="stMainBlockContainer"] {
        position: relative;
        z-index: 1;
    }

    /* ── Hero Section ───────────────────────────────────────────────────── */
    .hero-section {
        text-align: center;
        padding: 2.5rem 1rem 1.5rem;
    }
    .hero-logo-img {
        width: 220px;
        margin: 0 auto 1.5rem;
        display: block;
    }
    .hero-title {
        font-size: 2rem;
        font-weight: 700;
        color: #0D47A1;
        margin-bottom: 0.5rem;
        letter-spacing: -0.01em;
    }
    .hero-subtitle {
        font-size: 1.15rem;
        color: #1976D2;
        font-weight: 500;
        margin-bottom: 0.5rem;
    }
    .hero-desc {
        font-size: 0.95rem;
        color: #64748B;
        max-width: 520px;
        margin: 0 auto;
        line-height: 1.5;
    }

    /* ── Feature Pills (Spotter-style) ──────────────────────────────────── */
    .features-row {
        display: flex;
        justify-content: center;
        gap: 1.25rem;
        flex-wrap: wrap;
        padding: 2rem 0 1.5rem;
    }
    .feature-pill {
        display: flex;
        align-items: center;
        gap: 0.6rem;
        padding: 0.75rem 1.25rem;
        background: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-radius: 50px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.04);
        transition: all 0.2s ease;
    }
    .feature-pill:hover {
        border-color: #1976D2;
        box-shadow: 0 4px 16px rgba(25,118,210,0.1);
        transform: translateY(-1px);
    }
    .feature-pill-icon {
        font-size: 1.25rem;
    }
    .feature-pill-text {
        font-size: 0.85rem;
        font-weight: 500;
        color: #334155;
    }
    .feature-pill-desc {
        font-size: 0.75rem;
        color: #64748B;
    }

    /* ── Suggestion Cards ───────────────────────────────────────────────── */
    .suggestions-header {
        text-align: center;
        font-size: 0.85rem;
        color: #94A3B8;
        margin: 1.5rem 0 0.75rem;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        font-weight: 500;
    }

    /* Style the suggestion buttons */
    div[data-testid="stHorizontalBlock"] button[kind="secondary"] {
        border-radius: 12px;
        border: 1px solid #E2E8F0;
        background: #F8FAFC;
        color: #334155;
        font-size: 0.82rem;
        padding: 0.6rem 1rem;
        transition: all 0.2s ease;
    }
    div[data-testid="stHorizontalBlock"] button[kind="secondary"]:hover {
        border-color: #1976D2;
        background: #EBF5FF;
        color: #1565C0;
    }

    /* ── Chat Messages ──────────────────────────────────────────────────── */
    [data-testid="stChatMessage"] {
        border-radius: 16px;
        padding: 1rem 1.25rem;
        margin-bottom: 0.75rem;
        border: 1px solid #F1F5F9;
    }

    /* ── Chat Input ─────────────────────────────────────────────────────── */
    [data-testid="stChatInputContainer"] {
        border-top: 1px solid #E8EDF2;
        padding-top: 0.5rem;
    }

    /* ── Sidebar Elements ───────────────────────────────────────────────── */
    .sidebar-logo {
        text-align: center;
        padding: 1.25rem 0 1rem;
        border-bottom: 1px solid #E2E8F0;
        margin-bottom: 1.25rem;
    }
    .sidebar-logo img {
        width: 160px;
    }
    .sidebar-section-title {
        font-size: 0.7rem;
        font-weight: 600;
        color: #94A3B8;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        margin: 1rem 0 0.5rem;
    }
    .connection-badge {
        display: inline-flex;
        align-items: center;
        gap: 0.4rem;
        padding: 0.3rem 0.75rem;
        border-radius: 20px;
        font-size: 0.75rem;
        font-weight: 500;
        background: #ECFDF5;
        color: #059669;
        margin-bottom: 0.75rem;
    }
    .connection-badge::before {
        content: '';
        width: 7px;
        height: 7px;
        border-radius: 50%;
        background: #059669;
    }
    .info-table {
        font-size: 0.8rem;
        color: #475569;
        line-height: 1.8;
    }
    .info-table strong {
        color: #1E293B;
    }

    /* ── Compact Chat Header ────────────────────────────────────────────── */
    .chat-header {
        text-align: center;
        padding: 0.5rem 0 1rem;
        border-bottom: 1px solid #F1F5F9;
        margin-bottom: 1rem;
    }
    .chat-header img {
        width: 140px;
    }

    /* ── Connector Picker Cards ─────────────────────────────────────────── */
    .connector-group-title {
        font-size: 0.65rem;
        font-weight: 600;
        color: #94A3B8;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        margin: 0.75rem 0 0.4rem;
    }
    .connector-card {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        padding: 0.5rem 0.75rem;
        border-radius: 10px;
        border: 1px solid #E2E8F0;
        background: #FFFFFF;
        margin-bottom: 0.35rem;
        cursor: pointer;
        transition: all 0.15s ease;
    }
    .connector-card:hover {
        border-color: #1976D2;
        background: #F0F7FF;
    }
    .connector-card.active {
        border-color: #1976D2;
        background: #EBF5FF;
        box-shadow: 0 0 0 1px #1976D2;
    }
    .connector-card-icon {
        font-size: 1.1rem;
        width: 24px;
        text-align: center;
    }
    .connector-card-name {
        flex: 1;
        font-size: 0.8rem;
        font-weight: 500;
        color: #334155;
    }
    .connector-card-status {
        font-size: 0.75rem;
    }
    .connector-status-configured {
        color: #059669;
        font-size: 0.7rem;
    }
    .connector-status-unconfigured {
        color: #D97706;
        font-size: 0.7rem;
    }

    /* ── Status Panel ───────────────────────────────────────────────────── */
    .status-panel {
        padding: 0.6rem 0.75rem;
        border-radius: 10px;
        background: #F8FAFC;
        border: 1px solid #E2E8F0;
        margin: 0.5rem 0;
        font-size: 0.78rem;
        color: #475569;
        line-height: 1.7;
    }
    .status-panel strong {
        color: #1E293B;
    }
    .status-connected {
        color: #059669;
        font-weight: 500;
    }
    .status-unconfigured {
        color: #D97706;
        font-weight: 500;
    }

    /* ── Hide Streamlit defaults ────────────────────────────────────────── */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    [data-testid="stDecoration"] {display: none;}
    [data-testid="stToolbar"] {display: none;}
    .stDeployButton {display: none;}
    </style>
    """, unsafe_allow_html=True)

    # Inject moving cloud elements
    st.markdown("""
    <div class="clouds-container">
        <div class="cloud cloud-1"></div>
        <div class="cloud cloud-2"></div>
        <div class="cloud cloud-3"></div>
        <div class="cloud cloud-4"></div>
        <div class="cloud cloud-5"></div>
    </div>
    """, unsafe_allow_html=True)


# ── Service Layer ────────────────────────────────────────────────────────────

def _parse_glue_db_names(raw: str | None, fallback: str | None) -> list[str]:
    if raw:
        names = [part.strip() for part in raw.split(',') if part.strip()]
        if names:
            return names
    if fallback:
        return [fallback]
    return []


@st.cache_resource(show_spinner=False)
def _get_local_service(_db, _bucket, _region, _workgroup):
    """Build the Athena service. Args are used as cache keys so config changes reconnect."""
    from llm_sql.config import get_settings as _gs
    _gs.cache_clear()  # clear lru_cache so new env vars are picked up
    settings = get_settings()
    runtime = require_runtime_settings(settings)
    glue_db_names = _parse_glue_db_names(
        os.environ.get('GLUE_DB_NAMES'),
        runtime.glue_db_name,
    )
    if not glue_db_names:
        raise SettingsError('Set GLUE_DB_NAME or GLUE_DB_NAMES.')
    return build_athena_service(
        glue_db_names,
        runtime.project_files_bucket,
        region=runtime.region,
        athena_workgroup=runtime.athena_workgroup,
    )


def _api_base_url() -> Optional[str]:
    url = (os.environ.get('API_URL') or st.session_state.get('api_url') or '').strip()
    if not url:
        return None
    return url.rstrip('/')


def _ask_remote(question: str) -> str:
    base = _api_base_url()
    if not base:
        raise RuntimeError('API_URL is not set.')
    headers = {'Content-Type': 'application/json'}
    api_key = os.environ.get('API_KEY') or st.session_state.get('api_key')
    if api_key:
        headers['X-Api-Key'] = api_key
    response = requests.post(
        f'{base}/query',
        json={'question': question},
        headers=headers,
        timeout=300,
    )
    if response.status_code != 200:
        detail = response.text
        try:
            detail = response.json().get('detail', detail)
        except Exception:
            pass
        raise RuntimeError(f'API error ({response.status_code}): {detail}')
    return response.json()['answer']


def _ask_local(question: str) -> str:
    # Pass current config as cache keys so service rebuilds on config change
    db = os.environ.get('GLUE_DB_NAME', '')
    bucket = os.environ.get('PROJECT_FILES_BUCKET', '')
    region = os.environ.get('AWS_REGION', 'eu-north-1')
    workgroup = os.environ.get('ATHENA_WORKGROUP', 'primary')
    service = _get_local_service(db, bucket, region, workgroup)
    return service.run_query(question)


def _ask(question: str) -> str:
    if _api_base_url():
        return _ask_remote(question)

    # Get selected connector type from the new picker
    selected_type = st.session_state.get('active_connector_type', 'athena')

    # If Athena is selected, use the existing local service (backward compatible)
    if selected_type == 'athena':
        return _ask_local(question)

    # Try connector framework for other sources (config/connections/*.yaml)
    connections = load_connections()

    # Find a matching configured connection
    matching_conn = None
    for name, config in connections.items():
        if config.get('type') == selected_type:
            matching_conn = name
            break

    if matching_conn:
        try:
            connector = get_connector(matching_conn)
            return connector.run_query(question)
        except ImportError as e:
            return f"⚠️ {e}"
        except NotImplementedError as e:
            return f"⚠️ {e}"
        except Exception as e:
            return f"⚠️ Connector error: {e}"

    # No config file found — trigger the unconfigured banner
    display_name = get_connector_display_name(selected_type)
    trigger_unconfigured_banner(selected_type)
    return (
        f"⚠️ **{display_name}** is not configured. "
        f"Use the Configure panel in the sidebar to set it up."
    )


# ── UI Components ────────────────────────────────────────────────────────────

def _render_hero():
    """Render the Spotter-inspired hero/welcome section."""
    logo_uri = _get_logo_b64()

    logo_html = ""
    if logo_uri:
        logo_html = f'<img src="{logo_uri}" class="hero-logo-img" alt="CloudAge"/>'

    st.markdown(f"""
    <div class="hero-section">
        {logo_html}
        <div class="hero-title" style="color:#059669;">AI Data Analyst Agent</div>
        <div class="hero-subtitle">Instant answers from your data</div>
        <div class="hero-desc">
            Ask questions in plain English. CloudAge generates SQL, executes it
            against your data warehouse, and delivers trusted answers in seconds.
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Feature pills (Spotter-style)
    st.markdown("""
    <div class="features-row">
        <div class="feature-pill">
            <span class="feature-pill-icon">🧠</span>
            <div>
                <div class="feature-pill-text">Multi-step reasoning</div>
                <div class="feature-pill-desc">Breaks down complex questions</div>
            </div>
        </div>
        <div class="feature-pill">
            <span class="feature-pill-icon">⚡</span>
            <div>
                <div class="feature-pill-text">Instant insights</div>
                <div class="feature-pill-desc">SQL generated in seconds</div>
            </div>
        </div>
        <div class="feature-pill">
            <span class="feature-pill-icon">🛡️</span>
            <div>
                <div class="feature-pill-text">Enterprise-grade trust</div>
                <div class="feature-pill-desc">Read-only, fully auditable</div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)


def _render_suggestions():
    """Render clickable suggestion buttons."""
    st.markdown(
        '<div class="suggestions-header">Try asking</div>',
        unsafe_allow_html=True,
    )

    suggestions = [
        ("📚", "How many books are in the library?"),
        ("🚗", "What is the average price of cars?"),
        ("💰", "Top 5 most expensive cars"),
        ("📖", "List all genres in the library"),
        ("🏎️", "Cars with horsepower above 200"),
        ("📅", "Books published after 1950"),
    ]

    cols = st.columns(3)
    for i, (icon, text) in enumerate(suggestions):
        with cols[i % 3]:
            if st.button(
                f"{icon}  {text}",
                key=f"sug_{i}",
                use_container_width=True,
            ):
                st.session_state['pending_question'] = text
                st.rerun()


def _render_connector_picker() -> str:
    """Render the grouped connector picker and return the selected connector type.

    Displays connectors as a clean selectbox with emoji icons and status indicators.
    Persists selection to session state.

    Returns:
        The selected ConnectorType string (e.g. 'athena', 'redshift').
    """
    config_dir = Path("config/connections")

    # Get all connector type keys from the fixed order
    all_types = [entry[0] for entry in CONNECTOR_ORDER]

    # Build display options with icons
    display_names: dict[str, str] = {entry[0]: entry[1] for entry in CONNECTOR_ORDER}

    # Build selectbox options: "icon name"
    options_map: dict[str, str] = {}  # display_label -> type_key
    option_labels: list[str] = []

    for ct in all_types:
        icon = CONNECTOR_ICONS.get(ct, "❓")
        name = display_names.get(ct, ct)
        status = get_status_icon(ct, config_dir)
        label = f"{icon} {name} {status}"
        option_labels.append(label)
        options_map[label] = ct

    # Current selection
    current_type = st.session_state.get("active_connector_type", all_types[0])
    current_idx = all_types.index(current_type) if current_type in all_types else 0

    selected_label = st.selectbox(
        "Data source",
        options=option_labels,
        index=current_idx,
        key="connector_selectbox",
        label_visibility="collapsed",
    )

    resolved = options_map.get(selected_label, all_types[0])

    # Show grouped overview below the selector
    groups = group_connectors(all_types)
    for group_name in ("AWS Native", "External Platforms"):
        connectors_in_group = groups.get(group_name, [])
        if not connectors_in_group:
            continue

        st.markdown(f'<div class="connector-group-title">{group_name}</div>', unsafe_allow_html=True)

        cards_html = ""
        for ct in connectors_in_group:
            icon = CONNECTOR_ICONS.get(ct, "❓")
            name = display_names.get(ct, ct)
            status = get_status_icon(ct, config_dir)
            is_active = "active" if ct == resolved else ""
            status_class = "connector-status-configured" if status == "✅" else "connector-status-unconfigured"
            status_text = "Connected" if status == "✅" else "Not configured"

            cards_html += (
                f'<div class="connector-card {is_active}">'
                f'<span class="connector-card-icon">{icon}</span>'
                f'<span class="connector-card-name">{name}</span>'
                f'<span class="{status_class}">{status_text}</span>'
                f'</div>'
            )

        st.markdown(cards_html, unsafe_allow_html=True)

    # Persist to session state
    st.session_state["active_connector_type"] = resolved

    return resolved


# ── Config directory for connections ─────────────────────────────────────────
_CONFIG_DIR = Path(PROJECT_ROOT) / "config" / "connections"


def _render_status_panel(connector_type: str) -> None:
    """Render connection status panel for the selected connector type.

    Handles five states:
    - Athena: displays Glue DB, region, workgroup from env/session state
    - Configured External_Connector: displays type, host/account, database, status
    - Unconfigured: displays setup prompt with required fields from template
    - Unreadable config: displays error with file path
    - Removed/disabled config: displays warning with button to open config form
    """
    # ── Athena special case ──
    if connector_type == "athena":
        glue_db = os.environ.get(
            "GLUE_DB_NAME", st.session_state.get("cfg_glue_db", "N/A")
        )
        region = os.environ.get(
            "AWS_REGION", st.session_state.get("cfg_region", "N/A")
        )
        workgroup = os.environ.get(
            "ATHENA_WORKGROUP", st.session_state.get("cfg_workgroup", "N/A")
        )
        st.markdown(
            f'<div class="info-table">'
            f"<strong>Glue DB:</strong> {glue_db}<br>"
            f"<strong>Region:</strong> {region}<br>"
            f"<strong>Workgroup:</strong> {workgroup}"
            f"</div>",
            unsafe_allow_html=True,
        )
        return

    # ── External connectors: scan config directory ──
    config_file_path: Path | None = None
    config_data: dict | None = None
    config_error: str | None = None
    config_disabled: bool = False

    if _CONFIG_DIR.is_dir():
        for yaml_file in _CONFIG_DIR.glob("*.yaml"):
            try:
                with open(yaml_file, "r") as f:
                    data = yaml.safe_load(f)
                if not isinstance(data, dict):
                    continue
                if data.get("type") == connector_type:
                    config_file_path = yaml_file
                    if data.get("enabled") is True:
                        config_data = data
                    else:
                        # File exists but disabled
                        config_disabled = True
                    break
            except (yaml.YAMLError, OSError) as exc:
                # File found but unreadable/malformed
                config_file_path = yaml_file
                config_error = str(exc)
                break

    # ── State: Configured and enabled ──
    if config_data is not None:
        panel = extract_status_panel_data(config_data)
        status_class = "status-connected" if panel["status"] == "Connected" else ""
        dialect = DIALECT_LABELS.get(connector_type, panel["type"])
        st.markdown(
            f'<div class="status-panel">'
            f'<strong>{dialect}</strong><br>'
            f'📍 {panel["host_or_account"]}<br>'
            f'🗄️ {panel["database"]}<br>'
            f'<span class="{status_class}">● {panel["status"]}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
        return

    # ── State: Unreadable/malformed config ──
    if config_error is not None and config_file_path is not None:
        st.markdown(
            f'<div class="status-panel" style="border-color:#FCA5A5;">'
            f'⚠️ Config error<br>'
            f'<span style="font-size:0.7rem;color:#94A3B8;">{config_file_path.name}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
        return

    # ── State: Config exists but disabled (removed) ──
    if config_disabled and config_file_path is not None:
        st.markdown(
            '<div class="status-panel" style="border-color:#FDE68A;">'
            '⚠️ Configuration disabled'
            '</div>',
            unsafe_allow_html=True,
        )
        if st.button(
            "🔧 Re-configure",
            key=f"reconfig_{connector_type}",
        ):
            st.session_state["config_form_expanded"] = True
        return

    # ── State: Unconfigured - try to load template ──
    file_basename = get_config_filename(connector_type)
    template_path = _CONFIG_DIR / f"{file_basename}.yaml.template"
    display_name = get_connector_display_name(connector_type)
    dialect = DIALECT_LABELS.get(connector_type, connector_type)
    st.markdown(
        f'<div class="status-panel">'
        f'<span class="status-unconfigured">○ Not configured</span><br>'
        f'<span style="font-size:0.72rem;color:#64748B;">{dialect}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )


def _render_config_form(connector_type: str) -> None:
    """Render inline configuration form for the selected connector type.

    Loads the .yaml.template file to determine field definitions, pre-populates
    from existing config if present with enabled: true, validates on submit,
    and writes YAML to config/connections/.
    """
    # Determine if form should be expanded
    form_expanded = st.session_state.get("config_form_expanded", False)

    # Only expand if explicitly requested (not auto-expand for unconfigured)
    should_expand = form_expanded

    with st.expander(f"🔧 Configure {get_connector_display_name(connector_type)}", expanded=should_expand):
        # Load template
        file_basename = get_config_filename(connector_type)
        template_path = _CONFIG_DIR / f"{file_basename}.yaml.template"
        if not template_path.exists():
            st.error("Template unavailable")
            return

        # Extract field definitions from template
        fields = extract_template_fields(template_path)

        # Pre-populate from existing config if present with enabled: true
        existing_values: dict[str, str] = {}
        existing_name: str = ""
        if _CONFIG_DIR.is_dir():
            for yaml_file in _CONFIG_DIR.glob("*.yaml"):
                try:
                    with open(yaml_file, "r") as f:
                        data = yaml.safe_load(f)
                    if (
                        isinstance(data, dict)
                        and data.get("type") == connector_type
                        and data.get("enabled") is True
                    ):
                        settings = data.get("settings", {})
                        if isinstance(settings, dict):
                            existing_values = {k: str(v) for k, v in settings.items()}
                        existing_name = data.get("name", "")
                        break
                except (yaml.YAMLError, OSError):
                    continue

        # Render form
        with st.form(f"config_form_{connector_type}"):
            # Connection name field
            name_value = existing_name if existing_name else ""
            connection_name = st.text_input(
                "Connection Name",
                value=name_value,
                placeholder="My Connection",
                key=f"config_{connector_type}_name",
            )

            # Settings fields from template
            form_values: dict[str, str] = {}
            for field in fields:
                field_key = field["key"]
                placeholder = field["placeholder"]

                # Determine if secret field
                is_secret = any(
                    keyword in field_key.lower()
                    for keyword in ("secret", "token", "password")
                )

                # Default value from existing config or empty
                default_value = existing_values.get(field_key, "")

                input_type = "password" if is_secret else "default"
                form_values[field_key] = st.text_input(
                    label=field_key,
                    value=default_value,
                    placeholder=placeholder,
                    type=input_type,
                    key=f"config_{connector_type}_{field_key}",
                )

            # Submit button
            submitted = st.form_submit_button("Save Configuration")

        # Handle submission outside the form context
        if submitted:
            # Collect field names for validation
            field_names = [f["key"] for f in fields]

            # Validate form data
            errors = validate_form_data(field_names, form_values)

            if errors:
                for field_name, msg in errors.items():
                    st.error(f"❌ {field_name}: {msg}")
            else:
                # Build config
                settings_dict = {k: v for k, v in form_values.items()}
                config_name = connection_name.strip() if connection_name else connector_type
                config_data = build_yaml_config(connector_type, config_name, settings_dict)

                # Write YAML to config/connections/
                output_path = _CONFIG_DIR / f"{file_basename}.yaml"
                try:
                    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
                    with open(output_path, "w") as f:
                        yaml.dump(config_data, f, default_flow_style=False)

                    # Update session state
                    st.session_state["config_form_expanded"] = False
                    st.success("Configuration saved!")
                    st.rerun()
                except OSError as exc:
                    st.error(f"Failed to write configuration: {exc}")


def _render_connection_tester(connector_type: str) -> None:
    """Render test connection button and results for the selected connector.

    Only displays the "Test Connection" button when the connector is configured
    (i.e. a .yaml file with matching type and enabled: true exists in _CONFIG_DIR).
    On click, invokes get_connector(name).test_connection() and displays the result.
    Results are cached in st.session_state['test_result_{type}'].
    """
    from datetime import datetime

    # ── Check if connector is configured ──
    if not _CONFIG_DIR.is_dir():
        return

    configured_name: str | None = None
    for yaml_file in _CONFIG_DIR.glob("*.yaml"):
        try:
            with open(yaml_file, "r") as f:
                data = yaml.safe_load(f)
            if not isinstance(data, dict):
                continue
            if data.get("type") == connector_type and data.get("enabled") is True:
                configured_name = data.get("name", yaml_file.stem)
                break
        except (yaml.YAMLError, OSError):
            continue

    if configured_name is None:
        return

    # ── Show "Test Connection" button ──
    if st.button("🔌 Test Connection", key=f"test_conn_{connector_type}"):
        with st.spinner("Testing connection..."):
            try:
                connector = get_connector(configured_name)
                connector.test_connection()

                # Success
                dialect = DIALECT_LABELS.get(connector_type, "Unknown")
                timestamp = datetime.now().isoformat()
                result = {
                    "success": True,
                    "message": format_test_success(dialect, timestamp),
                    "timestamp": timestamp,
                }
            except Exception as exc:
                result = {
                    "success": False,
                    "message": format_test_failure(str(exc)),
                    "timestamp": "",
                }

            # Cache result in session state
            st.session_state[f"test_result_{connector_type}"] = result

    # ── Display cached result (if any) ──
    cached = st.session_state.get(f"test_result_{connector_type}")
    if cached:
        if cached["success"]:
            st.success(cached["message"])
        else:
            st.error(cached["message"])


def trigger_unconfigured_banner(connector_type: str) -> None:
    """Trigger the unconfigured connector banner in the sidebar.

    Sets session state flags so that _check_and_show_unconfigured_banner
    will display the banner on the next render cycle. Called from query
    handling logic when an unconfigured connector is active.
    """
    st.session_state['show_unconfigured_banner'] = True
    st.session_state['banner_connector_type'] = connector_type


def _check_and_show_unconfigured_banner(connector_type: str) -> None:
    """Show an informational banner if the active connector is unconfigured.

    The banner states the connector type name is not configured and includes
    a button to expand the Inline_Config_Form. It persists until the user
    configures the connector or selects a different type.
    """
    show_banner = st.session_state.get('show_unconfigured_banner', False)
    banner_type = st.session_state.get('banner_connector_type', '')

    if not show_banner:
        return

    # If banner refers to a different connector type, clear it
    if banner_type != connector_type:
        st.session_state['show_unconfigured_banner'] = False
        st.session_state['banner_connector_type'] = ''
        return

    # Show the banner
    display_name = get_connector_display_name(connector_type)
    st.warning(f"⚠️ {display_name} is not configured. Please configure it to run queries.")

    if st.button("🔧 Configure", key="banner_configure_btn"):
        st.session_state['config_form_expanded'] = True


def _friendly_connector_name(connector_type: str) -> str:
    """Return a user-friendly display name for a connector type."""
    names = {
        "athena": "Athena",
        "rds_mysql": "RDS Aurora MySQL",
        "redshift": "Redshift Serverless",
    }
    return names.get(connector_type, connector_type)


def _run_auto_detect():
    """Run auto-detection and display results in the sidebar."""
    orchestrator = AutoPopulateOrchestrator(config_dir=_CONFIG_DIR)
    with st.spinner("Scanning CloudFormation stacks..."):
        results = orchestrator.run()

    created = [r for r in results if r.action == 'created']
    skipped = [r for r in results if r.action == 'skipped']
    unavailable = [r for r in results if r.action == 'unavailable']
    errors = [r for r in results if r.action == 'error']

    if created:
        names = ', '.join(_friendly_connector_name(r.connector_type) for r in created)
        st.success(f"✓ Configured: {names}")
    if skipped:
        names = ', '.join(_friendly_connector_name(r.connector_type) for r in skipped)
        st.info(f"Already configured: {names}")
    if unavailable:
        names = ', '.join(_friendly_connector_name(r.connector_type) for r in unavailable)
        st.caption(f"Not deployed: {names}")
    if errors:
        for e in errors:
            st.error(f"Detection failed: {e.reason}")
    if not created and not skipped and not errors and not unavailable:
        st.caption("No stacks found in this region.")

    if created:
        st.rerun()


def _render_sidebar():
    """Render sidebar with CloudAge logo and connection info."""
    logo_uri = _get_logo_b64()

    with st.sidebar:
        # ── Startup auto-detection (runs once per session) ──
        if 'auto_detect_ran' not in st.session_state:
            st.session_state['auto_detect_ran'] = True
            orchestrator = AutoPopulateOrchestrator(config_dir=_CONFIG_DIR)
            if orchestrator.should_auto_run():
                try:
                    results = orchestrator.run()
                    created = [r for r in results if r.action == 'created']
                    if created:
                        st.session_state['auto_detect_results'] = results
                        st.rerun()
                except Exception as e:
                    st.session_state['auto_detect_error'] = str(e)

        # Show auto-detect results banner (from startup detection)
        if 'auto_detect_results' in st.session_state:
            results = st.session_state.pop('auto_detect_results')
            created = [r for r in results if r.action == 'created']
            if created:
                names = ', '.join(_friendly_connector_name(r.connector_type) for r in created)
                st.success(f"✓ Auto-configured: {names}")

        # Show auto-detect error (from startup detection)
        if 'auto_detect_error' in st.session_state:
            error_msg = st.session_state.pop('auto_detect_error')
            st.warning(f"Could not auto-detect connections: {error_msg}")

        # Logo
        if logo_uri:
            st.markdown(
                f'<div class="sidebar-logo">'
                f'<img src="{logo_uri}" alt="CloudAge"/>'
                f'</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<div class="sidebar-logo">'
                '<span style="font-size:1.5rem; font-weight:700; color:#0D47A1;">'
                'CloudAge</span></div>',
                unsafe_allow_html=True,
            )

        settings = get_settings()
        api_url = _api_base_url()

        # ── Load Balancer URL (always visible at top) ──
        st.markdown(
            '<div class="sidebar-section-title">⚖️ Load Balancer URL</div>',
            unsafe_allow_html=True,
        )
        remote_url = st.text_input(
            'ALB URL',
            value=st.session_state.get('api_url', ''),
            placeholder='http://data-arch-ai-alb-xxx.elb.amazonaws.com',
            key='api_url_input',
            label_visibility='collapsed',
        )
        if remote_url:
            st.session_state['api_url'] = remote_url.strip().rstrip('/')

        # ── Connection status ──
        st.markdown(
            '<div class="sidebar-section-title">Connection</div>',
            unsafe_allow_html=True,
        )

        if _api_base_url():
            st.markdown(
                '<div class="connection-badge">Remote API ✓</div>',
                unsafe_allow_html=True,
            )
            if not os.environ.get('API_KEY'):
                st.session_state.setdefault('api_key', '')
                st.session_state['api_key'] = st.text_input(
                    '🔑 API Key (optional)',
                    type='password',
                    key='api_key_input',
                    placeholder='X-Api-Key header',
                )
        else:
            try:
                runtime = require_runtime_settings(settings)
                st.markdown(
                    '<div class="connection-badge">Local AWS ✓</div>',
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f'<div class="info-table">'
                    f'<strong>Database:</strong> {runtime.glue_db_name}<br>'
                    f'<strong>Region:</strong> {runtime.region}<br>'
                    f'<strong>Workgroup:</strong> {runtime.athena_workgroup}'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            except SettingsError:
                st.markdown(
                    '<div style="padding:0.5rem 0.75rem; background:#ECFDF5; '
                    'border:1px solid #A7F3D0; border-radius:8px; '
                    'font-size:0.8rem; color:#065F46;">'
                    '⚙️ <strong>Setup needed</strong><br>'
                    'Enter a Load Balancer URL above, or fill in AWS details below.'
                    '</div>',
                    unsafe_allow_html=True,
                )

        # ── AWS Configuration (always visible) ──
        with st.expander("☁️ AWS Configuration", expanded=not bool(_api_base_url())):
            new_db = st.text_input(
                '🔗 Glue Database',
                value=os.environ.get('GLUE_DB_NAME', st.session_state.get('cfg_glue_db', '')),
                placeholder='e.g. project_library_db',
                key='cfg_glue_db_input',
            )
            new_bucket = st.text_input(
                '🪣 S3 Bucket',
                value=os.environ.get('PROJECT_FILES_BUCKET', st.session_state.get('cfg_bucket', '')),
                placeholder='e.g. langchain-012345-eu-north-1',
                key='cfg_bucket_input',
            )
            new_workgroup = st.text_input(
                '📊 Athena Workgroup',
                value=os.environ.get('ATHENA_WORKGROUP', st.session_state.get('cfg_workgroup', 'project-text-to-sql')),
                placeholder='e.g. project-text-to-sql',
                key='cfg_workgroup_input',
            )
            new_region = st.text_input(
                '🌍 AWS Region',
                value=os.environ.get('AWS_REGION', st.session_state.get('cfg_region', 'eu-north-1')),
                placeholder='e.g. eu-north-1',
                key='cfg_region_input',
            )

            # Save to session state so the service layer picks them up
            if new_db:
                st.session_state['cfg_glue_db'] = new_db
                os.environ['GLUE_DB_NAME'] = new_db
            if new_bucket:
                st.session_state['cfg_bucket'] = new_bucket
                os.environ['PROJECT_FILES_BUCKET'] = new_bucket
            if new_workgroup:
                st.session_state['cfg_workgroup'] = new_workgroup
                os.environ['ATHENA_WORKGROUP'] = new_workgroup
            if new_region:
                st.session_state['cfg_region'] = new_region
                os.environ['AWS_REGION'] = new_region

        st.divider()

        # ── Data Source (NEW) ──
        st.markdown(
            '<div class="sidebar-section-title">📊 Data Source</div>',
            unsafe_allow_html=True,
        )

        selected_type = _render_connector_picker()
        _render_status_panel(selected_type)
        _render_config_form(selected_type)
        _render_connection_tester(selected_type)
        _check_and_show_unconfigured_banner(selected_type)

        # Auto-detect button (subtle, below connector cards)
        if st.button("⚡ Auto-detect from CloudFormation", key="auto_detect_btn", use_container_width=True):
            _run_auto_detect()

        # Backward compatibility: update active_source from active_connector_type
        st.session_state['active_source'] = st.session_state.get('active_connector_type', 'athena')

        st.divider()

        # Actions
        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("🗑️ Clear", use_container_width=True):
                st.session_state['messages'] = []
                st.rerun()
        with col2:
            if st.button("🔄 Reconnect", use_container_width=True):
                st.cache_resource.clear()
                st.rerun()
        with col3:
            if st.button("🚪 Logout", use_container_width=True):
                st.session_state['authenticated'] = False
                st.session_state['messages'] = []
                st.rerun()

        # Footer
        st.markdown(
            '<div style="text-align:center; font-size:0.7rem; color:#94A3B8; '
            'padding:1rem 1rem 0.5rem; margin-top:1rem;">'
            'Powered by AWS Bedrock + Athena<br>'
            '© 2025 CloudAge Global'
            '</div>',
            unsafe_allow_html=True,
        )



def _check_login() -> bool:
    """Display login form and validate credentials.

    Credentials MUST be set via environment variables:
      - APP_USERNAME (required)
      - APP_PASSWORD (required)

    Returns True if authenticated, False otherwise.
    """
    if st.session_state.get('authenticated'):
        return True

    # Credentials must be explicitly configured - no insecure defaults
    valid_username = os.environ.get('APP_USERNAME', '')
    valid_password = os.environ.get('APP_PASSWORD', '')

    if not valid_username or not valid_password:
        st.error(
            "Authentication not configured. "
            "Set APP_USERNAME and APP_PASSWORD environment variables."
        )
        return False

    logo_uri = _get_logo_b64()

    # Center the login form
    st.markdown("""
    <style>
    [data-testid="stForm"] {
        max-width: 400px;
        margin: 0 auto;
        padding: 2rem;
        border: 1px solid #E2E8F0;
        border-radius: 16px;
        background: #FFFFFF;
        box-shadow: 0 4px 24px rgba(0,0,0,0.06);
    }
    </style>
    """, unsafe_allow_html=True)

    # Logo + title
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        if logo_uri:
            st.markdown(
                f'<div style="text-align:center; padding:2rem 0 1rem;">'
                f'<img src="{logo_uri}" style="width:180px;" alt="CloudAge"/>'
                f'</div>',
                unsafe_allow_html=True,
            )
        st.markdown(
            '<p style="text-align:center; color:#64748B; font-size:0.9rem; margin-bottom:1.5rem;">'
            'Sign in to Data Intelligence</p>',
            unsafe_allow_html=True,
        )

    # Login form
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        with st.form('login_form'):
            username = st.text_input('Username', placeholder='Enter username')
            password = st.text_input('Password', type='password', placeholder='Enter password')
            submitted = st.form_submit_button('Sign In', use_container_width=True)

            if submitted:
                # Use constant-time comparison to prevent timing attacks
                user_ok = hmac.compare_digest(
                    username.encode('utf-8'),
                    valid_username.encode('utf-8'),
                )
                pass_ok = hmac.compare_digest(
                    hashlib.sha256(password.encode('utf-8')).hexdigest(),
                    hashlib.sha256(valid_password.encode('utf-8')).hexdigest(),
                )
                if user_ok and pass_ok:
                    st.session_state['authenticated'] = True
                    st.session_state['user'] = username
                    st.rerun()
                else:
                    st.error('Invalid username or password')

    return False


def main() -> None:
    st.set_page_config(
        page_title='CloudAge — Data Intelligence',
        page_icon='☁️',
        layout='centered',
        initial_sidebar_state='expanded',
    )

    _inject_custom_css()

    # ── Always render sidebar (logo + connectors visible even before login) ──
    _render_sidebar()

    # ── Login gate ──
    if not _check_login():
        return

    # Initialize state
    if 'messages' not in st.session_state:
        st.session_state['messages'] = []

    # Show hero or chat history
    if not st.session_state['messages']:
        _render_hero()
        _render_suggestions()
    else:
        # Compact header in chat mode — show logo
        logo_uri = _get_logo_b64()
        if logo_uri:
            st.markdown(
                f'<div class="chat-header">'
                f'<img src="{logo_uri}" alt="CloudAge"/>'
                f'</div>',
                unsafe_allow_html=True,
            )

        # Render chat history
        for msg in st.session_state['messages']:
            role = msg['role']
            content = msg['content']
            with st.chat_message(role):
                st.markdown(content)

    # Handle pending question from suggestion buttons
    pending = st.session_state.pop('pending_question', None)
    question = pending or st.chat_input("Ask Bigger Questions")

    if not question:
        return

    # Add user message
    st.session_state['messages'].append({'role': 'user', 'content': question})
    with st.chat_message('user'):
        st.markdown(question)

    # Generate response
    with st.chat_message('assistant'):
        thinking = st.empty()
        thinking.markdown(
            '<span style="color:#64748B; font-size:0.85rem;">'
            '🔍 Analyzing your question and generating SQL…</span>',
            unsafe_allow_html=True,
        )
        try:
            answer = _ask(question)
            thinking.empty()
            st.markdown(answer)
            st.session_state['messages'].append(
                {'role': 'assistant', 'content': answer}
            )
        except Exception as exc:
            thinking.empty()
            err_msg = f"⚠️ **Error:** {exc}"
            st.markdown(err_msg)
            st.session_state['messages'].append(
                {'role': 'assistant', 'content': err_msg}
            )


if __name__ == '__main__':
    main()
