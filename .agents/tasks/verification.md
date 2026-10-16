# Verification — GitHub CI/CD opt-in flow (`--with-cicd` builds on GitHub, no local Docker)

Scope: `deploy-changeset.sh`, `README.md`. `cloudformation-github-oidc.yml` verified only
(no change). No real AWS or GitHub calls were made.

## 1. Shell syntax check (`bash -n`)

Command:
```
bash -n deploy-changeset.sh
```
Result: **PASS** — prints `SYNTAX_OK`, exit 0. Re-run after every edit; still passes.

## 2. Git-remote parse function — throwaway harness

A temporary harness (`/tmp/test_parse_slug.sh`) copied the `detect_github_slug` parse logic
(parameterized to read the URL from `TEST_URL` instead of calling `git`) and asserted the
expected owner/repo for each URL form, then asserted the fail-fast (empty/non-GitHub) cases.

Run under `bash 3.2.57(1)-release (arm64-apple-darwin26)`:
```
PASS  'https://github.com/acme/widgets.git'  -> owner=acme repo=widgets
PASS  'https://github.com/acme/widgets'       -> owner=acme repo=widgets
PASS  'git@github.com:acme/widgets.git'       -> owner=acme repo=widgets
PASS  'https://github.com/acme/widgets/'      -> owner=acme repo=widgets   (trailing slash)
PASS  'git@github.com:acme/widgets'           -> owner=acme repo=widgets
PASS  'ssh://git@github.com/acme/widgets.git' -> owner=acme repo=widgets
PASS  ''                                      -> correctly rejected (empty org/repo)
PASS  'https://gitlab.com/acme/widgets.git'   -> correctly rejected (non-GitHub)
ALL TESTS PASSED
```
The four required URL forms (HTTPS `.git`, HTTPS no-suffix, SSH `.git`, trailing-slash) all
yield `owner=acme repo=widgets`; empty/non-GitHub input yields empty org/repo (the fail-fast
case used by the `--with-cicd` gate). Harness **deleted** after it passed (`rm -f
/tmp/test_parse_slug.sh`).

## 3. Anti-regression greps (no bash-4-isms, no hardcoded author repo)

Commands and results (all empty = PASS):
```
grep -rn ',,}'  deploy-changeset.sh   -> none
grep -rn '\^\^}' deploy-changeset.sh  -> none
grep -rn 'huraisturkey' deploy-changeset.sh -> none
```
(Note: an earlier run matched `,,}` inside a code comment that spelled out the forbidden
expansion; the comment was reworded so the literal pattern no longer appears anywhere.)

README forbidden-word / hardcoded-repo scans (all empty = PASS):
```
grep -niE 'training|instructor|candidate|student|learner' README.md       -> none
grep -nE  'huraisturkey-lang/Ai_Agent' README.md                          -> none
```

## 4. Project gate — `make prod-check`

Command:
```
make prod-check
```
Result: **PASS**
- `make check` — `python -m compileall` succeeded (no output errors).
- `make test` — `Ran 127 tests in 1.745s` → `OK`.
- `make smoke` — `POC/run_smoke.py` → `Smoke test completed successfully.`

## 5. OIDC template verification (no change)

`cloudformation-github-oidc.yml` already declares `GitHubOrg` / `GitHubRepo` params and the
role trust `StringLike` uses `!Sub "repo:${GitHubOrg}/${GitHubRepo}:*"`. Passing
`--parameter-overrides GitHubOrg=.. GitHubRepo=..` scopes the trust to the detected repo
with no template edit. Thumbprint logic and role permission policies left untouched.

## Summary

All checks pass. `bash -n` clean; parse function correct for all four URL forms + fail-fast;
no bash-4 constructs; no hardcoded author repo as a functional default; README free of the
banned words and the hardcoded clone URL; `make prod-check` green (127 tests + smoke). No
AWS/GitHub network calls were made.
