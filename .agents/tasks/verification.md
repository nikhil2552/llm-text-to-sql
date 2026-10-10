# Verification — Deployment Reliability Bug Fixes

Iteration: FIRST (no `review.json` present). All five fixes implemented per `plan.md`.

## What was changed

1. **Data seeding** — New `scripts/seed_s3_data.sh` (reusable, idempotent,
   bash-3.2 safe). Uploads `POC/data/s3_cars_data_normalized.csv` → `cars-data/`
   and `POC/data/s3_library_data.json` → `library-data/`, only if the local
   files exist (warns otherwise, never aborts). Takes bucket as `$1` with
   `PRIMARY_DATA_BUCKET_NAME` env fallback. Called from the `--auto` path of
   `deploy-changeset.sh` immediately after "Stack complete" and before the
   image push / crawler run. `scripts/setup.sh` stale commented upload lines
   corrected to point at `POC/data/` with `cars-data/` and `library-data/`
   prefixes and the normalized CSV.
2. **Crawlers created** — `deploy-changeset.sh` now sets `CreateCrawlers` via
   `CREATE_CRAWLERS_PARAM` (`true` under `--auto`, `false` in review mode).
   Sequence: deploy (CreateCrawlers=true) → seed data → run crawlers. The
   first-deploy `DesiredCount=0` CREATE logic is untouched.
3. **Lambda duplicate catalog** — `lambda/s3_trigger_crawler/handler.py` adds a
   `KNOWN_PREFIXES` map pinning `cars-data`→(`project_cars_db`,
   `project-cars-crawler`) and `library-data`→(`project_library_db`,
   `project-library-crawler`). For known prefixes it STARTs the existing CFN
   crawler and skips create (fallback to create only if the CFN crawler is
   missing). Unknown prefixes keep the generic `_sanitize_name` path unchanged.
   Comments + docstring updated.
4. **Athena workgroup detection** — `scripts/detect_existing_resources.sh` now
   reports `CREATE_ATHENA=false` only when `get-work-group` returns
   `WorkGroup.State == ENABLED`; missing/deleted → `true`. Template's
   `ProjectAthenaWorkgroup` OutputLocation confirmed as
   `s3://${PrimaryDataBucketName}/athenaresults/`.
5. **Streamlit username** — `deploy-changeset.sh` defaults
   `STREAMLIT_USERNAME` to `admin` when unset. Streamlit blank-credential
   guard and `core.py` allowlist guard NOT touched.

Also fixed the latent bash-4 `${CHANGE_SET_TYPE,,}` in the review-mode help
string using `tr`-based lowercasing (bash-3.2 safe).

Template (`cloudformation-template-validated.yml`), `src/llm_sql/core.py`, and
`scripts/streamlit_app.py` were NOT modified.

## Commands run (no AWS calls, no real deploy)

- `make check` → `python3 -m compileall src scripts lambda POC/run_smoke.py` — **PASS** (exit 0)
- `make prod-check` (check + test + smoke):
  - unit tests: `Ran 127 tests ... OK`
  - smoke: `python3 POC/run_smoke.py` — "Smoke test completed successfully."
- `bash -n deploy-changeset.sh` — OK
- `bash -n scripts/setup.sh` — OK
- `bash -n scripts/detect_existing_resources.sh` — OK
- `bash -n scripts/seed_s3_data.sh` — OK
- `python3 -m py_compile lambda/s3_trigger_crawler/handler.py` — OK
- Residual checks: `grep ',,}' deploy-changeset.sh` → none; `grep 'data/s3_cars_data.csv' scripts/setup.sh` → none.

All verification passed. No AWS credentials were exercised.
