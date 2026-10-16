# ─────────────────────────────────────────────────────────────────────────────
# Makefile — Task runner for CloudAge Data Architecture project
#
# This file provides short, memorable commands for common tasks.
# Usage: make <target>
#
# Available targets:
#   make check       — Compile-check all Python code (catches syntax errors)
#   make test        — Run unit tests
#   make smoke       — Run smoke test (local data, no AWS calls)
#   make prod-check  — All three above in sequence (CI gate)
#   make ui          — Start the Streamlit chat UI
#   make deploy      — Review mode: show what CloudFormation will change
#   make deploy-all  — Full auto: deploy stack + build image + start service
#   make teardown    — Destroy all AWS infrastructure
#   make setup       — Create virtualenv and install dependencies
#   make venv        — Same as setup (ensure .venv exists)
# ─────────────────────────────────────────────────────────────────────────────

PYTHON ?= python3
VENV := .venv
VENV_PYTHON := $(VENV)/bin/python3

.PHONY: check test smoke prod-check ui deploy deploy-all setup venv teardown

# Create virtual environment and install dependencies
venv:
	@test -x $(VENV_PYTHON) || $(PYTHON) -m venv --clear $(VENV)
	$(VENV_PYTHON) -m pip install -q --upgrade pip
	$(VENV_PYTHON) -m pip install -q -r requirements-dev.txt

# Compile-check all Python code (catches syntax errors fast)
check:
	$(PYTHON) -m compileall src scripts lambda POC/run_smoke.py

# Run unit tests
test: venv
	PYTHONPATH=src $(VENV_PYTHON) -m unittest discover -s tests -p "test_*.py" -v

# Run smoke test — loads local data, no AWS calls
smoke:
	$(PYTHON) POC/run_smoke.py

# Full production gate: compile + test + smoke (used by CI)
prod-check: check test smoke

# Start the Streamlit chat UI (installs deps into .venv first)
ui: venv
	PYTHONPATH=src $(VENV_PYTHON) -m streamlit run scripts/streamlit_app.py

# Review mode — creates CloudFormation change set and shows summary
deploy:
	./deploy-changeset.sh

# Full auto — deploy stack + build Docker image + push to ECR + start ECS
deploy-all:
	./deploy-changeset.sh --auto

# Create virtualenv and install dependencies
setup:
	./scripts/setup.sh

# Tear down all AWS infrastructure (asks for confirmation)
teardown:
	./scripts/teardown.sh
